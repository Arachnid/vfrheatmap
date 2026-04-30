from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from adsb_vfr.config import load_classifier_config
from adsb_vfr.lib.airspace_lookup import AirspaceLookup
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
                "alt_qnh_amsl_ft": 1500,
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
                "alt_qnh_amsl_ft": 1600,
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
                "alt_qnh_amsl_ft": 1700,
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


def test_status_carries_forward_across_gap() -> None:
    cfg = load_classifier_config(Path("config"))
    base = datetime(2025, 1, 2, 9, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "ABC123",
                "timestamp": base,
                "lat": 51.0,
                "lon": -1.0,
                "alt_pressure_ft": 1500,
                "alt_qnh_amsl_ft": 1500,
                "ground_speed_kt": 85,
                "track_deg": 45,
                "squawk": "7000",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ABC123",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.02,
                "lon": -1.02,
                "alt_pressure_ft": 1700,
                "alt_qnh_amsl_ft": 1700,
                "ground_speed_kt": 90,
                "track_deg": 45,
                "squawk": "7000",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ABC123",
                "timestamp": base + timedelta(seconds=260),
                "lat": 51.04,
                "lon": -1.04,
                "alt_pressure_ft": 1800,
                "alt_qnh_amsl_ft": 1800,
                "ground_speed_kt": 92,
                "track_deg": 45,
                "squawk": "",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ABC123",
                "timestamp": base + timedelta(seconds=320),
                "lat": 51.06,
                "lon": -1.06,
                "alt_pressure_ft": 1900,
                "alt_qnh_amsl_ft": 1900,
                "ground_speed_kt": 95,
                "track_deg": 45,
                "squawk": "",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg)
    assert len(edges) == 2
    assert set(edges["classification"].tolist()) <= {"vfr_high", "vfr_medium", "vfr_type"}


def test_status_backfills_prior_unknown_segments() -> None:
    cfg = load_classifier_config(Path("config"))
    airspace = AirspaceLookup.from_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-2.0, 50.0], [1.0, 50.0], [1.0, 53.0], [-2.0, 53.0], [-2.0, 50.0]]],
                    },
                    "properties": {"class": "D"},
                }
            ],
        }
    )
    base = datetime(2025, 1, 2, 12, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "ZZZ111",
                "timestamp": base,
                "lat": 51.2,
                "lon": -0.8,
                "alt_pressure_ft": 2500,
                "alt_qnh_amsl_ft": 2500,
                "ground_speed_kt": 120,
                "track_deg": 90,
                "squawk": "",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ZZZ111",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.22,
                "lon": -0.78,
                "alt_pressure_ft": 2600,
                "alt_qnh_amsl_ft": 2600,
                "ground_speed_kt": 120,
                "track_deg": 90,
                "squawk": "",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ZZZ111",
                "timestamp": base + timedelta(seconds=260),
                "lat": 51.24,
                "lon": -0.76,
                "alt_pressure_ft": 2700,
                "alt_qnh_amsl_ft": 2700,
                "ground_speed_kt": 120,
                "track_deg": 90,
                "squawk": "2001",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "ZZZ111",
                "timestamp": base + timedelta(seconds=320),
                "lat": 51.26,
                "lon": -0.74,
                "alt_pressure_ft": 2800,
                "alt_qnh_amsl_ft": 2800,
                "ground_speed_kt": 120,
                "track_deg": 90,
                "squawk": "2001",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg, airspace_lookup=airspace)
    assert len(edges) == 2
    assert set(edges["classification"].tolist()) == {"ifr"}


def test_ifr_status_survives_class_a_to_class_d_break() -> None:
    cfg = load_classifier_config(Path("config"))
    airspace = AirspaceLookup.from_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-1.0, 51.0], [-0.9, 51.0], [-0.9, 51.1], [-1.0, 51.1], [-1.0, 51.0]]],
                    },
                    "properties": {"class": "A"},
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-0.8, 51.0], [-0.7, 51.0], [-0.7, 51.1], [-0.8, 51.1], [-0.8, 51.0]]],
                    },
                    "properties": {"class": "D"},
                },
            ],
        }
    )
    base = datetime(2025, 1, 3, 9, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "IFR001",
                "timestamp": base,
                "lat": 51.05,
                "lon": -0.95,
                "alt_pressure_ft": 6000,
                "alt_qnh_amsl_ft": 6000,
                "ground_speed_kt": 180,
                "track_deg": 120,
                "squawk": "1234",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
            {
                "hex_id": "IFR001",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.06,
                "lon": -0.94,
                "alt_pressure_ft": 5800,
                "alt_qnh_amsl_ft": 5800,
                "ground_speed_kt": 175,
                "track_deg": 120,
                "squawk": "1234",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
            {
                "hex_id": "IFR001",
                "timestamp": base + timedelta(seconds=260),
                "lat": 51.05,
                "lon": -0.75,
                "alt_pressure_ft": 4200,
                "alt_qnh_amsl_ft": 4200,
                "ground_speed_kt": 160,
                "track_deg": 110,
                "squawk": "1234",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
            {
                "hex_id": "IFR001",
                "timestamp": base + timedelta(seconds=320),
                "lat": 51.04,
                "lon": -0.74,
                "alt_pressure_ft": 3600,
                "alt_qnh_amsl_ft": 3600,
                "ground_speed_kt": 150,
                "track_deg": 110,
                "squawk": "1234",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg, airspace_lookup=airspace)
    assert len(edges) == 2
    assert set(edges["classification"].tolist()) == {"ifr"}


def test_ifr_status_does_not_downgrade_after_class_g_hit() -> None:
    cfg = load_classifier_config(Path("config"))
    airspace = AirspaceLookup.from_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-1.0, 51.0], [-0.9, 51.0], [-0.9, 51.1], [-1.0, 51.1], [-1.0, 51.0]]],
                    },
                    "properties": {"class": "A"},
                }
            ],
        }
    )
    base = datetime(2025, 1, 3, 12, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "IFR002",
                "timestamp": base,
                "lat": 51.05,
                "lon": -0.95,
                "alt_pressure_ft": 7000,
                "alt_qnh_amsl_ft": 7000,
                "ground_speed_kt": 180,
                "track_deg": 130,
                "squawk": "1234",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
            {
                "hex_id": "IFR002",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.06,
                "lon": -0.94,
                "alt_pressure_ft": 6800,
                "alt_qnh_amsl_ft": 6800,
                "ground_speed_kt": 178,
                "track_deg": 130,
                "squawk": "1234",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
            {
                "hex_id": "IFR002",
                "timestamp": base + timedelta(seconds=260),
                "lat": 51.15,
                "lon": -1.30,
                "alt_pressure_ft": 6200,
                "alt_qnh_amsl_ft": 6200,
                "ground_speed_kt": 170,
                "track_deg": 250,
                "squawk": "7000",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
            {
                "hex_id": "IFR002",
                "timestamp": base + timedelta(seconds=320),
                "lat": 51.16,
                "lon": -1.31,
                "alt_pressure_ft": 6000,
                "alt_qnh_amsl_ft": 6000,
                "ground_speed_kt": 168,
                "track_deg": 250,
                "squawk": "7000",
                "icao_type": "A320",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg, airspace_lookup=airspace)
    assert len(edges) == 2
    assert set(edges["classification"].tolist()) == {"ifr"}


def test_journey_entirely_in_controlled_airspace_is_ifr() -> None:
    cfg = load_classifier_config(Path("config"))
    airspace = AirspaceLookup.from_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-2.0, 50.0], [1.0, 50.0], [1.0, 53.0], [-2.0, 53.0], [-2.0, 50.0]]],
                    },
                    "properties": {"class": "D"},
                }
            ],
        }
    )
    base = datetime(2025, 1, 4, 8, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "CTRL01",
                "timestamp": base,
                "lat": 51.10,
                "lon": -0.50,
                "alt_pressure_ft": 1800,
                "alt_qnh_amsl_ft": 1800,
                "ground_speed_kt": 120,
                "track_deg": 95,
                "squawk": "7000",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "CTRL01",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.12,
                "lon": -0.45,
                "alt_pressure_ft": 1900,
                "alt_qnh_amsl_ft": 1900,
                "ground_speed_kt": 122,
                "track_deg": 95,
                "squawk": "7000",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
            {
                "hex_id": "CTRL01",
                "timestamp": base + timedelta(seconds=130),
                "lat": 51.15,
                "lon": -0.40,
                "alt_pressure_ft": 2000,
                "alt_qnh_amsl_ft": 2000,
                "ground_speed_kt": 125,
                "track_deg": 95,
                "squawk": "7000",
                "icao_type": "PA28",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg, airspace_lookup=airspace)
    assert len(edges) == 2
    assert set(edges["classification"].tolist()) == {"ifr"}


def test_always_ifr_emitter_not_downgraded_by_vfr_evidence() -> None:
    cfg = load_classifier_config(Path("config"))
    base = datetime(2025, 1, 5, 10, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "EMIT01",
                "timestamp": base,
                "lat": 51.0,
                "lon": -1.0,
                "alt_pressure_ft": 3000,
                "alt_qnh_amsl_ft": 3000,
                "ground_speed_kt": 140,
                "track_deg": 100,
                "squawk": "7000",
                "icao_type": "A320",
                "emitter_category": "A3",
            },
            {
                "hex_id": "EMIT01",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.01,
                "lon": -1.01,
                "alt_pressure_ft": 3200,
                "alt_qnh_amsl_ft": 3200,
                "ground_speed_kt": 142,
                "track_deg": 100,
                "squawk": "7000",
                "icao_type": "A320",
                "emitter_category": "A3",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg)
    assert len(edges) == 1
    assert set(edges["classification"].tolist()) == {"ifr"}


def test_always_vfr_type_not_upgraded_by_ifr_evidence() -> None:
    cfg = load_classifier_config(Path("config"))
    airspace = AirspaceLookup.from_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[-2.0, 50.0], [1.0, 50.0], [1.0, 53.0], [-2.0, 53.0], [-2.0, 50.0]]],
                    },
                    "properties": {"class": "A"},
                }
            ],
        }
    )
    base = datetime(2025, 1, 5, 11, 0, 0)
    rows = pd.DataFrame(
        [
            {
                "hex_id": "TYPE01",
                "timestamp": base,
                "lat": 51.2,
                "lon": -0.8,
                "alt_pressure_ft": 2500,
                "alt_qnh_amsl_ft": 2500,
                "ground_speed_kt": 90,
                "track_deg": 85,
                "squawk": "2001",
                "icao_type": "C42",
                "emitter_category": "A1",
            },
            {
                "hex_id": "TYPE01",
                "timestamp": base + timedelta(seconds=60),
                "lat": 51.22,
                "lon": -0.78,
                "alt_pressure_ft": 2600,
                "alt_qnh_amsl_ft": 2600,
                "ground_speed_kt": 92,
                "track_deg": 85,
                "squawk": "2001",
                "icao_type": "C42",
                "emitter_category": "A1",
            },
        ]
    )
    edges = segment_to_edges_batch(rows, classifier_config=cfg, airspace_lookup=airspace)
    assert len(edges) == 1
    assert set(edges["classification"].tolist()) == {"vfr_type"}
