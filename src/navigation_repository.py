from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from navigation_storage import load_navigation_world_data, save_navigation_world_data
from save_paths import navigation_json_path, trash_json_path


WORLD_DATA: list[dict] = []
NAVIGATION_PATH = str(navigation_json_path())
TRASH_PATH = str(trash_json_path())


def _resolved_navigation_path(navigation_path: Optional[str] = None) -> Path:
    raw_path = navigation_path if navigation_path is not None else NAVIGATION_PATH
    return Path(raw_path).expanduser().resolve()


def _navigation_base_dir(navigation_path: Optional[str] = None) -> Path:
    return _resolved_navigation_path(navigation_path).parent


def _load_navigation_legacy_file(path: Path) -> list[dict] | None:
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[WARN] Failed to read legacy navigation file '{path}': {exc}", file=sys.stderr)
        return None
    if isinstance(payload, list):
        return payload
    print(f"[WARN] Ignoring non-list legacy navigation payload in '{path}'", file=sys.stderr)
    return None


def _write_navigation_legacy_file(path: Path, data: list) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data if isinstance(data, list) else [], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[WARN] Failed to write legacy navigation file '{path}': {exc}", file=sys.stderr)


def load_navigation_data(*, navigation_path: Optional[str] = None) -> list:
    base_dir = _navigation_base_dir(navigation_path)
    legacy_path = _resolved_navigation_path(navigation_path)
    packaged: list | None = None
    try:
        data = load_navigation_world_data(base_dir=base_dir)
        packaged = data if isinstance(data, list) else None
    except Exception as exc:
        print(f"[WARN] Failed to load package navigation data from '{base_dir}': {exc}", file=sys.stderr)
    if packaged:
        return packaged
    legacy = _load_navigation_legacy_file(legacy_path)
    if legacy is not None:
        if packaged == [] and legacy:
            print(
                f"[INFO] Loaded legacy navigation data from '{legacy_path}', migrating to package storage.",
                file=sys.stderr,
            )
            try:
                save_navigation_world_data(legacy, base_dir=base_dir)
            except Exception as exc:
                print(
                    f"[WARN] Failed to migrate legacy navigation data to '{base_dir}': {exc}",
                    file=sys.stderr,
                )
        return legacy
    return packaged if isinstance(packaged, list) else WORLD_DATA


def save_navigation_data(data: list, *, navigation_path: Optional[str] = None) -> None:
    base_dir = _navigation_base_dir(navigation_path)
    legacy_path = _resolved_navigation_path(navigation_path)
    try:
        save_navigation_world_data(data if isinstance(data, list) else [], base_dir=base_dir)
    except Exception as exc:
        print(f"[WARN] Failed to save package navigation data in '{base_dir}': {exc}", file=sys.stderr)
    if legacy_path.exists() and legacy_path.is_file():
        _write_navigation_legacy_file(legacy_path, data)


def load_trash(*, path: Optional[str] = None) -> list[dict]:
    trash_path = path if path is not None else TRASH_PATH
    if not os.path.exists(trash_path):
        return []
    try:
        with open(trash_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return []
    if isinstance(data, list):
        return data
    return []


def save_trash(entries: list[dict], *, path: Optional[str] = None) -> None:
    trash_path = path if path is not None else TRASH_PATH
    os.makedirs(os.path.dirname(trash_path), exist_ok=True)
    with open(trash_path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)


def move_to_trash(
    entry_type: str,
    payload: dict,
    parent: Optional[dict] = None,
    *,
    path: Optional[str] = None,
) -> dict:
    if not isinstance(payload, dict):
        return {}
    entries = load_trash(path=path)
    trash_entry = {
        "type": entry_type,
        "name": payload.get("name"),
        "icon": payload.get("icon"),
        "payload": copy.deepcopy(payload),
        "parent": parent or {},
        "deleted_at": datetime.now().isoformat(timespec="seconds"),
    }
    entries.append(trash_entry)
    save_trash(entries, path=path)
    return trash_entry


def clean_navigation_id(value: object) -> str:
    return str(value or "").strip()


def normalize_group_entry(group: object, *, default_icon: str) -> dict:
    if isinstance(group, dict):
        name = str(group.get("name", "")).strip()
        icon = group.get("icon") or default_icon
        group_id = clean_navigation_id(group.get("id")) or None
        normalized = {"name": name, "icon": icon}
        if group_id:
            normalized["id"] = group_id
        return normalized
    name = str(group).strip()
    return {"name": name, "icon": default_icon}


def normalize_campaign_entry(
    campaign: dict,
    *,
    default_icon: str,
    default_group_icon: str,
) -> dict:
    name = str(campaign.get("name", "")).strip()
    icon = campaign.get("icon") or default_icon
    campaign_id = clean_navigation_id(campaign.get("id")) or None
    groups = []
    for group in campaign.get("groups", []):
        normalized = normalize_group_entry(group, default_icon=default_group_icon)
        if normalized["name"]:
            groups.append(normalized)
    normalized_campaign = {"name": name, "icon": icon, "groups": groups}
    if campaign_id:
        normalized_campaign["id"] = campaign_id
    return normalized_campaign


def normalize_world_entry(
    world: dict,
    *,
    default_icon: str,
    default_campaign_icon: str,
    default_group_icon: str,
) -> dict:
    name = str(world.get("name", "")).strip()
    icon = world.get("icon") or default_icon
    world_id = clean_navigation_id(world.get("id")) or None
    campaigns = []
    for campaign in world.get("campaigns", []):
        normalized = normalize_campaign_entry(
            campaign,
            default_icon=default_campaign_icon,
            default_group_icon=default_group_icon,
        )
        if normalized["name"]:
            campaigns.append(normalized)
    normalized_world = {"name": name, "icon": icon, "campaigns": campaigns}
    if world_id:
        normalized_world["id"] = world_id
    return normalized_world


def campaign_trash_entry_matches_world(
    entry: dict,
    world: dict,
    *,
    allow_renamed_legacy: bool,
) -> bool:
    parent = entry.get("parent", {})
    if not isinstance(parent, dict):
        parent = {}
    payload = entry.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    world_id = clean_navigation_id(world.get("id"))
    parent_world_id = clean_navigation_id(parent.get("world_id"))
    payload_world_id = clean_navigation_id(payload.get("world_id"))
    world_name = str(world.get("name") or "").strip()
    parent_world_name = str(parent.get("world") or "").strip()

    if world_id:
        for candidate_id in (parent_world_id, payload_world_id):
            if candidate_id:
                return candidate_id == world_id
        if not allow_renamed_legacy:
            return not parent_world_name or parent_world_name == world_name
        return True

    if parent_world_id or payload_world_id:
        return False
    if not parent_world_name or parent_world_name == world_name:
        return True
    return allow_renamed_legacy


def group_trash_entry_matches_campaign(
    entry: dict,
    world: dict,
    campaign: dict,
    *,
    allow_renamed_legacy: bool,
) -> bool:
    parent = entry.get("parent", {})
    if not isinstance(parent, dict):
        parent = {}
    payload = entry.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}

    world_id = clean_navigation_id(world.get("id"))
    campaign_id = clean_navigation_id(campaign.get("id"))
    parent_world_id = clean_navigation_id(parent.get("world_id"))
    parent_campaign_id = clean_navigation_id(parent.get("campaign_id"))
    payload_world_id = clean_navigation_id(payload.get("world_id"))
    payload_campaign_id = clean_navigation_id(payload.get("campaign_id"))

    if world_id:
        for candidate_world_id in (parent_world_id, payload_world_id):
            if candidate_world_id and candidate_world_id != world_id:
                return False
    elif parent_world_id or payload_world_id:
        return False

    if campaign_id:
        for candidate_campaign_id in (parent_campaign_id, payload_campaign_id):
            if candidate_campaign_id:
                return candidate_campaign_id == campaign_id
        if allow_renamed_legacy:
            return True
        campaign_name = str(campaign.get("name") or "").strip()
        parent_campaign_name = str(parent.get("campaign") or "").strip()
        return not parent_campaign_name or parent_campaign_name == campaign_name

    if parent_campaign_id or payload_campaign_id:
        return False
    campaign_name = str(campaign.get("name") or "").strip()
    parent_campaign_name = str(parent.get("campaign") or "").strip()
    if not parent_campaign_name or parent_campaign_name == campaign_name:
        return True
    return allow_renamed_legacy
