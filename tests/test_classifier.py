from __future__ import annotations

from pathlib import Path

from adsb_vfr.config import load_classifier_config
from adsb_vfr.lib.classifier import SegmentFeatures, classify_segment


def _cfg():
    return load_classifier_config(Path("config"))


def test_heavy_rule_precedence() -> None:
    label, vehicle = classify_segment(
        SegmentFeatures("7000", "C172", "A3", 2000, 0.4),
        _cfg(),
    )
    assert label == "heavy"
    assert vehicle == "fixed_wing"


def test_vfr_high_rule() -> None:
    label, vehicle = classify_segment(
        SegmentFeatures("7000", "PA38", "A1", 3500, 0.9),
        _cfg(),
    )
    assert label == "vfr_high"
    assert vehicle == "fixed_wing"


def test_ifr_rule_by_altitude() -> None:
    label, _ = classify_segment(
        SegmentFeatures("1234", "SR22", "A1", 17000, 0.4),
        _cfg(),
    )
    assert label == "ifr"
