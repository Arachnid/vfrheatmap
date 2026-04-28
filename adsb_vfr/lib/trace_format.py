from __future__ import annotations

import gzip
import io
import logging
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import orjson

LOGGER = logging.getLogger(__name__)


def _should_process_trace_member(name: str) -> bool:
    normalised = name.lstrip("./")
    if not normalised.endswith(".json"):
        return False
    if "trace_full_" in normalised:
        return True
    base = normalised.rsplit("/", 1)[-1]
    return base.startswith("trace_")


def _decode_member_payload(raw: bytes) -> dict[str, Any] | None:
    try:
        decoded = gzip.decompress(raw) if raw.startswith(b"\x1f\x8b") else raw
        payload = orjson.loads(decoded)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(payload, dict):
        return payload
    return None


def _coerce_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_trace_point(point: list[Any], base_time: datetime) -> dict[str, Any] | None:
    if len(point) < 4:
        return None

    ts_offset = point[0]
    lat = point[1]
    lon = point[2]
    alt_baro = point[3]
    point_meta = point[8] if len(point) > 8 and isinstance(point[8], dict) else {}
    speed = point[4] if len(point) > 4 and point[4] is not None else point_meta.get("gs", point_meta.get("speed"))
    track = point[5] if len(point) > 5 and point[5] is not None else point_meta.get("track", point_meta.get("heading"))
    squawk = point[11] if len(point) > 11 and point[11] is not None else point_meta.get("squawk", "")

    if alt_baro == "ground" or alt_baro is None:
        return None
    try:
        timestamp = base_time + timedelta(seconds=int(ts_offset))
        return {
            "timestamp": timestamp,
            "lat": float(lat),
            "lon": float(lon),
            "alt_pressure_ft": float(alt_baro),
            "ground_speed_kt": _coerce_optional_float(speed),
            "track_deg": _coerce_optional_float(track),
            "squawk": str(squawk or ""),
        }
    except (ValueError, TypeError):
        return None


def iter_trace_tarball_points(
    tarball_path: Path,
    malformed_counter: list[int] | None = None,
) -> Iterator[dict[str, Any]]:
    malformed_counter = malformed_counter if malformed_counter is not None else [0]
    with tarfile.open(tarball_path, mode="r|*") as archive:
        for member in archive:
            if not member.isfile() or not _should_process_trace_member(member.name):
                continue
            fileobj = archive.extractfile(member)
            if fileobj is None:
                continue
            raw = fileobj.read()
            payload = _decode_member_payload(raw)
            if payload is None:
                malformed_counter[0] += 1
                LOGGER.warning("Failed parsing JSON member %s in %s", member.name, tarball_path)
                continue
            hex_id = str(payload.get("hex", payload.get("icao", ""))).upper()
            if not hex_id:
                continue
            base_unix = payload.get("timestamp") or payload.get("now")
            if base_unix is None:
                malformed_counter[0] += 1
                continue
            try:
                base_time = datetime.fromtimestamp(int(base_unix), tz=UTC)
            except (TypeError, ValueError):
                malformed_counter[0] += 1
                continue

            aircraft_meta = payload.get("aircraft") if isinstance(payload.get("aircraft"), dict) else {}
            icao_type = str(payload.get("t", aircraft_meta.get("t", "")) or "")
            emitter_category = str(payload.get("category", aircraft_meta.get("category", "")) or "")
            trace = payload.get("trace", [])
            if not isinstance(trace, list):
                malformed_counter[0] += 1
                continue
            for raw_point in trace:
                if not isinstance(raw_point, list):
                    continue
                parsed = _parse_trace_point(raw_point, base_time)
                if parsed is None:
                    continue
                parsed["hex_id"] = hex_id
                parsed["icao_type"] = icao_type
                parsed["emitter_category"] = emitter_category
                yield parsed


def iter_trace_tarball_points_from_bytes(data: bytes) -> Iterator[dict[str, Any]]:
    """Used by tests to avoid filesystem IO."""
    malformed = [0]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r|*") as archive:
        for member in archive:
            if not member.isfile() or not _should_process_trace_member(member.name):
                continue
            fileobj = archive.extractfile(member)
            if fileobj is None:
                continue
            payload = _decode_member_payload(fileobj.read())
            if payload is None:
                malformed[0] += 1
                continue
            base_unix = payload.get("timestamp") or payload.get("now")
            if base_unix is None:
                malformed[0] += 1
                continue
            base_time = datetime.fromtimestamp(int(base_unix), tz=UTC)
            for raw_point in payload.get("trace", []):
                if not isinstance(raw_point, list):
                    continue
                row = _parse_trace_point(raw_point, base_time)
                if row is None:
                    continue
                row["hex_id"] = str(payload.get("hex", "")).upper()
                row["icao_type"] = str(payload.get("t", "") or "")
                row["emitter_category"] = str(payload.get("category", "") or "")
                yield row

