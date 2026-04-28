from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class PointRow:
    hex_id: str
    timestamp: datetime
    lat: float
    lon: float
    alt_pressure_ft: float
    alt_qnh_ft: float
    ground_speed_kt: float
    track_deg: float
    squawk: str
    icao_type: str
    emitter_category: str


@dataclass(frozen=True)
class SegmentSummary:
    segment_id: int
    hex_id: str
    date: datetime
    start_ts: datetime
    end_ts: datetime
    squawk: str
    icao_type: str
    emitter_category: str
    classification: str
    vehicle_class: str
    min_alt_ft: int
    max_alt_ft: int
    duration_s: float
    distance_nm: float
    straightness: float
    point_count: int

