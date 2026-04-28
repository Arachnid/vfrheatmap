from __future__ import annotations

from dataclasses import dataclass

from adsb_vfr.config import ClassifierConfig


VFR_CLASSES = {"vfr_high", "vfr_medium", "vfr_type"}


@dataclass(frozen=True)
class SegmentFeatures:
    squawk: str
    icao_type: str
    emitter_category: str
    max_alt_qnh_ft: float
    straightness: float


def _in_ifr_discrete_range(squawk: str, ranges: tuple[tuple[int, int], ...]) -> bool:
    if not squawk.isdigit():
        return False
    value = int(squawk)
    return any(start <= value <= end for start, end in ranges)


def classify_segment(features: SegmentFeatures, config: ClassifierConfig) -> tuple[str, str]:
    squawk = (features.squawk or "").strip()
    icao_type = (features.icao_type or "").upper()
    emitter = (features.emitter_category or "").upper()
    max_alt = float(features.max_alt_qnh_ft)
    straightness = float(features.straightness)

    if emitter in {"A3", "A4", "A5"}:
        return "heavy", "fixed_wing"

    if emitter == "B2" or icao_type.startswith("H"):
        vehicle_class = "helicopter"
    else:
        vehicle_class = "fixed_wing"

    if squawk == "7000" and max_alt < config.thresholds.vfr_alt_max_ft:
        return "vfr_high", vehicle_class

    if (
        squawk in config.listening_squawks
        and max_alt < config.thresholds.vfr_alt_max_ft
        and straightness < config.thresholds.vfr_straightness_max
    ):
        return "vfr_medium", vehicle_class

    if icao_type in config.known_vfr_only_types:
        return "vfr_type", vehicle_class

    if (
        max_alt > config.thresholds.ifr_alt_min_ft
        or (straightness > config.thresholds.ifr_straightness_min and icao_type in config.known_ifr_capable_types)
        or _in_ifr_discrete_range(squawk, config.ifr_discrete_ranges)
    ):
        return "ifr", vehicle_class

    return "unknown", vehicle_class

