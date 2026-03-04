from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from save_paths import dnd_saves_dir, selected_debug_save_profile

APP_SETTINGS_FILE_NAME = "app_settings.json"
LEGACY_DUNGEON_PROFILE_FILE_NAME = "dungeon_profile.json"
LOCAL_PLAYER_ID_KEY = "local_player_id"
DEFAULT_APP_SETTINGS: dict[str, object] = {
    "session_autosave_enabled": False,
    LOCAL_PLAYER_ID_KEY: "",
}


def app_settings_path() -> Path:
    return dnd_saves_dir() / "settings" / APP_SETTINGS_FILE_NAME


def load_app_settings() -> dict[str, object]:
    settings = dict(DEFAULT_APP_SETTINGS)
    path = app_settings_path()
    if not path.exists():
        return settings
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to load app settings from {path}: {exc}")
        return settings
    if not isinstance(payload, dict):
        print(f"Failed to load app settings from {path}: payload was not an object")
        return settings
    settings.update(payload)
    return settings


def save_app_settings(values: dict[str, object]) -> dict[str, object]:
    settings = load_app_settings()
    settings.update(dict(values or {}))
    path = app_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return settings


def _generate_local_player_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"player_{stamp}_{uuid.uuid4().hex}{uuid.uuid4().hex}"


def _generate_debug_local_player_id(profile: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    clean_profile = str(profile or "").strip().lower() or "debug"
    return f"{clean_profile}_player_{stamp}_{uuid.uuid4().hex}{uuid.uuid4().hex}"


def _legacy_dungeon_profile_player_id() -> str:
    path = dnd_saves_dir() / "settings" / LEGACY_DUNGEON_PROFILE_FILE_NAME
    if not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Failed to read legacy dungeon profile from {path}: {exc}")
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("player_id") or "").strip()


def get_or_create_local_player_id() -> str:
    settings = load_app_settings()
    active_debug_profile = str(selected_debug_save_profile() or "").strip()
    existing = str(settings.get(LOCAL_PLAYER_ID_KEY) or "").strip()
    if active_debug_profile:
        expected_prefix = f"{active_debug_profile.lower()}_player_"
        if existing.startswith(expected_prefix):
            return existing
        player_id = _generate_debug_local_player_id(active_debug_profile)
        save_app_settings({LOCAL_PLAYER_ID_KEY: player_id})
        return player_id
    if existing:
        return existing
    seeded = _legacy_dungeon_profile_player_id()
    player_id = seeded or _generate_local_player_id()
    save_app_settings({LOCAL_PLAYER_ID_KEY: player_id})
    return player_id


def is_session_autosave_enabled() -> bool:
    return bool(load_app_settings().get("session_autosave_enabled", False))
