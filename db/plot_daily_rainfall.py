#!/usr/bin/env python3
"""Interactive chart of summed daily rainfall across the collection-area gauges.

    .venv/bin/python db/plot_daily_rainfall.py [output.html]

Reads noaa_daily_weather and collection_area_rain_station (see schema.sql), so
run find_collection_rain_stations.py and the loaders first. Writes
experiments/daily_rainfall.html by default: one self-contained page that loads
Plotly from a CDN, so open it in a browser with a network connection.

Each day's bar is the sum of PRCP over every gauge that reported that day,
stacked by collection area. A sum over gauges is not an areal rainfall
amount, and it moves with the number of gauges reporting (NULL or missing rows
add nothing), so a second panel shows that count on its own axis.

The x-axis runs from START to the last day loaded, not to today: the loaders
stop at find_collection_rain_stations.END.

NOAA GHCN Daily values are provisional and revised after publication.
"""

import json
import os
import sys
from datetime import date, timedelta

import psycopg

from apply_schema import REPO, database_url

DEFAULT_OUT = os.path.join(REPO, "experiments", "daily_rainfall.html")
START = date(2022, 4, 1)

QUERY = """
SELECT w.observed_on, a.collection_area, sum(w.prcp_in), count(w.prcp_in)
FROM noaa_daily_weather w
JOIN collection_area_rain_station a USING (station)
WHERE w.observed_on >= %s AND w.observed_on <= current_date
GROUP BY 1, 2
ORDER BY 1, 2
"""

STATIONS = """
SELECT a.collection_area, count(DISTINCT w.station)
FROM noaa_daily_weather w
JOIN collection_area_rain_station a USING (station)
WHERE w.observed_on >= %s AND w.prcp_in IS NOT NULL
GROUP BY 1
"""

# Stack order, bottom to top, and the categorical slot each area keeps.
AREAS = ["South Platte", "Chatfield", "Bear Creek", "Upper Blue"]


def fetch():
    with psycopg.connect(database_url()) as conn:
        return (conn.execute(QUERY, (START,)).fetchall(),
                dict(conn.execute(STATIONS, (START,)).fetchall()))


def arrange(rows):
    """Return the day list, per-area daily sums, and per-area daily reporting counts."""
    last = max(r[0] for r in rows)
    days = [START + timedelta(n) for n in range((last - START).days + 1)]
    col = {d: i for i, d in enumerate(days)}
    unknown = {r[1] for r in rows} - set(AREAS)
    if unknown:
        sys.exit(f"Collection areas missing from AREAS: {sorted(unknown)}")
    sums = {a: [0.0] * len(days) for a in AREAS}
    counts = {a: [0] * len(days) for a in AREAS}
    for day, area, total, n in rows:
        sums[area][col[day]] = round(total or 0.0, 2)
        counts[area][col[day]] = n
    return days, sums, counts


def render(days, sums, counts, stations, out):
    data = {
        "days": [d.isoformat() for d in days],
        "areas": AREAS,
        "sums": sums,
        "counts": counts,
        "stations": {a: stations.get(a, 0) for a in AREAS},
    }
    page = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write(page)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    rows, stations = fetch()
    if not rows:
        sys.exit(f"No rows since {START}. Load the data with db/load_noaa_access.py first.")
    days, sums, counts = arrange(rows)
    render(days, sums, counts, stations, out)
    print(f"Plotted {sum(stations.values())} gauges, {days[0]} to {days[-1]}, "
          f"to {os.path.relpath(out, REPO)}.")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Daily Rainfall, Collection Areas</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js"></script>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding: 24px 16px 40px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
.sub { color: var(--ink2); margin: 0 0 16px; max-width: 80ch; }
.controls { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; margin-bottom: 12px; }
.seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.seg button { font: inherit; font-size: 13px; background: var(--surface); color: var(--ink2);
              border: 0; padding: 6px 12px; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--border); }
.seg button[aria-pressed="true"] { color: var(--ink); font-weight: 600; background: var(--grid); }
.stats { display: flex; flex-wrap: wrap; gap: 8px 28px; margin: 4px 0 12px; }
.stat b { display: block; font-size: 22px; font-weight: 600; }
.stat span { color: var(--ink2); font-size: 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 8px; }
#chart { width: 100%; height: 620px; }
.note { color: var(--ink2); font-size: 12px; margin-top: 12px; max-width: 100ch; }
</style>
</head>
<body>
<main>
  <h1>Daily rainfall, summed across collection-area gauges</h1>
  <p class="sub" id="sub"></p>
  <div class="controls">
    <div class="seg" role="group" aria-label="Date range" id="range">
      <button data-r="season">Since Apr 1 this year</button>
      <button data-r="365">Last 12 months</button>
      <button data-r="all" aria-pressed="true">All</button>
    </div>
    <div class="seg" role="group" aria-label="Breakdown" id="mode">
      <button data-m="area" aria-pressed="true">By collection area</button>
      <button data-m="total">Total only</button>
    </div>
  </div>
  <div class="stats" id="stats"></div>
  <div class="card"><div id="chart"></div></div>
  <p class="note">
    Drag across the chart to zoom, double-click to reset. Click a legend entry to hide an area;
    double-click to isolate it. Each bar sums NOAA GHCN Daily PRCP (inches) over the gauges that
    reported that day; a missing or failed-QC report adds nothing, so compare against the lower
    panel before reading a dip as a dry spell. A sum over gauges is not a basin-average depth.
    Observation days end at each observer's reading time, not midnight.
    NOAA data is provisional and revised after publication.
  </p>
</main>
<script>
const D = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const N = D.days.length;
const totals = D.days.map((_, i) => D.areas.reduce((s, a) => s + D.sums[a][i], 0));
const reporting = D.days.map((_, i) => D.areas.reduce((s, a) => s + D.counts[a][i], 0));
const gauges = D.areas.reduce((s, a) => s + D.stations[a], 0);
let mode = "area";

document.getElementById("sub").textContent =
  `${gauges} NOAA gauges in Denver Water's South Platte, Chatfield, Bear Creek and Upper Blue ` +
  `collection areas, ${fmtDate(D.days[0])} to ${fmtDate(D.days[N - 1])} (the last day loaded).`;

function fmtDate(iso) {
  return new Date(iso + "T00:00").toLocaleDateString("en-US",
    { year: "numeric", month: "short", day: "numeric" });
}

function stats(lo, hi) {
  let sum = 0, max = -1, maxDay = null, wet = 0, n = 0;
  for (let i = 0; i < N; i++) {
    if (D.days[i] < lo || D.days[i] > hi) continue;
    n++; sum += totals[i];
    if (totals[i] > 0) wet++;
    if (totals[i] > max) { max = totals[i]; maxDay = D.days[i]; }
  }
  const box = document.getElementById("stats");
  box.replaceChildren();
  const items = [
    [sum.toFixed(1) + " in", "summed over the range shown"],
    [max >= 0 ? max.toFixed(2) + " in" : "–", maxDay ? "largest day, " + fmtDate(maxDay) : "largest day"],
    [`${wet} of ${n}`, "days with any gauge reporting rain"],
  ];
  for (const [v, l] of items) {
    const d = document.createElement("div"); d.className = "stat";
    const b = document.createElement("b"); b.textContent = v;
    const s = document.createElement("span"); s.textContent = l;
    d.append(b, s); box.append(d);
  }
}

function traces() {
  const cols = ["--s1", "--s2", "--s3", "--s4"].map(css);
  const hover = D.days.map((d, i) => {
    let t = `<b>${fmtDate(d)}</b><br><b>${totals[i].toFixed(2)} in</b> total, ` +
            `${reporting[i]} of ${gauges} gauges<br>`;
    for (const a of D.areas)
      t += `<br>${D.sums[a][i].toFixed(2)} in  <span style="color:${css("--ink2")}">${a} ` +
           `(${D.counts[a][i]}/${D.stations[a]})</span>`;
    return t;
  });
  const bars = mode === "area"
    ? D.areas.map((a, k) => ({
        type: "bar", name: a, x: D.days, y: D.sums[a], marker: { color: cols[k], line: { width: 0 } },
        hoverinfo: k === 0 ? "text" : "skip", hovertext: hover, xaxis: "x", yaxis: "y",
      }))
    : [{ type: "bar", name: "All gauges", x: D.days, y: totals, marker: { color: cols[0], line: { width: 0 } },
         hoverinfo: "text", hovertext: hover, showlegend: false, xaxis: "x", yaxis: "y" }];
  bars.push({
    type: "scatter", mode: "lines", name: "Gauges reporting", x: D.days, y: reporting,
    line: { color: css("--muted"), width: 1.5, shape: "hv" }, showlegend: false,
    hovertemplate: "%{y} of " + gauges + " gauges reporting<extra></extra>", xaxis: "x", yaxis: "y2",
  });
  return bars;
}

function layout() {
  const ink2 = css("--ink2"), grid = css("--grid"), axis = css("--axis"), muted = css("--muted");
  const ax = { gridcolor: grid, linecolor: axis, zerolinecolor: axis, tickfont: { color: muted, size: 11 } };
  return {
    barmode: "stack", bargap: 0, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: 'system-ui, -apple-system, "Segoe UI", sans-serif', color: ink2, size: 12 },
    margin: { l: 56, r: 16, t: 36, b: 36 }, hovermode: "x",
    hoverlabel: { bgcolor: css("--surface"), bordercolor: axis, font: { color: css("--ink"), size: 12 }, align: "left" },
    legend: { orientation: "h", x: 0, y: 1.06, font: { color: ink2 }, traceorder: "reversed" },
    xaxis: { ...ax, type: "date", showgrid: false, showspikes: true, spikemode: "across", spikethickness: 1,
             spikecolor: muted, spikedash: "solid", spikesnap: "cursor", anchor: "y2" },
    yaxis: { ...ax, domain: [0.26, 1], title: { text: "Inches, summed over gauges", font: { size: 11, color: ink2 } },
             rangemode: "tozero", fixedrange: false },
    yaxis2: { ...ax, domain: [0, 0.18], title: { text: "Gauges reporting", font: { size: 11, color: ink2 } },
              range: [0, gauges + 2], fixedrange: true },
  };
}

const el = document.getElementById("chart");
function draw() {
  const r = el.layout && el.layout.xaxis && el.layout.xaxis.range;
  const lay = layout();
  if (r) lay.xaxis.range = r;
  Plotly.react(el, traces(), lay, { responsive: true, displaylogo: false,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"],
    toImageButtonOptions: { filename: "daily_rainfall", scale: 2 } });
}

function setRange(key) {
  const last = D.days[N - 1];
  let lo = D.days[0];
  if (key === "365") {
    const d = new Date(last + "T00:00"); d.setDate(d.getDate() - 364); lo = d.toISOString().slice(0, 10);
  } else if (key === "season") {
    lo = last.slice(0, 4) + "-04-01";
  }
  Plotly.relayout(el, { "xaxis.range": [lo + " 00:00", last + " 23:59"] });
}

function pressed(group, btn) {
  for (const b of group.querySelectorAll("button")) b.setAttribute("aria-pressed", b === btn);
}
document.getElementById("range").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  pressed(e.currentTarget, b); setRange(b.dataset.r);
});
document.getElementById("mode").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  pressed(e.currentTarget, b); mode = b.dataset.m; draw();
});

draw();
stats(D.days[0], D.days[N - 1]);
el.on("plotly_relayout", ev => {
  if (ev["yaxis.range"] && !ev["xaxis.range"] && ev["xaxis.range[0]"] === undefined) return;
  if (ev["xaxis.autorange"]) { Plotly.relayout(el, { "yaxis.autorange": true }); stats(D.days[0], D.days[N - 1]); pressed(document.getElementById("range"),
    document.querySelector('#range [data-r="all"]')); return; }
  const lo = ev["xaxis.range[0]"] ?? (ev["xaxis.range"] || [])[0];
  const hi = ev["xaxis.range[1]"] ?? (ev["xaxis.range"] || [])[1];
  if (lo && hi) { stats(String(lo).slice(0, 10), String(hi).slice(0, 10));
                  fitY(String(lo).slice(0, 10), String(hi).slice(0, 10)); }
});

// Plotly autoranges y over all data, not the visible days, so fit it by hand.
function fitY(lo, hi) {
  let max = 0;
  for (let i = 0; i < N; i++) if (D.days[i] >= lo && D.days[i] <= hi) max = Math.max(max, totals[i]);
  Plotly.relayout(el, { "yaxis.range": [0, (max || 1) * 1.05] });
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", draw);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
