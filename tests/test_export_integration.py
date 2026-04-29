from __future__ import annotations

import gzip
import json
from pathlib import Path

import duckdb
import h3

from adsb_vfr.tiles.export import BuildTilesConfig, build_tiles


def _create_test_db(path: Path) -> None:
    conn = duckdb.connect(str(path))
    conn.execute(
        """
        CREATE TABLE ingest_runs (
          run_id INTEGER,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          start_date DATE,
          end_date DATE,
          bbox VARCHAR,
          classifier_config_hash VARCHAR
        )
        """
    )
    conn.execute(
        """
        INSERT INTO ingest_runs VALUES
        (1, now(), now(), DATE '2026-03-01', DATE '2026-03-01', '49,-8,61,2', 'abc123')
        """
    )
    for classification in ("vfr", "ifr", "unknown"):
        for res in (6, 7, 8, 9):
            conn.execute(
                f"""
                CREATE TABLE aggregates_{classification}_res{res} (
                  h3_cell UBIGINT,
                  alt_bin SMALLINT,
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
            h3_cell = int(h3.str_to_int(h3.latlng_to_cell(51.0, -1.0, res)))
            conn.execute(
                f"""
                INSERT INTO aggregates_{classification}_res{res}
                VALUES (?, 25, 'fixed_wing', 3, 120.0, 80.0, 40.0, 240.0, 480.0, 4)
                """,
                [h3_cell],
            )
    conn.close()


def test_build_tiles_writes_manifest_and_tile(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "aggregates.duckdb"
    out_dir = tmp_path / "data"
    _create_test_db(db_path)

    def _fake_airspace(*args, **kwargs) -> None:  # noqa: ANN002, ANN003
        airspace_dir = out_dir / "airspace"
        airspace_dir.mkdir(parents=True, exist_ok=True)
        with gzip.open(airspace_dir / "uk.geojson.gz", "wt", encoding="utf-8") as handle:
            json.dump({"type": "FeatureCollection", "features": []}, handle)
        (airspace_dir / "style.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("adsb_vfr.tiles.export.write_airspace_outputs", _fake_airspace)

    build_tiles(
        BuildTilesConfig(
            input_path=db_path,
            output_dir=out_dir,
            bbox=None,
            api_key="dummy",
            cache_dir=tmp_path / "cache",
            refresh_airspace=False,
        )
    )

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["classifier_config_hash"] == "abc123"
    assert manifest["date_range"]["start"] == "2026-03-01"
    tiles = list((out_dir / "tiles").glob("**/*.json.gz"))
    assert len(tiles) > 0

