#!/usr/bin/env python3
"""Plot daily rainfall at every station in noaa_daily_weather since START.

    .venv/bin/python db/plot_station_rainfall.py [output.png]

Reads noaa_daily_weather, noaa_station, and collection_area_rain_station (see
schema.sql), so load them first. Writes experiments/noaa_station_rainfall.png by
default.

One row per station, one cell per day, shaded by prcp_in. Rows are grouped by
collection area and sorted by total within each. A cell is hatched where the
station reported no PRCP that day (no row, or a NULL from a failed quality
check), so a gap never reads as a dry day. The bar at the right is the total over
reported days only; the count beside it says how many days that covers, because a
station with gaps is understated.

The x-axis runs from START to the last day loaded, not to today: the loaders stop
at find_collection_rain_stations.END.

NOAA GHCN Daily values are provisional and revised after publication.
"""

import os
import sys
from datetime import date, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import psycopg
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.patches import Patch, Rectangle

from apply_schema import REPO, database_url

DEFAULT_OUT = os.path.join(REPO, "experiments", "noaa_station_rainfall.png")
START = date(2026, 8, 1)

QUERY = """
SELECT w.station, s.name, coalesce(a.collection_area, 'Unassigned'), w.observed_on, w.prcp_in
FROM noaa_daily_weather w
JOIN noaa_station s USING (station)
LEFT JOIN collection_area_rain_station a USING (station)
WHERE w.observed_on >= %s AND w.observed_on <= current_date
"""

INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
MISSING = "#b9b8b3"
SERIES = "#2a78d6"

# Inches per day. 0 gets the surface-adjacent gray so a dry day is visibly a
# measurement, distinct from both rain and the hatched no-report cell.
BOUNDS = [0, 0.005, 0.10, 0.25, 0.50, 1.00, 10]
BIN_LABELS = ["0", "0.01–0.09", "0.10–0.24", "0.25–0.49", "0.50–0.99", "≥ 1.00"]
BIN_COLORS = ["#f0efec", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]


def fetch():
    with psycopg.connect(database_url()) as conn:
        return conn.execute(QUERY, (START,)).fetchall()


def arrange(rows):
    """Return stations in plot order, the day list, and a stations x days array (NaN = no report)."""
    last = max(r[3] for r in rows)
    days = [START + timedelta(n) for n in range((last - START).days + 1)]
    col = {d: i for i, d in enumerate(days)}
    meta, values = {}, {}
    for station, name, area, day, prcp in rows:
        meta[station] = (name, area)
        values.setdefault(station, np.full(len(days), np.nan))[col[day]] = (
            np.nan if prcp is None else prcp)
    totals = {s: np.nansum(v) for s, v in values.items()}
    order = sorted(values, key=lambda s: (meta[s][1], -totals[s], meta[s][0]))
    grid = np.array([values[s] for s in order])
    return [(s, *meta[s]) for s in order], days, grid


def layout(stations):
    """Plot row for each station, leaving one header row above each collection area."""
    rows, headers, y = [], [], 0
    for i, s in enumerate(stations):
        if i == 0 or s[2] != stations[i - 1][2]:
            headers.append((y, s[2]))
            y += 1
        rows.append(y)
        y += 1
    return rows, headers, y


def plot(stations, days, grid, out):
    n_days = grid.shape[1]
    rows, headers, n_rows = layout(stations)
    fig = plt.figure(figsize=(14, 0.22 * n_rows + 2.4), facecolor=SURFACE)
    gs = fig.add_gridspec(1, 2, width_ratios=[n_days, 9], wspace=0.02)
    ax = fig.add_subplot(gs[0])
    bx = fig.add_subplot(gs[1], sharey=ax)
    for a in (ax, bx):
        a.set_facecolor(SURFACE)
        for side in a.spines.values():
            side.set_visible(False)
        a.tick_params(colors=INK2, length=0)

    cmap = ListedColormap(BIN_COLORS)
    norm = BoundaryNorm(BOUNDS, cmap.N)
    placed = np.full((n_rows, n_days), np.nan)
    placed[rows] = grid
    ax.imshow(np.ma.masked_invalid(placed), cmap=cmap, norm=norm, aspect="auto",
              interpolation="none", extent=(-0.5, n_days - 0.5, n_rows - 0.5, -0.5))
    for r, c in zip(*np.where(np.isnan(grid))):
        ax.add_patch(Rectangle((c - 0.5, rows[r] - 0.5), 1, 1, facecolor=SURFACE,
                               edgecolor=MISSING, hatch="////", linewidth=0))
    # Surface-colored gaps between cells.
    for x in np.arange(-0.5, n_days, 1):
        ax.axvline(x, color=SURFACE, linewidth=1.2)
    for y in np.arange(-0.5, n_rows, 1):
        ax.axhline(y, color=SURFACE, linewidth=1.2)
    for y, area in headers:
        ax.add_patch(Rectangle((-0.5, y - 0.5), n_days, 1, facecolor=SURFACE, linewidth=0,
                               zorder=2))
        ax.text(-0.5, y + 0.15, area.upper(), ha="left", va="center", color=INK,
                fontsize=8, fontweight="bold", zorder=3)

    ax.set_ylim(n_rows - 0.5, -0.5)
    ax.set_yticks(rows)
    ax.set_yticklabels([s[1].title() for s in stations], fontsize=8, color=INK2)
    ticks = [i for i, d in enumerate(days) if d.weekday() == 0 or i == 0]
    if n_days - 1 - ticks[-1] >= 3:
        ticks.append(n_days - 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels([f"{days[i]:%-d %b}" for i in ticks], fontsize=8)
    ax.xaxis.tick_top()

    totals = np.nansum(grid, axis=1)
    reported = np.sum(~np.isnan(grid), axis=1)
    bx.barh(rows, totals, height=0.62, color=SERIES)
    for r, t, k in zip(rows, totals, reported):
        label = f"{t:.2f}" + ("" if k == n_days else f"  ({k}/{n_days} d)")
        bx.text(t + 0.08, r, label, va="center", fontsize=7.5,
                color=INK if k == n_days else INK2)
    bx.set_xlim(0, totals.max() * 1.9)
    bx.xaxis.tick_top()
    bx.set_xticks([])
    bx.set_title("Total, in", loc="left", fontsize=8, color=INK2, pad=4)
    bx.tick_params(labelleft=False)

    h = fig.get_figheight()
    fig.suptitle("Daily precipitation by NOAA station, Denver Water collection areas",
                 x=0.01, ha="left", color=INK, fontsize=13, y=1 - 0.12 / h, va="top")
    fig.text(0.01, 1 - 0.45 / h,
             f"{len(stations)} stations, {days[0]:%-d %b} to {days[-1]:%-d %b %Y} "
             f"(the last day loaded). GHCN Daily PRCP, inches; provisional NOAA data. "
             f"Totals cover reported days only.",
             color=INK2, fontsize=9, ha="left", va="top")

    handles = [Patch(facecolor=c, label=l) for c, l in zip(BIN_COLORS, BIN_LABELS)]
    handles.append(Patch(facecolor=SURFACE, edgecolor=MISSING, hatch="////", label="no report"))
    fig.legend(handles=handles, loc="lower left", ncol=len(handles), frameon=False,
               fontsize=8, labelcolor=INK2, bbox_to_anchor=(0.01, 0), handlelength=1.4,
               title="Inches per day", title_fontsize=8, alignment="left")

    fig.subplots_adjust(left=0.16, right=0.99, top=1 - 1.05 / h, bottom=0.7 / h)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=150, facecolor=SURFACE)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    rows = fetch()
    if not rows:
        sys.exit(f"No rows since {START}. Load the data with db/load_noaa_access.py first.")
    stations, days, grid = arrange(rows)
    plot(stations, days, grid, out)
    print(f"Plotted {len(stations)} stations, {days[0]} to {days[-1]}, "
          f"to {os.path.relpath(out, REPO)}.")


if __name__ == "__main__":
    main()
