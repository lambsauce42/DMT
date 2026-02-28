from __future__ import annotations

import json
from pathlib import Path

from save_paths import dnd_saves_dir

APP_SETTINGS_FILE_NAME = "app_settings.json"
DEFAULT_APP_SETTINGS: dict[str, object] = {
    "session_autosave_enabled": False,
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


def is_session_autosave_enabled() -> bool:
    return bool(load_app_settings().get("session_autosave_enabled", False))
