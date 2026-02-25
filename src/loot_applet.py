from __future__ import annotations

import json
import math
import os
import random
import re
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QSize, QPoint, QObject, QEvent
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QInputDialog,
)

from ui.widgets import PlusMinusSpinBox
from dmt_package import read_dmt_package_info, write_dmt_package
from item_file_format import list_item_file_paths, load_item_payload
from save_paths import default_dnd_save_dir, items_dir
from unique_ids import generate_probabilistic_unique_id

ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
RESET_ICON = os.path.join(ICON_DIR, "reset.svg")

try:
    from item_renderer import RenderOptions, render_item_card, spec_from_dict

    SPEC_AVAILABLE = True
    RENDERER_AVAILABLE = True
except Exception:  # pragma: no cover - optional renderer dependency
    SPEC_AVAILABLE = False
    RENDERER_AVAILABLE = False


RARITY_ORDER = ["common", "uncommon", "rare", "very rare", "legendary", "artifact"]
RARITY_LABELS = {
    "common": "Common",
    "uncommon": "Uncommon",
    "rare": "Rare",
    "very rare": "Epic",
    "legendary": "Legendary",
    "artifact": "Artifact",
}
RARITY_COLORS = {
    "common": "#4a5564",
    "uncommon": "#4c7a57",
    "rare": "#4d6aa6",
    "very rare": "#7b5ca8",
    "legendary": "#b58a2f",
    "artifact": "#c24b4b",
}
RARITY_CURVES = [
    "Linear",
    "Linear (Steep)",
    "Quadratic",
    "Quadratic (Steep)",
    "Exponential",
    "Poisson",
    "Bell Curve (Narrow)",
    "Bell Curve",
    "Bell Curve (Wide)",
    "Flat",
    "Inverted",
]
DEFAULT_LUCK = 50
LEVEL_CAP = 20
LEVEL_RANGE = 2
ICON_SIZE = 42
RESULT_ICON_SIZE = 58
ROLLS_MAX = 20
SLIDER_SCALE = 10
LUCK_MIN = 1.0
LUCK_MAX = 100.0
LUCK_SLIDER_SCALE = 1
CONTROL_SPIN_WIDTH = 120
LIBRARY_ITEM_MIN_WIDTH = 190
EXPORT_WIDTH = 350
EXPORT_SCALE = 6
EXPORT_DPI = 480
ARTIFACT_DEFAULT_PROB = 0.5
LOOT_RESULTS_EXTENSION = ".dmtloot"
LOOT_PRESET_EXTENSION = ".dmtpreset"
LOOT_PRESET_FORMAT = "dmtpreset.v1"
CATEGORY_LABELS = {
    "equipment": "Equipment",
    "consumables": "Consumables",
    "valuables": "Valuables",
    "magic": "Magic",
    "quest": "Quest",
    "miscellaneous": "Miscellaneous",
}
PREVIEW_WIDTH = 350
PREVIEW_SCALE = 3
PREVIEW_TITLE_SCALE = 1.05
PREVIEW_BODY_SCALE = 0.90
PREVIEW_LABEL_SCALE = 0.85
PREVIEW_ICON_CURVE = 1.12
PREVIEW_TOOLTIP_WIDTH = 322


@dataclass(frozen=True)
class LootItem:
    item_id: str
    title: str
    rarity: str
    category_label: Optional[str]
    categories: Set[str]
    level: int
    tags: Set[str]
    icon_path: Optional[str] = None
    path: Optional[str] = None
    show_icon_padding: bool = True


@dataclass
class LootResultItem:
    result_id: int
    item: LootItem
    locked: bool = False
    guaranteed: bool = False


@dataclass
class PresetEntry:
    name: str
    data: Dict[str, object]
    path: Optional[Path] = None
    built_in: bool = False


BUILTIN_PRESETS = []


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalize_rarity(value: str) -> Optional[str]:
    if not value:
        return None
    cleaned = value.strip().lower().replace("_", " ").replace("-", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if cleaned in ("veryrare", "very rare", "epic"):
        return "very rare"
    if cleaned == "artifact":
        return "artifact"
    if cleaned in ("legendary", "rare", "uncommon", "common"):
        return cleaned
    return None


def _parse_tag_list(text: str) -> Set[str]:
    tags = set()
    for raw in re.split(r"[,\n;]+", text):
        cleaned = raw.strip().lower()
        if cleaned:
            tags.add(cleaned)
    return tags


def _normalize_tags(raw) -> Set[str]:
    tags: Set[str] = set()
    if isinstance(raw, str):
        for entry in re.split(r"[,\n;]+", raw):
            cleaned = entry.strip().lower()
            if cleaned:
                tags.add(cleaned)
        return tags
    if isinstance(raw, list):
        for entry in raw:
            if entry is None:
                continue
            cleaned = str(entry).strip().lower()
            if cleaned:
                tags.add(cleaned)
    return tags


def _normalize_categories(raw) -> Set[str]:
    categories: Set[str] = set()
    if raw is None:
        return categories
    if isinstance(raw, list):
        for entry in raw:
            if entry:
                label = str(entry).strip().lower()
                if label:
                    categories.add(label)
        return categories
    label = str(raw).strip().lower()
    if label:
        categories.add(label)
    return categories


def _category_label_from_categories(categories: Set[str]) -> Optional[str]:
    if not categories:
        return None
    primary = sorted(categories)[0]
    return CATEGORY_LABELS.get(primary, primary.title())


def _resolve_icon_path(raw: Optional[str], base_path: Path) -> Optional[str]:
    if not raw:
        return None
    candidate = os.path.expanduser(str(raw))
    candidate = os.path.normpath(candidate)
    if not os.path.isabs(candidate):
        candidate = os.path.normpath(os.path.join(base_path.parent, candidate))
    if os.path.exists(candidate):
        return candidate
    return None


def _rarity_label(rarity: str) -> str:
    return RARITY_LABELS.get(rarity, rarity.title())


def _rarity_color(rarity: str) -> str:
    return RARITY_COLORS.get(rarity, "#2a2f36")


def _rgba_color(hex_color: str, alpha: float) -> str:
    cleaned = hex_color.lstrip("#")
    if len(cleaned) != 6:
        return f"rgba(30, 34, 40, {alpha:.2f})"
    try:
        r = int(cleaned[0:2], 16)
        g = int(cleaned[2:4], 16)
        b = int(cleaned[4:6], 16)
    except ValueError:
        return f"rgba(30, 34, 40, {alpha:.2f})"
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def _core_rarities() -> List[str]:
    return [rarity for rarity in RARITY_ORDER if rarity != "artifact"]


def _format_tags(tags: Set[str]) -> str:
    if not tags:
        return "None"
    return ", ".join(sorted(tags))


def _format_category_list(categories: Set[str]) -> str:
    if not categories:
        return "No Category"
    labels = [CATEGORY_LABELS.get(key, key.title()) for key in sorted(categories)]
    return ", ".join(labels)


def _brighten_hex(hex_color: str, factor: int = 135) -> str:
    color = QColor(hex_color)
    if not color.isValid():
        return hex_color
    return color.lighter(factor).name()


def _pil_to_qimage(pil_image) -> QImage:
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(
        data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888
    )
    return qimage.copy()


class LootPreviewTooltip(QFrame):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip)
        self.setObjectName("PreviewTooltip")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(0)
        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._image)
        self.setStyleSheet(
            "QFrame#PreviewTooltip {"
            "background-color: #0d1117;"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
        )

    def show_preview(self, pixmap: QPixmap, global_pos: QPoint) -> None:
        if pixmap.isNull():
            return
        self._image.setPixmap(pixmap)
        self.adjustSize()
        target = global_pos + QPoint(12, 12)
        screen = QGuiApplication.screenAt(global_pos)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            x = min(target.x(), geom.right() - self.width())
            y = min(target.y(), geom.bottom() - self.height())
            x = max(geom.left(), x)
            y = max(geom.top(), y)
            target = QPoint(x, y)
        self.move(target)
        self.show()

    def show_preview_at(self, pixmap: QPixmap, top_left: QPoint) -> None:
        if pixmap.isNull():
            return
        self._image.setPixmap(pixmap)
        self.adjustSize()
        target = QPoint(top_left)
        screen = QGuiApplication.screenAt(top_left)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            x = min(target.x(), geom.right() - self.width())
            y = min(target.y(), geom.bottom() - self.height())
            x = max(geom.left(), x)
            y = max(geom.top(), y)
            target = QPoint(x, y)
        self.move(target)
        self.show()

    def hide_preview(self) -> None:
        self.hide()


class PresetRow(QFrame):
    def __init__(self, entry: PresetEntry, on_delete) -> None:
        super().__init__()
        # CRITICAL: Hide immediately to prevent flashing as a window before parent is set
        self.hide()
        self._entry = entry
        self._on_delete = on_delete
        self._trash_btn: Optional[QPushButton] = None
        self.setObjectName("PresetRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        name = QLabel(entry.name)
        name.setStyleSheet("background-color: transparent; color: #f5f6f7;")
        name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(name, 1)

        if not entry.built_in:
            trash_btn = QPushButton()
            trash_btn.setObjectName("DestructiveButton")
            trash_btn.setProperty("compact", True)
            trash_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            trash_btn.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
            trash_btn.setIconSize(QSize(12, 12))
            trash_btn.setFixedSize(24, 24)
            trash_btn.setStyleSheet(
                "QPushButton { border-radius: 4px; padding: 0px; min-height: 24px; min-width: 24px; }"
            )
            trash_btn.setToolTip("Delete preset")
            trash_btn.clicked.connect(lambda checked=False: self._on_delete(entry))
            layout.addWidget(
                trash_btn, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._trash_btn = trash_btn

        self.setStyleSheet(
            "QFrame#PresetRow {"
            "background-color: transparent;"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
            "QFrame#PresetRow:hover {"
            "background-color: #1c2128;"
            "border-color: #444c56;"
            "}"
        )
        self.setMinimumHeight(38)




def _slugify(name: str) -> str:
    cleaned = []
    for ch in name.strip().lower():
        if ch.isalnum() or ch in ("-", "_"):
            cleaned.append(ch)
        elif ch.isspace():
            cleaned.append("-")
    slug = re.sub(r"-+", "-", "".join(cleaned)).strip("-")
    return slug or "preset"


class LootResultRow(QFrame):
    def __init__(
        self,
        result: LootResultItem,
        icon_pixmap: Optional[QPixmap],
        on_lock,
        on_reroll,
        on_remove,
        on_hover,
        on_leave,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LootResultRow")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._result_id = result.result_id
        self._item = result.item
        self._on_hover = on_hover
        self._on_leave = on_leave
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        rarity_color = _rarity_color(result.item.rarity)
        tint = _rgba_color(rarity_color, 0.15)
        self.setStyleSheet(
            "QFrame#LootResultRow {"
            f"background-color: {tint};"
            "border: 1px solid #27272a;"
            "border-radius: 8px;"
            "}"
            "QFrame#LootResultRow:hover {"
            f"background-color: {_rgba_color(rarity_color, 0.22)};"
            "border-color: #4b5563;"
            "}"
        )

        self._icon_pixmap = icon_pixmap
        self._icon_label = QLabel(self)
        self._icon_label.setObjectName("LootResultIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setStyleSheet(
            "QLabel#LootResultIcon {"
            "background-color: transparent;"
            "border: 1px solid #5c5c6e;"
            "border-radius: 0px;"
            "}"
        )

        self._text_container = QWidget(self)
        text_layout = QVBoxLayout(self._text_container)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        title = QLabel(result.item.title, self)
        title.setWordWrap(True)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 4)
        title_font.setBold(True)
        title.setFont(title_font)
        title_color = _brighten_hex(rarity_color)
        title.setStyleSheet(f"background-color: transparent; color: {title_color};")

        level_label = QLabel(f"Lvl {result.item.level}", self)
        level_font = level_label.font()
        level_font.setPointSize(max(1, level_font.pointSize() - 1))
        level_label.setFont(level_font)
        level_label.setStyleSheet("background-color: transparent; color: #e5e7eb;")

        category_text = _format_category_list(result.item.categories)
        categories_label = QLabel(category_text, self)
        categories_font = categories_label.font()
        categories_font.setPointSize(max(1, categories_font.pointSize() - 2))
        categories_label.setFont(categories_font)
        categories_label.setStyleSheet("background-color: transparent; color: #9ca3af;")

        tags_label = QLabel(_format_tags(result.item.tags), self)
        tags_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        tags_label.setWordWrap(True)
        tags_font = tags_label.font()
        tags_font.setPointSize(max(1, tags_font.pointSize() - 3))
        tags_label.setFont(tags_font)
        tags_label.setStyleSheet("background-color: transparent; color: #71717a;")

        status_label = QLabel(self)
        status_parts = []
        if result.guaranteed:
            status_parts.append("Guaranteed")
        elif result.locked:
            status_parts.append("Locked")
        status_label.setText(" / ".join(status_parts))
        status_label.setStyleSheet(
            "background-color: transparent; color: #3b82f6; font-weight: 600;"
        )
        status_label.setVisible(bool(status_parts))

        tags_row = QHBoxLayout()
        tags_row.setContentsMargins(0, 0, 0, 0)
        tags_row.setSpacing(6)
        tags_row.addWidget(tags_label, 1)
        if status_label.isVisible():
            tags_row.addWidget(
                status_label, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

        text_layout.addWidget(title)
        text_layout.addWidget(level_label)
        text_layout.addWidget(categories_label)
        text_layout.addLayout(tags_row)
        self._text_container.setMinimumHeight(RESULT_ICON_SIZE)
        self._text_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)
        button_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        lock_button = QPushButton("Locked" if result.locked else "Lock", self)
        lock_button.setCheckable(True)
        lock_button.setChecked(result.locked)
        lock_button.setObjectName("SecondaryButton")
        lock_button.setProperty("compact", True)
        lock_button.clicked.connect(
            lambda checked=False, rid=self._result_id: on_lock(rid)
        )

        reroll_button = QPushButton("Re-roll", self)
        reroll_button.setObjectName("SecondaryButton")
        reroll_button.setProperty("compact", True)
        reroll_button.clicked.connect(
            lambda checked=False, rid=self._result_id: on_reroll(rid)
        )

        remove_button = QPushButton("Remove", self)
        remove_button.setObjectName("DestructiveButton")
        remove_button.setProperty("compact", True)
        remove_button.clicked.connect(
            lambda checked=False, rid=self._result_id: on_remove(rid)
        )

        if result.guaranteed:
            lock_button.setEnabled(False)
            reroll_button.setEnabled(False)

        button_layout.addWidget(lock_button)
        button_layout.addWidget(reroll_button)
        button_layout.addWidget(remove_button)

        layout.addWidget(self._icon_label, 0)
        layout.addWidget(self._text_container, 1)
        layout.addLayout(button_layout, 0)

        self._sync_icon_size()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_icon_size()

    def _sync_icon_size(self) -> None:
        if not hasattr(self, "_text_container") or not hasattr(self, "_icon_label"):
            return
        target = self._text_container.height()
        if target <= 0:
            target = self._text_container.sizeHint().height()
        if target <= 0:
            target = RESULT_ICON_SIZE
        target = max(RESULT_ICON_SIZE, target)
        icon_size = max(12, target)
        if self._icon_label.width() != icon_size or self._icon_label.height() != icon_size:
            self._icon_label.setFixedSize(icon_size, icon_size)
        if self._icon_pixmap:
            if self._icon_pixmap.width() == icon_size and self._icon_pixmap.height() == icon_size:
                self._icon_label.setPixmap(self._icon_pixmap)
            else:
                scaled = self._icon_pixmap.scaled(
                    icon_size,
                    icon_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self._icon_label.setPixmap(scaled)
        else:
            self._icon_label.setText("•")

    def enterEvent(self, event) -> None:
        if self._on_hover:
            self._on_hover(self._item, self)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self._on_leave:
            self._on_leave()
        super().leaveEvent(event)


class LootAppletWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(1100, 680)
        self._item_library: List[LootItem] = []
        self._item_by_id: Dict[str, LootItem] = {}
        self._filtered_pool: List[LootItem] = []
        self._base_filtered_pool: List[LootItem] = []
        self._results: List[LootResultItem] = []
        self._next_result_id = 1
        self._guaranteed_ids: Set[str] = set()
        self._limited_pool_ids: Set[str] = set()
        self._rng = random.Random()
        self._loading_preset = False
        self._custom_weights_enabled = False
        self._updating_weight_sliders = False
        self._syncing_luck = False
        self._syncing_group_level = False
        self._syncing_rolls = False
        self._preset_entries: List[PresetEntry] = []
        self._weight_sliders: Dict[str, QSlider] = {}
        self._weight_value_labels: Dict[str, QLabel] = {}
        self._prob_value_labels: Dict[str, QLabel] = {}
        self._pool_value_labels: Dict[str, QLabel] = {}
        self._category_checks: Dict[str, QCheckBox] = {}
        self._category_labels: Dict[str, str] = {}
        self._generate_button_default_text = "Generate Loot"
        self._preview_cache: Dict[Tuple[str, int, int, int], QPixmap] = {}
        self._preview_tooltip = LootPreviewTooltip()
        self._library_widget_map: Dict[QObject, QListWidget] = {}

        self._preset_dir = Path(default_dnd_save_dir()) / "loot" / "presets"
        self._results_dir = Path(default_dnd_save_dir()) / "loot" / "results"
        os.makedirs(self._preset_dir, exist_ok=True)
        os.makedirs(self._results_dir, exist_ok=True)

        self._build_ui()
        self._load_item_library()
        self._load_presets()
        self._update_preview()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "_guaranteed_list", None) and getattr(self, "_limited_list", None):
            self._update_library_grids()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        config_scroll = QScrollArea()
        config_scroll.setWidgetResizable(True)
        config_scroll.setFrameShape(QFrame.Shape.NoFrame)
        config_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        config_scroll.setWidget(self._build_config_panel())

        layout.addWidget(config_scroll, 12)
        layout.addWidget(self._build_center_panel(), 13)

    def _build_config_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(10)

        title = QLabel("Settings")
        title.setObjectName("PanelTitle")
        panel_layout.addWidget(title)

        cols_container = QWidget()
        cols_layout = QHBoxLayout(cols_container)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.setSpacing(10)

        # Left Column: Settings
        left_col = QVBoxLayout()
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(10)
        
        left_col.addWidget(self._build_core_inputs_section())
        left_col.addWidget(self._build_filters_section())
        
        guaranteed_section = self._build_guaranteed_section()
        guaranteed_section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_col.addWidget(guaranteed_section)

        # Right Column: Preview & Controls
        right_col = QVBoxLayout()
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(10)
        
        limited_section = self._build_limited_pool_section()
        limited_section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_col.addWidget(limited_section)
        
        presets_section = self._build_presets_panel()
        presets_section.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_col.addWidget(presets_section)

        right_col.addWidget(self._build_controls_section())

        cols_layout.addLayout(left_col, 1)
        cols_layout.addLayout(right_col, 1)
        
        panel_layout.addWidget(cols_container, 1)

        self._generate_button = QPushButton(self._generate_button_default_text)
        self._generate_button.setObjectName("PrimaryButton")
        self._generate_button.clicked.connect(
            lambda checked=False: self._generate_loot(preserve_locked=False)
        )
        panel_layout.addWidget(self._generate_button)
        
        return panel

    def _build_core_inputs_section(self) -> QFrame:
        core = self._build_section("Core Inputs")
        core_layout = core.layout()

        level_label = QLabel("Group Level")
        level_label.setObjectName("ColumnHeader")
        level_row = QHBoxLayout()
        self._group_level_slider = QSlider(Qt.Orientation.Horizontal)
        self._group_level_slider.setRange(1, LEVEL_CAP)
        self._group_level_slider.setValue(5)
        self._group_level_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._group_level_slider.setTickInterval(1)
        self._group_level_slider.valueChanged.connect(self._on_group_level_slider_changed)
        self._group_level_spin = PlusMinusSpinBox()
        self._group_level_spin.setRange(1, 20)
        self._group_level_spin.setValue(5)
        self._group_level_spin.valueChanged.connect(self._on_group_level_spin_changed)
        self._group_level_spin.setFixedWidth(CONTROL_SPIN_WIDTH)
        level_row.addWidget(self._group_level_slider, 1)
        level_row.addWidget(self._group_level_spin)
        level_help = QLabel("Items are capped at level +2.")

        rolls_label = QLabel("Roll Amount")
        rolls_label.setObjectName("ColumnHeader")
        rolls_row = QHBoxLayout()
        self._rolls_slider = QSlider(Qt.Orientation.Horizontal)
        self._rolls_slider.setRange(1, ROLLS_MAX)
        self._rolls_slider.setValue(4)
        self._rolls_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._rolls_slider.setTickInterval(1)
        self._rolls_slider.valueChanged.connect(self._on_rolls_slider_changed)
        self._rolls_spin = PlusMinusSpinBox()
        self._rolls_spin.setRange(1, 50)
        self._rolls_spin.setValue(4)
        self._rolls_spin.valueChanged.connect(self._on_rolls_spin_changed)
        self._rolls_spin.setFixedWidth(CONTROL_SPIN_WIDTH)
        rolls_row.addWidget(self._rolls_slider, 1)
        rolls_row.addWidget(self._rolls_spin)

        luck_label = QLabel("Luck (1-100)")
        luck_label.setObjectName("ColumnHeader")
        luck_row = QHBoxLayout()
        self._luck_slider = QSlider(Qt.Orientation.Horizontal)
        self._luck_slider.setRange(
            int(LUCK_MIN * LUCK_SLIDER_SCALE),
            int(LUCK_MAX * LUCK_SLIDER_SCALE),
        )
        self._luck_slider.setValue(int(DEFAULT_LUCK * LUCK_SLIDER_SCALE))
        self._luck_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._luck_slider.setTickInterval(int(10 * LUCK_SLIDER_SCALE))
        self._luck_slider.setSingleStep(1)
        self._luck_slider.valueChanged.connect(self._on_luck_slider_changed)
        self._luck_spin = PlusMinusSpinBox()
        self._luck_spin.setRange(int(LUCK_MIN), int(LUCK_MAX))
        self._luck_spin.setSingleStep(1)
        self._luck_spin.setValue(int(DEFAULT_LUCK))
        self._luck_spin.valueChanged.connect(self._on_luck_spin_changed)
        self._luck_spin.setFixedWidth(CONTROL_SPIN_WIDTH)
        luck_row.addWidget(self._luck_slider, 1)
        luck_row.addWidget(self._luck_spin)
        luck_help = QLabel("Luck drives the base rarity curve.")

        self._curve_combo = QComboBox()
        self._curve_combo.addItems(RARITY_CURVES)
        self._curve_combo.currentTextChanged.connect(self._on_settings_changed)

        core_layout.addWidget(level_label)
        core_layout.addLayout(level_row)
        core_layout.addWidget(level_help)
        core_layout.addSpacing(6)
        core_layout.addWidget(rolls_label)
        core_layout.addLayout(rolls_row)
        core_layout.addSpacing(6)
        core_layout.addWidget(luck_label)
        core_layout.addLayout(luck_row)
        core_layout.addWidget(luck_help)
        return core

    def _build_filters_section(self) -> QFrame:
        filters = self._build_section("Filters")
        filters_layout = filters.layout()

        tags_label = QLabel("Tags (comma separated)")
        tags_label.setObjectName("ColumnHeader")
        self._tags_edit = QLineEdit()
        self._tags_edit.setPlaceholderText("e.g. potion, scroll, undead")
        self._tags_edit.textChanged.connect(self._on_settings_changed)
        filters_layout.addWidget(tags_label)
        filters_layout.addWidget(self._tags_edit)
        filters_layout.addSpacing(8)

        category_label = QLabel("Item Categories")
        category_label.setObjectName("ColumnHeader")
        self._category_container = QWidget()
        self._category_layout = QGridLayout(self._category_container)
        self._category_layout.setContentsMargins(0, 0, 0, 0)
        self._category_layout.setSpacing(8)

        filters_layout.addWidget(category_label)
        filters_layout.addWidget(self._category_container)
        return filters

    def _build_guaranteed_section(self) -> QFrame:
        guaranteed = self._build_section("Guaranteed Items")
        guaranteed_layout = guaranteed.layout()
        header_item = guaranteed_layout.takeAt(0)
        if header_item and header_item.widget():
            header_item.widget().deleteLater()
        header_row = QHBoxLayout()
        header_label = QLabel("Guaranteed Items")
        header_label.setObjectName("ColumnHeader")
        self._library_status = QLabel("Library: 0 items")
        self._library_status.setObjectName("SelectionType")
        header_row.addWidget(header_label)
        header_row.addStretch(1)
        header_row.addWidget(self._library_status)
        guaranteed_layout.addLayout(header_row)
        self._guaranteed_search = QLineEdit()
        self._guaranteed_search.setPlaceholderText("Search item library...")
        self._guaranteed_search.textChanged.connect(self._filter_guaranteed_list)

        self._guaranteed_list = QListWidget()
        self._guaranteed_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._guaranteed_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._guaranteed_list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._guaranteed_list.setFlow(QListView.Flow.LeftToRight)
        self._guaranteed_list.setWrapping(True)
        self._guaranteed_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._guaranteed_list.setViewMode(QListView.ViewMode.IconMode)
        self._guaranteed_list.setUniformItemSizes(True)
        self._guaranteed_list.setStyleSheet(
            "QListWidget::indicator { width: 0px; height: 0px; }"
            "QListWidget::item { background-color: transparent; padding: 0px; margin: 0px; }"
            "QListWidget::item:selected { background-color: transparent; }"
            "QListWidget::item:selected:active { background-color: transparent; }"
            "QListWidget::item:selected:!active { background-color: transparent; }"
            "QListWidget::item:hover { background-color: transparent; }"
        )
        self._guaranteed_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._guaranteed_list.setSelectionRectVisible(False)
        self._guaranteed_list.setSpacing(6)
        self._guaranteed_list.setWordWrap(True)
        self._guaranteed_list.setMouseTracking(True)
        self._guaranteed_list.viewport().setMouseTracking(True)
        self._guaranteed_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._guaranteed_list.verticalScrollBar().setSingleStep(4)
        self._guaranteed_list.setMinimumHeight(216)
        self._guaranteed_list.itemEntered.connect(self._on_library_item_hover)
        self._guaranteed_list.viewport().installEventFilter(self)
        self._guaranteed_list.itemChanged.connect(self._on_guaranteed_item_changed)

        guaranteed_row = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Library")
        refresh_btn.setObjectName("SecondaryButton")
        refresh_btn.setProperty("compact", "true")
        refresh_btn.clicked.connect(self._load_item_library)
        clear_btn = QPushButton("Clear Guaranteed")
        clear_btn.setObjectName("SecondaryButton")
        clear_btn.setProperty("compact", "true")
        clear_btn.clicked.connect(self._clear_guaranteed)
        guaranteed_row.addWidget(self._guaranteed_search, 1)
        guaranteed_row.addWidget(refresh_btn)
        guaranteed_row.addWidget(clear_btn)

        guaranteed_layout.addLayout(guaranteed_row)
        guaranteed_layout.addWidget(self._guaranteed_list)
        return guaranteed

    def _build_limited_pool_section(self) -> QFrame:
        limited = self._build_section("Limited Pool")
        limited_layout = limited.layout()
        limited_header_item = limited_layout.takeAt(0)
        if limited_header_item and limited_header_item.widget():
            limited_header_item.widget().deleteLater()
        limited_header_row = QHBoxLayout()
        limited_header_label = QLabel("Limited Pool")
        limited_header_label.setObjectName("ColumnHeader")
        self._limited_search = QLineEdit()
        self._limited_search.setPlaceholderText("Search item library...")
        self._limited_search.textChanged.connect(self._filter_limited_pool_list)

        self._limited_status = QLabel("Limited Pool: 0 selected")
        self._limited_status.setObjectName("SelectionType")
        limited_header_row.addWidget(limited_header_label)
        limited_header_row.addStretch(1)
        limited_header_row.addWidget(self._limited_status)
        limited_layout.addLayout(limited_header_row)

        self._limited_list = QListWidget()
        self._limited_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._limited_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._limited_list.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self._limited_list.setFlow(QListView.Flow.LeftToRight)
        self._limited_list.setWrapping(True)
        self._limited_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._limited_list.setViewMode(QListView.ViewMode.IconMode)
        self._limited_list.setUniformItemSizes(True)
        self._limited_list.setStyleSheet(
            "QListWidget::indicator { width: 0px; height: 0px; }"
            "QListWidget::item { background-color: transparent; padding: 0px; margin: 0px; }"
            "QListWidget::item:selected { background-color: transparent; }"
            "QListWidget::item:selected:active { background-color: transparent; }"
            "QListWidget::item:selected:!active { background-color: transparent; }"
            "QListWidget::item:hover { background-color: transparent; }"
        )
        self._limited_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._limited_list.setSelectionRectVisible(False)
        self._limited_list.setSpacing(6)
        self._limited_list.setWordWrap(True)
        self._limited_list.setMouseTracking(True)
        self._limited_list.viewport().setMouseTracking(True)
        self._limited_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._limited_list.verticalScrollBar().setSingleStep(4)
        self._limited_list.setMinimumHeight(216)
        self._limited_list.itemEntered.connect(self._on_library_item_hover)
        self._limited_list.viewport().installEventFilter(self)
        self._limited_list.itemChanged.connect(self._on_limited_pool_item_changed)

        limited_row = QHBoxLayout()
        clear_limited_btn = QPushButton("Clear Limited Pool")
        clear_limited_btn.setObjectName("SecondaryButton")
        clear_limited_btn.setProperty("compact", "true")
        clear_limited_btn.clicked.connect(self._clear_limited_pool)
        limited_row.addWidget(self._limited_search, 1)
        limited_row.addWidget(clear_limited_btn)

        limited_layout.addLayout(limited_row)
        limited_layout.addWidget(self._limited_list)
        return limited

    def _build_center_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(10)

        title = QLabel("Generated Loot")
        title.setObjectName("PanelTitle")
        panel_layout.addWidget(title)

        header_row = QHBoxLayout()
        self._rolls_label = QLabel("Rolls: 0")
        self._pool_label = QLabel("Pool: 0 items")
        self._rolls_label.setObjectName("SelectionType")
        self._pool_label.setObjectName("SelectionType")
        header_row.addWidget(self._rolls_label)
        header_row.addStretch(1)
        header_row.addWidget(self._pool_label)
        panel_layout.addLayout(header_row)

        weights_panel = self._build_section("Loot Table")
        grid_container = QFrame()
        grid_container.setObjectName("LootTableGrid")
        grid_container.setStyleSheet(
            "QFrame#LootTableGrid {"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
            "QFrame#LootTableCell {"
            "border-right: 1px solid #30363d;"
            "border-bottom: 1px solid #30363d;"
            "}"
            "QFrame#LootTableCell[last_col=\"true\"] {"
            "border-right: 0;"
            "}"
            "QFrame#LootTableCell[last_row=\"true\"] {"
            "border-bottom: 0;"
            "}"
            "QFrame#LootTableCell QLabel {"
            "background-color: transparent;"
            "}"
        )
        weights_layout = QGridLayout(grid_container)
        weights_layout.setContentsMargins(0, 0, 0, 0)
        weights_layout.setHorizontalSpacing(0)
        weights_layout.setVerticalSpacing(0)
        weights_panel.layout().addWidget(grid_container)

        header_labels: List[QLabel] = []
        label_widgets: List[QLabel] = []
        value_widgets: List[QLabel] = []
        prob_widgets: List[QLabel] = []
        pool_widgets: List[QLabel] = []

        header_rarity = QLabel("Rarity")
        header_weight = QLabel("Weight")
        header_prob = QLabel("Prob ≥ 1")
        header_pool = QLabel("Pool")
        header_adjust = QLabel("Adjust")
        for header in (header_rarity, header_weight, header_prob, header_pool, header_adjust):
            header.setObjectName("ColumnHeader")
            header_labels.append(header)
            header.setAlignment(Qt.AlignmentFlag.AlignCenter)

        weights_layout.addWidget(
            self._wrap_table_cell(header_rarity, False, False), 0, 0
        )
        weights_layout.addWidget(
            self._wrap_table_cell(header_weight, False, False), 0, 1
        )
        weights_layout.addWidget(
            self._wrap_table_cell(header_prob, False, False), 0, 2
        )
        weights_layout.addWidget(
            self._wrap_table_cell(header_pool, False, False), 0, 3
        )
        weights_layout.addWidget(
            self._wrap_table_cell(header_adjust, True, False), 0, 4
        )

        for row, rarity in enumerate(RARITY_ORDER, start=1):
            label = QLabel(_rarity_label(rarity))
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 100 * SLIDER_SCALE)
            slider.setValue(0)
            slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            slider.valueChanged.connect(
                lambda value, rarity_key=rarity: self._on_weight_slider_changed(
                    rarity_key, value
                )
            )
            value_label = QLabel("0.0%")
            prob_label = QLabel("0%")
            pool_label = QLabel("0")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            prob_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pool_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._weight_sliders[rarity] = slider
            self._weight_value_labels[rarity] = value_label
            self._prob_value_labels[rarity] = prob_label
            self._pool_value_labels[rarity] = pool_label
            label_widgets.append(label)
            value_widgets.append(value_label)
            prob_widgets.append(prob_label)
            pool_widgets.append(pool_label)

            is_last_row = row == len(RARITY_ORDER)
            weights_layout.addWidget(
                self._wrap_table_cell(label, False, is_last_row), row, 0
            )
            weights_layout.addWidget(
                self._wrap_table_cell(value_label, False, is_last_row), row, 1
            )
            weights_layout.addWidget(
                self._wrap_table_cell(prob_label, False, is_last_row), row, 2
            )
            weights_layout.addWidget(
                self._wrap_table_cell(pool_label, False, is_last_row), row, 3
            )
            weights_layout.addWidget(
                self._wrap_table_cell(slider, True, is_last_row), row, 4
            )

        label_width = max(
            label.fontMetrics().horizontalAdvance(label.text())
            for label in label_widgets + header_labels
        ) + 16
        for label in label_widgets + [header_rarity]:
            label.setFixedWidth(label_width)
        for value_label in value_widgets + [header_weight]:
            value_label.setFixedWidth(72)
        for prob_label in prob_widgets + [header_prob]:
            prob_label.setFixedWidth(72)
        for pool_label in pool_widgets + [header_pool]:
            pool_label.setFixedWidth(60)

        weights_layout.setColumnStretch(4, 1)

        divider = QFrame()
        divider.setObjectName("LootTableDivider")
        divider.setFixedHeight(1)
        divider.setStyleSheet("background-color: #30363d;")
        weights_layout.addWidget(
            divider,
            len(RARITY_ORDER) + 1,
            0,
            1,
            5,
        )

        self._weights_reset_btn = self._make_reset_button("Reset to Luck")
        self._weights_reset_btn.clicked.connect(self._reset_weights_to_luck)
        weights_layout.addWidget(
            self._weights_reset_btn,
            len(RARITY_ORDER) + 2,
            0,
            1,
            5,
            Qt.AlignmentFlag.AlignRight,
        )

        panel_layout.addWidget(weights_panel)

        curve_row = QHBoxLayout()
        curve_label = QLabel("Rarity Curve")
        curve_label.setObjectName("ColumnHeader")
        curve_row.addWidget(curve_label)
        curve_row.addWidget(self._curve_combo, 1)
        panel_layout.addLayout(curve_row)

        results_panel = self._build_section("Generated Loot Result")
        results_layout = results_panel.layout()

        self._results_scroll = QScrollArea()
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(8)
        self._results_scroll.setWidget(self._results_container)
        self._results_scroll.verticalScrollBar().setSingleStep(4)
        results_layout.addWidget(self._results_scroll)

        panel_layout.addWidget(results_panel, 1)

        export_row = QHBoxLayout()
        export_row.setContentsMargins(0, 0, 0, 0)
        self._save_results_btn = QPushButton("Save Results")
        self._save_results_btn.setObjectName("SecondaryButton")
        self._save_results_btn.setProperty("compact", "true")
        self._save_results_btn.clicked.connect(self._save_generated_results)
        self._load_results_btn = QPushButton("Load Results")
        self._load_results_btn.setObjectName("SecondaryButton")
        self._load_results_btn.setProperty("compact", "true")
        self._load_results_btn.clicked.connect(self._load_generated_results)
        self._export_pdf_btn = QPushButton("Export Loot PDF")
        self._export_pdf_btn.setObjectName("SecondaryButton")
        self._export_pdf_btn.setProperty("compact", "true")
        self._export_pdf_btn.clicked.connect(self._export_loot_pdf)
        export_row.addStretch(1)
        export_row.addWidget(self._save_results_btn)
        export_row.addWidget(self._load_results_btn)
        export_row.addWidget(self._export_pdf_btn)
        panel_layout.addLayout(export_row)
        return panel

    def _make_reset_button(self, tooltip: str) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("InlineResetButton")
        btn.setIcon(QIcon(RESET_ICON))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _build_controls_section(self) -> QFrame:
        controls = self._build_section("Controls")
        controls_layout = controls.layout()

        self._reroll_all_btn = QPushButton("Re-roll All Items")
        self._reroll_all_btn.setObjectName("PrimaryButton")
        self._reroll_all_btn.setProperty("compact", "true")
        self._reroll_all_btn.clicked.connect(
            lambda checked=False: self._generate_loot(preserve_locked=False)
        )
        self._reroll_unlocked_btn = QPushButton("Re-roll Unlocked Items")
        self._reroll_unlocked_btn.setObjectName("SecondaryButton")
        self._reroll_unlocked_btn.setProperty("compact", "true")
        self._reroll_unlocked_btn.clicked.connect(
            lambda checked=False: self._generate_loot(preserve_locked=True)
        )

        controls_layout.addWidget(self._reroll_all_btn)
        controls_layout.addWidget(self._reroll_unlocked_btn)
        return controls

    def _build_presets_panel(self) -> QFrame:
        presets = self._build_section("Presets")
        presets_layout = presets.layout()

        preset_buttons = QHBoxLayout()
        self._preset_save_btn = QPushButton("Save Preset")
        self._preset_save_btn.setObjectName("PrimaryButton")
        self._preset_save_btn.setProperty("compact", "true")
        self._preset_save_btn.clicked.connect(self._save_preset)
        preset_buttons.addWidget(self._preset_save_btn)
        preset_buttons.addStretch(1)

        presets_layout.addLayout(preset_buttons)
        self._preset_list = QListWidget()
        self._preset_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._preset_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._preset_list.setSelectionRectVisible(False)
        self._preset_list.setStyleSheet(
            "QListWidget::item { background-color: transparent; padding: 0px; margin: 0px; }"
            "QListWidget::item:selected { background-color: transparent; }"
            "QListWidget::item:selected:active { background-color: transparent; }"
            "QListWidget::item:selected:!active { background-color: transparent; }"
            "QListWidget::item:hover { background-color: transparent; }"
        )
        self._preset_list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel
        )
        self._preset_list.verticalScrollBar().setSingleStep(4)
        self._preset_list.setSpacing(6)
        self._preset_list.setMinimumHeight(240)
        self._preset_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preset_list.itemClicked.connect(self._on_preset_clicked)
        presets_layout.addWidget(self._preset_list)
        return presets

    def _build_section(self, title: str) -> QFrame:
        section = QFrame()
        section.setObjectName("SubPanel")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("ColumnHeader")
        layout.addWidget(label)
        return section

    def _wrap_table_cell(
        self, widget: QWidget, is_last_col: bool, is_last_row: bool
    ) -> QFrame:
        cell = QFrame()
        cell.setObjectName("LootTableCell")
        cell.setProperty("last_col", is_last_col)
        cell.setProperty("last_row", is_last_row)
        layout = QHBoxLayout(cell)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        if isinstance(widget, QSlider):
            layout.addWidget(widget, 1)
        else:
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignCenter)
        return cell

    def _show_placeholder(self, title: str) -> None:
        QMessageBox.information(self, "Placeholder", f"{title} is not implemented yet.")

    def _on_luck_slider_changed(self, value: int) -> None:
        if self._syncing_luck:
            return
        self._syncing_luck = True
        self._luck_spin.setValue(int(round(value / LUCK_SLIDER_SCALE)))
        self._syncing_luck = False
        self._on_settings_changed()

    def _on_luck_spin_changed(self, value: int) -> None:
        if self._syncing_luck:
            return
        self._syncing_luck = True
        self._luck_slider.setValue(int(round(value * LUCK_SLIDER_SCALE)))
        self._syncing_luck = False
        self._on_settings_changed()

    def _on_group_level_slider_changed(self, value: int) -> None:
        if self._syncing_group_level:
            return
        self._syncing_group_level = True
        self._group_level_spin.setValue(value)
        self._syncing_group_level = False
        self._on_settings_changed()

    def _on_group_level_spin_changed(self, value: int) -> None:
        if self._syncing_group_level:
            return
        self._syncing_group_level = True
        self._group_level_slider.setValue(value)
        self._syncing_group_level = False
        self._on_settings_changed()

    def _on_rolls_slider_changed(self, value: int) -> None:
        if self._syncing_rolls:
            return
        self._syncing_rolls = True
        self._rolls_spin.setValue(value)
        self._syncing_rolls = False
        self._on_settings_changed()

    def _on_rolls_spin_changed(self, value: int) -> None:
        if self._syncing_rolls:
            return
        self._syncing_rolls = True
        self._rolls_slider.setValue(value)
        self._syncing_rolls = False
        self._on_settings_changed()

    def _on_settings_changed(self) -> None:
        if not self._loading_preset:
            self._select_custom_preset()
        self._update_preview()

    def _select_custom_preset(self) -> None:
        if not hasattr(self, "_preset_list") or self._preset_list.count() == 0:
            return
        self._preset_list.blockSignals(True)
        self._preset_list.setCurrentItem(None)
        self._preset_list.blockSignals(False)

    def _on_weight_slider_changed(self, rarity: str, value: int) -> None:
        if self._updating_weight_sliders:
            return
        self._custom_weights_enabled = True
        self._update_preview()

    def _sync_weight_sliders(self, weights: Dict[str, float]) -> None:
        self._updating_weight_sliders = True
        for rarity, slider in self._weight_sliders.items():
            value = int(round(weights.get(rarity, 0.0) * SLIDER_SCALE))
            slider.setValue(value)
        self._updating_weight_sliders = False

    def _refresh_weight_labels(self, probabilities: Dict[str, float]) -> None:
        for rarity, label in self._weight_value_labels.items():
            value = probabilities.get(rarity, 0.0)
            label.setText(f"{value:.2f}%")

    def _reset_weights_to_luck(self) -> None:
        self._custom_weights_enabled = False
        self._sync_weight_sliders(self._calculate_weights())
        self._update_preview()

    def _coerce_luck_value(self, raw) -> float:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return self._current_luck()
        if -2.0 <= value <= 2.0:
            scaled = ((value + 2.0) / 4.0) * (LUCK_MAX - LUCK_MIN) + LUCK_MIN
            return max(LUCK_MIN, min(LUCK_MAX, scaled))
        return max(LUCK_MIN, min(LUCK_MAX, value))

    def _load_item_library(self) -> None:
        selected_categories = {
            key for key, cb in self._category_checks.items() if cb.isChecked()
        }
        self._item_library.clear()
        self._item_by_id.clear()
        self._preview_cache.clear()
        self._category_labels.clear()
        self._category_labels.update(CATEGORY_LABELS)
        for root in self._item_dirs():
            if not root.exists():
                continue
            for path in list_item_file_paths(root):
                item = self._item_from_path(path)
                if not item:
                    continue
                if item.item_id in self._item_by_id:
                    continue
                self._item_library.append(item)
                self._item_by_id[item.item_id] = item
                for category in sorted(item.categories):
                    if category not in self._category_labels:
                        self._category_labels[category] = category.title()

        available_ids = set(self._item_by_id.keys())
        self._guaranteed_ids &= available_ids
        self._limited_pool_ids &= available_ids
        self._item_library.sort(key=lambda item: item.title.lower())
        self._rebuild_category_filters(selected_categories)
        self._refresh_guaranteed_list()
        self._refresh_limited_pool_list()
        self._update_preview()

    def _item_dirs(self) -> List[Path]:
        return [items_dir()]

    def _item_from_path(self, path: Path) -> Optional[LootItem]:
        data = load_item_payload(path)
        if not isinstance(data, dict):
            return None

        title, rarity = self._parse_item_fields(data)
        if rarity is None:
            return None
        level = self._parse_item_level(data)
        if level is None or level > LEVEL_CAP:
            return None
        tags = _normalize_tags(data.get("tags"))
        categories = _normalize_categories(
            data.get("category", data.get("categories"))
        )
        for key in CATEGORY_LABELS:
            if key in tags:
                categories.add(key)
        if tags:
            tags = {tag for tag in tags if tag not in CATEGORY_LABELS}
        category_label = _category_label_from_categories(categories)
        icon_path = _resolve_icon_path(
            data.get("icon_path") or data.get("icon") or data.get("preview_image"),
            path,
        )

        item_id = str(path.resolve())
        show_padding = bool(data.get("show_icon_padding", True))
        return LootItem(
            item_id=item_id,
            title=title,
            rarity=rarity,
            category_label=category_label,
            categories=categories,
            level=level,
            tags=tags,
            icon_path=icon_path,
            path=str(path),
            show_icon_padding=show_padding,
        )

    def _rarity_color_for_item(self, item: LootItem, alpha: float) -> QColor:
        hex_color = _rarity_color(item.rarity)
        cleaned = hex_color.lstrip("#")
        if len(cleaned) != 6:
            return QColor(30, 34, 40, int(alpha * 255))
        try:
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
        except ValueError:
            return QColor(30, 34, 40, int(alpha * 255))
        return QColor(r, g, b, int(alpha * 255))

    def _build_library_icon(self, item: LootItem, size: int = ICON_SIZE) -> QPixmap:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        base_color = self._rarity_color_for_item(item, 1.0)
        grad = QRadialGradient(size / 2, size / 2, size / 2)
        grad.setColorAt(0.0, base_color.lighter(135))
        grad.setColorAt(0.55, base_color)
        grad.setColorAt(1.0, base_color.darker(180))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(0, 0, size, size, grad)
        painter.setPen(QColor(25, 28, 33))
        painter.drawRect(1, 1, size - 2, size - 2)
        painter.setPen(QColor(200, 200, 210, 80))
        painter.drawRect(2, 2, size - 4, size - 4)

        if item.icon_path:
            icon = QPixmap(item.icon_path)
            if not icon.isNull():
                if item.show_icon_padding:
                    inner_size = int(round(size * 0.75))
                else:
                    inner_size = size
                
                scaled = icon.scaled(
                    inner_size,
                    inner_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (size - scaled.width()) // 2
                y = (size - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
        painter.end()
        return pixmap

    def _parse_item_fields(self, data: Dict[str, object]):
        if SPEC_AVAILABLE:
            spec = spec_from_dict(data)
            title = spec.title
            rarity = _normalize_rarity(spec.rarity)
            return title, rarity

        title = str(data.get("title", "Untitled Item"))
        rarity = _normalize_rarity(str(data.get("rarity", "")))
        return title, rarity

    def _parse_item_level(self, data: Dict[str, object]) -> Optional[int]:
        raw = data.get("level", data.get("required_level"))
        if raw is None:
            return None
        try:
            level = int(raw)
        except (TypeError, ValueError):
            return None
        if level < 1:
            return None
        return level

    def _build_library_row(self, item: LootItem, checked: bool) -> tuple[QListWidgetItem, QWidget]:
        row = QListWidgetItem("")
        row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        row.setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        )
        row.setBackground(QBrush(Qt.GlobalColor.transparent))
        row.setData(Qt.ItemDataRole.UserRole, item.item_id)
        row.setData(Qt.ItemDataRole.UserRole + 1, item.title.lower())
        tooltip_parts = [f"lvl {item.level}", _rarity_label(item.rarity)]
        if item.category_label:
            tooltip_parts.append(item.category_label)
        row.setToolTip(" \u2022 ".join(tooltip_parts))

        widget = QWidget()
        widget.setObjectName("LootLibraryRow")
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(10)

        check_box = QCheckBox()
        check_box.setText("")
        check_box.setChecked(checked)
        check_box.setFixedSize(18, 18)
        check_box.setStyleSheet(
            "QCheckBox { background-color: transparent; padding: 0px; spacing: 0px; }"
        )
        check_box.stateChanged.connect(
            lambda state, target=row: target.setCheckState(
                Qt.CheckState.Checked if state == Qt.CheckState.Checked.value else Qt.CheckState.Unchecked
            )
        )
        layout.addWidget(check_box, 0, Qt.AlignmentFlag.AlignVCenter)

        icon_label = QLabel()
        icon_label.setFixedSize(ICON_SIZE, ICON_SIZE)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_pixmap = self._build_library_icon(item)
        icon_label.setPixmap(icon_pixmap)
        layout.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(0)

        name_label = QLabel(item.title)
        name_label.setWordWrap(True)
        name_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        name_font = name_label.font()
        name_font.setBold(True)
        name_label.setFont(name_font)
        name_label.setStyleSheet("background: transparent; border: none; color: #7fd18c;")

        level_label = QLabel(f"lvl {item.level}")
        level_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        level_font = level_label.font()
        level_font.setPointSize(max(1, level_font.pointSize() - 1))
        level_label.setFont(level_font)
        level_label.setStyleSheet("background: transparent; border: none; color: #f5f6f7;")

        text_col.addStretch(1)
        text_col.addWidget(name_label)
        text_col.addWidget(level_label)
        text_col.addStretch(1)

        layout.addLayout(text_col, 1)

        base_color = self._rarity_color_for_item(item, 0.18)
        hover_color = self._rarity_color_for_item(item, 0.28)
        widget.setStyleSheet(
            "QWidget#LootLibraryRow {"
            f"background-color: rgba({base_color.red()}, {base_color.green()}, {base_color.blue()},"
            f" {base_color.alpha() / 255:.2f});"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
            "QWidget#LootLibraryRow:hover {"
            f"background-color: rgba({hover_color.red()}, {hover_color.green()}, {hover_color.blue()},"
            f" {hover_color.alpha() / 255:.2f});"
            "border-color: #4b5563;"
            "}"
        )
        return row, widget

    def _clear_library_widget_map(self, list_widget: QListWidget) -> None:
        if not self._library_widget_map:
            return
        self._library_widget_map = {
            obj: widget
            for obj, widget in self._library_widget_map.items()
            if widget is not list_widget
        }

    def _register_library_widget(self, widget: QWidget, list_widget: QListWidget) -> None:
        widget.setMouseTracking(True)
        widget.installEventFilter(self)
        self._library_widget_map[widget] = list_widget
        for child in widget.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)
            self._library_widget_map[child] = list_widget

    def _refresh_guaranteed_list(self) -> None:
        self._clear_library_widget_map(self._guaranteed_list)
        self._guaranteed_list.blockSignals(True)
        self._guaranteed_list.clear()
        for item in self._item_library:
            row, widget = self._build_library_row(
                item, item.item_id in self._guaranteed_ids
            )
            self._guaranteed_list.addItem(row)
            self._guaranteed_list.setItemWidget(row, widget)
            self._register_library_widget(widget, self._guaranteed_list)
        self._guaranteed_list.blockSignals(False)
        self._filter_guaranteed_list()
        self._update_library_status()
        self._update_library_grids()

    def _filter_guaranteed_list(self) -> None:
        query = self._guaranteed_search.text().strip().lower()
        for idx in range(self._guaranteed_list.count()):
            item = self._guaranteed_list.item(idx)
            title = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(bool(query) and query not in title)

    def _refresh_limited_pool_list(self) -> None:
        self._clear_library_widget_map(self._limited_list)
        self._limited_list.blockSignals(True)
        self._limited_list.clear()
        for item in self._item_library:
            row, widget = self._build_library_row(
                item, item.item_id in self._limited_pool_ids
            )
            self._limited_list.addItem(row)
            self._limited_list.setItemWidget(row, widget)
            self._register_library_widget(widget, self._limited_list)
        self._limited_list.blockSignals(False)
        self._filter_limited_pool_list()
        self._update_limited_status()
        self._update_library_grids()

    def _filter_limited_pool_list(self) -> None:
        query = self._limited_search.text().strip().lower()
        for idx in range(self._limited_list.count()):
            item = self._limited_list.item(idx)
            title = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            item.setHidden(bool(query) and query not in title)

    def _on_guaranteed_item_changed(self, item: QListWidgetItem) -> None:
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._guaranteed_ids.add(item_id)
        else:
            self._guaranteed_ids.discard(item_id)
        self._apply_guaranteed_to_results()
        self._update_preview()

    def _on_limited_pool_item_changed(self, item: QListWidgetItem) -> None:
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return
        if item.checkState() == Qt.CheckState.Checked:
            self._limited_pool_ids.add(item_id)
        else:
            self._limited_pool_ids.discard(item_id)
        self._update_limited_status()
        self._update_preview()

    def _apply_guaranteed_to_results(self) -> None:
        if not self._results:
            return
        guaranteed_ids = set(self._guaranteed_ids)
        updated: List[LootResultItem] = []
        present_ids: Set[str] = set()
        for result in self._results:
            if result.guaranteed and result.item.item_id not in guaranteed_ids:
                continue
            if result.item.item_id in guaranteed_ids:
                result.guaranteed = True
                result.locked = True
            updated.append(result)
            present_ids.add(result.item.item_id)

        for item_id in guaranteed_ids:
            if item_id in present_ids:
                continue
            item = self._item_by_id.get(item_id)
            if not item:
                continue
            updated.append(
                LootResultItem(
                    result_id=self._next_result_id,
                    item=item,
                    locked=True,
                    guaranteed=True,
                )
            )
            self._next_result_id += 1

        self._results = updated
        self._render_results()

    def _clear_guaranteed(self) -> None:
        self._guaranteed_ids.clear()
        self._refresh_guaranteed_list()
        self._apply_guaranteed_to_results()
        self._update_preview()

    def _clear_limited_pool(self) -> None:
        self._limited_pool_ids.clear()
        self._refresh_limited_pool_list()
        self._update_preview()

    def _update_library_status(self) -> None:
        self._library_status.setText(f"Library: {len(self._item_library)} items")

    def _update_limited_status(self) -> None:
        self._limited_status.setText(
            f"Limited Pool: {len(self._limited_pool_ids)} selected"
        )

    def _update_library_grids(self) -> None:
        for list_widget in (self._guaranteed_list, self._limited_list):
            if list_widget is None:
                continue
            viewport_width = list_widget.viewport().width()
            if viewport_width <= 0:
                viewport_width = 380  # Default fallback width
            spacing = list_widget.spacing()
            # Force 2 items per row by always dividing viewport width by 2
            item_width = (viewport_width - spacing * 3) // 2
            item_width = max(LIBRARY_ITEM_MIN_WIDTH, item_width)
            item_height = max(88, ICON_SIZE + 36)
            for idx in range(list_widget.count()):
                item = list_widget.item(idx)
                item.setSizeHint(QSize(item_width, item_height))
                widget = list_widget.itemWidget(item)
                if widget is not None:
                    widget.setFixedSize(item_width, item_height)
            list_widget.setGridSize(QSize(item_width, item_height))

    def eventFilter(self, obj, event) -> bool:
        guaranteed_viewport = (
            self._guaranteed_list.viewport()
            if hasattr(self, "_guaranteed_list")
            else None
        )
        limited_viewport = (
            self._limited_list.viewport() if hasattr(self, "_limited_list") else None
        )
        if obj in self._library_widget_map:
            list_widget = self._library_widget_map.get(obj)
            if list_widget is not None and event.type() in (
                QEvent.Type.MouseMove,
                QEvent.Type.Enter,
            ):
                if hasattr(event, "position"):
                    global_pos = obj.mapToGlobal(event.position().toPoint())
                else:
                    global_pos = QCursor.pos()
                pos = list_widget.viewport().mapFromGlobal(global_pos)
                item = list_widget.itemAt(pos)
                if item is not None:
                    self._on_library_item_hover(item)
                else:
                    self._hide_preview()
        if obj in (guaranteed_viewport, limited_viewport):
            if event.type() == QEvent.Type.MouseMove:
                list_widget = (
                    self._guaranteed_list
                    if obj is guaranteed_viewport
                    else self._limited_list
                )
                if list_widget is not None:
                    item = list_widget.itemAt(event.position().toPoint())
                    if item is not None:
                        self._on_library_item_hover(item)
                    else:
                        self._hide_preview()
            if event.type() == QEvent.Type.Resize:
                self._update_library_grids()
            if event.type() == QEvent.Type.Leave:
                self._hide_preview()
        return super().eventFilter(obj, event)

    def _on_library_item_hover(self, item: QListWidgetItem) -> None:
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return
        loot_item = self._item_by_id.get(item_id)
        if not loot_item:
            return
        sender = self.sender()
        anchor = sender if isinstance(sender, QListWidget) else self._guaranteed_list
        self._show_item_preview(loot_item, anchor)

    def _show_item_preview(self, item: LootItem, anchor: QWidget) -> None:
        global_pos = QCursor.pos()
        dpr = self._screen_dpr_for_global_pos(global_pos, anchor)
        pixmap = self._preview_pixmap_for_item(
            item,
            max_width=PREVIEW_TOOLTIP_WIDTH,
            max_height=None,
            dpr=dpr,
        )
        if pixmap is None:
            return
        self._preview_tooltip.show_preview(pixmap, global_pos)

    def _hide_preview(self) -> None:
        self._preview_tooltip.hide_preview()

    def _screen_dpr_for_global_pos(
        self, global_pos: QPoint, fallback_widget: Optional[QWidget] = None
    ) -> float:
        screen = QGuiApplication.screenAt(global_pos)
        if screen is None and fallback_widget is not None:
            window_handle = fallback_widget.window().windowHandle()
            if window_handle is not None:
                screen = window_handle.screen()
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 1.0
        return max(1.0, float(screen.devicePixelRatio()))

    def _preview_pixmap_for_item(
        self,
        item: LootItem,
        *,
        max_width: int = PREVIEW_TOOLTIP_WIDTH,
        max_height: Optional[int] = None,
        dpr: float = 1.0,
    ) -> Optional[QPixmap]:
        safe_width = max(1, int(round(max_width)))
        safe_height = max_height if max_height is None else max(1, int(round(max_height)))
        safe_dpr = max(1.0, float(dpr))
        cache_key = (
            item.item_id,
            safe_width,
            safe_height if safe_height is not None else 0,
            int(round(safe_dpr * 100.0)),
        )
        cached = self._preview_cache.get(cache_key)
        if cached is not None:
            return cached
        pixmap = self._render_item_preview(
            item,
            max_width=safe_width,
            max_height=safe_height,
            dpr=safe_dpr,
        )
        if pixmap is None:
            return None
        self._preview_cache[cache_key] = pixmap
        return pixmap

    def _render_item_preview(
        self,
        item: LootItem,
        *,
        max_width: int = PREVIEW_TOOLTIP_WIDTH,
        max_height: Optional[int] = None,
        dpr: float = 1.0,
    ) -> Optional[QPixmap]:
        if not (SPEC_AVAILABLE and RENDERER_AVAILABLE and item.path):
            return None
        try:
            data = load_item_payload(Path(item.path))
            if not isinstance(data, dict):
                return None
            spec = spec_from_dict(data)
            opts = RenderOptions(
                width=PREVIEW_WIDTH,
                scale=PREVIEW_SCALE,
                title_scale=PREVIEW_TITLE_SCALE,
                body_scale=PREVIEW_BODY_SCALE,
                label_scale=PREVIEW_LABEL_SCALE,
                icon_bg_curve=PREVIEW_ICON_CURVE,
                panel_inner_glow=False,
                outer_rarity_glow=False,
                outside_alpha=0,
            )
            rendered = render_item_card(spec, opts, downscale=False)
            image = _pil_to_qimage(rendered.image)
            pixmap = QPixmap.fromImage(image)
        except Exception:
            return None
        safe_dpr = max(1.0, float(dpr))
        target_width_px = max(1, int(round(max_width * safe_dpr)))
        if max_height is None:
            if pixmap.width() != target_width_px:
                pixmap = pixmap.scaledToWidth(
                    target_width_px,
                    Qt.TransformationMode.SmoothTransformation,
                )
        else:
            target_height_px = max(1, int(round(max_height * safe_dpr)))
            if pixmap.width() != target_width_px or pixmap.height() != target_height_px:
                pixmap = pixmap.scaled(
                    target_width_px,
                    target_height_px,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
        pixmap.setDevicePixelRatio(safe_dpr)
        return pixmap

    def _rebuild_category_filters(self, selected: Set[str]) -> None:
        if not hasattr(self, "_category_layout"):
            return
        while self._category_layout.count():
            child = self._category_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self._category_checks.clear()
        
        # Sort by predefined order to ensure consistent 2x3 grid
        predefined_order = ["equipment", "consumables", "valuables", "magic", "quest", "miscellaneous"]
        keys = predefined_order + [k for k in sorted(self._category_labels) if k not in predefined_order]
        
        for idx, key in enumerate(keys):
            if key not in self._category_labels:
                continue
            label = self._category_labels[key]
            cb = QCheckBox(label)
            cb_font = cb.font()
            cb_font.setPointSize(max(1, cb_font.pointSize() - 2))
            cb.setFont(cb_font)
            cb.setChecked(key in selected)
            cb.stateChanged.connect(self._on_settings_changed)
            self._category_checks[key] = cb
            
            row = idx // 3
            col = idx % 3
            self._category_layout.addWidget(cb, row, col)

    def _apply_filters(self, ignore_limited: bool = False) -> List[LootItem]:
        categories = {
            key for key, cb in self._category_checks.items() if cb.isChecked()
        }
        group_level = self._group_level_spin.value()
        max_level = min(LEVEL_CAP, group_level + LEVEL_RANGE)

        def matches(item: LootItem) -> bool:
            if item.level > max_level:
                return False
            if categories and not categories.issubset(item.categories):
                return False
            return True

        filtered = [item for item in self._item_library if matches(item)]
        if not ignore_limited and self._limited_pool_ids:
            return [item for item in filtered if item.item_id in self._limited_pool_ids]
        return filtered

    def _calculate_rolls(self) -> int:
        return self._rolls_spin.value()

    def _current_luck(self) -> float:
        return self._luck_slider.value() / LUCK_SLIDER_SCALE

    def _calculate_weights(self) -> Dict[str, float]:
        if self._custom_weights_enabled:
            weights = self._custom_weights()
            return self._normalize_weights(weights)

        core_weights = self._base_weights_from_luck()
        core_total = sum(core_weights.values()) or 1.0
        artifact_weight = core_total * (ARTIFACT_DEFAULT_PROB / (100.0 - ARTIFACT_DEFAULT_PROB))
        core_weights["artifact"] = artifact_weight
        return self._normalize_weights(core_weights)

    def _base_weights_from_luck(self) -> Dict[str, float]:
        luck = self._current_luck()
        luck_norm = (luck - LUCK_MIN) / (LUCK_MAX - LUCK_MIN)
        curve = self._curve_combo.currentText()
        if curve == "Linear (Steep)":
            return self._linear_weights(luck_norm, steep=True)
        if curve == "Quadratic":
            return self._quadratic_weights(luck_norm, steep=False)
        if curve == "Quadratic (Steep)":
            return self._quadratic_weights(luck_norm, steep=True)
        if curve == "Exponential":
            return self._exponential_weights(luck_norm)
        if curve == "Poisson":
            return self._poisson_weights(luck_norm)
        if curve == "Bell Curve":
            return self._bell_curve_weights(luck_norm, sigma=0.25)
        if curve == "Bell Curve (Narrow)":
            return self._bell_curve_weights(luck_norm, sigma=0.15)
        if curve == "Bell Curve (Wide)":
            return self._bell_curve_weights(luck_norm, sigma=0.45)
        if curve == "Flat":
            return self._flat_weights()
        if curve == "Inverted":
            return self._inverted_weights(luck_norm)
        return self._linear_weights(luck_norm, steep=False)

    def _linear_weights(self, luck_norm: float, steep: bool = False) -> Dict[str, float]:
        common_weight = 1.0
        if steep:
            artifact_weight = 0.01 + 0.9 * luck_norm
        else:
            artifact_weight = 0.08 + 0.6 * luck_norm
        weights: Dict[str, float] = {}
        core = _core_rarities()
        tier_count = len(core) - 1
        for idx, rarity in enumerate(core):
            t = idx / tier_count if tier_count else 0.0
            weight = common_weight + (artifact_weight - common_weight) * t
            weights[rarity] = weight
        return weights

    def _quadratic_weights(self, luck_norm: float, steep: bool = False) -> Dict[str, float]:
        common_weight = 1.0
        if steep:
            artifact_weight = 0.01 + 0.9 * luck_norm
            power = 4
        else:
            artifact_weight = 0.1 + 0.55 * luck_norm
            power = 2
        weights: Dict[str, float] = {}
        core = _core_rarities()
        tier_count = len(core) - 1
        for idx, rarity in enumerate(core):
            t = idx / tier_count if tier_count else 0.0
            weight = artifact_weight + (common_weight - artifact_weight) * ((1 - t) ** power)
            weights[rarity] = weight
        return weights

    def _exponential_weights(self, luck_norm: float) -> Dict[str, float]:
        target = 0.05 + 0.95 * luck_norm
        weights: Dict[str, float] = {}
        core = _core_rarities()
        tier_count = len(core) - 1
        for idx, rarity in enumerate(core):
            t = idx / tier_count if tier_count else 0.0
            weight = target ** t
            weights[rarity] = weight
        return weights

    def _bell_curve_weights(self, luck_norm: float, sigma: float = 0.25) -> Dict[str, float]:
        peak_t = luck_norm
        weights: Dict[str, float] = {}
        core = _core_rarities()
        tier_count = len(core) - 1
        for idx, rarity in enumerate(core):
            t = idx / tier_count if tier_count else 0.0
            val = math.exp(-0.5 * ((t - peak_t) / sigma) ** 2)
            weights[rarity] = val
        return weights

    def _flat_weights(self) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        core = _core_rarities()
        for rarity in core:
            weights[rarity] = 1.0
        return weights

    def _inverted_weights(self, luck_norm: float) -> Dict[str, float]:
        legendary_weight = 1.0
        common_weight = 0.05 + 0.5 * (1.0 - luck_norm)
        weights: Dict[str, float] = {}
        core = _core_rarities()
        tier_count = len(core) - 1
        for idx, rarity in enumerate(core):
            t = idx / tier_count if tier_count else 0.0
            weight = common_weight + (legendary_weight - common_weight) * t
            weights[rarity] = weight
        return weights

    def _poisson_weights(self, luck_norm: float) -> Dict[str, float]:
        core = _core_rarities()
        lam = max(0.1, luck_norm * (len(core) - 1))
        weights: Dict[str, float] = {}
        for idx, rarity in enumerate(core):
            weight = math.exp(-lam) * (lam**idx) / math.factorial(idx)
            weights[rarity] = weight
        return weights

    def _custom_weights(self) -> Dict[str, float]:
        weights: Dict[str, float] = {}
        for rarity, slider in self._weight_sliders.items():
            weights[rarity] = float(slider.value())
        if sum(weights.values()) <= 0.0:
            return self._base_weights_from_luck()
        return weights

    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        total = sum(weights.values()) or 1.0
        return {key: (value / total) * 100.0 for key, value in weights.items()}

    def _update_preview(self) -> None:
        self._base_filtered_pool = self._apply_filters(ignore_limited=True)
        self._filtered_pool = self._apply_filters()
        if not self._custom_weights_enabled:
            self._sync_weight_sliders(self._calculate_weights())
        self._update_table()
        self._weights_reset_btn.setEnabled(self._custom_weights_enabled)
        self._refresh_weight_labels(self._calculate_weights())
        self._generate_button.setEnabled(
            bool(self._filtered_pool or self._guaranteed_ids)
        )
        self._reroll_all_btn.setEnabled(
            bool(self._filtered_pool or self._guaranteed_ids)
        )
        self._reroll_unlocked_btn.setEnabled(
            bool(self._filtered_pool or self._guaranteed_ids)
        )
        if not self._results:
            self._render_results()

    def _update_table(self) -> None:
        pool_counts = {
            rarity: 0 for rarity in RARITY_ORDER
        }
        for item in self._filtered_pool:
            pool_counts[item.rarity] = pool_counts.get(item.rarity, 0) + 1

        rolls = self._calculate_rolls()
        weights = self._calculate_weights()
        effective_weights = self._get_effective_weights(weights, pool_counts)

        self._rolls_label.setText(f"Rolls: {rolls}")
        self._pool_label.setText(f"Pool: {len(self._filtered_pool)} items")

        for rarity in RARITY_ORDER:
            pool_count = pool_counts.get(rarity, 0)
            pool_label = self._pool_value_labels.get(rarity)
            if pool_label:
                pool_label.setText(str(pool_count))

            prob_label = self._prob_value_labels.get(rarity)
            if prob_label:
                if pool_count > 0:
                    p = effective_weights.get(rarity, 0.0) / 100.0
                    prob = 1.0 - (1.0 - p) ** rolls
                    prob_label.setText(f"{prob * 100.0:.1f}%")
                else:
                    prob_label.setText("0.0%")

    def _get_effective_weights(self, base_weights: Dict[str, float], pool_counts: Dict[str, int]) -> Dict[str, float]:
        """
        Calculates effective weights by filtering for available rarities and re-normalizing.
        This ensures that if a rarity is missing, its probability mass is distributed
        proportionally among the available rarities, preserving relative ratios.
        """
        available_weights = {}
        total_weight = 0.0
        for rarity, count in pool_counts.items():
            if count > 0:
                weight = base_weights.get(rarity, 0.0)
                available_weights[rarity] = weight
                total_weight += weight
        
        if total_weight <= 0.0:
            return {r: 0.0 for r in RARITY_ORDER}
            
        return {
            r: (available_weights.get(r, 0.0) / total_weight) * 100.0
            for r in RARITY_ORDER
        }

    def _shift_note(self) -> str:
        if self._custom_weights_enabled:
            return "Custom rarity weights active. Reset to Luck to return to the Luck curve."
        luck = self._current_luck()
        curve = self._curve_combo.currentText()
        
        if curve == "Flat":
            return "Flat distribution ignores Luck."
            
        if "Bell Curve" in curve:
            if "Narrow" in curve:
                spread = "High precision:"
            elif "Wide" in curve:
                spread = "Wide spread:"
            else:
                spread = "Balanced spread:"
                
            if luck >= 80:
                return f"{spread} Luck focuses strongly on Epic/Legendary."
            if luck <= 20:
                return f"{spread} Luck focuses strongly on Common."
            return f"{spread} Luck sets the rarity peak."

        if curve == "Poisson":
            if luck >= 80:
                return "Luck pushes the peak toward Epic/Legendary."
            if luck <= 20:
                return "Luck keeps the peak near Common."
            return "Luck sets the rarity peak."

        if curve == "Inverted":
            if luck >= 60:
                return "Luck further reduces Common items."
            if luck <= 40:
                return "Lower Luck makes Common items more frequent."
            return "High rarities are favored; Luck adjusts the slope."

        # Monotonic curves (Linear, Quadratic, Exponential)
        if "Steep" in curve:
             if luck >= 75:
                 return "High luck drastically favors higher rarities."
             if luck <= 25:
                 return "Low luck makes higher rarities extremely rare."
        
        if luck >= 75:
            return "High luck favors Epic and Artifact items."
        if luck <= 25:
            return "Low luck favors Common and Uncommon items."
        if luck >= 60:
            return "Luck nudges the table toward higher rarities."
        if luck <= 40:
            return "Luck nudges the table toward lower rarities."
        return "Balanced rarity mix based on Luck."

    def _example_outcome(self, weights: Dict[str, float], rolls: int) -> str:
        if rolls <= 0:
            return ""
        rng = random.Random()
        counts = {rarity: 0 for rarity in RARITY_ORDER}
        for _ in range(rolls):
            rarity = self._weighted_choice(weights, rng)
            counts[rarity] += 1
        parts = []
        for rarity in RARITY_ORDER:
            if counts[rarity]:
                label = _rarity_label(rarity)
                parts.append(f"{counts[rarity]} {label}")
        return ", ".join(parts)

    def _weighted_choice(self, weights: Dict[str, float], rng: random.Random) -> str:
        total = sum(weights.values())
        if total <= 0.0:
             return RARITY_ORDER[0] # Default fallback
        roll = rng.random() * total
        current = 0.0
        for rarity in RARITY_ORDER:
            current += weights.get(rarity, 0.0)
            if roll <= current:
                return rarity
        return RARITY_ORDER[-1]

    def _generate_loot(self, preserve_locked: bool) -> None:

        pool = self._filtered_pool
        guaranteed_items = [
            self._item_by_id[item_id]
            for item_id in self._guaranteed_ids
            if item_id in self._item_by_id
        ]
        if not pool and not guaranteed_items:
            self._results = []
            self._render_results()
            QMessageBox.warning(
                self,
                "Loot Generation",
                self._empty_state_message(),
            )
            return

        if preserve_locked and self._results:
            unlocked_exists = any(
                not result.locked and not result.guaranteed for result in self._results
            )
            if not unlocked_exists:
                QMessageBox.information(
                    self,
                    "Re-roll Unavailable",
                    "All items are locked. Unlock at least one item to re-roll.",
                )
                return

        self._flash_generate_button()
        base_weights = self._calculate_weights()
        rolls = self._calculate_rolls()
        rng = self._rng
        
        pool_by_rarity = {rarity: [] for rarity in RARITY_ORDER}
        pool_counts = {rarity: 0 for rarity in RARITY_ORDER}
        for item in pool:
            pool_by_rarity.setdefault(item.rarity, []).append(item)
            pool_counts[item.rarity] += 1
            
        weights = self._get_effective_weights(base_weights, pool_counts)

        results: List[LootResultItem] = []
        used_ids: Set[str] = set()

        for item in sorted(guaranteed_items, key=lambda entry: entry.title.lower()):
            results.append(
                LootResultItem(
                    result_id=self._next_result_id,
                    item=item,
                    locked=True,
                    guaranteed=True,
                )
            )
            self._next_result_id += 1
            used_ids.add(item.item_id)

        locked_results: List[LootResultItem] = []
        if preserve_locked:
            for result in self._results:
                if result.locked and not result.guaranteed:
                    locked_results.append(result)
            for result in locked_results:
                results.append(result)
                used_ids.add(result.item.item_id)

        slots = max(0, rolls - len(locked_results))
        for _ in range(slots):
            # Recalculate weights if we are exhausting pools?
            # For simplicity/performance, assume relative weights hold unless pool exhausted.
            # If pool exhaustion is common, we should check availability.
            
            rarity = self._weighted_choice(weights, rng)
            item = self._pick_item(rarity, pool_by_rarity, pool, used_ids, rng)
            
            # If pick_item failed (exhausted or empty), try again with adjusted weights?
            # _pick_item handles empty/exhausted by returning None or (previously) fallback.
            # With fallback removed, we need to handle exhaustion.
            # If item is None, it means the chosen rarity is fully used.
            # We should temporarily set its weight to 0 and re-roll rarity.
            
            attempts = 0
            while item is None and attempts < 10:
                # Temporarily mask this rarity
                temp_weights = dict(weights)
                temp_weights[rarity] = 0.0
                # Re-normalize? _weighted_choice handles unnormalized sum.
                # Just loop to pick another rarity.
                
                # If all exhausted, break
                if sum(temp_weights.values()) <= 0.0:
                    break
                    
                rarity = self._weighted_choice(temp_weights, rng)
                item = self._pick_item(rarity, pool_by_rarity, pool, used_ids, rng)
                attempts += 1
                
                # Persist the zeroing for this slot?
                # Actually, if it's exhausted, we should update 'weights' for subsequent slots too.
                if item is None:
                     weights[rarity] = 0.0

            if not item:
                break
            results.append(
                LootResultItem(result_id=self._next_result_id, item=item)
            )
            self._next_result_id += 1
            used_ids.add(item.item_id)

        self._results = results
        self._render_results()

    def _pick_item(
        self,
        rarity: str,
        pool_by_rarity: Dict[str, List[LootItem]],
        pool: List[LootItem],
        used_ids: Set[str],
        rng: random.Random,
    ) -> Optional[LootItem]:
        candidates = pool_by_rarity.get(rarity) or []
        if not candidates:
            return None
        available = [item for item in candidates if item.item_id not in used_ids]
        if not available:
            available = candidates
        return self._weighted_item_choice(available, rng)



    def _weighted_item_choice(
        self,
        items: List[LootItem],
        rng: random.Random,
    ) -> Optional[LootItem]:
        if not items:
            return None
        group_level = self._group_level_spin.value()
        weights = []
        for item in items:
            diff = abs(item.level - group_level)
            weight = 1.0 / ((1.0 + diff) ** 2)
            weights.append(weight)
        total = sum(weights)
        if total <= 0.0:
            return rng.choice(items)
        roll = rng.random() * total
        current = 0.0
        for item, weight in zip(items, weights):
            current += weight
            if roll <= current:
                return item
        return items[-1]

    def _load_icon_pixmap(self, item: LootItem) -> Optional[QPixmap]:
        return self._build_library_icon(item, RESULT_ICON_SIZE)

    def _empty_state_message(self) -> str:
        if self._filtered_pool or self._guaranteed_ids:
            return "No loot generated yet."
        lines = ["No items can be generated."]
        reasons = []
        if not self._item_library:
            reasons.append("Total pool is 0 (item library empty).")
        else:
            if not self._base_filtered_pool:
                reasons.append("Filters/pool restrictions eliminate all items.")
            if self._limited_pool_ids and self._base_filtered_pool and not self._filtered_pool:
                reasons.append("Limited Pool selection yields no eligible items.")
        if reasons:
            lines.extend(f"- {reason}" for reason in reasons)
        lines.append(
            "- Check pool size, category filters, Limited Pool selections, and roll amount."
        )
        return "\n".join(lines)

    def _render_results(self) -> None:
        while self._results_layout.count():
            child = self._results_layout.takeAt(0)
            widget = child.widget()
            if widget:
                widget.deleteLater()

        if not self._results:
            empty = QLabel("No loot generated.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #71717a; padding: 20px;")
            self._results_layout.addWidget(empty)
            return

        header = QLabel(f"Generated {len(self._results)} items")
        header.setObjectName("Subheader")
        self._results_layout.addWidget(header)

        for result in self._results:
            row = LootResultRow(
                result,
                self._build_library_icon(result.item, size=RESULT_ICON_SIZE),
                on_lock=self._toggle_lock,
                on_reroll=self._reroll_result,
                on_remove=self._remove_result,
                on_hover=self._show_item_preview,
                on_leave=self._hide_preview,
                parent=self._results_container,
            )
            self._results_layout.addWidget(row)

        self._results_layout.addStretch(1)

    def _toggle_lock(self, result_id: int) -> None:
        for result in self._results:
            if result.result_id == result_id:
                if result.guaranteed:
                    return
                result.locked = not result.locked
                break
        self._render_results()

    def _reroll_single(self, result_id: int) -> None:
        base_weights = self._calculate_weights()
        pool = self._filtered_pool
        if not pool:
            return
        pool_by_rarity = {rarity: [] for rarity in RARITY_ORDER}
        pool_counts = {rarity: 0 for rarity in RARITY_ORDER}
        for item in pool:
            pool_by_rarity.setdefault(item.rarity, []).append(item)
            pool_counts[item.rarity] += 1
            
        weights = self._get_effective_weights(base_weights, pool_counts)

        used_ids = {result.item.item_id for result in self._results}
        for result in self._results:
            if result.result_id != result_id:
                continue
            if result.locked or result.guaranteed:
                return
            used_ids.discard(result.item.item_id)
            
            # Use same exhaustion logic as _generate_loot
            item = None
            attempts = 0
            current_weights = dict(weights)
            
            while item is None and attempts < 10:
                if sum(current_weights.values()) <= 0.0:
                    break
                rarity = self._weighted_choice(current_weights, self._rng)
                item = self._pick_item(rarity, pool_by_rarity, pool, used_ids, self._rng)
                attempts += 1
                if item is None:
                    current_weights[rarity] = 0.0

            if item:
                result.item = item
            break
        self._render_results()

    def _reroll_result(self, result_id: int) -> None:
        self._reroll_single(result_id)

    def _remove_result(self, result_id: int) -> None:
        self._results = [r for r in self._results if r.result_id != result_id]
        self._render_results()

    def _results_payload(self) -> dict:
        rows: list[dict] = []
        for result in self._results:
            rows.append(
                {
                    "item_id": result.item.item_id,
                    "path": result.item.path,
                    "title": result.item.title,
                    "locked": bool(result.locked),
                    "guaranteed": bool(result.guaranteed),
                }
            )
        return {
            "version": 1,
            "created_at": _utc_timestamp(),
            "results": rows,
        }

    def _save_generated_results(self) -> None:
        if not self._results:
            QMessageBox.information(self, "Save Results", "No generated loot to save.")
            return
        self._results_dir.mkdir(parents=True, exist_ok=True)
        default_path = self._results_dir / f"generated_results{LOOT_RESULTS_EXTENSION}"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Generated Loot Results",
            str(default_path),
            f"DMT Loot Results (*{LOOT_RESULTS_EXTENSION})",
        )
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != LOOT_RESULTS_EXTENSION:
            path = path.with_suffix(LOOT_RESULTS_EXTENSION)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._results_payload(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return
        QMessageBox.information(self, "Save Results", f"Saved {path.name}.")

    def _load_generated_results(self) -> None:
        self._results_dir.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Generated Loot Results",
            str(self._results_dir),
            f"DMT Loot Results (*{LOOT_RESULTS_EXTENSION})",
        )
        if not filename:
            return
        try:
            payload = json.loads(Path(filename).read_text(encoding="utf-8"))
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))
            return
        if not isinstance(payload, dict):
            QMessageBox.warning(self, "Load Results", "Invalid results file.")
            return
        self._load_item_library()
        rows = payload.get("results")
        if not isinstance(rows, list):
            QMessageBox.warning(self, "Load Results", "Results file is missing rows.")
            return
        loaded: list[LootResultItem] = []
        skipped_titles: list[str] = []
        next_result_id = 1
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            item = None
            item_id = str(raw.get("item_id") or "").strip()
            if item_id:
                item = self._item_by_id.get(item_id)
            if item is None:
                item = self._match_item(raw.get("path"), raw.get("title"))
            if item is None:
                title = str(raw.get("title") or item_id or "Unknown")
                skipped_titles.append(title)
                continue
            loaded.append(
                LootResultItem(
                    result_id=next_result_id,
                    item=item,
                    locked=bool(raw.get("locked", False)),
                    guaranteed=bool(raw.get("guaranteed", False)),
                )
            )
            next_result_id += 1
        self._results = loaded
        self._next_result_id = max(1, next_result_id)
        self._render_results()
        if skipped_titles:
            QMessageBox.warning(
                self,
                "Load Results",
                f"Loaded {len(loaded)} result(s). Skipped {len(skipped_titles)} missing item(s).",
            )
            return
        QMessageBox.information(self, "Load Results", f"Loaded {len(loaded)} result(s).")

    def _export_loot_pdf(self) -> None:
        if not (RENDERER_AVAILABLE and SPEC_AVAILABLE):
            QMessageBox.warning(
                self,
                "Renderer Unavailable",
                "Cannot export loot without the item renderer.",
            )
            return
        if not self._results:
            QMessageBox.information(
                self, "Export Loot", "No generated loot to export."
            )
            return

        export_dir = Path(default_dnd_save_dir()) / "loot" / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        default_path = export_dir / "loot_export.pdf"

        while True:
            pdf_path, _ = QFileDialog.getSaveFileName(
                self, "Export Loot PDF", str(default_path), "PDF (*.pdf)"
            )
            if not pdf_path:
                return
            if not pdf_path.lower().endswith(".pdf"):
                pdf_path += ".pdf"
            if os.path.exists(pdf_path):
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Icon.Warning)
                dialog.setWindowTitle("File Exists")
                dialog.setText("A PDF with this name already exists.")
                dialog.setInformativeText("Rename the file or overwrite the existing PDF.")
                rename_btn = dialog.addButton(
                    "Rename", QMessageBox.ButtonRole.ActionRole
                )
                overwrite_btn = dialog.addButton(
                    "Overwrite", QMessageBox.ButtonRole.DestructiveRole
                )
                dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
                dialog.exec()
                if dialog.clickedButton() == rename_btn:
                    default_path = Path(pdf_path)
                    continue
                if dialog.clickedButton() != overwrite_btn:
                    return
            break

        try:
            from PIL import Image
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        render_opts = RenderOptions(
            width=EXPORT_WIDTH,
            scale=EXPORT_SCALE,
            title_scale=PREVIEW_TITLE_SCALE,
            body_scale=PREVIEW_BODY_SCALE,
            label_scale=PREVIEW_LABEL_SCALE,
            icon_bg_curve=PREVIEW_ICON_CURVE,
        )

        images = []
        skipped = []
        for result in self._results:
            item = result.item
            if not item.path or not os.path.exists(item.path):
                skipped.append(item.title)
                continue
            try:
                data = load_item_payload(Path(item.path))
                if not isinstance(data, dict):
                    raise ValueError("invalid item file")
                spec = spec_from_dict(data)
                rendered = render_item_card(spec, render_opts, downscale=False)
                images.append(rendered.image.convert("RGB"))
            except Exception:
                skipped.append(item.title)

        if not images:
            QMessageBox.warning(
                self,
                "Export Loot",
                "No items could be rendered for export. Check the item files.",
            )
            return

        try:
            pages = []
            for idx in range(0, len(images), 2):
                left = images[idx]
                right = images[idx + 1] if idx + 1 < len(images) else None
                page_width = left.width * 2
                page_height = left.height
                page = Image.new("RGB", (page_width, page_height), "white")
                page.paste(left, (0, 0))
                if right:
                    if right.size != left.size:
                        right = right.resize(left.size)
                    page.paste(right, (left.width, 0))
                pages.append(page)
            pages[0].save(
                pdf_path,
                "PDF",
                resolution=EXPORT_DPI,
                save_all=True,
                append_images=pages[1:],
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", str(exc))
            return

        if skipped:
            QMessageBox.warning(
                self,
                "Export Loot",
                f"Exported {len(images)} items. Skipped {len(skipped)} item(s).",
            )
            return
        QMessageBox.information(
            self,
            "Export Loot",
            f"Exported {len(images)} items to {Path(pdf_path).name}.",
        )

    def _flash_generate_button(self) -> None:
        self._generate_button.setText(self._generate_button_default_text)

    def _load_presets(self) -> None:
        self._preset_entries = []
        for preset in BUILTIN_PRESETS:
            self._preset_entries.append(
                PresetEntry(name=preset["name"], data=preset, built_in=True)
            )

        for path in sorted(self._preset_dir.glob(f"*{LOOT_PRESET_EXTENSION}")):
            try:
                info = read_dmt_package_info(path)
            except Exception:
                continue
            if not isinstance(info, dict):
                continue
            if str(info.get("format") or "") != LOOT_PRESET_FORMAT:
                continue
            data = info.get("payload")
            if not isinstance(data, dict):
                continue
            name = str(info.get("name") or data.get("name") or path.stem)
            self._preset_entries.append(
                PresetEntry(name=name, data=data, path=path, built_in=False)
            )

        self._refresh_preset_list()
        self._select_custom_preset()

    def _refresh_preset_list(self) -> None:
        if not hasattr(self, "_preset_list"):
            return
        self._preset_list.blockSignals(True)
        self._preset_list.clear()
        for entry in self._preset_entries:
            row = QListWidgetItem("")
            row.setData(Qt.ItemDataRole.UserRole, entry)
            widget = PresetRow(entry, self._delete_preset_entry)
            row.setSizeHint(QSize(0, 42))
            self._preset_list.addItem(row)
            self._preset_list.setItemWidget(row, widget)
            widget.show()  # Show after parent is set to prevent window flash
        self._preset_list.blockSignals(False)

    def _on_preset_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(entry, PresetEntry):
            return
        self._apply_preset(entry.data)

    def _apply_preset(self, data: Dict[str, object]) -> None:
        self._loading_preset = True
        try:
            group_level = int(data.get("group_level", self._group_level_spin.value()))
            self._group_level_spin.setValue(max(1, min(LEVEL_CAP, group_level)))
            rolls = int(data.get("rolls", self._rolls_spin.value()))
            self._rolls_spin.setValue(max(1, min(ROLLS_MAX, rolls)))
            luck_raw = data.get("luck", self._current_luck())
            luck = self._coerce_luck_value(luck_raw)
            self._luck_slider.setValue(int(round(luck * LUCK_SLIDER_SCALE)))
            curve = str(data.get("rarity_curve", self._curve_combo.currentText()))
            if curve in RARITY_CURVES:
                self._curve_combo.setCurrentText(curve)

            tags = data.get("tags", [])
            if isinstance(tags, list):
                self._tags_edit.setText(", ".join(str(tag) for tag in tags if tag))
            else:
                self._tags_edit.setText(str(tags))

            categories = set(data.get("categories", []) or [])
            for key, cb in self._category_checks.items():
                cb.setChecked(key in categories)

            weights_mode = data.get("weights_mode", "luck")
            weights = data.get("weights", {})
            if weights_mode == "custom" and isinstance(weights, dict):
                self._custom_weights_enabled = True
                scaled_weights = {
                    rarity: float(weights.get(rarity, 0.0)) for rarity in RARITY_ORDER
                }
                self._sync_weight_sliders(scaled_weights)
            else:
                self._custom_weights_enabled = False
                self._sync_weight_sliders(self._base_weights_from_luck())

            self._guaranteed_ids.clear()
            guaranteed = data.get("guaranteed", []) or []
            for entry in guaranteed:
                if isinstance(entry, dict):
                    path = entry.get("path")
                    title = entry.get("title")
                    matched = self._match_item(path, title)
                else:
                    matched = self._match_item(None, str(entry))
                if matched:
                    self._guaranteed_ids.add(matched.item_id)

            self._refresh_guaranteed_list()
            self._apply_guaranteed_to_results()

            self._limited_pool_ids.clear()
            limited_pool = data.get("limited_pool", []) or []
            for entry in limited_pool:
                if isinstance(entry, dict):
                    path = entry.get("path")
                    title = entry.get("title")
                    matched = self._match_item(path, title)
                else:
                    matched = self._match_item(None, str(entry))
                if matched:
                    self._limited_pool_ids.add(matched.item_id)
            self._refresh_limited_pool_list()
        finally:
            self._loading_preset = False
            self._update_preview()

    def _match_item(self, path: Optional[str], title: Optional[str]) -> Optional[LootItem]:
        if path:
            for item in self._item_library:
                if item.path and os.path.normpath(item.path) == os.path.normpath(path):
                    return item
        if title:
            title_lower = str(title).strip().lower()
            for item in self._item_library:
                if item.title.lower() == title_lower:
                    return item
        return None

    def _current_settings(self) -> Dict[str, object]:
        tags = _parse_tag_list(self._tags_edit.text())
        categories = [
            key for key, cb in self._category_checks.items() if cb.isChecked()
        ]
        guaranteed = []
        for item_id in sorted(self._guaranteed_ids):
            item = self._item_by_id.get(item_id)
            if item:
                guaranteed.append({"title": item.title, "path": item.path})
        limited_pool = []
        for item_id in sorted(self._limited_pool_ids):
            item = self._item_by_id.get(item_id)
            if item:
                limited_pool.append({"title": item.title, "path": item.path})
        return {
            "group_level": self._group_level_spin.value(),
            "rolls": self._rolls_spin.value(),
            "luck": self._current_luck(),
            "rarity_curve": self._curve_combo.currentText(),
            "tags": sorted(tags),
            "categories": categories,
            "weights_mode": "custom" if self._custom_weights_enabled else "luck",
            "weights": {rarity: slider.value() / SLIDER_SCALE for rarity, slider in self._weight_sliders.items()},
            "guaranteed": guaranteed,
            "limited_pool": limited_pool,
        }

    def _save_preset(self) -> None:
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        cleaned_name = name.strip()
        filename = f"{_slugify(cleaned_name)}{LOOT_PRESET_EXTENSION}"
        path = self._preset_dir / filename

        if path.exists():
            response = QMessageBox.question(
                self,
                "Overwrite Preset",
                f"A preset named '{cleaned_name}' already exists. Overwrite it?",
            )
            if response != QMessageBox.StandardButton.Yes:
                return

        data = self._current_settings()
        data["name"] = cleaned_name
        try:
            existing_info = read_dmt_package_info(path) if path.exists() else None
            object_id = (
                str(existing_info.get("object_id") or "").strip()
                if isinstance(existing_info, dict)
                else ""
            ) or generate_probabilistic_unique_id("loot_preset")
            write_dmt_package(
                path,
                info={
                    "format": LOOT_PRESET_FORMAT,
                    "object_type": "loot_preset",
                    "object_id": object_id,
                    "name": cleaned_name,
                    "updated_at": _utc_timestamp(),
                    "payload": data,
                },
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))
            return

        self._load_presets()
        if hasattr(self, "_preset_list"):
            for idx in range(self._preset_list.count()):
                item = self._preset_list.item(idx)
                entry = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(entry, PresetEntry) and entry.name == cleaned_name:
                    self._preset_list.setCurrentItem(item)
                    break

    def _delete_preset_entry(self, entry: PresetEntry) -> None:
        if entry.built_in:
            QMessageBox.information(
                self, "Preset Locked", "Built-in presets cannot be deleted."
            )
            return
        if not entry.path or not entry.path.exists():
            return
        response = QMessageBox.question(
            self,
            "Delete Preset",
            f"Delete preset '{entry.name}'?",
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        try:
            entry.path.unlink()
        except Exception as exc:
            QMessageBox.critical(self, "Delete Failed", str(exc))
            return
        self._load_presets()
