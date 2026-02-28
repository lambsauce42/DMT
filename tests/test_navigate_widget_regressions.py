import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import navigate_widget
from navigate_widget import NavigateContentWidget


_DEBUG_LOG = Path(ROOT) / "debug" / "test_navigate_widget_regressions.log"


def _debug_log(message: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def _write_nav(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _build_widget(monkeypatch, tmp_path, data: list[dict]) -> NavigateContentWidget:
    nav_path = tmp_path / "nav.json"
    trash_path = tmp_path / "trash.json"
    _write_nav(nav_path, copy.deepcopy(data))
    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))
    monkeypatch.setattr(navigate_widget, "TRASH_PATH", str(trash_path))
    return NavigateContentWidget(show_worlds_header=False)


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


def test_load_navigation_data_reads_legacy_json_file(monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    nav_path.write_text(
        json.dumps([{"name": "Legacy World", "campaigns": []}], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))

    data = navigate_widget.load_navigation_data()

    assert len(data) == 1
    assert data[0]["name"] == "Legacy World"


def test_widget_init_handles_timezone_aware_trash(qtbot, monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    trash_path = tmp_path / "trash.json"
    _write_nav(nav_path, [{"name": "World A", "campaigns": []}])
    trash_path.write_text(
        json.dumps(
            [
                {
                    "type": "world",
                    "name": "Old World",
                    "payload": {"name": "Old World"},
                    "deleted_at": (datetime.now(timezone.utc) - timedelta(days=31)).isoformat(),
                },
                {
                    "type": "world",
                    "name": "Recent World",
                    "payload": {"name": "Recent World"},
                    "deleted_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(),
                },
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))
    monkeypatch.setattr(navigate_widget, "TRASH_PATH", str(trash_path))

    widget = NavigateContentWidget(show_worlds_header=False)
    qtbot.addWidget(widget)

    assert [entry.get("name") for entry in widget._trash] == ["Recent World"]


def test_widget_init_preserves_loaded_navigation_ids(qtbot, monkeypatch, tmp_path):
    _debug_log("test_start=legacy_widget_preserves_loaded_ids")
    widget = _build_widget(
        monkeypatch,
        tmp_path,
        [
            {
                "id": "world_1",
                "name": "World A",
                "campaigns": [
                    {
                        "id": "campaign_1",
                        "name": "Campaign A",
                        "groups": [{"id": "group_1", "name": "Group A"}],
                    }
                ],
            }
        ]
    )
    qtbot.addWidget(widget)

    _debug_log(
        "loaded_ids="
        f"{widget._data[0].get('id')}/"
        f"{widget._data[0]['campaigns'][0].get('id')}/"
        f"{widget._data[0]['campaigns'][0]['groups'][0].get('id')}"
    )

    assert widget._data[0]["id"] == "world_1"
    assert widget._data[0]["campaigns"][0]["id"] == "campaign_1"
    assert widget._data[0]["campaigns"][0]["groups"][0]["id"] == "group_1"


def test_revive_campaign_after_world_rename_stays_recoverable(qtbot, monkeypatch, tmp_path):
    _debug_log("test_start=legacy_campaign_revive_after_world_rename")
    widget = _build_widget(
        monkeypatch,
        tmp_path,
        [
            {
                "id": "world_1",
                "name": "World A",
                "campaigns": [{"id": "campaign_1", "name": "Campaign A", "groups": []}],
            }
        ]
    )
    qtbot.addWidget(widget)

    widget._remove_campaign(0, "Campaign A")
    _debug_log(f"trash_parent={widget._trash[0].get('parent')}")

    widget._data[0]["name"] = "World B"
    _debug_log("renamed_world=World B")

    def _select_entry(title: str, label: str, entries: list[dict]) -> dict | None:
        _debug_log(f"campaign_revive_candidates={len(entries)}")
        return entries[0] if entries else None

    widget._select_trash_entry = _select_entry  # type: ignore[assignment]
    with patch.object(navigate_widget.QMessageBox, "information", lambda *args, **kwargs: None):
        widget._revive_campaign(0)

    _debug_log(f"after_revive_campaigns={len(widget._data[0]['campaigns'])}")

    assert [entry["name"] for entry in widget._data[0]["campaigns"]] == ["Campaign A"]
    assert widget._data[0]["campaigns"][0]["id"] == "campaign_1"
