#!/usr/bin/env python3
"""Plot each cast's lowest and highest turbidity over time, labelled with depth.

    .venv/bin/python db/plot_turbidity_range.py [output.png]

Reads strontia_cast_reading (see schema.sql), so run apply_schema.py and
load_strontia.py first. Writes experiments/strontia_turbidity_range.png by default.

Each cast gets two points joined by a thin line: its lowest and its highest
Turbidity NTU, each labelled with the Vertical Position it was read at. Ties
go to the shallowest reading. The y-axis is logarithmic because per-cast
maximums run to thousands of NTU while minimums sit near zero.

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
from matplotlib.ticker import FuncFormatter

from apply_schema import REPO, database_url
from plot_min_turbidity import GRID, INK, INK2, SURFACE

DEFAULT_OUT = os.path.join(REPO, "experiments", "strontia_turbidity_range.png")
FIG_WIDTH = 36  # inches; wide enough that neighbouring casts' labels don't collide
LOW_COLOR = "#2a78d6"   # categorical slot 1
HIGH_COLOR = "#eb6834"  # categorical slot 2
LABEL_SIZE = 5

# One row per cast: its lowest and highest reading, ties broken by shallowest.
QUERY = """
SELECT lo.cast_at, lo.measured_at, lo.vertical_position, lo.turbidity_ntu,
       hi.measured_at, hi.vertical_position, hi.turbidity_ntu
FROM (
    SELECT DISTINCT ON (cast_no) cast_no, cast_at, measured_at, vertical_position, turbidity_ntu
    FROM strontia_cast_reading
    WHERE turbidity_ntu IS NOT NULL
    ORDER BY cast_no, turbidity_ntu, vertical_position
) lo
JOIN (
    SELECT DISTINCT ON (cast_no) cast_no, measured_at, vertical_position, turbidity_ntu
    FROM strontia_cast_reading
    WHERE turbidity_ntu IS NOT NULL
    ORDER BY cast_no, turbidity_ntu DESC, vertical_position
) hi USING (cast_no)
ORDER BY cast_no
"""


def fetch_casts():
    with psycopg.connect(database_url()) as conn:
        return conn.execute(QUERY).fetchall()


def depth_label(z):
    return f"{z:.1f}"


def plot(casts, out):
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 8), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_yscale("log")

    # Plot both points at the cast's start so each cast's pair lines up vertically.
    ts = [c[0] for c in casts]
    lows = [(c[2], c[3]) for c in casts]
    highs = [(c[5], c[6]) for c in casts]

    ax.vlines(ts, [n for _, n in lows], [n for _, n in highs], color=GRID, linewidth=1, zorder=1)
    ax.scatter(ts, [n for _, n in highs], s=14, color=HIGH_COLOR, edgecolor=SURFACE,
               linewidth=0.6, zorder=3, label="Highest turbidity in the cast")
    ax.scatter(ts, [n for _, n in lows], s=14, color=LOW_COLOR, edgecolor=SURFACE,
               linewidth=0.6, zorder=3, label="Lowest turbidity in the cast")

    # Depth labels: above the high point, below the low point, rotated to fit.
    for t, (z, n) in zip(ts, highs):
        ax.annotate(depth_label(z), (t, n), xytext=(0, 4), textcoords="offset points",
                    rotation=90, ha="center", va="bottom", fontsize=LABEL_SIZE, color=INK2)
    for t, (z, n) in zip(ts, lows):
        ax.annotate(depth_label(z), (t, n), xytext=(0, -4), textcoords="offset points",
                    rotation=90, ha="center", va="top", fontsize=LABEL_SIZE, color=INK2)

    first, last = ts[0], ts[-1]
    ax.set_xlim(first.replace(day=1, hour=0, minute=0, second=0), last + timedelta(days=1))
    all_ntu = [n for _, n in lows + highs]
    ax.set_ylim(min(all_ntu) / 4, max(all_ntu) * 4)  # room for the rotated labels
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_ylabel("Turbidity (NTU, log scale)", color=INK2)
    ax.set_title("Lowest and highest turbidity of each cast, Strontia Springs Reservoir",
                 loc="left", color=INK, fontsize=13, pad=22)
    ax.text(0, 1.01, f"Labels give the Vertical Position of each reading (small = near surface). "
                     f"{len(casts)} casts, {first:%-d %b} to {last:%-d %b %Y}. "
                     "Provisional Denver Water data; see data/TERMS.md.",
            transform=ax.transAxes, color=INK2, fontsize=9, va="bottom")

    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_minor_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_minor_formatter(mdates.DateFormatter("%-d"))
    ax.grid(axis="x", which="both", color=GRID, linewidth=0.5)
    ax.grid(axis="y", which="major", color=GRID, linewidth=0.8)
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
    casts = fetch_casts()
    if not casts:
        sys.exit("No casts found. Load the data with db/load_strontia.py first.")
    plot(casts, out)
    print(f"Plotted {len(casts)} casts to {os.path.relpath(out, REPO)}.")


if __name__ == "__main__":
    main()
