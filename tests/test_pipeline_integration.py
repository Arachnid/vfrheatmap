from __future__ import annotations

import io
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import numpy as np
import orjson
import pytest
import ray
import xarray as xr

from adsb_vfr.config import load_classifier_config
from adsb_vfr.finalise import FinaliseInput, finalise_to_duckdb
from adsb_vfr.pipeline import build_and_run_pipeline, load_era5_lookup


@pytest.fixture(scope="module", autouse=True)
def _ray_cluster():
    ray.init(num_cpus=4, num_gpus=0, include_dashboard=False, ignore_reinit_error=True)
    yield
    ray.shutdown()


def _write_tarball(path: Path, payloads: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w") as tar:
        for idx, payload in enumerate(payloads):
            data = orjson.dumps(payload)
            info = tarfile.TarInfo(name=f"trace_{idx}.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def _make_payload(hex_id: str, base_ts: int, squawk: str, icao_type: str, emitter: str, alt1: float, alt2: float) -> dict:
    return {
        "hex": hex_id,
        "timestamp": base_ts,
        "t": icao_type,
        "category": emitter,
        "trace": [
            [0, 51.0, -1.0, alt1, 80.0, 90.0, 0, 0, {}, "adsb", 0, squawk],
            [60, 51.001, -1.001, alt2, 85.0, 92.0, 0, 0, {}, "adsb", 0, squawk],
        ],
    }


def _write_era5(path: Path, start_dt: np.datetime64, hours: int = 6) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    times = np.array([start_dt + np.timedelta64(i, "h") for i in range(hours)], dtype="datetime64[ns]")
    lats = np.array([49.0, 55.0, 61.0], dtype=np.float64)
    lons = np.array([-8.0, -3.0, 2.0], dtype=np.float64)
    msl = np.ones((len(times), len(lats), len(lons)), dtype=np.float64) * 101325.0
    ds = xr.Dataset({"msl": (("time", "latitude", "longitude"), msl)}, coords={"time": times, "latitude": lats, "longitude": lons})
    ds.to_netcdf(path)


def test_end_to_end_pipeline(tmp_path: Path) -> None:
    cfg = load_classifier_config(Path("config"))
    trace1 = tmp_path / "cache" / "traces" / "2025-01-01" / "2025-01-01.tar"
    base1 = int(datetime(2025, 1, 1, 12, 0, tzinfo=UTC).timestamp())
    _write_tarball(
        trace1,
        [
            _make_payload("ABC123", base1, "7000", "C152", "A1", 1500, 1800),
                _make_payload("DEF456", base1, "1200", "SR22", "A3", 16000, 16200),
        ],
    )
    era5 = tmp_path / "cache" / "era5" / "mslp_2025-01_test.nc"
    _write_era5(era5, np.datetime64("2025-01-01T00:00:00"))
    bbox = (49.0, -8.0, 61.0, 2.0)
    lookup = load_era5_lookup([era5], bbox=bbox, start=date(2025, 1, 1), end=date(2025, 1, 1))
    result = build_and_run_pipeline(
        trace_items=[(date(2025, 1, 1), trace1)],
        era5_ref=ray.put(lookup),
        classifier_config=cfg,
        bbox=bbox,
    )
    out_db = tmp_path / "out.duckdb"
    finalise_to_duckdb(
        FinaliseInput(
            output_path=out_db,
            started_at=datetime(2025, 1, 3, tzinfo=UTC),
            finished_at=datetime(2025, 1, 3, tzinfo=UTC),
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            bbox=bbox,
            classifier_config=cfg,
            ingest_result=result,
        )
    )
    conn = duckdb.connect(str(out_db))
    try:
        vfr_count = conn.execute("SELECT COUNT(*) FROM aggregates_vfr WHERE agg_date = DATE '2025-01-01'").fetchone()[0]
        ifr_count = conn.execute("SELECT COUNT(*) FROM aggregates_ifr WHERE agg_date = DATE '2025-01-01'").fetchone()[0]
        run_count = conn.execute("SELECT COUNT(*) FROM ingest_runs").fetchone()[0]
        dropped_unknown = conn.execute("SELECT unknown_traces_dropped FROM ingest_runs LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    assert vfr_count > 0
    assert ifr_count > 0
    assert run_count == 1
    assert int(dropped_unknown) >= 0
