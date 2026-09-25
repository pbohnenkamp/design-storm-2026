-- Schema for the denver_water database. Safe to run repeatedly.
--
-- Sources: data/Strontia 0407_0819.xlsx, Denver Water's profiling sonde at
-- Strontia Springs Reservoir, and data/FoothillsInfluent.csv, Denver Water's lab
-- results for water entering the Foothills plant. Provisional data; see
-- data/TERMS.md. Also data/USC00058022.csv, NOAA GHCN Daily weather, and
-- NOAA's GHCN Daily station list and per-station daily files, fetched from NCEI.

BEGIN;

-- One row per sonde reading, as recorded. Negative values (chlorophyll, ORP,
-- dissolved oxygen) are kept: they are sensor output, filter them in queries.
CREATE TABLE IF NOT EXISTS strontia_sonde_reading (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_row         integer NOT NULL UNIQUE,   -- row number in the xlsx; blocks double loads, orders rows sharing a timestamp
    measured_at        timestamp NOT NULL,        -- as recorded; the file states no time zone
    vertical_position  double precision NOT NULL, -- units not stated; small = near surface
    temp_c             double precision,
    conductivity       double precision,          -- units not stated
    ph                 double precision,
    orp_mv             double precision,
    turbidity_ntu      double precision,
    chlorophyll_ug_l   double precision,
    phycocyanin        double precision,          -- units not stated
    odo_pct_sat        double precision,          -- header reads "ODO & sat"
    odo_mg_l           double precision
);

CREATE INDEX IF NOT EXISTS strontia_sonde_reading_measured_at_idx
    ON strontia_sonde_reading (measured_at);

-- Each reading tagged with its cast (one profile through the water column).
-- A new cast starts after a gap of more than 30 minutes between readings.
-- cast_at is the cast's first reading, so every row of a cast shares it. Casts
-- start on a six-hour schedule (00, 06, 12, 18) and run 30 to 80 minutes.
-- Dropped first because CREATE OR REPLACE cannot insert a column mid-list.
DROP VIEW IF EXISTS strontia_cast_reading;
CREATE VIEW strontia_cast_reading AS
SELECT
    cast_no,
    min(measured_at) OVER (PARTITION BY cast_no) AS cast_at,
    id,
    source_row,
    measured_at,
    vertical_position,
    temp_c,
    conductivity,
    ph,
    orp_mv,
    turbidity_ntu,
    chlorophyll_ug_l,
    phycocyanin,
    odo_pct_sat,
    odo_mg_l
FROM (
    SELECT
        sum(new_cast) OVER (ORDER BY source_row) AS cast_no,
        id,
        source_row,
        measured_at,
        vertical_position,
        temp_c,
        conductivity,
        ph,
        orp_mv,
        turbidity_ntu,
        chlorophyll_ug_l,
        phycocyanin,
        odo_pct_sat,
        odo_mg_l
    FROM (
        SELECT
            r.*,
            CASE WHEN measured_at - lag(measured_at) OVER (ORDER BY source_row)
                      <= interval '30 minutes'
                 THEN 0 ELSE 1 END AS new_cast
        FROM strontia_sonde_reading r
    ) tagged
) numbered;

-- One row per day of lab results for water entering the Foothills treatment
-- plant: the target the models predict. The file has no January to March rows.
CREATE TABLE IF NOT EXISTS foothills_influent (
    sample_date  date PRIMARY KEY,           -- one row per day; blocks double loads
    toc_mg_l     double precision NOT NULL,  -- total organic carbon
    alk_mg_l     double precision NOT NULL   -- alkalinity; the file does not say "as CaCO3"
);

-- One row per station per day of NOAA GHCN Daily weather. Blank cells in the
-- file are missing observations and load as NULL, not zero.
CREATE TABLE IF NOT EXISTS noaa_daily_weather (
    station      text NOT NULL,              -- GHCN station id, e.g. USC00058022
    observed_on  date NOT NULL,
    prcp_in      double precision,           -- precipitation; the file states no unit, GHCN's standard unit is inches
    snow_in      double precision,           -- snowfall; same caveat
    tmax_f       double precision,           -- daily high, Fahrenheit
    tmin_f       double precision,           -- daily low, Fahrenheit
    PRIMARY KEY (station, observed_on)       -- blocks double loads
);

-- One row per GHCN Daily station worldwide, from ghcnd-stations.txt (format in
-- NCEI's GHCN Daily readme.txt, section IV). Station metadata, not measurements:
-- reloading updates rows in place, since NOAA revises it.
CREATE TABLE IF NOT EXISTS noaa_station (
    station       text PRIMARY KEY,          -- matches noaa_daily_weather.station
    latitude      double precision NOT NULL, -- decimal degrees
    longitude     double precision NOT NULL, -- decimal degrees
    elevation_m   double precision,          -- NULL where the file has -999.9 (missing)
    state         text,                      -- US postal code; NULL outside the US
    name          text NOT NULL,
    gsn_flag      text,                      -- 'GSN' for GCOS Surface Network stations, else NULL
    hcn_crn_flag  text,                      -- 'HCN' or 'CRN', else NULL
    wmo_id        text                       -- WMO station number, NULL if none
);

-- NOAA stations inside Denver Water's South Platte, Chatfield, Bear Creek, and
-- Upper Blue collection areas that reported precipitation from 2022-04-01 to
-- 2026-09-01. Derived, not loaded: find_collection_rain_stations.py replaces
-- every row on each run.
CREATE TABLE IF NOT EXISTS collection_area_rain_station (
    station          text PRIMARY KEY REFERENCES noaa_station,
    collection_area  text NOT NULL,          -- SYSTEM in Denver Water's Collection System layer
    first_prcp_on    date NOT NULL,          -- first day in the window with a PRCP value
    last_prcp_on     date NOT NULL,          -- last day in the window with a PRCP value
    prcp_days        integer NOT NULL        -- days in the window with a PRCP value; gaps are days without
);

COMMIT;
