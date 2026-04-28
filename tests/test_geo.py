from __future__ import annotations

from adsb_vfr.lib.geo import densify_segment, great_circle_distance_nm, heading_bin_index


def test_distance_positive() -> None:
    d = great_circle_distance_nm(51.0, -1.0, 51.1, -1.2)
    assert d > 0.0


def test_densify_emits_more_than_endpoints() -> None:
    pts = densify_segment(51.0, -1.0, 51.01, -1.01, max_spacing_m=50.0)
    assert len(pts) > 2
    assert pts[0].frac == 0.0
    assert pts[-1].frac == 1.0


def test_heading_bins() -> None:
    assert heading_bin_index(0.0) == 0
    assert heading_bin_index(359.9) == 15
    assert heading_bin_index(22.6) == 1

