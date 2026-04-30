"""Tests for FL vs AMSL vertical airspace checks and AGL lower behaviour."""

from __future__ import annotations

from adsb_vfr.lib.airspace_vertical import point_in_airspace_vertically


def test_fl_band_uses_pressure_altitude_only() -> None:
    """FL lower/upper: aircraft datum is pressure altitude (ft)."""
    assert point_in_airspace_vertically(
        pressure_alt_ft=10_500.0,
        qnh_amsl_ft=11_000.0,
        lower_ft=10_000,
        lower_ref="FL",
        upper_ft=15_000,
        upper_ref="FL",
    )
    assert not point_in_airspace_vertically(
        pressure_alt_ft=16_000.0,
        qnh_amsl_ft=16_200.0,
        lower_ft=10_000,
        lower_ref="FL",
        upper_ft=15_000,
        upper_ref="FL",
    )


def test_amsl_band_uses_qnh_amsl_only() -> None:
    """AMSL lower/upper: aircraft datum is QNH/MSLP AMSL (ft)."""
    assert point_in_airspace_vertically(
        pressure_alt_ft=5000.0,
        qnh_amsl_ft=3500.0,
        lower_ft=3000,
        lower_ref="AMSL",
        upper_ft=4000,
        upper_ref="AMSL",
    )
    assert not point_in_airspace_vertically(
        pressure_alt_ft=5000.0,
        qnh_amsl_ft=4500.0,
        lower_ft=3000,
        lower_ref="AMSL",
        upper_ft=4000,
        upper_ref="AMSL",
    )


def test_mixed_fl_lower_amsl_upper() -> None:
    """Each limit uses its own reference (FL lower, AMSL upper)."""
    assert point_in_airspace_vertically(
        pressure_alt_ft=10_500.0,
        qnh_amsl_ft=9800.0,
        lower_ft=10_000,
        lower_ref="FL",
        upper_ft=10_000,
        upper_ref="AMSL",
    )
    assert not point_in_airspace_vertically(
        pressure_alt_ft=10_500.0,
        qnh_amsl_ft=10_500.0,
        lower_ft=10_000,
        lower_ref="FL",
        upper_ft=10_000,
        upper_ref="AMSL",
    )


def test_agl_lower_means_no_lower_bound_upper_amsl_still_enforced() -> None:
    """Lower AGL: do not require a minimum altitude; still enforce AMSL ceiling."""
    assert point_in_airspace_vertically(
        pressure_alt_ft=500.0,
        qnh_amsl_ft=480.0,
        lower_ft=0,
        lower_ref="AGL",
        upper_ft=2500,
        upper_ref="AMSL",
    )
    assert not point_in_airspace_vertically(
        pressure_alt_ft=4000.0,
        qnh_amsl_ft=3500.0,
        lower_ft=0,
        lower_ref="AGL",
        upper_ft=2500,
        upper_ref="AMSL",
    )


def test_agl_lower_upper_fl_still_enforced() -> None:
    """With lower AGL, FL cap is still compared to pressure altitude."""
    assert point_in_airspace_vertically(
        pressure_alt_ft=3500.0,
        qnh_amsl_ft=3200.0,
        lower_ft=0,
        lower_ref="AGL",
        upper_ft=5000,
        upper_ref="FL",
    )
    assert not point_in_airspace_vertically(
        pressure_alt_ft=6000.0,
        qnh_amsl_ft=5800.0,
        lower_ft=0,
        lower_ref="AGL",
        upper_ft=5000,
        upper_ref="FL",
    )


def test_amsl_lower_not_satisfied_even_when_pressure_high() -> None:
    """Below AMSL floor fails even if pressure altitude would suggest FL band overlap."""
    assert not point_in_airspace_vertically(
        pressure_alt_ft=8000.0,
        qnh_amsl_ft=2500.0,
        lower_ft=3000,
        lower_ref="AMSL",
        upper_ft=12_000,
        upper_ref="AMSL",
    )
