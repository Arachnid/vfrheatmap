from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class AltBinValue(BaseModel):
    bin_index: int
    time_seconds: float
    flight_count: int


class TileCell(BaseModel):
    h3: str
    flight_count: int
    time_seconds: float
    mean_track_x: float
    mean_track_y: float
    coherence: float
    mean_speed: float
    alt_bins: list[AltBinValue]


class TilePayload(BaseModel):
    z: int
    x: int
    y: int
    h3_resolution: int
    cells: list[TileCell]


class Manifest(BaseModel):
    schema_version: int
    generated_at: datetime
    bbox: list[float] = Field(min_length=4, max_length=4)
    date_range: dict[str, str]
    classifier_config_hash: str
    h3_resolutions: list[int]
    altitude_bins: list[int]
    classifications: list[str]

