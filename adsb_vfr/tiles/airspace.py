from __future__ import annotations

import gzip
import hashlib
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any

import httpx
import mercantile
from shapely.geometry import box, mapping, shape

OPENAIP_AIRSPACES_ENDPOINT = "https://api.core.openaip.net/api/airspaces"
OPENAIP_TILES_ENDPOINT = "https://api.tiles.openaip.net/api/data/openaip/{z}/{x}/{y}.png"
AIRSPACE_STYLE = {
    "CTR": {"line_color": "#2563eb", "line_dash": [], "fill_color": "#60a5fa", "fill_opacity": 0.10, "label": True},
    "CTA": {"line_color": "#2563eb", "line_dash": [2, 2], "fill_color": "#93c5fd", "fill_opacity": 0.08, "label": True},
    "TMA": {"line_color": "#1d4ed8", "line_dash": [2, 2], "fill_color": "#bfdbfe", "fill_opacity": 0.06, "label": True},
    "MATZ": {"line_color": "#a21caf", "line_dash": [], "fill_color": "#e879f9", "fill_opacity": 0.10, "label": True},
    "ATZ": {"line_color": "#0ea5e9", "line_dash": [], "fill_color": "#7dd3fc", "fill_opacity": 0.08, "label": False},
    "DANGER": {"line_color": "#dc2626", "line_dash": [1, 2], "fill_color": "#ef4444", "fill_opacity": 0.12, "label": True},
    "RESTRICTED": {"line_color": "#b91c1c", "line_dash": [], "fill_color": "#dc2626", "fill_opacity": 0.20, "label": True},
    "PROHIBITED": {"line_color": "#7f1d1d", "line_dash": [], "fill_color": "#b91c1c", "fill_opacity": 0.20, "label": True},
    "AIAA": {"line_color": "#4b5563", "line_dash": [4, 2], "fill_color": "#9ca3af", "fill_opacity": 0.08, "label": False},
}
ALLOWED_TYPES = {"CTR", "CTA", "TMA", "ATZ", "MATZ", "DANGER", "RESTRICTED", "PROHIBITED", "AIAA"}
TYPE_ENUM_MAP: dict[int, str] = {
    1: "RESTRICTED",
    2: "DANGER",
    3: "PROHIBITED",
    4: "CTR",
    7: "TMA",
    13: "ATZ",
    14: "MATZ",
    18: "DANGER",
    21: "AIAA",
    26: "CTA",
    28: "ATZ",
}
UNIT_ENUM_MAP: dict[int, str] = {
    1: "FT",
    6: "FL",
}
REF_ENUM_MAP: dict[int, str] = {
    0: "AGL",
    1: "AMSL",
    2: "FL",
}
ICAO_CLASS_MAP: dict[int, str] = {
    0: "A",
    1: "B",
    2: "C",
    3: "D",
    4: "E",
    5: "F",
    6: "G",
    7: "UNCLASSIFIED",
    8: "SPECIAL",
}


def _cache_path(cache_dir: Path, params: dict[str, Any]) -> Path:
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    return cache_dir / f"{key}.json"


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_cache(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle)


def _to_ft(limit: dict[str, Any] | None) -> tuple[int | None, str]:
    if not isinstance(limit, dict):
        return None, "UNKNOWN"
    value = limit.get("value")
    unit_raw = limit.get("unit", "")
    ref_raw = limit.get("referenceDatum", "UNKNOWN")
    unit = UNIT_ENUM_MAP.get(unit_raw, str(unit_raw)).upper()
    ref = REF_ENUM_MAP.get(ref_raw, str(ref_raw)).upper()
    if value is None:
        return None, ref
    value_f = float(value)
    if unit in {"M", "METER", "METERS"}:
        value_f *= 3.28084
    elif unit in {"FL"}:
        value_f *= 100.0
    return int(round(value_f)), ref


def _resolve_type(item: dict[str, Any], props: dict[str, Any]) -> str:
    raw_type = item.get("type") or props.get("type")
    if isinstance(raw_type, str):
        type_name = raw_type.upper()
    elif isinstance(raw_type, int):
        type_name = TYPE_ENUM_MAP.get(raw_type, "OTHER")
    else:
        type_name = "OTHER"
    if type_name == "OTHER":
        name = str(item.get("name") or props.get("name") or "").upper()
        if " CTR" in name:
            return "CTR"
        if " CTA" in name:
            return "CTA"
        if " TMA" in name:
            return "TMA"
        if " MATZ" in name:
            return "MATZ"
        if " ATZ" in name:
            return "ATZ"
        if name.startswith("D") or "DANGER" in name:
            return "DANGER"
        if name.startswith("R") or "RESTRICTED" in name:
            return "RESTRICTED"
        if name.startswith("P") or "PROHIBITED" in name:
            return "PROHIBITED"
    return type_name


def _resolve_icao_class(item: dict[str, Any], props: dict[str, Any]) -> str:
    raw = item.get("icaoClass") or props.get("icaoClass")
    if isinstance(raw, int):
        return ICAO_CLASS_MAP.get(raw, "SPECIAL")
    return str(raw or "SPECIAL").upper()


def _extract_frequency(props: dict[str, Any], item: dict[str, Any]) -> str | None:
    if isinstance(props.get("frequency"), str):
        return props.get("frequency")
    freqs = item.get("frequencies")
    if isinstance(freqs, list) and freqs:
        first = freqs[0]
        if isinstance(first, dict):
            value = first.get("value") or first.get("frequency")
            if value is not None:
                return str(value)
    return None


def _extract_geometry(payload: dict[str, Any]) -> dict[str, Any] | None:
    geometry = payload.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") and geometry.get("coordinates"):
        return geometry
    geom = payload.get("geom")
    if isinstance(geom, dict) and geom.get("type") and geom.get("coordinates"):
        return geom
    return None


def parse_airspace_items(items: list[dict[str, Any]], bbox: tuple[float, float, float, float]) -> dict[str, Any]:
    region = box(bbox[1], bbox[0], bbox[3], bbox[2])
    features: list[dict[str, Any]] = []
    for item in items:
        geometry = _extract_geometry(item)
        if geometry is None:
            continue
        try:
            geom = shape(geometry)
        except Exception:  # noqa: BLE001
            continue
        if not geom.is_valid or geom.is_empty or not geom.intersects(region):
            continue
        props = item.get("properties", {}) if isinstance(item.get("properties"), dict) else {}
        type_name = _resolve_type(item, props)
        if type_name not in ALLOWED_TYPES:
            continue
        lower_ft, lower_ref = _to_ft(item.get("lowerLimit") or props.get("lowerLimit"))
        upper_ft, upper_ref = _to_ft(item.get("upperLimit") or props.get("upperLimit"))
        if type_name == "AIRWAY" and upper_ft is not None and upper_ft > 19_500:
            continue
        if upper_ref == "FL" and upper_ft is not None and upper_ft > 19_500:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": mapping(geom.intersection(region)),
                "properties": {
                    "name": str(item.get("name") or props.get("name") or "Unknown"),
                    "class": _resolve_icao_class(item, props),
                    "type": type_name,
                    "lower_limit_ft": lower_ft,
                    "lower_limit_ref": lower_ref,
                    "upper_limit_ft": upper_ft,
                    "upper_limit_ref": upper_ref,
                    "frequency": _extract_frequency(props, item),
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def fetch_openaip_airspaces(
    api_key: str,
    cache_dir: Path,
    refresh: bool,
    bbox: tuple[float, float, float, float],
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    log = logger or logging.getLogger(__name__)
    page = 1
    limit = 200
    all_items: list[dict[str, Any]] = []
    with httpx.Client(timeout=30.0) as client:
        while True:
            params = {"country": "GB", "page": page, "limit": limit, "sortBy": "name"}
            cache_path = _cache_path(cache_dir, params)
            payload = None if refresh else _read_cache(cache_path)
            if payload is None:
                response = client.get(
                    OPENAIP_AIRSPACES_ENDPOINT,
                    params=params,
                    headers={"x-openaip-api-key": api_key},
                )
                response.raise_for_status()
                payload = response.json()
                _write_cache(cache_path, payload)
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list) or not items:
                break
            all_items.extend([i for i in items if isinstance(i, dict)])
            if len(items) < limit:
                break
            page += 1
    log.info("Fetched %d OpenAIP airspace records", len(all_items))
    return parse_airspace_items(all_items, bbox=bbox)


def write_airspace_outputs(
    output_dir: Path,
    api_key: str,
    cache_dir: Path,
    refresh: bool,
    bbox: tuple[float, float, float, float],
    logger: logging.Logger | None = None,
) -> None:
    airspace_dir = output_dir / "airspace"
    airspace_dir.mkdir(parents=True, exist_ok=True)
    feature_collection = fetch_openaip_airspaces(
        api_key=api_key,
        cache_dir=cache_dir / "openaip",
        refresh=refresh,
        bbox=bbox,
        logger=logger,
    )
    with gzip.open(airspace_dir / "uk.geojson.gz", "wt", encoding="utf-8") as handle:
        json.dump(feature_collection, handle, separators=(",", ":"))
    _prefetch_openaip_tiles(
        api_key=api_key,
        cache_dir=cache_dir / "openaip_tiles",
        output_tiles_dir=airspace_dir / "tiles",
        refresh=refresh,
        bbox=bbox,
        min_zoom=5,
        max_zoom=11,
        max_requests_per_second=5.0,
        logger=logger,
    )
    style_payload = {
        "render_mode": "raster_tiles",
        "tile_url_template": "./data/airspace/tiles/z{z}/x{x}/y{y}.png",
        "bounds": [bbox[1], bbox[0], bbox[3], bbox[2]],
        "minzoom": 5,
        "maxzoom": 11,
        "attribution": "© OpenAIP",
        "vector_fallback_style": AIRSPACE_STYLE,
    }
    with (airspace_dir / "style.json").open("w", encoding="utf-8") as handle:
        json.dump(style_payload, handle, indent=2)


def _prefetch_openaip_tiles(
    api_key: str,
    cache_dir: Path,
    output_tiles_dir: Path,
    refresh: bool,
    bbox: tuple[float, float, float, float],
    min_zoom: int,
    max_zoom: int,
    max_requests_per_second: float,
    logger: logging.Logger | None = None,
) -> None:
    log = logger or logging.getLogger(__name__)
    output_tiles_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    min_lat, min_lon, max_lat, max_lon = bbox
    tile_coords: list[tuple[int, int, int]] = []
    for zoom in range(min_zoom, max_zoom + 1):
        for tile in mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [zoom]):
            tile_coords.append((tile.z, tile.x, tile.y))
    if not tile_coords:
        return
    log.info("Prefetching %d OpenAIP raster tiles (z%d-z%d)", len(tile_coords), min_zoom, max_zoom)
    interval = 1.0 / max_requests_per_second if max_requests_per_second > 0 else 0.5
    next_allowed = time.monotonic()
    fetched = 0
    copied = 0
    skipped = 0
    missing = 0
    retries = 0
    with httpx.Client(timeout=20.0) as client:
        for z, x, y in tile_coords:
            rel = Path(f"z{z}") / f"x{x}" / f"y{y}.png"
            output_path = output_tiles_dir / rel
            cache_path = cache_dir / rel
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists() and not refresh:
                skipped += 1
                continue
            if cache_path.exists() and not refresh:
                shutil.copy2(cache_path, output_path)
                copied += 1
                continue
            attempts = 0
            while attempts < 4:
                attempts += 1
                now = time.monotonic()
                if now < next_allowed:
                    time.sleep(next_allowed - now)
                next_allowed = max(next_allowed + interval, time.monotonic())
                url = OPENAIP_TILES_ENDPOINT.format(z=z, x=x, y=y)
                response = client.get(url, headers={"x-openaip-api-key": api_key})
                if response.status_code in {200}:
                    cache_path.write_bytes(response.content)
                    shutil.copy2(cache_path, output_path)
                    fetched += 1
                    break
                if response.status_code in {204, 404}:
                    missing += 1
                    break
                if response.status_code in {429, 500, 502, 503, 504}:
                    retries += 1
                    time.sleep(0.5 * attempts)
                    continue
                response.raise_for_status()
    log.info(
        "Airspace tile prefetch done: total=%d fetched=%d copied=%d skipped=%d missing=%d retries=%d",
        len(tile_coords),
        fetched,
        copied,
        skipped,
        missing,
        retries,
    )

