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
    max_alt_qnh_amsl_ft: float
    straightness: float


def is_always_ifr_emitter(emitter_category: str) -> bool:
    return (emitter_category or "").strip().upper() in ALWAYS_IFR_EMITTER_CATEGORIES


def is_always_ifr_type(icao_type: str, config: ClassifierConfig) -> bool:
    return (icao_type or "").strip().upper() in config.known_ifr_only_types


def is_always_vfr_type(icao_type: str, config: ClassifierConfig) -> bool:
    return (icao_type or "").strip().upper() in config.known_vfr_only_types


def infer_vehicle_class(icao_type: str, config: ClassifierConfig) -> str:
    """Map ICAO type designator to aggregate rotorcraft category (Doc 8643–style codes)."""
    icao = (icao_type or "").strip().upper()
    if not icao:
        return "fixed_wing"
    if icao in config.gyrocopter_types:
        return "gyrocopter"
    if icao in config.helicopter_types or icao in config.tiltrotor_types:
        return "helicopter"
    # Tiltrotors are typically designators starting with T; helicopters with H.
    if icao[0] == "T":
        return "helicopter"
    if icao[0] == "H":
        return "helicopter"
    # Brantly B-2 uses designator B2; emitter category B2 is light aircraft — use type field only.
    if icao == "B2":
        return "helicopter"
    return "fixed_wing"


def classify_segment(features: SegmentFeatures, config: ClassifierConfig) -> tuple[str, str]:
    icao_type = (features.icao_type or "").upper()
    emitter = (features.emitter_category or "").upper()
    vehicle_class = infer_vehicle_class(features.icao_type, config)

    if is_always_ifr_emitter(emitter) or is_always_ifr_type(icao_type, config):
        return "ifr", vehicle_class
    if is_always_vfr_type(icao_type, config):
        return "vfr_type", vehicle_class

    return "unknown", vehicle_class
