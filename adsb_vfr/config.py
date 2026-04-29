from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_BBOX = (49.0, -8.0, 61.0, 2.0)
DEFAULT_GAP_SECONDS = 120


@dataclass(frozen=True)
class ThresholdConfig:
    gap_seconds: int
    vfr_alt_max_ft: float
    ifr_alt_min_ft: float
    vfr_straightness_max: float
    ifr_straightness_min: float


@dataclass(frozen=True)
class ClassifierConfig:
    thresholds: ThresholdConfig
    listening_squawks: frozenset[str]
    known_vfr_only_types: frozenset[str]
    known_ifr_only_types: frozenset[str]
    known_ifr_capable_types: frozenset[str]
    ifr_discrete_ranges: tuple[tuple[int, int], ...]

    @property
    def config_hash(self) -> str:
        payload = {
            "thresholds": {
                "gap_seconds": self.thresholds.gap_seconds,
                "vfr_alt_max_ft": self.thresholds.vfr_alt_max_ft,
                "ifr_alt_min_ft": self.thresholds.ifr_alt_min_ft,
                "vfr_straightness_max": self.thresholds.vfr_straightness_max,
                "ifr_straightness_min": self.thresholds.ifr_straightness_min,
            },
            "listening_squawks": sorted(self.listening_squawks),
            "known_vfr_only_types": sorted(self.known_vfr_only_types),
            "known_ifr_only_types": sorted(self.known_ifr_only_types),
            "known_ifr_capable_types": sorted(self.known_ifr_capable_types),
            "ifr_discrete_ranges": [list(r) for r in self.ifr_discrete_ranges],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_classifier_config(config_dir: Path) -> ClassifierConfig:
    defaults = _load_json(config_dir / "classifier_defaults.json")
    listening = _load_json(config_dir / "listening_squawks.json")
    vfr_types = _load_json(config_dir / "vfr_only_types.json")
    ifr_only_types = _load_json(config_dir / "ifr_only_types.json")
    ifr_types = _load_json(config_dir / "ifr_capable_types.json")
    ifr_ranges = _load_json(config_dir / "ifr_discrete_ranges.json")

    thresholds = ThresholdConfig(
        gap_seconds=int(defaults.get("gap_seconds", DEFAULT_GAP_SECONDS)),
        vfr_alt_max_ft=float(defaults.get("vfr_alt_max_ft", 10_000.0)),
        ifr_alt_min_ft=float(defaults.get("ifr_alt_min_ft", 15_000.0)),
        vfr_straightness_max=float(defaults.get("vfr_straightness_max", 0.85)),
        ifr_straightness_min=float(defaults.get("ifr_straightness_min", 0.95)),
    )

    return ClassifierConfig(
        thresholds=thresholds,
        listening_squawks=frozenset(str(v) for v in listening),
        known_vfr_only_types=frozenset(str(v).upper() for v in vfr_types),
        known_ifr_only_types=frozenset(str(v).upper() for v in ifr_only_types),
        known_ifr_capable_types=frozenset(str(v).upper() for v in ifr_types),
        ifr_discrete_ranges=tuple((int(r[0]), int(r[1])) for r in ifr_ranges),
    )


def bbox_hash(bbox: tuple[float, float, float, float]) -> str:
    text = ",".join(f"{x:.4f}" for x in bbox)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]

