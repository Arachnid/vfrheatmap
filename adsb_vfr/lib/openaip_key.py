from __future__ import annotations

import os
from pathlib import Path


DEFAULT_DOTFILE_NAME = ".openaip-api-key"


def _read_key_file(path: Path) -> str:
    if not path.exists():
        return ""
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        return ""
    for line in value.splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith("#"):
            continue
        return candidate
    return ""


def resolve_openaip_api_key(
    explicit_key: str | None = None,
    *,
    dotfile_path: Path | None = None,
) -> str:
    if explicit_key and explicit_key.strip():
        return explicit_key.strip()
    if dotfile_path is not None:
        key = _read_key_file(dotfile_path)
        if key:
            return key
    repo_dotfile = Path.cwd() / DEFAULT_DOTFILE_NAME
    key = _read_key_file(repo_dotfile)
    if key:
        return key
    home_dotfile = Path.home() / DEFAULT_DOTFILE_NAME
    key = _read_key_file(home_dotfile)
    if key:
        return key
    env_key = os.getenv("OPENAIP_API_KEY", "").strip()
    if env_key:
        return env_key
    return ""

