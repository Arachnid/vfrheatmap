from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import ray
import typer

from adsb_vfr.config import DEFAULT_BBOX, load_classifier_config
from adsb_vfr.download import ensure_inputs
from adsb_vfr.lib.airspace_lookup import load_airspace_lookup
from adsb_vfr.lib.openaip_key import resolve_openaip_api_key
from adsb_vfr.finalise import FinaliseInput, finalise_to_duckdb
from adsb_vfr.pipeline import build_and_run_pipeline, load_era5_lookup
from adsb_vfr.tiles.cli import build_tiles_command

app = typer.Typer(help="ADS-B VFR aggregation tools.")


def _parse_date(value: str | None, default: date) -> date:
    if value is None:
        return default
    return date.fromisoformat(value)


def _parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(p.strip()) for p in value.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter("--bbox must be MINLAT,MINLON,MAXLAT,MAXLON")
    return parts[0], parts[1], parts[2], parts[3]


@app.command("ingest")
def ingest(
    start_date: str | None = typer.Option(None, "--start-date", help="Inclusive start date YYYY-MM-DD"),
    end_date: str | None = typer.Option(None, "--end-date", help="Inclusive end date YYYY-MM-DD"),
    bbox: str = typer.Option(",".join(str(x) for x in DEFAULT_BBOX), "--bbox"),
    cache_dir: Path = typer.Option(Path("./cache"), "--cache-dir"),
    output: Path = typer.Option(Path("./output/aggregates.duckdb"), "--output"),
    skip_fetch: bool = typer.Option(False, "--skip-fetch", help="Fail if downloads are missing."),
    download_concurrency: int = typer.Option(4, "--download-concurrency"),
    ray_address: str = typer.Option("", "--ray-address"),
    num_cpus: int | None = typer.Option(None, "--num-cpus"),
    object_store_memory_gb: int | None = typer.Option(None, "--object-store-memory-gb"),
    openaip_api_key: str | None = typer.Option(
        None,
        "--openaip-api-key",
        help="OpenAIP API key for airspace-assisted IFR/VFR propagation (or .openaip-api-key).",
    ),
    openaip_key_file: Path | None = typer.Option(
        None,
        "--openaip-key-file",
        help="Optional OpenAIP API key file path.",
    ),
    refresh_airspace: bool = typer.Option(False, "--refresh-airspace", help="Refresh cached OpenAIP pages."),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    started_at = datetime.now(tz=UTC)
    today = datetime.now(tz=UTC).date()
    start = _parse_date(start_date, default=today - timedelta(days=30))
    end = _parse_date(end_date, default=today - timedelta(days=1))
    if start > end:
        raise typer.BadParameter("--start-date must be <= --end-date")
    bbox_tuple = _parse_bbox(bbox)
    config_dir = Path("config")
    classifier_config = load_classifier_config(config_dir)

    if ray_address:
        ray.init(address=ray_address, ignore_reinit_error=True, logging_level=log_level.upper())
    else:
        ray_kwargs: dict[str, object] = {
            "ignore_reinit_error": True,
            "logging_level": log_level.upper(),
            # Avoid Ray Data reserving fractional GPU resources for shuffle/aggregate
            # on machines that expose a desktop GPU but where we run CPU-only workloads.
            "num_gpus": 0,
        }
        if num_cpus is not None:
            ray_kwargs["num_cpus"] = num_cpus
        if object_store_memory_gb is not None:
            ray_kwargs["object_store_memory"] = int(object_store_memory_gb * 1024 * 1024 * 1024)
        ray.init(**ray_kwargs)

    manifest = asyncio.run(
        ensure_inputs(
            start_date=start,
            end_date=end,
            bbox=bbox_tuple,
            cache_dir=cache_dir,
            skip_fetch=skip_fetch,
            download_concurrency=download_concurrency,
        )
    )

    era5_lookup = load_era5_lookup(era5_paths=manifest.era5_files, bbox=bbox_tuple, start=start, end=end)
    era5_ref = ray.put(era5_lookup)
    api_key = resolve_openaip_api_key(openaip_api_key, dotfile_path=openaip_key_file)
    airspace_lookup = load_airspace_lookup(
        cache_dir=cache_dir,
        bbox=bbox_tuple,
        api_key=api_key,
        refresh=refresh_airspace,
    )
    airspace_ref = ray.put(airspace_lookup)
    ingest_result = build_and_run_pipeline(
        trace_items=manifest.trace_files,
        era5_ref=era5_ref,
        classifier_config=classifier_config,
        bbox=bbox_tuple,
        airspace_ref=airspace_ref,
    )
    finished_at = datetime.now(tz=UTC)
    finalise_to_duckdb(
        FinaliseInput(
            output_path=output,
            started_at=started_at,
            finished_at=finished_at,
            start_date=start,
            end_date=end,
            bbox=bbox_tuple,
            classifier_config=classifier_config,
            ingest_result=ingest_result,
        )
    )
    logging.getLogger(__name__).info("Ingest complete: aggregate tables written to %s", output)
    ray.shutdown()


@app.command("build-tiles")
def build_tiles(
    input_path: Path = typer.Option(Path("./output/aggregates.duckdb"), "--input", help="DuckDB file from ingest."),
    output_dir: Path = typer.Option(Path("./web/public/data"), "--output-dir", help="Output directory for static files."),
    bbox: str | None = typer.Option(None, "--bbox", help="MINLAT,MINLON,MAXLAT,MAXLON."),
    openaip_api_key: str | None = typer.Option(None, "--openaip-api-key", help="OpenAIP API key (or .openaip-api-key)."),
    openaip_key_file: Path | None = typer.Option(None, "--openaip-key-file", help="Optional OpenAIP API key file path."),
    cache_dir: Path = typer.Option(Path("./cache"), "--cache-dir"),
    refresh_airspace: bool = typer.Option(False, "--refresh-airspace"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    build_tiles_command(
        input_path=input_path,
        output_dir=output_dir,
        bbox=bbox,
        openaip_api_key=openaip_api_key,
        openaip_key_file=openaip_key_file,
        cache_dir=cache_dir,
        refresh_airspace=refresh_airspace,
        log_level=log_level,
    )


if __name__ == "__main__":
    app()

