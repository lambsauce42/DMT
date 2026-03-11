from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta
from typing import Callable, Optional

from PySide6.QtCore import QCoreApplication, QEasingCurve, QPropertyAnimation, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from asset_paths import icons_dir
try:
    import shiboken6
except Exception:  # pragma: no cover - optional runtime guard
    shiboken6 = None

try:
    from PySide6.QtSvg import QSvgRenderer

    SVG_AVAILABLE = True
except Exception:
    SVG_AVAILABLE = False

ICON_DIR = str(icons_dir())
ROW_ICON_SIZE = 22
LARGE_ROW_ICON_SIZE = int(ROW_ICON_SIZE * 1.5)
LARGE_ROW_PADDING_X = 15
LARGE_ROW_PADDING_Y = 12
CARET_ICON_SIZE = 12
ACTION_ICON_SIZE = 14
ANIMATION_MS = 180
# Qt's internal "unbounded" widget dimension sentinel.
WIDGET_SIZE_MAX = 16777215
CARET_DOWN_ICON = os.path.join(ICON_DIR, "caret_down.svg")
CARET_UP_ICON = os.path.join(ICON_DIR, "caret_up.svg")
PLUS_ICON = os.path.join(ICON_DIR, "plus.svg")
MINUS_ICON = os.path.join(ICON_DIR, "minus.svg")
EDIT_ICON = os.path.join(ICON_DIR, "edit.svg")
DISINTEGRATE_ICON = os.path.join(ICON_DIR, "disintegrate.svg")
REVIVE_ICON = os.path.join(ICON_DIR, "revive.svg")
TRASH_RETENTION_DAYS = 30
from save_paths import trash_json_path, navigation_json_path
from navigation_repository import (
    campaign_trash_entry_matches_world,
    clean_navigation_id,
    group_trash_entry_matches_campaign,
    load_navigation_data as shared_load_navigation_data,
    load_trash as shared_load_trash,
    move_to_trash as shared_move_to_trash,
    normalize_campaign_entry,
    normalize_group_entry,
    normalize_world_entry,
    save_navigation_data as shared_save_navigation_data,
    save_trash as shared_save_trash,
)
TRASH_RETENTION_DAYS = 30
TRASH_PATH = trash_json_path()
NAVIGATION_PATH = str(navigation_json_path())




def load_trash(path: Optional[str] = None) -> list[dict]:
    return shared_load_trash(path=path or TRASH_PATH)


def save_trash(entries: list[dict], path: Optional[str] = None) -> None:
    shared_save_trash(entries, path=path or TRASH_PATH)





def save_navigation_data(data: list) -> None:
    shared_save_navigation_data(data, navigation_path=NAVIGATION_PATH)


def load_navigation_data() -> list:
    return shared_load_navigation_data(navigation_path=NAVIGATION_PATH)


def move_to_trash(
    entry_type: str,
    payload: dict,
    parent: Optional[dict] = None,
    path: Optional[str] = None,
) -> dict:
    return shared_move_to_trash(
        entry_type,
        payload,
        parent=parent,
        path=path or TRASH_PATH,
    )

def _load_icon(path: str, size: int) -> Optional[QPixmap]:
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


def _make_action_button(icon_path: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setObjectName("NavActionButton")
    
    # Set action property for consistent coloring based on icon filename
    icon_name = os.path.basename(icon_path).lower()
    if "plus" in icon_name:
        button.setProperty("action", "add")
    elif "minus" in icon_name:
        button.setProperty("action", "delete")
    elif "revive" in icon_name:
        button.setProperty("action", "revive")
    elif "disintegrate" in icon_name:
        button.setProperty("action", "disintegrate")
        
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setToolTip(tooltip)
    pixmap = _load_icon(icon_path, ACTION_ICON_SIZE)
    if pixmap:
        button.setIcon(QIcon(pixmap))
        button.setIconSize(QSize(ACTION_ICON_SIZE, ACTION_ICON_SIZE))
    else:
        button.setText(tooltip[:1])
    button.setAutoRaise(False)
    button.setMinimumSize(32, 32)
    return button


def _list_icon_paths() -> list[str]:
    if not os.path.isdir(ICON_DIR):
        return []
    ignored = {
        "caret_down.svg",
        "caret_up.svg",
        "plus.svg",
        "minus.svg",
        "edit.svg",
        "disintegrate.svg",
        "revive.svg",
    }
    return [
        os.path.join(ICON_DIR, name)
        for name in sorted(os.listdir(ICON_DIR))
        if name.lower().endswith((".png", ".svg")) and name not in ignored
    ]


class NameIconDialog(QDialog):
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
        self._selected_icon: Optional[str] = default_icon
        self.setWindowTitle(title)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        label_widget = QLabel(label)
        label_widget.setObjectName("Subheader")
        layout.addWidget(label_widget)

        self._name_input = QLineEdit(default_name)
        self._name_input.setObjectName("NameInputField")
        self._name_input.textChanged.connect(self._clear_name_warning)
        layout.addWidget(self._name_input)

        self._name_warning = QLabel("Please enter a name or cancel.")
        self._name_warning.setObjectName("NameValidationError")
        self._name_warning.setStyleSheet("color: #e5534b;")
        self._name_warning.setVisible(False)
        layout.addWidget(self._name_warning)

        icon_label = QLabel("Icon")
        icon_label.setObjectName("Subheader")
        layout.addWidget(icon_label)

        self._icon_list = QListWidget()
        self._icon_list.setObjectName("IconPickerList")
        self._icon_list.setViewMode(QListView.ViewMode.IconMode)
        self._icon_list.setFlow(QListView.Flow.LeftToRight)
        self._icon_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._icon_list.setMovement(QListView.Movement.Static)
        self._icon_list.setWrapping(True)
        self._icon_list.setSpacing(8)
        self._icon_list.setIconSize(QSize(28, 28))
        self._icon_list.setUniformItemSizes(True)
        self._icon_list.setGridSize(QSize(68, 68))
        self._icon_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._icon_list.itemClicked.connect(self._on_icon_clicked)
        layout.addWidget(self._icon_list, 1)

        self._custom_item: Optional[QListWidgetItem] = None
        for path in icon_paths:
            pixmap = _load_icon(path, 28)
            if not pixmap:
                continue
            item = QListWidgetItem(QIcon(pixmap), os.path.splitext(os.path.basename(path))[0])
            item.setSizeHint(QSize(64, 64))
            item.setData(Qt.ItemDataRole.UserRole, path)
            self._icon_list.addItem(item)
            if default_icon and path == default_icon:
                self._icon_list.setCurrentItem(item)

        icon_actions = QHBoxLayout()
        icon_actions.setContentsMargins(0, 0, 0, 0)
        icon_actions.setSpacing(8)
        icon_actions.addStretch(1)
        custom_button = _make_action_button(PLUS_ICON, "Custom Icon")
        custom_button.clicked.connect(self._choose_custom_icon)
        icon_actions.addWidget(custom_button)
        layout.addLayout(icon_actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _clear_name_warning(self) -> None:
        if self._name_warning.isVisible():
            self._name_warning.setVisible(False)

    def _on_accept(self) -> None:
        if not self._name_input.text().strip():
            self._name_warning.setVisible(True)
            self._name_input.setFocus()
            return
        self.accept()

    def _on_icon_clicked(self, item: QListWidgetItem) -> None:
        self._selected_icon = item.data(Qt.ItemDataRole.UserRole)

    def _choose_custom_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Icon",
            os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.svg)",
        )
        if not path:
            return
        pixmap = _load_icon(path, 28)
        if not pixmap:
            QMessageBox.warning(self, "Invalid Icon", "Unable to load the selected icon.")
            return
        if self._custom_item is None:
            self._custom_item = QListWidgetItem(QIcon(pixmap), "Custom")
            self._custom_item.setSizeHint(QSize(64, 64))
            self._icon_list.insertItem(0, self._custom_item)
        else:
            self._custom_item.setIcon(QIcon(pixmap))
        self._custom_item.setData(Qt.ItemDataRole.UserRole, path)
        self._icon_list.setCurrentItem(self._custom_item)
        self._selected_icon = path

    def values(self) -> tuple[str, Optional[str]]:
        return self._name_input.text().strip(), self._selected_icon


class IconListDialog(QDialog):
    def __init__(
        self,
        title: str,
        label: str,
        items: list[tuple],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._selected: Optional[object] = None
        self.setWindowTitle(title)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        label_widget = QLabel(label)
        label_widget.setObjectName("Subheader")
        layout.addWidget(label_widget)

        self._list = QListWidget()
        self._list.setObjectName("IconSelectList")
        self._list.setIconSize(QSize(26, 26))
        self._list.setUniformItemSizes(True)
        self._list.setSpacing(6)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        for item_data in items:
            if len(item_data) == 2:
                name, icon_path = item_data
                value = name
            else:
                name, icon_path, value = item_data
            pixmap = _load_icon(icon_path or "", 26) if icon_path else None
            item = QListWidgetItem(QIcon(pixmap) if pixmap else QIcon(), name)
            item.setSizeHint(QSize(0, 36))
            item.setData(Qt.ItemDataRole.UserRole, value)
            self._list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._selected = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    @property
    def selected(self) -> Optional[object]:
        return self._selected


class DashedHeaderRow(QWidget):
    add_clicked = Signal()
    edit_clicked = Signal()
    remove_clicked = Signal()
    disintegrate_clicked = Signal()
    revive_clicked = Signal()

    def __init__(self, title: str, add_tooltip: str, remove_tooltip: str) -> None:
        super().__init__()
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)

        center_row = QWidget()
        center_layout = QHBoxLayout(center_row)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        line_left = QFrame()
        line_left.setObjectName("SectionLineDashed")
        line_left.setFixedHeight(1)
        line_left.setFixedWidth(28)
        line_left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        label = QLabel(title)
        label.setObjectName("SectionHeader")
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        line_right = QFrame()
        line_right.setObjectName("SectionLineDashed")
        line_right.setFixedHeight(1)
        line_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        center_layout.addWidget(line_left)
        center_layout.addWidget(label)
        center_layout.addWidget(line_right)

        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)
        add_button = _make_action_button(PLUS_ICON, add_tooltip)
        edit_button = _make_action_button(EDIT_ICON, "Edit")
        remove_button = _make_action_button(MINUS_ICON, remove_tooltip)
        disintegrate_button = _make_action_button(DISINTEGRATE_ICON, "Disintegrate")
        revive_button = _make_action_button(REVIVE_ICON, "Revive")
        add_button.clicked.connect(lambda checked=False: self.add_clicked.emit())
        edit_button.clicked.connect(lambda checked=False: self.edit_clicked.emit())
        remove_button.clicked.connect(lambda checked=False: self.remove_clicked.emit())
        disintegrate_button.clicked.connect(
            lambda checked=False: self.disintegrate_clicked.emit()
        )
        revive_button.clicked.connect(lambda checked=False: self.revive_clicked.emit())
        actions_layout.addWidget(edit_button)
        actions_layout.addWidget(add_button)
        actions_layout.addWidget(remove_button)
        actions_layout.addWidget(revive_button)
        actions_layout.addWidget(disintegrate_button)

        layout.addWidget(center_row, 0, 0)
        layout.addWidget(actions, 0, 0, Qt.AlignmentFlag.AlignRight)


class NavRow(QFrame):
    clicked = Signal()

    def __init__(
        self,
        title: str,
        icon_path: Optional[str],
        show_arrow: bool,
        icon_size: int = ROW_ICON_SIZE,
        padding_x: int = 10,
        padding_y: int = 6,
    ) -> None:
        super().__init__()
        self._show_arrow = show_arrow
        self._arrow_label: Optional[QLabel] = None
        self._caret_down = _load_icon(CARET_DOWN_ICON, CARET_ICON_SIZE)
        self._caret_up = _load_icon(CARET_UP_ICON, CARET_ICON_SIZE)
        self._context_edit = None
        self._context_delete = None
        self._context_disintegrate = None
        self._icon_size = icon_size
        self.setObjectName("NavRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(padding_x, padding_y, padding_x, padding_y)
        layout.setSpacing(8)

        icon_label = QLabel()
        icon_label.setFixedSize(self._icon_size + 6, self._icon_size + 6)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setObjectName("NavIcon")
        icon_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        pixmap = _load_icon(icon_path, self._icon_size) if icon_path else None
        if pixmap:
            icon_label.setPixmap(pixmap)
        else:
            icon_label.setText("*")
        layout.addWidget(icon_label)

        text_label = QLabel(title)
        text_label.setObjectName("NavTitle")
        text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(text_label, 1)

        if self._show_arrow:
            self._arrow_label = QLabel()
            self._arrow_label.setObjectName("NavArrow")
            self._arrow_label.setFixedSize(CARET_ICON_SIZE + 6, CARET_ICON_SIZE + 6)
            self._arrow_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._arrow_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            layout.addWidget(self._arrow_label)
            self.set_expanded(False)

    def set_expanded(self, expanded: bool) -> None:
        if self._arrow_label is not None:
            if self._caret_down and self._caret_up:
                self._arrow_label.setPixmap(self._caret_up if expanded else self._caret_down)
            else:
                self._arrow_label.setText("^" if expanded else "v")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_context_actions(
        self,
        edit_action,
        delete_action,
        disintegrate_action,
    ) -> None:
        self._context_edit = edit_action
        self._context_delete = delete_action
        self._context_disintegrate = disintegrate_action

    def contextMenuEvent(self, event) -> None:
        if not any([self._context_edit, self._context_delete, self._context_disintegrate]):
            return
        menu = QMenu(self)
        if self._context_edit:
            icon = _load_icon(EDIT_ICON, ACTION_ICON_SIZE)
            action = menu.addAction(QIcon(icon) if icon else QIcon(), "Edit")
            action.triggered.connect(lambda checked=False: self._context_edit())
        if self._context_delete:
            icon = _load_icon(MINUS_ICON, ACTION_ICON_SIZE)
            action = menu.addAction(QIcon(icon) if icon else QIcon(), "Delete")
            action.triggered.connect(lambda checked=False: self._context_delete())
        if self._context_disintegrate:
            icon = _load_icon(DISINTEGRATE_ICON, ACTION_ICON_SIZE)
            action = menu.addAction(QIcon(icon) if icon else QIcon(), "Disintegrate")
            action.triggered.connect(lambda checked=False: self._context_disintegrate())
        menu.exec(event.globalPos())


class NavItemRow(NavRow):
    def __init__(self, title: str, icon_path: Optional[str]) -> None:
        super().__init__(title, icon_path, show_arrow=False)
        self.setObjectName("NavItemRow")

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)


class CollapsibleSection(QWidget):
    def __init__(
        self,
        title: str,
        icon_path: Optional[str],
        indent: int = 0,
        expanded: bool = False,
        duration_ms: int = ANIMATION_MS,
        row_icon_size: int = ROW_ICON_SIZE,
        row_padding_x: int = 10,
        row_padding_y: int = 6,
    ) -> None:
        super().__init__()
        self.title = title
        self._expanded = expanded
        self._duration_ms = duration_ms

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._header = NavRow(
            title,
            icon_path,
            show_arrow=True,
            icon_size=row_icon_size,
            padding_x=row_padding_x,
            padding_y=row_padding_y,
        )
        self._header.set_expanded(expanded)
        self._header.clicked.connect(self.toggle)
        layout.addWidget(self._header)

        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(indent, 4, 0, 0)
        self._content_layout.setSpacing(6)
        self._content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._content.setMaximumHeight(0 if not expanded else self._content.sizeHint().height())
        layout.addWidget(self._content)

        self._animation = QPropertyAnimation(self._content, b"maximumHeight", self)
        self._animation.setDuration(self._duration_ms)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.finished.connect(self._on_animation_finished)
        self.destroyed.connect(self._on_destroyed)

    @property
    def expanded(self) -> bool:
        return self._expanded

    @property
    def content_widget(self) -> QWidget:
        return self._content

    def add_widget(self, widget: QWidget) -> None:
        self._content_layout.addWidget(widget)

    def set_expanded(self, expanded: bool, animate: bool = True) -> None:
        if expanded == self._expanded:
            return
        self._expanded = expanded
        self._header.set_expanded(expanded)
        self._content_layout.activate()
        content_height = self._content_layout.sizeHint().height()
        target = content_height if expanded else 0
        if not animate or self._duration_ms <= 0:
            self._animation.stop()
            self._content.setMaximumHeight(target)
            if expanded:
                self._content.setMaximumHeight(WIDGET_SIZE_MAX)
            return
        self._animation.stop()
        if expanded:
            start_height = self._content.maximumHeight()
        else:
            start_height = content_height
            self._content.setMaximumHeight(start_height)
        self._animation.setStartValue(start_height)
        self._animation.setEndValue(target)
        self._animation.start()

    def toggle(self) -> None:
        self.set_expanded(not self._expanded, animate=True)

    def _on_animation_finished(self) -> None:
        if self._expanded:
            self._content.setMaximumHeight(WIDGET_SIZE_MAX)
        else:
            self._content.setMaximumHeight(0)

    def _on_destroyed(self, *_args) -> None:
        self._dispose_animation()

    def _dispose_animation(self) -> None:
        try:
            self._animation.stop()
        except Exception:
            pass
        try:
            self._animation.finished.disconnect(self._on_animation_finished)
        except Exception:
            pass
        try:
            self._animation.setTargetObject(None)
        except Exception:
            pass

    def set_context_actions(
        self,
        edit_action,
        delete_action,
        disintegrate_action,
    ) -> None:
        self._header.set_context_actions(edit_action, delete_action, disintegrate_action)


class NavigateContentWidget(QWidget):
    def __init__(self, show_worlds_header: bool = True) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._show_worlds_header = show_worlds_header
        self._launch_session_callback: Optional[Callable[[str, str, str], None]] = None
        self._icon_paths = _list_icon_paths()
        self._default_world_icon = os.path.join(ICON_DIR, "navigate.png")
        self._default_campaign_icon = os.path.join(ICON_DIR, "mapselector.png")
        self._default_group_icon = os.path.join(ICON_DIR, "charactersheets.png")
        self._trash: list[dict] = []
        self._data = []
        
        # Load from persistent storage
        loaded_data = load_navigation_data()
        
        for world in loaded_data:
            if not isinstance(world, dict):
                continue
            normalized = normalize_world_entry(
                world,
                default_icon=self._default_world_icon,
                default_campaign_icon=self._default_campaign_icon,
                default_group_icon=self._default_group_icon,
            )
            if normalized["name"]:
                self._data.append(normalized)

        self.worlds_section: Optional[CollapsibleSection] = None
        self.world_sections: list[CollapsibleSection] = []

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._load_trash()
        self._rebuild()

    def set_launch_session_callback(
        self, callback: Optional[Callable[[str, str, str], None]]
    ) -> None:
        self._launch_session_callback = callback

    def expand_worlds(self, expanded: bool, animate: bool = True) -> None:
        if self.worlds_section is None:
            return
        self.worlds_section.set_expanded(expanded, animate=animate)

    def add_world(self, name: Optional[str] = None) -> None:
        if name is None:
            name, icon = self._prompt_name_icon(
                "New World",
                "World name:",
                "",
                self._default_world_icon,
            )
        else:
            name = name.strip()
            icon = self._default_world_icon
        if not name:
            return
        expansion_state = self._capture_expansion_state()
        expansion_state["worlds_section"] = True
        expansion_state["worlds"][name] = True
        self._data.append({"name": name, "icon": icon, "campaigns": []})
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def remove_world(self, name: Optional[int | str] = None) -> None:
        if not self._data:
            if name is not None:
                return
            QMessageBox.information(self, "No Worlds", "There are no worlds to remove.")
            return
        if name is None:
            name = self._select_item(
                "Remove World",
                "Click a world to remove it.",
                [(world["name"], world.get("icon")) for world in self._data],
            )
        if name is None:
            return
        if isinstance(name, str) and not name.strip():
            return
        expansion_state = self._capture_expansion_state()
        world_index = self._resolve_world_index(name)
        if world_index is None:
            return
        world = self._data[world_index]
        world_name = str(world.get("name", ""))
        self._move_to_trash("world", world)
        del self._data[world_index]
        save_navigation_data(self._data)
        expansion_state.get("worlds", {}).pop(world_name, None)
        self._rebuild(expansion_state)

    def edit_world(self, old_name: Optional[str] = None, new_name: Optional[str] = None) -> None:
        if not self._data:
            QMessageBox.information(self, "No Worlds", "There are no worlds to edit.")
            return
        if old_name is None:
            old_name = self._select_item(
                "Edit World",
                "Click a world to edit it.",
                [(world["name"], world.get("icon")) for world in self._data],
            )
        if not old_name:
            return
        icon = None
        for world in self._data:
            if world["name"] == old_name:
                icon = world.get("icon") or self._default_world_icon
                break
        if new_name is None:
            new_name, icon = self._prompt_name_icon(
                "Edit World",
                "New world name:",
                old_name,
                icon or self._default_world_icon,
            )
        else:
            new_name = new_name.strip()
        if not new_name:
            return
        for world in self._data:
            if world["name"] == old_name:
                world["name"] = new_name
                new_icon = icon or world.get("icon") or self._default_world_icon
                world["icon"] = new_icon
                break
        expansion_state = self._capture_expansion_state()
        if old_name != new_name:
            was_expanded = expansion_state.get("worlds", {}).pop(old_name, None)
            if was_expanded is not None:
                expansion_state["worlds"][new_name] = was_expanded
            updated_campaigns = {}
            for (world_name, campaign_name), expanded in expansion_state.get("campaigns", {}).items():
                if world_name == old_name:
                    updated_campaigns[(new_name, campaign_name)] = expanded
                else:
                    updated_campaigns[(world_name, campaign_name)] = expanded
            expansion_state["campaigns"] = updated_campaigns
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def disintegrate_world(self, name: Optional[int | str] = None) -> None:
        if not self._data:
            QMessageBox.information(self, "No Worlds", "There are no worlds to delete.")
            return
        if name is None:
            name = self._select_item(
                "Disintegrate World",
                "Click a world to delete permanently.",
                [(world["name"], world.get("icon")) for world in self._data],
            )
        if name is None:
            return
        if isinstance(name, str) and not name.strip():
            return
        if not self._confirm_disintegrate(
            "Disintegrate World",
            f"Type CONFIRM to permanently delete '{name}'. This cannot be undone.",
        ):
            return
        expansion_state = self._capture_expansion_state()
        world_index = self._resolve_world_index(name)
        if world_index is None:
            return
        world_name = str(self._data[world_index].get("name", ""))
        del self._data[world_index]
        save_navigation_data(self._data)
        expansion_state.get("worlds", {}).pop(world_name, None)
        self._rebuild(expansion_state)

    def revive_world(self, name: Optional[str] = None) -> None:
        if not self._trash:
            QMessageBox.information(self, "Trash Empty", "There are no worlds to revive.")
            return
        existing = {world["name"] for world in self._data}
        entries = [
            entry
            for entry in self._trash
            if entry.get("type") == "world" and entry.get("name") not in existing
        ]
        if not entries:
            QMessageBox.information(self, "No Worlds", "No worlds are eligible to revive.")
            return
        entry = None
        if name is not None:
            entry = next((item for item in entries if item.get("name") == name), None)
        if entry is None:
            entry = self._select_trash_entry(
                "Revive World",
                "Click a world to revive it.",
                entries,
            )
        if not entry:
            return
        payload = self._normalize_world(entry.get("payload") or {})
        if not payload.get("name"):
            QMessageBox.warning(self, "Invalid Entry", "Selected world is missing a name.")
            return
        if payload["name"] in existing:
            QMessageBox.warning(self, "Name Conflict", "A world with that name already exists.")
            return
        expansion_state = self._capture_expansion_state()
        expansion_state["worlds_section"] = True
        expansion_state["worlds"][payload["name"]] = True
        self._data.append(payload)
        self._trash.remove(entry)
        self._save_trash()
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _add_campaign(self, world_index: int, name: Optional[str] = None) -> None:
        world = self._get_world(world_index)
        if world is None:
            return
        if name is None:
            name, icon = self._prompt_name_icon(
                "New Campaign",
                "Campaign name:",
                "",
                self._default_campaign_icon,
            )
        else:
            name = name.strip()
            icon = self._default_campaign_icon
        if not name:
            return
        expansion_state = self._capture_expansion_state()
        expansion_state["worlds_section"] = True
        expansion_state["worlds"][world["name"]] = True
        expansion_state["campaigns"][(world["name"], name)] = True
        world["campaigns"].append({"name": name, "icon": icon, "groups": []})
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _remove_campaign(self, world_index: int, name: Optional[int | str] = None) -> None:
        world = self._get_world(world_index)
        if world is None:
            return
        campaigns = world["campaigns"]
        if not campaigns:
            QMessageBox.information(self, "No Campaigns", "There are no campaigns to remove.")
            return
        if name is None:
            name = self._select_item(
                "Remove Campaign",
                "Click a campaign to remove it.",
                [(camp["name"], camp.get("icon")) for camp in campaigns],
            )
        if name is None:
            return
        if isinstance(name, str) and not name.strip():
            return
        expansion_state = self._capture_expansion_state()
        campaign_index = self._resolve_campaign_index(world, name)
        if campaign_index is None:
            return
        campaign = campaigns[campaign_index]
        campaign_name = str(campaign.get("name", ""))
        if campaign:
            parent = {"world": world["name"]}
            world_id = clean_navigation_id(world.get("id"))
            if world_id:
                parent["world_id"] = world_id
            campaign_payload = copy.deepcopy(campaign)
            if world_id and not clean_navigation_id(campaign_payload.get("world_id")):
                campaign_payload["world_id"] = world_id
            self._move_to_trash(
                "campaign",
                campaign_payload,
                parent=parent,
            )
        del world["campaigns"][campaign_index]
        expansion_state.get("campaigns", {}).pop((world["name"], campaign_name), None)
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _edit_campaign(
        self,
        world_index: int,
        old_name: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> None:
        world = self._get_world(world_index)
        if world is None:
            return
        campaigns = world["campaigns"]
        if not campaigns:
            QMessageBox.information(self, "No Campaigns", "There are no campaigns to edit.")
            return
        if old_name is None:
            old_name = self._select_item(
                "Edit Campaign",
                "Click a campaign to edit it.",
                [(camp["name"], camp.get("icon")) for camp in campaigns],
            )
        if not old_name:
            return
        icon = None
        for campaign in campaigns:
            if campaign["name"] == old_name:
                icon = campaign.get("icon") or self._default_campaign_icon
                break
        if new_name is None:
            new_name, icon = self._prompt_name_icon(
                "Edit Campaign",
                "New campaign name:",
                old_name,
                icon or self._default_campaign_icon,
            )
        else:
            new_name = new_name.strip()
        if not new_name:
            return
        for campaign in campaigns:
            if campaign["name"] == old_name:
                campaign["name"] = new_name
                campaign["icon"] = icon or campaign.get("icon") or self._default_campaign_icon
                break
        expansion_state = self._capture_expansion_state()
        if old_name != new_name:
            key_old = (world["name"], old_name)
            key_new = (world["name"], new_name)
            was_expanded = expansion_state.get("campaigns", {}).pop(key_old, None)
            if was_expanded is not None:
                expansion_state["campaigns"][key_new] = was_expanded
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _disintegrate_campaign(self, world_index: int, name: Optional[int | str] = None) -> None:
        world = self._get_world(world_index)
        if world is None:
            return
        campaigns = world["campaigns"]
        if not campaigns:
            QMessageBox.information(self, "No Campaigns", "There are no campaigns to delete.")
            return
        if name is None:
            name = self._select_item(
                "Disintegrate Campaign",
                "Click a campaign to delete permanently.",
                [(camp["name"], camp.get("icon")) for camp in campaigns],
            )
        if name is None:
            return
        if isinstance(name, str) and not name.strip():
            return
        if not self._confirm_disintegrate(
            "Disintegrate Campaign",
            f"Type CONFIRM to permanently delete '{name}'. This cannot be undone.",
        ):
            return
        expansion_state = self._capture_expansion_state()
        campaign_index = self._resolve_campaign_index(world, name)
        if campaign_index is None:
            return
        campaign_name = str(campaigns[campaign_index].get("name", ""))
        del world["campaigns"][campaign_index]
        expansion_state.get("campaigns", {}).pop((world["name"], campaign_name), None)
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _revive_campaign(self, world_index: int, name: Optional[str] = None) -> None:
        world = self._get_world(world_index)
        if world is None:
            return
        existing = {camp["name"] for camp in world["campaigns"]}
        candidates = [
            entry
            for entry in self._trash
            if entry.get("type") == "campaign"
            and entry.get("name") not in existing
        ]
        entries = [
            entry
            for entry in candidates
            if campaign_trash_entry_matches_world(
                entry,
                world,
                allow_renamed_legacy=False,
            )
        ]
        if not entries:
            entries = [
                entry
                for entry in candidates
                if campaign_trash_entry_matches_world(
                    entry,
                    world,
                    allow_renamed_legacy=True,
                )
            ]
        if not entries:
            QMessageBox.information(self, "No Campaigns", "No campaigns are eligible to revive.")
            return
        entry = None
        if name is not None:
            entry = next((item for item in entries if item.get("name") == name), None)
        if entry is None:
            entry = self._select_trash_entry(
                "Revive Campaign",
                "Click a campaign to revive it.",
                entries,
            )
        if not entry:
            return
        payload = self._normalize_campaign(entry.get("payload") or {})
        if not payload.get("name"):
            QMessageBox.warning(self, "Invalid Entry", "Selected campaign is missing a name.")
            return
        if payload["name"] in existing:
            QMessageBox.warning(self, "Name Conflict", "A campaign with that name already exists.")
            return
        expansion_state = self._capture_expansion_state()
        expansion_state["worlds"][world["name"]] = True
        expansion_state["campaigns"][(world["name"], payload["name"])] = True
        world["campaigns"].append(payload)
        self._trash.remove(entry)
        self._save_trash()
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _add_group(
        self,
        world_index: int,
        campaign_index: int,
        name: Optional[str] = None,
    ) -> None:
        campaign = self._get_campaign(world_index, campaign_index)
        if campaign is None:
            return
        if name is None:
            name, icon = self._prompt_name_icon(
                "New Group",
                "Group name:",
                "",
                self._default_group_icon,
            )
        else:
            name = name.strip()
            icon = self._default_group_icon
        if not name:
            return
        expansion_state = self._capture_expansion_state()
        world = self._get_world(world_index)
        if world:
            expansion_state["worlds"][world["name"]] = True
            expansion_state["campaigns"][(world["name"], campaign["name"])] = True
        campaign["groups"].append({"name": name, "icon": icon})
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _remove_group(
        self,
        world_index: int,
        campaign_index: int,
        name: Optional[int | str] = None,
    ) -> None:
        campaign = self._get_campaign(world_index, campaign_index)
        if campaign is None:
            return
        groups = campaign["groups"]
        if not groups:
            QMessageBox.information(self, "No Groups", "There are no groups to remove.")
            return
        if name is None:
            name = self._select_item(
                "Remove Group",
                "Click a group to remove it.",
                [(group["name"], group.get("icon")) for group in groups],
            )
        if name is None:
            return
        if isinstance(name, str) and not name.strip():
            return
        expansion_state = self._capture_expansion_state()
        group_index = self._resolve_group_index(campaign, name)
        if group_index is None:
            return
        group = groups[group_index]
        world = self._get_world(world_index)
        if group and world:
            parent = {"world": world["name"], "campaign": campaign["name"]}
            world_id = clean_navigation_id(world.get("id"))
            campaign_id = clean_navigation_id(campaign.get("id"))
            if world_id:
                parent["world_id"] = world_id
            if campaign_id:
                parent["campaign_id"] = campaign_id
            group_payload = copy.deepcopy(group)
            if world_id and not clean_navigation_id(group_payload.get("world_id")):
                group_payload["world_id"] = world_id
            if campaign_id and not clean_navigation_id(group_payload.get("campaign_id")):
                group_payload["campaign_id"] = campaign_id
            self._move_to_trash(
                "group",
                group_payload,
                parent=parent,
            )
        del campaign["groups"][group_index]
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _edit_group(
        self,
        world_index: int,
        campaign_index: int,
        old_name: Optional[str] = None,
        new_name: Optional[str] = None,
    ) -> None:
        campaign = self._get_campaign(world_index, campaign_index)
        if campaign is None:
            return
        groups = campaign["groups"]
        if not groups:
            QMessageBox.information(self, "No Groups", "There are no groups to edit.")
            return
        if old_name is None:
            old_name = self._select_item(
                "Edit Group",
                "Click a group to edit it.",
                [(group["name"], group.get("icon")) for group in groups],
            )
        if not old_name:
            return
        icon = None
        for group in groups:
            if group["name"] == old_name:
                icon = group.get("icon") or self._default_group_icon
                break
        if new_name is None:
            new_name, icon = self._prompt_name_icon(
                "Edit Group",
                "New group name:",
                old_name,
                icon or self._default_group_icon,
            )
        else:
            new_name = new_name.strip()
        if not new_name:
            return
        for group in groups:
            if group["name"] == old_name:
                group["name"] = new_name
                group["icon"] = icon or group.get("icon") or self._default_group_icon
                break
        expansion_state = self._capture_expansion_state()
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _disintegrate_group(
        self,
        world_index: int,
        campaign_index: int,
        name: Optional[int | str] = None,
    ) -> None:
        campaign = self._get_campaign(world_index, campaign_index)
        if campaign is None:
            return
        groups = campaign["groups"]
        if not groups:
            QMessageBox.information(self, "No Groups", "There are no groups to delete.")
            return
        if name is None:
            name = self._select_item(
                "Disintegrate Group",
                "Click a group to delete permanently.",
                [(group["name"], group.get("icon")) for group in groups],
            )
        if name is None:
            return
        if isinstance(name, str) and not name.strip():
            return
        if not self._confirm_disintegrate(
            "Disintegrate Group",
            f"Type CONFIRM to permanently delete '{name}'. This cannot be undone.",
        ):
            return
        expansion_state = self._capture_expansion_state()
        group_index = self._resolve_group_index(campaign, name)
        if group_index is None:
            return
        del campaign["groups"][group_index]
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _revive_group(
        self,
        world_index: int,
        campaign_index: int,
        name: Optional[str] = None,
    ) -> None:
        campaign = self._get_campaign(world_index, campaign_index)
        if campaign is None:
            return
        world = self._get_world(world_index)
        if world is None:
            return
        existing = {group["name"] for group in campaign["groups"]}
        candidates = [
            entry
            for entry in self._trash
            if entry.get("type") == "group"
            and entry.get("name") not in existing
        ]
        entries = [
            entry
            for entry in candidates
            if group_trash_entry_matches_campaign(
                entry,
                world,
                campaign,
                allow_renamed_legacy=False,
            )
        ]
        if not entries:
            entries = [
                entry
                for entry in candidates
                if group_trash_entry_matches_campaign(
                    entry,
                    world,
                    campaign,
                    allow_renamed_legacy=True,
                )
            ]
        if not entries:
            QMessageBox.information(self, "No Groups", "No groups are eligible to revive.")
            return
        entry = None
        if name is not None:
            entry = next((item for item in entries if item.get("name") == name), None)
        if entry is None:
            entry = self._select_trash_entry(
                "Revive Group",
                "Click a group to revive it.",
                entries,
            )
        if not entry:
            return
        payload = self._normalize_group(entry.get("payload") or {})
        if not payload.get("name"):
            QMessageBox.warning(self, "Invalid Entry", "Selected group is missing a name.")
            return
        if payload["name"] in existing:
            QMessageBox.warning(self, "Name Conflict", "A group with that name already exists.")
            return
        expansion_state = self._capture_expansion_state()
        expansion_state["worlds"][world["name"]] = True
        expansion_state["campaigns"][(world["name"], campaign["name"])] = True
        campaign["groups"].append(payload)
        self._trash.remove(entry)
        self._save_trash()
        save_navigation_data(self._data)
        self._rebuild(expansion_state)

    def _prompt_name_icon(
        self,
        title: str,
        label: str,
        default_name: str,
        default_icon: Optional[str],
    ) -> tuple[Optional[str], Optional[str]]:
        dialog = NameIconDialog(
            title,
            label,
            self._icon_paths,
            default_name=default_name,
            default_icon=default_icon,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None, None
        name, icon = dialog.values()
        if not name:
            return None, None
        return name, icon or default_icon

    def _select_item(
        self,
        title: str,
        label: str,
        items: list[tuple[str, Optional[str]]],
    ) -> Optional[str]:
        if not items:
            return None
        dialog = IconListDialog(
            title,
            label,
            [(name, icon_path, name) for name, icon_path in items],
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected

    def _select_trash_entry(
        self,
        title: str,
        label: str,
        entries: list[dict],
    ) -> Optional[dict]:
        if not entries:
            return None
        items = []
        for entry in entries:
            entry_name = entry.get("name", "")
            entry_icon = entry.get("icon")
            parent = entry.get("parent") or {}
            if entry["type"] == "campaign":
                display = f"{entry_name} · {parent.get('world', 'Unknown')}"
            elif entry["type"] == "group":
                display = f"{entry_name} · {parent.get('campaign', 'Unknown')} / {parent.get('world', 'Unknown')}"
            else:
                display = entry_name
            items.append((display, entry_icon, entry))
        dialog = IconListDialog(title, label, items, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        return dialog.selected

    def _load_trash(self) -> None:
        self._trash = load_trash(TRASH_PATH)
        self._purge_trash()

    def _save_trash(self) -> None:
        save_trash(self._trash, TRASH_PATH)

    def _purge_trash(self) -> None:
        if not self._trash:
            return
        cutoff = datetime.now() - timedelta(days=TRASH_RETENTION_DAYS)
        kept = []
        for entry in self._trash:
            deleted_at = entry.get("deleted_at")
            try:
                deleted_time = datetime.fromisoformat(str(deleted_at))
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
        trash_entry = move_to_trash(entry_type, payload, parent=parent, path=TRASH_PATH)
        if not trash_entry:
            return
        self._trash.append(trash_entry)

    def _confirm_disintegrate(self, title: str, message: str) -> bool:
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
        return normalize_group_entry(group, default_icon=self._default_group_icon)

    def _normalize_campaign(self, campaign: dict) -> dict:
        return normalize_campaign_entry(
            campaign,
            default_icon=self._default_campaign_icon,
            default_group_icon=self._default_group_icon,
        )

    def _normalize_world(self, world: dict) -> dict:
        return normalize_world_entry(
            world,
            default_icon=self._default_world_icon,
            default_campaign_icon=self._default_campaign_icon,
            default_group_icon=self._default_group_icon,
        )

    def _capture_expansion_state(self) -> dict:
        state: dict = {"worlds_section": True, "worlds": {}, "campaigns": {}}
        if self.worlds_section is not None:
            state["worlds_section"] = self.worlds_section.expanded
        for world_section in self.world_sections:
            world_name = world_section.title
            state["worlds"][world_name] = world_section.expanded
            layout = world_section.content_widget.layout()
            if not layout:
                continue
            for idx in range(layout.count()):
                widget = layout.itemAt(idx).widget()
                if isinstance(widget, CollapsibleSection):
                    state["campaigns"][(world_name, widget.title)] = widget.expanded
        return state

    def _restore_expansion_state(self, state: Optional[dict]) -> None:
        if not state:
            return
        if self.worlds_section is not None:
            self.worlds_section.set_expanded(state.get("worlds_section", True), animate=False)
        for world_section in self.world_sections:
            world_name = world_section.title
            if world_name in state.get("worlds", {}):
                world_section.set_expanded(state["worlds"][world_name], animate=False)
            layout = world_section.content_widget.layout()
            if not layout:
                continue
            for idx in range(layout.count()):
                widget = layout.itemAt(idx).widget()
                if isinstance(widget, CollapsibleSection):
                    key = (world_name, widget.title)
                    if key in state.get("campaigns", {}):
                        widget.set_expanded(state["campaigns"][key], animate=False)

    def _get_world(self, world_index: int) -> Optional[dict]:
        if world_index < 0 or world_index >= len(self._data):
            return None
        return self._data[world_index]

    def _resolve_world_index(self, world_ref: int | str) -> Optional[int]:
        if isinstance(world_ref, int):
            return world_ref if 0 <= world_ref < len(self._data) else None
        target = str(world_ref or "").strip()
        if not target:
            return None
        for idx, world in enumerate(self._data):
            if str(world.get("name") or "") == target:
                return idx
        return None

    def _resolve_campaign_index(self, world: dict, campaign_ref: int | str) -> Optional[int]:
        campaigns = world.get("campaigns", [])
        if not isinstance(campaigns, list):
            return None
        if isinstance(campaign_ref, int):
            return campaign_ref if 0 <= campaign_ref < len(campaigns) else None
        target = str(campaign_ref or "").strip()
        if not target:
            return None
        for idx, campaign in enumerate(campaigns):
            if str(campaign.get("name") or "") == target:
                return idx
        return None

    def _resolve_group_index(self, campaign: dict, group_ref: int | str) -> Optional[int]:
        groups = campaign.get("groups", [])
        if not isinstance(groups, list):
            return None
        if isinstance(group_ref, int):
            return group_ref if 0 <= group_ref < len(groups) else None
        target = str(group_ref or "").strip()
        if not target:
            return None
        for idx, group in enumerate(groups):
            if str(group.get("name") or "") == target:
                return idx
        return None

    def _get_campaign(self, world_index: int, campaign_index: int) -> Optional[dict]:
        world = self._get_world(world_index)
        if world is None:
            return None
        campaigns = world["campaigns"]
        if campaign_index < 0 or campaign_index >= len(campaigns):
            return None
        return campaigns[campaign_index]

    def _clear_layout(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget:
                for section in widget.findChildren(CollapsibleSection):
                    section._dispose_animation()
                if isinstance(widget, CollapsibleSection):
                    widget._dispose_animation()
                if shiboken6 is not None:
                    try:
                        if shiboken6.isValid(widget):
                            shiboken6.delete(widget)
                            continue
                    except Exception:
                        pass
                widget.deleteLater()
        QCoreApplication.sendPostedEvents(None, 0)

    def closeEvent(self, event) -> None:
        self._clear_layout()
        self.world_sections = []
        self.worlds_section = None
        super().closeEvent(event)

    def _rebuild(self, expansion_state: Optional[dict] = None) -> None:
        self._clear_layout()
        self.worlds_section = None
        self.world_sections = []

        if self._show_worlds_header:
            self.worlds_section = CollapsibleSection(
                "Worlds",
                self._default_world_icon,
                indent=12,
            )
            self._layout.addWidget(self.worlds_section)

        for world_index, world in enumerate(self._data):
            world_section = CollapsibleSection(
                world["name"],
                world.get("icon") or self._default_world_icon,
                indent=16,
                row_icon_size=LARGE_ROW_ICON_SIZE,
                row_padding_x=LARGE_ROW_PADDING_X,
                row_padding_y=LARGE_ROW_PADDING_Y,
            )
            world_section.set_context_actions(
                lambda checked=False, name=world["name"]: self.edit_world(old_name=name),
                lambda checked=False, idx=world_index: self.remove_world(name=idx),
                lambda checked=False, idx=world_index: self.disintegrate_world(name=idx),
            )
            campaign_header = DashedHeaderRow(
                "Campaigns",
                "Add campaign",
                "Delete campaign (30 days)",
            )
            campaign_header.add_clicked.connect(
                lambda checked=False, idx=world_index: self._add_campaign(idx)
            )
            campaign_header.edit_clicked.connect(
                lambda checked=False, idx=world_index: self._edit_campaign(idx)
            )
            campaign_header.remove_clicked.connect(
                lambda checked=False, idx=world_index: self._remove_campaign(idx)
            )
            campaign_header.disintegrate_clicked.connect(
                lambda checked=False, idx=world_index: self._disintegrate_campaign(idx)
            )
            campaign_header.revive_clicked.connect(
                lambda checked=False, idx=world_index: self._revive_campaign(idx)
            )
            world_section.add_widget(campaign_header)

            for campaign_index, campaign in enumerate(world["campaigns"]):
                campaign_section = CollapsibleSection(
                    campaign["name"],
                    campaign.get("icon") or self._default_campaign_icon,
                    indent=18,
                    row_icon_size=LARGE_ROW_ICON_SIZE,
                    row_padding_x=LARGE_ROW_PADDING_X,
                    row_padding_y=LARGE_ROW_PADDING_Y,
                )
                campaign_section.set_context_actions(
                    lambda checked=False, w_idx=world_index, name=campaign["name"]: self._edit_campaign(
                        w_idx, old_name=name
                    ),
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._remove_campaign(
                        w_idx, name=c_idx
                    ),
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._disintegrate_campaign(
                        w_idx, name=c_idx
                    ),
                )
                groups_header = DashedHeaderRow("Groups", "Add group", "Delete group (30 days)")
                groups_header.add_clicked.connect(
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._add_group(
                        w_idx, c_idx
                    )
                )
                groups_header.edit_clicked.connect(
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._edit_group(
                        w_idx, c_idx
                    )
                )
                groups_header.remove_clicked.connect(
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._remove_group(
                        w_idx, c_idx
                    )
                )
                groups_header.disintegrate_clicked.connect(
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._disintegrate_group(
                        w_idx, c_idx
                    )
                )
                groups_header.revive_clicked.connect(
                    lambda checked=False, w_idx=world_index, c_idx=campaign_index: self._revive_group(
                        w_idx, c_idx
                    )
                )
                campaign_section.add_widget(groups_header)
                for group_index, group in enumerate(campaign["groups"]):
                    group_row = NavItemRow(
                        group["name"],
                        group.get("icon") or self._default_group_icon,
                    )
                    launch_button = QPushButton("Launch Session")
                    launch_button.setObjectName("LaunchSessionButton")
                    launch_button.setCursor(Qt.CursorShape.PointingHandCursor)
                    launch_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
                    launch_button.clicked.connect(
                        lambda checked=False,
                        w_name=world["name"],
                        c_name=campaign["name"],
                        g_name=group["name"]: self._launch_session(
                            w_name, c_name, g_name
                        )
                    )
                    group_layout = group_row.layout()
                    if group_layout is not None:
                        group_layout.addWidget(launch_button)
                    group_row.set_context_actions(
                        lambda checked=False, w_idx=world_index, c_idx=campaign_index, name=group["name"]: self._edit_group(
                            w_idx, c_idx, old_name=name
                        ),
                        lambda checked=False, w_idx=world_index, c_idx=campaign_index, g_idx=group_index: self._remove_group(
                            w_idx, c_idx, name=g_idx
                        ),
                        lambda checked=False, w_idx=world_index, c_idx=campaign_index, g_idx=group_index: self._disintegrate_group(
                            w_idx, c_idx, name=g_idx
                        ),
                    )
                    campaign_section.add_widget(group_row)
                world_section.add_widget(campaign_section)

            self.world_sections.append(world_section)
            if self.worlds_section is None:
                self._layout.addWidget(world_section)
            else:
                self.worlds_section.add_widget(world_section)
        self._restore_expansion_state(expansion_state)

    def _launch_session(self, world_name: str, campaign_name: str, group_name: str) -> None:
        if self._launch_session_callback is not None:
            self._launch_session_callback(world_name, campaign_name, group_name)
            return
        QMessageBox.information(
            self,
            "Launch Session",
            f"Session for {group_name} is not implemented yet.",
        )


class NavigateWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setMinimumSize(720, 480)
        self._auto_expand_done = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Navigate")
        header.setObjectName("Header")
        subheader = QLabel("Pick a world, then drill into campaigns and groups.")
        subheader.setObjectName("Subheader")
        layout.addWidget(header)
        layout.addWidget(subheader)

        self._content = NavigateContentWidget(show_worlds_header=True)
        self._worlds_section = self._content.worlds_section
        self._world_sections = self._content.world_sections
        layout.addWidget(self._content)
        layout.addStretch(1)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._auto_expand_done and self._worlds_section is not None:
            self._auto_expand_done = True
            self._worlds_section.set_expanded(True, animate=True)

    def closeEvent(self, event) -> None:
        if hasattr(self, "_content") and self._content is not None:
            try:
                self._content.close()
            except Exception:
                pass
        super().closeEvent(event)
