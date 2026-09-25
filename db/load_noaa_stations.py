#!/usr/bin/env python3
"""Load NOAA's GHCN Daily station list into noaa_station.

    .venv/bin/python db/apply_schema.py
    .venv/bin/python db/load_noaa_stations.py [url-or-path]

Downloads ghcnd-stations.txt from NCEI by default (about 11 MB, every station
worldwide); pass a local path to load a saved copy instead. The file is fixed
width; the layout is section IV of
https://www.ncei.noaa.gov/pub/data/ghcn/daily/readme.txt.

Rerunning is safe. Unlike the measurement loaders, this one updates stations
already loaded, because NOAA revises station metadata.
"""

import os
import sys
import urllib.request

import psycopg

from apply_schema import REPO, database_url

DEFAULT_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily/ghcnd-stations.txt"

# Table column -> 1-based inclusive columns from the readme. The columns count
# bytes: a line with an accented name is still 85 bytes, but fewer characters,
# so slice the bytes before decoding.
FIELDS = {
    "station": (1, 11),
    "latitude": (13, 20),
    "longitude": (22, 30),
    "elevation_m": (32, 37),
    "state": (39, 40),
    "name": (42, 71),
    "gsn_flag": (73, 75),
    "hcn_crn_flag": (77, 79),
    "wmo_id": (81, 85),
}
NUMERIC = {"latitude", "longitude", "elevation_m"}
MISSING_ELEVATION = -999.9


def read_bytes(source):
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source) as resp:
            return resp.read()
    with open(source, "rb") as f:
        return f.read()


def parse(line):
    row = {}
    for col, (start, end) in FIELDS.items():
        text = line[start - 1:end].decode("utf-8").strip()
        if col in NUMERIC:
            row[col] = float(text)
        else:
            row[col] = text or None
    if row["elevation_m"] == MISSING_ELEVATION:
        row["elevation_m"] = None
    return tuple(row.values())


def read_rows(source):
    for line_no, line in enumerate(read_bytes(source).splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield parse(line)
        except (ValueError, UnicodeDecodeError) as e:
            sys.exit(f"{source} line {line_no}: {e}: {line!r}")


def main():
    source = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    rows = list(read_rows(source))
    cols = list(FIELDS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols[1:])
    insert = (
        f"INSERT INTO noaa_station ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT (station) DO UPDATE SET {updates}"
    )
    count = "SELECT count(*) FROM noaa_station"
    with psycopg.connect(database_url()) as conn:  # one transaction: all rows or none
        before = conn.execute(count).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(insert, rows)
        after = conn.execute(count).fetchone()[0]
    print(f"Read {len(rows)} stations from {source}: "
          f"{after - before} new, {len(rows) - (after - before)} updated. "
          f"Table now has {after} rows.")


if __name__ == "__main__":
    main()
