from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import h3
import numpy as np


EARTH_RADIUS_M = 6_371_000.0
NM_PER_M = 1.0 / 1852.0


@dataclass(frozen=True)
class DensifiedPoint:
    lat: float
    lon: float
    frac: float


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = math.radians(lat2)
    lon2_r = math.radians(lon2)
    d_lat = lat2_r - lat1_r
    d_lon = lon2_r - lon1_r
    a = math.sin(d_lat / 2.0) ** 2 + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(d_lon / 2.0) ** 2
    return EARTH_RADIUS_M * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def great_circle_distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_m(lat1, lon1, lat2, lon2) * NM_PER_M


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    d_lon_r = math.radians(lon2 - lon1)
    y = math.sin(d_lon_r) * math.cos(lat2_r)
    x = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(lat2_r) * math.cos(d_lon_r)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def interpolate_linear(lat1: float, lon1: float, lat2: float, lon2: float, frac: float) -> tuple[float, float]:
    return lat1 + (lat2 - lat1) * frac, lon1 + (lon2 - lon1) * frac


def densify_segment(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    max_spacing_m: float = 100.0,
) -> list[DensifiedPoint]:
    distance = haversine_m(lat1, lon1, lat2, lon2)
    if distance <= 0:
        return [DensifiedPoint(lat=lat1, lon=lon1, frac=0.0)]
    steps = max(1, int(math.ceil(distance / max_spacing_m)))
    result: list[DensifiedPoint] = []
    for i in range(steps + 1):
        frac = i / steps
        lat, lon = interpolate_linear(lat1, lon1, lat2, lon2, frac)
        result.append(DensifiedPoint(lat=lat, lon=lon, frac=frac))
    return result


def h3_cell(lat: float, lon: float, resolution: int) -> str:
    return h3.latlng_to_cell(lat, lon, resolution)


def heading_bin_index(track_deg: float) -> int:
    wrapped = track_deg % 360.0
    return int(wrapped // 22.5) % 16


def weighted_track_hist(track_deg: float, weight: float) -> np.ndarray:
    hist = np.zeros(16, dtype=np.float64)
    hist[heading_bin_index(track_deg)] = weight
    return hist


def straightness_ratio(points: Iterable[tuple[float, float]]) -> float:
    pts = list(points)
    if len(pts) < 2:
        return 1.0
    path = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(pts, pts[1:]):
        path += haversine_m(lat1, lon1, lat2, lon2)
    chord = haversine_m(pts[0][0], pts[0][1], pts[-1][0], pts[-1][1])
    if path <= 0:
        return 1.0
    return max(0.0, min(1.0, chord / path))

