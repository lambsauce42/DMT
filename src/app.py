from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QSize, QTimer, QEventLoop
from PySide6.QtGui import (
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSizePolicy,
    QTabWidget,
    QTabBar,
    QTextEdit,
    QToolButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

import re

from item_creator import ItemCreatorWidget
from dungeon_applet import DungeonAppletWidget
from loot_applet import LootAppletWidget
from maps_applet import MapsWidget
from ui.widgets import TerminalWidget

from compact_nav_tree import CompactNavTree
from npc_database import NPCDatabaseWidget
from player_sheets import PlayerSheetsWidget, refresh_character_sheet_index_cache
from session_creator import SessionCreatorWidget
from save_paths import dungeon_collections_dir, clear_all_online_runtime_caches
from tab_workspace import TabWorkspaceController
from ui.encounter_panel import EncounterPanel

COLLECTION_FILE_EXTENSION = ".dmtcollection"

try:
    from PySide6.QtSvg import QSvgRenderer

    SVG_AVAILABLE = True
except Exception:  # pragma: no cover - optional SVG support
    SVG_AVAILABLE = False

# Calculate icon paths for the stylesheet
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ICON_DIR = os.path.join(_BASE_DIR, "..", "assets", "icons")
CARET_UP_PATH = os.path.join(_ICON_DIR, "caret_up_white.svg").replace("\\", "/")
CARET_DOWN_PATH = os.path.join(_ICON_DIR, "caret_down_white.svg").replace("\\", "/")
CLOSE_ICON_PATH = os.path.join(_ICON_DIR, "close.svg").replace("\\", "/")

DARK_STYLESHEET = f"""
* {{
    color: #e3e3e3;
    font-family: "Segoe UI", "Noto Sans", sans-serif;
}}
QLabel {{
    background-color: transparent;
}}
QToolTip {{
    background-color: #2b3138;
    color: #e6edf3;
    border: 1px solid #3b424b;
    padding: 4px 6px;
}}
QMainWindow {{
    background-color: #0d1117;
}}
QWidget {{
    background-color: transparent;
}}
QWidget#TransparentContainer, QWidget#FilterFieldContainer, QGroupBox#TransparentContainer {{
    background-color: transparent;
}}
QWidget#TopBar {{
    background-color: #161b22;
    border-bottom: 1px solid #30363d;
}}
QLabel#BreadcrumbLabel {{
    font-size: 13px;
    font-weight: 600;
    color: #8b949e;
    background-color: transparent;
    padding-left: 10px;
}}
QToolButton#TopBarButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 4px 12px;
    color: #8b949e;
    font-weight: 600;
    min-height: 32px;
}}
QToolButton#TopBarButton:hover {{
    color: #e6edf3;
    background-color: #21262d;
    border-color: #30363d;
}}
QToolButton#TopBarButton:pressed {{
    background-color: #161b22;
}}
QFrame#Panel {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161b22, stop:1 #0d1117);
    border: 1px solid #30363d;
    border-top: 1px solid #3d444d;
    border-radius: 8px;
}}
QFrame#PanelTransparent {{
    background-color: transparent;
    border: 1px solid #30363d;
    border-top: 1px solid #3d444d;
    border-radius: 8px;
}}
QFrame#SubPanel {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 8px;
}}
QToolButton#InventoryToggleButton {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 4px 10px;
    color: #c9d1d9;
    font-weight: 600;
    min-height: 36px;
    max-height: 36px;
}}
QToolButton#InventoryToggleButton:hover {{
    background-color: #21262d;
    border-color: #444c56;
    color: #e6edf3;
}}
QToolButton#InventoryToggleButton:checked {{
    background-color: #2d6cdf;
    border-color: #388bfd;
    color: #ffffff;
}}
QWidget#EquipmentPanel {{
    background-color: transparent;
}}
QFrame#EquipmentSlot {{
    background-color: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
}}
QFrame#EquipmentSlotInner {{
    background-color: rgba(13, 17, 23, 0.35);
    border: 1px solid #30363d;
    border-radius: 0px;
}}
QFrame#EquipmentSlotInner[selected="true"] {{
    background-color: rgba(13, 17, 23, 0.55);
    border-color: #58a6ff;
}}
QFrame#EquipmentSlotInner[dragover="true"] {{
    border-color: #3fb950;
}}
QLabel#EquipmentSlotIcon {{
    background-color: transparent;
}}
QFrame#EquipmentFigureFrame {{
    background-color: rgba(13, 17, 23, 0.2);
    border: 1px dashed #30363d;
    border-radius: 10px;
}}
QLabel#EquipmentFigure {{
    background-color: transparent;
}}
QLabel#EquipmentPreview {{
    background-color: transparent;
}}
QLabel#PanelTitle {{
    font-size: 16px;
    font-weight: 700;
    color: #e6edf3;
    background-color: transparent;
    padding-bottom: 2px;
}}
QLabel#SelectionTitle {{
    font-size: 18px;
    font-weight: 600;
    color: #e6edf3;
    background-color: transparent;
}}
QLabel#SelectionType {{
    font-size: 14px;
    font-weight: 600;
    color: #58a6ff;
    background-color: transparent;
}}
QLabel#ColumnHeader {{
    font-size: 12px;
    font-weight: 700;
    color: #8b949e;
    text-transform: uppercase;
    background-color: transparent;
    letter-spacing: 1.2px;
    border-bottom: 2px solid #30363d;
    padding-bottom: 4px;
    margin-bottom: 4px;
}}
QListWidget#NavList {{
    background-color: transparent;
    border: none;
    padding: 2px;
}}
QListWidget#NavList::item {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 10px 12px;
    margin: 4px 0px;
    color: #c9d1d9;
}}
QListWidget#NavList::item:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
    border-color: #444c56;
}}
QListWidget#NavList::item:selected {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2d6cdf, stop:1 #1c4d9b);
    color: #ffffff;
    border: 1px solid #388bfd;
}}
QListWidget#NavList::item:selected:active,
QListWidget#NavList::item:selected:!active {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2d6cdf, stop:1 #1c4d9b);
    color: #ffffff;
    border: 1px solid #388bfd;
}}
QListWidget#NavList::item:focus {{
    outline: none;
}}
QListWidget#NavList::item:selected:focus {{
    outline: none;
}}
QListWidget#IconPickerList,
QListWidget#IconSelectList {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
}}
QListWidget#IconPickerList::item:selected,
QListWidget#IconSelectList::item:selected {{
    background-color: #2d6cdf;
    color: #ffffff;
}}
QPushButton#PrimaryButton, QToolButton#PrimaryButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #238636, stop:1 #1a6329);
    border: 1px solid #2ea043;
    border-radius: 6px;
    color: #ffffff;
    padding: 6px 12px;
    min-height: 32px;
    min-width: 32px;
    font-weight: 600;
}}
QPushButton#PrimaryButton[compact="true"], QToolButton#PrimaryButton[compact="true"] {{
    padding: 4px 10px;
    min-height: 32px;
    min-width: 32px;
}}
QPushButton#PrimaryButton:hover, QToolButton#PrimaryButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2ea043, stop:1 #238636);
    border-color: #3fb950;
}}
QPushButton#DestructiveButton, QToolButton#DestructiveButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #da3633, stop:1 #890606);
    border: 1px solid #f85149;
    border-radius: 6px;
    color: #ffffff;
    padding: 6px 12px;
    min-height: 32px;
    min-width: 32px;
    font-weight: 600;
}}
QPushButton#DestructiveButton[compact="true"], QToolButton#DestructiveButton[compact="true"] {{
    padding: 4px 10px;
    min-height: 32px;
    min-width: 32px;
}}
QPushButton#DestructiveButton:hover, QToolButton#DestructiveButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f85149, stop:1 #da3633);
    border-color: #ff7b72;
}}
QPushButton#SecondaryButton, QToolButton#SecondaryButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
    border: 1px solid #3b424b;
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 32px;
}}
QPushButton#SecondaryButton[compact="true"], QToolButton#SecondaryButton[compact="true"] {{
    padding: 4px 10px;
    min-height: 32px;
    min-width: 0;
}}
QPushButton#SecondaryButton:hover, QToolButton#SecondaryButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
    border-color: #58a6ff;
}}
QPushButton#InlineResetButton, QToolButton#InlineResetButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
    border: 1px solid #3b424b;
    border-radius: 4px;
    padding: 2px;
    min-height: 24px;
    min-width: 24px;
}}
QPushButton#InlineResetButton:hover, QToolButton#InlineResetButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #30363d, stop:1 #21262d);
    border-color: #58a6ff;
}}
QPushButton#InlinePrimaryButton, QToolButton#InlinePrimaryButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #238636, stop:1 #1a6329);
    border: 1px solid #2ea043;
    border-radius: 4px;
    padding: 2px;
    min-height: 24px;
    min-width: 24px;
    color: #ffffff;
}}
QPushButton#InlinePrimaryButton:hover, QToolButton#InlinePrimaryButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2ea043, stop:1 #238636);
    border-color: #3fb950;
}}
QPushButton#InlineDestructiveButton, QToolButton#InlineDestructiveButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #da3633, stop:1 #890606);
    border: 1px solid #f85149;
    border-radius: 4px;
    padding: 2px;
    min-height: 24px;
    min-width: 24px;
    color: #ffffff;
}}
QPushButton#InlineDestructiveButton:hover, QToolButton#InlineDestructiveButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f85149, stop:1 #da3633);
    border-color: #ff7b72;
}}
QTextEdit#InfoBox {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 8px;
    color: #c9d1d9;
}}
QTextEdit#TerminalOutput {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px;
}}
QLineEdit#TerminalInput {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #e6edf3;
}}
QLabel#InfoTitle {{
    font-size: 15px;
    font-weight: 600;
    color: #c9d1d9;
    background-color: transparent;
}}
QSplitter::handle {{
    background-color: transparent;
}}
QSplitter::handle:hover {{
    background-color: #58a6ff;
}}
QScrollArea#AppletsScroll {{
    background-color: transparent;
    border: 0px;
}}
QScrollArea#AppletsScroll QWidget {{
    background-color: transparent;
}}
QScrollBar {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    width: 10px;
    margin: 0px;
    background-color: rgba(13, 17, 23, 0.6);
    border-radius: 6px;
}}
QScrollBar::handle:vertical {{
    background-color: #484f58;
    border-radius: 3px;
    min-height: 20px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: #58a6ff;
}}
QScrollBar::handle:vertical:pressed {{
    background-color: #79c0ff;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
    width: 0px;
}}
QScrollBar:horizontal {{
    height: 10px;
    margin: 0px;
    background-color: rgba(13, 17, 23, 0.6);
    border-radius: 6px;
}}
QScrollBar::handle:horizontal {{
    background-color: #484f58;
    border-radius: 3px;
    min-width: 20px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: #58a6ff;
}}
QScrollBar::handle:horizontal:pressed {{
    background-color: #79c0ff;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: transparent;
    height: 0px;
    width: 0px;
}}
QPushButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    padding: 6px 12px;
    min-height: 32px;
}}
QPushButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
    border-color: #8b949e;
}}
QPushButton:pressed {{
    background-color: #0d1117;
}}
QPushButton#LauncherButton {{
    text-align: left;
    padding: 8px 10px;
}}
QPushButton#LaunchSessionButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
    border: 1px solid #3b424b;
    border-radius: 4px;
    padding: 4px 10px;
    font-size: 12px;
    color: #c9d1d9;
}}
QPushButton#LaunchSessionButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #30363d, stop:1 #21262d);
    border-color: #58a6ff;
    color: #ffffff;
}}
QToolButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
    border: 1px solid #3b424b;
    border-radius: 6px;
    padding: 4px;
    min-height: 32px;
}}
QToolButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2b3138, stop:1 #21262d);
    border-color: #58a6ff;
}}
QToolButton:checked {{
    background-color: #2d6cdf;
    border-color: #388bfd;
}}
QLineEdit, QPlainTextEdit, QTextEdit, QTableWidget, QTableView, QComboBox, QListView, QTreeView, QAbstractItemView, QColumnView {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #c9d1d9;
    selection-background-color: #3a5a7a;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QTableWidget:focus, QTableView:focus, QComboBox:focus, QListView:focus, QTreeView:focus, QAbstractItemView:focus, QColumnView:focus {{
    outline: none;
    border: 1px solid #30363d;
}}
QListView::item:focus, QTreeView::item:focus, QAbstractItemView::item:focus {{
    outline: none;
}}
QListWidget, QTreeWidget {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
}}
QListWidget::item, QListView::item, QTreeWidget::item, QTreeView::item {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #161b22, stop:1 #0d1117);
    padding: 6px;
}}
QListWidget::item:selected, QListView::item:selected, QTreeWidget::item:selected, QTreeView::item:selected {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3a5a7a, stop:1 #2a4a6a);
}}
QListWidget#IconPickerList::item {{
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px;
}}
QListWidget#IconPickerList::item:selected {{
    border-color: #58a6ff;
    background-color: #292e36;
}}
QTableWidget::item:selected {{
    background-color: #3a5a7a;
}}
QHeaderView::section {{
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1c2128, stop:1 #0d1117);
    border: 1px solid #30363d;
    padding: 4px 6px;
    color: #8b949e;
    font-weight: 600;
}}
QComboBox::drop-down {{
    border: 0;
}}
QComboBox QAbstractItemView {{
    background-color: #161b22;
    border: 1px solid #30363d;
    selection-background-color: #3a5a7a;
}}
QGroupBox {{
    border: 1px solid #30363d;
    margin-top: 10px;
    padding: 10px;
    border-radius: 6px;
    background-color: #161b22;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    color: #8b949e;
    font-weight: 600;
}}
QLabel#Header {{
    font-size: 22px;
    font-weight: 700;
    color: #e6edf3;
    background-color: transparent;
}}
QLabel#Subheader {{
    color: #8b949e;
    background-color: transparent;
}}
QLabel#PanelPlaceholder {{
    color: #7d8590;
    background-color: transparent;
    font-style: italic;
}}
QFrame#HomeCard {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 12px;
}}
QFrame#HomeCard:hover {{
    border-color: #444c56;
    background-color: #161b22;
}}
QLabel#CardTitle {{
    font-size: 15px;
    font-weight: 700;
    color: #e6edf3;
    background-color: transparent;
}}
QLabel#CardSubtitle {{
    font-size: 13px;
    color: #8b949e;
    background-color: transparent;
}}
QLabel#CardIcon {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 12px;
}}
QFrame#HomeCard:hover QLabel#CardIcon {{
    border-color: #58a6ff;
}}

QLabel#SectionHeader {{
    font-size: 16px;
    font-weight: 700;
    color: #e6edf3;
    background-color: transparent;
}}
QFrame#SectionLine {{
    background-color: #30363d;
}}
QFrame#SectionLineDashed {{
    background-color: transparent;
    border-top: 1px dashed #30363d;
}}
QFrame#NavRow, QFrame#NavItemRow {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
    border: 1px solid #30363d;
    border-radius: 6px;
}}
QFrame#NavRow:hover, QFrame#NavItemRow:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #30363d, stop:1 #21262d);
    border-color: #444c56;
}}
QLabel#NavTitle {{
    background-color: transparent;
    font-weight: 600;
}}
QToolButton#NavActionButton {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 2px;
    margin-bottom: 2px;
    min-height: 32px;
    min-width: 32px;
}}
QToolButton#NavActionButton:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #30363d, stop:1 #21262d);
    border-color: #58a6ff;
}}
QToolButton#NavActionButton:pressed {{
    background-color: #161b22;
}}
QToolButton#NavActionButton[action="add"], QToolButton#NavActionButton[action="revive"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #238636, stop:1 #1a6329);
    border-color: #2ea043;
}}
QToolButton#NavActionButton[action="add"]:hover, QToolButton#NavActionButton[action="revive"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2ea043, stop:1 #238636);
    border-color: #3fb950;
}}
QToolButton#NavActionButton[action="delete"], QToolButton#NavActionButton[action="disintegrate"] {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #da3633, stop:1 #890606);
    border-color: #f85149;
}}
QToolButton#NavActionButton[action="delete"]:hover, QToolButton#NavActionButton[action="disintegrate"]:hover {{
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f85149, stop:1 #da3633);
    border-color: #ff7b72;
}}
QTabWidget {{
    background-color: #010409;
    border: 0px;
}}
QTabWidget::tab-bar {{
    border: 0px;
}}
QTabWidget::pane {{
    border: 1px solid #30363d;
    border-radius: 12px;
    top: -1px;
    background-color: #0d1117;
}}
QTabBar {{
    background-color: transparent;
    border: 0px;
}}
QTabBar::tab {{
    background-color: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 10px 20px;
    margin-right: 8px;
    color: transparent;
    font-weight: 600;
    font-size: 13px;
}}
QTabBar::tab:hover {{
    color: transparent;
}}
QTabBar::tab:selected {{
    color: transparent;
    border-bottom: 2px solid transparent;
}}
QTabBar::close-button {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    image: url({CLOSE_ICON_PATH});
}}
QTabBar::close-button:hover {{
    background-color: #30363d;
}}

/* PlusMinusSpinBox Styles */
QWidget#PlusMinusSpinBox {{
    background-color: transparent;
}}
QPushButton#SpinBoxButton {{
    background-color: #21262d;
    border: 1px solid #30363d;
    border-radius: 4px;
    color: #c9d1d9;
    font-weight: bold;
    font-size: 14px;
    padding: 0px;
    min-height: 32px;
    min-width: 32px;
}}
QPushButton#SpinBoxButton:hover {{
    background-color: #30363d;
    border-color: #8b949e;
    color: #ffffff;
}}
QPushButton#SpinBoxButton:pressed {{
    background-color: #161b22;
}}
QLineEdit#SpinBoxInput {{
    background-color: #0d1117;
    border-top: 1px solid #30363d;
    border-bottom: 1px solid #30363d;
    border-left: 0px;
    border-right: 0px;
    border-radius: 0px;
    color: #e6edf3;
    font-weight: 700;
    padding: 0px 4px 2px 4px;
}}
QLineEdit#SpinBoxInput:focus {{
    border-top: 1px solid #58a6ff;
    border-bottom: 1px solid #58a6ff;
}}

/* Global Styles for missing components */
QScrollArea {{
    background-color: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background-color: transparent;
}}
QScrollArea QWidget#qt_scrollarea_viewport {{
    background-color: transparent;
}}

QSpinBox, QDoubleSpinBox {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #c9d1d9;
    selection-background-color: #3a5a7a;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 20px;
    border-left: 1px solid #30363d;
    border-bottom: 0.5px solid #30363d;
    border-top-right-radius: 6px;
    background-color: #21262d;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover {{
    background-color: #30363d;
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 20px;
    border-left: 1px solid #30363d;
    border-top: 0.5px solid #30363d;
    border-bottom-right-radius: 6px;
    background-color: #21262d;
}}
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: #30363d;
}}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: url({CARET_UP_PATH});
    width: 10px;
    height: 10px;
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: url({CARET_DOWN_PATH});
    width: 10px;
    height: 10px;
}}

QCheckBox, QRadioButton {{
    color: #c9d1d9;
    spacing: 8px;
    background-color: transparent;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 4px;
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background-color: #2d6cdf;
    border-color: #388bfd;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: #58a6ff;
}}

QMenu {{
    background-color: #161b22;
    border: 1px solid #30363d;
    color: #c9d1d9;
    padding: 4px 0px;
}}
QMenu::item {{
    padding: 6px 24px;
    background-color: transparent;
}}
QMenu::item:selected {{
    background-color: #3a5a7a;
    color: #ffffff;
}}
QMenu::separator {{
    height: 1px;
    background-color: #30363d;
    margin: 4px 0px;
}}

QDialog {{
    background-color: #0d1117;
}}

QSlider::groove:horizontal {{
    border: 1px solid #30363d;
    height: 6px;
    background: #161b22;
    margin: 2px 0;
    border-radius: 3px;
}}
QSlider {{
    background-color: transparent;
}}
QSlider::handle:horizontal {{
    background: #58a6ff;
    border: 1px solid #30363d;
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover {{
    background: #79c0ff;
}}

QTreeWidget, QTreeView {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    outline: none;
}}
QTreeWidget::item, QTreeView::item {{
    padding: 6px;
    border-bottom: 1px solid #161b22;
}}
QTreeWidget::item:selected, QTreeView::item:selected {{
    background-color: #3a5a7a;
    color: #ffffff;
}}

/* Compact Navigation Tree Styling */
QTreeWidget#CompactNavTree {{
    background-color: #0d1117;
    border: 1px solid #30363d;
    border-radius: 6px;
    color: #c9d1d9;
    outline: none;
    font-size: 16px;
}}
QTreeWidget#CompactNavTree::item {{
    padding: 4px 8px;
    min-height: 40px;
    max-height: 48px;
    border-bottom: none;
}}
QTreeWidget#CompactNavTree::item:hover {{
    background-color: #21262d;
}}
QTreeWidget#CompactNavTree::item:selected {{
    background-color: transparent;
    color: #c9d1d9;
}}
QTreeWidget#CompactNavTree::branch {{
    background-color: transparent;
    border: none;
}}
QTreeWidget#CompactNavTree::branch:selected {{
    background-color: transparent;
}}
QTreeWidget#CompactNavTree::branch:has-children:!has-siblings:closed,
QTreeWidget#CompactNavTree::branch:closed:has-children:has-siblings {{
    image: url({CARET_DOWN_PATH});
}}
QTreeWidget#CompactNavTree::branch:open:has-children:!has-siblings,
QTreeWidget#CompactNavTree::branch:open:has-children:has-siblings {{
    image: url({CARET_UP_PATH});
}}
"""



class ModernDialog(QDialog):
    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(450)
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(20, 20, 20, 20)
        self._main_layout.setSpacing(15)

        self._header = QLabel(title)
        self._header.setObjectName("Header")
        self._main_layout.addWidget(self._header)

    def add_content(self, widget: QWidget) -> None:
        self._main_layout.addWidget(widget, 1)

    def add_text(self, text: str) -> None:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #c9d1d9; font-size: 14px; line-height: 1.5;")
        self._main_layout.addWidget(label)

    def add_buttons(self, buttons: List[QPushButton]) -> None:
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        for btn in buttons:
            btn_layout.addWidget(btn)
        self._main_layout.addLayout(btn_layout)


APPLET_DEFINITIONS: List[Dict[str, object]] = [
    {
        "key": "world_selector",
        "tab": "Navigate",
        "title": "Navigate",
        "subtitle": "World / Campaign / Group selector",
        "icon": "navigate.png",
        "actions": ["Add World", "Add Campaign", "Add Group"],
        "panels": ["Hierarchy", "Details"],
    },
    {
        "key": "map_library",
        "tab": "Maps",
        "title": "Maps",
        "subtitle": "Browse and link maps",
        "icon": "mapselector.png",
        "actions": ["Import Map", "Link to Campaign", "Open Image"],
        "panels": ["Map List", "Preview"],
    },
    {
        "key": "player_sheets",
        "tab": "Characters",
        "title": "Characters",
        "subtitle": "PDF folder access",
        "icon": "charactersheets.png",
        "actions": ["Open Folder", "Import Sheet", "Open Sheet"],
        "panels": ["Sheet List", "Preview"],
    },
    {
        "key": "session_creator",
        "tab": "Sessions",
        "title": "Sessions",
        "subtitle": "Launch session tooling",
        "icon": "sessioncreator.png",
        "actions": ["New Session", "Open Plan", "Attach Groups"],
        "panels": ["Session List", "Details"],
    },
    {
        "key": "dungeon_creator",
        "tab": "Dungeons",
        "title": "Dungeons",
        "subtitle": "Build dungeon assets",
        "icon": "dungeoncreator.png",
        "actions": ["New Dungeon", "Import JSON", "Open Image"],
        "panels": ["Dungeon List", "Inspector"],
    },
    {
        "key": "item_creator",
        "tab": "Item Creator",
        "title": "Item Creator",
        "subtitle": "Create item PDFs",
        "icon": "itemcreator.png",
        "actions": ["New Item", "Import PDF", "Open JSON"],
        "panels": ["Item List", "Inspector"],
    },
    {
        "key": "loot_table_generator",
        "tab": "Loot",
        "title": "Loot",
        "subtitle": "Generate loot from your item library",
        "icon": "loottablegenerator.png",
        "actions": ["Generate Loot", "Re-roll Unlocked", "Save Preset"],
        "panels": ["Settings", "Loot", "Preview"],
    },
    {
        "key": "npc_database",
        "tab": "NPCs",
        "title": "NPCs",
        "subtitle": "Browse NPC records",
        "icon": "npc_database.png",
        "actions": ["Add NPC", "Edit NPC", "Filter"],
        "panels": ["NPC List", "Details"],
    },
    {
        "key": "encounter_creator",
        "tab": "Encounters",
        "title": "Encounters",
        "subtitle": "Build encounters",
        "icon": "encountercreator.png",
        "actions": ["New Encounter", "Load Encounter", "Export"],
        "panels": ["Encounter List", "Details"],
    },
]

ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
ICON_SIZE = 101
ICON_FRAME = 8
CARD_MIN_HEIGHT = ICON_SIZE + ICON_FRAME + 24
ICON_COLOR = QColor("#c9d1d9")
TRASH_RETENTION_DAYS = 30


class PlaceholderPanel(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        layout = QVBoxLayout(self)
        label = QLabel("Empty panel")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setObjectName("PanelPlaceholder")
        layout.addWidget(label)


def _is_svg_file(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            head = handle.read(512).lower()
        return b"<svg" in head
    except Exception:
        return False


def _load_icon_pixmap(path: str, size: int) -> tuple[Optional[QPixmap], bool]:
    if not os.path.exists(path):
        return None, False
    is_svg = path.lower().endswith(".svg") or _is_svg_file(path)
    if SVG_AVAILABLE and is_svg:
        renderer = QSvgRenderer(path)
        if not renderer.isValid():
            return None, False
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return QPixmap.fromImage(image), True
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None, False
    return (
        pixmap.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ),
        is_svg,
    )


def _tint_pixmap(pixmap: QPixmap, color: QColor) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = QColor.fromRgba(image.pixel(x, y)).alpha()
            if alpha:
                image.setPixelColor(x, y, QColor(color.red(), color.green(), color.blue(), alpha))
    return QPixmap.fromImage(image)




class HomeCard(QFrame):
    def __init__(
        self,
        title: str,
        subtitle: str,
        icon_path: Optional[str],
        on_open: Callable[[bool], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._on_open = on_open
        self._icon_path = icon_path
        self._icon_cache: dict[int, QPixmap] = {}
        self.setObjectName("HomeCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        self._layout = layout

        icon_label = QLabel()
        icon_label.setFixedSize(ICON_SIZE + ICON_FRAME, ICON_SIZE + ICON_FRAME)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setObjectName("CardIcon")
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._icon_label = icon_label

        if icon_path:
            pixmap, tint = _load_icon_pixmap(icon_path, ICON_SIZE)
            if pixmap:
                if tint:
                    icon_label.setPixmap(_tint_pixmap(pixmap, ICON_COLOR))
                else:
                    icon_label.setPixmap(pixmap)
            else:
                icon_label.setText("•")

        text_group = QVBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("CardTitle")
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_label.setWordWrap(True)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("CardSubtitle")
        subtitle_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        subtitle_label.setWordWrap(True)
        text_group.addStretch(1)
        text_group.addWidget(title_label)
        text_group.addWidget(subtitle_label)
        text_group.addStretch(1)
        text_group.setSpacing(6)
        text_group.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(icon_label)
        layout.addLayout(text_group, 1)

        self.setMinimumHeight(CARD_MIN_HEIGHT)
        self._update_icon_layout()

    def _target_icon_box_size(self) -> int:
        margins = self._layout.contentsMargins()
        available_height = max(0, self.height() - margins.top() - margins.bottom())
        return available_height

    def _scaled_icon_pixmap(self, icon_size: int) -> Optional[QPixmap]:
        if not self._icon_path:
            return None
        cached = self._icon_cache.get(icon_size)
        if cached is not None:
            return cached
        pixmap, tint = _load_icon_pixmap(self._icon_path, icon_size)
        if not pixmap:
            return None
        if tint:
            pixmap = _tint_pixmap(pixmap, ICON_COLOR)
        self._icon_cache[icon_size] = pixmap
        return pixmap

    def _update_icon_layout(self) -> None:
        box_size = self._target_icon_box_size()
        if box_size <= 0:
            return
        self._icon_label.setFixedSize(box_size, box_size)

        if not self._icon_path:
            return

        # Keep icon very close to the frame edge while preserving a small inset.
        inset = max(3, int(round(box_size * 0.045)))
        icon_size = max(12, box_size - (2 * inset))
        pixmap = self._scaled_icon_pixmap(icon_size)
        if pixmap is None:
            self._icon_label.setText("*")
            self._icon_label.setPixmap(QPixmap())
            return
        self._icon_label.setText("")
        self._icon_label.setPixmap(pixmap)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(False)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(True)
        super().mouseDoubleClickEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_icon_layout()




class AppletWidget(QWidget):
    def __init__(self, title: str, actions: List[str], panels: List[str], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(720, 480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel(title)
        header.setObjectName("Header")
        subheader = QLabel("Scaffold only - functionality to be implemented.")
        subheader.setObjectName("Subheader")
        layout.addWidget(header)
        layout.addWidget(subheader)

        action_row = QHBoxLayout()
        for action in actions:
            button = QPushButton(action)
            button.clicked.connect(
                lambda checked=False, name=action: self.show_placeholder(name)
            )
            action_row.addWidget(button)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        panel_row = QHBoxLayout()
        for panel_title in panels:
            panel_row.addWidget(PlaceholderPanel(panel_title))
        layout.addLayout(panel_row)

    def show_placeholder(self, action: str) -> None:
        QMessageBox.information(self, "Placeholder", f"{action} is not implemented yet.")


class CircularLoadingSpinner(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._angle = 0
        self.setFixedSize(18, 18)
        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._advance)
        self._timer.stop()

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        if self._timer.isActive():
            self._timer.stop()

    def _advance(self) -> None:
        self._angle = (self._angle + 24) % 360
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#58a6ff"))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        arc_rect = self.rect().adjusted(2, 2, -2, -2)
        painter.drawArc(arc_rect, int(-self._angle * 16), int(120 * 16))


class AppletLoadingOverlay(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background-color: rgba(13, 17, 23, 120);")

        self._card = QFrame(self)
        self._card.setStyleSheet(
            """
            QFrame {
                background-color: rgba(22, 27, 34, 230);
                border: 1px solid #3b424b;
                border-radius: 10px;
            }
            """
        )
        card_layout = QHBoxLayout(self._card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(8)

        self._spinner = CircularLoadingSpinner(self._card)
        self._label = QLabel("Loading applet...", self._card)
        self._label.setStyleSheet("color: #c9d1d9; font-size: 12px; font-weight: 500;")
        card_layout.addWidget(self._spinner)
        card_layout.addWidget(self._label)

    def start_animation(self) -> None:
        self._spinner.start()

    def stop_animation(self) -> None:
        self._spinner.stop()

    def set_message(self, message: str) -> None:
        self._label.setText(str(message or "Loading applet..."))
        self._label.adjustSize()
        self._card.adjustSize()
        self._position_card()

    def _position_card(self) -> None:
        card_size = self._card.sizeHint()
        x = max(0, (self.width() - card_size.width()) // 2)
        y = max(0, (self.height() - card_size.height()) // 2)
        self._card.setGeometry(x, y, card_size.width(), card_size.height())

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_card()


def build_applet_widget(parent: QWidget, key: str, applet: Dict[str, object]) -> Optional[QWidget]:
    if str(key).startswith("online_host::"):
        widget = DungeonAppletWidget(parent)
        online_cfg = applet.get("online", {}) if isinstance(applet.get("online"), dict) else {}
        port = int(online_cfg.get("port", 8765))
        collection_path = str(online_cfg.get("collection_path") or "").strip()
        started = widget.start_online_host(port, collection_path or None)
        if not started:
            widget.deleteLater()
            return None
        return widget
    if str(key).startswith("online_join::"):
        widget = DungeonAppletWidget(parent)
        online_cfg = applet.get("online", {}) if isinstance(applet.get("online"), dict) else {}
        host_ip = str(online_cfg.get("host_ip") or "").strip()
        port = int(online_cfg.get("port", 8765))
        player_name = str(online_cfg.get("player_name") or "Player").strip() or "Player"
        widget.join_online_session(host_ip, port, player_name)
        return widget
    if key == "item_creator":
        return ItemCreatorWidget(parent)
    if key == "map_library":
        return MapsWidget(parent)
    if key == "player_sheets":
        return PlayerSheetsWidget(parent)
    if key == "session_creator":
        return SessionCreatorWidget(parent)
    if key == "loot_table_generator":
        return LootAppletWidget(parent)
    if key == "npc_database":
        return NPCDatabaseWidget(parent)
    if key == "encounter_creator":
        return EncounterPanel(parent)
    if key == "dungeon_creator":
        return DungeonAppletWidget(parent)
    return AppletWidget(
        applet["title"],
        applet["actions"],
        applet["panels"],
        parent,
    )


class _WorkspaceTabWindow(QMainWindow):
    def __init__(self, workspace_controller: TabWorkspaceController, *, primary: bool, title: str) -> None:
        super().__init__()
        self._workspace_controller = workspace_controller
        self._workspace_primary = bool(primary)
        self.setWindowTitle(title)
        self.setMinimumSize(1200, 700)

        self.tabs = QTabWidget(self)
        self.tabs.setDocumentMode(False)
        self.setCentralWidget(self.tabs)

        self._loading_overlay = AppletLoadingOverlay(self.tabs)
        self._loading_overlay.setGeometry(self.tabs.rect())
        self._loading_overlay.hide()

        self._workspace_controller.register_window(self, primary=self._workspace_primary)
        self._tab_by_key = self._workspace_controller.tab_by_key
        self._loading_tabs = self._workspace_controller.loading_keys

    def workspace_tabs(self) -> QTabWidget:
        return self.tabs

    def is_primary_window(self) -> bool:
        return self._workspace_primary

    def _disable_tab_close(self, index: int) -> None:
        bar = self.tabs.tabBar()
        bar.setTabButton(index, QTabBar.ButtonPosition.RightSide, None)
        bar.setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.setGeometry(self.tabs.rect())
        if hasattr(self, "_workspace_controller"):
            self._workspace_controller.sync_tab_bar_extent(self)

    def _show_applet_loading_overlay(self, message: str) -> None:
        self._loading_overlay.setGeometry(self.tabs.rect())
        self._loading_overlay.set_message(message)
        self._loading_overlay.start_animation()
        self._loading_overlay.show()
        self._loading_overlay.raise_()

    def _hide_applet_loading_overlay(self) -> None:
        self._loading_overlay.stop_animation()
        self._loading_overlay.hide()

    def _warmup_loading_overlay(self, *, frames: int = 2, frame_ms: int = 75) -> None:
        target_frames = max(0, int(frames))
        delay_ms = max(1, int(frame_ms))
        for _ in range(target_frames):
            QApplication.processEvents()
            loop = QEventLoop(self)
            QTimer.singleShot(delay_ms, loop.quit)
            loop.exec()

    def _build_applet_widget(self, key: str, applet: Dict[str, object]) -> Optional[QWidget]:
        return build_applet_widget(self.tabs, key, applet)

    def open_applet(self, applet: Dict[str, object], focus_if_new: bool = True) -> None:
        self._workspace_controller.open_applet(self, applet, focus_if_new=focus_if_new)

    def _close_tab(self, index: int) -> None:
        self._workspace_controller.close_tab_by_index(self, index)


class DetachedTabWindow(_WorkspaceTabWindow):
    def __init__(self, workspace_controller: TabWorkspaceController) -> None:
        super().__init__(
            workspace_controller,
            primary=False,
            title="AIO-Hub | Detached Tabs",
        )

    def closeEvent(self, event) -> None:
        self._workspace_controller.prepare_window_close(self)
        self._workspace_controller.unregister_window(self)
        super().closeEvent(event)


class MainLauncherWindow(_WorkspaceTabWindow):
    def __init__(self) -> None:
        self._workspace_controller = TabWorkspaceController()
        super().__init__(
            self._workspace_controller,
            primary=True,
            title="AIO-Hub | D&D Management Toolkit",
        )
        self._workspace_controller.set_detached_window_factory(
            lambda: DetachedTabWindow(self._workspace_controller)
        )
        home = HomeWidget(APPLET_DEFINITIONS, self.open_applet)
        self._home = home
        home_index = self.tabs.addTab(home, "Home")
        self._disable_tab_close(home_index)
        self._workspace_controller.set_home_widget(home)
        self.tabs.setCurrentIndex(0)

    def closeEvent(self, event) -> None:
        self._workspace_controller.begin_primary_shutdown(self)
        self._workspace_controller.prepare_window_close(self)
        self._workspace_controller.unregister_window(self)
        clear_all_online_runtime_caches()
        super().closeEvent(event)


class HomeWidget(QWidget):
    def __init__(
        self,
        applets: List[Dict[str, object]],
        on_open: Callable[[Dict[str, object], bool], None],
        world_data: Optional[list[dict]] = None,
        trash_path: Optional[Path] = None,
    ) -> None:
        super().__init__()
        self._on_open = on_open
        self._breadcrumbs_text = "Navigation"

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        top_bar = QWidget(self)
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(10, 8, 10, 8)
        top_layout.setSpacing(10)

        online_cluster = QWidget(top_bar)
        online_actions_layout = QHBoxLayout(online_cluster)
        online_actions_layout.setContentsMargins(0, 0, 0, 0)
        online_actions_layout.setSpacing(6)

        self._host_collection_btn = QPushButton("Host Session", online_cluster)
        self._host_collection_btn.setObjectName("PrimaryButton")
        self._host_collection_btn.setFixedWidth(140)
        self._host_collection_btn.setProperty("compact", True)
        self._host_collection_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._host_collection_btn.clicked.connect(self._host_dungeon_collection)
        online_actions_layout.addWidget(self._host_collection_btn)

        self._join_ip_btn = QPushButton("Join Session", online_cluster)
        self._join_ip_btn.setObjectName("SecondaryButton")
        self._join_ip_btn.setFixedWidth(140)
        self._join_ip_btn.setProperty("compact", True)
        self._join_ip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._join_ip_btn.clicked.connect(self._join_dungeon_by_ip)
        online_actions_layout.addWidget(self._join_ip_btn)
        top_layout.addWidget(
            online_cluster,
            0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

        self._breadcrumbs_label = QLabel(top_bar)
        self._breadcrumbs_label.setObjectName("BreadcrumbLabel")
        self._breadcrumbs_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._breadcrumbs_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        top_layout.addWidget(self._breadcrumbs_label, 1)

        settings_cluster = QWidget(top_bar)
        settings_layout = QHBoxLayout(settings_cluster)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(4)
        self._settings_button = QToolButton(settings_cluster)
        self._settings_button.setObjectName("TopBarButton")
        self._settings_button.setText("Settings")
        self._settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_button.clicked.connect(self._show_settings)

        self._about_button = QToolButton(settings_cluster)
        self._about_button.setObjectName("TopBarButton")
        self._about_button.setText("About")
        self._about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._about_button.clicked.connect(self._show_about)

        # Add a subtle separator between buttons
        sep = QLabel("|", settings_cluster)
        sep.setStyleSheet("color: #30363d; font-weight: bold; margin: 0 4px;")

        settings_layout.addWidget(self._settings_button)
        settings_layout.addWidget(sep)
        settings_layout.addWidget(self._about_button)
        top_layout.addWidget(settings_cluster, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        main_layout.addWidget(top_bar)

        # Main content: horizontal layout with applets on left, nav+terminal column on right
        main_content = QWidget(self)
        main_content.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        main_content_layout = QHBoxLayout(main_content)
        main_content_layout.setContentsMargins(0, 0, 0, 0)
        main_content_layout.setSpacing(10)

        # Applets panel (left side - takes most space, full height)
        applets_panel = QFrame(main_content)
        applets_panel.setObjectName("Panel")
        applets_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        applets_layout = QVBoxLayout(applets_panel)
        applets_layout.setContentsMargins(10, 10, 10, 10)
        applets_layout.setSpacing(8)
        self._applets_panel = applets_panel

        applets_title = QLabel("Applets", applets_panel)
        applets_title.setObjectName("PanelTitle")
        applets_layout.addWidget(applets_title)

        # Grid container for applet cards (no scroll - cards expand to fill)
        grid_container = QWidget(applets_panel)
        grid_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._grid_layout = QGridLayout(grid_container)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setHorizontalSpacing(12)
        self._grid_layout.setVerticalSpacing(12)

        self._applet_cards = []
        applet_defs = [
            applet for applet in applets if applet.get("key") != "world_selector"
        ][:8]
        for applet in applet_defs:
            icon_name = applet.get("icon")
            icon_path = (
                os.path.join(ICON_DIR, icon_name) if icon_name else None
            )
            card = HomeCard(
                applet["title"],
                applet["subtitle"],
                icon_path,
                on_open=lambda focus, info=applet: on_open(info, focus),
                parent=grid_container,
            )
            # Cards expand both horizontally and vertically to fill available space
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self._applet_cards.append(card)

        self._current_columns = 2
        self._layout_applets(self._current_columns)

        applets_layout.addWidget(grid_container, 1)

        # Right column: navigation panel (top) + terminal panel (bottom)
        right_column = QWidget(main_content)
        right_column.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_column_layout = QVBoxLayout(right_column)
        right_column_layout.setContentsMargins(0, 0, 0, 0)
        right_column_layout.setSpacing(10)

        # Navigation panel (top of right column)
        nav_panel = QFrame(right_column)
        nav_panel.setObjectName("Panel")
        nav_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(10, 10, 10, 10)
        nav_layout.setSpacing(8)
        self._nav_panel = nav_panel

        nav_title = QLabel("Navigation", nav_panel)
        nav_title.setObjectName("PanelTitle")
        nav_layout.addWidget(nav_title)

        # Compact hierarchical tree navigation
        self._compact_nav_tree = CompactNavTree(nav_panel)
        nav_layout.addWidget(self._compact_nav_tree, 1)

        right_column_layout.addWidget(nav_panel, 4)  # Nav takes 4 parts

        # Terminal panel (bottom of right column, slightly taller)
        self._right_free_panel = QFrame(right_column)
        self._right_free_panel.setObjectName("Panel")
        self._right_free_panel.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._build_terminal_panel()

        right_column_layout.addWidget(self._right_free_panel, 5)  # Terminal takes 5 parts (slightly taller)

        main_content_layout.addWidget(applets_panel, 1)  # Applets take all remaining space
        main_content_layout.addWidget(right_column)  # Right column has fixed width
        main_content_layout.setStretch(0, 2)
        main_content_layout.setStretch(1, 1)
        main_layout.addWidget(main_content, 1)
        main_layout.setStretch(1, 1)

        self._set_breadcrumbs(["Navigation"])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_bottom_panel_sizes()

    def _build_terminal_panel(self) -> None:
        layout = QVBoxLayout(self._right_free_panel)
        layout.setContentsMargins(10, 10, 10, 10)
        self._terminal = TerminalWidget()
        layout.addWidget(self._terminal)

    def _set_breadcrumbs(self, parts: List[str]) -> None:
        cleaned = [part for part in parts if part]
        if cleaned and cleaned[0].lower() == "navigation":
            cleaned = cleaned[1:] if len(cleaned) > 1 else []
        self._breadcrumbs_text = " / ".join(cleaned)
        self._update_breadcrumbs()

    def _update_breadcrumbs(self) -> None:
        metrics = self._breadcrumbs_label.fontMetrics()
        width = max(0, self._breadcrumbs_label.width())
        if width:
            text = metrics.elidedText(
                self._breadcrumbs_text,
                Qt.TextElideMode.ElideRight,
                width,
            )
        else:
            text = self._breadcrumbs_text
        self._breadcrumbs_label.setText(text)

    def _sync_bottom_panel_sizes(self) -> None:
        # Responsive applet grid
        if hasattr(self, "_applets_panel") and hasattr(self, "_grid_layout"):
            available_width = self._applets_panel.width()
            if available_width > 40:  # Avoid layout noise during init
                new_columns = 1 if available_width < 540 else 2
                if new_columns != self._current_columns:
                    self._current_columns = new_columns
                    self._layout_applets(new_columns)

    def _layout_applets(self, columns: int) -> None:
        # Clear existing layout
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().hide()  # Keep it but hide to avoid flicker or issues

        # Reset old stretch values so removed rows/columns stop consuming space.
        for row in range(self._grid_layout.rowCount()):
            self._grid_layout.setRowStretch(row, 0)
        for col in range(self._grid_layout.columnCount()):
            self._grid_layout.setColumnStretch(col, 0)
        
        # Re-add to grid
        num_rows = 0
        for index, card in enumerate(self._applet_cards):
            row = index // columns
            col = index % columns
            self._grid_layout.addWidget(card, row, col)
            card.show()
            num_rows = max(num_rows, row + 1)

        # Set column stretches
        for col in range(max(columns, 2)):
            self._grid_layout.setColumnStretch(col, 1 if col < columns else 0)
        
        # Set row stretches so cards expand vertically
        for row in range(num_rows):
            self._grid_layout.setRowStretch(row, 1)

    def _host_dungeon_collection(self) -> None:
        base_dir = dungeon_collections_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Dungeon Collection",
            str(base_dir),
            f"Dungeon Collection (*{COLLECTION_FILE_EXTENSION})",
        )
        if not filename:
            return
        port, ok = QInputDialog.getInt(
            self,
            "Host Port",
            "Port:",
            8765,
            1024,
            65535,
            1,
        )
        if not ok:
            return
        collection_name = Path(filename).stem or "Collection"
        key = f"online_host::{port}::{collection_name}::{int(datetime.now().timestamp())}"
        applet = {
            "key": key,
            "tab": f"Host: {collection_name}",
            "title": "Online Host",
            "subtitle": f"Port {port}",
            "actions": [],
            "panels": [],
            "online": {
                "port": int(port),
                "collection_path": filename,
            },
        }
        self._on_open(applet, True)

    def _join_dungeon_by_ip(self) -> None:
        host_ip, ok = QInputDialog.getText(
            self,
            "Join by IP",
            "Host IP:",
            text="127.0.0.1",
        )
        if not ok:
            return
        host_ip = host_ip.strip()
        if not host_ip:
            QMessageBox.warning(self, "Join by IP", "Host IP is required.")
            return
        port, ok = QInputDialog.getInt(
            self,
            "Join by IP",
            "Port:",
            8765,
            1,
            65535,
            1,
        )
        if not ok:
            return
        default_name = "Player"
        player_name, ok = QInputDialog.getText(
            self,
            "Join by IP",
            "Player Name:",
            text=default_name,
        )
        if not ok:
            return
        player_name = player_name.strip()
        if not player_name:
            QMessageBox.warning(self, "Join by IP", "Player name is required.")
            return
        key = f"online_join::{host_ip}:{port}::{player_name}::{int(datetime.now().timestamp())}"
        applet = {
            "key": key,
            "tab": f"Join: {player_name}",
            "title": "Online Player",
            "subtitle": f"{host_ip}:{port}",
            "actions": [],
            "panels": [],
            "online": {
                "host_ip": host_ip,
                "port": int(port),
                "player_name": player_name,
            },
        }
        self._on_open(applet, True)

    def _show_settings(self) -> None:
        dialog = ModernDialog("Settings", self)
        dialog.add_text("Configure your AIO-Hub and DMT experience.")

        # Placeholder for settings content
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        label = QLabel("Settings panel is not implemented yet.")
        label.setStyleSheet("color: #8b949e; font-style: italic;")
        content_layout.addWidget(label)
        dialog.add_content(content)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryButton")
        close_btn.clicked.connect(dialog.accept)
        dialog.add_buttons([close_btn])
        dialog.exec()

    def _show_about(self) -> None:
        dialog = ModernDialog("About D&D Management Toolkit", self)
        dialog.add_text(
            "A comprehensive suite for Dungeon Masters and players, integrated into the AIO-Hub platform."
        )

        message = (
            "Character Sheets use PDFium via pypdfium2 for interactive AcroForms.\n\n"
            "Licenses: See THIRD_PARTY_NOTICES/ in the app folder.\n\n"
            "Limitations: XFA and JavaScript-driven PDFs require a V8-enabled PDFium build."
        )
        dialog.add_text(message)

        ok_btn = QPushButton("Done")
        ok_btn.setObjectName("PrimaryButton")
        ok_btn.clicked.connect(dialog.accept)
        dialog.add_buttons([ok_btn])
        dialog.exec()

    def open_navigate(self) -> None:
        if hasattr(self, "_compact_nav_tree"):
            self._compact_nav_tree.setFocus()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_breadcrumbs()
        self._sync_bottom_panel_sizes()


def main() -> int:

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    clear_all_online_runtime_caches()
    try:
        refresh_character_sheet_index_cache()
    except Exception:
        pass
    app = QApplication(sys.argv)
    app.setApplicationName("DnD-AAT")
    app.setStyleSheet(DARK_STYLESHEET)
    window = MainLauncherWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
