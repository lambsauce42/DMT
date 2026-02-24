import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import navigate_widget
from navigate_widget import NavigateContentWidget


def _write_nav(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def test_remove_world_moves_single_trash_entry(qtbot, monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    trash_path = tmp_path / "trash.json"
    _write_nav(nav_path, [{"name": "World A", "campaigns": []}])

    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))
    monkeypatch.setattr(navigate_widget, "TRASH_PATH", str(trash_path))

    widget = NavigateContentWidget(show_worlds_header=False)
    qtbot.addWidget(widget)

    widget.remove_world(name="World A")

    assert widget._data == []
    assert len(widget._trash) == 1
    assert widget._trash[0].get("name") == "World A"


def test_remove_world_missing_name_is_noop(qtbot, monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    trash_path = tmp_path / "trash.json"
    _write_nav(nav_path, [{"name": "World A", "campaigns": []}])

    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))
    monkeypatch.setattr(navigate_widget, "TRASH_PATH", str(trash_path))

    widget = NavigateContentWidget(show_worlds_header=False)
    qtbot.addWidget(widget)

    widget.remove_world(name="Does Not Exist")

    assert len(widget._data) == 1
    assert widget._data[0]["name"] == "World A"
    assert widget._trash == []


def test_load_navigation_data_tolerates_missing_campaigns_key(qtbot, monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    trash_path = tmp_path / "trash.json"
    _write_nav(nav_path, [{"name": "World Only"}])

    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))
    monkeypatch.setattr(navigate_widget, "TRASH_PATH", str(trash_path))

    widget = NavigateContentWidget(show_worlds_header=False)
    qtbot.addWidget(widget)

    assert len(widget._data) == 1
    assert widget._data[0]["name"] == "World Only"
    assert widget._data[0]["campaigns"] == []
