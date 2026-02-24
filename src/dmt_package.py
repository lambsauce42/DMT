from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Mapping, Optional


INFO_ENTRY_NAME = "info.json"


def _normalize_asset_name(name: str) -> str:
    cleaned = str(name or "").replace("\\", "/").strip().lstrip("/")
    if not cleaned:
        raise ValueError("Asset name must not be empty.")
    if ".." in cleaned.split("/"):
        raise ValueError("Asset name must not contain parent traversal.")
    return cleaned


def write_dmt_package(
    path: Path,
    *,
    info: dict,
    assets: Optional[Mapping[str, bytes]] = None,
) -> None:
    if not isinstance(info, dict):
        raise TypeError("info must be a dictionary")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(info, ensure_ascii=False, indent=2)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(INFO_ENTRY_NAME, payload)
        for asset_name, asset_bytes in (assets or {}).items():
            normalized_name = _normalize_asset_name(asset_name)
            zf.writestr(normalized_name, bytes(asset_bytes))


def read_dmt_package_info(path: Path) -> Optional[dict]:
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if INFO_ENTRY_NAME not in zf.namelist():
                return None
            payload = json.loads(zf.read(INFO_ENTRY_NAME).decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_dmt_package_asset(path: Path, asset_name: str) -> Optional[bytes]:
    if not path.exists():
        return None
    normalized_name = _normalize_asset_name(asset_name)
    try:
        with zipfile.ZipFile(path, "r") as zf:
            if normalized_name not in zf.namelist():
                return None
            return zf.read(normalized_name)
    except Exception:
        return None


def list_dmt_package_assets(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            return sorted(
                [
                    name
                    for name in zf.namelist()
                    if name and name != INFO_ENTRY_NAME and not name.endswith("/")
                ]
            )
    except Exception:
        return []
