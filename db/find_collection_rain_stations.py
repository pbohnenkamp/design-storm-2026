#!/usr/bin/env python3
"""Find the NOAA rain gauges inside Denver Water's South System collection areas.

    .venv/bin/python db/apply_schema.py
    .venv/bin/python db/load_noaa_stations.py
    .venv/bin/python db/find_collection_rain_stations.py

Replaces the rows of collection_area_rain_station with every station in
noaa_station that
  1. lies inside one of the South Platte, Chatfield, Bear Creek, or Upper Blue
     collection areas (on the boundary or outside counts as out), and
  2. reported precipitation (GHCN element PRCP) from START to END.

The boundaries are Denver Water's Collection System layer on ArcGIS Online,
fetched once into strontia-brief/basins/dw-collection-south.json. Delete that
file to fetch it again. The four areas do not overlap, so a station is in at
most one.

Coverage is checked in two passes. NCEI's ghcnd-inventory.txt gives each
station's first and last PRCP year, which rules out most stations without
downloading their data. The rest are checked day by day through NCEI's Access
Data Service. A station counts as covering the window if its first PRCP report
in the window is within TOLERANCE of START and its last is within TOLERANCE of
END. Gaps in between are allowed; prcp_days records how many days it reported.
"""

import csv
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta

import psycopg
from shapely.geometry import Point, shape
from shapely.prepared import prep

from apply_schema import REPO, database_url

START = date(2022, 4, 1)
END = date(2026, 9, 1)
TOLERANCE = timedelta(days=7)

AREAS = ("South Platte", "Chatfield", "Bear Creek", "Upper Blue")
BOUNDARY_PATH = os.path.join(REPO, "strontia-brief", "basins", "dw-collection-south.json")
BOUNDARY_URL = (
    "https://services.arcgis.com/czCXlxn6hYtK4vdg/arcgis/rest/services/"
    "Denver_Water_Collection_System/FeatureServer/3/query?"
    + urllib.parse.urlencode({
        "where": "SYSTEM IN ({})".format(", ".join(f"'{a}'" for a in AREAS)),
        "outFields": "SYSTEM",
        "outSR": 4326,  # the layer is stored in Colorado State Plane; ask for lat/long
        "f": "geojson",
    })
)
INVENTORY_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-inventory.txt"
ACCESS_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
STATIONS_PER_REQUEST = 25  # keeps the Access Data Service URL and response small


def fetch(url):
    with urllib.request.urlopen(url, timeout=300) as resp:
        return resp.read()


def load_areas():
    if not os.path.exists(BOUNDARY_PATH):
        with open(BOUNDARY_PATH, "wb") as f:
            f.write(fetch(BOUNDARY_URL))
        print(f"Fetched {os.path.relpath(BOUNDARY_PATH, REPO)}.")
    with open(BOUNDARY_PATH) as f:
        features = json.load(f)["features"]
    areas = {f["properties"]["SYSTEM"]: shape(f["geometry"]) for f in features}
    missing = set(AREAS) - set(areas)
    if missing:
        sys.exit(f"{BOUNDARY_PATH} has no polygon for {', '.join(sorted(missing))}.")
    return areas


def stations_inside(conn, areas):
    """Station id -> collection area, for stations strictly inside an area."""
    west, south, east, north = (
        min(a.bounds[0] for a in areas.values()), min(a.bounds[1] for a in areas.values()),
        max(a.bounds[2] for a in areas.values()), max(a.bounds[3] for a in areas.values()),
    )
    rows = conn.execute(
        "SELECT station, longitude, latitude FROM noaa_station "
        "WHERE longitude BETWEEN %s AND %s AND latitude BETWEEN %s AND %s",
        (west, east, south, north),
    ).fetchall()
    prepared = {name: prep(poly) for name, poly in areas.items()}
    inside = {}
    for station, lon, lat in rows:
        point = Point(lon, lat)
        for name, poly in prepared.items():
            if poly.contains(point):  # contains() is False on the boundary itself
                inside[station] = name
                break
    return inside


def prcp_years(stations):
    """Station id -> (first year, last year) of PRCP, from ghcnd-inventory.txt.

    Layout is section VII of NCEI's GHCN Daily readme.txt: id in columns 1-11,
    element 32-35, first year 37-40, last year 42-45.
    """
    years = {}
    for line in fetch(INVENTORY_URL).decode("ascii").splitlines():
        station, element = line[0:11], line[31:35]
        if element == "PRCP" and station in stations:
            years[station] = (int(line[36:40]), int(line[41:45]))
    return years


def prcp_dates(stations):
    """Station id -> sorted dates with a PRCP value between START and END."""
    dates = {s: [] for s in stations}
    stations = sorted(stations)
    for i in range(0, len(stations), STATIONS_PER_REQUEST):
        batch = stations[i:i + STATIONS_PER_REQUEST]
        query = urllib.parse.urlencode({
            "dataset": "daily-summaries",
            "stations": ",".join(batch),
            "startDate": START.isoformat(),
            "endDate": END.isoformat(),
            "dataTypes": "PRCP",
            "format": "csv",
        })
        text = fetch(f"{ACCESS_URL}?{query}").decode("utf-8")
        for row in csv.DictReader(io.StringIO(text)):
            if row.get("PRCP", "").strip():
                dates[row["STATION"]].append(date.fromisoformat(row["DATE"]))
    return {s: sorted(d) for s, d in dates.items()}


def main():
    areas = load_areas()
    with psycopg.connect(database_url()) as conn:  # one transaction: all rows or none
        inside = stations_inside(conn, areas)
        if not inside:
            sys.exit("No stations in noaa_station fall inside the areas. "
                     "Run db/load_noaa_stations.py first.")

        years = prcp_years(inside)
        candidates = [s for s, (first, last) in years.items()
                      if first <= START.year and last >= END.year]
        dates = prcp_dates(candidates)

        rows = []
        for station in candidates:
            d = dates[station]
            if d and d[0] <= START + TOLERANCE and d[-1] >= END - TOLERANCE:
                rows.append((station, inside[station], d[0], d[-1], len(d)))

        conn.execute("DELETE FROM collection_area_rain_station")
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO collection_area_rain_station "
                "(station, collection_area, first_prcp_on, last_prcp_on, prcp_days) "
                "VALUES (%s, %s, %s, %s, %s)",
                rows,
            )

    window_days = (END - START).days + 1
    print(f"{len(inside)} stations inside the areas, {len(years)} ever reported "
          f"precipitation, {len(candidates)} did in both {START.year} and {END.year}, "
          f"{len(rows)} cover {START} to {END}.")
    for area in AREAS:
        mine = sorted(r for r in rows if r[1] == area)
        print(f"\n{area}: {len(mine)}")
        for station, _, first, last, days in mine:
            print(f"  {station}  {first} to {last}  {days}/{window_days} days")


if __name__ == "__main__":
    main()
