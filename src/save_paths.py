from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

DEFAULT_SAVE_DIR_PARTS = ("Documents", "DMT")
DEFAULT_SAVE_DIR_FALLBACK_PARTS = ("documents", "DMT")
LEGACY_NESTED_DND_DIR_NAME = "DMT_saves"
DEBUG_SAVE_PROFILE_ENV = "DMT_SAVE_PROFILE"
DEBUG_SAVE_PROFILES = ("DEBUG1", "DEBUG2")
_WARNED_INVALID_DEBUG_PROFILES: set[str] = set()


def _in_test_env() -> bool:
    if os.environ.get("DMT_TEST_MODE") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def _default_user_dnd_save_dir() -> Path:
    home = os.path.expanduser("~")
    primary = Path(home).joinpath(*DEFAULT_SAVE_DIR_PARTS)
    fallback = Path(home).joinpath(*DEFAULT_SAVE_DIR_FALLBACK_PARTS)

    if os.path.exists(os.path.join(home, DEFAULT_SAVE_DIR_PARTS[0])):
        return primary
    return fallback


def _selected_debug_save_profile() -> str:
    raw = str(os.environ.get(DEBUG_SAVE_PROFILE_ENV) or "").strip().upper()
    if not raw:
        return ""
    if raw in DEBUG_SAVE_PROFILES:
        return raw
    if raw not in _WARNED_INVALID_DEBUG_PROFILES:
        print(
            f"Ignoring invalid {DEBUG_SAVE_PROFILE_ENV}={raw!r}. "
            f"Expected one of: {', '.join(DEBUG_SAVE_PROFILES)}."
        )
        _WARNED_INVALID_DEBUG_PROFILES.add(raw)
    return ""


def selected_debug_save_profile() -> str:
    return _selected_debug_save_profile()


def _debug_save_dir_for_profile(profile: str) -> Path:
    base_dir = _default_user_dnd_save_dir()
    return base_dir.parent / f"{profile}_{base_dir.name}"


def default_dnd_save_dir() -> str:
    if _in_test_env():
        override = str(os.environ.get("DMT_TEST_SAVE_DIR") or "").strip()
        if override:
            return str(Path(override))
        return str(Path.cwd() / "tests" / "test_saves" / "DMT")

    profile = _selected_debug_save_profile()
    if profile:
        debug_dir = _debug_save_dir_for_profile(profile)
        try:
            debug_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            print(f"Failed to create DMT debug save directory {debug_dir}: {exc}")
        return str(debug_dir)

    return str(_default_user_dnd_save_dir())


def _legacy_nested_dnd_dir(base_dir: Path) -> Path:
    return base_dir / LEGACY_NESTED_DND_DIR_NAME


def _root_dnd_data_seems_empty(base_dir: Path) -> bool:
    markers = (
        "items",
        "navigation_objects",
        "trash.json",
        "dungeon_collections",
        "encounters",
        "online_sessions",
        "cache",
    )
    return not any((base_dir / marker).exists() for marker in markers)


def _migrate_legacy_nested_dnd_data(base_dir: Path) -> None:
    if _in_test_env():
        return
    legacy_dir = _legacy_nested_dnd_dir(base_dir)
    if not legacy_dir.exists() or not legacy_dir.is_dir():
        return
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        for child in list(legacy_dir.iterdir()):
            target = base_dir / child.name
            if child.is_dir():
                if target.exists() and target.is_dir():
                    shutil.copytree(child, target, dirs_exist_ok=True)
                    shutil.rmtree(child, ignore_errors=True)
                elif not target.exists():
                    shutil.move(str(child), str(target))
            else:
                if target.exists():
                    try:
                        child.unlink()
                    except Exception:
                        pass
                else:
                    shutil.move(str(child), str(target))
        if legacy_dir.exists() and not any(legacy_dir.iterdir()):
            legacy_dir.rmdir()
    except Exception:
        return


def dnd_saves_dir() -> Path:
    base_dir = Path(default_dnd_save_dir())
    _migrate_legacy_nested_dnd_data(base_dir)
    legacy_dir = _legacy_nested_dnd_dir(base_dir)
    if _in_test_env() and legacy_dir.exists() and _root_dnd_data_seems_empty(base_dir):
        return legacy_dir
    return base_dir


def trash_json_path() -> str:
    return str(dnd_saves_dir() / "trash.json")


def navigation_json_path() -> Path:
    return dnd_saves_dir() / "navigation.json"


def items_dir() -> Path:
    return dnd_saves_dir() / "items"


def dungeon_collections_dir() -> Path:
    return dnd_saves_dir() / "dungeon_collections"


def online_sessions_dir() -> Path:
    return dnd_saves_dir() / "online_sessions"


def session_transcripts_dir() -> Path:
    return dnd_saves_dir() / "session_transcripts"


def session_transcript_dir(session_id: str) -> Path:
    return session_transcripts_dir() / _safe_component(str(session_id or ""), "session")


def online_session_dir(session_id: str) -> Path:
    safe = "".join(ch for ch in str(session_id).strip() if ch not in '<>:"/\\|?*').strip(" .")
    if not safe:
        safe = "session"
    return online_sessions_dir() / safe


def online_icon_cache_dir(session_id: str) -> Path:
    return online_session_dir(session_id) / "cache" / "icons"


def online_image_cache_dir(session_id: str) -> Path:
    return online_session_dir(session_id) / "cache" / "images"


def online_media_cache_dir(session_id: str) -> Path:
    return online_session_dir(session_id) / "cache" / "media"


def media_settings_path() -> Path:
    return dnd_saves_dir() / "settings" / "media_profile.json"


def online_loot_item_cache_root() -> Path:
    return dnd_saves_dir() / "cache" / "online_loot_items"


def runtime_cache_root() -> Path:
    return dnd_saves_dir() / "cache"


def debug_logs_dir() -> Path:
    return dnd_saves_dir() / "debug"


def character_cache_dir() -> Path:
    return runtime_cache_root() / "characters"


def character_sheet_index_cache_path() -> Path:
    return character_cache_dir() / "character_sheets.json"


def character_linked_item_cache_root() -> Path:
    return character_cache_dir() / "linked_items"


def item_icon_cache_dir() -> Path:
    return runtime_cache_root() / "item_icons"


def session_attachment_cache_root() -> Path:
    return runtime_cache_root() / "session_attachments"


def online_loot_item_cache_dir(session_id: str) -> Path:
    session_key = _safe_component(str(session_id or ""), "local")
    return online_loot_item_cache_root() / session_key


def _safe_component(value: str, fallback: str) -> str:
    invalid = set('<>:"/\\|?*')
    cleaned = "".join(ch for ch in str(value).strip() if ch not in invalid).strip(" .")
    return cleaned or fallback


def collection_icon_assets_dir(collection_path: Path) -> Path:
    path = Path(collection_path)
    stem = _safe_component(path.stem, "collection")
    return path.parent / f"{stem}_assets" / "icons"


def collection_image_assets_dir(collection_path: Path) -> Path:
    path = Path(collection_path)
    stem = _safe_component(path.stem, "collection")
    return path.parent / f"{stem}_assets" / "images"


def working_collection_icon_assets_dir(collection_name: str) -> Path:
    safe_name = _safe_component(collection_name, "collection")
    return dungeon_collections_dir() / "_working_assets" / safe_name / "icons"


def working_collection_image_assets_dir(collection_name: str) -> Path:
    safe_name = _safe_component(collection_name, "collection")
    return dungeon_collections_dir() / "_working_assets" / safe_name / "images"


def clear_online_icon_cache(session_id: str) -> None:
    session_root = online_session_dir(session_id)
    cache_root = session_root / "cache"
    try:
        if cache_root.exists():
            shutil.rmtree(cache_root, ignore_errors=True)
        if session_root.exists() and not any(session_root.iterdir()):
            session_root.rmdir()
    except Exception:
        return


def clear_online_loot_item_cache(session_id: str) -> None:
    session_root = online_loot_item_cache_dir(session_id)
    parent = online_loot_item_cache_root()
    try:
        if session_root.exists():
            shutil.rmtree(session_root, ignore_errors=True)
        if parent.exists() and not any(parent.iterdir()):
            parent.rmdir()
    except Exception:
        return


def clear_online_runtime_cache(session_id: str) -> None:
    clear_online_icon_cache(session_id)
    clear_online_loot_item_cache(session_id)


def clear_all_online_icon_caches() -> None:
    base = online_sessions_dir()
    if not base.exists():
        return
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            cache_root = child / "cache"
            if cache_root.exists():
                shutil.rmtree(cache_root, ignore_errors=True)
            if child.exists() and not any(child.iterdir()):
                child.rmdir()
    except Exception:
        return


def clear_all_online_loot_item_caches() -> None:
    base = online_loot_item_cache_root()
    if not base.exists():
        return
    try:
        shutil.rmtree(base, ignore_errors=True)
    except Exception:
        return


def clear_runtime_cache_root() -> None:
    root = runtime_cache_root()
    if not root.exists():
        return
    try:
        shutil.rmtree(root, ignore_errors=True)
    except Exception:
        return


def clear_all_online_runtime_caches() -> None:
    clear_all_online_icon_caches()
    clear_all_online_loot_item_caches()


def clear_character_metadata_caches() -> None:
    index_path = character_sheet_index_cache_path()
    linked_items_root = character_linked_item_cache_root()
    cache_root = character_cache_dir()
    try:
        if index_path.exists():
            index_path.unlink()
        if linked_items_root.exists():
            shutil.rmtree(linked_items_root, ignore_errors=True)
        if cache_root.exists() and not any(cache_root.iterdir()):
            cache_root.rmdir()
    except Exception:
        return


def clear_item_icon_cache() -> None:
    cache_dir = item_icon_cache_dir()
    if not cache_dir.exists():
        return
    try:
        shutil.rmtree(cache_dir, ignore_errors=True)
    except Exception:
        return


def clear_session_attachment_caches() -> None:
    cache_root = session_attachment_cache_root()
    if not cache_root.exists():
        return
    try:
        shutil.rmtree(cache_root, ignore_errors=True)
    except Exception:
        return


def clear_all_disposable_caches() -> None:
    clear_character_metadata_caches()
    clear_item_icon_cache()
    clear_session_attachment_caches()
