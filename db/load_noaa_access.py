#!/usr/bin/env python3
"""Load NCEI's per-station GHCN Daily files into noaa_daily_weather.

    .venv/bin/python db/find_collection_rain_stations.py
    .venv/bin/python db/load_noaa_access.py [STATION ...]

With no arguments, loads every station in collection_area_rain_station except
the SNOTEL sites (ids starting USS). Each station's file is
https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/<id>.csv,
its whole record; only days from START to END are loaded.

The files hold GHCN's raw units, converted here to match data/USC00058022.csv,
which NCEI exported in standard units:
  PRCP  tenths of mm -> inches, 2 decimals
  SNOW  mm           -> inches, 1 decimal
  TMAX, TMIN  tenths of degrees C -> whole degrees F
Each value has an _ATTRIBUTES cell, "MFLAG,QFLAG,SFLAG[,time]" (section III of
NCEI's GHCN Daily readme.txt). A value with a quality flag failed one of NCEI's
checks and loads as NULL. A trace of rain (MFLAG T) is stored by NCEI as 0 and
loads as 0.

Rerunning is safe. Days already loaded are skipped, not updated, so rows from
load_noaa.py keep Denver Water's values.
"""

import csv
import io
import sys
import urllib.request
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import psycopg

from apply_schema import database_url
from find_collection_rain_stations import END, START

ACCESS_URL = "https://www.ncei.noaa.gov/data/global-historical-climatology-network-daily/access/{}.csv"


def half_up(value, places):
    return float(Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


# Element -> (table column, raw text -> value in the table's units).
ELEMENTS = {
    "PRCP": ("prcp_in", lambda v: half_up(Decimal(v) / 254, 2)),
    "SNOW": ("snow_in", lambda v: half_up(Decimal(v) / Decimal("25.4"), 1)),
    "TMAX": ("tmax_f", lambda v: half_up(Decimal(v) * Decimal("0.18") + 32, 0)),
    "TMIN": ("tmin_f", lambda v: half_up(Decimal(v) * Decimal("0.18") + 32, 0)),
}


def default_stations(conn):
    return [s for (s,) in conn.execute(
        "SELECT station FROM collection_area_rain_station "
        "WHERE station NOT LIKE 'USS%' ORDER BY station"
    )]


def read_rows(station):
    """Rows for noaa_daily_weather, and how many values failed quality checks."""
    with urllib.request.urlopen(ACCESS_URL.format(station), timeout=300) as resp:
        text = resp.read().decode("utf-8")
    rows, flagged = [], 0
    for record in csv.DictReader(io.StringIO(text)):
        day = date.fromisoformat(record["DATE"])
        if not START <= day <= END:
            continue
        values = []
        for element, (_, convert) in ELEMENTS.items():
            raw = (record.get(element) or "").strip()
            attributes = (record.get(f"{element}_ATTRIBUTES") or "").split(",")
            qflag = attributes[1].strip() if len(attributes) > 1 else ""
            if raw and qflag:
                flagged += 1
                raw = ""
            values.append(convert(raw) if raw else None)
        rows.append((station, day, *values))
    return rows, flagged


def main():
    cols = ["station", "observed_on"] + [col for col, _ in ELEMENTS.values()]
    insert = (
        f"INSERT INTO noaa_daily_weather ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) "
        "ON CONFLICT (station, observed_on) DO NOTHING"
    )
    count = "SELECT count(*) FROM noaa_daily_weather"
    with psycopg.connect(database_url()) as conn:  # one transaction: all stations or none
        stations = sys.argv[1:] or default_stations(conn)
        if not stations:
            sys.exit("No stations to load. Run db/find_collection_rain_stations.py first.")
        start_count = conn.execute(count).fetchone()[0]
        for station in stations:
            rows, flagged = read_rows(station)
            before = conn.execute(count).fetchone()[0]
            with conn.cursor() as cur:
                cur.executemany(insert, rows)
            inserted = conn.execute(count).fetchone()[0] - before
            print(f"{station}: {len(rows)} days, {inserted} inserted, "
                  f"{len(rows) - inserted} already loaded, {flagged} values failed QC")
        end_count = conn.execute(count).fetchone()[0]
    print(f"\n{len(stations)} stations, {end_count - start_count} rows inserted. "
          f"Table now has {end_count} rows.")


if __name__ == "__main__":
    main()
