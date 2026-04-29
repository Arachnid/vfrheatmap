from __future__ import annotations

import numpy as np
import xarray as xr

from adsb_vfr.lib.era5_lookup import Era5Lookup


def test_pressure_to_qnh_formula() -> None:
    ds = xr.Dataset(
        {"msl": (("time", "latitude", "longitude"), np.ones((1, 1, 1), dtype=np.float64) * 101325.0)},
        coords={
            "time": np.array(["2025-01-01T00:00:00"], dtype="datetime64[ns]"),
            "latitude": np.array([51.0]),
            "longitude": np.array([-1.0]),
        },
    )
    lookup = Era5Lookup(dataset=ds)
    corrected = lookup.pressure_to_qnh_alt_ft(np.array([5000.0]), np.array([1023.25]))
    assert corrected[0] == 5000.0 + (10.0 * 27.3)


def test_correct_altitudes_uses_pressure_altitude_at_or_above_transition() -> None:
    """MSLP correction only below 3000 ft PA; at/above transition use uncorrected pressure altitude."""
    ds = xr.Dataset(
        {"msl": (("time", "latitude", "longitude"), np.ones((1, 1, 1), dtype=np.float64) * 102_325.0)},
        coords={
            "time": np.array(["2025-01-01T00:00:00"], dtype="datetime64[ns]"),
            "latitude": np.array([51.0]),
            "longitude": np.array([-1.0]),
        },
    )
    lookup = Era5Lookup(dataset=ds)
    pa = np.array([2000.0, 3000.0, 5000.0], dtype=np.float64)
    lats = np.full(3, 51.0)
    lons = np.full(3, -1.0)
    ts = np.array(
        ["2025-01-01T00:00:00", "2025-01-01T00:00:00", "2025-01-01T00:00:00"],
        dtype="datetime64[ns]",
    )
    out = lookup.correct_altitudes(pa, lats, lons, ts)
    assert abs(float(out[0]) - (2000.0 + 10.0 * 27.3)) < 1e-6
    assert abs(float(out[1]) - 3000.0) < 1e-9
    assert abs(float(out[2]) - 5000.0) < 1e-9
