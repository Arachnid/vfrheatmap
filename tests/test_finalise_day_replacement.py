"""Finalise replaces only the requested date range; other days in DuckDB are preserved."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pandas as pd

from adsb_vfr.config import load_classifier_config
from adsb_vfr.finalise import FinaliseInput, finalise_to_duckdb
from adsb_vfr.pipeline import IngestResult


def _write_aggregate_parquet(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_parquet(path, index=False)


def _vfr_row(
    *,
    day: str,
    h3_cell: int,
    point_count: int,
) -> dict:
    return {
        "row_type": "aggregate",
        "agg_date": day,
        "classification_group": "vfr",
        "h3_cell": h3_cell,
        "vehicle_class": "fixed_wing",
        "flight_count": 1,
        "time_seconds": float(point_count),
        "sum_cos_track": 1.0,
        "sum_sin_track": 0.0,
        "sum_speed": 100.0,
        "sum_speed_sq": 10000.0,
        "agg_point_count": point_count,
    }


def test_finalise_replaces_only_days_in_range(tmp_path: Path) -> None:
    cfg = load_classifier_config(Path("config"))
    h3_cell = 999001002003004005

    def run_finalise(start: date, end: date, rows: list[dict]) -> Path:
        ingest_root = tmp_path / f"ingest_{start}_{end}"
        out_parquet = ingest_root / "pipeline_output"
        out_parquet.mkdir(parents=True)
        _write_aggregate_parquet(out_parquet / "part.parquet", rows)
        db_path = tmp_path / "shared.duckdb"
        finalise_to_duckdb(
            FinaliseInput(
                output_path=db_path,
                started_at=datetime.now(tz=UTC),
                finished_at=datetime.now(tz=UTC),
                start_date=start,
                end_date=end,
                bbox=(49.0, -8.0, 61.0, 2.0),
                classifier_config=cfg,
                ingest_result=IngestResult(
                    temp_dir=ingest_root,
                    pipeline_output_dir=out_parquet,
                    unknown_traces_dropped=0,
                ),
            )
        )
        return db_path

    run_finalise(
        date(2025, 1, 1),
        date(2025, 1, 2),
        [
            _vfr_row(day="2025-01-01", h3_cell=h3_cell, point_count=10),
            _vfr_row(day="2025-01-02", h3_cell=h3_cell, point_count=20),
        ],
    )

    run_finalise(
        date(2025, 1, 2),
        date(2025, 1, 2),
        [_vfr_row(day="2025-01-02", h3_cell=h3_cell, point_count=99)],
    )

    conn = duckdb.connect(str(tmp_path / "shared.duckdb"))
    try:
        rows = conn.execute(
            "SELECT CAST(agg_date AS VARCHAR), point_count FROM aggregates_vfr ORDER BY agg_date"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("2025-01-01", 10), ("2025-01-02", 99)]
