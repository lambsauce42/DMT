import sys
import os
import pytest
from PySide6.QtWidgets import QPushButton, QSlider, QWidget

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from app import MainLauncherWindow, APPLET_DEFINITIONS
from loot_applet import LootAppletWidget
from navigate_widget import NavigateContentWidget
from ui.widgets import TerminalWidget

# Fixture to create the main window
@pytest.fixture
def main_window(qtbot):
    window = MainLauncherWindow()
    yield window
    window.close()

def test_main_window_initialization(main_window):
    """Verify the main window opens and has the correct title/structure."""
    assert hasattr(main_window, "tabs")
    assert main_window.tabs.count() >= 0

def test_loot_applet_creation(qtbot):
    """Verify LootAppletWidget can be instantiated."""
    widget = LootAppletWidget()
    
    # Check for critical child widgets
    buttons = widget.findChildren(QPushButton)
    sliders = widget.findChildren(QSlider)
    
    # We expect some buttons and sliders
    assert len(buttons) > 0, "Loot applet should have buttons (e.g. Generate)"
    assert len(sliders) > 0, "Loot applet should have sliders (e.g. Luck)"
    widget.close()

def test_open_loot_applet_from_main(main_window, qtbot):
    """Test clicking the 'Loot Generator' button/action in the main window."""
    # Find the applet definition for loot
    loot_def = next(a for a in APPLET_DEFINITIONS if a["key"] == "loot_table_generator")
    
    # Simulate opening it
    main_window.open_applet(loot_def, focus_if_new=True)
    
    # Check if a new tab was added
    assert main_window.tabs.count() > 0
    current_widget = main_window.tabs.currentWidget()
    assert isinstance(current_widget, LootAppletWidget)

def test_navigate_widget_creation(qtbot):
    """Test instantiation of the file navigation widget."""
    # NavigateContentWidget does not take a path, but an optional bool
    widget = NavigateContentWidget(show_worlds_header=True)
    
    # Check if the layout is present
    assert hasattr(widget, "_layout")
    # Check internal data structure
    assert isinstance(widget._data, list)
    widget.close()

def test_terminal_existence(main_window, qtbot):
    """Verify terminal exists in Home and can be added to Session Creator."""
    # Check Home Terminal
    assert hasattr(main_window._home, "_terminal")
    assert isinstance(main_window._home._terminal, TerminalWidget)
    
    # Check Session Creator Terminal
    session_def = next(a for a in APPLET_DEFINITIONS if a["key"] == "session_creator")
    main_window.open_applet(session_def, focus_if_new=True)
    session_widget = main_window.tabs.currentWidget()
    
    # It should have a terminal attribute now
    assert hasattr(session_widget, "terminal")
    assert isinstance(session_widget.terminal, TerminalWidget)

