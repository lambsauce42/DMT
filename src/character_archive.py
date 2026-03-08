from __future__ import annotations

"""Canonical .dmtchar archive helpers for Player Sheets.

Archive layout:
- sheet.pdf
- inventory.json (linked inventory state plus referenced item documents)
- info.json
"""

import io
import json
import hashlib
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from item_file_format import (
    ITEM_FILE_FORMAT,
    ensure_item_payload_id,
    item_id_from_payload,
    normalize_item_name,
)


ARCHIVE_EXTENSION = ".dmtchar"
ARCHIVE_VERSION = 2
PDF_ENTRY_NAME = "sheet.pdf"
INVENTORY_ENTRY_NAME = "inventory.json"
INFO_ENTRY_NAME = "info.json"
META_ENTRY_NAME = INFO_ENTRY_NAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _coerce_quantity(raw: object, *, default: int = 1) -> int:
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return max(1, int(default))


def _coerce_currency(raw: object) -> int:
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _normalize_item_entry(
    raw: object,
    *,
    default_quantity: int = 1,
) -> dict[str, Any] | None:
    if raw is None:
        return None
    if isinstance(raw, dict):
        item_id = str(raw.get("item_id") or "").strip()
        normalized_name = normalize_item_name(
            raw.get("normalized_item_name") or raw.get("title") or raw.get("name") or item_id
        )
        quantity = _coerce_quantity(raw.get("quantity", default_quantity), default=default_quantity)
    else:
        item_id = str(raw or "").strip()
        normalized_name = normalize_item_name(item_id)
        quantity = _coerce_quantity(default_quantity, default=default_quantity)
    if not item_id:
        return None
    return {
        "item_id": item_id,
        "normalized_item_name": normalized_name or normalize_item_name(item_id),
        "quantity": quantity,
    }


def _normalize_item_document(raw: object) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    if str(raw.get("format") or "").strip().lower() != ITEM_FILE_FORMAT:
        return None
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return None
    normalized_payload = ensure_item_payload_id(payload, preserve_existing=True)
    normalized_document: dict[str, Any] = {
        "format": ITEM_FILE_FORMAT,
        "payload": normalized_payload,
    }
    icon_asset_name = str(raw.get("icon_asset_name") or "").strip()
    assets = raw.get("assets")
    if (
        icon_asset_name
        and isinstance(assets, dict)
        and isinstance(assets.get(icon_asset_name), dict)
    ):
        asset_payload = dict(assets.get(icon_asset_name) or {})
        normalized_document["icon_asset_name"] = icon_asset_name
        normalized_document["assets"] = {icon_asset_name: asset_payload}
    return normalized_document


def normalize_inventory_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    src = payload if isinstance(payload, dict) else {}
    inventory_raw = src.get("inventory")
    inventory: list[dict[str, Any]] = []
    if isinstance(inventory_raw, list):
        merged_inventory: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for item in inventory_raw:
            normalized_item = _normalize_item_entry(item, default_quantity=1)
            if normalized_item is None:
                continue
            key = str(normalized_item.get("item_id") or "").strip()
            if not key:
                key = str(normalized_item.get("normalized_item_name") or "").strip()
            if not key:
                continue
            existing = merged_inventory.get(key)
            if existing is None:
                merged_inventory[key] = dict(normalized_item)
                order.append(key)
                continue
            existing["quantity"] = int(existing.get("quantity", 1)) + int(
                normalized_item.get("quantity", 1)
            )
            incoming_item_id = str(normalized_item.get("item_id") or "").strip()
            if incoming_item_id:
                existing["item_id"] = incoming_item_id
        inventory = [merged_inventory[key] for key in order]

    notes = str(src.get("inventory_notes", ""))

    equipment_raw = src.get("equipment")
    equipment: dict[str, dict[str, Any] | None] = {}
    if isinstance(equipment_raw, dict):
        for key, value in equipment_raw.items():
            slot_id = str(key or "").strip()
            if not slot_id:
                continue
            equipment[slot_id] = _normalize_item_entry(value, default_quantity=1)

    referenced_item_ids: set[str] = set()
    for entry in inventory:
        item_id = str(entry.get("item_id") or "").strip()
        if item_id:
            referenced_item_ids.add(item_id)
    for value in equipment.values():
        if not isinstance(value, dict):
            continue
        item_id = str(value.get("item_id") or "").strip()
        if item_id:
            referenced_item_ids.add(item_id)

    item_documents: dict[str, dict[str, Any]] = {}
    raw_item_documents = src.get("item_documents")
    raw_documents_iterable: list[object] = []
    if isinstance(raw_item_documents, dict):
        raw_documents_iterable = list(raw_item_documents.values())
    elif isinstance(raw_item_documents, list):
        raw_documents_iterable = list(raw_item_documents)
    for raw_document in raw_documents_iterable:
        normalized_document = _normalize_item_document(raw_document)
        if normalized_document is None:
            continue
        payload_item_id = item_id_from_payload(normalized_document.get("payload"))
        if not payload_item_id or payload_item_id not in referenced_item_ids:
            continue
        item_documents[payload_item_id] = normalized_document

    return {
        "inventory": inventory,
        "inventory_notes": notes,
        "equipment": equipment,
        "gold": _coerce_currency(src.get("gold", 0)),
        "silver": _coerce_currency(src.get("silver", 0)),
        "copper": _coerce_currency(src.get("copper", 0)),
        "item_documents": item_documents,
    }


def inventory_payload_content_hash(payload: dict[str, Any] | None) -> str:
    normalized = normalize_inventory_payload(payload)
    serialized = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def character_archive_pdf_hash(archive_bytes: bytes | None) -> str | None:
    if not archive_bytes:
        return ""
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            names = set(zf.namelist())
            if not {PDF_ENTRY_NAME, INVENTORY_ENTRY_NAME, INFO_ENTRY_NAME}.issubset(names):
                return None
            raw_pdf = zf.read(PDF_ENTRY_NAME)
            raw_inventory = json.loads(zf.read(INVENTORY_ENTRY_NAME).decode("utf-8"))
            raw_meta = json.loads(zf.read(INFO_ENTRY_NAME).decode("utf-8"))
    except Exception:
        return None
    if not raw_pdf or not isinstance(raw_inventory, dict) or not isinstance(raw_meta, dict):
        return None
    normalize_inventory_payload(raw_inventory)
    return hashlib.sha256(raw_pdf).hexdigest()


def validate_character_archive_bytes(archive_bytes: bytes | None) -> bool:
    return character_archive_pdf_hash(archive_bytes) is not None


def character_sync_content_hash(
    character_id: str,
    inventory_payload: dict[str, Any] | None,
    archive_bytes: bytes | None = None,
) -> str:
    archive_hash = character_archive_pdf_hash(archive_bytes)
    if archive_hash is None:
        raise ValueError("invalid character archive")
    payload = {
        "character_id": str(character_id or "").strip(),
        "inventory": normalize_inventory_payload(inventory_payload),
        "archive_hash": archive_hash or "",
    }
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def write_character_archive(
    archive_path: Path,
    *,
    pdf_path: Path,
    inventory_payload: dict[str, Any],
    meta: dict[str, Any] | None = None,
) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing sheet PDF: {pdf_path}")

    archive_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_inventory = normalize_inventory_payload(inventory_payload)
    meta_payload = dict(meta or {})
    meta_payload["archive_version"] = ARCHIVE_VERSION
    meta_payload.setdefault("updated_at", _utc_now())

    pdf_bytes = pdf_path.read_bytes()
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(PDF_ENTRY_NAME, pdf_bytes)
        zf.writestr(
            INVENTORY_ENTRY_NAME,
            json.dumps(normalized_inventory, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            INFO_ENTRY_NAME,
            json.dumps(meta_payload, ensure_ascii=False, indent=2),
        )


def extract_character_pdf(archive_path: Path, target_pdf_path: Path) -> bool:
    if not archive_path.exists():
        return False
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            if PDF_ENTRY_NAME not in zf.namelist():
                return False
            raw = zf.read(PDF_ENTRY_NAME)
    except Exception:
        return False
    if not raw:
        return False
    target_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    target_pdf_path.write_bytes(raw)
    return True


def read_character_inventory(archive_path: Path) -> dict[str, Any]:
    if not archive_path.exists():
        return normalize_inventory_payload({})
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            if INVENTORY_ENTRY_NAME not in zf.namelist():
                return normalize_inventory_payload({})
            payload = json.loads(zf.read(INVENTORY_ENTRY_NAME).decode("utf-8"))
    except Exception:
        return normalize_inventory_payload({})
    if not isinstance(payload, dict):
        return normalize_inventory_payload({})
    return normalize_inventory_payload(payload)


def read_character_inventory_bytes(archive_bytes: bytes | None) -> dict[str, Any]:
    if not archive_bytes:
        return normalize_inventory_payload({})
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            if INVENTORY_ENTRY_NAME not in zf.namelist():
                return normalize_inventory_payload({})
            payload = json.loads(zf.read(INVENTORY_ENTRY_NAME).decode("utf-8"))
    except Exception:
        return normalize_inventory_payload({})
    if not isinstance(payload, dict):
        return normalize_inventory_payload({})
    return normalize_inventory_payload(payload)


def rewrite_character_archive_bytes(
    archive_bytes: bytes | None,
    inventory_payload: dict[str, Any] | None,
    *,
    meta_updates: dict[str, Any] | None = None,
) -> bytes | None:
    if not archive_bytes:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
            names = set(zf.namelist())
            if not {PDF_ENTRY_NAME, INVENTORY_ENTRY_NAME, INFO_ENTRY_NAME}.issubset(names):
                return None
            raw_pdf = zf.read(PDF_ENTRY_NAME)
            raw_meta = json.loads(zf.read(INFO_ENTRY_NAME).decode("utf-8"))
    except Exception:
        return None
    if not raw_pdf or not isinstance(raw_meta, dict):
        return None

    normalized_inventory = normalize_inventory_payload(inventory_payload)
    meta_payload = dict(raw_meta)
    meta_payload["archive_version"] = ARCHIVE_VERSION
    meta_payload["updated_at"] = _utc_now()
    if isinstance(meta_updates, dict):
        meta_payload.update(meta_updates)

    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(PDF_ENTRY_NAME, raw_pdf)
            zf.writestr(
                INVENTORY_ENTRY_NAME,
                json.dumps(normalized_inventory, ensure_ascii=False, indent=2),
            )
            zf.writestr(
                INFO_ENTRY_NAME,
                json.dumps(meta_payload, ensure_ascii=False, indent=2),
            )
    except Exception:
        return None
    return buffer.getvalue()


def read_character_meta(archive_path: Path) -> dict[str, Any]:
    if not archive_path.exists():
        return {}
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            if INFO_ENTRY_NAME not in zf.namelist():
                return {}
            payload = json.loads(zf.read(INFO_ENTRY_NAME).decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
