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

from adsb_vfr.lib.airspace_vertical import point_in_airspace_vertically
from adsb_vfr.tiles.airspace import fetch_openaip_airspaces, parse_airspace_items

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AirspaceLookup:
    tree: STRtree | None
    classes: np.ndarray
    lower_ft: np.ndarray
    lower_ref: np.ndarray
    upper_ft: np.ndarray
    upper_ref: np.ndarray

    @classmethod
    def empty(cls) -> "AirspaceLookup":
        return cls(
            tree=None,
            classes=np.array([], dtype=object),
            lower_ft=np.array([], dtype=np.float64),
            lower_ref=np.array([], dtype=object),
            upper_ft=np.array([], dtype=np.float64),
            upper_ref=np.array([], dtype=object),
        )

    @classmethod
    def from_feature_collection(cls, feature_collection: dict[str, Any]) -> "AirspaceLookup":
        features = feature_collection.get("features", [])
        if not isinstance(features, list) or not features:
            return cls.empty()
        geoms = []
        classes: list[str] = []
        lower_list: list[float] = []
        lower_refs: list[str] = []
        upper_list: list[float] = []
        upper_refs: list[str] = []
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
                lf = props.get("lower_limit_ft")
                lr = props.get("lower_limit_ref") or "UNKNOWN"
                uf = props.get("upper_limit_ft")
                ur = props.get("upper_limit_ref") or "UNKNOWN"
                lower_list.append(float(lf) if lf is not None else np.nan)
                lower_refs.append(str(lr).upper())
                upper_list.append(float(uf) if uf is not None else np.nan)
                upper_refs.append(str(ur).upper())
            else:
                classes.append("SPECIAL")
                lower_list.append(np.nan)
                lower_refs.append("UNKNOWN")
                upper_list.append(np.nan)
                upper_refs.append("UNKNOWN")
        if not geoms:
            return cls.empty()
        return cls(
            tree=STRtree(geoms),
            classes=np.array(classes, dtype=object),
            lower_ft=np.array(lower_list, dtype=np.float64),
            lower_ref=np.array(lower_refs, dtype=object),
            upper_ft=np.array(upper_list, dtype=np.float64),
            upper_ref=np.array(upper_refs, dtype=object),
        )

    def flags_for_points(
        self,
        lats: np.ndarray,
        lons: np.ndarray,
        alt_pressure_ft: np.ndarray,
        alt_qnh_amsl_ft: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """2D footprint hit plus vertical band using FL vs AMSL datums per OpenAIP refs."""
        n = len(lats)
        in_class_a = np.zeros(n, dtype=bool)
        in_any_airspace = np.zeros(n, dtype=bool)
        if self.tree is None or n == 0:
            return in_class_a, in_any_airspace
        pts = shapely.points(lons, lats)
        matches = self.tree.query(pts, predicate="intersects")
        if matches.size == 0:
            return in_class_a, in_any_airspace
        point_idx = matches[0]
        poly_idx = matches[1]
        for i in range(len(point_idx)):
            pi = int(point_idx[i])
            pj = int(poly_idx[i])
            lf = self.lower_ft[pj]
            uf = self.upper_ft[pj]
            lower_ft_i = None if (lf != lf or np.isnan(lf)) else int(round(float(lf)))
            upper_ft_i = None if (uf != uf or np.isnan(uf)) else int(round(float(uf)))
            lr = str(self.lower_ref[pj])
            ur = str(self.upper_ref[pj])
            pa = float(alt_pressure_ft[pi])
            qa = float(alt_qnh_amsl_ft[pi])
            if not point_in_airspace_vertically(pa, qa, lower_ft_i, lr, upper_ft_i, ur):
                continue
            in_any_airspace[pi] = True
            if str(self.classes[pj]) == "A":
                in_class_a[pi] = True
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
