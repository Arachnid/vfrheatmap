from __future__ import annotations

from pathlib import Path

from adsb_vfr.config import load_classifier_config
from adsb_vfr.lib.classifier import SegmentFeatures, classify_segment


def _cfg():
    return load_classifier_config(Path("config"))


def test_emitter_always_ifr_precedence() -> None:
    label, vehicle = classify_segment(
        SegmentFeatures("7000", "C172", "A3", 2000, 0.4),
        _cfg(),
    )
    assert label == "ifr"
    assert vehicle == "fixed_wing"


def test_icao_type_always_vfr_precedence() -> None:
    label, vehicle = classify_segment(
        SegmentFeatures("2001", "C42", "A1", 18000, 0.99),
        _cfg(),
    )
    assert label == "vfr_type"
    assert vehicle == "fixed_wing"


def test_unknown_falls_through_to_segment_logic() -> None:
    label, _ = classify_segment(
        SegmentFeatures("1234", "SR22", "A1", 17000, 0.4),
        _cfg(),
    )
    assert label == "unknown"
