# ADS-B VFR Hotness

`adsb-vfr` ingests ADS-B traces, applies ERA5 pressure correction, classifies segments, and builds H3/altitude aggregates for static map rendering.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
```

## CDS API Setup

ERA5 downloads require a Copernicus CDS API key in `~/.cdsapirc`:

```text
url: https://cds.climate.copernicus.eu/api
key: <uid>:<api-key>
```

## Ingest Command

Run with defaults:

```bash
adsb-vfr ingest
```

Important options:
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
- `--openaip-api-key KEY`
- `--openaip-key-file PATH`
- `--refresh-airspace`
- `--log-level {DEBUG,INFO,WARNING,ERROR}`

Only immutable inputs are cached (`cache/traces`, `cache/era5`); the Ray pipeline recomputes every run.

## Build Tiles Command

`build-tiles` converts DuckDB aggregates into static files for the web app:

```bash
adsb-vfr build-tiles \
  --input ./output/aggregates.duckdb \
  --output-dir ./web/public/data
```

OpenAIP key lookup order:
- `--openaip-api-key`
- `--openaip-key-file /path/to/file`
- `./.openaip-api-key` (repo root)
- `~/.openaip-api-key`
- `OPENAIP_API_KEY` (fallback)

Example dotfile:

```text
# first non-comment line is used
your-openaip-key-here
```

Options:
- `--input PATH`
- `--output-dir PATH`
- `--bbox MINLAT,MINLON,MAXLAT,MAXLON` (defaults from latest `ingest_runs`)
- `--openaip-api-key KEY`
- `--openaip-key-file PATH`
- `--cache-dir PATH` (`cache/openaip` used internally)
- `--refresh-airspace`
- `--log-level {DEBUG,INFO,WARNING,ERROR}`

Output layout:
- `manifest.json`
- `tiles/{vfr|ifr|unknown}/z{z}/x{x}/y{y}.json.gz`
- `airspace/uk.geojson.gz`
- `airspace/style.json`

## Web Frontend

The static SPA is in `web/` (Vite + React + TypeScript + MapLibre + deck.gl).

Local development:

```bash
cd web
npm install
npm run dev
```

Production build:

```bash
cd web
npm run build
```

`web/public/data/` is populated by `adsb-vfr build-tiles`.

## GitHub Pages Deployment

Workflow: `.github/workflows/deploy.yml`

On push to `main`, it:
1. Installs Python project.
2. Retrieves DuckDB (release URL by default, LFS fallback).
3. Runs `adsb-vfr build-tiles`.
4. Builds `web/dist`.
5. Deploys via `actions/deploy-pages`.

Required secret:
- `OPENAIP_API_KEY`

Optional repo variable:
- `DUCKDB_RELEASE_URL` (if empty, workflow expects Git LFS file at `output/aggregates.duckdb`).

## Methodology Notes and Caveats

- VFR/IFR/unknown groups come from the rule-based segment classifier in the ingest pipeline.
- Altitudes are pressure-corrected with ERA5 MSLP as a QNH proxy.
- Coherence is derived from normalized directional vectors (`sum_cos_track`, `sum_sin_track`).
- Low-coherence cells intentionally suppress directional arrows.
- ADS-B reception is uneven at low altitude and in rural terrain.
- Classification can produce false positives and false negatives.
- Output is for exploratory analysis only, **not for operational flight planning**.

## Attribution

- ADS-B data: ADS-B Exchange / adsb.lol contributors
- Airspace data: OpenAIP
- Basemap: provider specified in frontend configuration
- Pressure data: ECMWF / Copernicus Climate Data Store (ERA5)
