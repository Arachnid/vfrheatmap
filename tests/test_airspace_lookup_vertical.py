"""Integration tests: airspace hit requires correct altitude and datum per limit."""

from __future__ import annotations

import numpy as np

from adsb_vfr.lib.airspace_lookup import AirspaceLookup


def _fc_one_polygon(
    *,
    lower_ft: int | None,
    lower_ref: str,
    upper_ft: int | None,
    upper_ref: str,
    icao_class: str = "C",
) -> dict:
    """Single axis-aligned polygon around (51°N, 1°W) — matches test points."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [-1.01, 50.99],
                            [-0.99, 50.99],
                            [-0.99, 51.01],
                            [-1.01, 51.01],
                            [-1.01, 50.99],
                        ]
                    ],
                },
                "properties": {
                    "class": icao_class,
                    "name": "TEST",
                    "lower_limit_ft": lower_ft,
                    "lower_limit_ref": lower_ref,
                    "upper_limit_ft": upper_ft,
                    "upper_limit_ref": upper_ref,
                },
            }
        ],
    }


def test_flags_inside_only_when_amsl_band_matches() -> None:
    lookup = AirspaceLookup.from_feature_collection(
        _fc_one_polygon(lower_ft=1000, lower_ref="AMSL", upper_ft=4000, upper_ref="AMSL")
    )
    lats = np.array([51.0])
    lons = np.array([-1.0])
    pa = np.array([5000.0])
    qa = np.array([2500.0])
    class_a, any_a = lookup.flags_for_points(lats, lons, pa, qa)
    assert bool(any_a[0])
    assert not bool(class_a[0])

    qa_too_high = np.array([4500.0])
    _, any_high = lookup.flags_for_points(lats, lons, pa, qa_too_high)
    assert not bool(any_high[0])


def test_flags_fl_ceiling_requires_pressure_altitude() -> None:
    lookup = AirspaceLookup.from_feature_collection(
        _fc_one_polygon(lower_ft=0, lower_ref="AGL", upper_ft=5000, upper_ref="FL")
    )
    lats = np.array([51.0])
    lons = np.array([-1.0])
    pa_ok = np.array([4500.0])
    qa = np.array([4000.0])
    _, any_ok = lookup.flags_for_points(lats, lons, pa_ok, qa)
    assert bool(any_ok[0])

    pa_high = np.array([5500.0])
    _, any_bad = lookup.flags_for_points(lats, lons, pa_high, qa)
    assert not bool(any_bad[0])


def test_flags_agl_lower_still_enforces_upper_amsl() -> None:
    lookup = AirspaceLookup.from_feature_collection(
        _fc_one_polygon(lower_ft=0, lower_ref="AGL", upper_ft=2000, upper_ref="AMSL")
    )
    lats = np.array([51.0])
    lons = np.array([-1.0])
    pa = np.array([3000.0])
    qa_inside = np.array([1500.0])
    _, any_in = lookup.flags_for_points(lats, lons, pa, qa_inside)
    assert bool(any_in[0])

    qa_above = np.array([2500.0])
    _, any_out = lookup.flags_for_points(lats, lons, pa, qa_above)
    assert not bool(any_out[0])


def test_flags_horizontal_miss_never_true() -> None:
    lookup = AirspaceLookup.from_feature_collection(
        _fc_one_polygon(lower_ft=0, lower_ref="AGL", upper_ft=50_000, upper_ref="AMSL")
    )
    lats = np.array([52.0])
    lons = np.array([-1.0])
    pa = np.array([5000.0])
    qa = np.array([5000.0])
    _, any_a = lookup.flags_for_points(lats, lons, pa, qa)
    assert not bool(any_a[0])


def test_class_a_requires_vertical_and_class() -> None:
    lookup = AirspaceLookup.from_feature_collection(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-1.01, 50.99],
                                [-0.99, 50.99],
                                [-0.99, 51.01],
                                [-1.01, 51.01],
                                [-1.01, 50.99],
                            ]
                        ],
                    },
                    "properties": {
                        "class": "A",
                        "lower_limit_ft": 10_000,
                        "lower_limit_ref": "FL",
                        "upper_limit_ft": 20_000,
                        "upper_limit_ref": "FL",
                    },
                }
            ],
        }
    )
    lats = np.array([51.0])
    lons = np.array([-1.0])
    pa_in = np.array([15_000.0])
    qa = np.array([14_000.0])
    class_a, any_a = lookup.flags_for_points(lats, lons, pa_in, qa)
    assert bool(any_a[0])
    assert bool(class_a[0])

    pa_out = np.array([25_000.0])
    class_a2, any_a2 = lookup.flags_for_points(lats, lons, pa_out, qa)
    assert not bool(any_a2[0])
    assert not bool(class_a2[0])
