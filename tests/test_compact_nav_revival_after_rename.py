import copy
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import compact_nav_tree

pytestmark = pytest.mark.tier1

_DEBUG_LOG = Path(ROOT) / "debug" / "test_compact_nav_revival_after_rename.log"


def _debug_log(message: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"{message}\n")


def _build_widget(data: list[dict]) -> compact_nav_tree.CompactNavTree:
    with patch.object(compact_nav_tree, "load_navigation_data", return_value=copy.deepcopy(data)):
        with patch.object(compact_nav_tree, "load_trash", return_value=[]):
            with patch.object(compact_nav_tree, "save_navigation_data", lambda _: None):
                with patch.object(compact_nav_tree, "save_trash", lambda _: None):
                    return compact_nav_tree.CompactNavTree()


def test_revive_campaign_after_world_rename_keeps_campaign_recoverable() -> None:
    _debug_log("test_start=campaign_revive_after_world_rename")
    _ = QApplication.instance() or QApplication([])
    widget = _build_widget(
        [
            {
                "name": "World A",
                "campaigns": [{"name": "Campaign A", "groups": []}],
            }
        ]
    )
    try:
        widget._remove_campaign(0, "Campaign A")
        _debug_log(f"after_remove_campaigns={len(widget._data[0]['campaigns'])}")
        _debug_log(f"trash_parent={widget._trash[0].get('parent')}")

        widget._data[0]["name"] = "World B"
        _debug_log("renamed_world=World B")

        def _select_entry(title: str, label: str, entries: list[dict]) -> dict | None:
            _debug_log(f"campaign_revive_candidates={len(entries)}")
            return entries[0] if entries else None

        widget._select_trash_entry = _select_entry  # type: ignore[assignment]
        with patch.object(
            compact_nav_tree.QMessageBox,
            "information",
            lambda *args, **kwargs: _debug_log("campaign_revive_no_candidates_dialog"),
        ):
            widget._revive_campaign(0)
        _debug_log(f"after_revive_campaigns={len(widget._data[0]['campaigns'])}")

        assert [entry["name"] for entry in widget._data[0]["campaigns"]] == ["Campaign A"]
    finally:
        widget.close()


def test_revive_group_after_campaign_rename_keeps_group_recoverable() -> None:
    _debug_log("test_start=group_revive_after_campaign_rename")
    _ = QApplication.instance() or QApplication([])
    widget = _build_widget(
        [
            {
                "name": "World A",
                "campaigns": [
                    {
                        "name": "Campaign A",
                        "groups": [{"name": "Group A"}],
                    }
                ],
            }
        ]
    )
    try:
        widget._remove_group(0, 0, "Group A")
        _debug_log(f"after_remove_groups={len(widget._data[0]['campaigns'][0]['groups'])}")
        _debug_log(f"trash_parent={widget._trash[0].get('parent')}")

        widget._data[0]["campaigns"][0]["name"] = "Campaign B"
        _debug_log("renamed_campaign=Campaign B")

        def _select_entry(title: str, label: str, entries: list[dict]) -> dict | None:
            _debug_log(f"group_revive_candidates={len(entries)}")
            return entries[0] if entries else None

        widget._select_trash_entry = _select_entry  # type: ignore[assignment]
        with patch.object(
            compact_nav_tree.QMessageBox,
            "information",
            lambda *args, **kwargs: _debug_log("group_revive_no_candidates_dialog"),
        ):
            widget._revive_group(0, 0)
        _debug_log(f"after_revive_groups={len(widget._data[0]['campaigns'][0]['groups'])}")

        assert [entry["name"] for entry in widget._data[0]["campaigns"][0]["groups"]] == ["Group A"]
    finally:
        widget.close()


def test_revive_world_preserves_original_world_id() -> None:
    _debug_log("test_start=world_revive_preserves_id")
    _ = QApplication.instance() or QApplication([])
    widget = _build_widget([{"id": "world_1", "name": "World A", "campaigns": []}])
    try:
        widget._remove_world(0)
        _debug_log(f"trash_world_payload_id={widget._trash[0].get('payload', {}).get('id')}")

        def _select_entry(title: str, label: str, entries: list[dict]) -> dict | None:
            _debug_log(f"world_revive_candidates={len(entries)}")
            return entries[0] if entries else None

        widget._select_trash_entry = _select_entry  # type: ignore[assignment]
        with patch.object(compact_nav_tree.QMessageBox, "information", lambda *args, **kwargs: None):
            widget._revive_world()
        revived_id = widget._data[0].get("id") if widget._data else None
        _debug_log(f"revived_world_id={revived_id}")

        assert revived_id == "world_1"
    finally:
        widget.close()
