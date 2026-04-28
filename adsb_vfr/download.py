from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import httpx
from tqdm import tqdm

from adsb_vfr.config import bbox_hash

LOGGER = logging.getLogger(__name__)


GITHUB_API_BASE = "https://api.github.com"
TRACE_REPO_TEMPLATE = "adsblol/globe_history_{year}"
RELEASE_DAY_RE = re.compile(r"^v(?P<year>\d{4})\.(?P<month>\d{2})\.(?P<day>\d{2})-")


@dataclass(frozen=True)
class InputsManifest:
    trace_files: list[tuple[date, Path]]
    era5_files: list[Path]


def _daterange(start_date: date, end_date: date) -> list[date]:
    days: list[date] = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current = date.fromordinal(current.toordinal() + 1)
    return days


def _months_for_range(start_date: date, end_date: date) -> list[tuple[int, int]]:
    y, m = start_date.year, start_date.month
    end = (end_date.year, end_date.month)
    out: list[tuple[int, int]] = []
    while (y, m) <= end:
        out.append((y, m))
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
    return out


async def _download_file(url: str, path: Path, client: httpx.AsyncClient, sem: asyncio.Semaphore) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    async with sem:
        response = await client.get(url, timeout=120.0)
        response.raise_for_status()
        path.write_bytes(response.content)


def _day_from_release_tag(tag_name: str) -> date | None:
    match = RELEASE_DAY_RE.match(tag_name)
    if match is None:
        return None
    try:
        return date(
            year=int(match.group("year")),
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
    except ValueError:
        return None


async def _list_releases_for_year(client: httpx.AsyncClient, year: int) -> list[dict]:
    repo = TRACE_REPO_TEMPLATE.format(year=year)
    releases: list[dict] = []
    page = 1
    while True:
        url = f"{GITHUB_API_BASE}/repos/{repo}/releases"
        response = await client.get(url, params={"per_page": 100, "page": page}, timeout=30.0)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        payload = response.json()
        if not payload:
            break
        if not isinstance(payload, list):
            break
        releases.extend(payload)
        if len(payload) < 100:
            break
        page += 1
    return releases


def _asset_download_urls(release: dict, day: date) -> list[str]:
    assets = release.get("assets", [])
    if not isinstance(assets, list):
        return []

    direct_tar_urls: list[str] = []
    split_urls: list[tuple[str, str]] = []
    day_text = day.isoformat().replace("-", ".")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if not url:
            continue
        if name.endswith(".tar"):
            direct_tar_urls.append(url)
            continue
        if ".tar." in name:
            # Prefer release chunks for the requested day when tags contain multiple flavors.
            if day_text in str(release.get("tag_name", "")) or day.isoformat() in name:
                split_urls.append((name, url))
            else:
                split_urls.append((name, url))
    if direct_tar_urls:
        return [direct_tar_urls[0]]
    if split_urls:
        split_urls.sort(key=lambda item: item[0])
        return [url for _, url in split_urls]
    return []


async def _download_trace_release_to_tar(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    day: date,
    tar_path: Path,
    release: dict,
) -> None:
    urls = _asset_download_urls(release=release, day=day)
    if not urls:
        tag = str(release.get("tag_name", "<unknown>"))
        raise FileNotFoundError(f"No downloadable trace tar assets found in release {tag} for {day.isoformat()}.")

    tar_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = tar_path.with_suffix(".tar.part")
    if tmp_path.exists():
        tmp_path.unlink()
    async with sem:
        with tmp_path.open("wb") as output:
            for url in urls:
                async with client.stream("GET", url, timeout=300.0) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        output.write(chunk)
    tmp_path.replace(tar_path)


async def ensure_trace_tarballs(
    dates: Iterable[date],
    cache_dir: Path,
    skip_fetch: bool,
    concurrency: int,
) -> list[tuple[date, Path]]:
    days = list(dates)
    traces_dir = cache_dir / "traces"
    trace_paths = [(d, traces_dir / d.isoformat() / f"{d.isoformat()}.tar") for d in days]
    missing = [(d, p) for d, p in trace_paths if not p.exists()]
    if missing and skip_fetch:
        sample = ", ".join(d.isoformat() for d, _ in missing[:5])
        raise FileNotFoundError(f"Missing cached trace tarballs while --skip-fetch set: {sample}")
    if not missing:
        return trace_paths

    sem = asyncio.Semaphore(max(1, concurrency))
    headers = {"User-Agent": "adsb-vfr-ingest/0.1"}
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        days_by_year: dict[int, set[date]] = {}
        for day, _ in missing:
            days_by_year.setdefault(day.year, set()).add(day)

        releases_by_day: dict[date, dict] = {}
        for year, needed_days in days_by_year.items():
            releases = await _list_releases_for_year(client=client, year=year)
            for release in releases:
                if not isinstance(release, dict):
                    continue
                tag_name = str(release.get("tag_name", ""))
                release_day = _day_from_release_tag(tag_name)
                if release_day is None:
                    continue
                if release_day in needed_days:
                    releases_by_day[release_day] = release

        unresolved = [day.isoformat() for day, _ in missing if day not in releases_by_day]
        if unresolved:
            sample = ", ".join(unresolved[:8])
            raise FileNotFoundError(f"No matching GitHub release found for trace days: {sample}")

        async def _download_one(day: date, target_path: Path) -> None:
            release = releases_by_day[day]
            await _download_trace_release_to_tar(
                client=client,
                sem=sem,
                day=day,
                tar_path=target_path,
                release=release,
            )

        tasks = [_download_one(day=day, target_path=path) for day, path in missing]
        for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Downloading traces"):
            await coro
    return trace_paths


def _ensure_cdsapi():
    if not Path.home().joinpath(".cdsapirc").exists():
        raise RuntimeError(
            "CDS API credentials missing. Create ~/.cdsapirc first. "
            "See https://cds.climate.copernicus.eu/how-to-api"
        )
    try:
        import cdsapi  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("cdsapi is required for ERA5 downloads.") from exc
    return cdsapi


def _era5_request_dict(year: int, month: int, bbox: tuple[float, float, float, float]) -> dict[str, object]:
    min_lat, min_lon, max_lat, max_lon = bbox
    days = [f"{d:02d}" for d in range(1, 32)]
    hours = [f"{h:02d}:00" for h in range(24)]
    return {
        "product_type": "reanalysis",
        "format": "netcdf",
        "variable": "mean_sea_level_pressure",
        "year": f"{year}",
        "month": f"{month:02d}",
        "day": days,
        "time": hours,
        # ERA5 expects North, West, South, East
        "area": [max_lat, min_lon, min_lat, max_lon],
    }


def _download_era5_month(path: Path, year: int, month: int, bbox: tuple[float, float, float, float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cdsapi = _ensure_cdsapi()
    client = cdsapi.Client(quiet=True, progress=False)
    request = _era5_request_dict(year=year, month=month, bbox=bbox)
    client.retrieve("reanalysis-era5-single-levels", request, str(path))


async def ensure_era5_netcdfs(
    start_date: date,
    end_date: date,
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    skip_fetch: bool,
    concurrency: int,
) -> list[Path]:
    era5_dir = cache_dir / "era5"
    bh = bbox_hash(bbox)
    months = _months_for_range(start_date=start_date, end_date=end_date)
    files = [era5_dir / f"mslp_{y:04d}-{m:02d}_{bh}.nc" for y, m in months]
    missing = [(ym, f) for ym, f in zip(months, files) if not f.exists()]
    if missing and skip_fetch:
        sample = ", ".join(f.name for _, f in missing[:5])
        raise FileNotFoundError(f"Missing cached ERA5 files while --skip-fetch set: {sample}")
    if not missing:
        return files

    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run(month_tuple: tuple[int, int], target: Path) -> None:
        async with sem:
            y, m = month_tuple
            await asyncio.to_thread(_download_era5_month, target, y, m, bbox)

    tasks = [_run(month_tuple=ym, target=p) for ym, p in missing]
    for coro in tqdm(asyncio.as_completed(tasks), total=len(tasks), desc="Downloading ERA5"):
        await coro
    return files


async def ensure_inputs(
    start_date: date,
    end_date: date,
    bbox: tuple[float, float, float, float],
    cache_dir: Path,
    skip_fetch: bool,
    download_concurrency: int,
) -> InputsManifest:
    cache_dir.mkdir(parents=True, exist_ok=True)
    days = _daterange(start_date=start_date, end_date=end_date)
    trace_files = await ensure_trace_tarballs(
        dates=days,
        cache_dir=cache_dir,
        skip_fetch=skip_fetch,
        concurrency=download_concurrency,
    )
    era5_files = await ensure_era5_netcdfs(
        start_date=start_date,
        end_date=end_date,
        bbox=bbox,
        cache_dir=cache_dir,
        skip_fetch=skip_fetch,
        concurrency=max(1, min(download_concurrency, 3)),
    )
    return InputsManifest(trace_files=trace_files, era5_files=era5_files)

