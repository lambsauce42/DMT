from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from save_paths import dnd_saves_dir

ITEM_FILE_EXTENSION = ".dmtitem"
LEGACY_ITEM_FILE_EXTENSION = ".json"
ITEM_FILE_FORMAT = "dmtitem.v1"
ITEM_FILE_PATTERNS = ("*.dmtitem", "*.json")

_ITEM_ICON_DIRS = (
    Path(__file__).resolve().parent.parent / "assets" / "itemicons",
    Path(__file__).resolve().parent.parent / "assets" / "iconitems",
)


def list_item_file_paths(root: Path) -> list[Path]:
    if not root.exists():
        return []
    by_key: dict[str, Path] = {}
    for pattern in ITEM_FILE_PATTERNS:
        for path in root.rglob(pattern):
            if not path.is_file():
                continue
            key = str(path.resolve()).lower()
            by_key[key] = path
    return sorted(by_key.values(), key=lambda path: str(path).lower())


def resolve_item_icon_source(
    raw: Optional[str],
    *,
    base_path: Optional[Path] = None,
) -> Optional[Path]:
    text = str(raw or "").strip()
    if not text:
        return None

    expanded = Path(os.path.expanduser(text))
    if expanded.is_absolute() and expanded.exists():
        return expanded
    if expanded.exists():
        return expanded.resolve()

    if base_path is not None and not expanded.is_absolute():
        relative_to_base = (base_path.parent / expanded).resolve()
        if relative_to_base.exists():
            return relative_to_base

    icon_name = expanded.name
    if icon_name:
        for icon_dir in _ITEM_ICON_DIRS:
            candidate = (icon_dir / icon_name).resolve()
            if candidate.exists():
                return candidate

    return None


def build_item_document(payload: dict, icon_source: Optional[str]) -> dict:
    document: dict[str, object] = {
        "format": ITEM_FILE_FORMAT,
        "payload": dict(payload),
    }
    icon_path = resolve_item_icon_source(icon_source)
    if icon_path is None:
        return document
    try:
        raw = icon_path.read_bytes()
    except Exception:
        return document
    if not raw:
        return document
    document["icon"] = {
        "name": icon_path.name,
        "encoding": "base64",
        "data": base64.b64encode(raw).decode("ascii"),
    }
    return document


def _materialize_embedded_icon(path: Path, icon_payload: dict) -> Optional[str]:
    encoded = str(icon_payload.get("data") or "").strip()
    if not encoded:
        return None
    try:
        icon_raw = base64.b64decode(encoded, validate=True)
    except Exception:
        return None
    if not icon_raw:
        return None

    icon_name = str(icon_payload.get("name") or "icon.bin").strip() or "icon.bin"
    suffix = Path(icon_name).suffix.lower()
    if not suffix or any(ch for ch in suffix if not (ch.isalnum() or ch == ".")):
        suffix = ".bin"
    digest = hashlib.sha256(icon_raw).hexdigest()
    cache_dir = dnd_saves_dir() / "cache" / "item_icons"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        icon_path = cache_dir / f"{digest}{suffix}"
        if not icon_path.exists():
            icon_path.write_bytes(icon_raw)
        return str(icon_path)
    except Exception:
        return None


def load_item_payload(path: Path) -> Optional[dict]:
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    if str(data.get("format") or "").strip().lower() != ITEM_FILE_FORMAT:
        return data

    payload = data.get("payload")
    if not isinstance(payload, dict):
        return None
    resolved_payload = dict(payload)
    icon_payload = data.get("icon")
    if isinstance(icon_payload, dict):
        icon_path = _materialize_embedded_icon(path, icon_payload)
        if icon_path:
            resolved_payload["icon_path"] = icon_path
    return resolved_payload
