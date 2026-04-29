from __future__ import annotations

from dataclasses import dataclass

from adsb_vfr.config import ClassifierConfig


VFR_CLASSES = {"vfr_high", "vfr_medium", "vfr_type"}
ALWAYS_IFR_EMITTER_CATEGORIES = {"A2", "A3", "A4", "A5", "A6", "A7"}
ALWAYS_VFR_TYPES = {
    "C42",
    "EV97",
    "P92",
    "P96",
    "SAVG",
    "SHIP",
    "SKR",
    "FK9",
    "FK14",
    "AT3",
    "CTSW",
    "CTLS",
    "SR1",
    "DYN",
    "VL3",
    "PIO3",
    "EUPA",
    "P2002",
    "P2008",
    "S6",
    "S7",
    "AVID",
    "KITF",
    "X32",
    "QUIK",
    "GA7B",
    "PEGS",
    "WT9",
    "PPC",
    "MTO3",
    "CALI",
    "CAVN",
    "EL07",
    "MAGN",
    "AS21",
    "AS25",
    "DG10",
    "DUOD",
    "ARCE",
    "DISC",
    "LS8",
    "JANS",
    "NIMB",
    "VENT",
    "G103",
    "G102",
    "DIMO",
    "TMOT",
    "S10",
    "SF25",
    "TIGR",
    "DH82",
    "STMP",
    "CUB",
    "J3",
    "PA18",
    "CHAM",
    "AC11",
    "DR22",
    "JOD1",
    "JDEL",
    "EUROFOX",
    "EFOX",
    "RV3",
    "RV4",
    "BALL",
}


@dataclass(frozen=True)
class SegmentFeatures:
    squawk: str
    icao_type: str
    emitter_category: str
    max_alt_qnh_ft: float
    straightness: float

def is_always_ifr_emitter(emitter_category: str) -> bool:
    return (emitter_category or "").strip().upper() in ALWAYS_IFR_EMITTER_CATEGORIES


def is_always_vfr_type(icao_type: str) -> bool:
    return (icao_type or "").strip().upper() in ALWAYS_VFR_TYPES


def classify_segment(features: SegmentFeatures, config: ClassifierConfig) -> tuple[str, str]:
    _ = config
    icao_type = (features.icao_type or "").upper()
    emitter = (features.emitter_category or "").upper()

    if emitter == "B2" or icao_type.startswith("H"):
        vehicle_class = "helicopter"
    else:
        vehicle_class = "fixed_wing"

    if is_always_ifr_emitter(emitter):
        return "ifr", vehicle_class
    if is_always_vfr_type(icao_type):
        return "vfr_type", vehicle_class

    return "unknown", vehicle_class

