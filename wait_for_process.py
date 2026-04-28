#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import time


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Exists but not signalable by this user.
        return True
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Wait until a PID exits, or until timeout.",
    )
    parser.add_argument("pid", type=int, help="Process ID to monitor.")
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=600.0,
        help="Maximum wait time in seconds (default: 600).",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval in seconds (default: 2).",
    )
    args = parser.parse_args()

    if args.pid <= 0:
        print("PID must be a positive integer.")
        return 2
    if args.max_seconds < 0:
        print("--max-seconds must be >= 0.")
        return 2
    if args.interval_seconds <= 0:
        print("--interval-seconds must be > 0.")
        return 2

    start = time.monotonic()
    deadline = start + args.max_seconds

    while _pid_exists(args.pid):
        now = time.monotonic()
        if now >= deadline:
            print(f"Timed out after {args.max_seconds:.1f}s waiting for PID {args.pid}.")
            return 124
        remaining = deadline - now
        time.sleep(min(args.interval_seconds, max(0.0, remaining)))

    elapsed = time.monotonic() - start
    print(f"PID {args.pid} exited after {elapsed:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
