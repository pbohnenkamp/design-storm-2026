# What I did at the Design Storm, and how far I got

Notes for a conference observer. The exercise was time-boxed, so this is a record of work in
progress, not a finished analysis. Everything here is exploratory.

## The question

Our team's working idea (whiteboard, "Experiment 1"):

> Rain that falls upstream shows up days later as a change in water quality where Foothills
> draws its water, so rain-gauge records can be used to predict it.

We simplified hard to get something testable in the time we had:

- Runoff travels at one constant speed, in a straight line ("as the crow flies") from each gauge to
  the measurement point. Terrain is ignored.
- Rain gauges at fixed points stand in for the rain over the area around them. Radar
  (`[x, y, intensity, time]`) was the better idea; gauges (`[x, y, rain height, time]`) were what
  we could get in a day.
- We started with turbidity at the top of the Strontia Springs sonde's water column, then switched
  the target to **TOC (total organic carbon) at the Foothills plant influent**, because TOC has
  years of history and the sonde has one season.

A teammate wrote the program that tests the idea (the "Rainfall-to-TOC experiment", a Python tool
with `check-data`, `train` and `predict` commands, documented in its own `GETTING_STARTED.md`). My
part was the data: get it into a database, find the right rain gauges, and produce the program's
input files.

## What I built

A small Postgres database (`denver_water`) and the scripts in this folder that fill and query it.
`DATABASE_URL` comes from the environment or `.env` at the repo root. Every loader is safe to rerun.

### 1. Schema and loaders

| Script | What it does |
|---|---|
| `schema.sql`, `apply_schema.py` | Creates the tables below. Idempotent. |
| `load_strontia.py` | Strontia Springs sonde readings from the xlsx (the CSV export drops seconds) into `strontia_sonde_reading`. The view `strontia_cast_reading` groups readings into casts (one trip through the water column; a gap over 30 minutes starts a new cast). |
| `load_foothills.py` | Foothills influent TOC and alkalinity into `foothills_influent`. The file has no January to March rows. |
| `load_noaa.py` | The NOAA daily weather CSV Denver Water supplied (`data/USC00058022.csv`). |
| `load_noaa_stations.py` | NOAA's worldwide GHCN Daily station list into `noaa_station`. |
| `find_collection_rain_stations.py` | Picks the NOAA stations strictly inside Denver Water's South Platte, Chatfield, Bear Creek and Upper Blue collection areas (polygons from their public ArcGIS layer) that reported precipitation across 2022-04-01 to 2026-09-01. Writes `collection_area_rain_station`. |
| `load_noaa_access.py` | Downloads each of those stations' daily records from NCEI, converts GHCN's raw units to inches and °F, and nulls values that failed NCEI's quality checks. Skips SNOTEL (`USS*`) sites unless named on the command line. |

### 2. Looking at the data

Each of these writes to `experiments/` (not committed; see "Caveats").

| Script | Output |
|---|---|
| `plot_min_turbidity.py`, `plot_surface_turbidity.py`, `plot_turbidity_range.py` | Sonde turbidity per cast: depth of the clearest reading, the top three levels, and each cast's min and max. This is where we saw surface turbidity was too short a record to model. |
| `plot_station_rainfall.py` | Heat map, one row per gauge, one cell per day, with missing days hatched so a gap never reads as a dry day. |
| `plot_daily_rainfall.py` | Interactive (Plotly) daily rainfall summed across gauges, stacked by collection area, with the count of reporting gauges alongside. |
| `map_rain_stations.py` | Interactive (Leaflet) map of the gauges over the collection-area boundaries. |
| `export_rainfall.py` | All collection-area gauges as one long `date, gauge, inches` CSV, with a gap report per gauge. |

### 3. Feeding the program

`build_inputs.py` turns the database into one input bundle for the program. See
"Generating the program's input files" below for how to run it.

## Working with the program

The program is strict, and its rules drove most of my choices:

| Program rule | What it forced |
|---|---|
| No blank cells, ever; 0 means it did not rain. | A missing gauge day cannot become 0. Either drop the gauge or fill the day from a real neighbour, and record the fill. |
| Every day from first to last must be present. | Can't just leave winter out; see run 4. |
| Rainfall must start 3 weeks before the first TOC sample. | The first 21 TOC samples (2022-04-01 to 04-21) are dropped. |
| Gauge IDs must match between files exactly. | Built both files from the same query. |
| The most recent 20% of TOC samples is the hold-out. | Run 5 moves a whole summer out of training to get a second, cleaner test. |

The workflow per run, from `GETTING_STARTED.md`, is: copy the bundle's `data/` and `config.yaml`
into the program folder, then

```bash
python main.py check-data
```

until it prints `DATA CHECK PASSED`, then

```bash
python main.py train
```

which prints a verdict (SUPPORTED / PARTLY SUPPORTED / INCONCLUSIVE / NOT SUPPORTED) from three checks:
beats predicting the average on unseen samples, rainfall effect significant, and a clear best
travel velocity. Run 5 also uses

```bash
python main.py predict --input data/new_rainfall.csv
```

I built five bundles, each a response to what the last one exposed. They were handed over through
the team's shared drive as `experiment_1_data` to `experiment_5_data`.

| Run | Gauges | What changed and why |
|---|---|---|
| 1 | 5 | Only the 5 of 19 catchment gauges that reported every single day: CHEESMAN, DIVIDE 4NW, and SNOTEL sites Jackwhacker Gulch, Hoosier Pass, Buckskin Joe. Five gauges for 2,584 sq mi is thin, and 4 of 5 sit on the mainstem behind the reservoirs. |
| 2 | 4 | Swaps three SNOTEL sites for Michigan Creek and Rough and Tumble, filling their 9 QC-failed days from the nearest gauge that reported (`--fill-nearest`). |
| 3 | 5 | The five SNOTEL sites, keeping precipitation only on days when the gauge's own minimum temperature was at or above freezing (32 °F); colder days are written as 0. The aim was to strip snow, which runs off weeks later at melt, not in the following days. Missing days filled from neighbours. `reference/tmin_rule_summary.csv` shows what the rule removed per gauge and month. |
| 4 | 12 | Summer only (June 1 to September 30). TOC outside the season is dropped. Real rain from May 11 so early-June samples have their 3 weeks; every other day is written as 0, which is safe because no kept sample can see it. Gauges are every catchment gauge with at least 95% summer coverage; 79 missing days filled from neighbours. 3 of the 12 are on the North Fork, which has no major reservoir. |
| 5 | 12 | Run 4 with training stopped at 2025-12-31. Summer 2026 becomes a fully unseen test: `predict` on `new_rainfall.csv`, then compare with the 80 measured samples in `reference/toc_after_end.csv`. |

## How far I got

- **Done:** database, loaders, gauge selection by collection-area polygon, exploratory plots and
  map, and five input bundles that match the program's formats.
- **Results are not in this repository.** The runs happened on a teammate's machine, and Kyle Brown
  presented the program's verdicts in the conference recap. None of the program's `outputs/` came
  back here, so for results, see the recap.
- **Not done:** scoring run 5's 2026 predictions against `toc_after_end.csv`; radar rainfall;
  anything but straight-line distance.

## What I'd want someone to know before trusting any result

- **Reservoirs break the core assumption.** Most gauges drain through Antero, Eleven Mile or Cheesman
  before Strontia. Storage holds water for weeks to months, so "constant travel speed" is a poor fit
  for the mainstem. The North Fork gauges are the fairest test of the idea.
- **Snow is precipitation on the day it falls** in GHCN, but it runs off at melt. Run 3 and the
  summer-only runs 4 and 5 are two different workarounds; neither models melt.
- **Gauges don't share a day.** SNOTEL days run midnight to midnight in 0.1 inch steps; COOP and
  CoCoRaHS days end at the observer's reading time (often 7 a.m.) in 0.01 inch steps.
- **Filled days are real rain from somewhere else.** Six August 2024 days at Michigan Creek came from
  Hoosier Pass, in storm season. Every fill is listed in the bundle's `reference/filled_days.csv`.
- **No winter TOC** in the source, so no run says anything about January to March.
- **All of it is provisional.** Denver Water's TOC and sonde data and NOAA's GHCN Daily values can be
  revised after publication.

## Caveats about this repository

- `experiments/` is in `.gitignore`. The plots, the rain CSV and the five bundles are on my machine
  and the team's shared drive, not on GitHub. The scripts in this folder regenerate all of them.
- The Denver Water data terms (`data/TERMS.md`) travel with every bundle.

## Rebuilding from scratch

```bash
python3 -m venv .venv && .venv/bin/pip install -r db/requirements.txt
.venv/bin/python db/apply_schema.py
.venv/bin/python db/load_strontia.py
.venv/bin/python db/load_foothills.py
.venv/bin/python db/load_noaa.py
.venv/bin/python db/load_noaa_stations.py
.venv/bin/python db/find_collection_rain_stations.py
.venv/bin/python db/load_noaa_access.py
.venv/bin/python db/load_noaa_access.py USS0005K26S USS0005K28S USS0006K01S USS0006K16S USS0006K43S
```

The last line loads the five SNOTEL sites the runs use, which the default skips. The NCEI steps
need the network and take a while.

## Generating the program's input files

With the database loaded, `build_inputs.py` writes one bundle per run:

```
<out>/
  config.yaml          copy of db/rainfall_toc_config.yaml
  TERMS.md             copy of data/TERMS.md; keep it with the data
  data/
    rainfall.csv       date, then one column per gauge, daily inches, no blanks or skipped days
    gauges.csv         gauge_id, lat, lon, exactly the gauges in rainfall.csv
    toc.csv            date, toc_mg_per_L, Foothills influent
    new_rainfall.csv   same gauges, for `predict`: days after the training data, with 30 days' history
  reference/           read by people, not by the program
    gauge_registry.csv every gauge: location, distance to the TOC point, gaps, why it is in or out
    catchment.geojson  USGS basin above Strontia Springs (gage 06707525)
    filled_days.csv    with --fill-nearest: every filled day and where it came from
    tmin_rule_summary.csv  with --zero-below-tmin: what the rule removed
    toc_after_end.csv  with --end: measured TOC after the training data, to score predictions
```

`config.yaml` is hand-written, not generated. It sets the TOC point, the Conduit 26 intake at
Strontia Springs Dam (39.431939 N, 105.126546 W), where Foothills draws its water. It starts the
velocity at the program's default of 2.0 ft/s, and the program scans 0.5 to 5 ft/s anyway. Edit
`db/rainfall_toc_config.yaml` to change it for every future bundle.

Options:

| Option | Effect |
|---|---|
| `--out DIR` | Where to write. Default `experiments/rainfall_toc_prediction`. |
| `--gauges ID,ID,...` | Which gauges, in column order. Default: every catchment gauge with no missing day over the TOC period. `reference/gauge_registry.csv` from any run lists the candidates. |
| `--fill-nearest` | Fill a chosen gauge's missing days from the nearest catchment gauge that reported that day. Without it, a gap stops the script, because a gap is not a zero. |
| `--zero-below-tmin F` | Write 0 on days the gauge's minimum temperature is below F °F, before any filling. |
| `--season MM-DD:MM-DD` | Keep only TOC samples inside this window each year. Rain is kept from 21 days before the window to its end, and every other day is written as 0. |
| `--end YYYY-MM-DD` | Train on nothing after this date. Later TOC goes to `reference/toc_after_end.csv`. |

The exact commands for the five runs (they reproduce the handed-over bundles byte for byte from the
current database):

```bash
.venv/bin/python db/build_inputs.py --out experiments/rainfall_toc_prediction
```

```bash
.venv/bin/python db/build_inputs.py --out experiments/rainfall_toc_prediction_2 --gauges USC00051528,USC00052294,USS0005K28S,USS0006K43S --fill-nearest
```

```bash
.venv/bin/python db/build_inputs.py --out experiments/rainfall_toc_prediction_3 --gauges USS0005K26S,USS0005K28S,USS0006K01S,USS0006K16S,USS0006K43S --fill-nearest --zero-below-tmin 32
```

```bash
.venv/bin/python db/build_inputs.py --out experiments/rainfall_toc_prediction_4 --gauges USC00051528,USC00052294,USS0005K26S,USC00054742,USS0006K01S,USS0006K16S,USS0006K43S,USC00053530,USS0005K28S,US1COPK0046,US1COJF0081,US1COTL0039 --fill-nearest --season 06-01:09-30
```

```bash
.venv/bin/python db/build_inputs.py --out experiments/rainfall_toc_prediction_5 --gauges USC00051528,USC00052294,USS0005K26S,USC00054742,USS0006K01S,USS0006K16S,USS0006K43S,USC00053530,USS0005K28S,US1COPK0046,US1COJF0081,US1COTL0039 --fill-nearest --season 06-01:09-30 --end 2025-12-31
```

The script prints what it chose: the gauges, each fill, how many TOC samples it kept, and a table of
catchment gauges by distance with their gaps. Copy the bundle's `config.yaml` and `data/` into the
program's folder, then run `python main.py check-data` as described above.

A rerun overwrites the files in `--out` but does not delete ones an earlier run with other options
left behind (for example, `filled_days.csv`). Use a fresh folder when changing options.
