from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

import numpy as np
import xarray as xr


@dataclass
class Era5Lookup:
    dataset: xr.Dataset

    @classmethod
    def from_netcdfs(cls, paths: Sequence[Path]) -> "Era5Lookup":
        if not paths:
            raise ValueError("No ERA5 NetCDF paths provided.")
        datasets = [xr.open_dataset(str(p)) for p in paths]
        if len(datasets) == 1:
            ds = datasets[0]
        else:
            ds = xr.combine_by_coords(datasets)
        if "time" not in ds.coords and "valid_time" in ds.coords:
            ds = ds.rename({"valid_time": "time"})
        if "msl" not in ds:
            raise ValueError("ERA5 dataset missing `msl` variable (mean sea-level pressure).")
        return cls(dataset=ds)

    def lookup_hpa(self, lats: np.ndarray, lons: np.ndarray, timestamps: np.ndarray) -> np.ndarray:
        times = np.asarray(timestamps, dtype="datetime64[ns]")
        selected = self.dataset["msl"].sel(
            latitude=xr.DataArray(lats, dims="points"),
            longitude=xr.DataArray(lons, dims="points"),
            time=xr.DataArray(times, dims="points"),
            method="nearest",
        )
        return (selected.values.astype(np.float64) / 100.0).reshape(-1)

    def pressure_to_qnh_alt_ft(self, pressure_alt_ft: np.ndarray, mslp_hpa: np.ndarray) -> np.ndarray:
        # Technically MSLP != local QNH, but this difference is tiny (<0.5 hPa),
        # well below METAR quantisation and our 100ft/500ft aggregation scale.
        return pressure_alt_ft + (mslp_hpa - 1013.25) * 27.3

    def correct_altitudes(
        self,
        pressure_alt_ft: np.ndarray,
        lats: np.ndarray,
        lons: np.ndarray,
        timestamps: np.ndarray,
    ) -> np.ndarray:
        mslp_hpa = self.lookup_hpa(lats=lats, lons=lons, timestamps=timestamps)
        return self.pressure_to_qnh_alt_ft(pressure_alt_ft=pressure_alt_ft, mslp_hpa=mslp_hpa)

