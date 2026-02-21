import os
import sys

import pytest
from PyQt6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from app import HomeWidget, MainLauncherWindow, APPLET_DEFINITIONS


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
        "app.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(collection_path), "Dungeon Collection (*.json)"),
    )
    monkeypatch.setattr(
        "app.QInputDialog.getInt",
        lambda *args, **kwargs: (8765, True),
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._host_dungeon_collection()

    assert len(opened) == 1
    applet, focus = opened[0]
    assert focus is True
    assert str(applet["key"]).startswith("online_host::")
    assert applet["online"]["port"] == 8765
    assert applet["online"]["collection_path"] == str(collection_path)


def test_join_online_builds_online_join_applet(monkeypatch, qapp):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    text_answers = iter(
        [
            ("192.168.1.10", True),  # host ip
            ("Mira", True),  # player name
        ]
    )
    monkeypatch.setattr(
        "app.QInputDialog.getText",
        lambda *args, **kwargs: next(text_answers),
    )
    monkeypatch.setattr(
        "app.QInputDialog.getInt",
        lambda *args, **kwargs: (8765, True),
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


def test_host_online_cancelled_file_dialog_does_not_open_applet(monkeypatch, qapp):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        "app.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: ("", ""),
    )
    monkeypatch.setattr(
        "app.QInputDialog.getInt",
        lambda *args, **kwargs: pytest.fail("port prompt should not be shown when no file was chosen"),
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._host_dungeon_collection()

    assert opened == []


def test_host_online_cancelled_port_does_not_open_applet(monkeypatch, qapp, tmp_path):
    opened = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    collection_path = tmp_path / "collection.json"
    collection_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "app.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: (str(collection_path), "Dungeon Collection (*.json)"),
    )
    monkeypatch.setattr(
        "app.QInputDialog.getInt",
        lambda *args, **kwargs: (8765, False),
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._host_dungeon_collection()

    assert opened == []


def test_join_online_rejects_blank_host_ip(monkeypatch, qapp):
    opened = []
    warnings = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    monkeypatch.setattr(
        "app.QInputDialog.getText",
        lambda *args, **kwargs: ("   ", True),
    )
    monkeypatch.setattr(
        "app.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    widget = HomeWidget(APPLET_DEFINITIONS, _on_open)
    widget._join_dungeon_by_ip()

    assert opened == []
    assert len(warnings) == 1


def test_join_online_rejects_blank_player_name(monkeypatch, qapp):
    opened = []
    warnings = []

    def _on_open(applet, focus):
        opened.append((applet, focus))

    text_answers = iter(
        [
            ("192.168.1.10", True),
            ("   ", True),
        ]
    )
    monkeypatch.setattr(
        "app.QInputDialog.getText",
        lambda *args, **kwargs: next(text_answers),
    )
    monkeypatch.setattr(
        "app.QInputDialog.getInt",
        lambda *args, **kwargs: (8765, True),
    )
    monkeypatch.setattr(
        "app.QMessageBox.warning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

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
