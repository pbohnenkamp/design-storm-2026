#!/usr/bin/env python3
"""Interactive map of the collection-area rain gauges over Denver Water's boundaries.

    .venv/bin/python db/map_rain_stations.py [output.html]

Reads collection_area_rain_station, noaa_station, and noaa_daily_weather (see
schema.sql), so run find_collection_rain_stations.py and the loaders first. The
polygons are Denver Water's Collection System layer on ArcGIS Online, from
strontia-brief/basins/dw-collection-south.json (find_collection_rain_stations.py
fetches it). Writes experiments/rain_stations_map.html by default: one
self-contained page that loads Leaflet from a CDN and basemap tiles from Esri and
OpenStreetMap, so open it in a browser with a network connection.

Each gauge's popup gives its PRCP totals from START to the last day loaded.
Totals are sums over the days it reported, so gauges with more missing days read
low; the popup shows the day count next to the total for that reason.

NOAA GHCN Daily values are provisional and revised after publication.
"""

import json
import os
import sys
from datetime import date

import psycopg
from shapely.geometry import mapping, shape

from apply_schema import REPO, database_url
from find_collection_rain_stations import AREAS, BOUNDARY_PATH

DEFAULT_OUT = os.path.join(REPO, "experiments", "rain_stations_map.html")
START = date(2022, 4, 1)
SIMPLIFY_DEG = 0.0002  # about 20 m; the layer's full detail triples the page size

QUERY = """
SELECT s.station, s.name, s.latitude, s.longitude, s.elevation_m, a.collection_area,
       count(w.prcp_in), coalesce(sum(w.prcp_in), 0), max(w.prcp_in),
       min(w.observed_on), max(w.observed_on)
FROM collection_area_rain_station a
JOIN noaa_station s USING (station)
LEFT JOIN noaa_daily_weather w
  ON w.station = a.station AND w.observed_on >= %s AND w.prcp_in IS NOT NULL
GROUP BY 1, 2, 3, 4, 5, 6
ORDER BY 6, 1
"""


def fetch():
    with psycopg.connect(database_url()) as conn:
        return conn.execute(QUERY, (START,)).fetchall()


def load_areas():
    with open(BOUNDARY_PATH) as f:
        features = json.load(f)["features"]
    out = []
    for f in features:
        name = f["properties"]["SYSTEM"]
        if name in AREAS:
            geom = shape(f["geometry"]).simplify(SIMPLIFY_DEG, preserve_topology=True)
            out.append({"type": "Feature", "properties": {"area": name}, "geometry": mapping(geom)})
    return {"type": "FeatureCollection", "features": out}


def render(rows, areas, out):
    gauges = [{
        "id": station, "name": name, "lat": lat, "lon": lon,
        "elev_ft": round(elev_m * 3.28084) if elev_m is not None else None,
        "area": area, "days": days, "total_in": round(total, 2),
        "max_in": round(peak, 2) if peak is not None else None,
        "first": first.isoformat() if first else None, "last": last.isoformat() if last else None,
    } for station, name, lat, lon, elev_m, area, days, total, peak, first, last in rows]
    data = {"areas": AREAS, "gauges": gauges, "polygons": areas, "start": START.isoformat()}
    page = TEMPLATE.replace("__DATA__", json.dumps(data, separators=(",", ":")))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w") as f:
        f.write(page)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    rows = fetch()
    if not rows:
        sys.exit("No gauges in collection_area_rain_station. "
                 "Run db/find_collection_rain_stations.py first.")
    render(rows, load_areas(), out)
    counts = {a: sum(1 for r in rows if r[5] == a) for a in AREAS}
    print(f"Mapped {len(rows)} gauges ({', '.join(f'{a} {n}' for a, n in counts.items())}) "
          f"to {os.path.relpath(out, REPO)}.")


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Collection-Area Rain Gauges</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css">
<script src="https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink2: #52514e; --muted: #898781;
  --border: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
    --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #ffffff; --ink2: #c3c2b7; --muted: #898781;
  --border: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
       font: 14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1280px; margin: 0 auto; padding: 24px 16px 40px; }
h1 { font-size: 20px; font-weight: 600; margin: 0 0 4px; }
.sub { color: var(--ink2); margin: 0 0 16px; max-width: 80ch; }
.layout { display: grid; grid-template-columns: 1fr 300px; gap: 16px; }
@media (max-width: 860px) { .layout { grid-template-columns: 1fr; } }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
#map { width: 100%; height: 680px; }
@media (max-width: 860px) { #map { height: 480px; } }
.side { padding: 12px; max-height: 680px; overflow: auto; }
.side h2 { font-size: 13px; font-weight: 600; margin: 12px 0 4px; display: flex; align-items: center; gap: 8px; }
.side h2:first-child { margin-top: 0; }
.side h2 small { color: var(--muted); font-weight: 400; }
.sw { width: 10px; height: 10px; border-radius: 50%; flex: none; }
.side ul { list-style: none; margin: 0; padding: 0; }
.side li button { font: inherit; font-size: 12px; width: 100%; text-align: left; background: none;
                  border: 0; border-radius: 6px; padding: 3px 6px; color: var(--ink2); cursor: pointer;
                  display: flex; justify-content: space-between; gap: 8px; }
.side li button:hover { background: var(--border); color: var(--ink); }
.side li code { font-size: 11px; color: var(--muted); }
.leaflet-popup-content { font: 13px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; margin: 10px 12px; }
.pop b { font-size: 14px; }
.pop table { border-collapse: collapse; margin-top: 6px; }
.pop td { padding: 1px 10px 1px 0; vertical-align: top; }
.pop td:first-child { color: #52514e; }
.note { color: var(--ink2); font-size: 12px; margin-top: 12px; max-width: 100ch; }
</style>
</head>
<body>
<main>
  <h1>Rain gauges in the collection areas</h1>
  <p class="sub" id="sub"></p>
  <div class="layout">
    <div class="card"><div id="map"></div></div>
    <div class="card side" id="side"></div>
  </div>
  <p class="note">
    Polygons are Denver Water's Collection System layer on ArcGIS Online (South Platte, Chatfield,
    Bear Creek, Upper Blue), simplified to about 20 m. Points are NOAA GHCN Daily stations inside
    those polygons that reported precipitation from April 2022 to September 2026. Popup totals sum
    only the days a gauge reported, so compare the day counts before comparing totals. Switch
    basemaps with the layer control at top right. NOAA data is provisional and revised after publication.
  </p>
</main>
<script>
const D = __DATA__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const color = a => css(["--s1", "--s2", "--s3", "--s4"][D.areas.indexOf(a)]);
const fmtDate = iso => iso ? new Date(iso + "T00:00").toLocaleDateString("en-US",
  { year: "numeric", month: "short", day: "numeric" }) : "–";
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

document.getElementById("sub").textContent =
  `${D.gauges.length} NOAA gauges in Denver Water's South Platte, Chatfield, Bear Creek and ` +
  `Upper Blue collection areas. Click a gauge for its record since ${fmtDate(D.start)}.`;

const esriAttr = "Tiles &copy; Esri";
const bases = {
  "Topographic (Esri)": L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: esriAttr }),
  "Imagery (Esri)": L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: esriAttr }),
  "OpenStreetMap": L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    { maxZoom: 19, attribution: "&copy; OpenStreetMap contributors" }),
};
const map = L.map("map", { layers: [bases["Topographic (Esri)"]] });

const polys = L.geoJSON(D.polygons, {
  style: f => ({ color: color(f.properties.area), weight: 2, fillColor: color(f.properties.area), fillOpacity: 0.12 }),
  onEachFeature: (f, layer) => layer.bindTooltip(f.properties.area, { sticky: true }),
}).addTo(map);

function popup(g) {
  const rows = [
    ["Area", esc(g.area)],
    ["Elevation", g.elev_ft != null ? g.elev_ft.toLocaleString() + " ft" : "–"],
    ["Location", `${g.lat.toFixed(4)}, ${g.lon.toFixed(4)}`],
    ["Days reported", `${g.days.toLocaleString()} (${fmtDate(g.first)} to ${fmtDate(g.last)})`],
    ["Total PRCP", `${g.total_in.toFixed(2)} in`],
    ["Wettest day", g.max_in != null ? `${g.max_in.toFixed(2)} in` : "–"],
  ];
  return `<div class="pop"><b>${esc(g.name)}</b><br><code>${esc(g.id)}</code><table>` +
    rows.map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join("") + "</table></div>";
}

const markers = {};
const points = L.layerGroup(D.gauges.map(g => {
  const m = L.circleMarker([g.lat, g.lon], {
    radius: 6, weight: 1.5, color: "#ffffff", fillColor: color(g.area), fillOpacity: 1,
  }).bindPopup(popup(g)).bindTooltip(`${esc(g.name)} (${esc(g.id)})`);
  markers[g.id] = m;
  return m;
})).addTo(map);

L.control.layers(bases, { "Collection areas": polys, "Rain gauges": points }, { collapsed: false }).addTo(map);
L.control.scale({ imperial: true, metric: true }).addTo(map);
// Fit once the container has a size; a page opened in a hidden tab or pane has none at load.
let fitted = false;
new ResizeObserver(() => {
  map.invalidateSize();
  if (!fitted && map.getSize().y > 0) { map.fitBounds(polys.getBounds(), { padding: [12, 12] }); fitted = true; }
}).observe(document.getElementById("map"));
map.setView([39.25, -105.5], 8);

const side = document.getElementById("side");
for (const a of D.areas) {
  const mine = D.gauges.filter(g => g.area === a).sort((x, y) => x.name.localeCompare(y.name));
  const h = document.createElement("h2");
  const sw = document.createElement("span"); sw.className = "sw"; sw.style.background = color(a);
  const n = document.createElement("small"); n.textContent = `${mine.length} gauges`;
  h.append(sw, a, n);
  const ul = document.createElement("ul");
  for (const g of mine) {
    const li = document.createElement("li"), b = document.createElement("button");
    const name = document.createElement("span"); name.textContent = g.name;
    const id = document.createElement("code"); id.textContent = g.id;
    b.append(name, id);
    b.addEventListener("click", () => { map.setView([g.lat, g.lon], Math.max(map.getZoom(), 11)); markers[g.id].openPopup(); });
    li.append(b); ul.append(li);
  }
  side.append(h, ul);
}
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
