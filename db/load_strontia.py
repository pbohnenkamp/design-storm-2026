#!/usr/bin/env python3
"""Load the Strontia Springs sonde readings into strontia_sonde_reading.

    .venv/bin/python db/apply_schema.py
    .venv/bin/python db/load_strontia.py [path/to/file.xlsx]

Reads data/Strontia 0407_0819.xlsx by default. The xlsx, not the CSV export:
the CSV truncates timestamps to the minute, the xlsx keeps seconds.

Rerunning is safe. Rows are keyed by their spreadsheet row number
(source_row), and rows already loaded are skipped, not duplicated or updated.
Values are stored as recorded; see data/TERMS.md for the data's terms.
"""

import os
import sys

import openpyxl
import psycopg

from apply_schema import REPO, database_url

DEFAULT_XLSX = os.path.join(REPO, "data", "Strontia 0407_0819.xlsx")

# Spreadsheet header (stripped of trailing spaces) -> table column, in file order.
COLUMNS = {
    "Time stamp": "measured_at",
    "Temp C": "temp_c",
    "Conductivity": "conductivity",
    "Vertical Position": "vertical_position",
    "pH": "ph",
    "ORP mV": "orp_mv",
    "Turbidity NTU": "turbidity_ntu",
    "Chl ug/L": "chlorophyll_ug_l",
    "Phycocyanin": "phycocyanin",
    "ODO & sat": "odo_pct_sat",
    "ODO mg/L": "odo_mg_l",
}


def read_rows(path):
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = wb.active.iter_rows(values_only=True)
    header = [str(h).strip() if h is not None else "" for h in next(rows)]
    if header != list(COLUMNS):
        sys.exit(f"Unexpected header in {path}:\n  got      {header}\n  expected {list(COLUMNS)}")
    # Row 1 is the header, so data starts at spreadsheet row 2.
    for source_row, values in enumerate(rows, start=2):
        if all(v is None for v in values):
            continue
        yield (source_row, *values)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    rows = list(read_rows(path))
    cols = ["source_row", *COLUMNS.values()]
    insert = (
        f"INSERT INTO strontia_sonde_reading ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))}) "
        "ON CONFLICT (source_row) DO NOTHING"
    )
    count = "SELECT count(*) FROM strontia_sonde_reading"
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
