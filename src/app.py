from __future__ import annotations

import copy
import json
import os
import traceback
import sys
import faulthandler
import threading
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import Qt, QSize, QTimer, Signal
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
    QCheckBox,
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
)

import re

from asset_paths import asset_path, icon_path, icons_dir, is_frozen_app, resource_path
from item_creator import ItemCreatorWidget
from bundled_data import cleanup_current_bundled_runtime_data, cleanup_stale_bundled_runtime_data
from dungeon_applet import DungeonAppletWidget
from loot_applet import LootAppletWidget
from maps_applet import MapsWidget, load_map_entries_from_storage
from ui.widgets import TerminalWidget

from compact_nav_tree import CompactNavTree
from navigation_repository import load_navigation_data
from npc_database import NPCDatabaseWidget
from player_sheets import (
    PlayerSheetsWidget,
    load_entries_from_storage,
    refresh_character_sheet_index_cache,
)
from session_creator import SessionCreatorWidget, SessionManager, _navigation_world_data
from save_paths import (
    dungeon_collections_dir,
    clear_all_disposable_caches,
    clear_all_online_runtime_caches,
    dnd_saves_dir,
    default_dnd_save_dir,
)
from online_logging import append_active_online_session_crash_event, is_runtime_logging_enabled
from tab_workspace import TabWorkspaceController, WorkspaceTabsHost
from ui.encounter_panel import EncounterPanel
from user_settings import (
    get_or_create_local_player_id,
    is_ctrl_mouse_wheel_zoom_enabled,
    load_app_settings,
    save_app_settings,
)

COLLECTION_FILE_EXTENSION = ".dmtcollection"
ONLINE_LAUNCH_LOG_FILENAME = "dmt_online_launch.log"
APP_CRASH_LOG_FILENAME = "dmt_app_crash.log"
LOCAL_DUNGEON_PROFILE_FILENAME = "dungeon_profile.json"
_CRASH_LOG_HANDLE: Optional[object] = None
_CRASH_LOG_INSTANCE_PATH: Optional[Path] = None
_ORIGINAL_SYS_EXCEPTHOOK = sys.excepthook
_ORIGINAL_THREADING_EXCEPTHOOK = getattr(threading, "excepthook", None)

try:
    from PySide6.QtSvg import QSvgRenderer

    SVG_AVAILABLE = True
except Exception:  # pragma: no cover - optional SVG support
    SVG_AVAILABLE = False

# Calculate icon paths for the stylesheet
_ICON_DIR = str(icons_dir())
CARET_UP_PATH = str(icon_path("caret_up_white.svg")).replace("\\", "/")
CARET_DOWN_PATH = str(icon_path("caret_down_white.svg")).replace("\\", "/")
CLOSE_ICON_PATH = str(icon_path("close.svg")).replace("\\", "/")
APP_ICON_PATH = asset_path("DMT.png")

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
QWidget#WorkspaceTabHost {{
    background-color: #010409;
    border: 0px;
}}
QWidget#WorkspaceTabStrip {{
    background-color: transparent;
    border: 0px;
}}
QWidget#WorkspaceTabStack {{
    border: 1px solid #30363d;
    border-radius: 12px;
    background-color: #0d1117;
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
        "tab": "Items",
        "title": "Items",
        "subtitle": "Create and browse items",
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

ICON_DIR = str(icons_dir())
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
            self._on_open(True)
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

    def show_loading(self, message: str) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.set_message(message)
        self.start_animation()
        self.show()
        self.raise_()
        self._paint_now()

    def hide_loading(self) -> None:
        self.stop_animation()
        self.hide()

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

    def _paint_now(self) -> None:
        self._card.repaint()
        self.repaint()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._position_card()


def _async_applet_loading_enabled() -> bool:
    if os.environ.get("DMT_TEST_MODE") == "1":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if "pytest" in sys.modules:
        return False
    return True


def _external_loading_indicator_enabled() -> bool:
    if is_frozen_app():
        return False
    if os.environ.get("DMT_DISABLE_EXTERNAL_LOADING_INDICATOR") == "1":
        return False
    if os.environ.get("DMT_TEST_EXTERNAL_LOADING_INDICATOR") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return "pytest" not in sys.modules


class ExternalLoadingIndicatorController:
    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen[bytes]] = None

    def show(self, host: QWidget, message: str) -> bool:
        if not _external_loading_indicator_enabled():
            return False
        helper_path = resource_path("loading_indicator_process.py")
        if not helper_path.exists():
            print(f"[WARN] Loading indicator helper missing: {helper_path}", file=sys.stderr)
            return False
        self.hide()
        global_top_left = host.mapToGlobal(host.rect().topLeft())
        rect = host.rect()
        cmd = [
            sys.executable,
            str(helper_path),
            "--message",
            str(message or "Loading applet..."),
            "--x",
            str(int(global_top_left.x())),
            "--y",
            str(int(global_top_left.y())),
            "--width",
            str(max(1, int(rect.width()))),
            "--height",
            str(max(1, int(rect.height()))),
        ]
        heartbeat_path = os.environ.get("DMT_LOADING_INDICATOR_HEARTBEAT_PATH", "").strip()
        if heartbeat_path:
            cmd.extend(["--heartbeat-path", heartbeat_path])
        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            self._process = None
            print(f"[WARN] Failed to launch external loading indicator: {exc}", file=sys.stderr)
            return False
        return True

    def hide(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


def _safe_navigation_world_data() -> list[dict]:
    loaded = load_navigation_data()
    return list(loaded) if isinstance(loaded, list) else []


class DeferredAppletHost(QWidget):
    _load_finished = Signal(object, str)
    appletReady = Signal()
    appletFailed = Signal(str)
    appletStatusChanged = Signal(str)

    def __init__(
        self,
        title: str,
        load_fn: Callable[[], object],
        build_fn: Callable[[QWidget, object], QWidget],
        parent: Optional[QWidget] = None,
        *,
        use_internal_overlay: bool = True,
    ) -> None:
        super().__init__(parent)
        self._title = str(title or "Applet")
        self._load_fn = load_fn
        self._build_fn = build_fn
        self._closed = False
        self._ready_emitted = False
        self._inner_widget: Optional[QWidget] = None
        self._startup_connected = False
        self._overlay: Optional[AppletLoadingOverlay] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._layout = layout

        self._content_root = QWidget(self)
        self._content_layout = QVBoxLayout(self._content_root)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        layout.addWidget(self._content_root, 1)

        if use_internal_overlay:
            self._overlay = AppletLoadingOverlay(self)
            self._overlay.show_loading(f"Loading {self._title}...")

        self._load_finished.connect(self._on_load_finished)
        self._loader_thread = threading.Thread(
            target=self._run_loader,
            name=f"dmt-load-{self._title.lower().replace(' ', '-')}",
            daemon=True,
        )
        self._loader_thread.start()

    def is_loading(self) -> bool:
        return (not self._closed) and (not self._ready_emitted)

    def _run_loader(self) -> None:
        try:
            payload = self._load_fn()
        except Exception:
            if self._closed:
                return
            self._load_finished.emit(None, traceback.format_exc())
            return
        if self._closed:
            return
        self._load_finished.emit(payload, "")

    def _on_load_finished(self, payload: object, error_text: str) -> None:
        if self._closed:
            return
        if error_text:
            self._set_status_message("Failed to load applet.")
            print(
                f"[WARN] Deferred applet load failed for {self._title}: {error_text}",
                file=sys.stderr,
            )
            QMessageBox.warning(
                self,
                f"{self._title} Load Failed",
                "The applet could not be prepared. See terminal output for details.",
            )
            self.appletFailed.emit(error_text)
            return
        self._set_status_message("Building interface...")
        QTimer.singleShot(0, lambda payload=payload: self._build_loaded_widget(payload))

    def _build_loaded_widget(self, payload: object) -> None:
        if self._closed:
            return
        try:
            widget = self._build_fn(self, payload)
        except Exception:
            self._set_status_message("Failed to build applet.")
            error_text = traceback.format_exc()
            print(f"[WARN] Deferred applet build failed for {self._title}: {error_text}", file=sys.stderr)
            QMessageBox.warning(
                self,
                f"{self._title} Build Failed",
                "The applet UI could not be created. See terminal output for details.",
            )
            self.appletFailed.emit(error_text)
            return
        self._inner_widget = widget
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            child_widget = item.widget()
            if child_widget is not None:
                child_widget.deleteLater()
        self._content_layout.addWidget(widget, 1)
        self._attach_widget_startup(widget)
        self._start_widget_startup(widget)
        if not self._widget_startup_in_progress(widget):
            self._finish_ready()

    def _attach_widget_startup(self, widget: QWidget) -> None:
        if self._startup_connected:
            return
        finished_signal = getattr(widget, "startupFinished", None)
        if finished_signal is not None and hasattr(finished_signal, "connect"):
            finished_signal.connect(self._finish_ready)
        status_signal = getattr(widget, "startupStatusChanged", None)
        if status_signal is not None and hasattr(status_signal, "connect"):
            status_signal.connect(self._set_status_message)
        failed_signal = getattr(widget, "startupFailed", None)
        if failed_signal is not None and hasattr(failed_signal, "connect"):
            failed_signal.connect(self._on_widget_startup_failed)
        self._startup_connected = True

    def _start_widget_startup(self, widget: QWidget) -> None:
        begin_startup = getattr(widget, "begin_startup", None)
        if not callable(begin_startup):
            return
        try:
            begin_startup()
        except Exception:
            self._on_widget_startup_failed(traceback.format_exc())

    def _widget_startup_in_progress(self, widget: QWidget) -> bool:
        startup_pending = getattr(widget, "startup_in_progress", None)
        if callable(startup_pending):
            try:
                return bool(startup_pending())
            except Exception:
                return False
        return False

    def _on_widget_startup_failed(self, error_text: str) -> None:
        if self._closed:
            return
        self._set_status_message("Failed to finish applet startup.")
        print(f"[WARN] Deferred applet startup failed for {self._title}: {error_text}", file=sys.stderr)
        QMessageBox.warning(
            self,
            f"{self._title} Startup Failed",
            "The applet could not finish starting. See terminal output for details.",
        )
        self.appletFailed.emit(str(error_text or ""))

    def _finish_ready(self) -> None:
        if self._closed or self._ready_emitted:
            return
        self._ready_emitted = True
        if self._overlay is not None:
            self._overlay.hide_loading()
        self.appletReady.emit()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._overlay is not None:
            self._overlay.setGeometry(self.rect())

    def _set_status_message(self, message: str) -> None:
        text = str(message or "Loading applet...")
        if self._overlay is not None:
            self._overlay.set_message(text)
        self.appletStatusChanged.emit(text)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._closed = True
        inner = self._inner_widget
        if inner is not None:
            try:
                inner.close()
            except Exception:
                pass
        super().closeEvent(event)


def build_applet_widget(parent: QWidget, key: str, applet: Dict[str, object]) -> Optional[QWidget]:
    if str(key).startswith("online_host::"):
        widget: Optional[DungeonAppletWidget] = None
        online_cfg = applet.get("online", {}) if isinstance(applet.get("online"), dict) else {}
        port = int(online_cfg.get("port", 8765))
        collection_path = str(online_cfg.get("collection_path") or "").strip()
        dm_name = str(online_cfg.get("dm_name") or "DM").strip() or "DM"
        _append_online_launch_log(
            "online_host_launch_begin",
            key=str(key),
            port=int(port),
            collection_path=collection_path,
            dm_name=dm_name,
        )
        try:
            widget = DungeonAppletWidget(parent)
            started = widget.start_online_host(port, collection_path or None, dm_name)
        except Exception as exc:
            _append_online_launch_log(
                "online_host_launch_exception",
                key=str(key),
                port=int(port),
                collection_path=collection_path,
                dm_name=dm_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            if widget is not None:
                widget.deleteLater()
            return None
        if not started:
            _append_online_launch_log(
                "online_host_launch_failed",
                key=str(key),
                port=int(port),
                collection_path=collection_path,
                dm_name=dm_name,
            )
            if widget is not None:
                widget.deleteLater()
            return None
        _append_online_launch_log(
            "online_host_launch_ok",
            key=str(key),
            port=int(port),
            collection_path=collection_path,
            dm_name=dm_name,
        )
        return widget
    if str(key).startswith("online_join::"):
        widget: Optional[DungeonAppletWidget] = None
        online_cfg = applet.get("online", {}) if isinstance(applet.get("online"), dict) else {}
        host_ip = str(online_cfg.get("host_ip") or "").strip()
        port = int(online_cfg.get("port", 8765))
        player_name = str(online_cfg.get("player_name") or "Player").strip() or "Player"
        _append_online_launch_log(
            "online_join_launch_begin",
            key=str(key),
            host_ip=host_ip,
            port=int(port),
            player_name=player_name,
        )
        try:
            widget = DungeonAppletWidget(parent)
            widget.join_online_session(host_ip, port, player_name)
        except Exception as exc:
            _append_online_launch_log(
                "online_join_launch_exception",
                key=str(key),
                host_ip=host_ip,
                port=int(port),
                player_name=player_name,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            if widget is not None:
                widget.deleteLater()
            return None
        _append_online_launch_log(
            "online_join_launch_ok",
            key=str(key),
            host_ip=host_ip,
            port=int(port),
            player_name=player_name,
        )
        return widget
    if key == "item_creator":
        return ItemCreatorWidget(parent)
    if key == "map_library":
        if _async_applet_loading_enabled():
            return DeferredAppletHost(
                "Maps",
                load_fn=lambda: {
                    "world_data": _safe_navigation_world_data(),
                    "entries_and_error": load_map_entries_from_storage(),
                },
                build_fn=lambda host, payload: MapsWidget(
                    host,
                    initial_world_data=list(payload.get("world_data") or []),
                    initial_entries=list((payload.get("entries_and_error") or ([], ""))[0] or []),
                    load_entries_error=str((payload.get("entries_and_error") or ([], ""))[1] or ""),
                    defer_startup=True,
                ),
                parent=parent,
                use_internal_overlay=False,
            )
        return MapsWidget(parent)
    if key == "player_sheets":
        if _async_applet_loading_enabled():
            return DeferredAppletHost(
                "Characters",
                load_fn=lambda: {
                    "world_data": _safe_navigation_world_data(),
                    "entries": load_entries_from_storage(),
                },
                build_fn=lambda host, payload: PlayerSheetsWidget(
                    host,
                    initial_world_data=list(payload.get("world_data") or []),
                    initial_entries=list(payload.get("entries") or []),
                    defer_startup=True,
                ),
                parent=parent,
                use_internal_overlay=False,
            )
        return PlayerSheetsWidget(parent)
    if key == "session_creator":
        if _async_applet_loading_enabled():
            return DeferredAppletHost(
                "Sessions",
                load_fn=lambda: {
                    "manager": SessionManager(),
                    "world_data": _navigation_world_data(),
                },
                build_fn=lambda host, payload: SessionCreatorWidget(
                    host,
                    initial_manager=payload.get("manager")
                    if isinstance(payload.get("manager"), SessionManager)
                    else None,
                    initial_world_data=list(payload.get("world_data") or []),
                    defer_startup=True,
                    defer_files_tab=True,
                ),
                parent=parent,
                use_internal_overlay=False,
            )
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


def _online_launch_log_path() -> Path:
    try:
        return dnd_saves_dir() / "cache" / "logs" / ONLINE_LAUNCH_LOG_FILENAME
    except Exception:
        return Path(default_dnd_save_dir()) / "cache" / "logs" / ONLINE_LAUNCH_LOG_FILENAME

def _instance_log_path(base_path: Path) -> Path:
    return base_path.with_name(f"{base_path.stem}_pid{os.getpid()}{base_path.suffix}")

def _append_json_line(path: Path, payload: dict[str, object], *, warn_prefix: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True))
            handle.write("\n")
    except Exception as exc:
        print(f"[WARN] {warn_prefix}: {exc}", file=sys.stderr)


def _append_online_launch_log(event: str, **fields: object) -> None:
    if not is_runtime_logging_enabled():
        return
    payload: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "pid": os.getpid(),
        "event": str(event or "unknown"),
    }
    for key, value in fields.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[str(key)] = value
        else:
            payload[str(key)] = str(value)
    shared_path = _online_launch_log_path()
    _append_json_line(
        shared_path,
        payload,
        warn_prefix="Failed to write online launch log",
    )
    instance_path = _instance_log_path(shared_path)
    if instance_path != shared_path:
        _append_json_line(
            instance_path,
            payload,
            warn_prefix="Failed to write instance online launch log",
        )


def _app_crash_log_path() -> Path:
    try:
        return dnd_saves_dir() / "cache" / "logs" / APP_CRASH_LOG_FILENAME
    except Exception:
        return Path(default_dnd_save_dir()) / "cache" / "logs" / APP_CRASH_LOG_FILENAME


def _app_crash_instance_log_path() -> Path:
    return _instance_log_path(_app_crash_log_path())


def _append_app_crash_log(event: str, **fields: object) -> None:
    if not is_runtime_logging_enabled():
        return
    payload: dict[str, object] = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "pid": os.getpid(),
        "event": str(event or "unknown"),
        "argv": list(sys.argv),
        "cwd": str(Path.cwd()),
    }
    for key, value in fields.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            payload[str(key)] = value
        else:
            payload[str(key)] = str(value)
    try:
        global _CRASH_LOG_HANDLE, _CRASH_LOG_INSTANCE_PATH
        handle = _CRASH_LOG_HANDLE
        if handle is None:
            instance_path = _app_crash_instance_log_path()
            _append_json_line(
                instance_path,
                payload,
                warn_prefix="Failed to write instance app crash log",
            )
        else:
            handle.write(json.dumps(payload, ensure_ascii=True))
            handle.write("\n")
            handle.flush()
        shared_path = _app_crash_log_path()
        if _CRASH_LOG_INSTANCE_PATH is None or shared_path != _CRASH_LOG_INSTANCE_PATH:
            _append_json_line(
                shared_path,
                payload,
                warn_prefix="Failed to write app crash log",
            )
    except Exception as exc:
        print(f"[WARN] Failed to write app crash log: {exc}", file=sys.stderr)


def _install_crash_logging() -> None:
    global _CRASH_LOG_HANDLE, _CRASH_LOG_INSTANCE_PATH
    if _CRASH_LOG_HANDLE is None:
        _CRASH_LOG_INSTANCE_PATH = _app_crash_instance_log_path()
        _CRASH_LOG_INSTANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CRASH_LOG_HANDLE = _CRASH_LOG_INSTANCE_PATH.open("a", encoding="utf-8")
    handle = _CRASH_LOG_HANDLE
    try:
        if not faulthandler.is_enabled():
            faulthandler.enable(handle, all_threads=True)
    except Exception as exc:
        print(f"[WARN] Failed to enable faulthandler: {exc}", file=sys.stderr)
        _append_app_crash_log(
            "crash_logging_faulthandler_enable_failed",
            error=str(exc),
        )

    def _sys_excepthook(exc_type, exc_value, exc_traceback):
        crash_payload = {
            "exception_type": getattr(exc_type, "__name__", str(exc_type)),
            "error": str(exc_value or ""),
            "traceback": "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)),
        }
        append_active_online_session_crash_event("uncaught_exception", **crash_payload)
        _append_app_crash_log(
            "uncaught_exception",
            **crash_payload,
        )
        _ORIGINAL_SYS_EXCEPTHOOK(exc_type, exc_value, exc_traceback)

    sys.excepthook = _sys_excepthook

    if _ORIGINAL_THREADING_EXCEPTHOOK is not None and hasattr(threading, "excepthook"):
        def _threading_excepthook(args):
            crash_payload = {
                "thread_name": str(getattr(getattr(args, "thread", None), "name", "")),
                "exception_type": getattr(getattr(args, "exc_type", None), "__name__", str(getattr(args, "exc_type", ""))),
                "error": str(getattr(args, "exc_value", "") or ""),
                "traceback": "".join(
                    traceback.format_exception(
                        getattr(args, "exc_type", None),
                        getattr(args, "exc_value", None),
                        getattr(args, "exc_traceback", None),
                    )
                ),
            }
            append_active_online_session_crash_event("uncaught_thread_exception", **crash_payload)
            _append_app_crash_log(
                "uncaught_thread_exception",
                **crash_payload,
            )
            _ORIGINAL_THREADING_EXCEPTHOOK(args)

        threading.excepthook = _threading_excepthook


class _WorkspaceTabWindow(QMainWindow):
    def __init__(self, workspace_controller: TabWorkspaceController, *, primary: bool, title: str) -> None:
        super().__init__()
        self._workspace_controller = workspace_controller
        self._workspace_primary = bool(primary)
        self.setWindowTitle(title)
        self.setMinimumSize(1200, 700)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))

        self.tabs = WorkspaceTabsHost(self)
        self.setCentralWidget(self.tabs)

        self._loading_overlay = AppletLoadingOverlay(self.tabs)
        self._loading_overlay.setGeometry(self.tabs.rect())
        self._loading_overlay.hide()
        self._external_loading_indicator = ExternalLoadingIndicatorController()

        self._workspace_controller.register_window(self, primary=self._workspace_primary)
        self._tab_by_key = self._workspace_controller.tab_by_key

    def workspace_host(self) -> WorkspaceTabsHost:
        return self.tabs

    def workspace_tabs(self) -> WorkspaceTabsHost:
        return self.tabs

    def is_primary_window(self) -> bool:
        return self._workspace_primary

    def _disable_tab_close(self, index: int) -> None:
        self.tabs.setTabClosable(index, False)

    def begin_applet_load(self, key: str, title: str) -> None:
        _ = key
        self._show_applet_loading_overlay(f"Loading {title or 'applet'}...")

    def end_applet_load(self, key: str) -> None:
        _ = key
        self._hide_applet_loading_overlay()

    def update_applet_load_status(self, key: str, message: str) -> None:
        _ = (key, message)

    def build_applet_widget(self, key: str, applet: Dict[str, object]) -> Optional[QWidget]:
        # Applet construction is synchronous on the UI thread. Re-entering the
        # event loop with QApplication.processEvents() while a widget tree is
        # only partially constructed has caused native Qt access violations.
        return self._build_applet_widget(key, applet)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "_loading_overlay"):
            self._loading_overlay.setGeometry(self.tabs.rect())
        if hasattr(self, "_workspace_controller"):
            self._workspace_controller.sync_tab_bar_extent(self)

    def _show_applet_loading_overlay(self, message: str) -> None:
        if self._external_loading_indicator.show(self.tabs, message):
            self._loading_overlay.hide_loading()
            return
        self._loading_overlay.show_loading(message)

    def _hide_applet_loading_overlay(self) -> None:
        self._external_loading_indicator.hide()
        self._loading_overlay.hide_loading()

    def _build_applet_widget(self, key: str, applet: Dict[str, object]) -> Optional[QWidget]:
        return build_applet_widget(self.tabs, key, applet)

    def open_applet(self, applet: Dict[str, object], focus_if_new: bool = True) -> None:
        self._workspace_controller.open_applet(self, applet, focus_if_new=focus_if_new)

    def _close_tab(self, index: int) -> None:
        self._workspace_controller.close_tab_by_index(self, index)

    def closeEvent(self, event) -> None:
        self._external_loading_indicator.hide()
        super().closeEvent(event)


class DetachedTabWindow(_WorkspaceTabWindow):
    def __init__(self, workspace_controller: TabWorkspaceController) -> None:
        super().__init__(
            workspace_controller,
            primary=False,
            title="Dungeon Master Tools | Detached Tabs",
        )

    def closeEvent(self, event) -> None:
        if not self._workspace_controller.prepare_window_close(self):
            event.ignore()
            return
        self._workspace_controller.unregister_window(self)
        super().closeEvent(event)


class MainLauncherWindow(_WorkspaceTabWindow):
    def __init__(self) -> None:
        self._workspace_controller = TabWorkspaceController()
        super().__init__(
            self._workspace_controller,
            primary=True,
            title="Dungeon Master Tools",
        )
        self._workspace_controller.set_detached_window_factory(
            lambda: DetachedTabWindow(self._workspace_controller)
        )
        home = HomeWidget(APPLET_DEFINITIONS, self.open_applet)
        self._home = home
        home_index = self.tabs.addTab(home, "Home", closable=False, pinned=True)
        self._disable_tab_close(home_index)
        self._workspace_controller.set_home_widget(home)
        self.tabs.setCurrentIndex(0)

    def closeEvent(self, event) -> None:
        if not self._workspace_controller.begin_primary_shutdown(self):
            event.ignore()
            return
        if not self._workspace_controller.prepare_window_close(self):
            self._workspace_controller.is_shutting_down = False
            event.ignore()
            return
        self._workspace_controller.unregister_window(self)
        clear_all_online_runtime_caches()
        clear_all_disposable_caches()
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
        top_bar.setFixedHeight(74)
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

        self._local_player_id = get_or_create_local_player_id()

        settings_cluster = QWidget(top_bar)
        settings_layout = QVBoxLayout(settings_cluster)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(2)

        settings_row = QWidget(settings_cluster)
        settings_row_layout = QHBoxLayout(settings_row)
        settings_row_layout.setContentsMargins(0, 0, 0, 0)
        settings_row_layout.setSpacing(4)

        self._settings_button = QToolButton(settings_row)
        self._settings_button.setObjectName("TopBarButton")
        self._settings_button.setText("Settings")
        self._settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._settings_button.clicked.connect(self._show_settings)

        self._about_button = QToolButton(settings_row)
        self._about_button.setObjectName("TopBarButton")
        self._about_button.setText("About")
        self._about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._about_button.clicked.connect(self._show_about)

        # Add a subtle separator between buttons
        sep = QLabel("|", settings_row)
        sep.setStyleSheet("color: #30363d; font-weight: bold; margin: 0 4px;")

        settings_row_layout.addWidget(self._settings_button)
        settings_row_layout.addWidget(sep)
        settings_row_layout.addWidget(self._about_button)
        settings_layout.addWidget(
            settings_row,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )

        self._player_id_label = QLabel(settings_cluster)
        self._player_id_label.setObjectName("TopBarPlayerId")
        self._player_id_label.setText(f"Player ID: {self._local_player_id}")
        self._player_id_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._player_id_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._player_id_label.setStyleSheet("font-size: 10px; color: #7f8ea3;")
        settings_layout.addWidget(
            self._player_id_label,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
        )
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
        _append_online_launch_log("home_host_prompt_opened")
        details = self._prompt_host_dungeon_collection_details()
        if details is None:
            _append_online_launch_log("home_host_prompt_cancelled")
            return
        filename = str(details["collection_path"]).strip()
        port = int(details["port"])
        dm_name = str(details["dm_name"]).strip()
        if not filename:
            _append_online_launch_log("home_host_prompt_rejected_blank_collection")
            QMessageBox.warning(self, "Host Online Session", "Dungeon collection is required.")
            return
        if not Path(filename).is_file():
            _append_online_launch_log(
                "home_host_prompt_rejected_missing_collection",
                collection_path=filename,
            )
            QMessageBox.warning(
                self,
                "Host Online Session",
                "Choose an existing dungeon collection file.",
            )
            return
        if not dm_name:
            _append_online_launch_log(
                "home_host_prompt_rejected_blank_dm_name",
                collection_path=str(filename),
                port=int(port),
            )
            QMessageBox.warning(self, "Host Online Session", "DM name is required.")
            return
        collection_name = Path(filename).stem or "Collection"
        _append_online_launch_log(
            "home_host_applet_queued",
            collection_path=str(filename),
            port=int(port),
            collection_name=str(collection_name),
            dm_name=str(dm_name),
        )
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
                "dm_name": dm_name,
            },
        }
        self._on_open(applet, True)

    def _join_dungeon_by_ip(self) -> None:
        _append_online_launch_log("home_join_prompt_opened")
        details = self._prompt_join_online_details()
        if details is None:
            _append_online_launch_log("home_join_prompt_cancelled")
            return
        host_ip = str(details["host_ip"]).strip()
        port = int(details["port"])
        player_name = str(details["player_name"]).strip()
        if not host_ip.strip():
            _append_online_launch_log("home_join_prompt_rejected_blank_host")
            QMessageBox.warning(self, "Join Online Session", "Host IP is required.")
            return
        if not player_name.strip():
            _append_online_launch_log(
                "home_join_prompt_rejected_blank_name",
                host_ip=host_ip,
                port=int(port),
            )
            QMessageBox.warning(self, "Join Online Session", "Player name is required.")
            return
        _append_online_launch_log(
            "home_join_applet_queued",
            host_ip=host_ip,
            port=int(port),
            player_name=str(player_name),
        )
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

    def _dialog_action_button(self, text: str, object_name: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName(object_name)
        button.setMinimumHeight(36)
        button.setMinimumWidth(110)
        return button

    def _last_join_player_name(self) -> str:
        path = dnd_saves_dir() / "settings" / LOCAL_DUNGEON_PROFILE_FILENAME
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    clean_name = str(payload.get("last_player_name") or "").strip()
                    if clean_name:
                        return clean_name
        except Exception:
            pass
        return "Player"

    def _last_join_host_ip(self) -> str:
        path = dnd_saves_dir() / "settings" / LOCAL_DUNGEON_PROFILE_FILENAME
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    host_ip = str(payload.get("last_join_host_ip") or "").strip()
                    if host_ip:
                        return host_ip
        except Exception:
            pass
        return "127.0.0.1"

    def _last_host_dm_name(self) -> str:
        path = dnd_saves_dir() / "settings" / LOCAL_DUNGEON_PROFILE_FILENAME
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    clean_name = str(payload.get("last_dm_name") or "").strip()
                    if clean_name:
                        return clean_name
        except Exception:
            pass
        return "DM"

    def _last_host_collection_path(self) -> str:
        path = dnd_saves_dir() / "settings" / LOCAL_DUNGEON_PROFILE_FILENAME
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    collection_path = str(payload.get("last_host_collection_path") or "").strip()
                    if collection_path and Path(collection_path).is_file():
                        return collection_path
        except Exception:
            pass
        return ""

    def _prompt_host_dungeon_collection_details(self) -> Optional[Dict[str, object]]:
        base_dir = dungeon_collections_dir()
        base_dir.mkdir(parents=True, exist_ok=True)

        dialog = ModernDialog("Host Online Session", self)
        dialog.setMinimumWidth(620)
        dialog.add_text("Choose a collection file, port, and DM name, then start the host.")

        content = QWidget(dialog)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        layout.addLayout(form)

        collection_edit = QLineEdit(dialog)
        collection_edit.setPlaceholderText("Select a dungeon collection file")
        collection_edit.setMinimumHeight(36)
        collection_edit.setText(self._last_host_collection_path())

        browse_button = QPushButton("Browse", dialog)
        browse_button.setObjectName("SecondaryButton")
        browse_button.setMinimumHeight(36)
        browse_button.setMinimumWidth(110)

        collection_row = QWidget(dialog)
        collection_row_layout = QHBoxLayout(collection_row)
        collection_row_layout.setContentsMargins(0, 0, 0, 0)
        collection_row_layout.setSpacing(8)
        collection_row_layout.addWidget(collection_edit, 1)
        collection_row_layout.addWidget(browse_button, 0)
        form.addRow("Collection", collection_row)

        port_spin = QSpinBox(dialog)
        port_spin.setRange(1024, 65535)
        port_spin.setValue(8765)
        port_spin.setMinimumHeight(36)
        form.addRow("Port", port_spin)

        dm_name_edit = QLineEdit(dialog)
        dm_name_edit.setText(self._last_host_dm_name())
        dm_name_edit.setMinimumHeight(36)
        form.addRow("DM Name", dm_name_edit)

        def _browse_for_collection() -> None:
            filename, _ = QFileDialog.getOpenFileName(
                dialog,
                "Select Dungeon Collection",
                str(base_dir),
                f"Dungeon Collection (*{COLLECTION_FILE_EXTENSION})",
            )
            if filename:
                collection_edit.setText(str(filename))

        browse_button.clicked.connect(_browse_for_collection)

        submit_button = self._dialog_action_button("Host", "PrimaryButton")
        cancel_button = self._dialog_action_button("Cancel", "SecondaryButton")
        submit_button.setDefault(True)

        def _accept_if_valid() -> None:
            filename = collection_edit.text().strip()
            if not filename:
                _append_online_launch_log("home_host_prompt_rejected_blank_collection")
                QMessageBox.warning(dialog, "Host Online Session", "Dungeon collection is required.")
                return
            if not Path(filename).is_file():
                _append_online_launch_log(
                    "home_host_prompt_rejected_missing_collection",
                    collection_path=filename,
                )
                QMessageBox.warning(
                    dialog,
                    "Host Online Session",
                    "Choose an existing dungeon collection file.",
                )
                return
            dm_name = dm_name_edit.text().strip()
            if not dm_name:
                _append_online_launch_log(
                    "home_host_prompt_rejected_blank_dm_name",
                    collection_path=filename,
                    port=int(port_spin.value()),
                )
                QMessageBox.warning(dialog, "Host Online Session", "DM name is required.")
                return
            dialog.accept()

        submit_button.clicked.connect(_accept_if_valid)
        cancel_button.clicked.connect(dialog.reject)

        dialog.add_content(content)
        dialog.add_buttons([cancel_button, submit_button])

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "collection_path": collection_edit.text().strip(),
            "port": int(port_spin.value()),
            "dm_name": dm_name_edit.text().strip(),
        }

    def _prompt_join_online_details(self) -> Optional[Dict[str, object]]:
        dialog = ModernDialog("Join Online Session", self)
        dialog.setMinimumWidth(520)
        dialog.add_text("Enter the host, port, and player name, then join the session.")

        content = QWidget(dialog)
        form = QFormLayout(content)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        host_edit = QLineEdit(dialog)
        host_edit.setText(self._last_join_host_ip())
        host_edit.setMinimumHeight(36)
        form.addRow("Host IP", host_edit)

        port_spin = QSpinBox(dialog)
        port_spin.setRange(1, 65535)
        port_spin.setValue(8765)
        port_spin.setMinimumHeight(36)
        form.addRow("Port", port_spin)

        player_name_edit = QLineEdit(dialog)
        player_name_edit.setText(self._last_join_player_name())
        player_name_edit.setMinimumHeight(36)
        form.addRow("Player Name", player_name_edit)

        submit_button = self._dialog_action_button("Join", "PrimaryButton")
        cancel_button = self._dialog_action_button("Cancel", "SecondaryButton")
        submit_button.setDefault(True)

        def _accept_if_valid() -> None:
            host_ip = host_edit.text().strip()
            if not host_ip:
                _append_online_launch_log("home_join_prompt_rejected_blank_host")
                QMessageBox.warning(dialog, "Join Online Session", "Host IP is required.")
                return
            player_name = player_name_edit.text().strip()
            if not player_name:
                _append_online_launch_log(
                    "home_join_prompt_rejected_blank_name",
                    host_ip=host_ip,
                    port=int(port_spin.value()),
                )
                QMessageBox.warning(dialog, "Join Online Session", "Player name is required.")
                return
            dialog.accept()

        submit_button.clicked.connect(_accept_if_valid)
        cancel_button.clicked.connect(dialog.reject)

        dialog.add_content(content)
        dialog.add_buttons([cancel_button, submit_button])

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "host_ip": host_edit.text().strip(),
            "port": int(port_spin.value()),
            "player_name": player_name_edit.text().strip(),
        }

    def _show_settings(self) -> None:
        dialog = ModernDialog("Settings", self)
        dialog.add_text("Configure your Dungeon Master Tools experience.")

        settings = load_app_settings()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        session_group = QGroupBox("Session Creator", content)
        session_group.setObjectName("TransparentContainer")
        session_layout = QVBoxLayout(session_group)
        session_layout.setContentsMargins(12, 12, 12, 12)
        session_layout.setSpacing(6)

        session_autosave_checkbox = QCheckBox("Enable autosave while editing sessions", session_group)
        session_autosave_checkbox.setChecked(
            bool(settings.get("session_autosave_enabled", False))
        )
        session_layout.addWidget(session_autosave_checkbox)

        session_hint = QLabel(
            "When enabled, Session Creator saves edits automatically after about 2 seconds of inactivity."
        )
        session_hint.setWordWrap(True)
        session_hint.setStyleSheet("color: #8b949e;")
        session_layout.addWidget(session_hint)

        content_layout.addWidget(session_group)

        wheel_group = QGroupBox("Mouse Wheel", content)
        wheel_group.setObjectName("TransparentContainer")
        wheel_layout = QVBoxLayout(wheel_group)
        wheel_layout.setContentsMargins(12, 12, 12, 12)
        wheel_layout.setSpacing(6)

        ctrl_wheel_zoom_checkbox = QCheckBox(
            "Require Ctrl for mouse-wheel zoom",
            wheel_group,
        )
        ctrl_wheel_zoom_checkbox.setChecked(is_ctrl_mouse_wheel_zoom_enabled())
        wheel_layout.addWidget(ctrl_wheel_zoom_checkbox)

        wheel_hint = QLabel(
            "When disabled, the plain mouse wheel zooms and Ctrl+wheel scrolls instead."
        )
        wheel_hint.setWordWrap(True)
        wheel_hint.setStyleSheet("color: #8b949e;")
        wheel_layout.addWidget(wheel_hint)

        content_layout.addWidget(wheel_group)
        content_layout.addStretch(1)
        dialog.add_content(content)

        def _save_settings() -> None:
            try:
                save_app_settings(
                    {
                        "session_autosave_enabled": bool(session_autosave_checkbox.isChecked()),
                        "ctrl_mouse_wheel_zoom_enabled": bool(
                            ctrl_wheel_zoom_checkbox.isChecked()
                        ),
                    }
                )
            except Exception as exc:
                QMessageBox.warning(
                    dialog,
                    "Settings",
                    f"Unable to save settings.\n\n{exc}",
                )
                return
            dialog.accept()

        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setFixedWidth(96)
        save_btn.clicked.connect(_save_settings)

        close_btn = QPushButton("Close")
        close_btn.setObjectName("SecondaryButton")
        close_btn.setFixedWidth(96)
        close_btn.clicked.connect(dialog.accept)
        dialog.add_buttons([close_btn, save_btn])
        dialog.exec()

    def _show_about(self) -> None:
        dialog = ModernDialog("About Dungeon Master Tools", self)
        dialog.add_text(
            "A comprehensive suite for Dungeon Masters and players."
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
    _install_crash_logging()
    _append_app_crash_log("app_main_enter")
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    clear_all_online_runtime_caches()
    clear_all_disposable_caches()
    cleanup_stale_bundled_runtime_data()
    try:
        refresh_character_sheet_index_cache()
    except Exception:
        pass
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("DMT")
        if APP_ICON_PATH.exists():
            app.setWindowIcon(QIcon(str(APP_ICON_PATH)))
        app.setStyleSheet(DARK_STYLESHEET)
        window = MainLauncherWindow()
        window.show()
        _append_app_crash_log("app_event_loop_enter")
        exit_code = int(app.exec())
        _append_app_crash_log("app_event_loop_exit", exit_code=exit_code)
        return exit_code
    except Exception as exc:
        _append_app_crash_log(
            "app_main_exception",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise
    finally:
        cleanup_current_bundled_runtime_data()


if __name__ == "__main__":
    raise SystemExit(main())
