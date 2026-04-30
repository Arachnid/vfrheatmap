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


def test_qnh_amsl_ft_applies_mslp_at_all_pressure_altitudes() -> None:
    """ERA5 MSLP correction applies at every pressure altitude (not only below transition)."""
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
    out = lookup.qnh_amsl_ft(pa, lats, lons, ts)
    expected_delta = 10.0 * 27.3
    for i in range(3):
        assert abs(float(out[i]) - (pa[i] + expected_delta)) < 1e-6
