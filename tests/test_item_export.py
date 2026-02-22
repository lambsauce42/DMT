
import os
import sys
import pytest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from item_creator import ItemCreatorWidget
from item_renderer import ItemCardSpec, save_item_card_png

def test_save_item_card_png(tmp_path):
    spec = ItemCardSpec(
        title="Test Item",
        rarity="rare",
        classes=["Weapon"],
        icon_path="",
        stats=[],
        effects=[],
        flavor_text="A test item for PNG export."
    )
    png_path = str(tmp_path / "test_item.png")
    save_item_card_png(spec, png_path)
    
    assert os.path.exists(png_path)
    # Check if it's a valid PNG (simple check for header)
    with open(png_path, "rb") as f:
        header = f.read(4)
        # Check first 4 bytes of PNG signature
        assert header == b"\x89PNG"

def test_item_creator_export_buttons_exist(qtbot):
    window = ItemCreatorWidget()
    qtbot.addWidget(window)
    
    assert hasattr(window, "export_button")
    assert window.export_button.toolTip() == "Export PDF"
    assert hasattr(window, "export_png_button")
    assert window.export_png_button.toolTip() == "Export PNG"

def test_export_pdf_respects_chosen_path(qtbot, tmp_path):
    widget = ItemCreatorWidget()
    qtbot.addWidget(widget)
    
    # Create a separate export directory
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    chosen_path = str(export_dir / "my_item.pdf")
    
    # Mock QFileDialog.getSaveFileName to return our chosen path
    with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName", return_value=(chosen_path, "PDF (*.pdf)")):
        # Mock save_item_card_pdf to avoid actual rendering but check the path
        with patch("item_creator.save_item_card_pdf") as mock_save:
            widget._export_pdf()
            
            # Assert that the path passed to save_item_card_pdf is the one we chose
            called_path = mock_save.call_args[0][1]
            assert called_path == chosen_path
            assert os.path.dirname(called_path) == str(export_dir)

def test_export_png_respects_chosen_path(qtbot, tmp_path):
    widget = ItemCreatorWidget()
    qtbot.addWidget(widget)
    
    # Create a separate export directory
    export_dir = tmp_path / "exports"
    export_dir.mkdir()
    chosen_path = str(export_dir / "my_item.png")
    
    # Mock QFileDialog.getSaveFileName to return our chosen path
    with patch("PyQt6.QtWidgets.QFileDialog.getSaveFileName", return_value=(chosen_path, "PNG (*.png)")):
        # Mock save_item_card_png to avoid actual rendering but check the path
        with patch("item_creator.save_item_card_png") as mock_save:
            widget._export_png()
            
            # Assert that the path passed to save_item_card_png is the one we chose
            called_path = mock_save.call_args[0][1]
            assert called_path == chosen_path
            assert os.path.dirname(called_path) == str(export_dir)
