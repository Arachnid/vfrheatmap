#!/usr/bin/env python3
"""Run sequential 14-day ingest windows; child process inherits stdout/stderr (no log file)."""
from __future__ import annotations

import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = date(2025, 5, 16)
END = date(2026, 1, 31)


def _batch_count() -> int:
    n, cur = 0, START
    while cur <= END:
        batch_end = min(cur + timedelta(days=13), END)
        n += 1
        cur = batch_end + timedelta(days=1)
    return n


def main() -> None:
    total = _batch_count()
    exe = sys.executable
    cur = START
    batch = 0
    while cur <= END:
        batch_end = min(cur + timedelta(days=13), END)
        batch += 1
        sd, ed = cur.isoformat(), batch_end.isoformat()
        print(
            f"\n{'=' * 60}\nBatch {batch}/{total}: {sd} .. {ed}\n{'=' * 60}\n",
            flush=True,
        )
        r = subprocess.run(
            [
                exe,
                "-m",
                "adsb_vfr.cli",
                "ingest",
                "--start-date",
                sd,
                "--end-date",
                ed,
                "--skip-fetch",
                "--log-level",
                "INFO",
            ],
            cwd=str(ROOT),
        )
        if r.returncode != 0:
            print(f"Batch {batch} failed with exit {r.returncode}", flush=True)
            sys.exit(r.returncode)
        cur = batch_end + timedelta(days=1)
    print(f"\nAll {total} two-week batches completed.\n", flush=True)


if __name__ == "__main__":
    main()
