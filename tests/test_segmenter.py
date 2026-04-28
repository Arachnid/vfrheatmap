from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from adsb_vfr.config import load_classifier_config
from adsb_vfr.pipeline import segment_to_edges_batch


def test_segment_split_on_gap() -> None:
    cfg = load_classifier_config(Path("config"))
    base = datetime(2025, 1, 1, 12, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "ABC123",
                "timestamp": base,
                "lat": 51.0,
                "lon": -1.0,
                "alt_pressure_ft": 1500,
                "alt_qnh_ft": 1500,
                "ground_speed_kt": 80,
                "track_deg": 45,
                "squawk": "7000",
                "icao_type": "C152",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ABC123",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.01,
                "lon": -1.01,
                "alt_pressure_ft": 1600,
                "alt_qnh_ft": 1600,
                "ground_speed_kt": 82,
                "track_deg": 45,
                "squawk": "7000",
                "icao_type": "C152",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ABC123",
                "timestamp": base + timedelta(seconds=300),
                "lat": 51.03,
                "lon": -1.03,
                "alt_pressure_ft": 1700,
                "alt_qnh_ft": 1700,
                "ground_speed_kt": 90,
                "track_deg": 45,
                "squawk": "7000",
                "icao_type": "C152",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg)
    assert len(edges) == 1
