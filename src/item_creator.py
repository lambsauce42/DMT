from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QSize, QTimer, Signal, QEvent
from PySide6.QtGui import (
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
from PySide6.QtWidgets import (
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
    QSlider,
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
    list_item_file_paths,
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
        save_item_card_png,
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
    hitboxClicked = Signal(str)

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

        self.export_png_button = QToolButton(self)
        self.export_png_button.setObjectName("SecondaryButton")
        self.export_png_button.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "image.svg")))
        self.export_png_button.setToolTip("Export PNG")

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
        for btn in (self.load_button, self.save_button, self.save_to_button, self.export_button, self.export_png_button):
            btn.setProperty("compact", True)
            btn.setIconSize(QSize(20, 20))
            btn.setFixedSize(36, 36)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet(top_action_button_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_row.addWidget(btn)
            
        action_row.addStretch(1)
        form_layout.addLayout(action_row)

        INPUT_H = 36  # Uniform height for all inputs and buttons

        basic_group = QGroupBox("Basics", self)
        basic_group.setObjectName("TransparentContainer")
        basic_layout = QHBoxLayout(basic_group)
        basic_layout.setContentsMargins(12, 12, 12, 12)
        basic_layout.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title_label = QLabel("Title")
        title_label.setStyleSheet("opacity: 0.72; font-size: 12px;")
        title_col.addWidget(title_label)
        self.title_edit = QLineEdit("Sample Item", basic_group)
        self.title_edit.setFixedHeight(INPUT_H)
        title_col.addWidget(self.title_edit)
        basic_layout.addLayout(title_col, 3)

        rarity_col = QVBoxLayout()
        rarity_col.setContentsMargins(0, 0, 0, 0)
        rarity_col.setSpacing(4)
        rarity_label = QLabel("Rarity")
        rarity_label.setStyleSheet("opacity: 0.72; font-size: 12px;")
        rarity_col.addWidget(rarity_label)
        self.rarity_combo = QComboBox(basic_group)
        self.rarity_combo.setFixedHeight(INPUT_H)
        self.rarity_combo.setFixedWidth(160)
        self.rarity_combo.setEditable(True)
        self.rarity_combo.lineEdit().setReadOnly(True)
        self.rarity_combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 20px left padding balances the ~20px wide dropdown arrow. 
        # 4px bottom padding ensures characters like 'y' or 'g' aren't cutoff.
        self.rarity_combo.lineEdit().setStyleSheet(
            "background: transparent; border: none; padding: 0px 0px 4px 20px; selection-background-color: #3a5a7a;"
        )
        self.rarity_combo.lineEdit().installEventFilter(self)
        self.rarity_combo.addItems(
            ["common", "uncommon", "rare", "epic", "legendary", "artifact"]
        )
        rarity_col.addWidget(self.rarity_combo)
        basic_layout.addLayout(rarity_col)

        form_layout.addWidget(basic_group)

        icon_group = QGroupBox("Icon", self)
        icon_group.setObjectName("TransparentContainer")
        icon_layout = QVBoxLayout(icon_group)
        icon_layout.setContentsMargins(12, 12, 12, 12)
        icon_layout.setSpacing(10)
        icon_row = QHBoxLayout()
        icon_row.setContentsMargins(0, 0, 0, 0)
        icon_row.setSpacing(12)
        self.icon_edit = QLineEdit(icon_group)
        self.icon_edit.setPlaceholderText("Path to icon image")
        self.icon_edit.setFixedHeight(INPUT_H)
        self.icon_browse_btn = QToolButton(icon_group)
        self.icon_browse_btn.setObjectName("SecondaryButton")
        self.icon_browse_btn.setText("Browse")
        self.icon_browse_btn.setFixedHeight(INPUT_H)
        self.icon_browse_btn.setFixedWidth(160)
        self.icon_browse_btn.setStyleSheet(
            "QToolButton { padding: 0px; border-radius: 6px; }"
        )
        self.icon_browse_btn.clicked.connect(self._browse_icon)
        icon_row.addWidget(self.icon_edit, 1)
        icon_row.addWidget(self.icon_browse_btn)
        icon_layout.addLayout(icon_row)

        self.icon_category_combo = QComboBox(icon_group)
        self.icon_category_combo.setFixedHeight(INPUT_H)
        self.icon_category_combo.setFixedWidth(160)
        self.icon_category_combo.setEditable(True)
        self.icon_category_combo.lineEdit().setReadOnly(True)
        self.icon_category_combo.lineEdit().setAlignment(Qt.AlignmentFlag.AlignCenter)
        # 20px left padding balances the dropdown arrow. 4px bottom padding prevents clipping.
        self.icon_category_combo.lineEdit().setStyleSheet(
            "background: transparent; border: none; padding: 0px 0px 4px 20px; selection-background-color: #3a5a7a;"
        )
        self.icon_category_combo.lineEdit().installEventFilter(self)
        self.icon_category_combo.currentTextChanged.connect(self._on_icon_category_changed)

        search_row = QHBoxLayout()
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.setSpacing(12)
        self._icon_search_edit = QLineEdit(icon_group)
        self._icon_search_edit.setPlaceholderText("Search icons...")
        self._icon_search_edit.setFixedHeight(INPUT_H)
        self._icon_search_edit.textChanged.connect(self._on_icon_search_changed)
        search_row.addWidget(self._icon_search_edit, 1)
        search_row.addWidget(self.icon_category_combo)
        icon_layout.addLayout(search_row)

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
        self.icon_category_combo.blockSignals(True)
        self._icon_search_edit.blockSignals(True)
        categories = sorted(list(set(icon['category'] for icon in self._all_icon_data if icon['category'] != "All")))
        self.icon_category_combo.addItem("All Categories")
        self.icon_category_combo.addItems(categories)
        self.icon_category_combo.blockSignals(False)
        self._icon_search_edit.blockSignals(False)
        
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
        icon_scroll.setMinimumHeight(208)
        icon_layout.addWidget(icon_scroll)
        form_layout.addWidget(icon_group)

        stats_effects_row = QWidget(self)
        stats_effects_row.setObjectName("TransparentContainer")
        se_layout = QHBoxLayout(stats_effects_row)
        se_layout.setContentsMargins(0, 0, 0, 0)
        se_layout.setSpacing(10)

        stats_group = QGroupBox("Stats", self)
        stats_group.setObjectName("TransparentContainer")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        self.stats_table = QTableWidget(0, 3, stats_group)
        self.stats_table.setHorizontalHeaderLabels(["Value", "Stat", ""])
        self.stats_table.horizontalHeader().setSectionResizeMode(0, self.stats_table.horizontalHeader().ResizeMode.Fixed)
        self.stats_table.horizontalHeader().setSectionResizeMode(1, self.stats_table.horizontalHeader().ResizeMode.Stretch)
        self.stats_table.horizontalHeader().setSectionResizeMode(2, self.stats_table.horizontalHeader().ResizeMode.Fixed)
        self.stats_table.setColumnWidth(0, 80)
        self.stats_table.setColumnWidth(2, 64)
        self.stats_table.verticalHeader().setVisible(False)
        self.stats_table.verticalHeader().setDefaultSectionSize(40)
        self.stats_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.stats_table.setMinimumHeight(160)
        self.stats_table.setShowGrid(False)
        self.stats_table.setAlternatingRowColors(True)
        self.stats_table.setCornerButtonEnabled(False)
        self.stats_table.setStyleSheet("""
            QTableWidget {
                background-color: #0d1117;
                border: 1px solid #30363d;
                border-radius: 6px;
                selection-background-color: #3a5a7a;
                gridline-color: transparent;
                padding: 0px;
                margin: 0px;
            }
            QTableWidget::item {
                padding-left: 10px;
                padding-right: 10px;
                border-bottom: 1px solid #21262d; 
            }
            QHeaderView::section {
                background-color: #161b22;
                border: none;
                border-bottom: 1px solid #30363d;
                padding-left: 14px;
                height: 36px;
                color: #8b949e;
                font-weight: 600;
                text-align: left;
                margin: 0px;
            }
            QHeaderView {
                background-color: transparent;
                border: none;
                margin: 0px;
                padding: 0px;
            }
        """)
        self.stats_table.horizontalHeader().setHighlightSections(False)
        self.stats_table.horizontalHeader().setSectionsClickable(False)
        self.stats_table.horizontalHeader().setSortIndicatorShown(False)
        self.stats_table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.stats_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.stats_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        stats_layout.addWidget(self.stats_table)
        stats_buttons = QHBoxLayout()
        self.add_stat_btn = QToolButton(stats_group)
        self.add_stat_btn.setObjectName("PrimaryButton")
        self.add_stat_btn.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "plus.svg")))
        self.add_stat_btn.setIconSize(QSize(16, 16))
        self.add_stat_btn.setToolTip("Add Stat")
        self.add_stat_btn.setFixedSize(32, 32)
        
        square_btn_style = """
            QToolButton {
                padding: 4px;
                border-radius: 6px;
            }
        """
        self.add_stat_btn.setStyleSheet(square_btn_style)
        
        self.add_stat_btn.clicked.connect(self._add_stat_row)
        stats_buttons.addWidget(self.add_stat_btn)
        stats_buttons.addStretch(1)
        stats_layout.addLayout(stats_buttons)
        se_layout.addWidget(stats_group, 1)

        effects_group = QGroupBox("Effects", self)
        effects_group.setObjectName("TransparentContainer")
        effects_layout = QVBoxLayout(effects_group)
        effects_layout.setContentsMargins(12, 12, 12, 12)
        self.effects_edit = QPlainTextEdit(effects_group)
        self.effects_edit.setPlaceholderText("One effect per line")
        self.effects_edit.setPlainText(
            "Gain resistance to necrotic damage.\n"
            "Once per rest, reroll a failed saving throw."
        )
        self.effects_edit.setMinimumHeight(80)
        effects_layout.addWidget(self.effects_edit)

        se_layout.addWidget(effects_group, 1)

        form_layout.addWidget(stats_effects_row, 1)

        flavor_group = QGroupBox("Flavor Text", self)
        flavor_group.setObjectName("TransparentContainer")
        flavor_layout = QVBoxLayout(flavor_group)
        flavor_layout.setContentsMargins(12, 12, 12, 12)
        self.flavor_edit = QPlainTextEdit(flavor_group)
        self.flavor_edit.setPlaceholderText("Short italic flavor text")
        self.flavor_edit.setPlainText(
            "A quiet glow pools in the seams of the metal."
        )
        flavor_layout.addWidget(self.flavor_edit)
        form_layout.addWidget(flavor_group, 1)

        preview_panel = QWidget(self)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setSpacing(8)

        # ── Top bar: Classes | Categories+Level | Display Options ──
        top_bar = QFrame(preview_panel)
        top_bar.setStyleSheet(
            "QFrame#ItemTopBar { background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #161b22, stop:1 #0d1117);"
            " border: 1px solid #30363d; border-top: 1px solid #3d444d; border-radius: 8px; }"
        )
        top_bar.setObjectName("ItemTopBar")
        
        # Grid layout for strict column/row alignment
        tb_grid = QGridLayout(top_bar)
        tb_grid.setContentsMargins(24, 20, 24, 20)
        tb_grid.setHorizontalSpacing(40)
        tb_grid.setVerticalSpacing(12) 
        
        # Set fixed widths for category columns to ensure they are identical
        tb_grid.setColumnMinimumWidth(1, 120)
        tb_grid.setColumnMinimumWidth(2, 120)
        
        # Force rows 1, 2, 3 to have identical heights to ensure equal spacing
        # while matching the 36px height of the left-hand input box
        ROW_H = 36
        tb_grid.setRowMinimumHeight(1, ROW_H)
        tb_grid.setRowMinimumHeight(2, ROW_H)
        tb_grid.setRowMinimumHeight(3, ROW_H)

        # --- Headers (Row 0) ---
        classes_hdr = QLabel("CLASSES")
        classes_hdr.setStyleSheet("font-size: 11px; font-weight: bold; color: #8b949e; border: none;")
        tb_grid.addWidget(classes_hdr, 0, 0)

        cats_hdr = QLabel("CATEGORIES")
        cats_hdr.setStyleSheet("font-size: 11px; font-weight: bold; color: #8b949e; border: none;")
        tb_grid.addWidget(cats_hdr, 0, 1, 1, 2)

        disp_hdr = QLabel("DISPLAY OPTIONS")
        disp_hdr.setStyleSheet("font-size: 11px; font-weight: bold; color: #8b949e; border: none;")
        tb_grid.addWidget(disp_hdr, 0, 3)

        # Helper for uniform checkboxes with alignment correction
        self._category_checks: Dict[str, QCheckBox] = {}
        def make_check(name, checked=False):
            cb = QCheckBox(name.capitalize())
            cb.setStyleSheet("font-size: 12px; opacity: 0.9;")
            cb.setChecked(checked)
            cb.stateChanged.connect(self._mark_dirty)
            self._category_checks[name] = cb
            return cb

        # --- Content Row 1 (Input row) ---
        # Row 1 Left: Classes Edit
        self._classes_edit = QLineEdit()
        self._classes_edit.setPlaceholderText("e.g. Fighter, Rogue, Wizard...")
        self._classes_edit.setStyleSheet("font-size: 12px;")
        self._classes_edit.setFixedHeight(INPUT_H)
        self._classes_edit.textChanged.connect(self._mark_dirty)
        tb_grid.addWidget(self._classes_edit, 1, 0, Qt.AlignmentFlag.AlignTop)

        # We use spanning layouts for the category columns to ensure perfect 
        # vertical distribution between the top of Row 1 and bottom of Row 3.
        def make_v_col(checks: List[QCheckBox]):
            vbox = QVBoxLayout()
            vbox.setContentsMargins(0, 0, 0, 0)
            vbox.setSpacing(0)
            for i, cb in enumerate(checks):
                vbox.addWidget(cb)
                if i < len(checks) - 1:
                    vbox.addStretch(1)
            return vbox

        self._show_level_check = make_check("Show Level", checked=True)
        self._show_rarity_check = make_check("Show Rarity", checked=True)
        self._icon_padding_check = make_check("Icon Padding", checked=True)

        tb_grid.addLayout(
            make_v_col([make_check("equipment"), make_check("valuables"), make_check("miscellaneous")]),
            1, 1, 3, 1
        )
        tb_grid.addLayout(
            make_v_col([make_check("consumables"), make_check("magic"), make_check("quest")]),
            1, 2, 3, 1
        )
        tb_grid.addLayout(
            make_v_col([self._show_level_check, self._show_rarity_check, self._icon_padding_check]),
            1, 3, 3, 1
        )

        # --- Content Row 2 (Level Header row) ---
        # Row 2 Left: Level Header label
        level_hdr = QLabel("LEVEL")
        level_hdr.setStyleSheet("font-size: 11px; font-weight: bold; color: #8b949e; border: none;")
        tb_grid.addWidget(level_hdr, 2, 0, Qt.AlignmentFlag.AlignTop)

        # --- Content Row 3 (Level Slider row) ---
        # Row 3 Left: Level Slider widget
        level_row_widget = QWidget()
        level_row_widget.setObjectName("TransparentContainer")
        level_row_layout = QHBoxLayout(level_row_widget)
        level_row_layout.setContentsMargins(0, 0, 0, 0)
        level_row_layout.setSpacing(6)
        self._level_edit = QLineEdit()
        self._level_edit.setFixedWidth(42)
        self._level_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._level_edit.setFixedHeight(28)
        self._level_edit.setStyleSheet("font-size: 12px; padding: 0px;")
        self._level_edit.setValidator(QIntValidator(1, 20, self))
        self._level_edit.setText(str(self._level_value))
        self._level_edit.textChanged.connect(self._on_level_text_changed)
        self._level_edit.editingFinished.connect(self._on_level_edit_finished)
        level_row_layout.addWidget(self._level_edit)
        self._level_slider = QSlider(Qt.Orientation.Horizontal)
        self._level_slider.setRange(1, 20)
        self._level_slider.setValue(self._level_value)
        self._level_slider.setTickInterval(1)
        self._level_slider.setSingleStep(1)
        self._level_slider.setFixedHeight(28)
        self._level_slider.valueChanged.connect(
            lambda v: (
                self._level_edit.setText(str(v)),
                setattr(self, "_level_value", v),
                self._mark_dirty(),
            )
        )
        level_row_layout.addWidget(self._level_slider, 1)
        tb_grid.addWidget(level_row_widget, 3, 0, Qt.AlignmentFlag.AlignBottom)

        preview_layout.addWidget(top_bar)

        # ── Preview header ──
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
        self.export_png_button.clicked.connect(self._export_png)

        self.title_edit.textChanged.connect(self._mark_dirty)
        self.rarity_combo.currentTextChanged.connect(self._mark_dirty)
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



    def _seed_stats(self) -> None:
        sample_rows = [("+1", "AC"), ("+1", "CON")]
        self.stats_table.blockSignals(True)
        for value, name in sample_rows:
            self._insert_stat_row(value, name)
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

    def _on_icon_category_changed(self, text: str) -> None:
        self._filter_icons()

    def _on_icon_search_changed(self, text: str) -> None:
        self._filter_icons()

    def _filter_icons(self) -> None:
        search_text = self._icon_search_edit.text().lower().strip()
        category_filter = self.icon_category_combo.currentText()
        
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

    def _insert_stat_row(self, value: str = "+1", name: str = "Stat") -> None:
        """Insert a stat row with value, name, and inline remove button."""
        row = self.stats_table.rowCount()
        self.stats_table.insertRow(row)

        val_item = QTableWidgetItem(value)
        val_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.stats_table.setItem(row, 0, val_item)

        name_item = QTableWidgetItem(name)
        name_item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.stats_table.setItem(row, 1, name_item)
        
        # Center the remove button in a layout
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        remove_btn = QToolButton(container)
        remove_btn.setObjectName("SecondaryButton")
        remove_btn.setProperty("compact", "true")
        remove_btn.setIcon(QIcon(os.path.join(ITEM_ICON_DIR, "..", "icons", "trash.svg")))
        remove_btn.setIconSize(QSize(14, 14))
        remove_btn.setFixedSize(30, 30)
        remove_btn.setStyleSheet("QToolButton { padding: 0px; border-radius: 4px; border: 1px solid #3b424b; background-color: #1c2128; min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px; }")
        remove_btn.setToolTip("Remove Stat")
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.clicked.connect(lambda _=False, r=row: self._remove_stat_at(r))
        
        lay.addWidget(remove_btn)
        self.stats_table.setCellWidget(row, 2, container)

    def _add_stat_row(self) -> None:
        self._insert_stat_row()
        self._mark_dirty()

    def _remove_stat_at(self, row: int) -> None:
        """Remove stat row at given index, then re-wire remaining buttons."""
        if row < self.stats_table.rowCount():
            self.stats_table.removeRow(row)
            # Re-wire all remaining remove buttons to correct row indices
            for r in range(self.stats_table.rowCount()):
                btn = self.stats_table.cellWidget(r, 2)
                if btn:
                    # The button is inside a container widget, so we need to get the button itself
                    # Assuming the button is the only widget in the layout of the container
                    actual_btn = btn.layout().itemAt(0).widget()
                    try:
                        actual_btn.clicked.disconnect()
                    except Exception:
                        pass
                    actual_btn.clicked.connect(lambda _=False, idx=r: self._remove_stat_at(idx))
            self._mark_dirty()

    def _remove_stat_row(self) -> None:
        selected = self.stats_table.selectionModel().selectedRows()
        if not selected:
            return
        for index in sorted(selected, key=lambda i: i.row(), reverse=True):
            self.stats_table.removeRow(index.row())
        # Re-wire remaining remove buttons
        for r in range(self.stats_table.rowCount()):
            btn = self.stats_table.cellWidget(r, 2)
            if btn:
                # The button is inside a container widget, so we need to get the button itself
                actual_btn = btn.layout().itemAt(0).widget()
                try:
                    actual_btn.clicked.disconnect()
                except Exception:
                    pass
                actual_btn.clicked.connect(lambda _=False, idx=r: self._remove_stat_at(idx))
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
        # Collect classes from text input
        classes_raw = self._classes_edit.text().strip()
        if classes_raw:
            class_value = [c.strip() for c in classes_raw.split(",") if c.strip()]
        else:
            class_value = []  # Empty list means "All Classes"
        tags: List[str] = []
        seen: set[str] = set()
        for tag, cb in self._category_checks.items():
            if cb.isChecked():
                key = tag.lower()
                if key not in seen:
                    tags.append(tag)
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
            fused_stats_effects=False,
            show_level=self._show_level_check.isChecked(),
            show_rarity=self._show_rarity_check.isChecked(),
            show_icon_padding=self._icon_padding_check.isChecked(),
        )

    def _apply_spec(self, spec: ItemCardSpec) -> None:
        self.title_edit.blockSignals(True)
        self.rarity_combo.blockSignals(True)
        self._classes_edit.blockSignals(True)
        for cb in self._category_checks.values():
            cb.blockSignals(True)
        self._level_edit.blockSignals(True)
        self._level_slider.blockSignals(True)
        self.icon_edit.blockSignals(True)
        self.effects_edit.blockSignals(True)
        self.flavor_edit.blockSignals(True)
        self.stats_table.blockSignals(True)
        self._show_level_check.blockSignals(True)
        self._show_rarity_check.blockSignals(True)
        self._icon_padding_check.blockSignals(True)

        self.title_edit.setText(spec.title or "Untitled Item")
        if spec.rarity in [self.rarity_combo.itemText(i) for i in range(self.rarity_combo.count())]:
            self.rarity_combo.setCurrentText(spec.rarity)
        else:
            self.rarity_combo.setCurrentText("common")
        
        # Apply classes from text input
        if spec.classes:
            self._classes_edit.setText(", ".join(spec.classes))
        else:
            self._classes_edit.setText("")

        raw_tags = [str(t).strip() for t in (spec.tags or []) if str(t).strip()]
        normalized = {t.lower() for t in raw_tags}
        for tag, cb in self._category_checks.items():
            cb.setChecked(tag in normalized)
        level = spec.level if spec.level is not None else 1
        if level < 1 or level > 20:
            level = 1
        self._level_value = level
        self._level_edit.setText(str(level))
        self._level_slider.setValue(level)
        
        self.icon_edit.setText(spec.icon_path or "")
        self.effects_edit.setPlainText("\n".join(spec.effects))
        self.flavor_edit.setPlainText(spec.flavor_text or "")

        self.stats_table.setRowCount(0)
        for value, name in spec.stats:
            self._insert_stat_row(value, name)

        self._show_level_check.setChecked(spec.show_level)
        self._show_rarity_check.setChecked(spec.show_rarity)
        self._icon_padding_check.setChecked(spec.show_icon_padding)

        self.title_edit.blockSignals(False)
        self.rarity_combo.blockSignals(False)
        self._classes_edit.blockSignals(False)
        for cb in self._category_checks.values():
            cb.blockSignals(False)
        self._level_edit.blockSignals(False)
        self._level_slider.blockSignals(False)
        self.icon_edit.blockSignals(False)
        self.effects_edit.blockSignals(False)
        self.flavor_edit.blockSignals(False)
        self.stats_table.blockSignals(False)
        self._show_level_check.blockSignals(False)
        self._show_rarity_check.blockSignals(False)
        self._icon_padding_check.blockSignals(False)
        self._sync_icon_selection()
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
            
            # Ensure extension
            if not pdf_path.lower().endswith(".pdf"):
                pdf_path += ".pdf"
            
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
            export_dir = os.path.dirname(pdf_path)
            if export_dir:
                os.makedirs(export_dir, exist_ok=True)
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

    def _export_png(self) -> None:
        if not RENDERER_AVAILABLE:
            QMessageBox.warning(
                self, "Renderer Unavailable", f"Cannot export: {RENDERER_ERROR}"
            )
            return

        default_name = self._default_base_name() + ".png"
        default_path = os.path.join(self._base_save_dir, default_name)

        while True:
            png_path, _ = QFileDialog.getSaveFileName(
                self, "Export PNG", default_path, "PNG (*.png)"
            )
            if not png_path:
                return
            
            # Ensure extension
            if not png_path.lower().endswith(".png"):
                png_path += ".png"
            
            if os.path.exists(png_path):
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setWindowTitle("File Exists")
                dialog.setText("A PNG with this name already exists.")
                dialog.setInformativeText("Rename the file or overwrite the existing PNG.")
                rename_btn = dialog.addButton("Rename", QMessageBox.ButtonRole.ActionRole)
                overwrite_btn = dialog.addButton(
                    "Overwrite", QMessageBox.ButtonRole.DestructiveRole
                )
                dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                dialog.exec()
                if dialog.clickedButton() == rename_btn:
                    default_path = png_path
                    continue
                if dialog.clickedButton() != overwrite_btn:
                    return
            break

        spec = self._current_spec()
        try:
            export_dir = os.path.dirname(png_path)
            if export_dir:
                os.makedirs(export_dir, exist_ok=True)
            save_item_card_png(
                spec,
                png_path,
                RenderOptions(
                    width=EXPORT_WIDTH,
                    scale=EXPORT_SCALE,
                    title_scale=self._title_scale,
                    body_scale=self._body_scale,
                    label_scale=self._label_scale,
                    icon_bg_curve=self._icon_bg_curve,
                ),
                png_resolution=EXPORT_DPI,
                downscale=False,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))

    def _load_item(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Item", self._base_save_dir, "DMT Item (*.dmtitem)"
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

    def open_linked_item(self, item_id: str) -> bool:
        clean_id = str(item_id or "").strip()
        if not clean_id:
            return False
        root = Path(self._base_save_dir)
        target_path = None
        for path in list_item_file_paths(root):
            if str(path.stem or "").strip() == clean_id:
                target_path = path
                break
        if target_path is None:
            return False
        try:
            data = load_item_payload(target_path)
            if data is None:
                return False
            spec = spec_from_dict(data)
        except Exception:
            return False
        self._apply_spec(spec)
        self._last_save_path = str(target_path)
        self._set_dirty(False)
        return True

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
                outside_alpha=0,
            )
            # Keep full export resolution to avoid double downscaling blur.
            rendered = render_item_card(spec, opts, downscale=False)
            qimage = _pil_to_qimage(rendered.image)
            self.preview.set_card(qimage, rendered.hitboxes)
        except Exception as exc:
            self.preview.set_card(None, {})
            self._preview_status.setText(f"Preview error: {str(exc)[:40]}...")
            return

    def eventFilter(self, obj, event) -> bool:
        """Handle mouse clicks on read-only line edits within editable combo boxes."""
        if event.type() == QEvent.Type.MouseButtonPress:
            # Check if this is one of our combo box line edits
            if (hasattr(self, 'rarity_combo') and obj is self.rarity_combo.lineEdit()) or \
               (hasattr(self, 'icon_category_combo') and obj is self.icon_category_combo.lineEdit()):
                obj.parent().showPopup()
                return True
        return super().eventFilter(obj, event)

    def _focus_from_hitbox(self, key: str) -> None:
        mapping = {
            "icon": self.icon_edit,
            "title": self.title_edit,
            "rarity": self.rarity_combo,
            "classes": self._classes_edit,
            "stats": self.stats_table,
            "effects": self.effects_edit,
            "flavor": self.flavor_edit,
        }
        target = mapping.get(key)
        if target:
            target.setFocus()
            self.preview.set_active_key(key)
