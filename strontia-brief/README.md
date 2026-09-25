# Watershed geodata

Basin boundaries, river lines, and two short gage series for the South Platte
above Strontia Springs Reservoir. The 3D map (`../design-storm-water-system-3d.html`)
reads all of it; `../water-system-3d/build_system.py` reads `places.json`.

| Path | What it is |
|---|---|
| `places.json` | USGS-verified coordinates and plain-language blurbs for every reservoir, gage, snow station, and treatment plant on the map. Hand-maintained. |
| `basins/*.json` | Drainage polygons and flowlines from the USGS NLDI service, one file per gage, plus the OSM conduit lines. Fetched once and committed. |
| `basins/dw-collection-south.json` | Denver Water's South Platte, Chatfield, Bear Creek, and Upper Blue collection areas, from their Collection System layer on ArcGIS Online. Fetched by `../db/find_collection_rain_stations.py`; the map does not read it. |
| `series/*.json` | Fifteen-minute discharge, turbidity, and conductance from two USGS gages across Aug 14 to 15, 2026, behind the storm replay. |

Coordinates and geometry come from USGS and OpenStreetMap. The gage readings are
USGS provisional data, subject to revision.
