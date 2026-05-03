from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import duckdb

from adsb_vfr.config import ClassifierConfig
from adsb_vfr.pipeline import IngestResult

LOGGER = logging.getLogger(__name__)


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


def _ensure_aggregate_table(conn: duckdb.DuckDBPyConnection, group_name: str) -> None:
    table_name = f"aggregates_{group_name}"
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
          agg_date DATE,
          h3_cell UBIGINT,
          vehicle_class VARCHAR,
          flight_count INTEGER,
          time_seconds DOUBLE,
          sum_cos_track DOUBLE,
          sum_sin_track DOUBLE,
          sum_speed DOUBLE,
          sum_speed_sq DOUBLE,
          point_count INTEGER
        )
        """
    )


def _replace_aggregate_days(
    conn: duckdb.DuckDBPyConnection,
    source_glob: str,
    group_name: str,
    start_date: date,
    end_date: date,
) -> None:
    table_name = f"aggregates_{group_name}"
    conn.execute(
        f"DELETE FROM {table_name} WHERE agg_date BETWEEN ? AND ?",
        [start_date, end_date],
    )
    conn.execute(
        f"""
        INSERT INTO {table_name}
        SELECT
          CAST(agg_date AS DATE) AS agg_date,
          CAST(h3_cell AS UBIGINT) AS h3_cell,
          CAST(vehicle_class AS VARCHAR) AS vehicle_class,
          CAST(flight_count AS INTEGER) AS flight_count,
          CAST(time_seconds AS DOUBLE) AS time_seconds,
          CAST(sum_cos_track AS DOUBLE) AS sum_cos_track,
          CAST(sum_sin_track AS DOUBLE) AS sum_sin_track,
          CAST(sum_speed AS DOUBLE) AS sum_speed,
          CAST(sum_speed_sq AS DOUBLE) AS sum_speed_sq,
          CAST(agg_point_count AS INTEGER) AS point_count
        FROM read_parquet(?, union_by_name=true)
        WHERE row_type = 'aggregate'
          AND classification_group = ?
          AND CAST(agg_date AS DATE) BETWEEN ? AND ?
        """,
        [source_glob, group_name, start_date, end_date],
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
          classifier_config_hash VARCHAR,
          unknown_traces_dropped INTEGER
        )
        """
    )
    conn.execute("ALTER TABLE ingest_runs ADD COLUMN IF NOT EXISTS unknown_traces_dropped INTEGER")
    next_run_id = conn.execute("SELECT COALESCE(MAX(run_id), 0) + 1 FROM ingest_runs").fetchone()[0]
    conn.execute(
        """
        INSERT INTO ingest_runs (
          run_id, started_at, finished_at, start_date, end_date, bbox, classifier_config_hash, unknown_traces_dropped
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            int(next_run_id),
            payload.started_at,
            payload.finished_at,
            payload.start_date,
            payload.end_date,
            ",".join(str(v) for v in payload.bbox),
            payload.classifier_config.config_hash,
            payload.ingest_result.unknown_traces_dropped,
        ],
    )


def finalise_to_duckdb(payload: FinaliseInput) -> None:
    payload.output_path.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(payload.output_path))
    source_glob = str(payload.ingest_result.pipeline_output_dir / "*.parquet")

    for group in ("vfr", "ifr", "helicopter"):
        _ensure_aggregate_table(conn=conn, group_name=group)
        _replace_aggregate_days(
            conn=conn,
            source_glob=source_glob,
            group_name=group,
            start_date=payload.start_date,
            end_date=payload.end_date,
        )

    _write_ingest_run(conn=conn, payload=payload)
    conn.close()
    LOGGER.info("Removing temporary pipeline directory %s ...", payload.ingest_result.temp_dir)
    shutil.rmtree(payload.ingest_result.temp_dir, ignore_errors=True)

