from __future__ import annotations

import sys
from pathlib import Path

_WARNED_MISSING_RESOURCES: set[str] = set()


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    meipass = str(getattr(sys, "_MEIPASS", "") or "").strip()
    if meipass:
        candidates.append(Path(meipass))
    executable = str(getattr(sys, "executable", "") or "").strip()
    if executable and is_frozen_app():
        candidates.append(Path(executable).resolve().parent)
    candidates.append(Path(__file__).resolve().parent.parent)
    candidates.append(Path(__file__).resolve().parent)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def resource_path(*parts: str) -> Path:
    cleaned_parts = tuple(str(part) for part in parts if str(part))
    candidates = _resource_root_candidates()
    fallback = candidates[0] if candidates else Path.cwd()
    if not cleaned_parts:
        return fallback

    for root in candidates:
        candidate = root.joinpath(*cleaned_parts)
        if candidate.exists():
            return candidate

    target = fallback.joinpath(*cleaned_parts)
    key = str(target)
    if key not in _WARNED_MISSING_RESOURCES:
        print(f"[WARN] Bundled resource not found: {target}", file=sys.stderr)
        _WARNED_MISSING_RESOURCES.add(key)
    return target


def asset_path(*parts: str) -> Path:
    return resource_path("assets", *parts)


def icons_dir() -> Path:
    return asset_path("icons")


def icon_path(name: str) -> Path:
    return asset_path("icons", str(name or "").strip())


def item_icon_dirs() -> tuple[Path, Path]:
    return (
        asset_path("itemicons"),
        asset_path("iconitems"),
    )


def equipment_backgrounds_dir() -> Path:
    return asset_path("equipment backgrounds")
