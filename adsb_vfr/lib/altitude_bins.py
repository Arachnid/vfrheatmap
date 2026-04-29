"""Altitude bin indices for aggregation and tiles (must match web/src/lib/altitudeBins.ts)."""

from __future__ import annotations

import numpy as np

# Below this AMSL (ft), use 100 ft bins with MSLP-based altitude; at/above, use 500 ft bins and
# pressure altitude (1013.25 hPa) — see Era5Lookup.correct_altitudes.
TRANSITION_ALTITUDE_FT = 3000.0

LOW_BAND_FT = 100.0
HIGH_BAND_FT = 500.0

N_LOW_BINS = int(TRANSITION_ALTITUDE_FT / LOW_BAND_FT)

# Clip aggregation altitude (matches ~FL650 cap used historically).
MAX_AGGREGATION_ALTITUDE_FT = 65_000.0


def altitude_ft_to_bin(altitude_ft: float) -> int:
    """Map altitude (ft) to a contiguous bin index: 0–29 = 100 ft steps below transition; 30+ = 500 ft."""
    alt = float(np.clip(altitude_ft, 0.0, MAX_AGGREGATION_ALTITUDE_FT))
    if alt < TRANSITION_ALTITUDE_FT:
        b = int(np.floor(alt / LOW_BAND_FT))
        return min(b, N_LOW_BINS - 1)
    excess = alt - TRANSITION_ALTITUDE_FT
    b = N_LOW_BINS + int(np.floor(excess / HIGH_BAND_FT))
    max_b = N_LOW_BINS + int(np.floor((MAX_AGGREGATION_ALTITUDE_FT - TRANSITION_ALTITUDE_FT) / HIGH_BAND_FT))
    return min(b, max_b)


def max_altitude_bin_index() -> int:
    return altitude_ft_to_bin(MAX_AGGREGATION_ALTITUDE_FT)
