"""Regression tests for ingest: unknown exclusion, agg_date propagation."""

from __future__ import annotations

import h3

from adsb_vfr.pipeline import add_aggregate_keys, edge_to_cell_intersections


def test_edge_to_cell_intersections_propagates_agg_date() -> None:
    start = h3.latlng_to_cell(51.0, -1.0, 9)
    end = h3.latlng_to_cell(51.002, -1.002, 9)
    lat1, lon1 = h3.cell_to_latlng(start)
    lat2, lon2 = h3.cell_to_latlng(end)
    edge = {
        "segment_id": 42,
        "agg_date": "2025-06-15",
        "classification": "vfr_medium",
        "vehicle_class": "fixed_wing",
        "start_lat": lat1,
        "start_lon": lon1,
        "end_lat": lat2,
        "end_lon": lon2,
        "start_alt_qnh_ft": 3000.0,
        "end_alt_qnh_ft": 3000.0,
        "track_deg": 45.0,
        "ground_speed_kt": 90.0,
        "edge_duration_s": 60.0,
    }
    rows = edge_to_cell_intersections(edge)
    assert rows
    for row in rows:
        assert row["agg_date"] == "2025-06-15"


def test_add_aggregate_keys_sets_h3_and_classification_group() -> None:
    cell = h3.latlng_to_cell(51.0, -1.0, 9)
    out = add_aggregate_keys(
        {
            "classification": "vfr_medium",
            "vehicle_class": "fixed_wing",
            "alt_qnh_ft": 5000.0,
            "track_deg": 0.0,
            "ground_speed_kt": 80.0,
            "time_weight": 1.0,
            "res9_idx": cell,
        }
    )
    assert out["classification_group"] == "vfr"
    assert out["h3_cell"] == int(h3.str_to_int(cell))


def test_add_aggregate_keys_unknown_not_grouped() -> None:
    cell = h3.latlng_to_cell(51.0, -1.0, 9)
    row = add_aggregate_keys(
        {
            "classification": "unknown",
            "vehicle_class": "fixed_wing",
            "alt_qnh_ft": 5000.0,
            "track_deg": 0.0,
            "ground_speed_kt": 100.0,
            "time_weight": 1.0,
            "res9_idx": cell,
        }
    )
    assert row.get("classification_group") is None


def test_add_aggregate_keys_helicopter_layer() -> None:
    cell = h3.latlng_to_cell(51.0, -1.0, 9)
    out = add_aggregate_keys(
        {
            "classification": "ifr",
            "vehicle_class": "helicopter",
            "alt_qnh_ft": 2000.0,
            "track_deg": 90.0,
            "ground_speed_kt": 100.0,
            "time_weight": 2.0,
            "res9_idx": cell,
        }
    )
    assert out["classification_group"] == "helicopter"


def test_add_aggregate_keys_gyrocopter_uses_vfr_layer() -> None:
    cell = h3.latlng_to_cell(51.0, -1.0, 9)
    out = add_aggregate_keys(
        {
            "classification": "vfr_medium",
            "vehicle_class": "gyrocopter",
            "alt_qnh_ft": 500.0,
            "track_deg": 0.0,
            "ground_speed_kt": 50.0,
            "time_weight": 1.0,
            "res9_idx": cell,
        }
    )
    assert out["classification_group"] == "vfr"
