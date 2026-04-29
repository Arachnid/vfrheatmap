from __future__ import annotations

from dataclasses import dataclass

from adsb_vfr.config import ClassifierConfig


VFR_CLASSES = {"vfr_high", "vfr_medium", "vfr_type"}
ALWAYS_IFR_EMITTER_CATEGORIES = {"A2", "A3", "A4", "A5", "A6", "A7"}


@dataclass(frozen=True)
class SegmentFeatures:
    squawk: str
    icao_type: str
    emitter_category: str
    max_alt_qnh_ft: float
    straightness: float

def is_always_ifr_emitter(emitter_category: str) -> bool:
    return (emitter_category or "").strip().upper() in ALWAYS_IFR_EMITTER_CATEGORIES


def is_always_ifr_type(icao_type: str, config: ClassifierConfig) -> bool:
    return (icao_type or "").strip().upper() in config.known_ifr_only_types


def is_always_vfr_type(icao_type: str, config: ClassifierConfig) -> bool:
    return (icao_type or "").strip().upper() in config.known_vfr_only_types


def classify_segment(features: SegmentFeatures, config: ClassifierConfig) -> tuple[str, str]:
    _ = config
    icao_type = (features.icao_type or "").upper()
    emitter = (features.emitter_category or "").upper()

    if emitter == "B2" or icao_type.startswith("H"):
        vehicle_class = "helicopter"
    else:
        vehicle_class = "fixed_wing"

    if is_always_ifr_emitter(emitter) or is_always_ifr_type(icao_type, config):
        return "ifr", vehicle_class
    if is_always_vfr_type(icao_type, config):
        return "vfr_type", vehicle_class

    return "unknown", vehicle_class

