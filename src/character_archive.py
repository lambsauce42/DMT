from __future__ import annotations

"""Canonical .dmtchar archive helpers for Player Sheets.

Archive layout:
- sheet.pdf
- inventory.json (backpack/equipment/notes/currency only)
- info.json
"""

import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARCHIVE_EXTENSION = ".dmtchar"
ARCHIVE_VERSION = 2
PDF_ENTRY_NAME = "sheet.pdf"
INVENTORY_ENTRY_NAME = "inventory.json"
INFO_ENTRY_NAME = "info.json"
META_ENTRY_NAME = INFO_ENTRY_NAME


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_inventory_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    src = payload if isinstance(payload, dict) else {}
    inventory_raw = src.get("inventory")
    inventory = []
    if isinstance(inventory_raw, list):
        inventory = [str(item).strip() for item in inventory_raw if str(item).strip()]

    notes = str(src.get("inventory_notes", ""))

    equipment_raw = src.get("equipment")
    equipment: dict[str, str | None] = {}
    if isinstance(equipment_raw, dict):
        for key, value in equipment_raw.items():
            if value is None:
                equipment[str(key)] = None
                continue
            cleaned = str(value).strip()
            equipment[str(key)] = cleaned or None

    def _coerce_currency(name: str) -> int:
        try:
            return max(0, int(src.get(name, 0)))
        except (TypeError, ValueError):
            return 0

    return {
        "inventory": inventory,
        "inventory_notes": notes,
        "equipment": equipment,
        "gold": _coerce_currency("gold"),
        "silver": _coerce_currency("silver"),
        "copper": _coerce_currency("copper"),
    }


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
