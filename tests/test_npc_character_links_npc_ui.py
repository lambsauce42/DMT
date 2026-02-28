import os
import sys

import pytest
from PySide6.QtWidgets import QDialog, QInputDialog, QMessageBox


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import npc_database
from npc_database import NPCDatabaseWidget, NPCEntry
from player_sheets import PlayerSheetEntry


@pytest.fixture
def npc_widget(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    monkeypatch.setattr(NPCDatabaseWidget, "_save_entries", lambda self: None)

    def _load_entries(_self):
        return [
            NPCEntry(
                id="npc_1",
                name="Guard",
                world="World A",
                campaign="Campaign A",
                group="Group A",
            )
        ]

    monkeypatch.setattr(NPCDatabaseWidget, "_load_entries", _load_entries)
    widget = NPCDatabaseWidget()
    qtbot.addWidget(widget)
    widget._npc_list.setCurrentRow(0)
    return widget


def test_npc_details_show_linked_character_field(npc_widget):
    assert npc_widget._detail_linked_character.text() == "None"


def test_npc_header_shows_linked_character_button(npc_widget, monkeypatch):
    monkeypatch.setattr(
        npc_database,
        "_character_sheet_name_map",
        lambda: {"Hero_One": "Hero One"},
    )

    npc_widget._current_entry.linked_sheet_id = "Hero_One"
    npc_widget._set_details(npc_widget._current_entry)

    assert npc_widget._header_name.text() == "NPC: Guard"
    assert [button.text() for button in npc_widget._header_links.link_buttons()] == ["Hero One"]


def test_manage_character_link_links_and_unlinks(npc_widget, monkeypatch):
    entries = [
        PlayerSheetEntry(
            name="Hero One",
            pdf_path="/tmp/hero_one.pdf",
            world="World A",
            campaign="Campaign A",
            group="Group A",
        )
    ]
    monkeypatch.setattr("npc_database.list_character_link_targets", lambda: entries)

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **kwargs: ("Hero One (Hero_One)", True),
    )
    npc_widget._manage_character_link()
    assert npc_widget._current_entry.linked_sheet_id == "Hero_One"

    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *args, **kwargs: ("None (Unlink)", True),
    )
    npc_widget._manage_character_link()
    assert npc_widget._current_entry.linked_sheet_id == ""


def test_manage_character_link_prefers_same_context_order(npc_widget, monkeypatch):
    entries = [
        PlayerSheetEntry(
            name="Far Hero",
            pdf_path="/tmp/far.pdf",
            world="World B",
            campaign="Campaign B",
            group="Group B",
        ),
        PlayerSheetEntry(
            name="Near Hero",
            pdf_path="/tmp/near.pdf",
            world="World A",
            campaign="Campaign A",
            group="Group A",
        ),
    ]
    monkeypatch.setattr("npc_database.list_character_link_targets", lambda: entries)

    captured: dict[str, list[str]] = {}

    def _capture_get_item(_parent, _title, _label, items, *_args, **_kwargs):
        captured["items"] = list(items)
        return ("None (Unlink)", False)

    monkeypatch.setattr(QInputDialog, "getItem", _capture_get_item)
    npc_widget._manage_character_link()

    assert captured["items"][0] == "None (Unlink)"
    assert "Near Hero (Near_Hero)" in captured["items"][1]
