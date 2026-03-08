import sys
import os
import pytest
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QToolButton, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, QTimer

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from item_creator import ItemCreatorWidget
from item_file_format import build_item_document, load_item_payload, write_item_document

@pytest.fixture
def item_widget(qtbot, monkeypatch, tmp_path):
    # Mock message boxes and dialogs
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "critical", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    # CRITICAL: Mock exec methods to prevent hanging dialogs
    monkeypatch.setattr(QMessageBox, "exec", lambda *args: QMessageBox.StandardButton.Yes)
    
    item_path = tmp_path / "test_item.dmtitem"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(item_path), "DMT Item"))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(item_path), "DMT Item"))

    # CRITICAL: Mock os.path.exists to avoid "File Exists" dialog logic entirely
    # We only want to test the save flow, not the overwrite confirmation
    original_exists = os.path.exists
    def mock_exists(path):
        if "test_item" in path:
            return False
        return original_exists(path)
    monkeypatch.setattr(os.path, "exists", mock_exists)

    # Mock open for save
    # We can just catch exceptions in the slot if we don't mock open
    # Writes are redirected to the test temp directory via mocked file dialogs.
    
    # PREVENT HANG: Mock update_preview to stop the recursive timer loop
    monkeypatch.setattr(ItemCreatorWidget, "update_preview", lambda self: None)
    # Also stop the singleShot in init if possible, but mocking the target method is safer/easier
    monkeypatch.setattr(QTimer, "singleShot", lambda *args: None)
    
    # Mock render_item_card to avoid actual rendering which might hang or be slow
    monkeypatch.setattr("item_creator.render_item_card", lambda *args, **kwargs: None)
    monkeypatch.setattr("item_creator.save_item_card_pdf", lambda *args, **kwargs: None)
    
    widget = ItemCreatorWidget()
    qtbot.addWidget(widget)
    return widget

def test_item_toolbar_buttons(item_widget, qtbot, monkeypatch):
    """
    Click Save, Load, Export buttons.
    """
    # Mock render check to allow save attempt
    monkeypatch.setattr(item_widget, "_current_spec", lambda: type("Spec", (), {"title": "Test", "rarity": "common", "classes": [], "stats": [], "effects": [], "flavor_text": "", "icon_path": "", "tags": [], "level": 1}))
    monkeypatch.setattr(item_widget, "_set_dirty", lambda x: None)
    
    # Mock open for save
    # We can just catch exceptions in the slot if we don't mock open
    
    # Click Save
    qtbot.mouseClick(item_widget.save_button, Qt.MouseButton.LeftButton)
    
    # Click Save As
    qtbot.mouseClick(item_widget.save_to_button, Qt.MouseButton.LeftButton)
    
    # Click Load
    qtbot.mouseClick(item_widget.load_button, Qt.MouseButton.LeftButton)
    
    # Click Export (might fail due to renderer but shouldn't crash)
    qtbot.mouseClick(item_widget.export_button, Qt.MouseButton.LeftButton)

    # Click Show Item Library
    qtbot.mouseClick(item_widget.show_library_button, Qt.MouseButton.LeftButton)

def test_item_toolbar_buttons_are_square(item_widget):
    for btn in (
        item_widget.load_button,
        item_widget.save_button,
        item_widget.save_to_button,
        item_widget.export_button,
        item_widget.show_library_button,
    ):
        assert btn.width() == btn.height()
        assert btn.width() >= 36
        style = btn.styleSheet()
        assert "padding: 4px;" in style
        assert "min-width: 36px;" in style
        assert "max-width: 36px;" in style
        assert "min-height: 36px;" in style
        assert "max-height: 36px;" in style
    assert item_widget.show_library_button.text() == ""

def test_item_stats_buttons(item_widget, qtbot):
    """
    Click Add stat button and inline remove buttons.
    """
    buttons = item_widget.findChildren(QToolButton)
    add_btn = next((b for b in buttons if b.toolTip() == "Add Stat"), None)
    
    assert add_btn is not None
    
    # Click Add
    row_count_before = item_widget.stats_table.rowCount()
    qtbot.mouseClick(add_btn, Qt.MouseButton.LeftButton)
    assert item_widget.stats_table.rowCount() == row_count_before + 1
    
    # Find the inline remove button in the last row
    last_row = item_widget.stats_table.rowCount() - 1
    container = item_widget.stats_table.cellWidget(last_row, 2)
    assert container is not None
    remove_btn = container.layout().itemAt(0).widget()
    assert remove_btn is not None
    qtbot.mouseClick(remove_btn, Qt.MouseButton.LeftButton)
    assert item_widget.stats_table.rowCount() == row_count_before

def test_click_all_item_buttons(item_widget, qtbot):
    """
    Click all buttons.
    """
    all_buttons = item_widget.findChildren(QPushButton) + item_widget.findChildren(QToolButton)
    for btn in all_buttons:
        if btn.isVisible() and btn.isEnabled():
            qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)


def test_editing_loaded_item_prompts_for_new_filename_on_title_change(item_widget, monkeypatch, tmp_path):
    item_path = tmp_path / "loaded_item.dmtitem"
    renamed_item_path = tmp_path / "healing-potion-updated.dmtitem"
    document = build_item_document({"title": "Healing Potion", "rarity": "common"}, None)
    write_item_document(item_path, document)
    initial_payload = load_item_payload(item_path)
    assert isinstance(initial_payload, dict)
    initial_item_id = str(initial_payload.get("item_id") or "")
    assert initial_item_id

    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (str(item_path), "DMT Item"))
    seen_default_paths: list[str] = []

    def _save_dialog(*args):
        seen_default_paths.append(str(args[2]))
        return (str(renamed_item_path), "DMT Item")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", _save_dialog)

    item_widget._load_item()
    item_widget.title_edit.setText("Healing Potion Updated")
    item_widget._save_item()

    original_payload = load_item_payload(item_path)
    renamed_payload = load_item_payload(renamed_item_path)
    assert isinstance(original_payload, dict)
    assert isinstance(renamed_payload, dict)
    assert original_payload["item_id"] == initial_item_id
    assert renamed_payload["item_id"] != initial_item_id
    assert renamed_payload["normalized_item_name"] == "healing potion updated"
    assert seen_default_paths == [str(renamed_item_path)]


def test_show_item_library_supports_search_category_filter_and_sort(item_widget, qtbot, tmp_path):
    first_path = tmp_path / "blade.dmtitem"
    second_path = tmp_path / "potion.dmtitem"
    third_path = tmp_path / "gem.dmtitem"
    write_item_document(
        first_path,
        build_item_document({"title": "Blade", "rarity": "rare", "tags": ["equipment"]}, None),
    )
    write_item_document(
        second_path,
        build_item_document({"title": "Potion", "rarity": "common", "tags": ["consumables"]}, None),
    )
    write_item_document(
        third_path,
        build_item_document({"title": "Gem", "rarity": "epic", "tags": ["valuables"]}, None),
    )
    item_widget._base_save_dir = str(tmp_path)

    item_widget._show_item_library()

    assert item_widget._library_dialogs
    dialog = item_widget._library_dialogs[-1]
    table = dialog._table
    assert table.item(0, 0).text() == "Blade"
    assert dialog._category_combo.currentText() == "All Categories"

    dialog._search_input.setText("pot")
    qtbot.waitUntil(lambda: table.rowCount() == 1)
    assert table.item(0, 0).text() == "Potion"

    dialog._search_input.clear()
    dialog._category_combo.setCurrentText("Valuables")
    qtbot.waitUntil(lambda: table.rowCount() == 1)
    assert table.item(0, 0).text() == "Gem"

    dialog._category_combo.setCurrentText("All Categories")
    dialog._sort_combo.setCurrentText("Category")
    qtbot.waitUntil(lambda: table.rowCount() == 3)
    assert table.item(0, 1).text() == "Consumables"
    assert table.item(0, 0).text() == "Potion"


def test_saving_existing_item_writes_new_item_version(item_widget, monkeypatch, tmp_path):
    item_path = tmp_path / "generated_item.dmtitem"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(item_path), "DMT Item"))
    item_widget._base_save_dir = str(tmp_path)

    item_widget.title_edit.setText("Fresh Potion")
    item_widget._save_item_as()

    saved_path = tmp_path / "generated_item.dmtitem"
    first_payload = load_item_payload(saved_path)
    assert isinstance(first_payload, dict)
    first_item_id = str(first_payload.get("item_id") or "")
    assert first_item_id

    item_widget.effects_edit.setPlainText("Restores HP")
    item_widget._save_item()

    second_payload = load_item_payload(saved_path)
    assert isinstance(second_payload, dict)
    assert second_payload["item_id"] != first_item_id
    assert second_payload["normalized_item_name"] == "fresh potion"
