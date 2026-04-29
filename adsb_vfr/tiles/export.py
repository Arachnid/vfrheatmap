from __future__ import annotations

import gzip
import json
import logging
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import h3
import ray
from ray.data.aggregate import Sum

from adsb_vfr.tiles import SCHEMA_VERSION
from adsb_vfr.tiles.airspace import write_airspace_outputs
from adsb_vfr.tiles.models import AltBinValue, ClassificationScale, Manifest, ResolutionScale, TileCell, TilePayload
from adsb_vfr.tiles.tile_math import ZOOM_TO_H3_RESOLUTION, TileKey, h3_cell_to_tile

SCALE_SAMPLE_SIZE = 200_000

# Distinct H3 resolutions used on the map (multiple zooms share one resolution).
ROLLUP_H3_RESOLUTIONS: tuple[int, ...] = tuple(sorted(set(ZOOM_TO_H3_RESOLUTION.values())))


@dataclass(frozen=True)
class BuildTilesConfig:
    input_path: Path
    output_dir: Path
    bbox: tuple[float, float, float, float] | None
    start_date: date | None
    end_date: date | None
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


def _table_for(classification: str) -> str:
    return f"aggregates_{classification}"


def _resolve_date_range(
    config: BuildTilesConfig,
    latest_start: str,
    latest_end: str,
) -> tuple[date, date]:
    start = config.start_date or date.fromisoformat(latest_start)
    end = config.end_date or date.fromisoformat(latest_end)
    if start > end:
        raise ValueError("start_date must be <= end_date")
    return start, end


def _load_daily_res9_rows(
    conn: duckdb.DuckDBPyConnection,
    classification: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, float | int]]:
    table_name = _table_for(classification)
    rows = conn.execute(
        f"""
        SELECT
          h3_cell,
          alt_bin,
          SUM(flight_count) AS flight_count,
          SUM(time_seconds) AS time_seconds,
          SUM(sum_cos_track) AS sum_cos_track,
          SUM(sum_sin_track) AS sum_sin_track,
          SUM(sum_speed) AS sum_speed,
          SUM(point_count) AS point_count
        FROM {table_name}
        WHERE agg_date BETWEEN ? AND ?
        GROUP BY h3_cell, alt_bin
        """,
        [start_date, end_date],
    ).fetchall()
    return [
        {
            "h3_cell": int(h3_cell),
            "alt_bin": int(alt_bin),
            "flight_count": int(flight_count),
            "time_seconds": float(time_seconds),
            "sum_cos_track": float(sum_cos_track),
            "sum_sin_track": float(sum_sin_track),
            "sum_speed": float(sum_speed),
            "point_count": int(point_count),
        }
        for h3_cell, alt_bin, flight_count, time_seconds, sum_cos_track, sum_sin_track, sum_speed, point_count in rows
    ]


def _expand_base_row_to_all_resolutions(row: dict[str, float | int]) -> list[dict[str, float | int]]:
    """Emit one row per rollup resolution so a single Ray groupby can aggregate all map resolutions."""
    cell = int(row["h3_cell"])
    alt_bin = int(row["alt_bin"])
    flight_count = int(row["flight_count"])
    time_seconds = float(row["time_seconds"])
    sum_cos_track = float(row["sum_cos_track"])
    sum_sin_track = float(row["sum_sin_track"])
    sum_speed = float(row["sum_speed"])
    point_count = int(row["point_count"])
    out: list[dict[str, float | int]] = []
    for resolution in ROLLUP_H3_RESOLUTIONS:
        if resolution != 9:
            parent = int(h3.str_to_int(h3.cell_to_parent(h3.int_to_str(cell), resolution)))
        else:
            parent = cell
        out.append(
            {
                "h3_resolution": resolution,
                "h3_cell": parent,
                "alt_bin": alt_bin,
                "flight_count": flight_count,
                "time_seconds": time_seconds,
                "sum_cos_track": sum_cos_track,
                "sum_sin_track": sum_sin_track,
                "sum_speed": sum_speed,
                "point_count": point_count,
            }
        )
    return out


def _rollup_rows_by_h3_resolution(
    base_rows: list[dict[str, float | int]],
) -> dict[int, list[tuple[int, int, int, float, float, float, float, int]]]:
    """One Ray Data pipeline per classification: expand res-9 rows to all resolutions, then aggregate."""
    empty: dict[int, list[tuple[int, int, int, float, float, float, float, int]]] = {r: [] for r in ROLLUP_H3_RESOLUTIONS}
    if not base_rows:
        return empty
    ds = ray.data.from_items(base_rows)
    ds = ds.flat_map(_expand_base_row_to_all_resolutions)
    grouped = ds.groupby(["h3_resolution", "h3_cell", "alt_bin"]).aggregate(
        Sum("flight_count", alias_name="flight_count"),
        Sum("time_seconds", alias_name="time_seconds"),
        Sum("sum_cos_track", alias_name="sum_cos_track"),
        Sum("sum_sin_track", alias_name="sum_sin_track"),
        Sum("sum_speed", alias_name="sum_speed"),
        Sum("point_count", alias_name="point_count"),
    )
    rows_by: dict[int, list[tuple[int, int, int, float, float, float, float, int]]] = {r: [] for r in ROLLUP_H3_RESOLUTIONS}
    for row in grouped.take_all():
        r = int(row["h3_resolution"])
        rows_by[r].append(
            (
                int(row["h3_cell"]),
                int(row["alt_bin"]),
                int(row["flight_count"]),
                float(row["time_seconds"]),
                float(row["sum_cos_track"]),
                float(row["sum_sin_track"]),
                float(row["sum_speed"]),
                int(row["point_count"]),
            )
        )
    return rows_by


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


def _reservoir_add(sample: list[float], seen: int, value: float, rng: random.Random) -> int:
    seen += 1
    if len(sample) < SCALE_SAMPLE_SIZE:
        sample.append(value)
        return seen
    idx = rng.randrange(seen)
    if idx < SCALE_SAMPLE_SIZE:
        sample[idx] = value
    return seen


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    q = min(1.0, max(0.0, quantile))
    index = q * (len(sorted_values) - 1)
    low = int(math.floor(index))
    high = int(math.ceil(index))
    if low == high:
        return float(sorted_values[low])
    fraction = index - low
    return float(sorted_values[low] + (sorted_values[high] - sorted_values[low]) * fraction)


def build_tiles(config: BuildTilesConfig, logger: logging.Logger | None = None) -> None:
    log = logger or logging.getLogger(__name__)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(config.input_path), read_only=True)
    default_bbox, latest_start, latest_end, config_hash = _read_latest_ingest(conn)
    start_date, end_date = _resolve_date_range(config, latest_start=latest_start, latest_end=latest_end)
    bbox = config.bbox or default_bbox
    altitude_bins: set[int] = set()
    available_resolutions = list(ROLLUP_H3_RESOLUTIONS)
    classification_scales: dict[str, ClassificationScale] = {}
    rng = random.Random(20260429)
    ray_started_here = False
    if not ray.is_initialized():
        ray.init(ignore_reinit_error=True, num_gpus=0, logging_level=logging.ERROR)
        ray_started_here = True
    for classification in ("vfr", "ifr", "helicopter"):
        base_rows = _load_daily_res9_rows(
            conn=conn,
            classification=classification,
            start_date=start_date,
            end_date=end_date,
        )
        max_flight_count = 0.0
        max_time_seconds = 0.0
        scale_by_resolution: dict[int, dict[str, object]] = {
            resolution: {
                "flight_max": 0.0,
                "time_max": 0.0,
                "flight_sample": [],
                "time_sample": [],
                "flight_seen": 0,
                "time_seen": 0,
            }
            for resolution in available_resolutions
        }
        rows_by_h3_resolution = _rollup_rows_by_h3_resolution(base_rows)
        for zoom, resolution in ZOOM_TO_H3_RESOLUTION.items():
            rows = rows_by_h3_resolution[resolution]
            tiles, bins_seen = _build_tile_payloads(
                rows=rows,
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
                for cell in cells:
                    max_flight_count = max(max_flight_count, float(cell.flight_count))
                    max_time_seconds = max(max_time_seconds, float(cell.time_seconds))
                    stats = scale_by_resolution[resolution]
                    stats["flight_max"] = max(float(stats["flight_max"]), float(cell.flight_count))
                    stats["time_max"] = max(float(stats["time_max"]), float(cell.time_seconds))
                    stats["flight_seen"] = _reservoir_add(
                        stats["flight_sample"], int(stats["flight_seen"]), float(cell.flight_count), rng
                    )
                    stats["time_seen"] = _reservoir_add(
                        stats["time_sample"], int(stats["time_seen"]), float(cell.time_seconds), rng
                    )
                _write_tile_file(config.output_dir, classification, tile_key, payload, logger=log)
        by_resolution = {
            str(resolution): ResolutionScale(
                flight_count_max=float(stats["flight_max"]),
                time_seconds_max=float(stats["time_max"]),
                flight_count_p90=_percentile(stats["flight_sample"], 0.90),
                time_seconds_p90=_percentile(stats["time_sample"], 0.90),
            )
            for resolution, stats in scale_by_resolution.items()
        }
        classification_scales[classification] = ClassificationScale(
            flight_count_max=max_flight_count,
            time_seconds_max=max_time_seconds,
            by_resolution=by_resolution,
        )

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
        date_range={"start": start_date.isoformat(), "end": end_date.isoformat()},
        classifier_config_hash=config_hash,
        h3_resolutions=available_resolutions,
        altitude_bins=sorted(altitude_bins),
        classifications=["vfr", "ifr", "helicopter"],
        classification_scales=classification_scales,
    )
    with (config.output_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        handle.write(manifest.model_dump_json(indent=2))
    conn.close()
    if ray_started_here:
        ray.shutdown()

