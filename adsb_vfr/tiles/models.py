from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TileCell(BaseModel):
    h3: str
    flight_count: int
    time_seconds: float
    mean_track_x: float
    mean_track_y: float
    coherence: float
    mean_speed: float


class TilePayload(BaseModel):
    z: int
    x: int
    y: int
    h3_resolution: int
    cells: list[TileCell]


class ResolutionScale(BaseModel):
    flight_count_max: float
    time_seconds_max: float
    flight_count_p90: float
    time_seconds_p90: float


class ClassificationScale(BaseModel):
    flight_count_max: float
    time_seconds_max: float
    by_resolution: dict[str, ResolutionScale] = Field(default_factory=dict)


class Manifest(BaseModel):
    schema_version: int
    generated_at: datetime
    bbox: list[float] = Field(min_length=4, max_length=4)
    date_range: dict[str, str]
    classifier_config_hash: str
    h3_resolutions: list[int]
    classifications: list[str]
    classification_scales: dict[str, ClassificationScale] = Field(default_factory=dict)

