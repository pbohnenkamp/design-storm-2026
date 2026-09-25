#!/usr/bin/env python3
"""Load the Foothills influent lab results into foothills_influent.

    .venv/bin/python db/apply_schema.py
    .venv/bin/python db/load_foothills.py [path/to/file.csv]

Reads data/FoothillsInfluent.csv by default: one row per day, TOC and
alkalinity in mg/L, dates as M/D/YYYY.

Rerunning is safe. Rows are keyed by sample_date, and dates already loaded
are skipped, not duplicated or updated. Values are stored as recorded; see
data/TERMS.md for the data's terms.
"""

import csv
import os
import sys
from datetime import datetime

import psycopg

from apply_schema import REPO, database_url

DEFAULT_CSV = os.path.join(REPO, "data", "FoothillsInfluent.csv")

# CSV header -> table column, in file order.
COLUMNS = {
    "DATE": "sample_date",
    "TOC_mg_L": "toc_mg_l",
    "Alk_mg_L": "alk_mg_l",
}


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
                date, toc, alk = (v.strip() for v in values)
                yield (datetime.strptime(date, "%m/%d/%Y").date(), float(toc), float(alk))
            except ValueError as e:
                sys.exit(f"{path} line {line_no}: {e}: {values}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    rows = list(read_rows(path))
    cols = list(COLUMNS.values())
    insert = (
        f"INSERT INTO foothills_influent ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) "
        "ON CONFLICT (sample_date) DO NOTHING"
    )
    count = "SELECT count(*) FROM foothills_influent"
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
