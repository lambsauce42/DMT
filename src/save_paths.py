from __future__ import annotations

import os
import sys
import shutil
from pathlib import Path

DEFAULT_SAVE_DIR_PARTS = ("Documents", "DMT")
DEFAULT_SAVE_DIR_FALLBACK_PARTS = ("documents", "DMT")
LEGACY_NESTED_DND_DIR_NAME = "DMT_saves"


def _in_test_env() -> bool:
    if os.environ.get("DMT_TEST_MODE") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules





def default_dnd_save_dir() -> str:
    if _in_test_env():
        return str(Path.cwd() / "tests" / "test_saves" / "DMT")
    
    home = os.path.expanduser("~")
    primary = Path(home).joinpath(*DEFAULT_SAVE_DIR_PARTS)
    fallback = Path(home).joinpath(*DEFAULT_SAVE_DIR_FALLBACK_PARTS)
    
    if os.path.exists(os.path.join(home, DEFAULT_SAVE_DIR_PARTS[0])):
        return str(primary)
    return str(fallback)


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


def navigation_trash_path() -> Path:
    return dnd_saves_dir() / "trash" / "navigation_trash.json"


def navigation_json_path() -> Path:
    return dnd_saves_dir() / "navigation.json"


def items_dir() -> Path:
    return dnd_saves_dir() / "items"


def dungeon_collections_dir() -> Path:
    return dnd_saves_dir() / "dungeon_collections"


def online_sessions_dir() -> Path:
    return dnd_saves_dir() / "online_sessions"


def online_session_dir(session_id: str) -> Path:
    safe = "".join(ch for ch in str(session_id).strip() if ch not in '<>:"/\\|?*').strip(" .")
    if not safe:
        safe = "session"
    return online_sessions_dir() / safe


def online_icon_cache_dir(session_id: str) -> Path:
    return online_session_dir(session_id) / "cache" / "icons"


def online_loot_item_cache_root() -> Path:
    return dnd_saves_dir() / "cache" / "online_loot_items"


def runtime_cache_root() -> Path:
    return dnd_saves_dir() / "cache"


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


def working_collection_icon_assets_dir(collection_name: str) -> Path:
    safe_name = _safe_component(collection_name, "collection")
    return dungeon_collections_dir() / "_working_assets" / safe_name / "icons"


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
    clear_runtime_cache_root()
