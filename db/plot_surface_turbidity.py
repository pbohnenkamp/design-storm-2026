#!/usr/bin/env python3
"""Plot turbidity at the top three levels of each cast over time.

    .venv/bin/python db/plot_surface_turbidity.py [output.png]

Reads strontia_cast_reading (see schema.sql), so run apply_schema.py and
load_strontia.py first. Writes experiments/strontia_surface_turbidity.png by default.

A cast's levels are its readings ordered by Vertical Position, shallowest first,
so level 1 is the shallowest reading of each cast. The sonde stops roughly one
unit apart, but where it stops varies from cast to cast, so levels are ranked
rather than binned by fixed depth. Lines break where no cast was recorded for
more than a day.

The readings are provisional Denver Water data; see data/TERMS.md before
sharing the figure.
"""

import os
import sys
from datetime import timedelta
from statistics import median

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import psycopg

from apply_schema import REPO, database_url
from plot_min_turbidity import GRID, INK, INK2, SURFACE, line_segments

DEFAULT_OUT = os.path.join(REPO, "experiments", "strontia_surface_turbidity.png")
LEVELS = 3
FIG_WIDTH = 30  # inches; wide so neighbouring casts, six hours apart, separate
COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]  # categorical slots 1-3, in order

# Rank before filtering on turbidity, so a missing value leaves a gap at its
# level instead of promoting the next reading down.
QUERY = """
SELECT level, measured_at, vertical_position, turbidity_ntu
FROM (
    SELECT
        row_number() OVER (PARTITION BY cast_no ORDER BY vertical_position, source_row) AS level,
        measured_at,
        vertical_position,
        turbidity_ntu
    FROM strontia_cast_reading
) ranked
WHERE level <= %s AND turbidity_ntu IS NOT NULL
ORDER BY level, measured_at
"""


def fetch_levels():
    levels = {n: [] for n in range(1, LEVELS + 1)}
    with psycopg.connect(database_url()) as conn:
        for level, t, z, ntu in conn.execute(QUERY, (LEVELS,)):
            levels[level].append((t, z, ntu))
    return levels


def plot(levels, out):
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 6), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)

    for (level, rows), color in zip(levels.items(), COLORS):
        if not rows:
            continue
        depth = median(z for _, z, _ in rows)
        label = f"Level {level}, median Vertical Position {depth:.1f}"
        for i, run in enumerate(line_segments([(t, ntu) for t, _, ntu in rows])):
            ts, ys = zip(*run)
            ax.plot(ts, ys, color=color, linewidth=1.5, zorder=4 - level,
                    label=label if i == 0 else None)

    all_rows = [r for rows in levels.values() for r in rows]
    first = min(t for t, _, _ in all_rows)
    last = max(t for t, _, _ in all_rows)
    ax.set_ylabel("Turbidity (NTU)", color=INK2)
    # Start on a month tick so the first month is labelled; pad the right edge by a day.
    ax.set_xlim(first.replace(day=1, hour=0, minute=0, second=0), last + timedelta(days=1))
    ax.set_ylim(bottom=0)
    ax.set_title("Turbidity at the top three levels of each cast, Strontia Springs Reservoir",
                 loc="left", color=INK, fontsize=13, pad=22)
    ax.text(0, 1.01, f"Level 1 is each cast's shallowest reading. {first:%-d %b} to "
                     f"{last:%-d %b %Y}. Provisional Denver Water data; see data/TERMS.md.",
            transform=ax.transAxes, color=INK2, fontsize=9, va="bottom")

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%-d"))
    ax.grid(axis="x", which="both", color=GRID, linewidth=0.5)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(INK2)
    ax.tick_params(colors=INK2, length=0)
    ax.tick_params(axis="x", which="major", pad=14)
    ax.legend(loc="upper right", frameon=False, labelcolor=INK2)

    fig.tight_layout()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=SURFACE)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    levels = fetch_levels()
    if not any(levels.values()):
        sys.exit("No readings found. Load the data with db/load_strontia.py first.")
    plot(levels, out)
    counts = ", ".join(f"level {n}: {len(rows)}" for n, rows in levels.items())
    print(f"Plotted readings ({counts}) to {os.path.relpath(out, REPO)}.")


if __name__ == "__main__":
    main()
