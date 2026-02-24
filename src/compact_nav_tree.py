"""
Compact hierarchical navigation tree for DMT.

This module provides a dense tree view for navigating:
  World -> Campaign -> Group hierarchy.

Features:
- Left caret for expand/collapse
- Context menus for CRUD operations
- Compact/dense row styling
- No overview panels or dashboards
"""
from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtSvg import QSvgRenderer
    SVG_AVAILABLE = True
except Exception:
    SVG_AVAILABLE = False

from save_paths import trash_json_path, navigation_json_path
from navigation_storage import load_navigation_world_data, save_navigation_world_data

# Icons directory
ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))

# Compact styling constants
COMPACT_ICON_SIZE = 32
COMPACT_ROW_HEIGHT = 48  # 2x taller for visibility
TRASH_RETENTION_DAYS = 30

# Icon paths
CARET_RIGHT_ICON = os.path.join(ICON_DIR, "caret_right.svg")
CARET_DOWN_ICON = os.path.join(ICON_DIR, "caret_down.svg")
PLUS_ICON = os.path.join(ICON_DIR, "plus.svg")
MINUS_ICON = os.path.join(ICON_DIR, "minus.svg")
EDIT_ICON = os.path.join(ICON_DIR, "edit.svg")
DISINTEGRATE_ICON = os.path.join(ICON_DIR, "disintegrate.svg")
REVIVE_ICON = os.path.join(ICON_DIR, "revive.svg")


def _load_icon(path: str, size: int) -> Optional[QPixmap]:
    """Load icon from path, handling SVG and raster formats."""
    if not path or not os.path.exists(path):
        return None
    if SVG_AVAILABLE and path.lower().endswith(".svg"):
        renderer = QSvgRenderer(path)
        if renderer.isValid():
            image = QImage(size, size, QImage.Format.Format_ARGB32)
            image.fill(Qt.GlobalColor.transparent)
            painter = QPainter(image)
            renderer.render(painter)
            painter.end()
            return QPixmap.fromImage(image)
    pixmap = QPixmap(path)
    if pixmap.isNull():
        return None
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def _list_icon_paths() -> list[str]:
    """List available icon files in the icons directory."""
    if not os.path.isdir(ICON_DIR):
        return []
    icons = []
    for name in sorted(os.listdir(ICON_DIR)):
        if name.lower().endswith((".png", ".svg", ".jpg", ".jpeg")):
            icons.append(os.path.join(ICON_DIR, name))
    return icons


# Default world data structure
WORLD_DATA: list[dict] = []
NAVIGATION_PATH = str(navigation_json_path())


def _navigation_base_dir() -> Path:
    return Path(NAVIGATION_PATH).expanduser().resolve().parent


def load_navigation_data() -> list:
    """Load navigation data from persistent storage."""
    try:
        data = load_navigation_world_data(base_dir=_navigation_base_dir())
        return data if isinstance(data, list) else WORLD_DATA
    except Exception:
        return WORLD_DATA


def save_navigation_data(data: list) -> None:
    """Save navigation data to persistent storage."""
    try:
        save_navigation_world_data(data if isinstance(data, list) else [], base_dir=_navigation_base_dir())
    except Exception:
        pass


def load_trash() -> list[dict]:
    """Load trash entries from storage."""
    path = trash_json_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_trash(entries: list[dict]) -> None:
    """Save trash entries to storage."""
    path = trash_json_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, ensure_ascii=False, indent=2)


class NameIconDialog(QDialog):
    """Dialog for entering a name and selecting an icon."""
    
    def __init__(
        self,
        title: str,
        label: str,
        icon_paths: list[str],
        default_name: str = "",
        default_icon: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(350)
        
        self._selected_icon = default_icon
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        # Name input
        name_label = QLabel(label)
        layout.addWidget(name_label)
        self._name_input = QLineEdit()
        self._name_input.setText(default_name)
        layout.addWidget(self._name_input)
        
        # Icon selection
        icon_label = QLabel("Icon:")
        layout.addWidget(icon_label)
        self._icon_list = QListWidget()
        self._icon_list.setObjectName("IconPickerList")
        self._icon_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._icon_list.setIconSize(self._icon_list.iconSize())
        self._icon_list.setSpacing(4)
        self._icon_list.setFixedHeight(120)
        for path in icon_paths[:24]:  # Limit to first 24 icons
            pixmap = _load_icon(path, 32)
            if pixmap:
                item = QListWidgetItem(QIcon(pixmap), "")
                item.setData(Qt.ItemDataRole.UserRole, path)
                self._icon_list.addItem(item)
        self._icon_list.itemClicked.connect(self._on_icon_clicked)
        layout.addWidget(self._icon_list)
        
        # Custom icon button
        custom_btn = QPushButton("Choose Custom Icon...")
        custom_btn.clicked.connect(self._choose_custom_icon)
        layout.addWidget(custom_btn)
        
        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _on_icon_clicked(self, item: QListWidgetItem) -> None:
        self._selected_icon = item.data(Qt.ItemDataRole.UserRole)
    
    def _choose_custom_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Icon",
            "",
            "Images (*.png *.svg *.jpg *.jpeg)",
        )
        if path:
            self._selected_icon = path
    
    def values(self) -> tuple[Optional[str], Optional[str]]:
        name = self._name_input.text().strip()
        return name if name else None, self._selected_icon


class IconListDialog(QDialog):
    """Dialog for selecting from a list of items with icons."""
    
    def __init__(
        self,
        title: str,
        label: str,
        items: list[tuple],  # (display_text, icon_path, value)
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(300)
        self.selected = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        label_widget = QLabel(label)
        layout.addWidget(label_widget)
        
        self._list = QListWidget()
        self._list.setObjectName("IconSelectList")
        self._list.itemClicked.connect(self._on_item_clicked)
        for display, icon_path, value in items:
            item = QListWidgetItem(display)
            pixmap = _load_icon(icon_path, 24) if icon_path else None
            if pixmap:
                item.setIcon(QIcon(pixmap))
            item.setData(Qt.ItemDataRole.UserRole, value)
            self._list.addItem(item)
        layout.addWidget(self._list, 1)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
    
    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self.selected = item.data(Qt.ItemDataRole.UserRole)


class CompactNavTree(QWidget):
    """
    Compact hierarchical navigation tree.
    
    Displays Worlds -> Campaigns -> Groups in a dense tree layout.
    Left-click on carets to expand/collapse.
    Right-click shows context menus with creation and management actions.
    """
    
    # Signals
    session_launched = pyqtSignal(str, str, str)  # world, campaign, group
    
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._data: list[dict] = []
        self._trash: list[dict] = []
        self._icon_paths = _list_icon_paths()
        
        # Default icons
        self._default_world_icon = os.path.join(ICON_DIR, "navigate.png")
        self._default_campaign_icon = os.path.join(ICON_DIR, "mapselector.png")
        self._default_group_icon = os.path.join(ICON_DIR, "charactersheets.png")
        
        self._setup_ui()
        self._load_data()
        self._load_trash()
        self._rebuild_tree()
    
    def _setup_ui(self) -> None:
        """Initialize the UI layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Tree widget for hierarchical navigation
        self._tree = QTreeWidget()
        self._tree.setObjectName("CompactNavTree")
        self._tree.setHeaderHidden(True)
        self._tree.setIconSize(QSize(COMPACT_ICON_SIZE, COMPACT_ICON_SIZE))
        self._tree.setIndentation(16)  # Compact indentation
        self._tree.setAnimated(True)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._show_context_menu)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemExpanded.connect(self._on_item_expanded)
        self._tree.itemCollapsed.connect(self._on_item_collapsed)
        self._tree.verticalScrollBar().setSingleStep(8)
        self._tree.verticalScrollBar().setPageStep(COMPACT_ROW_HEIGHT * 2)
        self._tree.horizontalScrollBar().setSingleStep(8)
        self._tree.viewport().installEventFilter(self)
        
        layout.addWidget(self._tree, 1)

    def eventFilter(self, watched, event):  # type: ignore[override]
        if watched is self._tree.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton:
                pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
                self._clear_selection_if_empty_click(pos)
        return super().eventFilter(watched, event)

    def _clear_selection_if_empty_click(self, pos) -> bool:
        if self._tree.itemAt(pos) is not None:
            return False
        self._tree.clearSelection()
        self._tree.setCurrentItem(None)
        return True
    
    def _load_data(self) -> None:
        """Load navigation data from storage."""
        loaded = load_navigation_data()
        self._data = []
        for world in loaded:
            world_entry = {
                "name": world.get("name", ""),
                "icon": world.get("icon") or self._default_world_icon,
                "campaigns": [],
            }
            for campaign in world.get("campaigns", []):
                groups = []
                for group in campaign.get("groups", []):
                    if isinstance(group, dict):
                        group_name = group.get("name", "")
                        group_icon = group.get("icon") or self._default_group_icon
                    else:
                        group_name = str(group)
                        group_icon = self._default_group_icon
                    if group_name:
                        groups.append({"name": group_name, "icon": group_icon})
                world_entry["campaigns"].append({
                    "name": campaign.get("name", ""),
                    "icon": campaign.get("icon") or self._default_campaign_icon,
                    "groups": groups,
                })
            self._data.append(world_entry)
    
    def _save_data(self) -> None:
        """Save navigation data to storage."""
        save_navigation_data(self._data)
    
    def _load_trash(self) -> None:
        """Load trash entries."""
        self._trash = load_trash()
        self._purge_trash()
    
    def _save_trash(self) -> None:
        """Save trash entries."""
        save_trash(self._trash)
    
    def _purge_trash(self) -> None:
        """Remove old trash entries."""
        if not self._trash:
            return
        cutoff = datetime.now() - timedelta(days=TRASH_RETENTION_DAYS)
        kept = []
        for entry in self._trash:
            deleted_at = entry.get("deleted_at")
            try:
                deleted_time = datetime.fromisoformat(str(deleted_at))
                # Convert timezone-aware datetime to naive for comparison
                if deleted_time.tzinfo is not None:
                    deleted_time = deleted_time.replace(tzinfo=None)
            except Exception:
                deleted_time = None
            if deleted_time and deleted_time < cutoff:
                continue
            kept.append(entry)
        if len(kept) != len(self._trash):
            self._trash = kept
            self._save_trash()
    
    def _move_to_trash(self, entry_type: str, payload: dict, parent: Optional[dict] = None) -> None:
        """Move an entry to trash."""
        trash_entry = {
            "type": entry_type,
            "name": payload.get("name"),
            "icon": payload.get("icon"),
            "payload": copy.deepcopy(payload),
            "parent": parent or {},
            "deleted_at": datetime.now().isoformat(timespec="seconds"),
        }
        self._trash.append(trash_entry)
        self._save_trash()
    
    def _rebuild_tree(self) -> None:
        """Rebuild the tree widget from data."""
        # Store expansion state
        expanded_worlds = set()
        expanded_campaigns = {}
        
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            world_item = root.child(i)
            world_name = world_item.data(0, Qt.ItemDataRole.UserRole + 1)
            if world_item.isExpanded():
                expanded_worlds.add(world_name)
            for j in range(world_item.childCount()):
                campaign_item = world_item.child(j)
                campaign_name = campaign_item.data(0, Qt.ItemDataRole.UserRole + 1)
                if campaign_item.isExpanded():
                    expanded_campaigns[(world_name, campaign_name)] = True
        
        self._tree.clear()
        
        for world_idx, world in enumerate(self._data):
            world_item = QTreeWidgetItem()
            world_item.setText(0, world["name"])
            world_item.setData(0, Qt.ItemDataRole.UserRole, ("world", world_idx))
            world_item.setData(0, Qt.ItemDataRole.UserRole + 1, world["name"])
            
            # Set icon
            pixmap = _load_icon(world.get("icon"), COMPACT_ICON_SIZE)
            if pixmap:
                world_item.setIcon(0, QIcon(pixmap))
            
            for campaign_idx, campaign in enumerate(world.get("campaigns", [])):
                campaign_item = QTreeWidgetItem()
                campaign_item.setText(0, campaign["name"])
                campaign_item.setData(0, Qt.ItemDataRole.UserRole, ("campaign", world_idx, campaign_idx))
                campaign_item.setData(0, Qt.ItemDataRole.UserRole + 1, campaign["name"])
                
                pixmap = _load_icon(campaign.get("icon"), COMPACT_ICON_SIZE)
                if pixmap:
                    campaign_item.setIcon(0, QIcon(pixmap))
                
                for group in campaign.get("groups", []):
                    group_item = QTreeWidgetItem()
                    group_item.setText(0, group["name"])
                    group_item.setData(0, Qt.ItemDataRole.UserRole, ("group", world_idx, campaign_idx, group["name"]))
                    group_item.setData(0, Qt.ItemDataRole.UserRole + 1, group["name"])
                    
                    pixmap = _load_icon(group.get("icon"), COMPACT_ICON_SIZE)
                    if pixmap:
                        group_item.setIcon(0, QIcon(pixmap))
                    
                    campaign_item.addChild(group_item)
                
                world_item.addChild(campaign_item)
                
                # Restore campaign expansion
                if (world["name"], campaign["name"]) in expanded_campaigns:
                    campaign_item.setExpanded(True)
            
            self._tree.addTopLevelItem(world_item)
            
            # Restore world expansion
            if world["name"] in expanded_worlds:
                world_item.setExpanded(True)
    
    def _on_item_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        """Handle item click - toggle expansion for world/campaign."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        item_type = data[0]
        
        if item_type in ("world", "campaign"):
            # Toggle expansion
            item.setExpanded(not item.isExpanded())
    
    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        """Called when an item is expanded."""
        pass
    
    def _on_item_collapsed(self, item: QTreeWidgetItem) -> None:
        """Called when an item is collapsed."""
        pass
    
    def _show_context_menu(self, pos) -> None:
        """Show context menu based on clicked item."""
        item = self._tree.itemAt(pos)
        menu = QMenu(self)
        
        if item is None:
            # Empty space context menu
            self._add_menu_action(menu, PLUS_ICON, "New World", self._add_world)
        else:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if not data:
                return
            
            item_type = data[0]
            
            if item_type == "world":
                world_idx = data[1]
                world = self._data[world_idx] if world_idx < len(self._data) else None
                if world:
                    self._add_menu_action(menu, PLUS_ICON, "New World", self._add_world)
                    self._add_menu_action(
                        menu, PLUS_ICON, "New Campaign",
                        lambda idx=world_idx: self._add_campaign(idx)
                    )
                    menu.addSeparator()
                    self._add_menu_action(
                        menu, EDIT_ICON, "Edit World",
                        lambda w=world["name"]: self._edit_world(w)
                    )
                    self._add_menu_action(
                        menu, MINUS_ICON, "Remove World",
                        lambda w=world["name"]: self._remove_world(w)
                    )
                    self._add_menu_action(
                        menu, DISINTEGRATE_ICON, "Disintegrate World",
                        lambda w=world["name"]: self._disintegrate_world(w)
                    )
                    menu.addSeparator()
                    self._add_menu_action(menu, REVIVE_ICON, "Revive World", self._revive_world)
            
            elif item_type == "campaign":
                world_idx, campaign_idx = data[1], data[2]
                world = self._data[world_idx] if world_idx < len(self._data) else None
                campaign = None
                if world and campaign_idx < len(world.get("campaigns", [])):
                    campaign = world["campaigns"][campaign_idx]
                
                if campaign:
                    self._add_menu_action(
                        menu, PLUS_ICON, "New Campaign",
                        lambda idx=world_idx: self._add_campaign(idx)
                    )
                    self._add_menu_action(
                        menu, PLUS_ICON, "New Group",
                        lambda w=world_idx, c=campaign_idx: self._add_group(w, c)
                    )
                    menu.addSeparator()
                    self._add_menu_action(
                        menu, EDIT_ICON, "Edit Campaign",
                        lambda w=world_idx, c=campaign["name"]: self._edit_campaign(w, c)
                    )
                    self._add_menu_action(
                        menu, MINUS_ICON, "Remove Campaign",
                        lambda w=world_idx, c=campaign["name"]: self._remove_campaign(w, c)
                    )
                    self._add_menu_action(
                        menu, DISINTEGRATE_ICON, "Disintegrate Campaign",
                        lambda w=world_idx, c=campaign["name"]: self._disintegrate_campaign(w, c)
                    )
                    menu.addSeparator()
                    self._add_menu_action(
                        menu, REVIVE_ICON, "Revive Campaign",
                        lambda idx=world_idx: self._revive_campaign(idx)
                    )
            
            elif item_type == "group":
                world_idx, campaign_idx, group_name = data[1], data[2], data[3]
                world = self._data[world_idx] if world_idx < len(self._data) else None
                campaign = None
                if world and campaign_idx < len(world.get("campaigns", [])):
                    campaign = world["campaigns"][campaign_idx]
                
                if campaign:
                    self._add_menu_action(
                        menu, PLUS_ICON, "New Group",
                        lambda w=world_idx, c=campaign_idx: self._add_group(w, c)
                    )
                    menu.addSeparator()
                    self._add_menu_action(
                        menu, EDIT_ICON, "Edit Group",
                        lambda w=world_idx, c=campaign_idx, g=group_name: self._edit_group(w, c, g)
                    )
                    self._add_menu_action(
                        menu, MINUS_ICON, "Remove Group",
                        lambda w=world_idx, c=campaign_idx, g=group_name: self._remove_group(w, c, g)
                    )
                    self._add_menu_action(
                        menu, DISINTEGRATE_ICON, "Disintegrate Group",
                        lambda w=world_idx, c=campaign_idx, g=group_name: self._disintegrate_group(w, c, g)
                    )
                    menu.addSeparator()
                    self._add_menu_action(
                        menu, REVIVE_ICON, "Revive Group",
                        lambda w=world_idx, c=campaign_idx: self._revive_group(w, c)
                    )
        
        if menu.actions():
            menu.exec(self._tree.mapToGlobal(pos))
    
    def _add_menu_action(self, menu: QMenu, icon_path: str, text: str, callback) -> None:
        """Add an action to a menu with an icon."""
        pixmap = _load_icon(icon_path, 16)
        action = menu.addAction(QIcon(pixmap) if pixmap else QIcon(), text)
        action.triggered.connect(lambda checked=False: callback())
    
    # ----------------------------------------------------------------
    # World operations
    # ----------------------------------------------------------------
    
    def _add_world(self) -> None:
        """Add a new world."""
        name, icon = self._prompt_name_icon(
            "New World", "World name:", "", self._default_world_icon
        )
        if not name:
            return
        self._data.append({
            "name": name,
            "icon": icon or self._default_world_icon,
            "campaigns": [],
        })
        self._save_data()
        self._rebuild_tree()
    
    def _edit_world(self, old_name: str) -> None:
        """Edit an existing world."""
        world = next((w for w in self._data if w["name"] == old_name), None)
        if not world:
            return
        new_name, icon = self._prompt_name_icon(
            "Edit World", "New world name:", old_name, world.get("icon")
        )
        if not new_name:
            return
        world["name"] = new_name
        world["icon"] = icon or world.get("icon") or self._default_world_icon
        self._save_data()
        self._rebuild_tree()
    
    def _remove_world(self, name: str) -> None:
        """Remove a world (move to trash)."""
        world = next((w for w in self._data if w["name"] == name), None)
        if not world:
            return
        self._move_to_trash("world", world)
        self._data = [w for w in self._data if w["name"] != name]
        self._save_data()
        self._rebuild_tree()
    
    def _disintegrate_world(self, name: str) -> None:
        """Permanently delete a world."""
        if not self._confirm_disintegrate(
            "Disintegrate World",
            f"Type CONFIRM to permanently delete '{name}'. This cannot be undone."
        ):
            return
        self._data = [w for w in self._data if w["name"] != name]
        self._save_data()
        self._rebuild_tree()
    
    def _revive_world(self) -> None:
        """Revive a world from trash."""
        existing = {w["name"] for w in self._data}
        entries = [
            e for e in self._trash
            if e.get("type") == "world" and e.get("name") not in existing
        ]
        if not entries:
            QMessageBox.information(self, "No Worlds", "No worlds are eligible to revive.")
            return
        entry = self._select_trash_entry("Revive World", "Select a world to revive:", entries)
        if not entry:
            return
        payload = entry.get("payload", {})
        if not payload.get("name"):
            return
        self._data.append(self._normalize_world(payload))
        self._trash.remove(entry)
        self._save_trash()
        self._save_data()
        self._rebuild_tree()
    
    # ----------------------------------------------------------------
    # Campaign operations
    # ----------------------------------------------------------------
    
    def _add_campaign(self, world_idx: int) -> None:
        """Add a new campaign to a world."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        name, icon = self._prompt_name_icon(
            "New Campaign", "Campaign name:", "", self._default_campaign_icon
        )
        if not name:
            return
        world["campaigns"].append({
            "name": name,
            "icon": icon or self._default_campaign_icon,
            "groups": [],
        })
        self._save_data()
        self._rebuild_tree()
    
    def _edit_campaign(self, world_idx: int, old_name: str) -> None:
        """Edit an existing campaign."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        campaign = next((c for c in world["campaigns"] if c["name"] == old_name), None)
        if not campaign:
            return
        new_name, icon = self._prompt_name_icon(
            "Edit Campaign", "New campaign name:", old_name, campaign.get("icon")
        )
        if not new_name:
            return
        campaign["name"] = new_name
        campaign["icon"] = icon or campaign.get("icon") or self._default_campaign_icon
        self._save_data()
        self._rebuild_tree()
    
    def _remove_campaign(self, world_idx: int, name: str) -> None:
        """Remove a campaign (move to trash)."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        campaign = next((c for c in world["campaigns"] if c["name"] == name), None)
        if not campaign:
            return
        self._move_to_trash("campaign", campaign, parent={"world": world["name"]})
        world["campaigns"] = [c for c in world["campaigns"] if c["name"] != name]
        self._save_data()
        self._rebuild_tree()
    
    def _disintegrate_campaign(self, world_idx: int, name: str) -> None:
        """Permanently delete a campaign."""
        if world_idx >= len(self._data):
            return
        if not self._confirm_disintegrate(
            "Disintegrate Campaign",
            f"Type CONFIRM to permanently delete '{name}'. This cannot be undone."
        ):
            return
        world = self._data[world_idx]
        world["campaigns"] = [c for c in world["campaigns"] if c["name"] != name]
        self._save_data()
        self._rebuild_tree()
    
    def _revive_campaign(self, world_idx: int) -> None:
        """Revive a campaign from trash."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        existing = {c["name"] for c in world["campaigns"]}
        entries = [
            e for e in self._trash
            if e.get("type") == "campaign"
            and e.get("parent", {}).get("world") == world["name"]
            and e.get("name") not in existing
        ]
        if not entries:
            QMessageBox.information(self, "No Campaigns", "No campaigns are eligible to revive.")
            return
        entry = self._select_trash_entry("Revive Campaign", "Select a campaign to revive:", entries)
        if not entry:
            return
        payload = entry.get("payload", {})
        if not payload.get("name"):
            return
        world["campaigns"].append(self._normalize_campaign(payload))
        self._trash.remove(entry)
        self._save_trash()
        self._save_data()
        self._rebuild_tree()
    
    # ----------------------------------------------------------------
    # Group operations
    # ----------------------------------------------------------------
    
    def _add_group(self, world_idx: int, campaign_idx: int) -> None:
        """Add a new group to a campaign."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        if campaign_idx >= len(world.get("campaigns", [])):
            return
        campaign = world["campaigns"][campaign_idx]
        name, icon = self._prompt_name_icon(
            "New Group", "Group name:", "", self._default_group_icon
        )
        if not name:
            return
        campaign["groups"].append({
            "name": name,
            "icon": icon or self._default_group_icon,
        })
        self._save_data()
        self._rebuild_tree()
    
    def _edit_group(self, world_idx: int, campaign_idx: int, old_name: str) -> None:
        """Edit an existing group."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        if campaign_idx >= len(world.get("campaigns", [])):
            return
        campaign = world["campaigns"][campaign_idx]
        group = next((g for g in campaign["groups"] if g["name"] == old_name), None)
        if not group:
            return
        new_name, icon = self._prompt_name_icon(
            "Edit Group", "New group name:", old_name, group.get("icon")
        )
        if not new_name:
            return
        group["name"] = new_name
        group["icon"] = icon or group.get("icon") or self._default_group_icon
        self._save_data()
        self._rebuild_tree()
    
    def _remove_group(self, world_idx: int, campaign_idx: int, name: str) -> None:
        """Remove a group (move to trash)."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        if campaign_idx >= len(world.get("campaigns", [])):
            return
        campaign = world["campaigns"][campaign_idx]
        group = next((g for g in campaign["groups"] if g["name"] == name), None)
        if not group:
            return
        self._move_to_trash(
            "group", group,
            parent={"world": world["name"], "campaign": campaign["name"]}
        )
        campaign["groups"] = [g for g in campaign["groups"] if g["name"] != name]
        self._save_data()
        self._rebuild_tree()
    
    def _disintegrate_group(self, world_idx: int, campaign_idx: int, name: str) -> None:
        """Permanently delete a group."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        if campaign_idx >= len(world.get("campaigns", [])):
            return
        if not self._confirm_disintegrate(
            "Disintegrate Group",
            f"Type CONFIRM to permanently delete '{name}'. This cannot be undone."
        ):
            return
        campaign = world["campaigns"][campaign_idx]
        campaign["groups"] = [g for g in campaign["groups"] if g["name"] != name]
        self._save_data()
        self._rebuild_tree()
    
    def _revive_group(self, world_idx: int, campaign_idx: int) -> None:
        """Revive a group from trash."""
        if world_idx >= len(self._data):
            return
        world = self._data[world_idx]
        if campaign_idx >= len(world.get("campaigns", [])):
            return
        campaign = world["campaigns"][campaign_idx]
        existing = {g["name"] for g in campaign["groups"]}
        entries = [
            e for e in self._trash
            if e.get("type") == "group"
            and e.get("parent", {}).get("world") == world["name"]
            and e.get("parent", {}).get("campaign") == campaign["name"]
            and e.get("name") not in existing
        ]
        if not entries:
            QMessageBox.information(self, "No Groups", "No groups are eligible to revive.")
            return
        entry = self._select_trash_entry("Revive Group", "Select a group to revive:", entries)
        if not entry:
            return
        payload = entry.get("payload", {})
        if not payload.get("name"):
            return
        campaign["groups"].append(self._normalize_group(payload))
        self._trash.remove(entry)
        self._save_trash()
        self._save_data()
        self._rebuild_tree()
    
    # ----------------------------------------------------------------
    # Dialogs and helpers
    # ----------------------------------------------------------------
    
    def _prompt_name_icon(
        self, title: str, label: str, default_name: str, default_icon: Optional[str]
    ) -> tuple[Optional[str], Optional[str]]:
        """Show dialog for name and icon input."""
        dialog = NameIconDialog(
            title, label, self._icon_paths,
            default_name=default_name,
            default_icon=default_icon,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None, None
        name, icon = dialog.values()
        return name, icon or default_icon
    
    def _select_trash_entry(
        self, title: str, label: str, entries: list[dict]
    ) -> Optional[dict]:
        """Show dialog to select a trash entry."""
        items = []
        for entry in entries:
            name = entry.get("name", "")
            icon = entry.get("icon")
            parent = entry.get("parent", {})
            if entry["type"] == "campaign":
                display = f"{name} · {parent.get('world', 'Unknown')}"
            elif entry["type"] == "group":
                display = f"{name} · {parent.get('campaign', '?')} / {parent.get('world', '?')}"
            else:
                display = name
            items.append((display, icon, entry))
        
        dialog = IconListDialog(title, label, items, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected
    
    def _confirm_disintegrate(self, title: str, message: str) -> bool:
        """Show confirmation dialog for permanent deletion."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        
        input_field = QLineEdit()
        input_field.setPlaceholderText("Type CONFIRM to continue")
        layout.addWidget(input_field)
        
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        return input_field.text().strip() == "CONFIRM"
    
    def _normalize_group(self, group: object) -> dict:
        """Normalize a group entry."""
        if isinstance(group, dict):
            name = str(group.get("name", "")).strip()
            icon = group.get("icon") or self._default_group_icon
            return {"name": name, "icon": icon}
        name = str(group).strip()
        return {"name": name, "icon": self._default_group_icon}
    
    def _normalize_campaign(self, campaign: dict) -> dict:
        """Normalize a campaign entry."""
        name = str(campaign.get("name", "")).strip()
        icon = campaign.get("icon") or self._default_campaign_icon
        groups = []
        for group in campaign.get("groups", []):
            normalized = self._normalize_group(group)
            if normalized["name"]:
                groups.append(normalized)
        return {"name": name, "icon": icon, "groups": groups}
    
    def _normalize_world(self, world: dict) -> dict:
        """Normalize a world entry."""
        name = str(world.get("name", "")).strip()
        icon = world.get("icon") or self._default_world_icon
        campaigns = []
        for campaign in world.get("campaigns", []):
            normalized = self._normalize_campaign(campaign)
            if normalized["name"]:
                campaigns.append(normalized)
        return {"name": name, "icon": icon, "campaigns": campaigns}


