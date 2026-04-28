from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from adsb_vfr.config import ClassifierConfig
from adsb_vfr.pipeline import IngestResult


@dataclass(frozen=True)
class FinaliseInput:
    output_path: Path
    started_at: datetime
    finished_at: datetime
    start_date: date
    end_date: date
    bbox: tuple[float, float, float, float]
    classifier_config: ClassifierConfig
    ingest_result: IngestResult


def _render_track_hist_expr(prefix: str = "track_hist_") -> str:
    return "list_value(" + ",".join(f"CAST(round({prefix}{i}) AS INTEGER)" for i in range(16)) + ")"


def _create_aggregate_table(conn: duckdb.DuckDBPyConnection, source_glob: str, group_name: str, resolution: int) -> None:
    table_name = f"aggregates_{group_name}_res{resolution}"
    hist_expr = _render_track_hist_expr()
    conn.execute(
        f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT
          CAST(h3_cell AS UBIGINT) AS h3_cell,
          CAST(alt_bin AS SMALLINT) AS alt_bin,
          CAST(vehicle_class AS VARCHAR) AS vehicle_class,
          CAST(flight_count AS INTEGER) AS flight_count,
          CAST(time_seconds AS DOUBLE) AS time_seconds,
          CAST(sum_cos_track AS DOUBLE) AS sum_cos_track,
          CAST(sum_sin_track AS DOUBLE) AS sum_sin_track,
          {hist_expr} AS track_hist,
          CAST(sum_speed AS DOUBLE) AS sum_speed,
          CAST(sum_speed_sq AS DOUBLE) AS sum_speed_sq,
          CAST(agg_point_count AS INTEGER) AS point_count
        FROM read_parquet(?, union_by_name=true)
        WHERE row_type = 'aggregate' AND classification_group = ? AND resolution = ?
        """,
        [source_glob, group_name, resolution],
    )


def _write_ingest_run(conn: duckdb.DuckDBPyConnection, payload: FinaliseInput) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingest_runs (
          run_id INTEGER PRIMARY KEY,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          start_date DATE,
          end_date DATE,
          bbox VARCHAR,
          classifier_config_hash VARCHAR
        )
        """
    )
    next_run_id = conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM ingest_runs").fetchone()[0]
    conn.execute(
        """
        INSERT INTO ingest_runs (
          run_id, started_at, finished_at, start_date, end_date, bbox, classifier_config_hash
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            int(next_run_id),
            payload.started_at,
            payload.finished_at,
            payload.start_date,
            payload.end_date,
            ",".join(str(v) for v in payload.bbox),
            payload.classifier_config.config_hash,
        ],
    )


def finalise_to_duckdb(payload: FinaliseInput) -> None:
    payload.output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(payload.output_path))
    source_glob = str(payload.ingest_result.pipeline_output_dir / "*.parquet")

    for group in ("vfr", "ifr", "unknown"):
        for res in (9, 8, 7, 6):
            _create_aggregate_table(conn=conn, source_glob=source_glob, group_name=group, resolution=res)

    _write_ingest_run(conn=conn, payload=payload)
    conn.close()
    shutil.rmtree(payload.ingest_result.temp_dir, ignore_errors=True)

