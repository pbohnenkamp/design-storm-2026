#!/usr/bin/env python3
"""Build the rainfall-to-TOC program's input files from the database.

    .venv/bin/python db/build_inputs.py
        [--out DIR] [--gauges ID,ID,...] [--fill-nearest] [--zero-below-tmin F]
        [--season MM-DD:MM-DD] [--end YYYY-MM-DD]

By default it writes to experiments/rainfall_toc_prediction and uses every
catchment gauge with no missing day. --gauges picks the gauges instead; --fill-nearest fills a chosen
gauge's missing day from the nearest catchment gauge that reported that day,
and lists every fill in reference/filled_days.csv. --zero-below-tmin sets a chosen
gauge's precipitation to 0 on days its own TMIN is below F degrees Fahrenheit,
before any fill, and summarises what it removed in reference/tmin_rule_summary.csv;
a day with no TMIN keeps its value. --season keeps only TOC samples inside that
window each year, keeps real rain from LEAD before the window to its end, and
writes every other day as 0 (the program needs every day, and those days sit
more than LEAD before any kept sample). --end trains on nothing after that date:
rainfall.csv and toc.csv stop there, new_rainfall.csv covers the later samples
with LOOKBACK of history, and their measured TOC goes to reference/toc_after_end.csv
for scoring the predictions. --out writes elsewhere.

Formats follow the program's GETTING_STARTED.md (section 4), which supersedes the
formats in the "Multi-Gauge Rainfall-to-TOC Design" doc. Writes, into --out:

  data/rainfall.csv      date + one column per gauge, daily inches. Only catchment gauges
                         with every day reported: the program rejects blanks and skipped
                         days, and a gap is not a zero.
  data/new_rainfall.csv  same format and gauges; the days after the last TOC sample plus LOOKBACK
  data/gauges.csv        gauge_id, lat, lon; exactly the gauges in rainfall.csv
  data/toc.csv           date, toc_mg_per_L; Foothills plant influent, from LEAD after the
                         first rain day, so every sample has 3 weeks of earlier rain
  reference/gauge_registry.csv  every gauge with data, why it is in or out, and its gaps
  reference/catchment.geojson   USGS NLDI basin draining to gage 06707525, above Strontia Springs

  config.yaml            a copy of rainfall_toc_config.yaml beside this script, which is
                         hand-written: the TOC point and starting velocity

Sources: noaa_daily_weather, noaa_station, collection_area_rain_station and
foothills_influent (see db/schema.sql); strontia-brief/basins/*.json and
strontia-brief/places.json. Foothills TOC is Denver Water provisional data and
NOAA GHCN Daily values are provisional too, so TERMS.md travels with the output.
"""

import argparse
import csv
import json
import math
import os
import shutil
import sys
from collections import defaultdict
from datetime import date, timedelta

import psycopg
from shapely.geometry import Point, shape

from apply_schema import REPO, database_url

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(REPO, "experiments", "rainfall_toc_prediction")
CONFIG = os.path.join(HERE, "rainfall_toc_config.yaml")

BASINS = os.path.join(REPO, "strontia-brief", "basins")
CATCHMENT = os.path.join(BASINS, "south-platte-above-strontia-06707525.json")
TRUMBULL = os.path.join(BASINS, "south-platte-above-trumbull-06701900.json")
PLACES = os.path.join(REPO, "strontia-brief", "places.json")

LOOKBACK = timedelta(days=30)  # history new_rainfall.csv carries before the first prediction day
LEAD = timedelta(days=21)  # rain the program needs before a TOC sample (GETTING_STARTED 4.1)
EARTH_RADIUS_FT = 6371008.8 / 0.3048
NETWORK = {"US1": "CoCoRaHS", "USC": "NWS COOP", "USS": "NRCS SNOTEL"}

GAUGES_SQL = """
SELECT a.station, s.name, a.collection_area, s.latitude, s.longitude, s.elevation_m
FROM collection_area_rain_station a JOIN noaa_station s USING (station)
ORDER BY a.station
"""
RAIN_SQL = """
SELECT w.station, w.observed_on, w.prcp_in
FROM noaa_daily_weather w JOIN collection_area_rain_station a USING (station)
WHERE w.prcp_in IS NOT NULL
ORDER BY w.observed_on, w.station
"""
TMIN_SQL = "SELECT station, observed_on, tmin_f FROM noaa_daily_weather WHERE tmin_f IS NOT NULL"
TOC_SQL = "SELECT sample_date, toc_mg_l FROM foothills_influent ORDER BY sample_date"


def polygon(path):
    with open(path) as f:
        return shape(json.load(f)["features"][0]["geometry"])


def toc_point():
    """Conduit 26 intake at Strontia Springs Dam, where Foothills draws its water."""
    with open(PLACES) as f:
        p = json.load(f)["facilities"]["conduit_26_intake"]
    return p["lat"], p["lon"]


def great_circle_ft(lat, lon, lat0, lon0):
    p1, p2 = math.radians(lat0), math.radians(lat)
    dp, dl = p2 - p1, math.radians(lon - lon0)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_FT * math.asin(math.sqrt(a))


def resolution(values):
    """Coarsest step every nonzero reading is a multiple of: 0.1 or 0.01 inch."""
    nonzero = [v for v in values if v > 0]
    if nonzero and all(abs(v * 10 - round(v * 10)) < 1e-6 for v in nonzero):
        return 0.1
    return 0.01


def fill_nearest(days_by_gauge, ids, coords, candidates, start, end):
    """Fill each chosen gauge's missing days from the nearest candidate reporting that day.

    Returns the fills as rows for reference/filled_days.csv; days_by_gauge is updated in place.
    """
    fills = []
    for i in ids:
        donors = sorted((c for c in candidates if c != i),
                        key=lambda c: great_circle_ft(*coords[c], *coords[i]))
        d = start
        while d <= end:
            if d not in days_by_gauge[i]:
                donor = next((c for c in donors if d in days_by_gauge[c]), None)
                if donor is None:
                    sys.exit(f"No catchment gauge reported on {d} to fill {i}.")
                days_by_gauge[i][d] = days_by_gauge[donor][d]
                miles = great_circle_ft(*coords[donor], *coords[i]) / 5280
                fills.append([d.isoformat(), i, f"{days_by_gauge[i][d]:.2f}", donor, f"{miles:.1f}"])
            d += timedelta(days=1)
    return fills


def wide_rows(days_by_gauge, ids, start, end):
    """One row per day from start to end: date, then each gauge's inches. Fails on any gap."""
    rows = []
    d = start
    while d <= end:
        missing = [i for i in ids if d not in days_by_gauge[i]]
        if missing:
            sys.exit(f"No rainfall for {', '.join(missing)} on {d}; a gap cannot be written as zero.")
        rows.append([d.isoformat()] + [f"{days_by_gauge[i][d]:.2f}" for i in ids])
        d += timedelta(days=1)
    return rows


def write_csv(path, header, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {os.path.relpath(path, REPO)}: {len(rows)} rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", default=DEFAULT_OUT,
                        help="folder to write into (default: experiments/rainfall_toc_prediction)")
    parser.add_argument("--gauges", help="comma-separated gauge ids (default: complete catchment gauges)")
    parser.add_argument("--fill-nearest", action="store_true",
                        help="fill missing days from the nearest catchment gauge reporting that day")
    parser.add_argument("--zero-below-tmin", type=float, metavar="F",
                        help="set precipitation to 0 on days the gauge's TMIN is below F (Fahrenheit)")
    parser.add_argument("--season", metavar="MM-DD:MM-DD",
                        help="keep TOC inside this window each year; rain outside it (less LEAD) is 0")
    parser.add_argument("--end", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="last day to train on; later TOC becomes the prediction check")
    args = parser.parse_args()
    out = os.path.abspath(args.out)

    with psycopg.connect(database_url()) as conn:
        stations = conn.execute(GAUGES_SQL).fetchall()
        rain = conn.execute(RAIN_SQL).fetchall()
        toc = conn.execute(TOC_SQL).fetchall()
        tmin = {(s, d): t for s, d, t in conn.execute(TMIN_SQL)}

    catchment, trumbull = polygon(CATCHMENT), polygon(TRUMBULL)
    lat0, lon0 = toc_point()
    last_toc = toc[-1][0]
    first_toc = toc[0][0]

    days_by_gauge = defaultdict(dict)
    for station, day, prcp in rain:
        days_by_gauge[station][day] = prcp

    # Gauge registry.
    gauges, no_data = [], []
    for station, name, area, lat, lon, elev in stations:
        days = days_by_gauge[station]
        if not days:  # db/load_noaa_access.py skips SNOTEL sites
            no_data.append(station)
            continue
        inside = catchment.contains(Point(lon, lat))
        if inside:
            reason = ""
        elif area == "Upper Blue":
            reason = "outside catchment; reaches it only through Dillon Reservoir and Roberts Tunnel"
        elif area == "Chatfield":
            reason = "outside catchment; drains to the South Platte below the TOC point"
        elif area == "Bear Creek":
            reason = "outside catchment; Bear Creek drainage, does not reach the TOC point"
        elif station == "USC00058022":
            reason = ("outside catchment by 1.8 km: at Strontia Springs Dam, below outlet gage 06707525; "
                      "rain here falls on the reservoir itself")
        else:
            reason = "outside catchment"
        train_days = [d for d in days if first_toc <= d <= last_toc]
        span = (last_toc - first_toc).days + 1
        gauges.append({
            "gauge_id": station,
            "name": name,
            "network": NETWORK.get(station[:3], ""),
            "collection_area": area,
            "lat": f"{lat:.5f}",
            "lon": f"{lon:.5f}",
            "straight_line_ft": round(great_circle_ft(lat, lon, lat0, lon0)),
            "elevation_m": elev,
            "active_from": min(days).isoformat(),
            "active_to": max(days).isoformat(),
            "missing_days_in_toc_period": span - len(train_days),
            "bucket_resolution_in": resolution(days.values()),
            "in_catchment": str(inside).lower(),
            "in_trumbull_basin": str(trumbull.contains(Point(lon, lat))).lower(),
            "include": str(inside).lower(),
            "exclude_reason": reason,
        })

    print(f"Writing to {os.path.relpath(out, REPO)}/")
    included = [g for g in gauges if g["include"] == "true"]
    if args.gauges:
        by_id = {g["gauge_id"]: g for g in gauges}
        unknown = [i for i in args.gauges.split(",") if i not in by_id]
        if unknown:
            sys.exit(f"Unknown or dataless gauge ids: {', '.join(unknown)}")
        chosen = [by_id[i] for i in args.gauges.split(",")]
    else:
        chosen = [g for g in included if g["missing_days_in_toc_period"] == 0]
    ids = [g["gauge_id"] for g in chosen]
    first_rain = max(min(days_by_gauge[i]) for i in ids)
    last_rain = min(max(days_by_gauge[i]) for i in ids)
    usable_toc = [(d, v) for d, v in toc if d >= first_rain + LEAD]
    if args.season:
        (m0, d0), (m1, d1) = (map(int, part.split("-")) for part in args.season.split(":"))

        def in_season(d):
            return date(d.year, m0, d0) <= d <= date(d.year, m1, d1)

        def rain_kept(d):
            return date(d.year, m0, d0) - LEAD <= d <= date(d.year, m1, d1)

        usable_toc = [(d, v) for d, v in usable_toc if in_season(d)]
        off_season = 0
        for i in ids:
            d = first_rain
            while d <= last_rain:
                if not rain_kept(d):
                    days_by_gauge[i][d] = 0.0
                    off_season += 1
                d += timedelta(days=1)
    zeroed = defaultdict(lambda: [0, 0.0, 0])  # (gauge, yyyy-mm) -> days zeroed, inches removed, gaps closed
    if args.zero_below_tmin is not None:
        for i in ids:
            d = first_rain
            while d <= last_rain:
                t = tmin.get((i, d))
                if t is not None and t < args.zero_below_tmin:
                    z = zeroed[(i, d.strftime("%Y-%m"))]
                    z[0] += 1
                    if d in days_by_gauge[i]:
                        z[1] += days_by_gauge[i][d]
                    else:
                        z[2] += 1
                    days_by_gauge[i][d] = 0.0
                d += timedelta(days=1)
    later_toc = []
    if args.end:
        later_toc = [(d, v) for d, v in usable_toc if d > args.end]
        usable_toc = [(d, v) for d, v in usable_toc if d <= args.end]
    last_train = min(args.end, last_toc) if args.end else last_toc
    first_pred = later_toc[0][0] if later_toc else last_train + timedelta(days=1)
    fills = []
    if args.fill_nearest:
        coords = {g["gauge_id"]: (float(g["lat"]), float(g["lon"])) for g in gauges}
        fills = fill_nearest(days_by_gauge, ids, coords, [g["gauge_id"] for g in included],
                             first_rain, last_rain)

    data = os.path.join(out, "data")
    write_csv(os.path.join(data, "rainfall.csv"), ["date"] + ids,
              wide_rows(days_by_gauge, ids, first_rain, last_train))
    write_csv(os.path.join(data, "new_rainfall.csv"), ["date"] + ids,
              wide_rows(days_by_gauge, ids, first_pred - LOOKBACK, last_rain))
    write_csv(os.path.join(data, "gauges.csv"), ["gauge_id", "lat", "lon"],
              [[g["gauge_id"], g["lat"], g["lon"]] for g in chosen])
    write_csv(os.path.join(data, "toc.csv"), ["date", "toc_mg_per_L"],
              [[d.isoformat(), v] for d, v in usable_toc])

    reference = os.path.join(out, "reference")
    if args.end:
        write_csv(os.path.join(reference, "toc_after_end.csv"), ["date", "toc_mg_per_L"],
                  [[d.isoformat(), v] for d, v in later_toc])
    if args.zero_below_tmin is not None:
        write_csv(os.path.join(reference, "tmin_rule_summary.csv"),
                  ["gauge_id", "month", "days_zeroed", "inches_removed", "missing_days_set_to_zero"],
                  [[i, m, z[0], f"{z[1]:.2f}", z[2]] for (i, m), z in sorted(zeroed.items())])
    if args.fill_nearest:
        write_csv(os.path.join(reference, "filled_days.csv"),
                  ["date", "gauge_id", "rainfall_in", "source_gauge", "source_distance_mi"], fills)
    write_csv(os.path.join(reference, "gauge_registry.csv"), list(gauges[0]),
              [list(g.values()) for g in gauges])
    with open(CATCHMENT) as f:
        basin = json.load(f)
    basin["features"][0]["properties"] = {
        "name": "South Platte River above Strontia Springs Reservoir",
        "outlet_usgs_site": "06707525",
        "source": "USGS NLDI basin, strontia-brief/basins/south-platte-above-strontia-06707525.json",
    }
    with open(os.path.join(reference, "catchment.geojson"), "w") as f:
        json.dump(basin, f)
    print(f"  {os.path.relpath(reference, REPO)}/catchment.geojson: 1 polygon")

    shutil.copy(os.path.join(REPO, "data", "TERMS.md"), os.path.join(out, "TERMS.md"))
    shutil.copy(CONFIG, os.path.join(out, "config.yaml"))

    print(f"\nNo rainfall in the database, left out: {', '.join(no_data)}")
    print(f"{len(gauges)} gauges, {len(included)} inside the catchment, "
          f"{sum(g['missing_days_in_toc_period'] == 0 for g in included)} of those complete "
          f"over {first_toc} to {last_toc}. Using {len(ids)}: {', '.join(ids)}.")
    for f in fills:
        print(f"  filled {f[1]} on {f[0]} with {f[2]} in from {f[3]}, {f[4]} mi away")
    print(f"TOC samples: {len(usable_toc)} of {len(toc)} kept, {usable_toc[0][0]} to {usable_toc[-1][0]}"
          + (f", inside {args.season} each year." if args.season else
             f"; the {len(toc) - len(usable_toc)} before {first_rain + LEAD} lack 3 weeks of earlier rain."))
    print(f"new_rainfall.csv: {first_pred - LOOKBACK} to {last_rain}.")
    if args.end:
        print(f"Trained through {last_train}; {len(later_toc)} later TOC samples held for checking predictions.")
    if args.season:
        print(f"Season {args.season}: rain kept from {LEAD.days} days before it; "
              f"{off_season} gauge-days outside written as 0.")
    print(f"\n{'gauge':<12} {'network':<11} {'miles':>5} {'missing':>7} {'res_in':>6} trumbull  name")
    for g in sorted(included, key=lambda g: g["straight_line_ft"]):
        print(f"{g['gauge_id']:<12} {g['network']:<11} {g['straight_line_ft'] / 5280:5.1f} "
              f"{g['missing_days_in_toc_period']:>7} {g['bucket_resolution_in']:>6} "
              f"{g['in_trumbull_basin']:<9} {g['name']}")


if __name__ == "__main__":
    main()
