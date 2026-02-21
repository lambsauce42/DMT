from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFontMetrics,
    QIcon,
    QImage,
    QIntValidator,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QComboBox,
    QMessageBox,
    QFrame,
)

import save_paths
from item_file_format import (
    ITEM_FILE_EXTENSION,
    build_item_document,
    load_item_payload,
)

PREVIEW_WIDTH = 350  # Match export width for 1:1 display
EXPORT_WIDTH = 350   # Keep layout scale consistent with the renderer default
EXPORT_SCALE = 6
EXPORT_DPI = 480
ICON_GRID_ICON_SIZE = 48
ICON_GRID_BUTTON_SIZE = 88
ICON_GRID_COLUMNS = 4  # Minimum columns; expand based on available width
ITEM_ICON_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "itemicons")
)
ITEM_ICON_DIR_FALLBACK = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "assets", "iconitems")
)
ITEM_ICON_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

try:
    from item_renderer import (
        ItemCardSpec,
        RenderOptions,
        render_item_card,
        save_item_card_pdf,
        spec_from_dict,
        spec_to_dict,
    )

    RENDERER_AVAILABLE = True
    RENDERER_ERROR = ""
except Exception as exc:  # pragma: no cover - best effort for missing deps
    RENDERER_AVAILABLE = False
    RENDERER_ERROR = str(exc)


def _pil_to_qimage(pil_image) -> QImage:
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(
        data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888
    )
    return qimage.copy()


class _IconGridContainer(QWidget):
    def __init__(self, on_resize: Callable[[], None], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._on_resize = on_resize

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._on_resize:
            self._on_resize()


class ItemPreviewWidget(QWidget):
    hitboxClicked = pyqtSignal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._image: Optional[QImage] = None
        self._pixmap: Optional[QPixmap] = None
        self._scaled_pixmap: Optional[QPixmap] = None
        self._hitboxes: Dict[str, Tuple[int, int, int, int]] = {}
        self._active_key: Optional[str] = None
        self._scale: float = 1.0
        self._offset_x: float = 0.0
        self._offset_y: float = 0.0
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMinimumSize(1, 1)

    def set_card(self, image: Optional[QImage], hitboxes: Dict[str, Tuple[int, int, int, int]]):
        self._image = image
        self._pixmap = QPixmap.fromImage(image) if image else None
        self._hitboxes = hitboxes
        self._update_scaled_pixmap()
        self.update()

    def set_active_key(self, key: Optional[str]) -> None:
        self._active_key = key
        self.update()

    def _update_scaled_pixmap(self) -> None:
        if not self._image or not self._pixmap:
            self._scaled_pixmap = None
            self._scale = 1.0
            self._offset_x = 0.0
            self._offset_y = 0.0
            return
        img_w = self._image.width()
        img_h = self._image.height()
        if img_w <= 0 or img_h <= 0:
            self._scaled_pixmap = None
            return
        view_w = max(1, self.width())
        view_h = max(1, self.height())
        self._scale = min(view_w / img_w, view_h / img_h)
        draw_w = max(1, int(round(img_w * self._scale)))
        draw_h = max(1, int(round(img_h * self._scale)))
        self._offset_x = (view_w - draw_w) / 2
        self._offset_y = (view_h - draw_h) / 2
        dpr = self.devicePixelRatioF()
        target_w = max(1, int(round(draw_w * dpr)))
        target_h = max(1, int(round(draw_h * dpr)))
        scaled = self._pixmap.scaled(
            target_w,
            target_h,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        self._scaled_pixmap = scaled

    def resizeEvent(self, event) -> None:
        self._update_scaled_pixmap()
        super().resizeEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(22, 25, 30))

        if not self._pixmap or not self._scaled_pixmap:
            painter.setPen(QColor(120, 130, 140))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No preview")
            return

        painter.drawPixmap(int(self._offset_x), int(self._offset_y), self._scaled_pixmap)

        if self._active_key and self._active_key in self._hitboxes:
            box = self._hitboxes[self._active_key]
            x0 = self._offset_x + box[0] * self._scale
            y0 = self._offset_y + box[1] * self._scale
            x1 = self._offset_x + box[2] * self._scale
            y1 = self._offset_y + box[3] * self._scale
            pen = QPen(QColor(120, 190, 255), 2)
            painter.setPen(pen)
            painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def mousePressEvent(self, event) -> None:
        if not self._image or not self._hitboxes:
            return
        x = event.position().x()
        y = event.position().y()
        if x < self._offset_x or y < self._offset_y:
            return
        img_x = (x - self._offset_x) / self._scale
        img_y = (y - self._offset_y) / self._scale
        for key, box in self._hitboxes.items():
            if box[0] <= img_x <= box[2] and box[1] <= img_y <= box[3]:
                self._active_key = key
                self.hitboxClicked.emit(key)
                self.update()
                return
        self._active_key = None
        self.update()


class ItemCreatorWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(900, 600)
        self._title_scale = 1.05
        self._body_scale = 0.90
        self._label_scale = 0.85
        self._icon_bg_curve = 1.12
        self._dirty = False
        self._last_save_path: Optional[str] = None
        self._level_value = 1
        self._preview_fast_timer = QTimer(self)
        self._preview_fast_timer.setSingleShot(True)
        self._preview_fast_timer.timeout.connect(self._render_preview)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        form_panel = QWidget(self)
        form_layout = QVBoxLayout(form_panel)
        form_layout.setSpacing(10)

        header = QLabel("Item Editor")
        header.setObjectName("Header")
        subheader = QLabel("Edit fields or click the preview to jump to a section.")
        subheader.setObjectName("Subheader")
        form_layout.addWidget(header)
        form_layout.addWidget(subheader)

        action_row = QHBoxLayout()
        self.load_button = QToolButton(self)
        self.load_button.setObjectName("SecondaryButton")
        self.load_button.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "folder_open.svg")))
        self.load_button.setToolTip("Load Item")
        
        self.save_button = QToolButton(self)
        self.save_button.setObjectName("SecondaryButton")
        self.save_button.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "save.svg")))
        self.save_button.setToolTip("Save Item")
        
        self.save_to_button = QToolButton(self)
        self.save_to_button.setObjectName("SecondaryButton")
        self.save_to_button.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "save_as.svg")))
        self.save_to_button.setToolTip("Save Item As")
        
        self.export_button = QToolButton(self)
        self.export_button.setObjectName("SecondaryButton")
        self.export_button.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "file_pdf.svg")))
        self.export_button.setToolTip("Export PDF")

        top_action_button_style = (
            "QToolButton#SecondaryButton {"
            "padding: 4px;"
            "min-width: 36px;"
            "max-width: 36px;"
            "min-height: 36px;"
            "max-height: 36px;"
            "border-radius: 6px;"
            "}"
        )
        for btn in (self.load_button, self.save_button, self.save_to_button, self.export_button):
            btn.setProperty("compact", True)
            btn.setIconSize(QSize(20, 20))
            btn.setFixedSize(36, 36)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(top_action_button_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_row.addWidget(btn)
            
        action_row.addStretch(1)
        form_layout.addLayout(action_row)

        basic_group = QGroupBox("Basics", self)
        basic_group.setObjectName("TransparentContainer")
        basic_layout = QFormLayout(basic_group)
        basic_layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)

        self.title_edit = QLineEdit("Sample Item", basic_group)
        self.rarity_combo = QComboBox(basic_group)
        self.rarity_combo.addItems(
            ["common", "uncommon", "rare", "epic", "legendary", "artifact"]
        )
        self.rarity_combo.setCurrentText("uncommon")

        basic_layout.addRow("Title", self.title_edit)
        basic_layout.addRow("Rarity", self.rarity_combo)

        # Multi-class selection
        classes_group = QGroupBox("Classes", self)
        classes_group.setObjectName("TransparentContainer")
        classes_layout = QVBoxLayout(classes_group)
        classes_layout.setSpacing(4)
        
        self.all_classes_check = QCheckBox("All Classes", classes_group)
        self.all_classes_check.setChecked(True)
        classes_layout.addWidget(self.all_classes_check)
        
        # Class checkboxes in a grid
        class_grid_widget = QWidget(classes_group)
        class_grid_widget.setObjectName("TransparentContainer")
        class_grid = QGridLayout(class_grid_widget)
        class_grid.setContentsMargins(0, 4, 0, 0)
        class_grid.setSpacing(4)
        
        self._class_names = [
            "Barbarian", "Bard", "Cleric", "Druid", "Fighter", "Monk",
            "Paladin", "Ranger", "Rogue", "Sorcerer", "Warlock", "Wizard", "Artificer"
        ]
        self._class_checks: Dict[str, QCheckBox] = {}
        for i, cls_name in enumerate(self._class_names):
            cb = QCheckBox(cls_name, class_grid_widget)
            cb.setEnabled(False)  # Disabled when "All Classes" is checked
            cb.stateChanged.connect(self._mark_dirty)
            self._class_checks[cls_name] = cb
            class_grid.addWidget(cb, i // 3, i % 3)
        
        classes_layout.addWidget(class_grid_widget)

        tags_group = QGroupBox("Categories (internal)", self)
        tags_group.setObjectName("TransparentContainer")
        tags_layout = QVBoxLayout(tags_group)
        tags_layout.setSpacing(6)
        tags_grid_widget = QWidget(tags_group)
        tags_grid_widget.setObjectName("TransparentContainer")
        tags_grid = QGridLayout(tags_grid_widget)
        tags_grid.setContentsMargins(0, 0, 0, 0)
        tags_grid.setSpacing(4)
        self._category_names = [
            "equipment",
            "consumables",
            "valuables",
            "magic",
            "miscellaneous",
        ]
        self._category_checks: Dict[str, QCheckBox] = {}
        for i, name in enumerate(self._category_names):
            label = name.capitalize()
            cb = QCheckBox(label, tags_grid_widget)
            cb.stateChanged.connect(self._mark_dirty)
            self._category_checks[name] = cb
            tags_grid.addWidget(cb, i // 2, i % 2)
        tags_layout.addWidget(tags_grid_widget)
        self._tag_custom_edit = QLineEdit(tags_group)
        self._tag_custom_edit.setPlaceholderText(
            "Extra tags (comma separated)"
        )
        self._tag_custom_edit.textChanged.connect(self._mark_dirty)
        self._level_edit = QLineEdit(tags_group)
        self._level_edit.setPlaceholderText("Level (internal)")
        self._level_edit.setValidator(QIntValidator(1, 20, self))
        self._level_edit.setText(str(self._level_value))
        self._level_edit.textChanged.connect(self._on_level_text_changed)
        self._level_edit.editingFinished.connect(self._on_level_edit_finished)
        tags_label = QLabel("Tags:", tags_group)
        level_label = QLabel("Level:", tags_group)
        metrics = QFontMetrics(tags_label.font())
        label_width = max(metrics.horizontalAdvance("Tags:"), metrics.horizontalAdvance("Level:"))
        tags_label.setFixedWidth(label_width)
        level_label.setFixedWidth(label_width)

        tags_row = QWidget(tags_group)
        tags_row.setObjectName("TransparentContainer")
        tags_row_layout = QHBoxLayout(tags_row)
        tags_row_layout.setContentsMargins(0, 0, 0, 0)
        tags_row_layout.setSpacing(6)
        tags_row_layout.addWidget(tags_label)
        tags_row_layout.addWidget(self._tag_custom_edit, 1)
        tags_layout.addWidget(tags_row)

        level_row = QWidget(tags_group)
        level_row.setObjectName("TransparentContainer")
        level_row_layout = QHBoxLayout(level_row)
        level_row_layout.setContentsMargins(0, 0, 0, 0)
        level_row_layout.setSpacing(6)
        level_row_layout.addWidget(level_label)
        level_row_layout.addWidget(self._level_edit, 1)
        tags_layout.addWidget(level_row)

        classes_tags_row = QWidget(self)
        classes_tags_row.setObjectName("TransparentContainer")
        classes_tags_layout = QHBoxLayout(classes_tags_row)
        classes_tags_layout.setContentsMargins(0, 0, 0, 0)
        classes_tags_layout.setSpacing(10)
        classes_tags_layout.addWidget(classes_group, 1)
        classes_tags_layout.addWidget(tags_group, 1)

        form_layout.addWidget(basic_group)
        form_layout.addWidget(classes_tags_row)

        icon_group = QGroupBox("Icon", self)
        icon_group.setObjectName("TransparentContainer")
        icon_layout = QVBoxLayout(icon_group)
        icon_row = QHBoxLayout()
        self.icon_edit = QLineEdit(icon_group)
        self.icon_edit.setPlaceholderText("Path to icon image (optional)")
        icon_button = QPushButton("Browse", icon_group)
        icon_button.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_edit)
        icon_row.addWidget(icon_button)
        icon_layout.addLayout(icon_row)

        filter_row = QHBoxLayout()
        self.icon_search = QLineEdit(icon_group)
        self.icon_search.setPlaceholderText("Search icons...")
        self.icon_search.textChanged.connect(self._filter_icons)
        
        self.icon_category_filter = QComboBox(icon_group)
        self.icon_category_filter.currentTextChanged.connect(self._filter_icons)
        
        filter_row.addWidget(self.icon_search, 2)
        filter_row.addWidget(self.icon_category_filter, 1)
        icon_layout.addLayout(filter_row)

        self._icon_buttons: Dict[str, QToolButton] = {}
        self._icon_group = QButtonGroup(self)
        self._icon_group.setExclusive(True)

        icon_scroll = QScrollArea(icon_group)
        icon_scroll.setWidgetResizable(True)
        icon_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        icon_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._icon_grid_buttons = []
        self._icon_grid_columns = 0
        self._icon_scroll = icon_scroll
        icon_container = _IconGridContainer(self._reflow_icon_grid, icon_scroll)
        self._icon_container = icon_container
        icon_grid = QGridLayout(icon_container)
        self._icon_grid = icon_grid
        icon_grid.setSpacing(8)
        icon_grid.setContentsMargins(0, 0, 0, 0)

        self._all_icon_data = self._discover_item_icons()
        
        # Populate category filter (blocking signals during setup to avoid rapid-fire updates)
        self.icon_category_filter.blockSignals(True)
        self.icon_search.blockSignals(True)
        categories = sorted(list(set(icon['category'] for icon in self._all_icon_data if icon['category'] != "All")))
        self.icon_category_filter.addItem("All Categories")
        self.icon_category_filter.addItems(categories)
        self.icon_category_filter.blockSignals(False)
        self.icon_search.blockSignals(False)
        
        if self._all_icon_data:
            for icon_data in self._all_icon_data:
                path = icon_data['path']
                button = QToolButton(icon_container)
                button.setToolButtonStyle(
                    Qt.ToolButtonStyle.ToolButtonTextUnderIcon
                )
                button.setIcon(QIcon(path))
                button.setIconSize(QSize(ICON_GRID_ICON_SIZE, ICON_GRID_ICON_SIZE))
                button.setCheckable(True)
                button.setText(icon_data['label'])
                button.setFixedSize(
                    ICON_GRID_BUTTON_SIZE, ICON_GRID_BUTTON_SIZE
                )
                button.clicked.connect(
                    lambda checked=False, p=path: self._set_icon_path(p)
                )
                self._icon_group.addButton(button)
                self._icon_buttons[self._normalize_icon_path(path)] = button
                icon_data['button'] = button
            self._filter_icons()
        else:
            empty_label = QLabel("No icons found in assets/itemicons or assets/iconitems.")
            empty_label.setObjectName("Subheader")
            icon_grid.addWidget(empty_label, 0, 0)

        icon_scroll.setWidget(icon_container)
        icon_scroll.setMinimumHeight(220)
        icon_layout.addWidget(icon_scroll)
        form_layout.addWidget(icon_group)

        stats_group = QGroupBox("Stats", self)
        stats_group.setObjectName("TransparentContainer")
        stats_layout = QVBoxLayout(stats_group)
        self.stats_table = QTableWidget(0, 2, stats_group)
        self.stats_table.setHorizontalHeaderLabels(["Value", "Stat"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stats_table.setMinimumHeight(140)
        self.stats_table.setShowGrid(False)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setCornerButtonEnabled(False)
        self.stats_table.setStyleSheet("""
            QTableWidget {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                selection-background-color: #3a5a7a;
                gridline-color: #30363d;
            }
            QTableWidget::item {
                padding: 4px;
                border-bottom: 1px solid #21262d; 
            }
            QHeaderView::section {
                background-color: #161b22;
                border: none;
                border-bottom: 1px solid #30363d;
                padding: 6px;
                color: #8b949e;
                font-weight: 600;
            }
        """)
        stats_layout.addWidget(self.stats_table)
        stats_buttons = QHBoxLayout()
        self.add_stat_btn = QToolButton(stats_group)
        self.add_stat_btn.setObjectName("PrimaryButton")
        self.add_stat_btn.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "plus.svg")))
        self.add_stat_btn.setIconSize(QSize(16, 16))
        self.add_stat_btn.setToolTip("Add Stat")
        self.add_stat_btn.setFixedSize(32, 32)
        
        self.remove_stat_btn = QToolButton(stats_group)
        self.remove_stat_btn.setObjectName("DestructiveButton")
        self.remove_stat_btn.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "minus.svg")))
        self.remove_stat_btn.setIconSize(QSize(16, 16))
        self.remove_stat_btn.setToolTip("Remove Selected Stat")
        self.remove_stat_btn.setFixedSize(32, 32)
        
        # Override global padding to force square shape
        square_btn_style = """
            QToolButton {
                padding: 4px;
                border-radius: 6px;
            }
        """
        self.add_stat_btn.setStyleSheet(square_btn_style)
        self.remove_stat_btn.setStyleSheet(square_btn_style)
        
        self.add_stat_btn.clicked.connect(self._add_stat_row)
        self.remove_stat_btn.clicked.connect(self._remove_stat_row)
        stats_buttons.addWidget(self.add_stat_btn)
        stats_buttons.addWidget(self.remove_stat_btn)
        stats_buttons.addStretch(1)
        stats_layout.addLayout(stats_buttons)
        form_layout.addWidget(stats_group)

        effects_group = QGroupBox("Effects", self)
        effects_group.setObjectName("TransparentContainer")
        effects_layout = QVBoxLayout(effects_group)
        self.effects_edit = QPlainTextEdit(effects_group)
        self.effects_edit.setPlaceholderText("One effect per line")
        self.effects_edit.setPlainText(
            "Gain resistance to necrotic damage.\n"
            "Once per rest, reroll a failed saving throw."
        )
        self.effects_edit.setMinimumHeight(120)
        effects_layout.addWidget(self.effects_edit)

        self.fuse_stats_check = QCheckBox("Fuse Stats and Effects", effects_group)
        self.fuse_stats_check.setToolTip("Combine stats and effects boxes. Only available when no stats are set.")
        self.fuse_stats_check.stateChanged.connect(self._on_fuse_stats_changed)
        effects_layout.addWidget(self.fuse_stats_check)
        
        form_layout.addWidget(effects_group)

        flavor_group = QGroupBox("Flavor Text", self)
        flavor_group.setObjectName("TransparentContainer")
        flavor_layout = QVBoxLayout(flavor_group)
        self.flavor_edit = QPlainTextEdit(flavor_group)
        self.flavor_edit.setPlaceholderText("Short italic flavor text")
        self.flavor_edit.setPlainText(
            "A quiet glow pools in the seams of the metal."
        )
        flavor_layout.addWidget(self.flavor_edit)
        form_layout.addWidget(flavor_group)

        form_layout.addStretch(1)

        preview_panel = QWidget(self)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setSpacing(8)
        self._preview_header = QLabel("Preview", preview_panel)
        self._preview_header.setObjectName("Header")
        header_row = QHBoxLayout()
        header_row.addWidget(self._preview_header)
        self._preview_status = QLabel("", preview_panel)
        self._preview_status.setStyleSheet("color: #ff7b72; font-size: 11px;")
        header_row.addWidget(self._preview_status, 1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        preview_layout.addLayout(header_row)

        self.preview = ItemPreviewWidget(preview_panel)
        preview_scroll = QScrollArea(preview_panel)
        preview_scroll.setWidgetResizable(True)
        preview_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        preview_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        preview_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        preview_scroll.setWidget(self.preview)
        preview_layout.addWidget(preview_scroll, stretch=1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(form_panel)

        layout.addWidget(scroll, stretch=2)
        layout.addWidget(preview_panel, stretch=3)

        self._base_save_dir = str(save_paths.items_dir())
        os.makedirs(self._base_save_dir, exist_ok=True)

        self.preview.hitboxClicked.connect(self._focus_from_hitbox)
        self.load_button.clicked.connect(self._load_item)
        self.save_button.clicked.connect(self._save_item)
        self.save_to_button.clicked.connect(self._save_item_as)
        self.export_button.clicked.connect(self._export_pdf)

        self.title_edit.textChanged.connect(self._mark_dirty)
        self.rarity_combo.currentTextChanged.connect(self._mark_dirty)
        self.all_classes_check.stateChanged.connect(self._on_all_classes_changed)
        self.icon_edit.textChanged.connect(self._mark_dirty)
        self.icon_edit.textChanged.connect(self._sync_icon_selection)
        self.effects_edit.textChanged.connect(self._mark_dirty)
        self.flavor_edit.textChanged.connect(self._mark_dirty)
        self.stats_table.itemChanged.connect(self._mark_dirty)

        self._seed_stats()
        self._set_dirty(False)
        # Delay initial preview to ensure widget has proper size and UI is settled
        QTimer.singleShot(500, self.update_preview)
        QShortcut(QKeySequence.StandardKey.Save, self).activated.connect(
            self._save_item
        )

    def showEvent(self, event) -> None:
        """Refresh preview when widget becomes visible."""
        super().showEvent(event)
        self.update_preview()

    def _on_all_classes_changed(self, state: int) -> None:
        """Enable/disable individual class checkboxes based on 'All Classes' state."""
        is_all = state == Qt.CheckState.Checked.value
        for cb in self._class_checks.values():
            cb.setEnabled(not is_all)
            if is_all:
                cb.setChecked(False)
        self._mark_dirty()

    def _seed_stats(self) -> None:
        sample_rows = [("+1", "AC"), ("+1", "CON")]
        self.stats_table.blockSignals(True)
        for value, name in sample_rows:
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)
            self.stats_table.setItem(row, 0, QTableWidgetItem(value))
            self.stats_table.setItem(row, 1, QTableWidgetItem(name))
        self.stats_table.blockSignals(False)

    def _normalize_icon_path(self, path: str) -> str:
        return os.path.abspath(path)

    def _discover_item_icons(self) -> List[Dict[str, str]]:
        icons: List[Dict[str, str]] = []
        for icon_dir in (ITEM_ICON_DIR, ITEM_ICON_DIR_FALLBACK):
            if not os.path.isdir(icon_dir):
                continue
            for root, dirs, files in os.walk(icon_dir):
                for name in files:
                    if name.lower().endswith(ITEM_ICON_EXTS):
                        path = os.path.join(root, name)
                        rel_path = os.path.relpath(root, icon_dir)
                        category = "All" if rel_path == "." else rel_path.capitalize()
                        label = self._icon_label(path)
                        icons.append({
                            "path": path,
                            "category": category,
                            "label": label,
                            "search_text": f"{label} {category}".lower(),
                            "button": None
                        })
        return sorted(icons, key=lambda x: (x['category'] != "All", x['category'], x['label'].lower()))

    def _filter_icons(self) -> None:
        search_text = self.icon_search.text().lower().strip()
        category_filter = self.icon_category_filter.currentText()
        
        self._icon_grid_buttons = []
        for icon_data in self._all_icon_data:
            match_search = not search_text or search_text in icon_data['search_text']
            match_category = category_filter == "All Categories" or icon_data['category'] == category_filter
            
            button = icon_data['button']
            if not button:
                continue
                
            if match_search and match_category:
                self._icon_grid_buttons.append(button)
                button.show()
            else:
                button.hide()
        
        self._icon_grid_columns = 0 # Force reflow
        self._reflow_icon_grid()

    def _reflow_icon_grid(self) -> None:
        if getattr(self, "_icon_grid", None) is None:
            return
        if not self._icon_grid_buttons:
            return
        available_width = 0
        if getattr(self, "_icon_scroll", None):
            available_width = self._icon_scroll.viewport().width()
        if available_width <= 0 and getattr(self, "_icon_container", None):
            available_width = self._icon_container.width()
        spacing = self._icon_grid.spacing()
        button_span = ICON_GRID_BUTTON_SIZE + spacing
        if available_width <= 0 or button_span <= 0:
            columns = ICON_GRID_COLUMNS
        else:
            columns = max(
                ICON_GRID_COLUMNS, (available_width + spacing) // button_span
            )
        columns = int(columns)
        if columns == self._icon_grid_columns:
            return
        while self._icon_grid.count():
            item = self._icon_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(self._icon_container)
        for index, button in enumerate(self._icon_grid_buttons):
            row = index // columns
            col = index % columns
            self._icon_grid.addWidget(button, row, col)
        self._icon_grid_columns = columns

    def _icon_label(self, path: str) -> str:
        name = os.path.splitext(os.path.basename(path))[0]
        return name.replace("_", " ").strip() or "icon"

    def _set_icon_path(self, path: str) -> None:
        self.icon_edit.setText(self._normalize_icon_path(path))

    def _sync_icon_selection(self) -> None:
        text = self.icon_edit.text().strip()
        if not text:
            for button in self._icon_buttons.values():
                button.setChecked(False)
            return
        candidates = [self._normalize_icon_path(text)]
        if not os.path.isabs(text):
            for icon_dir in (ITEM_ICON_DIR, ITEM_ICON_DIR_FALLBACK):
                candidates.append(
                    self._normalize_icon_path(os.path.join(icon_dir, text))
                )
        selected = None
        for candidate in candidates:
            selected = self._icon_buttons.get(candidate)
            if selected:
                break
        for button in self._icon_buttons.values():
            button.setChecked(button is selected)

    def _browse_icon(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Icon", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if path:
            self._set_icon_path(path)

    def _add_stat_row(self) -> None:
        row = self.stats_table.rowCount()
        self.stats_table.insertRow(row)
        self.stats_table.setItem(row, 0, QTableWidgetItem("+1"))
        self.stats_table.setItem(row, 1, QTableWidgetItem("Stat"))
        self._mark_dirty()

    def _remove_stat_row(self) -> None:
        selected = self.stats_table.selectionModel().selectedRows()
        if not selected:
            return
        for index in sorted(selected, key=lambda i: i.row(), reverse=True):
            self.stats_table.removeRow(index.row())
        self._mark_dirty()

    def _collect_stats(self) -> List[Tuple[str, str]]:
        stats: List[Tuple[str, str]] = []
        for row in range(self.stats_table.rowCount()):
            value_item = self.stats_table.item(row, 0)
            name_item = self.stats_table.item(row, 1)
            value = value_item.text().strip() if value_item else ""
            name = name_item.text().strip() if name_item else ""
            if value or name:
                stats.append((value, name))
        return stats

    def _collect_effects(self) -> List[str]:
        lines = self.effects_edit.toPlainText().splitlines()
        return [line.strip() for line in lines if line.strip()]

    def _current_spec(self) -> ItemCardSpec:
        # Collect selected classes as list
        if self.all_classes_check.isChecked():
            class_value = []  # Empty list means "All Classes"
        else:
            class_value = [name for name, cb in self._class_checks.items() if cb.isChecked()]
        tags: List[str] = []
        seen: set[str] = set()
        for tag, cb in self._category_checks.items():
            if cb.isChecked():
                key = tag.lower()
                if key not in seen:
                    tags.append(tag)
                    seen.add(key)
        custom_raw = self._tag_custom_edit.text().strip()
        if custom_raw:
            for part in custom_raw.split(","):
                cleaned = part.strip()
                if cleaned:
                    key = cleaned.lower()
                    if key not in seen:
                        tags.append(cleaned)
                        seen.add(key)
        level = self._level_value
        
        return ItemCardSpec(
            title=self.title_edit.text().strip() or "Untitled Item",
            rarity=self.rarity_combo.currentText(),
            classes=class_value,
            stats=self._collect_stats(),
            effects=self._collect_effects(),
            flavor_text=self.flavor_edit.toPlainText().strip(),
            icon_path=self.icon_edit.text().strip() or None,
            tags=tags,
            level=level,
            fused_stats_effects=self.fuse_stats_check.isChecked(),
        )

    def _apply_spec(self, spec: ItemCardSpec) -> None:
        self.title_edit.blockSignals(True)
        self.rarity_combo.blockSignals(True)
        self.all_classes_check.blockSignals(True)
        for cb in self._class_checks.values():
            cb.blockSignals(True)
        for cb in self._category_checks.values():
            cb.blockSignals(True)
        self._tag_custom_edit.blockSignals(True)
        self._level_edit.blockSignals(True)
        self.icon_edit.blockSignals(True)
        self.effects_edit.blockSignals(True)
        self.flavor_edit.blockSignals(True)
        self.stats_table.blockSignals(True)
        self.fuse_stats_check.blockSignals(True)

        self.title_edit.setText(spec.title or "Untitled Item")
        if spec.rarity in [self.rarity_combo.itemText(i) for i in range(self.rarity_combo.count())]:
            self.rarity_combo.setCurrentText(spec.rarity)
        else:
            self.rarity_combo.setCurrentText("common")
        
        # Apply classes - classes is now a List[str]
        if not spec.classes or len(spec.classes) == 0:
            # Empty list means "All Classes"
            self.all_classes_check.setChecked(True)
            for cb in self._class_checks.values():
                cb.setChecked(False)
                cb.setEnabled(False)
        else:
            self.all_classes_check.setChecked(False)
            for name, cb in self._class_checks.items():
                cb.setEnabled(True)
                cb.setChecked(name in spec.classes)

        raw_tags = [str(t).strip() for t in (spec.tags or []) if str(t).strip()]
        normalized = {t.lower() for t in raw_tags}
        extras = []
        for tag, cb in self._category_checks.items():
            cb.setChecked(tag in normalized)
        for tag in raw_tags:
            if tag.lower() not in self._category_checks:
                extras.append(tag)
        self._tag_custom_edit.setText(", ".join(extras))
        level = spec.level if spec.level is not None else 1
        if level < 1 or level > 20:
            level = 1
        self._level_value = level
        self._level_edit.setText(str(level))
        
        self.icon_edit.setText(spec.icon_path or "")
        self.effects_edit.setPlainText("\n".join(spec.effects))
        self.flavor_edit.setPlainText(spec.flavor_text or "")

        self.stats_table.setRowCount(0)
        for value, name in spec.stats:
            row = self.stats_table.rowCount()
            self.stats_table.insertRow(row)
            self.stats_table.setItem(row, 0, QTableWidgetItem(value))
            self.stats_table.setItem(row, 1, QTableWidgetItem(name))

        self.fuse_stats_check.setChecked(spec.fused_stats_effects)

        self.title_edit.blockSignals(False)
        self.rarity_combo.blockSignals(False)
        self.all_classes_check.blockSignals(False)
        for cb in self._class_checks.values():
            cb.blockSignals(False)
        for cb in self._category_checks.values():
            cb.blockSignals(False)
        self._tag_custom_edit.blockSignals(False)
        self._level_edit.blockSignals(False)
        self.icon_edit.blockSignals(False)
        self.effects_edit.blockSignals(False)
        self.flavor_edit.blockSignals(False)
        self.stats_table.blockSignals(False)
        self.fuse_stats_check.blockSignals(False)
        self._sync_icon_selection()
        self._update_ui_states()
        self.update_preview()
        self._set_dirty(False)

    def _default_base_name(self) -> str:
        title = self.title_edit.text().strip() or "item"
        cleaned = []
        for ch in title.lower():
            if ch.isalnum() or ch in ("-", "_"):
                cleaned.append(ch)
            elif ch.isspace():
                cleaned.append("-")
        base = "".join(cleaned).strip("-")
        return base or "item"


    def _save_item(self) -> None:
        if not RENDERER_AVAILABLE:
            QMessageBox.warning(
                self, "Renderer Unavailable", f"Cannot save: {RENDERER_ERROR}"
            )
            return
        if not self._last_save_path:
            self._save_item_as()
            return

        save_path = self._last_save_path
        if Path(save_path).suffix.lower() != ITEM_FILE_EXTENSION:
            save_path = str(Path(save_path).with_suffix(ITEM_FILE_EXTENSION))
            self._last_save_path = save_path
        base_dir = os.path.dirname(save_path)
        try:
            os.makedirs(base_dir, exist_ok=True)
            spec = self._current_spec()
            document = build_item_document(spec_to_dict(spec), spec.icon_path)
            with open(save_path, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, ensure_ascii=False)
            self._set_dirty(False)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _save_item_as(self) -> None:
        if not RENDERER_AVAILABLE:
            QMessageBox.warning(
                self, "Renderer Unavailable", f"Cannot save: {RENDERER_ERROR}"
            )
            return

        default_name = self._default_base_name() + ITEM_FILE_EXTENSION
        default_path = self._last_save_path or os.path.join(
            self._base_save_dir, default_name
        )

        while True:
            item_path, _ = QFileDialog.getSaveFileName(
                self, "Save Item", default_path, "DMT Item (*.dmtitem)"
            )
            if not item_path:
                return
            base_name = os.path.splitext(os.path.basename(item_path))[0]
            if not base_name:
                base_name = self._default_base_name()
            base_path = os.path.join(self._base_save_dir, base_name)
            item_path = base_path + ITEM_FILE_EXTENSION

            if os.path.exists(item_path):
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setWindowTitle("Item Exists")
                dialog.setText("An item with this name already exists.")
                dialog.setInformativeText("Rename the item or overwrite the existing files.")
                rename_btn = dialog.addButton("Rename", QMessageBox.ButtonRole.ActionRole)
                overwrite_btn = dialog.addButton(
                    "Overwrite", QMessageBox.ButtonRole.DestructiveRole
                )
                dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                dialog.exec()
                if dialog.clickedButton() == rename_btn:
                    default_path = item_path
                    continue
                if dialog.clickedButton() != overwrite_btn:
                    return
            break

        spec = self._current_spec()
        try:
            os.makedirs(self._base_save_dir, exist_ok=True)
            document = build_item_document(spec_to_dict(spec), spec.icon_path)
            with open(item_path, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2, ensure_ascii=False)
            self._last_save_path = item_path
            self._set_dirty(False)
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _export_pdf(self) -> None:
        if not RENDERER_AVAILABLE:
            QMessageBox.warning(
                self, "Renderer Unavailable", f"Cannot export: {RENDERER_ERROR}"
            )
            return

        default_name = self._default_base_name() + ".pdf"
        default_path = os.path.join(self._base_save_dir, default_name)

        while True:
            pdf_path, _ = QFileDialog.getSaveFileName(
                self, "Export PDF", default_path, "PDF (*.pdf)"
            )
            if not pdf_path:
                return
            base_name = os.path.splitext(os.path.basename(pdf_path))[0]
            if not base_name:
                base_name = self._default_base_name()
            base_path = os.path.join(self._base_save_dir, base_name)
            pdf_path = base_path + ".pdf"
            if os.path.exists(pdf_path):
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setWindowTitle("File Exists")
                dialog.setText("A PDF with this name already exists.")
                dialog.setInformativeText("Rename the file or overwrite the existing PDF.")
                rename_btn = dialog.addButton("Rename", QMessageBox.ButtonRole.ActionRole)
                overwrite_btn = dialog.addButton(
                    "Overwrite", QMessageBox.ButtonRole.DestructiveRole
                )
                dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                dialog.exec()
                if dialog.clickedButton() == rename_btn:
                    default_path = pdf_path
                    continue
                if dialog.clickedButton() != overwrite_btn:
                    return
            break

        spec = self._current_spec()
        try:
            os.makedirs(self._base_save_dir, exist_ok=True)
            save_item_card_pdf(
                spec,
                pdf_path,
                RenderOptions(
                    width=EXPORT_WIDTH,
                    scale=EXPORT_SCALE,
                    title_scale=self._title_scale,
                    body_scale=self._body_scale,
                    label_scale=self._label_scale,
                    icon_bg_curve=self._icon_bg_curve,
                ),
                pdf_resolution=EXPORT_DPI,
                downscale=False,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _load_item(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Item", self._base_save_dir, "DMT Item (*.dmtitem);;JSON (*.json)"
        )
        if not path:
            return
        try:
            data = load_item_payload(Path(path))
            if data is None:
                raise ValueError("Invalid item file")
            spec = spec_from_dict(data)
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))
            return

        self._apply_spec(spec)
        loaded_path = Path(path)
        if loaded_path.suffix.lower() == ITEM_FILE_EXTENSION:
            self._last_save_path = str(loaded_path)
        else:
            self._last_save_path = str(loaded_path.with_suffix(ITEM_FILE_EXTENSION))
        self._set_dirty(False)

    def update_preview(self) -> None:
        self._preview_fast_timer.start(70)

    def _on_level_text_changed(self, text: str) -> None:
        cleaned = text.strip()
        if not cleaned:
            return
        if not cleaned.isdigit():
            return
        value = int(cleaned)
        clamped = min(max(value, 1), 20)
        if clamped != value:
            self._level_edit.blockSignals(True)
            self._level_edit.setText(str(clamped))
            self._level_edit.blockSignals(False)
        if clamped != self._level_value:
            self._level_value = clamped
            self._mark_dirty()

    def _on_level_edit_finished(self) -> None:
        cleaned = self._level_edit.text().strip()
        if cleaned.isdigit():
            value = int(cleaned)
            clamped = min(max(value, 1), 20)
            if clamped != value:
                self._level_edit.blockSignals(True)
                self._level_edit.setText(str(clamped))
                self._level_edit.blockSignals(False)
            if clamped != self._level_value:
                self._level_value = clamped
                self._mark_dirty()
            return
        self._level_edit.blockSignals(True)
        self._level_edit.setText(str(self._level_value))
        self._level_edit.blockSignals(False)

    def _on_fuse_stats_changed(self, state: int) -> None:
        self._update_ui_states()
        self._mark_dirty()

    def _update_ui_states(self) -> None:
        stats = self._collect_stats()
        has_stats = len(stats) > 0
        
        if has_stats:
            self.fuse_stats_check.setEnabled(False)
            self.fuse_stats_check.blockSignals(True)
            self.fuse_stats_check.setChecked(False)
            self.fuse_stats_check.blockSignals(False)
        else:
            self.fuse_stats_check.setEnabled(True)

        fused = self.fuse_stats_check.isChecked()
        self.stats_table.setEnabled(not fused)
        self.add_stat_btn.setEnabled(not fused)
        self.remove_stat_btn.setEnabled(not fused)

    def _update_dirty_indicator(self) -> None:
        if self._dirty:
            self._preview_header.setText("Preview*")
        else:
            self._preview_header.setText("Preview")

    def _set_dirty(self, dirty: bool) -> None:
        if self._dirty == dirty:
            return
        self._dirty = dirty
        self._update_dirty_indicator()

    def _mark_dirty(self) -> None:
        self._update_ui_states()
        self._set_dirty(True)
        self.update_preview()

    def _render_preview(self) -> None:
        if not RENDERER_AVAILABLE:
            self.preview.set_card(None, {})
            self._preview_status.setText("Renderer unavailable")
            return
        
        self._preview_status.setText("")

        try:
            spec = self._current_spec()
            # Match export layout and resolution so preview mirrors the PDF output.
            opts = RenderOptions(
                width=EXPORT_WIDTH,
                scale=EXPORT_SCALE,
                title_scale=self._title_scale,
                body_scale=self._body_scale,
                label_scale=self._label_scale,
                icon_bg_curve=self._icon_bg_curve,
                panel_inner_glow=False,
                outer_rarity_glow=False,
            )
            # Keep full export resolution to avoid double downscaling blur.
            rendered = render_item_card(spec, opts, downscale=False)
            qimage = _pil_to_qimage(rendered.image)
            self.preview.set_card(qimage, rendered.hitboxes)
        except Exception as exc:
            self.preview.set_card(None, {})
            self._preview_status.setText(f"Preview error: {str(exc)[:40]}...")
            return

    def _focus_from_hitbox(self, key: str) -> None:
        mapping = {
            "icon": self.icon_edit,
            "title": self.title_edit,
            "rarity": self.rarity_combo,
            "classes": self.all_classes_check,
            "stats": self.stats_table,
            "effects": self.effects_edit,
            "flavor": self.flavor_edit,
        }
        target = mapping.get(key)
        if target:
            target.setFocus()
            self.preview.set_active_key(key)
