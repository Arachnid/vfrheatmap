# ADS-B VFR Traffic Aggregation Pipeline

This project ingests historical ADS-B traces, applies pressure-altitude correction from ERA5, classifies flight segments, and writes H3/altitude aggregates into DuckDB for static tile serving.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## CDS API setup

ERA5 downloads use Copernicus CDS via `cdsapi`.

1. Create a CDS account and API key at [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu/)
2. Add `~/.cdsapirc`:

```text
url: https://cds.climate.copernicus.eu/api
key: <uid>:<api-key>
```

If this file is missing, ingest fails with a setup hint.

## Quick start

```bash
adsb-vfr ingest
```

Defaults:
- Date range: last 30 full UTC days (`--start-date`, `--end-date`)
- BBox: `49,-8,61,2`
- Cache dir: `./cache`
- Output DB: `./output/aggregates.duckdb`

Offline mode (requires pre-populated cache):

```bash
adsb-vfr ingest --skip-fetch
```

## CLI

`adsb-vfr ingest` options:
- `--start-date YYYY-MM-DD`
- `--end-date YYYY-MM-DD`
- `--bbox MINLAT,MINLON,MAXLAT,MAXLON`
- `--cache-dir PATH`
- `--output PATH`
- `--skip-fetch`
- `--download-concurrency N`
- `--ray-address ADDR`
- `--num-cpus N`
- `--object-store-memory-gb N`
- `--log-level {DEBUG,INFO,WARNING,ERROR}`

`adsb-vfr build-tiles` exists as a stub for future tile packaging.

## Cache behavior

Only immutable downloads are cached:
- `cache/traces/YYYY-MM-DD/YYYY-MM-DD.tar`
- `cache/era5/mslp_YYYY-MM_<bbox-hash>.nc`

Everything else is recomputed each run by design (no intermediate stage caches).

## Output schema

DuckDB includes:
- `aggregates_vfr_res{9,8,7,6}`
- `aggregates_ifr_res{9,8,7,6}`
- `aggregates_unknown_res{9,8,7,6}`
- `ingest_runs`

Aggregate columns: `h3_cell`, `alt_bin`, `vehicle_class`, `flight_count`, `time_seconds`, directional sums, `track_hist` (INTEGER[16]), speed moments, and `point_count`.

## Known limitations

- ADS-B coverage gaps are common at low altitude in rural terrain.
- MSLP is used as a QNH proxy; for this use case the error is much smaller than bin resolution.
- Rule-based classification can produce false positives/negatives.
- Entire Ray pipeline re-runs on every invocation (download cache only).

# ADS-B VFR Hotness

Ray-oriented ingest pipeline for ADS-B traces and ERA5 pressure correction.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
adsb-vfr ingest
```

## Notes

- Add a valid `~/.cdsapirc` to enable ERA5 downloads.
- Cache is stage-based under `./cache`.
- Use `--no-cache-<stage>` flags to invalidate stage outputs.
