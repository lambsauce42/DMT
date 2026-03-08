from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
import sys
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


@dataclass(frozen=True)
class IndexedItemRecord:
    path: Path
    item_id: str
    normalized_name: str
    payload: dict
    document: dict
    fingerprint: str


@dataclass
class ItemLibraryIndex:
    root: Path
    entries: list[IndexedItemRecord]
    by_item_id: dict[str, IndexedItemRecord]
    by_normalized_name: dict[str, list[IndexedItemRecord]]
    by_fingerprint: dict[str, list[IndexedItemRecord]]


_ITEM_LIBRARY_INDEX_CACHE: dict[str, ItemLibraryIndex] = {}


def normalize_item_name(raw: object) -> str:
    text = str(raw or "").strip().lower()
    if not text:
        return ""
    return " ".join(text.split())


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


def ensure_item_payload_id(
    payload: dict,
    *,
    fallback_name: str = "item",
    preserve_existing: bool = True,
) -> dict:
    normalized = dict(payload or {})
    item_name = str(normalized.get("title") or normalized.get("name") or fallback_name).strip()
    normalized_name = normalize_item_name(
        normalized.get("normalized_item_name") or item_name or fallback_name
    )
    existing = str(normalized.get("item_id") or "").strip()
    if preserve_existing and existing:
        normalized["item_id"] = existing
    else:
        normalized["item_id"] = generate_named_object_id(
            normalized_name or item_name or fallback_name,
            "item",
        )
    normalized["normalized_item_name"] = normalized_name
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


def normalized_item_name_from_payload(
    payload: dict | None,
    *,
    fallback_path: Optional[Path] = None,
) -> str:
    if isinstance(payload, dict):
        existing = normalize_item_name(payload.get("normalized_item_name"))
        if existing:
            return existing
        derived = normalize_item_name(payload.get("title") or payload.get("name"))
        if derived:
            return derived
    if fallback_path is None:
        return ""
    return normalize_item_name(fallback_path.stem)


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


def item_document_fingerprint(document: dict | None) -> str:
    if not isinstance(document, dict):
        return ""
    return _item_document_fingerprint(document)


def _resolved_payload_from_document(document: dict) -> dict | None:
    if not isinstance(document, dict):
        return None
    payload = document.get("payload")
    if not isinstance(payload, dict):
        return None
    resolved_payload = ensure_item_payload_id(payload, preserve_existing=True)
    icon_asset_name = str(document.get("icon_asset_name") or "").strip()
    if icon_asset_name:
        raw = _decode_document_asset(document, icon_asset_name)
        if raw:
            icon_path = _materialize_icon_bytes(raw, icon_asset_name)
            if icon_path:
                resolved_payload["icon_path"] = icon_path
    return resolved_payload


def _item_library_cache_key(root: Path) -> str:
    try:
        return str(root.resolve()).lower()
    except Exception:
        return str(root).lower()


def invalidate_item_library_index(*, root: Path | None = None, path: Path | None = None) -> None:
    if root is not None:
        _ITEM_LIBRARY_INDEX_CACHE.pop(_item_library_cache_key(Path(root).expanduser()), None)
    if path is not None:
        candidate = Path(path).expanduser()
        try:
            candidate_resolved = candidate.resolve()
        except Exception:
            candidate_resolved = candidate
        for cache_key, index in list(_ITEM_LIBRARY_INDEX_CACHE.items()):
            try:
                candidate_resolved.relative_to(index.root)
            except Exception:
                continue
            _ITEM_LIBRARY_INDEX_CACHE.pop(cache_key, None)


def build_item_library_index(root: Path, *, refresh: bool = False) -> ItemLibraryIndex:
    resolved_root = Path(root).expanduser()
    cache_key = _item_library_cache_key(resolved_root)
    if not refresh:
        cached = _ITEM_LIBRARY_INDEX_CACHE.get(cache_key)
        if isinstance(cached, ItemLibraryIndex):
            return cached

    entries: list[IndexedItemRecord] = []
    by_item_id: dict[str, IndexedItemRecord] = {}
    by_normalized_name: dict[str, list[IndexedItemRecord]] = {}
    by_fingerprint: dict[str, list[IndexedItemRecord]] = {}
    if resolved_root.exists():
        for path in list_item_file_paths(resolved_root):
            document = load_item_document(path)
            if not isinstance(document, dict):
                continue
            payload = _resolved_payload_from_document(document)
            if not isinstance(payload, dict):
                continue
            item_id = item_id_from_payload(payload, fallback_path=path)
            normalized_name = normalized_item_name_from_payload(payload, fallback_path=path)
            fingerprint = _item_document_fingerprint(document)
            record = IndexedItemRecord(
                path=path,
                item_id=item_id,
                normalized_name=normalized_name,
                payload=payload,
                document=document,
                fingerprint=fingerprint,
            )
            entries.append(record)
            if item_id and item_id not in by_item_id:
                by_item_id[item_id] = record
            if normalized_name:
                by_normalized_name.setdefault(normalized_name, []).append(record)
            if fingerprint:
                by_fingerprint.setdefault(fingerprint, []).append(record)
    index = ItemLibraryIndex(
        root=resolved_root,
        entries=entries,
        by_item_id=by_item_id,
        by_normalized_name=by_normalized_name,
        by_fingerprint=by_fingerprint,
    )
    _ITEM_LIBRARY_INDEX_CACHE[cache_key] = index
    return index


def indexed_item_records(root: Path, *, refresh: bool = False) -> list[IndexedItemRecord]:
    return list(build_item_library_index(root, refresh=refresh).entries)


def indexed_item_record_by_id(
    root: Path,
    item_id: str,
    *,
    refresh: bool = False,
) -> IndexedItemRecord | None:
    clean_item_id = str(item_id or "").strip()
    if not clean_item_id:
        return None
    index = build_item_library_index(root, refresh=refresh)
    record = index.by_item_id.get(clean_item_id)
    if record is not None and record.path.exists():
        return record
    if record is not None:
        invalidate_item_library_index(root=root)
        index = build_item_library_index(root, refresh=True)
        record = index.by_item_id.get(clean_item_id)
    return record if record is not None and record.path.exists() else None


def indexed_item_records_by_normalized_name(
    root: Path,
    normalized_name: str,
    *,
    refresh: bool = False,
) -> list[IndexedItemRecord]:
    clean_name = normalize_item_name(normalized_name)
    if not clean_name:
        return []
    index = build_item_library_index(root, refresh=refresh)
    records = [
        record
        for record in index.by_normalized_name.get(clean_name, [])
        if record.path.exists()
    ]
    if records or not index.by_normalized_name.get(clean_name):
        return records
    invalidate_item_library_index(root=root)
    index = build_item_library_index(root, refresh=True)
    return [
        record
        for record in index.by_normalized_name.get(clean_name, [])
        if record.path.exists()
    ]


def indexed_item_records_by_document(
    root: Path,
    document: dict | None,
    *,
    refresh: bool = False,
) -> list[IndexedItemRecord]:
    fingerprint = item_document_fingerprint(document)
    if not fingerprint:
        return []
    index = build_item_library_index(root, refresh=refresh)
    records = [
        record
        for record in index.by_fingerprint.get(fingerprint, [])
        if record.path.exists()
    ]
    if records or not index.by_fingerprint.get(fingerprint):
        return records
    invalidate_item_library_index(root=root)
    index = build_item_library_index(root, refresh=True)
    return [
        record
        for record in index.by_fingerprint.get(fingerprint, [])
        if record.path.exists()
    ]


def build_item_document(payload: dict, icon_source: Optional[str]) -> dict:
    normalized_payload = ensure_item_payload_id(payload, preserve_existing=True)
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

    normalized_payload = ensure_item_payload_id(payload, preserve_existing=True)
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
    invalidate_item_library_index(path=path)


def load_item_document(path: Path) -> Optional[dict]:
    info = read_dmt_package_info(path)
    if isinstance(info, dict):
        file_format = str(info.get("format") or "").strip().lower()
        if file_format != ITEM_FILE_FORMAT:
            info = None
        else:
            payload = info.get("payload")
            if not isinstance(payload, dict):
                return None
            normalized_payload = ensure_item_payload_id(payload, preserve_existing=True)
            document: dict[str, object] = {
                "format": ITEM_FILE_FORMAT,
                "payload": normalized_payload,
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
    try:
        raw_info = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw_info, dict):
        return None
    file_format = str(raw_info.get("format") or "").strip().lower()
    if file_format != ITEM_FILE_FORMAT:
        return None
    payload = raw_info.get("payload")
    if not isinstance(payload, dict):
        return None
    print(
        f"[WARN] Loading legacy plain-JSON item file '{path}'. Re-save to normalize it.",
        file=sys.stderr,
    )
    normalized_payload = ensure_item_payload_id(payload, preserve_existing=True)
    document = {
        "format": ITEM_FILE_FORMAT,
        "payload": normalized_payload,
    }
    icon_asset_name = str(raw_info.get("icon_asset_name") or "").strip()
    assets = raw_info.get("assets")
    if icon_asset_name and isinstance(assets, dict):
        document["icon_asset_name"] = icon_asset_name
        document["assets"] = assets
    return document


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
    return _resolved_payload_from_document(document)


def item_document_matches(a: dict | None, b: dict | None) -> bool:
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    return _item_document_fingerprint(a) == _item_document_fingerprint(b)
