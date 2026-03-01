from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Optional

from dmt_package import (
    read_dmt_package_asset,
    read_dmt_package_info,
    write_dmt_package,
)
from save_paths import dnd_saves_dir
from unique_ids import generate_named_object_id

ITEM_FILE_EXTENSION = ".dmtitem"
ITEM_FILE_FORMAT = "dmtitem.v2"
ITEM_FILE_PATTERNS = ("*.dmtitem",)
ITEM_ICON_ASSET_NAME = "assets/icon"

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


def ensure_item_payload_id(payload: dict, *, fallback_name: str = "item") -> dict:
    normalized = dict(payload or {})
    existing = str(normalized.get("item_id") or "").strip()
    if existing:
        normalized["item_id"] = existing
        return normalized
    item_name = str(normalized.get("title") or normalized.get("name") or fallback_name).strip()
    normalized["item_id"] = generate_named_object_id(item_name or fallback_name, "item")
    return normalized


def item_id_from_payload(payload: dict | None, *, fallback_path: Optional[Path] = None) -> str:
    if isinstance(payload, dict):
        existing = str(payload.get("item_id") or "").strip()
        if existing:
            return existing
    if fallback_path is None:
        return ""
    try:
        return str(fallback_path.resolve())
    except Exception:
        return str(fallback_path)


def _item_document_fingerprint(document: dict) -> str:
    try:
        payload = json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
    except Exception:
        payload = str(document)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_item_document(payload: dict, icon_source: Optional[str]) -> dict:
    normalized_payload = ensure_item_payload_id(payload)
    document: dict[str, object] = {
        "format": ITEM_FILE_FORMAT,
        "payload": normalized_payload,
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
    suffix = Path(icon_path.name).suffix.lower()
    asset_name = f"{ITEM_ICON_ASSET_NAME}{suffix or '.bin'}"
    document["icon_asset_name"] = asset_name
    document["assets"] = {
        asset_name: {
            "encoding": "base64",
            "data": base64.b64encode(raw).decode("ascii"),
        }
    }
    return document


def _decode_document_asset(document: dict, asset_name: str) -> Optional[bytes]:
    assets = document.get("assets")
    if not isinstance(assets, dict):
        return None
    asset_payload = assets.get(asset_name)
    if not isinstance(asset_payload, dict):
        return None
    encoded = str(asset_payload.get("data") or "").strip()
    if not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception:
        return None


def write_item_document(path: Path, document: dict) -> None:
    if not isinstance(document, dict):
        raise TypeError("document must be a dictionary")
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("document payload is missing")

    normalized_payload = ensure_item_payload_id(payload)
    info = {
        "format": ITEM_FILE_FORMAT,
        "payload": normalized_payload,
    }
    assets: dict[str, bytes] = {}
    icon_asset_name = str(document.get("icon_asset_name") or "").strip()
    if icon_asset_name:
        raw = _decode_document_asset(document, icon_asset_name)
        if raw:
            info["icon_asset_name"] = icon_asset_name
            assets[icon_asset_name] = raw
    write_dmt_package(path, info=info, assets=assets)


def load_item_document(path: Path) -> Optional[dict]:
    info = read_dmt_package_info(path)
    if isinstance(info, dict):
        file_format = str(info.get("format") or "").strip().lower()
        if file_format != ITEM_FILE_FORMAT:
            return None
        payload = info.get("payload")
        if not isinstance(payload, dict):
            return None
        document: dict[str, object] = {
            "format": ITEM_FILE_FORMAT,
            "payload": dict(payload),
        }
        icon_asset_name = str(info.get("icon_asset_name") or "").strip()
        if icon_asset_name:
            raw = read_dmt_package_asset(path, icon_asset_name)
            if raw:
                document["icon_asset_name"] = icon_asset_name
                document["assets"] = {
                    icon_asset_name: {
                        "encoding": "base64",
                        "data": base64.b64encode(raw).decode("ascii"),
                    }
                }
        return document
    return None


def _materialize_icon_bytes(raw: bytes, asset_name: str) -> Optional[str]:
    if not raw:
        return None
    suffix = Path(asset_name).suffix.lower()
    if not suffix or any(ch for ch in suffix if not (ch.isalnum() or ch == ".")):
        suffix = ".bin"
    digest = hashlib.sha256(raw).hexdigest()
    cache_dir = dnd_saves_dir() / "cache" / "item_icons"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        icon_path = cache_dir / f"{digest}{suffix}"
        if not icon_path.exists():
            icon_path.write_bytes(raw)
        return str(icon_path)
    except Exception:
        return None


def load_item_payload(path: Path) -> Optional[dict]:
    document = load_item_document(path)
    if not isinstance(document, dict):
        return None
    payload = document.get("payload")
    if not isinstance(payload, dict):
        return None
    resolved_payload = dict(payload)
    icon_asset_name = str(document.get("icon_asset_name") or "").strip()
    if icon_asset_name:
        raw = _decode_document_asset(document, icon_asset_name)
        if raw:
            icon_path = _materialize_icon_bytes(raw, icon_asset_name)
            if icon_path:
                resolved_payload["icon_path"] = icon_path
    return resolved_payload


def item_document_matches(a: dict | None, b: dict | None) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    return _item_document_fingerprint(a) == _item_document_fingerprint(b)
