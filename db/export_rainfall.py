#!/usr/bin/env python3
"""Export the collection-area rain gauges to a long-format rainfall.csv.

    .venv/bin/python db/export_rainfall.py [output.csv]

Reads noaa_daily_weather and collection_area_rain_station (see schema.sql).
Writes experiments/rainfall.csv by default, with columns

    timestamp    observation day, ISO date (GHCN Daily's logging interval)
    gauge_id     GHCN station id
    rainfall_in  PRCP for that day, inches, incremental (not cumulative)

one row per gauge per day, sorted by gauge then day. A day with no PRCP value
(not reported, or failed NCEI's quality checks) has no row; zeros in the file
are reported zeros or traces, never filled gaps. The gaps per gauge are printed.

A GHCN "day" ends at each observer's reading time (often 7 a.m. for CoCoRaHS
gauges), not midnight, so the same date can cover different 24 hours at
different gauges.

NOAA GHCN Daily values are provisional and revised after publication.
USC00058022 rows may come from Denver Water's data/USC00058022.csv, so keep
data/TERMS.md with this file.
"""

import csv
import os
import sys
from datetime import timedelta

import psycopg

from apply_schema import REPO, database_url

DEFAULT_OUT = os.path.join(REPO, "experiments", "rainfall.csv")

QUERY = """
SELECT w.station, w.observed_on, w.prcp_in
FROM noaa_daily_weather w
JOIN collection_area_rain_station a USING (station)
WHERE w.prcp_in IS NOT NULL
ORDER BY 1, 2
"""


def gaps(days):
    """Runs of missing days between the first and last reported day."""
    runs = []
    for prev, cur in zip(days, days[1:]):
        if cur - prev > timedelta(days=1):
            runs.append((prev + timedelta(days=1), cur - timedelta(days=1)))
    return runs


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    with psycopg.connect(database_url()) as conn:
        rows = conn.execute(QUERY).fetchall()
    if not rows:
        sys.exit("No rainfall rows. Load the data with db/load_noaa_access.py first.")

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["timestamp", "gauge_id", "rainfall_in"])
        for station, day, prcp in rows:
            w.writerow([day.isoformat(), station, f"{prcp:.2f}"])

    by_gauge = {}
    for station, day, _ in rows:
        by_gauge.setdefault(station, []).append(day)
    print(f"Wrote {len(rows)} rows for {len(by_gauge)} gauges to {os.path.relpath(out, REPO)}.\n")
    print(f"{'gauge':<12} {'first':<10} {'last':<10} {'days':>5} {'missing':>7} {'gaps':>4}  longest gap")
    for station, days in by_gauge.items():
        span = (days[-1] - days[0]).days + 1
        runs = gaps(days)
        longest = max(runs, key=lambda r: r[1] - r[0], default=None)
        longest_text = (f"{longest[0]} to {longest[1]} ({(longest[1] - longest[0]).days + 1} d)"
                        if longest else "")
        print(f"{station:<12} {days[0]} {days[-1]} {len(days):>5} {span - len(days):>7} "
              f"{len(runs):>4}  {longest_text}")


if __name__ == "__main__":
    main()
