"""Altitude bin mapping (see adsb_vfr/lib/altitude_bins.py)."""

from __future__ import annotations

import numpy as np

from adsb_vfr.lib.altitude_bins import (
    HIGH_BAND_FT,
    N_LOW_BINS,
    TRANSITION_ALTITUDE_FT,
    altitude_ft_to_bin,
    max_altitude_bin_index,
)


def test_altitude_ft_to_bin_low_band_100ft() -> None:
    assert altitude_ft_to_bin(0.0) == 0
    assert altitude_ft_to_bin(99.9) == 0
    assert altitude_ft_to_bin(100.0) == 1
    assert altitude_ft_to_bin(2999.0) == 29


def test_altitude_ft_to_bin_at_transition() -> None:
    assert altitude_ft_to_bin(TRANSITION_ALTITUDE_FT) == N_LOW_BINS
    assert altitude_ft_to_bin(3000.0 + HIGH_BAND_FT - 1) == N_LOW_BINS
    assert altitude_ft_to_bin(3000.0 + HIGH_BAND_FT) == N_LOW_BINS + 1


def test_altitude_ft_to_bin_high_band_500ft() -> None:
    assert altitude_ft_to_bin(5000.0) == N_LOW_BINS + int((5000 - TRANSITION_ALTITUDE_FT) / HIGH_BAND_FT)
    assert altitude_ft_to_bin(5000.0) == 34


def test_max_bin_matches_clip() -> None:
    assert max_altitude_bin_index() == altitude_ft_to_bin(65_000.0)
    assert max_altitude_bin_index() == N_LOW_BINS + int(
        np.floor((65_000.0 - TRANSITION_ALTITUDE_FT) / HIGH_BAND_FT)
    )

