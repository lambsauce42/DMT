from __future__ import annotations

import sys
from pathlib import Path

from dmt_package import read_dmt_package_info, write_dmt_package
from save_paths import dnd_saves_dir
from unique_ids import generate_named_object_id


NAVIGATION_OBJECTS_DIR_NAME = "navigation_objects"
WORLD_EXTENSION = ".dmtworld"
CAMPAIGN_EXTENSION = ".dmtcampaign"
GROUP_EXTENSION = ".dmtgroup"

WORLD_FORMAT = "dmtworld.v1"
CAMPAIGN_FORMAT = "dmtcampaign.v1"
GROUP_FORMAT = "dmtgroup.v1"


def _safe_component(value: str, fallback: str) -> str:
    invalid = set('<>:"/\\|?*')
    cleaned = "".join(ch for ch in str(value or "").strip() if ch not in invalid).strip(" .")
    return cleaned or fallback


def _safe_order(value: object, *, object_type: str, object_id: str, path: Path) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        print(
            f"[WARN] Invalid {object_type} order in '{path}' for '{object_id}': {value!r}. Using 0.",
            file=sys.stderr,
        )
        return 0


def navigation_objects_dir(base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else dnd_saves_dir()
    return root / NAVIGATION_OBJECTS_DIR_NAME


def _worlds_dir(base_dir: Path | None = None) -> Path:
    return navigation_objects_dir(base_dir=base_dir) / "worlds"


def _campaigns_dir(base_dir: Path | None = None) -> Path:
    return navigation_objects_dir(base_dir=base_dir) / "campaigns"


def _groups_dir(base_dir: Path | None = None) -> Path:
    return navigation_objects_dir(base_dir=base_dir) / "groups"


def _ensure_dirs(*, base_dir: Path | None = None) -> None:
    _worlds_dir(base_dir=base_dir).mkdir(parents=True, exist_ok=True)
    _campaigns_dir(base_dir=base_dir).mkdir(parents=True, exist_ok=True)
    _groups_dir(base_dir=base_dir).mkdir(parents=True, exist_ok=True)


def _world_file_path(world_name: str, *, base_dir: Path | None = None) -> Path:
    return _worlds_dir(base_dir=base_dir) / f"{_safe_component(world_name, 'world')}{WORLD_EXTENSION}"


def _campaign_file_path(campaign_name: str, *, base_dir: Path | None = None) -> Path:
    return _campaigns_dir(base_dir=base_dir) / f"{_safe_component(campaign_name, 'campaign')}{CAMPAIGN_EXTENSION}"


def _group_file_path(group_name: str, *, base_dir: Path | None = None) -> Path:
    return _groups_dir(base_dir=base_dir) / f"{_safe_component(group_name, 'group')}{GROUP_EXTENSION}"


def load_navigation_world_data(*, base_dir: Path | None = None) -> list[dict]:
    root = navigation_objects_dir(base_dir=base_dir)
    if not root.exists():
        return []

    worlds_by_id: dict[str, dict] = {}
    for path in sorted(_worlds_dir(base_dir=base_dir).glob(f"*{WORLD_EXTENSION}")):
        info = read_dmt_package_info(path)
        if not isinstance(info, dict):
            continue
        if str(info.get("format") or "") != WORLD_FORMAT:
            continue
        world_id = str(info.get("object_id") or "").strip()
        name = str(info.get("name") or "").strip()
        if not world_id or not name:
            continue
        worlds_by_id[world_id] = {
            "id": world_id,
            "name": name,
            "icon": str(info.get("icon") or ""),
            "_order": _safe_order(
                info.get("order"),
                object_type="world",
                object_id=world_id,
                path=path,
            ),
            "campaigns": [],
        }

    campaigns_by_id: dict[str, dict] = {}
    for path in sorted(_campaigns_dir(base_dir=base_dir).glob(f"*{CAMPAIGN_EXTENSION}")):
        info = read_dmt_package_info(path)
        if not isinstance(info, dict):
            continue
        if str(info.get("format") or "") != CAMPAIGN_FORMAT:
            continue
        campaign_id = str(info.get("object_id") or "").strip()
        world_id = str(info.get("world_id") or "").strip()
        name = str(info.get("name") or "").strip()
        if not campaign_id or not world_id or not name:
            continue
        if world_id not in worlds_by_id:
            continue
        row = {
            "id": campaign_id,
            "name": name,
            "icon": str(info.get("icon") or ""),
            "_order": _safe_order(
                info.get("order"),
                object_type="campaign",
                object_id=campaign_id,
                path=path,
            ),
            "world_id": world_id,
            "groups": [],
        }
        campaigns_by_id[campaign_id] = row
        worlds_by_id[world_id]["campaigns"].append(row)

    for path in sorted(_groups_dir(base_dir=base_dir).glob(f"*{GROUP_EXTENSION}")):
        info = read_dmt_package_info(path)
        if not isinstance(info, dict):
            continue
        if str(info.get("format") or "") != GROUP_FORMAT:
            continue
        group_id = str(info.get("object_id") or "").strip()
        campaign_id = str(info.get("campaign_id") or "").strip()
        name = str(info.get("name") or "").strip()
        if not group_id or not campaign_id or not name:
            continue
        campaign = campaigns_by_id.get(campaign_id)
        if not isinstance(campaign, dict):
            continue
        campaign["groups"].append(
            {
                "id": group_id,
                "name": name,
                "icon": str(info.get("icon") or ""),
                "_order": _safe_order(
                    info.get("order"),
                    object_type="group",
                    object_id=group_id,
                    path=path,
                ),
            }
        )

    worlds = sorted(
        worlds_by_id.values(),
        key=lambda row: (int(row.get("_order") or 0), str(row.get("name") or "").lower()),
    )
    result: list[dict] = []
    for world in worlds:
        campaigns = sorted(
            world.get("campaigns", []),
            key=lambda row: (int(row.get("_order") or 0), str(row.get("name") or "").lower()),
        )
        world_out = {
            "id": world.get("id"),
            "name": world.get("name"),
            "icon": world.get("icon"),
            "campaigns": [],
        }
        for campaign in campaigns:
            groups = sorted(
                campaign.get("groups", []),
                key=lambda row: (int(row.get("_order") or 0), str(row.get("name") or "").lower()),
            )
            campaign_out = {
                "id": campaign.get("id"),
                "name": campaign.get("name"),
                "icon": campaign.get("icon"),
                "groups": [],
            }
            for group in groups:
                campaign_out["groups"].append(
                    {
                        "id": group.get("id"),
                        "name": group.get("name"),
                        "icon": group.get("icon"),
                    }
                )
            world_out["campaigns"].append(campaign_out)
        result.append(world_out)
    return result


def save_navigation_world_data(world_data: list[dict], *, base_dir: Path | None = None) -> None:
    _ensure_dirs(base_dir=base_dir)
    expected: set[Path] = set()
    for world_order, world in enumerate(world_data):
        if not isinstance(world, dict):
            continue
        world_name = str(world.get("name") or "").strip()
        if not world_name:
            continue
        world_id = str(world.get("id") or "").strip() or generate_named_object_id(world_name, "world")
        world["id"] = world_id
        world_path = _world_file_path(world_name, base_dir=base_dir)
        expected.add(world_path.resolve())
        write_dmt_package(
            world_path,
            info={
                "format": WORLD_FORMAT,
                "object_type": "world",
                "object_id": world_id,
                "name": world_name,
                "icon": str(world.get("icon") or ""),
                "order": world_order,
            },
        )

        campaigns = world.get("campaigns")
        if not isinstance(campaigns, list):
            continue
        for campaign_order, campaign in enumerate(campaigns):
            if not isinstance(campaign, dict):
                continue
            campaign_name = str(campaign.get("name") or "").strip()
            if not campaign_name:
                continue
            campaign_id = (
                str(campaign.get("id") or "").strip()
                or generate_named_object_id(campaign_name, "campaign")
            )
            campaign["id"] = campaign_id
            campaign_path = _campaign_file_path(campaign_name, base_dir=base_dir)
            expected.add(campaign_path.resolve())
            write_dmt_package(
                campaign_path,
                info={
                    "format": CAMPAIGN_FORMAT,
                    "object_type": "campaign",
                    "object_id": campaign_id,
                    "world_id": world_id,
                    "name": campaign_name,
                    "icon": str(campaign.get("icon") or ""),
                    "order": campaign_order,
                },
            )

            groups = campaign.get("groups")
            if not isinstance(groups, list):
                continue
            for group_order, group in enumerate(groups):
                if not isinstance(group, dict):
                    continue
                group_name = str(group.get("name") or "").strip()
                if not group_name:
                    continue
                group_id = (
                    str(group.get("id") or "").strip()
                    or generate_named_object_id(group_name, "group")
                )
                group["id"] = group_id
                group_path = _group_file_path(group_name, base_dir=base_dir)
                expected.add(group_path.resolve())
                write_dmt_package(
                    group_path,
                    info={
                        "format": GROUP_FORMAT,
                        "object_type": "group",
                        "object_id": group_id,
                        "world_id": world_id,
                        "campaign_id": campaign_id,
                        "name": group_name,
                        "icon": str(group.get("icon") or ""),
                        "order": group_order,
                    },
                )

    for directory, extension, expected_format in (
        (_worlds_dir(base_dir=base_dir), WORLD_EXTENSION, WORLD_FORMAT),
        (_campaigns_dir(base_dir=base_dir), CAMPAIGN_EXTENSION, CAMPAIGN_FORMAT),
        (_groups_dir(base_dir=base_dir), GROUP_EXTENSION, GROUP_FORMAT),
    ):
        for existing in directory.glob(f"*{extension}"):
            try:
                resolved = existing.resolve()
            except Exception:
                resolved = existing
            if resolved in expected:
                continue
            info = read_dmt_package_info(existing)
            if not isinstance(info, dict):
                continue
            if str(info.get("format") or "") != expected_format:
                continue
            try:
                existing.unlink()
            except Exception:
                continue
