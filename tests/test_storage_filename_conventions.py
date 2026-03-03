import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dmt_package import read_dmt_package_info
import npc_database
from navigation_storage import (
    load_navigation_world_data,
    navigation_objects_dir,
    save_navigation_world_data,
)
from npc_database import NPCEntry, npc_file_path
from maps_applet import map_file_path
from session_creator import Session, SessionManager, session_file_path
from unique_ids import MAX_NAMED_OBJECT_ID_LENGTH, generate_named_object_id

pytestmark = pytest.mark.tier0


def test_generate_named_object_id_is_capped() -> None:
    object_id = generate_named_object_id("A" * 500, "session")
    assert len(object_id) <= MAX_NAMED_OBJECT_ID_LENGTH


def test_path_helpers_use_names_instead_of_object_ids(tmp_path: Path) -> None:
    assert map_file_path("Forest Entrance").name == "Forest_Entrance.dmtmap"
    assert npc_file_path("Bob the Bold").name == "Bob_the_Bold.dmtnpc"
    assert session_file_path("Session Zero", tmp_path).name == "Session_Zero.dmtsession"


def test_save_npc_uses_name_based_filename_and_internal_object_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(npc_database, "default_sheet_save_dir", lambda: str(tmp_path))
    monkeypatch.setattr(npc_database, "_now_timestamp", lambda: "2026-02-26T12:00:00")

    entry = NPCEntry(id="npc_internal_123", name="Bob")
    npc_database.save_npc_entries_to_storage([entry])

    package_path = tmp_path / "npcs" / "Bob.dmtnpc"
    info = read_dmt_package_info(package_path)
    assert package_path.exists()
    assert isinstance(info, dict)
    assert info.get("object_id") == "npc_internal_123"


def test_navigation_save_uses_object_ids_for_package_filenames(tmp_path: Path) -> None:
    world_data = [
        {
            "id": "world_internal",
            "name": "World Prime",
            "icon": "",
            "campaigns": [
                {
                    "id": "campaign_internal",
                    "name": "Campaign Alpha",
                    "icon": "",
                    "groups": [
                        {
                            "id": "group_internal",
                            "name": "Group One",
                            "icon": "",
                        }
                    ],
                }
            ],
        }
    ]

    save_navigation_world_data(world_data, base_dir=tmp_path)

    root = navigation_objects_dir(base_dir=tmp_path)
    world_path = root / "worlds" / "world_internal.dmtworld"
    campaign_path = root / "campaigns" / "campaign_internal.dmtcampaign"
    group_path = root / "groups" / "group_internal.dmtgroup"

    assert world_path.exists()
    assert campaign_path.exists()
    assert group_path.exists()
    assert read_dmt_package_info(world_path).get("object_id") == "world_internal"
    assert read_dmt_package_info(campaign_path).get("object_id") == "campaign_internal"
    assert read_dmt_package_info(group_path).get("object_id") == "group_internal"


def test_navigation_save_preserves_distinct_objects_with_duplicate_names(tmp_path: Path) -> None:
    world_data = [
        {
            "id": "world_one",
            "name": "Shared World",
            "icon": "",
            "campaigns": [
                {
                    "id": "campaign_one",
                    "name": "Shared Campaign",
                    "icon": "",
                    "groups": [
                        {
                            "id": "group_one",
                            "name": "Shared Group",
                            "icon": "",
                        }
                    ],
                }
            ],
        },
        {
            "id": "world_two",
            "name": "Shared World",
            "icon": "",
            "campaigns": [
                {
                    "id": "campaign_two",
                    "name": "Shared Campaign",
                    "icon": "",
                    "groups": [
                        {
                            "id": "group_two",
                            "name": "Shared Group",
                            "icon": "",
                        }
                    ],
                }
            ],
        },
    ]

    save_navigation_world_data(world_data, base_dir=tmp_path)
    loaded = load_navigation_world_data(base_dir=tmp_path)

    assert [world.get("id") for world in loaded] == ["world_one", "world_two"]
    assert [campaign.get("id") for campaign in loaded[0]["campaigns"]] == ["campaign_one"]
    assert [campaign.get("id") for campaign in loaded[1]["campaigns"]] == ["campaign_two"]
    assert [group.get("id") for group in loaded[0]["campaigns"][0]["groups"]] == ["group_one"]
    assert [group.get("id") for group in loaded[1]["campaigns"][0]["groups"]] == ["group_two"]


def test_session_manager_saves_package_under_session_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import session_creator

    monkeypatch.setattr(session_creator, "session_storage_path", lambda: tmp_path / "sessions.dmtindex")

    manager = SessionManager()
    manager.sessions = [Session(id="internal_session_id", name="Named Session", session_date="2026-02-26")]
    manager.save()

    package_path = tmp_path / "Named_Session.dmtsession"
    info = read_dmt_package_info(package_path)
    assert package_path.exists()
    assert isinstance(info, dict)
    assert info.get("object_id") == "internal_session_id"
