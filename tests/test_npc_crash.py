import sys
import os
import pytest
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QToolButton, QMessageBox, QInputDialog, QDialog
)
from PySide6.QtCore import Qt

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

import npc_database
from npc_database import NPCDatabaseWidget, NPCEntry, NPCDialog

@pytest.fixture
def npc_widget(qtbot, monkeypatch):
    # Mock message boxes and dialogs
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Copy Name", True))
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)

    # Mock filesystem methods
    monkeypatch.setattr("npc_database.load_trash", lambda *args: [])
    monkeypatch.setattr("npc_database.save_trash", lambda *args: None)
    
    # Mock NPCManager methods implicitly by mocking load_entries
    def mock_load_entries(self):
        return [
            NPCEntry(id="npc_1", name="Test NPC", role="Tester", description="A test npc")
        ]
    
    monkeypatch.setattr(NPCDatabaseWidget, "_load_entries", mock_load_entries)
    monkeypatch.setattr(NPCDatabaseWidget, "_save_entries", lambda self: None)

    widget = NPCDatabaseWidget()
    qtbot.addWidget(widget)
    return widget

def test_npc_crud_buttons(npc_widget, qtbot):
    """
    Select an NPC and click CRUD buttons.
    """
    # Select the first item
    assert npc_widget._npc_list.count() > 0
    npc_widget._npc_list.setCurrentRow(0)
    
    # Check buttons enabled
    assert npc_widget._edit_button.isEnabled()
    
    # Click Duplicate
    qtbot.mouseClick(npc_widget._duplicate_button, Qt.MouseButton.LeftButton)
    
    # Click Edit (opens dialog, mocked to reject)
    qtbot.mouseClick(npc_widget._edit_button, Qt.MouseButton.LeftButton)
    
    # Click Save
    qtbot.mouseClick(npc_widget._save_button, Qt.MouseButton.LeftButton)
    
    # Click Delete
    qtbot.mouseClick(npc_widget._delete_button, Qt.MouseButton.LeftButton)
    
    # Select again if list not empty (delete removes it)
    if npc_widget._npc_list.count() > 0:
        npc_widget._npc_list.setCurrentRow(0)
        # Click Disintegrate
        qtbot.mouseClick(npc_widget._disintegrate_button, Qt.MouseButton.LeftButton)

def test_npc_new_button(npc_widget, qtbot):
    """
    Click New NPC button.
    """
    qtbot.mouseClick(npc_widget._new_button, Qt.MouseButton.LeftButton)

def test_npc_search_reset_button_clears_query(npc_widget, qtbot):
    npc_widget._search_input.setText("merchant")
    assert npc_widget._search_input.text() == "merchant"
    qtbot.mouseClick(npc_widget._reset_search_button, Qt.MouseButton.LeftButton)
    assert npc_widget._search_input.text() == ""

def test_npc_sort_combo_has_no_focus_artifact(npc_widget):
    assert npc_widget._sort_combo.focusPolicy() == Qt.FocusPolicy.NoFocus

def test_npc_dialog_converts_html_description_to_plain_text(qtbot):
    entry = NPCEntry(id="npc_html", name="Html NPC", description="<html><body><p><span>5235235235</span></p></body></html>")
    dialog = NPCDialog([], entry=entry)
    qtbot.addWidget(dialog)
    text = dialog._description_input.toPlainText()
    assert "5235235235" in text
    assert "<html" not in text.lower()

def test_click_all_npc_buttons(npc_widget, qtbot):
    """
    Click all visible buttons.
    """
    all_buttons = npc_widget.findChildren(QPushButton) + npc_widget.findChildren(QToolButton)
    for btn in all_buttons:
        if btn.isVisible() and btn.isEnabled():
            qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)


def _build_saveable_npc_widget(qtbot, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Copy Name", True))
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    monkeypatch.setattr("npc_database.load_trash", lambda *args: [])
    monkeypatch.setattr("npc_database.save_trash", lambda *args: None)

    def mock_load_entries(self):
        return [NPCEntry(id="npc_1", name="Test NPC", description="Original")]

    saved_payloads = []

    def mock_save(entries):
        saved_payloads.append([npc_database.entry_to_dict(entry) for entry in entries])

    monkeypatch.setattr(NPCDatabaseWidget, "_load_entries", mock_load_entries)
    monkeypatch.setattr(npc_database, "save_npc_entries_to_storage", mock_save)

    widget = NPCDatabaseWidget()
    qtbot.addWidget(widget)
    widget.show()
    widget.activateWindow()
    widget._npc_list.setCurrentRow(0)
    widget._description_text.setFocus()
    return widget, saved_payloads


def test_npc_description_edits_mark_dirty_without_autosaving(qtbot, monkeypatch):
    widget, saved_payloads = _build_saveable_npc_widget(qtbot, monkeypatch)

    assert widget._header_name.text() == "NPC: Test NPC"

    widget._description_text.setPlainText("Edited description")

    assert widget._header_name.text() == "NPC: Test NPC *"
    assert saved_payloads == []


def test_npc_save_shortcut_saves_current_description_and_clears_dirty(qtbot, monkeypatch):
    widget, saved_payloads = _build_saveable_npc_widget(qtbot, monkeypatch)

    widget._description_text.setPlainText("Edited description")
    widget._save_shortcut.activated.emit()

    assert len(saved_payloads) == 1
    assert "Edited description" in saved_payloads[0][0]["description"]
    assert widget._header_name.text() == "NPC: Test NPC"
