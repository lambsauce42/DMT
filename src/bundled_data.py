from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from save_paths import default_dnd_save_dir, dnd_saves_dir

_BUNDLED_DATA_FILES = (
    "data/dnd_monsters_full.csv",
    "data/EncounterDifficulty.csv",
    "data/EncounterMultipliers.csv",
    "data/5e_CharacterSheet.pdf",
)
_BUNDLED_RUNTIME_DIRNAME = "bundled_runtime_data"


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _bundled_root() -> Path:
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return Path(str(meipass))
    return Path(sys.executable).resolve().parent


def _runtime_bundle_root() -> Path:
    try:
        return dnd_saves_dir() / "cache" / _BUNDLED_RUNTIME_DIRNAME
    except Exception:
        return Path(default_dnd_save_dir()) / "cache" / _BUNDLED_RUNTIME_DIRNAME


def _runtime_bundle_session_dir() -> Path:
    return _runtime_bundle_root() / f"pid_{os.getpid()}"


def cleanup_stale_bundled_runtime_data() -> None:
    root = _runtime_bundle_root()
    current_name = _runtime_bundle_session_dir().name
    try:
        if not root.exists():
            return
        for child in root.iterdir():
            if child.name == current_name:
                continue
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except Exception:
                    continue
    except Exception as exc:
        print(f"[WARN] Failed to clean stale bundled runtime data: {exc}")


def cleanup_current_bundled_runtime_data() -> None:
    target = _runtime_bundle_session_dir()
    try:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    except Exception as exc:
        print(f"[WARN] Failed to clean bundled runtime data {target}: {exc}")


def data_dir() -> Path:
    if not _is_frozen():
        return _project_root() / "data"
    session_dir = _runtime_bundle_session_dir()
    target_dir = session_dir / "data"
    source_root = _bundled_root()
    target_dir.mkdir(parents=True, exist_ok=True)
    for relative in _BUNDLED_DATA_FILES:
        source_path = source_root / relative
        if not source_path.exists():
            continue
        target_path = session_dir / relative
        if target_path.exists():
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
    return target_dir


def data_path(filename: str) -> Path:
    return data_dir() / str(filename or "").strip()
