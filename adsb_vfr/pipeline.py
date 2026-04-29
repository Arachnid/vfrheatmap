from __future__ import annotations

import hashlib
import logging
import tempfile
from functools import lru_cache
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import h3
import numpy as np
import pandas as pd
import ray
from ray.data.aggregate import Count, CountDistinct, Sum
from shapely.geometry import LineString, Polygon

from adsb_vfr.config import ClassifierConfig
from adsb_vfr.lib.airspace_lookup import AirspaceLookup
from adsb_vfr.lib.classifier import VFR_CLASSES, SegmentFeatures, classify_segment, is_always_ifr_emitter, is_always_vfr_type
from adsb_vfr.lib.era5_lookup import Era5Lookup
from adsb_vfr.lib.geo import great_circle_distance_nm, h3_cell, initial_bearing_deg
from adsb_vfr.lib.trace_format import iter_trace_tarball_points

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestResult:
    temp_dir: Path
    pipeline_output_dir: Path


def _base_unified_row(row_type: str) -> dict[str, Any]:
    return {
        "row_type": row_type,
        "classification_group": None,
        "resolution": None,
        "h3_cell": None,
        "alt_bin": None,
        "flight_count": None,
        "time_seconds": None,
        "sum_cos_track": None,
        "sum_sin_track": None,
        "sum_speed": None,
        "sum_speed_sq": None,
        "agg_point_count": None,
        "vehicle_class": None,
    }


def to_unified_aggregate_row(row: dict[str, Any]) -> dict[str, Any]:
    out = _base_unified_row("aggregate")
    out.update(
        {
            "classification_group": str(row["classification_group"]),
            "resolution": int(row["resolution"]),
            "h3_cell": int(row["h3_cell"]),
            "alt_bin": int(row["alt_bin"]),
            "vehicle_class": str(row["vehicle_class"]),
            "flight_count": int(row["flight_count"]),
            "time_seconds": float(row["time_seconds"]),
            "sum_cos_track": float(row["sum_cos_track"]),
            "sum_sin_track": float(row["sum_sin_track"]),
            "sum_speed": float(row["sum_speed"]),
            "sum_speed_sq": float(row["sum_speed_sq"]),
            "agg_point_count": int(row["point_count"]),
        }
    )
    return out


def _get_lookup(ref: ray.ObjectRef) -> Era5Lookup:
    lookup = ray.get(ref)
    if not isinstance(lookup, Era5Lookup):
        raise TypeError("Expected Era5Lookup in Ray object store.")
    return lookup


def _get_airspace_lookup(ref: ray.ObjectRef | None) -> AirspaceLookup:
    if ref is None:
        return AirspaceLookup.empty()
    lookup = ray.get(ref)
    if not isinstance(lookup, AirspaceLookup):
        raise TypeError("Expected AirspaceLookup in Ray object store.")
    return lookup


def _segment_id(hex_id: str, start_ts: pd.Timestamp, end_ts: pd.Timestamp, squawk: str, icao_type: str) -> int:
    payload = f"{hex_id}|{start_ts.isoformat()}|{end_ts.isoformat()}|{squawk}|{icao_type}"
    digest = hashlib.blake2b(payload.encode("utf-8"), digest_size=8).digest()
    # Keep IDs in signed 64-bit range for Arrow/Ray compatibility.
    return int.from_bytes(digest, byteorder="big", signed=False) & ((1 << 63) - 1)


def _point_in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    min_lat, min_lon, max_lat, max_lon = bbox
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon


def parse_correct_flatmap(
    item: dict[str, Any],
    era5_ref: ray.ObjectRef,
    bbox: tuple[float, float, float, float],
) -> list[dict[str, Any]]:
    lookup = _get_lookup(era5_ref)
    tarball_path = Path(item["tarball_path"])
    out_rows: list[dict[str, Any]] = []
    chunk: list[dict[str, Any]] = []

    def flush() -> None:
        if not chunk:
            return
        pressure = np.array([r["alt_pressure_ft"] for r in chunk], dtype=np.float64)
        lats = np.array([r["lat"] for r in chunk], dtype=np.float64)
        lons = np.array([r["lon"] for r in chunk], dtype=np.float64)
        times = np.array([r["timestamp"] for r in chunk], dtype="datetime64[ns]")
        alt_qnh = lookup.correct_altitudes(pressure_alt_ft=pressure, lats=lats, lons=lons, timestamps=times)
        for row, corrected in zip(chunk, alt_qnh):
            out_rows.append(
                {
                    "hex_id": row["hex_id"],
                    "timestamp": row["timestamp"],
                    "lat": row["lat"],
                    "lon": row["lon"],
                    "alt_pressure_ft": row["alt_pressure_ft"],
                    "alt_qnh_ft": float(corrected),
                    "ground_speed_kt": row["ground_speed_kt"],
                    "track_deg": row["track_deg"],
                    "squawk": row["squawk"],
                    "icao_type": row["icao_type"],
                    "emitter_category": row["emitter_category"],
                }
            )
        chunk.clear()

    malformed_counter = [0]
    for row in iter_trace_tarball_points(tarball_path=tarball_path, malformed_counter=malformed_counter):
        if not _point_in_bbox(row["lat"], row["lon"], bbox):
            continue
        chunk.append(row)
        if len(chunk) >= 5000:
            flush()
    flush()
    if malformed_counter[0]:
        LOGGER.warning("Skipped %s malformed records in %s", malformed_counter[0], tarball_path)
    return out_rows


def _build_edge_rows(
    batch: pd.DataFrame,
    classifier_config: ClassifierConfig,
    airspace_ref: ray.ObjectRef | None = None,
    airspace_lookup: AirspaceLookup | None = None,
) -> pd.DataFrame:
    if batch.empty:
        return pd.DataFrame()
    batch = batch.sort_values(["hex_id", "timestamp"]).reset_index(drop=True)
    gap_s = classifier_config.thresholds.gap_seconds
    resolved_airspace_lookup = airspace_lookup if airspace_lookup is not None else _get_airspace_lookup(airspace_ref)
    outputs: list[dict[str, Any]] = []

    for hex_id, g in batch.groupby("hex_id", sort=False):
        g = g.sort_values("timestamp").reset_index(drop=True)
        if len(g) < 2:
            continue
        # Statefully carry metadata forward for sparse point feeds.
        g["squawk"] = g["squawk"].astype("string").fillna("").str.strip()
        g["icao_type"] = g["icao_type"].astype("string").fillna("").str.strip()
        g["emitter_category"] = g["emitter_category"].astype("string").fillna("").str.strip()
        g["squawk"] = g["squawk"].replace("", pd.NA).ffill().fillna("")
        g["icao_type"] = g["icao_type"].replace("", pd.NA).ffill().bfill().fillna("")
        g["emitter_category"] = g["emitter_category"].replace("", pd.NA).ffill().bfill().fillna("")
        first_emitter = str(g.iloc[0]["emitter_category"])
        first_icao_type = str(g.iloc[0]["icao_type"])
        journey_force_ifr = is_always_ifr_emitter(first_emitter)
        journey_force_vfr = (not journey_force_ifr) and is_always_vfr_type(first_icao_type)
        journey_force_classification: str | None = None
        if journey_force_ifr:
            journey_force_classification = "ifr"
        elif journey_force_vfr:
            journey_force_classification = "vfr_type"

        if journey_force_classification is None:
            class_a_hits, any_airspace_hits = resolved_airspace_lookup.flags_for_points(
                lats=g["lat"].to_numpy(dtype=np.float64),
                lons=g["lon"].to_numpy(dtype=np.float64),
            )
            g["in_class_a"] = class_a_hits
            g["in_any_airspace"] = any_airspace_hits
        else:
            # List-based hard classification: skip behavioral airspace evaluation entirely.
            g["in_class_a"] = False
            g["in_any_airspace"] = False
        journey_all_controlled = bool(g["in_any_airspace"].all())
        split_indices = [0]
        prev = g.iloc[0]
        for idx in range(1, len(g)):
            row = g.iloc[idx]
            ts_gap = (row["timestamp"] - prev["timestamp"]).total_seconds()
            changed = (
                ts_gap > gap_s
                or str(row["squawk"]) != str(prev["squawk"])
            )
            if changed:
                split_indices.append(idx)
            prev = row
        split_indices.append(len(g))

        segment_infos: list[dict[str, Any]] = []
        for start_idx, end_idx in zip(split_indices[:-1], split_indices[1:]):
            seg = g.iloc[start_idx:end_idx].copy()
            if len(seg) < 2:
                continue
            start_ts = pd.Timestamp(seg.iloc[0]["timestamp"])
            end_ts = pd.Timestamp(seg.iloc[-1]["timestamp"])
            seg_id = _segment_id(
                hex_id=hex_id,
                start_ts=start_ts,
                end_ts=end_ts,
                squawk=str(seg.iloc[-1]["squawk"]),
                icao_type=str(seg.iloc[-1]["icao_type"]),
            )
            features = SegmentFeatures(
                squawk=str(seg.iloc[-1]["squawk"]),
                icao_type=str(seg.iloc[-1]["icao_type"]),
                emitter_category=str(seg.iloc[-1]["emitter_category"]),
                max_alt_qnh_ft=float(seg["alt_qnh_ft"].max()),
                straightness=0.0,
            )
            base_classification, vehicle_class = classify_segment(features, classifier_config)
            squawk = str(seg.iloc[-1]["squawk"])
            squawk_is_vfr = squawk == "7000" or squawk in classifier_config.listening_squawks
            squawk_is_ifr = False
            if squawk.isdigit():
                squawk_value = int(squawk)
                squawk_is_ifr = any(start <= squawk_value <= end for start, end in classifier_config.ifr_discrete_ranges)
            segment_infos.append(
                {
                    "segment_id": seg_id,
                    "segment_df": seg,
                    "base_classification": base_classification,
                    "vehicle_class": vehicle_class,
                    "squawk_is_vfr": squawk_is_vfr,
                    "squawk_is_ifr": squawk_is_ifr,
                    "has_class_g": bool((~seg["in_any_airspace"]).any()),
                    "has_class_a": bool(seg["in_class_a"].any()),
                }
            )

        status_by_segment: list[str] = ["unknown"] * len(segment_infos)
        current_status = "unknown"
        if journey_force_classification is not None:
            status_by_segment = ["unknown"] * len(segment_infos)
        elif journey_all_controlled:
            status_by_segment = ["ifr"] * len(segment_infos)
            current_status = "ifr"
        for idx, info in enumerate(segment_infos):
            if journey_all_controlled:
                continue
            evidence_ifr = bool(info["squawk_is_ifr"]) or bool(info["has_class_a"])
            evidence_vfr = bool(info["squawk_is_vfr"]) or bool(info["has_class_g"])
            # Keep IFR sticky once observed for the journey unless we see fresh IFR evidence.
            # This avoids downgrading instrument arrivals to VFR after transient Class G detections.
            if current_status == "ifr" and not evidence_ifr:
                status_by_segment[idx] = "ifr"
            elif evidence_ifr:
                current_status = "ifr"
                status_by_segment[idx] = "ifr"
            elif evidence_vfr:
                current_status = "vfr"
                status_by_segment[idx] = "vfr"
            else:
                status_by_segment[idx] = current_status
            if status_by_segment[idx] in {"ifr", "vfr"}:
                backfill_idx = idx - 1
                while backfill_idx >= 0 and status_by_segment[backfill_idx] == "unknown":
                    status_by_segment[backfill_idx] = status_by_segment[idx]
                    backfill_idx -= 1

        for info, persistent_status in zip(segment_infos, status_by_segment):
            seg = info["segment_df"]
            classification = str(info["base_classification"])
            if journey_force_classification == "ifr":
                classification = "ifr"
            elif journey_force_classification == "vfr_type":
                classification = "vfr_type"
            else:
                if persistent_status == "ifr":
                    classification = "ifr"
                elif persistent_status == "vfr":
                    if classification not in VFR_CLASSES:
                        # Keep VFR-group semantics while preserving existing fine-grained labels when possible.
                        classification = "vfr_medium"

            for i in range(1, len(seg)):
                p1 = seg.iloc[i - 1]
                p2 = seg.iloc[i]
                duration = float((p2["timestamp"] - p1["timestamp"]).total_seconds())
                if duration <= 0:
                    continue
                p1_track = p1.get("track_deg")
                if pd.isna(p1_track):
                    track_deg = initial_bearing_deg(
                        float(p1["lat"]),
                        float(p1["lon"]),
                        float(p2["lat"]),
                        float(p2["lon"]),
                    )
                else:
                    track_deg = float(p1_track) % 360.0

                p1_speed = p1.get("ground_speed_kt")
                if pd.isna(p1_speed):
                    distance_nm = great_circle_distance_nm(
                        float(p1["lat"]),
                        float(p1["lon"]),
                        float(p2["lat"]),
                        float(p2["lon"]),
                    )
                    ground_speed_kt = float(distance_nm * 3600.0 / duration)
                else:
                    ground_speed_kt = max(0.0, float(p1_speed))
                outputs.append(
                    {
                        "segment_id": int(info["segment_id"]),
                        "hex_id": hex_id,
                        "classification": classification,
                        "vehicle_class": str(info["vehicle_class"]),
                        "start_ts": p1["timestamp"],
                        "end_ts": p2["timestamp"],
                        "start_lat": float(p1["lat"]),
                        "start_lon": float(p1["lon"]),
                        "end_lat": float(p2["lat"]),
                        "end_lon": float(p2["lon"]),
                        "start_alt_qnh_ft": float(p1["alt_qnh_ft"]),
                        "end_alt_qnh_ft": float(p2["alt_qnh_ft"]),
                        "track_deg": track_deg,
                        "ground_speed_kt": ground_speed_kt,
                        "edge_duration_s": duration,
                    }
                )
    return pd.DataFrame(outputs)


def segment_to_edges_batch(
    batch: pd.DataFrame,
    classifier_config: ClassifierConfig,
    airspace_ref: ray.ObjectRef | None = None,
    airspace_lookup: AirspaceLookup | None = None,
) -> pd.DataFrame:
    return _build_edge_rows(
        batch=batch,
        classifier_config=classifier_config,
        airspace_ref=airspace_ref,
        airspace_lookup=airspace_lookup,
    )


@lru_cache(maxsize=200_000)
def _cell_polygon(cell_id: str) -> Polygon:
    boundary = h3.cell_to_boundary(cell_id)
    return Polygon([(float(lon), float(lat)) for lat, lon in boundary])


@lru_cache(maxsize=200_000)
def _path_cells_res9(start_cell: str, end_cell: str) -> tuple[str, ...]:
    try:
        path_cells = list(h3.grid_path_cells(start_cell, end_cell))
    except Exception:
        path_cells = [start_cell, end_cell]
    return tuple(path_cells)


def _line_components(geometry: Any) -> list[LineString]:
    geom_type = geometry.geom_type
    if geom_type == "LineString":
        return [geometry]
    if geom_type == "MultiLineString":
        return [part for part in geometry.geoms if part.length > 0]
    if geom_type == "GeometryCollection":
        out: list[LineString] = []
        for part in geometry.geoms:
            if part.geom_type == "LineString" and part.length > 0:
                out.append(part)
            elif part.geom_type == "MultiLineString":
                out.extend([sub for sub in part.geoms if sub.length > 0])
        return out
    return []


def _intersection_rows_for_cells(
    line: LineString,
    cells: set[str],
) -> tuple[list[tuple[str, float, float, float, float]], float]:
    line_len = float(line.length)
    if line_len <= 0:
        return [], 0.0
    intersections: list[tuple[str, float, float, float, float]] = []
    total_intersection_length = 0.0
    x1, y1 = map(float, line.coords[0])
    x2, y2 = map(float, line.coords[-1])
    dx = x2 - x1
    dy = y2 - y1
    denom = max((dx * dx) + (dy * dy), 1e-12)
    for cell in cells:
        clipped = line.intersection(_cell_polygon(cell))
        for component in _line_components(clipped):
            seg_len = float(component.length)
            if seg_len <= 0:
                continue
            midpoint = component.interpolate(0.5, normalized=True)
            mx = float(midpoint.x)
            my = float(midpoint.y)
            # Parametric fraction along the source segment in [0, 1].
            frac = ((mx - x1) * dx + (my - y1) * dy) / denom
            frac = max(0.0, min(1.0, frac))
            intersections.append((cell, seg_len, frac, my, mx))
            total_intersection_length += seg_len
    return intersections, total_intersection_length


def edge_to_cell_intersections(edge: dict[str, Any]) -> list[dict[str, Any]]:
    lat1 = float(edge["start_lat"])
    lon1 = float(edge["start_lon"])
    lat2 = float(edge["end_lat"])
    lon2 = float(edge["end_lon"])
    line = LineString([(lon1, lat1), (lon2, lat2)])
    if line.length <= 0:
        return []

    duration = float(edge["edge_duration_s"])
    if duration <= 0:
        return []

    start_cell = h3_cell(lat1, lon1, resolution=9)
    end_cell = h3_cell(lat2, lon2, resolution=9)
    path_cells = set(_path_cells_res9(start_cell, end_cell))
    intersections, total_intersection_length = _intersection_rows_for_cells(line, path_cells)

    # Fast path: most segments are fully covered by the direct cell path.
    # Expand to neighboring cells only when coverage suggests a miss.
    line_len = float(line.length)
    coverage_ratio = total_intersection_length / max(line_len, 1e-9)
    if coverage_ratio < 0.995:
        expanded_cells = set(path_cells)
        for cell in path_cells:
            expanded_cells.update(h3.grid_disk(cell, 1))
        extra_cells = expanded_cells.difference(path_cells)
        extra_intersections, extra_length = _intersection_rows_for_cells(line, extra_cells)
        if extra_intersections:
            intersections.extend(extra_intersections)
            total_intersection_length += extra_length

    if not intersections:
        midpoint = line.interpolate(0.5, normalized=True)
        intersections.append((start_cell, float(line.length), 0.5, float(midpoint.y), float(midpoint.x)))
        total_intersection_length = float(line.length)

    start_alt = float(edge["start_alt_qnh_ft"])
    alt_delta = float(edge["end_alt_qnh_ft"]) - start_alt
    out: list[dict[str, Any]] = []
    denom = max(total_intersection_length, 1e-9)
    for cell, seg_len, frac, lat_mid, lon_mid in intersections:
        alt = start_alt + alt_delta * frac
        out.append(
            {
                "segment_id": int(edge["segment_id"]),
                "classification": str(edge["classification"]),
                "vehicle_class": str(edge["vehicle_class"]),
                "lat": lat_mid,
                "lon": lon_mid,
                "alt_qnh_ft": alt,
                "track_deg": float(edge["track_deg"]),
                "ground_speed_kt": float(edge["ground_speed_kt"]),
                "time_weight": duration * (seg_len / denom),
                "res9_idx": cell,
            }
        )
    return out


def add_aggregate_keys(row: dict[str, Any]) -> dict[str, Any]:
    classification = str(row["classification"])
    vehicle_class = str(row["vehicle_class"])
    group: str | None
    if classification in VFR_CLASSES or vehicle_class == "helicopter":
        group = "vfr"
    elif classification == "ifr":
        group = "ifr"
    elif classification == "unknown":
        group = "unknown"
    else:
        group = None
    if group is None:
        row["classification_group"] = None
        return row
    alt_bin = int(np.clip(np.floor(float(row["alt_qnh_ft"]) / 100.0), 0, 119))
    row["classification_group"] = group
    row["alt_bin"] = alt_bin
    return row


def explode_resolutions(row: dict[str, Any]) -> list[dict[str, Any]]:
    track = float(row["track_deg"])
    weight = float(row["time_weight"])
    res9_idx = str(row.get("res9_idx") or h3_cell(float(row["lat"]), float(row["lon"]), resolution=9))
    res9_cell = int(h3.str_to_int(res9_idx))
    out_rows: list[dict[str, Any]] = []
    for resolution in (9, 8, 7, 6):
        cell = res9_cell
        if resolution != 9:
            parent = h3.cell_to_parent(res9_idx, resolution)
            cell = int(h3.str_to_int(parent))
        record = dict(row)
        record["resolution"] = resolution
        record["h3_cell"] = cell
        record["sum_cos_track"] = float(np.cos(np.deg2rad(track)) * weight)
        record["sum_sin_track"] = float(np.sin(np.deg2rad(track)) * weight)
        record["sum_speed"] = float(row["ground_speed_kt"]) * weight
        record["sum_speed_sq"] = float(row["ground_speed_kt"] ** 2) * weight
        record["point_weight"] = weight
        out_rows.append(record)
    return out_rows


def build_and_run_pipeline(
    trace_items: list[tuple[date, Path]],
    era5_ref: ray.ObjectRef,
    classifier_config: ClassifierConfig,
    bbox: tuple[float, float, float, float],
    airspace_ref: ray.ObjectRef | None = None,
) -> IngestResult:
    temp_dir = Path(tempfile.mkdtemp(prefix="adsb_vfr_"))
    pipeline_output_dir = temp_dir / "pipeline_output"

    source_items = [{"date": d.isoformat(), "tarball_path": str(p)} for d, p in trace_items]
    ds = ray.data.from_items(source_items)
    points_ds = ds.flat_map(
        parse_correct_flatmap,
        fn_kwargs={"era5_ref": era5_ref, "bbox": bbox},
    )
    # Keep shuffle parallelism stable regardless of date-range length.
    # Basing partitions on number of days causes severe skew for single-day runs.
    available_cpus = int(ray.available_resources().get("CPU", 1))
    partition_count = max(16, min(256, available_cpus * 8))
    points_ds = points_ds.repartition(num_blocks=partition_count, shuffle=True, keys=["hex_id"])

    edges_ds = points_ds.map_batches(
        segment_to_edges_batch,
        batch_format="pandas",
        fn_kwargs={"classifier_config": classifier_config, "airspace_ref": airspace_ref},
    )
    intersections_ds = edges_ds.flat_map(edge_to_cell_intersections)
    keyed_ds = intersections_ds.map(add_aggregate_keys).filter(lambda r: r.get("classification_group") is not None)
    exploded_ds = keyed_ds.flat_map(explode_resolutions)

    group_keys = ["classification_group", "resolution", "h3_cell", "alt_bin", "vehicle_class"]
    aggregates_ds = exploded_ds.groupby(group_keys).aggregate(
        Sum("point_weight", alias_name="time_seconds"),
        Sum("sum_cos_track", alias_name="sum_cos_track"),
        Sum("sum_sin_track", alias_name="sum_sin_track"),
        Sum("sum_speed", alias_name="sum_speed"),
        Sum("sum_speed_sq", alias_name="sum_speed_sq"),
        Count(alias_name="point_count"),
        CountDistinct("segment_id", alias_name="flight_count"),
    )
    unified_aggregates_ds = aggregates_ds.map(to_unified_aggregate_row)
    unified_aggregates_ds.write_parquet(str(pipeline_output_dir))
    return IngestResult(
        temp_dir=temp_dir,
        pipeline_output_dir=pipeline_output_dir,
    )


def load_era5_lookup(era5_paths: list[Path], bbox: tuple[float, float, float, float], start: date, end: date) -> Era5Lookup:
    lookup = Era5Lookup.from_netcdfs(era5_paths)
    ds = lookup.dataset
    min_lat, min_lon, max_lat, max_lon = bbox
    lat_vals = np.array(ds["latitude"].values)
    lon_vals = np.array(ds["longitude"].values)
    if lat_vals.min() > min_lat or lat_vals.max() < max_lat or lon_vals.min() > min_lon or lon_vals.max() < max_lon:
        raise ValueError("Cached ERA5 files do not fully cover the requested bounding box.")
    time_name = "time" if "time" in ds.coords else "valid_time"
    times = pd.to_datetime(ds[time_name].values, utc=True)
    if times.min().date() > start or times.max().date() < end:
        raise ValueError("Cached ERA5 files do not fully cover the requested date range.")
    return lookup

