import os
import sys
import json

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QLineEdit, QPushButton, QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import (
    HomeWidget,
    MainLauncherWindow,
    APPLET_DEFINITIONS,
    build_applet_widget,
    _append_online_launch_log,
)
from user_settings import (
    is_ctrl_mouse_wheel_zoom_enabled,
    is_session_autosave_enabled,
    load_app_settings,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_host_online_builds_online_host_applet(monkeypatch, qapp, tmp_path):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    collection_path = tmp_path / "collection.json"
    collection_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        HomeWidget,
        "_prompt_host_dungeon_collection_details",
        lambda self: {"collection_path": str(collection_path), "port": 8765, "dm_name": "Aria"},
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._host_dungeon_collection()

    assert len(opened) == 1
    applet, focus = opened[0]
    assert focus is True
    assert str(applet["key"]).startswith("online_host::")
    assert applet["online"]["port"] == 8765
    assert applet["online"]["collection_path"] == str(collection_path)
    assert applet["online"]["dm_name"] == "Aria"


def test_join_online_builds_online_join_applet(monkeypatch, qapp):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        HomeWidget,
        "_prompt_join_online_details",
        lambda self: {"host_ip": "192.168.1.10", "port": 8765, "player_name": "Mira"},
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._join_dungeon_by_ip()

    assert len(opened) == 1
    applet, focus = opened[0]
    assert focus is True
    assert str(applet["key"]).startswith("online_join::")
    assert applet["online"]["host_ip"] == "192.168.1.10"
    assert applet["online"]["port"] == 8765
    assert applet["online"]["player_name"] == "Mira"


def test_join_online_prompt_prefills_last_saved_player_name(monkeypatch, qapp, tmp_path):
    monkeypatch.setattr("app.dnd_saves_dir", lambda: tmp_path)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "dungeon_profile.json").write_text(
        json.dumps({"last_player_name": "Scout"}),
        encoding="utf-8",
    )

    widget = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)

    def _fake_exec(self):
        line_edits = self.findChildren(QLineEdit)
        assert any(edit.text() == "Scout" for edit in line_edits)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr("app.ModernDialog.exec", _fake_exec)

    assert widget._prompt_join_online_details() is None


def test_join_online_prompt_prefills_last_saved_host_ip(monkeypatch, qapp, tmp_path):
    monkeypatch.setattr("app.dnd_saves_dir", lambda: tmp_path)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "dungeon_profile.json").write_text(
        json.dumps({"last_join_host_ip": "10.0.0.42"}),
        encoding="utf-8",
    )

    widget = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)

    def _fake_exec(self):
        line_edits = self.findChildren(QLineEdit)
        assert any(edit.text() == "10.0.0.42" for edit in line_edits)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr("app.ModernDialog.exec", _fake_exec)

    assert widget._prompt_join_online_details() is None


def test_host_online_prompt_prefills_last_saved_dm_name(monkeypatch, qapp, tmp_path):
    monkeypatch.setattr("app.dnd_saves_dir", lambda: tmp_path)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "dungeon_profile.json").write_text(
        json.dumps({"last_dm_name": "Keeper"}),
        encoding="utf-8",
    )

    widget = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)

    def _fake_exec(self):
        line_edits = self.findChildren(QLineEdit)
        assert any(edit.text() == "Keeper" for edit in line_edits)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr("app.ModernDialog.exec", _fake_exec)

    assert widget._prompt_host_dungeon_collection_details() is None


def test_host_online_prompt_prefills_last_existing_collection(monkeypatch, qapp, tmp_path):
    monkeypatch.setattr("app.dnd_saves_dir", lambda: tmp_path)
    settings_dir = tmp_path / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    collection_path = tmp_path / "cached.dmtcollection"
    collection_path.write_text("{}", encoding="utf-8")
    (settings_dir / "dungeon_profile.json").write_text(
        json.dumps({"last_host_collection_path": str(collection_path)}),
        encoding="utf-8",
    )

    widget = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)

    def _fake_exec(self):
        line_edits = self.findChildren(QLineEdit)
        assert any(edit.text() == str(collection_path) for edit in line_edits)
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr("app.ModernDialog.exec", _fake_exec)

    assert widget._prompt_host_dungeon_collection_details() is None


def test_host_online_cancelled_dialog_does_not_open_applet(monkeypatch, qapp):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        HomeWidget,
        "_prompt_host_dungeon_collection_details",
        lambda self: None,
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._host_dungeon_collection()

    assert opened == []


def test_host_online_invalid_collection_does_not_open_applet(monkeypatch, qapp, tmp_path):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        HomeWidget,
        "_prompt_host_dungeon_collection_details",
        lambda self: {"collection_path": str(tmp_path / "missing.dmtcollection"), "port": 8765, "dm_name": "Aria"},
    )
    warnings = []
    monkeypatch.setattr(
        "app.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._host_dungeon_collection()

    assert opened == []
    assert len(warnings) == 1


def test_join_online_rejects_blank_host_ip(monkeypatch, qapp):
    opened = []
    warnings = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        HomeWidget,
        "_prompt_join_online_details",
        lambda self: {"host_ip": "   ", "port": 8765, "player_name": "Player"},
    )
    monkeypatch.setattr("app.QMessageBox.warning", lambda *args, **kwargs: warnings.append((args, kwargs)))

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._join_dungeon_by_ip()

    assert opened == []
    assert len(warnings) == 1


def test_join_online_rejects_blank_player_name(monkeypatch, qapp):
    opened = []
    warnings = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        HomeWidget,
        "_prompt_join_online_details",
        lambda self: {"host_ip": "192.168.1.10", "port": 8765, "player_name": "   "},
    )
    monkeypatch.setattr("app.QMessageBox.warning", lambda *args, **kwargs: warnings.append((args, kwargs)))

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._join_dungeon_by_ip()

    assert opened == []
    assert len(warnings) == 1


def test_main_window_close_clears_online_runtime_caches(monkeypatch, qapp):
    calls = []
    monkeypatch.setattr("app.clear_all_online_runtime_caches", lambda: calls.append(True))

    window = MainLauncherWindow()
    window.close()

    assert calls == [True]


def test_home_settings_saves_session_autosave_toggle(monkeypatch, qapp):
    widget = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)

    def _fake_exec(self):
        checkboxes = {checkbox.text(): checkbox for checkbox in self.findChildren(QCheckBox)}
        checkbox = checkboxes.get("Enable autosave while editing sessions")
        assert checkbox is not None
        assert checkbox.isChecked() is False
        checkbox.setChecked(True)
        for button in self.findChildren(QPushButton):
            if button.text() == "Save":
                button.click()
                return 0
        pytest.fail("Save button not found")

    monkeypatch.setattr("app.ModernDialog.exec", _fake_exec)

    widget._show_settings()

    assert is_session_autosave_enabled() is True


def test_home_settings_saves_ctrl_wheel_zoom_toggle(monkeypatch, qapp):
    widget = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)

    def _fake_exec(self):
        checkboxes = {checkbox.text(): checkbox for checkbox in self.findChildren(QCheckBox)}
        checkbox = checkboxes.get("Require Ctrl for mouse-wheel zoom")
        assert checkbox is not None
        assert checkbox.isChecked() is True
        checkbox.setChecked(False)
        for button in self.findChildren(QPushButton):
            if button.text() == "Save":
                button.click()
                return 0
        pytest.fail("Save button not found")

    monkeypatch.setattr("app.ModernDialog.exec", _fake_exec)

    widget._show_settings()

    assert is_ctrl_mouse_wheel_zoom_enabled() is False


def test_home_widget_creates_and_reuses_launcher_player_id(qapp):
    first = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)
    first_id = str(first._local_player_id)

    assert first_id
    assert first._player_id_label.text() == f"Player ID: {first_id}"
    assert str(load_app_settings().get("local_player_id") or "") == first_id

    second = HomeWidget(APPLET_DEFINITIONS, lambda applet, focus: None)
    assert str(second._local_player_id) == first_id


def test_online_join_launch_exception_writes_diagnostics_log(monkeypatch, qapp, tmp_path):
    _ = qapp
    log_path = tmp_path / "online_launch.log"
    deleted = []

    class _ExplodingDungeonWidget:
        def __init__(self, parent=None):
            _ = parent

        def join_online_session(self, host_ip, port, player_name):
            _ = (host_ip, port, player_name)
            raise RuntimeError("join boom")

        def deleteLater(self):
            deleted.append(True)

    monkeypatch.setattr("app._online_launch_log_path", lambda: log_path)
    monkeypatch.setattr("app.DungeonAppletWidget", _ExplodingDungeonWidget)

    result = build_applet_widget(
        QWidget(),
        "online_join::127.0.0.1:8765::Mira::123",
        {
            "key": "online_join::127.0.0.1:8765::Mira::123",
            "online": {"host_ip": "127.0.0.1", "port": 8765, "player_name": "Mira"},
        },
    )

    assert result is None
    assert deleted == [True]
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [str(line.get("event") or "") for line in lines]
    assert "online_join_launch_begin" in events
    assert "online_join_launch_exception" in events
    exception_row = next(row for row in lines if row.get("event") == "online_join_launch_exception")
    assert "join boom" in str(exception_row.get("error") or "")
    assert "RuntimeError" in str(exception_row.get("traceback") or "")


def test_online_host_launch_failed_writes_diagnostics_log(monkeypatch, qapp, tmp_path):
    _ = qapp
    log_path = tmp_path / "online_launch.log"
    deleted = []

    class _HostFailDungeonWidget:
        def __init__(self, parent=None):
            _ = parent

        def start_online_host(self, port, collection_path, dm_name):
            _ = (port, collection_path, dm_name)
            return False

        def deleteLater(self):
            deleted.append(True)

    monkeypatch.setattr("app._online_launch_log_path", lambda: log_path)
    monkeypatch.setattr("app.DungeonAppletWidget", _HostFailDungeonWidget)

    result = build_applet_widget(
        QWidget(),
        "online_host::8765::Collection::123",
        {
            "key": "online_host::8765::Collection::123",
            "online": {"port": 8765, "collection_path": "/tmp/test.dmtcollection"},
        },
    )

    assert result is None
    assert deleted == [True]
    lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [str(line.get("event") or "") for line in lines]
    assert "online_host_launch_begin" in events
    assert "online_host_launch_failed" in events


def test_online_launch_log_is_written_to_shared_and_instance_files(monkeypatch, qapp, tmp_path):
    _ = qapp
    shared_path = tmp_path / "dmt_online_launch.log"
    monkeypatch.setattr("app._online_launch_log_path", lambda: shared_path)

    _append_online_launch_log("instance_file_probe", probe=True)

    pid = os.getpid()
    instance_path = tmp_path / f"dmt_online_launch_pid{pid}.log"
    assert shared_path.exists()
    assert instance_path.exists()
    assert "instance_file_probe" in shared_path.read_text(encoding="utf-8")
    assert "instance_file_probe" in instance_path.read_text(encoding="utf-8")
