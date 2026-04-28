from __future__ import annotations

import gzip
import json
import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import h3

from adsb_vfr.tiles import SCHEMA_VERSION
from adsb_vfr.tiles.airspace import write_airspace_outputs
from adsb_vfr.tiles.models import AltBinValue, Manifest, TileCell, TilePayload
from adsb_vfr.tiles.tile_math import ZOOM_TO_H3_RESOLUTION, TileKey, h3_cell_to_tile


@dataclass(frozen=True)
class BuildTilesConfig:
    input_path: Path
    output_dir: Path
    bbox: tuple[float, float, float, float] | None
    api_key: str
    cache_dir: Path
    refresh_airspace: bool


def _parse_bbox_text(value: str) -> tuple[float, float, float, float]:
    parts = [float(p.strip()) for p in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must have four values")
    return parts[0], parts[1], parts[2], parts[3]


def _read_latest_ingest(conn: duckdb.DuckDBPyConnection) -> tuple[tuple[float, float, float, float], str, str, str]:
    row = conn.execute(
        """
        SELECT bbox, CAST(start_date AS VARCHAR), CAST(end_date AS VARCHAR), classifier_config_hash
        FROM ingest_runs
        ORDER BY run_id DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise RuntimeError("ingest_runs is empty; run ingest first")
    return _parse_bbox_text(str(row[0])), str(row[1]), str(row[2]), str(row[3])


def _table_for(classification: str, resolution: int) -> str:
    return f"aggregates_{classification}_res{resolution}"


def _load_rows(
    conn: duckdb.DuckDBPyConnection,
    table_name: str,
) -> list[tuple[int, int, int, float, float, float, float, int]]:
    return conn.execute(
        f"""
        SELECT h3_cell, alt_bin, flight_count, time_seconds,
               sum_cos_track, sum_sin_track, sum_speed, point_count
        FROM {table_name}
        """
    ).fetchall()


def _rollup_to_res5(
    rows: list[tuple[int, int, int, float, float, float, float, int]],
) -> list[tuple[int, int, int, float, float, float, float, int]]:
    grouped: dict[tuple[int, int], dict[str, float | int]] = {}
    for row in rows:
        h3_cell, alt_bin, flight_count, time_seconds, sum_cos, sum_sin, sum_speed, point_count = row
        parent = int(h3.str_to_int(h3.cell_to_parent(h3.int_to_str(int(h3_cell)), 5)))
        key = (parent, int(alt_bin))
        agg = grouped.setdefault(
            key,
            {
                "flight_count": 0,
                "time_seconds": 0.0,
                "sum_cos": 0.0,
                "sum_sin": 0.0,
                "sum_speed": 0.0,
                "point_count": 0,
            },
        )
        agg["flight_count"] = int(agg["flight_count"]) + int(flight_count)
        agg["time_seconds"] = float(agg["time_seconds"]) + float(time_seconds)
        agg["sum_cos"] = float(agg["sum_cos"]) + float(sum_cos)
        agg["sum_sin"] = float(agg["sum_sin"]) + float(sum_sin)
        agg["sum_speed"] = float(agg["sum_speed"]) + float(sum_speed)
        agg["point_count"] = int(agg["point_count"]) + int(point_count)
    output: list[tuple[int, int, int, float, float, float, float, int]] = []
    for (h3_cell, alt_bin), agg in grouped.items():
        output.append(
            (
                h3_cell,
                alt_bin,
                int(agg["flight_count"]),
                float(agg["time_seconds"]),
                float(agg["sum_cos"]),
                float(agg["sum_sin"]),
                float(agg["sum_speed"]),
                int(agg["point_count"]),
            )
        )
    return output


def _build_tile_payloads(
    rows: list[tuple[int, int, int, float, float, float, float, int]],
    zoom: int,
    h3_resolution: int,
    bbox: tuple[float, float, float, float],
) -> tuple[dict[TileKey, list[TileCell]], set[int]]:
    min_lat, min_lon, max_lat, max_lon = bbox
    per_cell: dict[int, dict[str, object]] = {}
    alt_bins_seen: set[int] = set()
    for row in rows:
        h3_cell, alt_bin, flight_count, time_seconds, sum_cos, sum_sin, sum_speed, point_count = row
        lat, lon = h3.cell_to_latlng(h3.int_to_str(int(h3_cell)))
        if lat < min_lat or lat > max_lat or lon < min_lon or lon > max_lon:
            continue
        key = int(h3_cell)
        entry = per_cell.setdefault(
            key,
            {
                "time_seconds": 0.0,
                "flight_count": 0,
                "sum_cos": 0.0,
                "sum_sin": 0.0,
                "sum_speed": 0.0,
                "point_count": 0,
                "alt_bins": [],
            },
        )
        entry["time_seconds"] = float(entry["time_seconds"]) + float(time_seconds)
        entry["flight_count"] = int(entry["flight_count"]) + int(flight_count)
        entry["sum_cos"] = float(entry["sum_cos"]) + float(sum_cos)
        entry["sum_sin"] = float(entry["sum_sin"]) + float(sum_sin)
        entry["sum_speed"] = float(entry["sum_speed"]) + float(sum_speed)
        entry["point_count"] = int(entry["point_count"]) + int(point_count)
        entry["alt_bins"].append(AltBinValue(bin_index=int(alt_bin), time_seconds=float(time_seconds), flight_count=int(flight_count)))
        alt_bins_seen.add(int(alt_bin))

    tiles: dict[TileKey, list[TileCell]] = defaultdict(list)
    for h3_cell, agg in per_cell.items():
        time_seconds = float(agg["time_seconds"])
        point_count = int(agg["point_count"])
        mean_track_x = float(agg["sum_cos"]) / time_seconds if time_seconds > 0 else 0.0
        mean_track_y = float(agg["sum_sin"]) / time_seconds if time_seconds > 0 else 0.0
        coherence = min(1.0, math.sqrt(mean_track_x * mean_track_x + mean_track_y * mean_track_y))
        mean_speed = float(agg["sum_speed"]) / point_count if point_count > 0 else 0.0
        tile_key = h3_cell_to_tile(h3_cell, zoom=zoom)
        tiles[tile_key].append(
            TileCell(
                h3=h3.int_to_str(int(h3_cell)),
                flight_count=int(agg["flight_count"]),
                time_seconds=time_seconds,
                mean_track_x=mean_track_x,
                mean_track_y=mean_track_y,
                coherence=coherence,
                mean_speed=mean_speed,
                alt_bins=sorted(list(agg["alt_bins"]), key=lambda x: x.bin_index),
            )
        )
    return tiles, alt_bins_seen


def _write_tile_file(output_root: Path, classification: str, tile_key: TileKey, payload: TilePayload, logger: logging.Logger) -> None:
    tile_path = output_root / "tiles" / classification / f"z{tile_key.z}" / f"x{tile_key.x}"
    tile_path.mkdir(parents=True, exist_ok=True)
    output_file = tile_path / f"y{tile_key.y}.json.gz"
    with gzip.open(output_file, "wt", encoding="utf-8") as handle:
        handle.write(payload.model_dump_json())
    size = output_file.stat().st_size
    if size > 200 * 1024:
        logger.warning("Tile %s exceeds 200KB gz budget (%d bytes)", output_file, size)


def build_tiles(config: BuildTilesConfig, logger: logging.Logger | None = None) -> None:
    log = logger or logging.getLogger(__name__)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(config.input_path), read_only=True)
    default_bbox, start_date, end_date, config_hash = _read_latest_ingest(conn)
    bbox = config.bbox or default_bbox
    altitude_bins: set[int] = set()
    available_resolutions = sorted(set(ZOOM_TO_H3_RESOLUTION.values()))
    for classification in ("vfr", "ifr", "unknown"):
        rows_by_res: dict[int, list[tuple[int, int, int, float, float, float, float, int]]] = {}
        for resolution in (6, 7, 8, 9):
            table_name = _table_for(classification, resolution)
            rows_by_res[resolution] = _load_rows(conn, table_name)
        rows_by_res[5] = _rollup_to_res5(rows_by_res[6])
        for zoom, resolution in ZOOM_TO_H3_RESOLUTION.items():
            tiles, bins_seen = _build_tile_payloads(
                rows=rows_by_res[resolution],
                zoom=zoom,
                h3_resolution=resolution,
                bbox=bbox,
            )
            altitude_bins.update(bins_seen)
            for tile_key, cells in tiles.items():
                payload = TilePayload(
                    z=tile_key.z,
                    x=tile_key.x,
                    y=tile_key.y,
                    h3_resolution=resolution,
                    cells=cells,
                )
                _write_tile_file(config.output_dir, classification, tile_key, payload, logger=log)

    write_airspace_outputs(
        output_dir=config.output_dir,
        api_key=config.api_key,
        cache_dir=config.cache_dir,
        refresh=config.refresh_airspace,
        bbox=bbox,
        logger=log,
    )
    manifest = Manifest(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.now(tz=UTC),
        bbox=list(bbox),
        date_range={"start": start_date, "end": end_date},
        classifier_config_hash=config_hash,
        h3_resolutions=available_resolutions,
        altitude_bins=sorted(altitude_bins),
        classifications=["vfr", "ifr", "unknown"],
    )
    with (config.output_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        handle.write(manifest.model_dump_json(indent=2))
    conn.close()

