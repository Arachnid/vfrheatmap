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
