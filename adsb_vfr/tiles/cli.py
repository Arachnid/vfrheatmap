from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import typer

from adsb_vfr.lib.openaip_key import resolve_openaip_api_key
from adsb_vfr.tiles.export import BuildTilesConfig, build_tiles


def parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    parts = [float(p.strip()) for p in value.split(",")]
    if len(parts) != 4:
        raise typer.BadParameter("--bbox must be MINLAT,MINLON,MAXLAT,MAXLON")
    return parts[0], parts[1], parts[2], parts[3]


def build_tiles_command(
    input_path: Path = typer.Option(Path("./output/aggregates.duckdb"), "--input", help="DuckDB file from ingest."),
    output_dir: Path = typer.Option(Path("./web/public/data"), "--output-dir", help="Output directory for static files."),
    bbox: str | None = typer.Option(None, "--bbox", help="MINLAT,MINLON,MAXLAT,MAXLON."),
    start_date: str | None = typer.Option(None, "--start-date", help="Inclusive start date YYYY-MM-DD."),
    end_date: str | None = typer.Option(None, "--end-date", help="Inclusive end date YYYY-MM-DD."),
    openaip_api_key: str | None = typer.Option(None, "--openaip-api-key", help="OpenAIP API key (or .openaip-api-key)."),
    openaip_key_file: Path | None = typer.Option(None, "--openaip-key-file", help="Optional OpenAIP API key file path."),
    cache_dir: Path = typer.Option(Path("./cache"), "--cache-dir"),
    refresh_airspace: bool = typer.Option(False, "--refresh-airspace"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO))
    api_key = resolve_openaip_api_key(openaip_api_key, dotfile_path=openaip_key_file)
    if not api_key:
        raise typer.BadParameter(
            "OpenAIP API key is required. Provide --openaip-api-key or add .openaip-api-key "
            "in the repo root or home directory (first non-comment line is used)."
        )
    cfg = BuildTilesConfig(
        input_path=input_path,
        output_dir=output_dir,
        bbox=parse_bbox(bbox),
        start_date=date.fromisoformat(start_date) if start_date else None,
        end_date=date.fromisoformat(end_date) if end_date else None,
        api_key=api_key,
        cache_dir=cache_dir,
        refresh_airspace=refresh_airspace,
    )
    build_tiles(cfg, logger=logging.getLogger(__name__))

