from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import shape
from shapely.strtree import STRtree

from adsb_vfr.tiles.airspace import fetch_openaip_airspaces, parse_airspace_items

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AirspaceLookup:
    tree: STRtree | None
    classes: np.ndarray

    @classmethod
    def empty(cls) -> "AirspaceLookup":
        return cls(tree=None, classes=np.array([], dtype=object))

    @classmethod
    def from_feature_collection(cls, feature_collection: dict[str, Any]) -> "AirspaceLookup":
        features = feature_collection.get("features", [])
        if not isinstance(features, list) or not features:
            return cls.empty()
        geoms = []
        classes: list[str] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            geometry = feature.get("geometry")
            props = feature.get("properties", {})
            if not isinstance(geometry, dict):
                continue
            try:
                geom = shape(geometry)
            except Exception:  # noqa: BLE001
                continue
            if geom.is_empty or not geom.is_valid:
                continue
            geoms.append(geom)
            if isinstance(props, dict):
                classes.append(str(props.get("class", "SPECIAL")).upper())
            else:
                classes.append("SPECIAL")
        if not geoms:
            return cls.empty()
        return cls(tree=STRtree(geoms), classes=np.array(classes, dtype=object))

    def flags_for_points(self, lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        in_class_a = np.zeros(len(lats), dtype=bool)
        in_any_airspace = np.zeros(len(lats), dtype=bool)
        if self.tree is None or len(lats) == 0:
            return in_class_a, in_any_airspace
        pts = shapely.points(lons, lats)
        matches = self.tree.query(pts, predicate="intersects")
        if matches.size == 0:
            return in_class_a, in_any_airspace
        point_idx = matches[0]
        poly_idx = matches[1]
        in_any_airspace[np.unique(point_idx)] = True
        if len(poly_idx):
            class_hits = self.classes[poly_idx] == "A"
            if np.any(class_hits):
                in_class_a[np.unique(point_idx[class_hits])] = True
        return in_class_a, in_any_airspace


def load_airspace_lookup(
    cache_dir: Path,
    bbox: tuple[float, float, float, float],
    api_key: str | None,
    refresh: bool,
) -> AirspaceLookup:
    openaip_cache = cache_dir / "openaip"
    feature_collection: dict[str, Any] | None = None
    if api_key:
        feature_collection = fetch_openaip_airspaces(
            api_key=api_key,
            cache_dir=openaip_cache,
            refresh=refresh,
            bbox=bbox,
            logger=LOGGER,
        )
    else:
        cached_items: list[dict[str, Any]] = []
        if openaip_cache.exists():
            for path in sorted(openaip_cache.glob("*.json")):
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                items = payload.get("items")
                if isinstance(items, list):
                    cached_items.extend(i for i in items if isinstance(i, dict))
        if cached_items:
            LOGGER.info("Using cached OpenAIP airspace pages (%d items).", len(cached_items))
            feature_collection = parse_airspace_items(cached_items, bbox=bbox)
        else:
            LOGGER.warning(
                "No OpenAIP API key and no cached OpenAIP pages found at %s; "
                "airspace-assisted IFR/VFR status propagation disabled.",
                openaip_cache,
            )
            return AirspaceLookup.empty()
    return AirspaceLookup.from_feature_collection(feature_collection or {"type": "FeatureCollection", "features": []})

