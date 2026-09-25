#!/usr/bin/env python3
"""Load NOAA GHCN Daily weather into noaa_daily_weather.

    .venv/bin/python db/apply_schema.py
    .venv/bin/python db/load_noaa.py [path/to/file.csv]

Reads data/USC00058022.csv by default: one row per station per day, dates as
M/D/YYYY. Blank cells are missing observations and load as NULL.

Rerunning is safe. Rows are keyed by (station, observed_on), and days already
loaded are skipped, not duplicated or updated. Values are stored as recorded.
"""

import csv
import os
import sys
from datetime import datetime

import psycopg

from apply_schema import REPO, database_url

DEFAULT_CSV = os.path.join(REPO, "data", "USC00058022.csv")

# CSV header -> table column, in file order.
COLUMNS = {
    "STATION": "station",
    "DATE": "observed_on",
    "PRCP": "prcp_in",
    "SNOW": "snow_in",
    "TMAX": "tmax_f",
    "TMIN": "tmin_f",
}


def number(value):
    return float(value) if value else None


def read_rows(path):
    with open(path, newline="") as f:
        rows = csv.reader(f)
        header = [h.strip() for h in next(rows)]
        if header != list(COLUMNS):
            sys.exit(f"Unexpected header in {path}:\n  got      {header}\n  expected {list(COLUMNS)}")
        for line_no, values in enumerate(rows, start=2):
            if not any(v.strip() for v in values):
                continue
            try:
                station, date, *measures = (v.strip() for v in values)
                yield (station, datetime.strptime(date, "%m/%d/%Y").date(),
                       *(number(v) for v in measures))
            except ValueError as e:
                sys.exit(f"{path} line {line_no}: {e}: {values}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    rows = list(read_rows(path))
    cols = list(COLUMNS.values())
    insert = (
        f"INSERT INTO noaa_daily_weather ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) "
        "ON CONFLICT (station, observed_on) DO NOTHING"
    )
    count = "SELECT count(*) FROM noaa_daily_weather"
    with psycopg.connect(database_url()) as conn:  # one transaction: all rows or none
        before = conn.execute(count).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(insert, rows)
        after = conn.execute(count).fetchone()[0]
    print(f"Read {len(rows)} rows from {os.path.relpath(path, REPO)}: "
          f"{after - before} inserted, {len(rows) - (after - before)} already loaded. "
          f"Table now has {after} rows.")


if __name__ == "__main__":
    main()
