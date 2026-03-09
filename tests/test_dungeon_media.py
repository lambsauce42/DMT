import os
import sys

import pytest
from PySide6.QtWidgets import QCheckBox

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import DungeonAppletWidget, ONLINE_MODE_DM_HOST, ONLINE_MODE_LOCAL_DM, ONLINE_MODE_PLAYER
from save_paths import online_media_cache_dir


pytestmark = pytest.mark.tier1


@pytest.fixture
def dungeon_widget(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    return widget


def test_media_button_is_square_and_visible_in_local_dm(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_LOCAL_DM)

    assert not dungeon_widget._media_btn.isHidden()
    assert dungeon_widget._media_btn.width() == dungeon_widget._media_btn.height()


def test_media_panel_hides_dm_controls_for_player(dungeon_widget):
    dungeon_widget._media_library["effects"] = [
        {"asset_id": "fx-1", "title": "Thunder", "path": "C:/fx/thunder.ogg", "icon_path": ""}
    ]
    dungeon_widget._set_online_mode(ONLINE_MODE_PLAYER)
    dungeon_widget._refresh_media_panel()

    assert dungeon_widget._media_music_dm_controls.isHidden()
    assert dungeon_widget._media_music_transport.isHidden()
    assert dungeon_widget._media_effects_dm_controls.isHidden()
    assert not dungeon_widget._media_personal_music_row.isHidden()
    assert not dungeon_widget._media_personal_effects_row.isHidden()
    assert "fx-1" in dungeon_widget._media_effect_buttons
    assert not dungeon_widget._media_effect_buttons["fx-1"].isEnabled()


def test_media_snapshot_contains_state(dungeon_widget):
    dungeon_widget._media_state["music"].update(
        {
            "asset_id": "track-1",
            "title": "Ambience",
            "state": "paused",
            "position_ms": 4200,
            "loop": True,
            "mix_volume": 65,
        }
    )
    dungeon_widget._media_state["effects"].update(
        {
            "mix_volume": 55,
            "active_titles": ["Thunder"],
        }
    )

    snapshot = dungeon_widget._build_online_snapshot()

    assert "media_state" in snapshot
    assert snapshot["media_state"]["music"]["asset_id"] == "track-1"
    assert snapshot["media_state"]["music"]["title"] == "Ambience"
    assert snapshot["media_state"]["effects"]["active_titles"] == ["Thunder"]


def test_media_profile_persists_library_and_audio_preferences(dungeon_widget, tmp_path, monkeypatch):
    profile_path = tmp_path / "media_profile.json"
    monkeypatch.setattr(dungeon_widget, "_media_profile_path", lambda: profile_path)

    dungeon_widget._media_library = {
        "music": [{"asset_id": "m1", "title": "Rain", "path": "C:/music/rain.mp3"}],
        "effects": [{"asset_id": "e1", "title": "Bell", "path": "C:/fx/bell.ogg", "icon_path": "C:/icons/bell.svg"}],
    }
    dungeon_widget._audio_preferences = {
        "music_volume": 33,
        "effects_volume": 77,
        "mute_music": True,
        "mute_effects": False,
    }

    dungeon_widget._save_media_profile()
    loaded = dungeon_widget._load_or_create_media_profile()

    assert loaded["media_library"]["music"][0]["title"] == "Rain"
    assert loaded["media_library"]["effects"][0]["asset_id"] == "e1"
    assert loaded["media_library"]["effects"][0]["icon_path"] == "C:/icons/bell.svg"
    assert loaded["audio_preferences"]["music_volume"] == 33
    assert loaded["audio_preferences"]["mute_music"] is True


def test_soundboard_pad_buttons_are_square(dungeon_widget):
    dungeon_widget._media_library["effects"] = [
        {"asset_id": "fx-1", "title": "Thunder", "path": "C:/fx/thunder.ogg", "icon_path": ""}
    ]

    dungeon_widget._refresh_media_panel()

    pad = dungeon_widget._media_effect_buttons["fx-1"]
    assert pad.width() == pad.height()


def test_media_slider_rows_do_not_end_with_checkboxes(dungeon_widget):
    dungeon_widget._refresh_media_panel()

    assert dungeon_widget._media_personal_music_row.findChildren(QCheckBox) == []
    assert dungeon_widget._media_personal_effects_row.findChildren(QCheckBox) == []
    assert dungeon_widget._media_personal_music_value.text().endswith("%")
    assert dungeon_widget._media_personal_effects_value.text().endswith("%")


def test_media_peer_buttons_share_widths(dungeon_widget):
    dungeon_widget._refresh_media_panel()

    transport_widths = {
        dungeon_widget._media_music_play_btn.width(),
        dungeon_widget._media_music_pause_btn.width(),
        dungeon_widget._media_music_stop_btn.width(),
        dungeon_widget._media_music_loop.width(),
    }
    music_manage_widths = {
        dungeon_widget._media_music_add_btn.width(),
        dungeon_widget._media_music_remove_btn.width(),
        dungeon_widget._media_music_rename_btn.width(),
    }
    soundboard_manage_widths = {
        dungeon_widget._media_effects_add_btn.width(),
        dungeon_widget._media_effects_icon_btn.width(),
        dungeon_widget._media_effects_rename_btn.width(),
        dungeon_widget._media_effects_remove_btn.width(),
        dungeon_widget._media_effects_stop_btn.width(),
    }
    mute_widths = {
        dungeon_widget._media_personal_music_mute.width(),
        dungeon_widget._media_personal_effects_mute.width(),
    }

    assert len(transport_widths) == 1
    assert len(music_manage_widths) == 1
    assert len(soundboard_manage_widths) == 1
    assert len(mute_widths) == 1


def test_snapshot_media_state_does_not_overwrite_local_audio_preferences(dungeon_widget):
    dungeon_widget._audio_preferences = {
        "music_volume": 12,
        "effects_volume": 34,
        "mute_music": True,
        "mute_effects": False,
    }
    snapshot_media = {
        "server": {"active": False, "port": 0, "token": ""},
        "music": {
            "asset_id": "",
            "title": "",
            "state": "stopped",
            "position_ms": 0,
            "duration_ms": 0,
            "anchor_utc": "",
            "loop": False,
            "mix_volume": 90,
        },
        "effects": {
            "mix_volume": 80,
            "active_titles": [],
        },
    }

    dungeon_widget._apply_snapshot_media_state(snapshot_media)

    assert dungeon_widget._audio_preferences["music_volume"] == 12
    assert dungeon_widget._audio_preferences["effects_volume"] == 34
    assert dungeon_widget._audio_preferences["mute_music"] is True


def test_host_media_server_updates_snapshot_endpoint_and_cache_path(dungeon_widget):
    dungeon_widget._set_online_mode(ONLINE_MODE_DM_HOST)
    dungeon_widget._start_host_media_server()
    try:
        payload = dungeon_widget._snapshot_media_state()["server"]
        assert payload["active"] is True
        assert int(payload["port"]) > 0
        assert online_media_cache_dir("session-x").name == "media"
    finally:
        dungeon_widget._stop_host_media_server()
