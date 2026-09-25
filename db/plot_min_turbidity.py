#!/usr/bin/env python3
"""Plot the depth of each cast's lowest turbidity reading over time.

    .venv/bin/python db/plot_min_turbidity.py [output.png]

Reads strontia_cast_reading (see schema.sql), so run apply_schema.py and
load_strontia.py first. Writes experiments/strontia_min_turbidity.png by default.

One dot per cast, placed at the Vertical Position of its lowest Turbidity NTU.
When several readings in a cast tie for the lowest, the shallowest is used.
Casts that covered less than SHALLOW_RANGE of the water column are drawn hollow:
their minimum is only the lowest of the depths they reached. The line joins
full-depth casts and breaks where no cast was recorded for more than a day.

The readings are provisional Denver Water data; see data/TERMS.md before
sharing the figure.
"""

import os
import sys
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import psycopg

from apply_schema import REPO, database_url

DEFAULT_OUT = os.path.join(REPO, "experiments", "strontia_min_turbidity.png")
SHALLOW_RANGE = 20  # vertical-position span below which a cast counts as shallow-only
LINE_BREAK = timedelta(days=1)

# One row per cast: its lowest-turbidity reading, ties broken by shallowest.
QUERY = """
SELECT DISTINCT ON (cast_no)
    cast_no,
    cast_at,
    measured_at,
    vertical_position,
    turbidity_ntu,
    max(vertical_position) OVER w - min(vertical_position) OVER w AS cast_range
FROM strontia_cast_reading
WHERE turbidity_ntu IS NOT NULL
WINDOW w AS (PARTITION BY cast_no)
ORDER BY cast_no, turbidity_ntu, vertical_position
"""

INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
SERIES = "#2a78d6"


def fetch_casts():
    with psycopg.connect(database_url()) as conn:
        return conn.execute(QUERY).fetchall()


def line_segments(points):
    """Split (time, depth) points into runs with no gap longer than LINE_BREAK."""
    runs, run = [], []
    for t, z in points:
        if run and t - run[-1][0] > LINE_BREAK:
            runs.append(run)
            run = []
        run.append((t, z))
    if run:
        runs.append(run)
    return runs


def plot(casts, out):
    full = [(c[1], c[3]) for c in casts if c[5] >= SHALLOW_RANGE]
    shallow = [(c[1], c[3]) for c in casts if c[5] < SHALLOW_RANGE]

    fig, ax = plt.subplots(figsize=(12, 5.5), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    for run in line_segments(full):
        ts, zs = zip(*run)
        ax.plot(ts, zs, color=SERIES, linewidth=1, alpha=0.35, zorder=1)
    if full:
        ts, zs = zip(*full)
        ax.scatter(ts, zs, s=22, color=SERIES, edgecolor=SURFACE, linewidth=0.8,
                   zorder=3, label=f"Full-depth cast ({len(full)})")
    if shallow:
        ts, zs = zip(*shallow)
        ax.scatter(ts, zs, s=22, facecolor="none", edgecolor=SERIES, linewidth=1.2,
                   zorder=3, label=f"Shallow-only cast, range < {SHALLOW_RANGE} ({len(shallow)})")

    ax.invert_yaxis()  # small Vertical Position = near the surface, so surface at top
    ax.set_ylabel("Vertical Position (surface at top)", color=INK2)
    ax.set_title("Depth of lowest turbidity per cast, Strontia Springs Reservoir",
                 loc="left", color=INK, fontsize=13, pad=22)
    first, last = casts[0][1], casts[-1][1]
    ax.text(0, 1.01, f"{len(casts)} casts, {first:%-d %b} to {last:%-d %b %Y}. "
                     "Provisional Denver Water data; see data/TERMS.md.",
            transform=ax.transAxes, color=INK2, fontsize=9, va="bottom")

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2, length=0)
    ax.legend(loc="lower right", frameon=False, labelcolor=INK2)

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=SURFACE)
    return len(full), len(shallow)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    casts = fetch_casts()
    if not casts:
        sys.exit("No casts found. Load the data with db/load_strontia.py first.")
    n_full, n_shallow = plot(casts, out)
    print(f"Plotted {len(casts)} casts ({n_full} full-depth, {n_shallow} shallow-only) "
          f"to {os.path.relpath(out, REPO)}.")


if __name__ == "__main__":
    main()
