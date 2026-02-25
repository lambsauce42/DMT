from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from typing import Iterable, List, Optional
import logging

from save_paths import default_dnd_save_dir, items_dir
from item_file_format import list_item_file_paths, load_item_payload
from character_archive import (
    ARCHIVE_EXTENSION,
    extract_character_pdf,
    normalize_inventory_payload,
    read_character_inventory,
    read_character_meta,
    write_character_archive,
)

from PySide6.QtCore import (
    Qt,
    QUrl,
    QItemSelectionModel,
    QTimer,
    QSize,
    QEvent,
    QRect,
    QEasingCurve,
    QPropertyAnimation,
    QPoint,
    QMimeData,
    QObject,
    Signal,
)
from PySide6.QtGui import (
    QDesktopServices,
    QKeySequence,
    QShortcut,
    QIcon,
    QGuiApplication,
    QImage,
    QPainter,
    QColor,
    QPixmap,
    QRadialGradient,
    QPen,
    QFont,
    QFontMetrics,
    QDrag,
    QCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsBlurEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTextEdit,
    QListView,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSpinBox,
    QStyle,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
)

from navigate_widget import load_navigation_data, move_to_trash
from loot_applet import (
    LootItem,
    LootPreviewTooltip,
    PREVIEW_WIDTH,
    PREVIEW_SCALE,
    PREVIEW_TITLE_SCALE,
    PREVIEW_BODY_SCALE,
    PREVIEW_LABEL_SCALE,
    PREVIEW_ICON_CURVE,
    PREVIEW_TOOLTIP_WIDTH,
    LEVEL_CAP,
    CATEGORY_LABELS,
    RARITY_COLORS as LOOT_RARITY_COLORS,
    _normalize_rarity,
    _normalize_tags,
    _normalize_categories,
    _category_label_from_categories,
    _resolve_icon_path,
)

logger = logging.getLogger(__name__)

ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
RESET_ICON = os.path.join(ICON_DIR, "reset.svg")
EQUIPMENT_BACKGROUNDS_DIR = Path(__file__).resolve().parent.parent / "assets" / "equipment backgrounds"
EQUIPMENT_DEFAULT_BACKGROUND_NAME = "ring_simple.png"
EQUIPMENT_SILHOUETTE_CANDIDATES: tuple[Path, ...] = (
    EQUIPMENT_BACKGROUNDS_DIR / "siluhette.png",
    EQUIPMENT_BACKGROUNDS_DIR / "silhouette.png",
    Path(ICON_DIR) / "equipment_dummy.svg",
)
EQUIPMENT_SLOT_BACKGROUND_CANDIDATES: dict[str, tuple[str, ...]] = {
    "head": ("helmet.png", "helmet_knight.png", "helmet_simple.png"),
    "necklace": ("necklace.png", "miscellaneous_necklace.png"),
    "chest": ("chest.png",),
    "back": ("cloak_white.png",),
    "pants": ("plate_leggings.png",),
    "shoulder_pads": ("shoulderpads.png",),
    "gloves": ("gauntlets_crossed.png",),
    "bracer": ("bracer.png", "bracers.png", "vambrace.png", "gauntlets_crossed.png"),
    "belt": ("belt.png",),
    "ring_left": ("ring_simple.png",),
    "ring_right": ("ring_simple.png",),
    "shoes": ("plate_boots.png",),
    "weapon_1": ("sword_short.png",),
    "weapon_2": ("sword_short.png",),
    "weapon_3": ("sword_short.png",),
    "weapon_4": ("shield.png", "sword_short.png"),
    "misc_1": ("trinket.png", "../icons/misc_hexagon.svg"),
    "misc_2": ("trinket.png", "../icons/misc_hexagon.svg"),
    "misc_4": ("../icons/misc_hexagon.svg",),
    "misc_5": ("../icons/misc_hexagon.svg",),
    "misc_6": ("../icons/misc_hexagon.svg",),
    "misc_7": ("../icons/misc_hexagon.svg",),
    "misc_8": ("../icons/misc_hexagon.svg",),
    "misc_9": ("../icons/misc_hexagon.svg",),
    "misc_10": ("../icons/misc_hexagon.svg",),
    "misc_11": ("../icons/misc_hexagon.svg",),
    "misc_12": ("../icons/misc_hexagon.svg",),
    "misc_13": ("../icons/misc_hexagon.svg",),
}

PDFIUM_VIEW_ERROR: Optional[Exception] = None
try:
    from ui.character_sheet_panel import CharacterSheetPanel

    PDFIUM_VIEW_AVAILABLE = True
except Exception as exc:  # pragma: no cover - optional PDFium support
    PDFIUM_VIEW_AVAILABLE = False
    PDFIUM_VIEW_ERROR = exc

SPEC_AVAILABLE = False
RENDERER_AVAILABLE = False
try:
    from item_renderer import (
        RenderOptions,
        render_item_card,
        spec_from_dict,
        _icon_gradient_bg,
        _icon_cover_resize,
        _icon_contain_resize,
        _trim_black_bbox,
        RARITY_COLORS as RENDER_RARITY_COLORS,
    )
    from PIL import Image, ImageDraw

    SPEC_AVAILABLE = True
    RENDERER_AVAILABLE = True
except Exception:  # pragma: no cover - optional renderer dependency
    SPEC_AVAILABLE = False
    RENDERER_AVAILABLE = False

ANY_LABEL = "Any"
DEFAULT_PDF_NAME = "5e_CharacterSheet.pdf"
DEFAULT_PDF_DIR_PARTS = ("data",)
INVENTORY_ICON_BOX = 81
INVENTORY_ICON_FRAME = 3
INVENTORY_ICON_SCALE = 0.86
INVENTORY_ICON_SIZE = INVENTORY_ICON_BOX + (INVENTORY_ICON_FRAME * 2)
EQUIPMENT_ICON_SCALE = 0.9
INVENTORY_GRID_SPACING = 10
INVENTORY_ITEM_PAD = 4
INVENTORY_HIGHLIGHT_OUTSET = 3
INVENTORY_ITEM_SIZE = INVENTORY_ICON_SIZE + (INVENTORY_ITEM_PAD * 2)
INVENTORY_DRAG_MIME = "application/x-dmt-inventory-item"
EQUIPMENT_SLOT_SIZE = INVENTORY_ITEM_SIZE
# PDF pane should be 80% of inventory pane width: pdf / inventory = 0.8.
# Therefore pdf share of total is 0.8 / (1 + 0.8) = 0.444...
DETAIL_SPLITTER_PRIMARY_RATIO = 0.4444444444
LEGACY_MOCK_CHARACTER_SIGNATURES = frozenset(
    {
        ("liora sunfall", "eldervale", "ashen crown", "silver lances", ("cleric", "healer", "sun")),
        ("rook ironhand", "stormreach", "iron meridian", "cinderwatch", ("fighter", "frontline")),
        ("nyx shade", "", "", "", ("rogue", "scout")),
    }
)
EQUIPMENT_SLOTS_LEFT = [
    ("head", "Head"),
    ("necklace", "Necklace"),
    ("shoulder_pads", "Shoulder Pads"),
    ("chest", "Chest"),
    ("back", "Back"),
    ("gloves", "Gloves"),
    ("bracer", "Bracer"),
]
EQUIPMENT_SLOTS_RIGHT = [
    ("belt", "Belt"),
    ("pants", "Pants"),
    ("shoes", "Shoes"),
    ("ring_left", "Left Ring"),
    ("ring_right", "Right Ring"),
    ("misc_1", "Trinket 1"),
    ("misc_2", "Trinket 2"),
]
EQUIPMENT_SLOTS_WEAPONS = [
    ("weapon_1", "Weapon 1"),
    ("weapon_2", "Weapon 2"),
    ("weapon_3", "Weapon 3"),
    ("weapon_4", "Shield"),
]
EQUIPMENT_SLOTS_MISC = [
    ("misc_4", "Misc 1"),
    ("misc_5", "Misc 2"),
    ("misc_6", "Misc 3"),
    ("misc_7", "Misc 4"),
    ("misc_8", "Misc 5"),
    ("misc_9", "Misc 6"),
    ("misc_10", "Misc 7"),
    ("misc_11", "Misc 8"),
    ("misc_12", "Misc 9"),
    ("misc_13", "Misc 10"),
]
EQUIPMENT_SLOT_LABELS = {
    slot_id: label
    for slot_id, label in (
        *EQUIPMENT_SLOTS_LEFT,
        *EQUIPMENT_SLOTS_RIGHT,
        *EQUIPMENT_SLOTS_WEAPONS,
        *EQUIPMENT_SLOTS_MISC,
    )
}
EQUIPMENT_SLOT_IDS = list(EQUIPMENT_SLOT_LABELS.keys())
_equipment_slot_background_cache: dict[tuple[str, str, int, int], QPixmap] = {}


def _equipment_silhouette_pixmap() -> QPixmap:
    for candidate in EQUIPMENT_SILHOUETTE_CANDIDATES:
        if not candidate.exists():
            continue
        pixmap = QPixmap(str(candidate))
        if not pixmap.isNull():
            return pixmap
    return QPixmap()


def default_sheet_pdf_path() -> Optional[str]:
    assets_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", *DEFAULT_PDF_DIR_PARTS)
    )
    if not os.path.isdir(assets_dir):
        return None
    preferred = os.path.join(assets_dir, DEFAULT_PDF_NAME)
    if os.path.exists(preferred):
        return preferred
    for filename in sorted(os.listdir(assets_dir)):
        if filename.lower().endswith(".pdf"):
            return os.path.join(assets_dir, filename)
    return None


def default_sheet_save_dir() -> str:
    return default_dnd_save_dir()


def character_sheets_dir() -> Path:
    return Path(default_sheet_save_dir()) / "characters"


def character_sheets_trash_dir() -> Path:
    return Path(default_sheet_save_dir()) / "trash" / "characters"


def character_sheet_cache_dir() -> Path:
    return Path(default_sheet_save_dir()) / "cache" / "characters"


class PlayerSheetEvents(QObject):
    inventorySaved = Signal(str, dict)


PLAYER_SHEET_EVENTS = PlayerSheetEvents()


def _empty_equipment_slots() -> dict[str, Optional[str]]:
    return {slot_id: None for slot_id in EQUIPMENT_SLOT_IDS}


def _normalize_equipment(payload: object) -> dict[str, Optional[str]]:
    equipment = _empty_equipment_slots()
    if not isinstance(payload, dict):
        return equipment
    for slot_id in EQUIPMENT_SLOT_IDS:
        value = payload.get(slot_id)
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                equipment[slot_id] = cleaned
    # Backward compatibility: older saves used misc_3 before the bracer slot existed.
    if equipment.get("bracer") is None:
        legacy_bracer = payload.get("misc_3")
        if isinstance(legacy_bracer, str):
            cleaned = legacy_bracer.strip()
            if cleaned:
                equipment["bracer"] = cleaned
    return equipment


def _decode_inventory_drag(mime_data: QMimeData) -> Optional[dict]:
    if not mime_data.hasFormat(INVENTORY_DRAG_MIME):
        return None
    raw = mime_data.data(INVENTORY_DRAG_MIME)
    if not raw:
        return None
    try:
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _encode_inventory_drag(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def _clamp_preview_point(point: QPoint, preview_size: QSize, screen_rect: QRect) -> QPoint:
    max_x = screen_rect.left() + max(0, screen_rect.width() - preview_size.width())
    max_y = screen_rect.top() + max(0, screen_rect.height() - preview_size.height())
    x = min(max(point.x(), screen_rect.left()), max_x)
    y = min(max(point.y(), screen_rect.top()), max_y)
    return QPoint(x, y)


def _intersects_blocked(rect: QRect, blocked_rects: list[QRect]) -> bool:
    return any(rect.intersects(blocked) for blocked in blocked_rects if blocked.isValid())


def _pixmap_logical_size(pixmap: QPixmap) -> QSize:
    if pixmap.isNull():
        return QSize()
    logical_size = pixmap.deviceIndependentSize()
    return QSize(
        max(0, int(round(logical_size.width()))),
        max(0, int(round(logical_size.height()))),
    )


def _screen_dpr_for_global_pos(
    global_pos: QPoint, fallback_widget: Optional[QWidget] = None
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


def _dpr_fitted_pixel_size(logical_size: int, requested_dpr: float) -> tuple[int, float]:
    """Return (pixel_size, effective_dpr) without fractional-DPR logical drift."""
    safe_logical = max(1, int(logical_size))
    safe_requested = max(1.0, float(requested_dpr))
    rounded_requested = round(safe_requested)
    if abs(safe_requested - rounded_requested) > 0.01:
        # Fractional DPR causes non-integer logical pixmap size in QLabel.
        # Use logical-size pixmaps to keep slot content locked to frame bounds.
        return safe_logical, 1.0
    pixel_size = max(1, int(round(safe_logical * float(rounded_requested))))
    effective_dpr = pixel_size / float(safe_logical)
    return pixel_size, effective_dpr


def compute_equipment_preview_position(
    hover_rect: QRect,
    preview_size: QSize,
    blocked_rects: list[QRect],
    screen_rect: QRect,
    toward_silhouette: str,
    gap: int = 10,
) -> QPoint:
    if preview_size.width() <= 0 or preview_size.height() <= 0:
        return hover_rect.topLeft()
    if not screen_rect.isValid():
        screen_rect = QRect(0, 0, preview_size.width() * 2, preview_size.height() * 2)

    prefer_right = toward_silhouette.lower() != "left"
    hover_center = hover_rect.center()
    y_base = hover_center.y() - (preview_size.height() // 2)
    primary_x = (
        hover_rect.right() + gap
        if prefer_right
        else hover_rect.left() - preview_size.width() - gap
    )
    secondary_x = (
        hover_rect.left() - preview_size.width() - gap
        if prefer_right
        else hover_rect.right() + gap
    )

    y_offsets = [0, -8, 8, -16, 16, -24, 24, -32, 32, -40, 40]
    primary_x_offsets = [0, 6, 12, 18, 24]
    secondary_x_offsets = [0, -6, -12, -18, -24]
    if not prefer_right:
        primary_x_offsets = [0, -6, -12, -18, -24]
        secondary_x_offsets = [0, 6, 12, 18, 24]

    best_valid: Optional[tuple[int, QPoint]] = None
    best_any: Optional[tuple[int, QPoint]] = None
    for is_primary, base_x, x_offsets in (
        (True, primary_x, primary_x_offsets),
        (False, secondary_x, secondary_x_offsets),
    ):
        side_penalty = 0 if is_primary else 10_000
        for x_offset in x_offsets:
            for y_offset in y_offsets:
                candidate = QPoint(base_x + x_offset, y_base + y_offset)
                clamped = _clamp_preview_point(candidate, preview_size, screen_rect)
                preview_rect = QRect(clamped, preview_size)
                distance = (
                    abs(preview_rect.center().x() - hover_center.x())
                    + abs(preview_rect.center().y() - hover_center.y())
                    + side_penalty
                )
                if best_any is None or distance < best_any[0]:
                    best_any = (distance, clamped)
                if _intersects_blocked(preview_rect, blocked_rects):
                    continue
                if best_valid is None or distance < best_valid[0]:
                    best_valid = (distance, clamped)

    if best_valid is not None:
        return best_valid[1]

    max_y = screen_rect.top() + max(0, screen_rect.height() - preview_size.height())
    for base_x in (primary_x, secondary_x):
        for y in range(screen_rect.top(), max_y + 1, 8):
            clamped = _clamp_preview_point(QPoint(base_x, y), preview_size, screen_rect)
            preview_rect = QRect(clamped, preview_size)
            if _intersects_blocked(preview_rect, blocked_rects):
                continue
            return clamped

    max_x = screen_rect.left() + max(0, screen_rect.width() - preview_size.width())
    for x in range(screen_rect.left(), max_x + 1, 12):
        for y in range(screen_rect.top(), max_y + 1, 12):
            candidate = QPoint(x, y)
            preview_rect = QRect(candidate, preview_size)
            if _intersects_blocked(preview_rect, blocked_rects):
                continue
            return candidate

    if best_any is not None:
        return best_any[1]
    return _clamp_preview_point(QPoint(primary_x, y_base), preview_size, screen_rect)


def compute_cursor_preview_position(
    hover_rect: QRect,
    preview_size: QSize,
    cursor_pos: QPoint,
    screen_rect: QRect,
    gap: int = 12,
) -> QPoint:
    if preview_size.width() <= 0 or preview_size.height() <= 0:
        return hover_rect.topLeft()
    if not screen_rect.isValid():
        screen_rect = QRect(
            cursor_pos.x() - preview_size.width(),
            cursor_pos.y() - preview_size.height(),
            preview_size.width() * 2,
            preview_size.height() * 2,
        )

    preview_w = preview_size.width()
    preview_h = preview_size.height()
    candidates: list[QPoint] = []

    def _add(point: QPoint) -> None:
        clamped = _clamp_preview_point(point, preview_size, screen_rect)
        if clamped not in candidates:
            candidates.append(clamped)

    # Prefer backpack-like cursor-relative placement first.
    _add(cursor_pos + QPoint(gap, gap))
    _add(cursor_pos + QPoint(gap, -preview_h - gap))
    _add(cursor_pos + QPoint(-preview_w - gap, gap))
    _add(cursor_pos + QPoint(-preview_w - gap, -preview_h - gap))

    # Fallback positions around the hovered slot if cursor-adjacent spots overlap.
    centered_y = hover_rect.center().y() - (preview_h // 2)
    centered_x = hover_rect.center().x() - (preview_w // 2)
    _add(QPoint(hover_rect.right() + gap, centered_y))
    _add(QPoint(hover_rect.left() - preview_w - gap, centered_y))
    _add(QPoint(centered_x, hover_rect.bottom() + gap))
    _add(QPoint(centered_x, hover_rect.top() - preview_h - gap))
    for offset in (-18, 18, -36, 36):
        _add(QPoint(hover_rect.right() + gap, centered_y + offset))
        _add(QPoint(hover_rect.left() - preview_w - gap, centered_y + offset))

    def _distance(point: QPoint) -> int:
        center_x = point.x() + (preview_w // 2)
        center_y = point.y() + (preview_h // 2)
        return abs(center_x - cursor_pos.x()) + abs(center_y - cursor_pos.y())

    best_non_overlap: Optional[tuple[int, QPoint]] = None
    best_overlap: Optional[tuple[int, int, QPoint]] = None
    for candidate in candidates:
        preview_rect = QRect(candidate, preview_size)
        overlap_rect = preview_rect.intersected(hover_rect)
        overlap_area = max(0, overlap_rect.width()) * max(0, overlap_rect.height())
        distance = _distance(candidate)
        if overlap_area == 0:
            if best_non_overlap is None or distance < best_non_overlap[0]:
                best_non_overlap = (distance, candidate)
            continue
        if best_overlap is None or (overlap_area, distance) < (best_overlap[0], best_overlap[1]):
            best_overlap = (overlap_area, distance, candidate)

    if best_non_overlap is not None:
        return best_non_overlap[1]
    if best_overlap is not None:
        return best_overlap[2]
    return _clamp_preview_point(cursor_pos + QPoint(gap, gap), preview_size, screen_rect)


def _renderer_rarity_key(rarity: str) -> str:
    cleaned = str(rarity or "").strip().lower()
    if cleaned == "very rare":
        return "epic"
    return cleaned or "common"


def _parse_item_fields(data: dict) -> tuple[str, Optional[str]]:
    if SPEC_AVAILABLE:
        spec = spec_from_dict(data)
        title = spec.title
        rarity = _normalize_rarity(spec.rarity)
        return title, rarity

    title = str(data.get("title", "Untitled Item"))
    rarity = _normalize_rarity(str(data.get("rarity", "")))
    return title, rarity


def _parse_item_level(data: dict) -> Optional[int]:
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


def _loot_item_dirs() -> List[Path]:
    return [items_dir()]


def _loot_item_from_path(path: Path) -> Optional[LootItem]:
    data = load_item_payload(path)
    if not isinstance(data, dict):
        return None

    title, rarity = _parse_item_fields(data)
    if rarity is None:
        return None
    level = _parse_item_level(data)
    if level is None or level > LEVEL_CAP:
        return None
    tags = _normalize_tags(data.get("tags"))
    categories = _normalize_categories(data.get("category", data.get("categories")))
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


def _load_loot_item_library() -> tuple[List[LootItem], dict[str, LootItem]]:
    items: List[LootItem] = []
    item_by_id: dict[str, LootItem] = {}
    for root in _loot_item_dirs():
        if not root.exists():
            continue
        for path in list_item_file_paths(root):
            item = _loot_item_from_path(path)
            if not item or item.item_id in item_by_id:
                continue
            items.append(item)
            item_by_id[item.item_id] = item
    items.sort(key=lambda entry: entry.title.lower())
    return items, item_by_id


def _pil_to_qimage(pil_image) -> QImage:
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(
        data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888
    )
    return qimage.copy()


def _fallback_inventory_icon_pixmap(
    item: Optional[LootItem], size: int
) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    rarity_key = (item.rarity or "common").strip().lower() if item else "common"
    hex_color = LOOT_RARITY_COLORS.get(rarity_key, "#2a2f36")
    base_color = QColor(hex_color)
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

    if item and item.icon_path:
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


def _trim_alpha_bbox(image, threshold: int = 8):
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    alpha = image.getchannel("A")
    mask = alpha if threshold <= 0 else alpha.point(lambda value: 255 if value > threshold else 0)
    bbox = mask.getbbox()
    if not bbox:
        return image
    return image.crop(bbox)


def _inventory_icon_pixmap(item: Optional[LootItem]) -> QPixmap:
    if item is None:
        return _fallback_inventory_icon_pixmap(None, INVENTORY_ICON_SIZE)
    if not RENDERER_AVAILABLE:
        return _fallback_inventory_icon_pixmap(item, INVENTORY_ICON_SIZE)

    frame = INVENTORY_ICON_FRAME
    size = INVENTORY_ICON_SIZE
    icon_box = max(1, size - (frame * 2))
    rarity_key = _renderer_rarity_key(item.rarity)
    rarity_rgb = RENDER_RARITY_COLORS.get(rarity_key, RENDER_RARITY_COLORS["common"])

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = _icon_gradient_bg(size, rarity_rgb, PREVIEW_ICON_CURVE)
    img.alpha_composite(bg, (0, 0))

    icon_path = item.icon_path or None
    if icon_path:
        try:
            icon = Image.open(icon_path)
        except Exception:
            icon = None
        if icon is not None:
            if icon.mode != "RGBA":
                icon = icon.convert("RGBA")
            if icon.size[0] != icon.size[1]:
                try:
                    icon = _trim_black_bbox(icon)
                except Exception:
                    pass
            effective_scale = 1.0
            if item.show_icon_padding:
                effective_scale = 0.75
            
            raw_icon_img_size = icon_box * effective_scale
            icon_img_size = max(1, min(icon_box, int(round(raw_icon_img_size))))
            # Keep icon/image parity aligned with the target box to avoid 1px centering drift.
            if (icon_img_size % 2) != (icon_box % 2):
                candidates = [
                    candidate
                    for candidate in (icon_img_size - 1, icon_img_size + 1)
                    if 1 <= candidate <= icon_box and (candidate % 2) == (icon_box % 2)
                ]
                if candidates:
                    icon_img_size = min(
                        candidates,
                        key=lambda candidate: (abs(candidate - raw_icon_img_size), -candidate),
                    )
            
            if item.show_icon_padding:
                icon_sq = _icon_contain_resize(icon, icon_img_size, inner_pad=0)
            else:
                icon_sq = _icon_cover_resize(icon, icon_img_size)

            icon_img_x = frame + (icon_box - icon_img_size) // 2
            icon_img_y = frame + (icon_box - icon_img_size) // 2
            img.alpha_composite(icon_sq, (icon_img_x, icon_img_y))

    draw = ImageDraw.Draw(img)
    outer_col = (108, 110, 132, 255)
    for offset in range(frame):
        draw.rectangle(
            [offset, offset, size - 1 - offset, size - 1 - offset],
            outline=outer_col,
            width=1,
        )
    qimage = _pil_to_qimage(img)
    return QPixmap.fromImage(qimage)


def _equipment_item_icon_pixmap(item: Optional[LootItem]) -> QPixmap:
    if item is None:
        return _missing_inventory_icon_pixmap()
    if not RENDERER_AVAILABLE:
        return _fallback_inventory_icon_pixmap(item, INVENTORY_ICON_SIZE)

    frame = INVENTORY_ICON_FRAME
    size = INVENTORY_ICON_SIZE
    icon_box = max(1, size - (frame * 2))
    rarity_key = _renderer_rarity_key(item.rarity)
    rarity_rgb = RENDER_RARITY_COLORS.get(rarity_key, RENDER_RARITY_COLORS["common"])

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg = _icon_gradient_bg(size, rarity_rgb, PREVIEW_ICON_CURVE)
    img.alpha_composite(bg, (0, 0))

    icon_path = item.icon_path or None
    if icon_path:
        try:
            icon = Image.open(icon_path)
        except Exception:
            icon = None
        if icon is not None:
            if icon.mode != "RGBA":
                icon = icon.convert("RGBA")
            icon = _trim_alpha_bbox(icon, threshold=8)
            if icon.size[0] != icon.size[1]:
                try:
                    icon = _trim_black_bbox(icon)
                except Exception:
                    pass
                icon = _trim_alpha_bbox(icon, threshold=8)
            effective_scale = 1.0
            if item.show_icon_padding:
                effective_scale = 0.75
            
            icon_img_size = max(1, int(round(icon_box * effective_scale)))
            icon_sq = _icon_contain_resize(icon, icon_img_size, 0)
            icon_img_x = frame + (icon_box - icon_img_size) // 2
            icon_img_y = frame + (icon_box - icon_img_size) // 2
            img.alpha_composite(icon_sq, (icon_img_x, icon_img_y))

    draw = ImageDraw.Draw(img)
    outer_col = (108, 110, 132, 255)
    for offset in range(frame):
        draw.rectangle(
            [offset, offset, size - 1 - offset, size - 1 - offset],
            outline=outer_col,
            width=1,
        )
    qimage = _pil_to_qimage(img)
    return QPixmap.fromImage(qimage)


def _render_item_preview_pixmap(
    item: LootItem,
    *,
    max_width: int = PREVIEW_TOOLTIP_WIDTH,
    max_height: Optional[int] = None,
    dpr: float = 1.0,
) -> Optional[QPixmap]:
    if not (RENDERER_AVAILABLE and item.path):
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


def _missing_inventory_icon_pixmap() -> QPixmap:
    size = INVENTORY_ICON_SIZE
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    base_color = QColor("#2a2f36")
    grad = QRadialGradient(size / 2, size / 2, size / 2)
    grad.setColorAt(0.0, base_color.lighter(120))
    grad.setColorAt(0.6, base_color)
    grad.setColorAt(1.0, base_color.darker(160))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.fillRect(0, 0, size, size, grad)
    painter.setPen(QColor(80, 88, 100))
    painter.drawRect(1, 1, size - 2, size - 2)
    painter.setPen(QColor("#8b949e"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "?")
    painter.end()
    return pixmap


def _currency_icon_pixmap(color: QColor, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    center = size / 2
    grad = QRadialGradient(center, center, max(2, size / 2))
    grad.setColorAt(0.0, color.lighter(135))
    grad.setColorAt(0.6, color)
    grad.setColorAt(1.0, color.darker(180))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(grad)
    painter.setPen(QColor(20, 24, 30))
    radius = max(1, int(size / 2) - 1)
    painter.drawEllipse(int(center - radius), int(center - radius), radius * 2, radius * 2)
    painter.setPen(QColor(255, 255, 255, 80))
    painter.drawEllipse(int(center - radius + 1), int(center - radius + 1), (radius * 2) - 2, (radius * 2) - 2)
    painter.end()
    return pixmap


def _resolve_equipment_slot_background_path(slot_id: Optional[str]) -> Path:
    candidate_names = EQUIPMENT_SLOT_BACKGROUND_CANDIDATES.get(slot_id or "", ())
    for name in candidate_names:
        path = EQUIPMENT_BACKGROUNDS_DIR / name
        if path.exists():
            return path
    fallback_path = EQUIPMENT_BACKGROUNDS_DIR / EQUIPMENT_DEFAULT_BACKGROUND_NAME
    return fallback_path


def _equipment_slot_background_pixmap(
    size: int, dpr: float = 1.0, slot_id: Optional[str] = None
) -> QPixmap:
    safe = max(1, int(size))
    pixel_size, effective_dpr = _dpr_fitted_pixel_size(safe, dpr)
    source_path = _resolve_equipment_slot_background_path(slot_id)
    cache_key = (str(source_path), slot_id or "", safe, pixel_size)
    cached = _equipment_slot_background_cache.get(cache_key)
    if cached is not None:
        return cached

    source: QPixmap
    if source_path.suffix.lower() == ".svg":
        # Render vectors directly at target size to avoid low-res SVG rasterization.
        source = QIcon(str(source_path)).pixmap(QSize(pixel_size, pixel_size))
    else:
        source = QPixmap(str(source_path))
    if source.isNull():
        fallback = QPixmap(pixel_size, pixel_size)
        fallback.fill(Qt.GlobalColor.transparent)
        # Keep a visible, faint placeholder even when the asset is missing.
        painter = QPainter(fallback)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(150, 150, 150, 120), max(1, int(round(pixel_size * 0.05)))))
        inset = max(2, int(round(pixel_size * 0.16)))
        diameter = max(1, pixel_size - (inset * 2))
        painter.drawEllipse(inset, inset, diameter, diameter)
        painter.setPen(QPen(QColor(180, 180, 180, 72), max(1, int(round(pixel_size * 0.02)))))
        inner_inset = inset + max(1, int(round(pixel_size * 0.1)))
        inner_diameter = max(1, pixel_size - (inner_inset * 2))
        painter.drawEllipse(inner_inset, inner_inset, inner_diameter, inner_diameter)
        painter.end()
        fallback.setDevicePixelRatio(effective_dpr)
        _equipment_slot_background_cache[cache_key] = fallback
        return fallback
    scaled = source.scaled(
        pixel_size,
        pixel_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QPixmap(pixel_size, pixel_size)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    x = (pixel_size - scaled.width()) // 2
    y = (pixel_size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()

    image = canvas.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for py in range(image.height()):
        for px in range(image.width()):
            color = image.pixelColor(px, py)
            alpha = color.alpha()
            if alpha == 0:
                continue
            gray = int((color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000)
            image.setPixelColor(px, py, QColor(gray, gray, gray, int(alpha * 0.52)))
    grayscale = QPixmap.fromImage(image)
    grayscale.setDevicePixelRatio(effective_dpr)
    _equipment_slot_background_cache[cache_key] = grayscale
    return grayscale


def sheet_id_for_entry(entry: PlayerSheetEntry) -> str:
    return sanitize_filename(entry.name)


def character_sheet_pdf_path(sheet_id: str) -> Path:
    return character_sheet_cache_dir() / f"{sheet_id}.pdf"


def character_sheet_archive_path(sheet_id: str) -> Path:
    return character_sheets_dir() / f"{sheet_id}{ARCHIVE_EXTENSION}"


def character_sheet_trash_path(sheet_id: str) -> Path:
    return character_sheets_trash_dir() / f"{sheet_id}.pdf"


def character_sheet_archive_trash_path(sheet_id: str) -> Path:
    return character_sheets_trash_dir() / f"{sheet_id}{ARCHIVE_EXTENSION}"


def move_entry_files_to_trash(entry: PlayerSheetEntry) -> Optional[str]:
    sheet_id = sheet_id_for_entry(entry)
    storage_path = character_sheet_pdf_path(sheet_id)
    trash_path = character_sheet_trash_path(sheet_id)
    archive_path = Path(entry.archive_path) if getattr(entry, "archive_path", "") else character_sheet_archive_path(sheet_id)
    archive_trash_path = character_sheet_archive_trash_path(sheet_id)
    current_path = Path(entry.pdf_path)
    moved_pdf: Optional[str] = None
    if current_path.exists():
        if character_sheets_trash_dir() in current_path.parents:
            moved_pdf = str(current_path)
        else:
            trash_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                if trash_path.exists():
                    trash_path.unlink()
                shutil.move(str(current_path), str(trash_path))
                moved_pdf = str(trash_path)
            except OSError:
                logger.exception("Failed to move player sheet PDF to trash: %s", current_path)
                moved_pdf = None
    elif storage_path.exists():
        trash_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if trash_path.exists():
                trash_path.unlink()
            shutil.move(str(storage_path), str(trash_path))
            moved_pdf = str(trash_path)
        except OSError:
            logger.exception("Failed to move stored player sheet PDF to trash: %s", storage_path)
            moved_pdf = None

    if archive_path.exists():
        archive_trash_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if archive_trash_path.exists():
                archive_trash_path.unlink()
            shutil.move(str(archive_path), str(archive_trash_path))
            entry.archive_path = str(archive_trash_path)
        except OSError:
            logger.exception("Failed to move player sheet archive to trash: %s", archive_path)

    return moved_pdf


def delete_entry_files(entry: PlayerSheetEntry) -> None:
    target = Path(entry.pdf_path)
    try:
        if target.exists():
            target.unlink()
    except OSError:
        return
    archive_target = Path(entry.archive_path) if getattr(entry, "archive_path", "") else None
    if archive_target is not None:
        try:
            if archive_target.exists():
                archive_target.unlink()
        except OSError:
            return


def disintegrate_entry_files(entry: PlayerSheetEntry) -> None:
    sheet_id = sheet_id_for_entry(entry)
    storage_path = character_sheet_pdf_path(sheet_id)
    trash_path = character_sheet_trash_path(sheet_id)
    archive_path = character_sheet_archive_path(sheet_id)
    archive_trash_path = character_sheet_archive_trash_path(sheet_id)
    dynamic_archive = Path(entry.archive_path) if getattr(entry, "archive_path", "") else None
    targets = {Path(entry.pdf_path), storage_path, trash_path, archive_path, archive_trash_path}
    if dynamic_archive is not None:
        targets.add(dynamic_archive)
    for target in targets:
        try:
            if not target.exists():
                continue
            target.unlink()
        except OSError:
            logger.exception("Failed to delete player sheet PDF: %s", target)
            continue


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "character_sheet"


def player_sheets_storage_path() -> Path:
    return player_sheets_cache_dir() / "character_sheets.json"


def player_sheets_storage_dir() -> Path:
    return Path(default_sheet_save_dir()) / "characters"


def player_sheets_cache_dir() -> Path:
    return Path(default_sheet_save_dir()) / "cache" / "characters"


def entry_to_dict(entry: PlayerSheetEntry) -> dict:
    return {
        "name": entry.name,
        "pdf_path": entry.pdf_path,
        "archive_path": entry.archive_path,
        "world": entry.world,
        "campaign": entry.campaign,
        "group": entry.group,
        "tags": list(entry.tags),
        "inventory": list(entry.inventory),
        "inventory_notes": entry.inventory_notes,
        "equipment": dict(entry.equipment),
        "gold": entry.gold,
        "silver": entry.silver,
        "copper": entry.copper,
    }


def entry_from_dict(payload: dict) -> Optional[PlayerSheetEntry]:
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "")).strip()
    pdf_path = str(payload.get("pdf_path", "")).strip()
    archive_path = str(payload.get("archive_path", "")).strip()
    if not name or (not pdf_path and not archive_path):
        return None
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    inventory = payload.get("inventory") or []
    if not isinstance(inventory, list):
        inventory = []
    equipment = payload.get("equipment") or {}
    def _read_currency(value) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return PlayerSheetEntry(
        name=name,
        pdf_path=pdf_path,
        archive_path=archive_path,
        world=payload.get("world") or None,
        campaign=payload.get("campaign") or None,
        group=payload.get("group") or None,
        tags=[str(tag) for tag in tags if str(tag).strip()],
        inventory=[str(item) for item in inventory if str(item).strip()],
        inventory_notes=str(payload.get("inventory_notes", "")),
        equipment=_normalize_equipment(equipment),
        gold=_read_currency(payload.get("gold", 0)),
        silver=_read_currency(payload.get("silver", 0)),
        copper=_read_currency(payload.get("copper", 0)),
    )


@dataclass
class PlayerSheetEntry:
    name: str
    pdf_path: str
    archive_path: str = ""
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    inventory: List[str] = field(default_factory=list)
    inventory_notes: str = ""
    equipment: dict[str, Optional[str]] = field(default_factory=_empty_equipment_slots)
    gold: int = 0
    silver: int = 0
    copper: int = 0

    def __post_init__(self) -> None:
        self.tags = normalize_tags(self.tags)
        self.inventory_notes = str(self.inventory_notes or "")
        self.equipment = _normalize_equipment(self.equipment)
        try:
            self.gold = max(0, int(self.gold))
        except (TypeError, ValueError):
            self.gold = 0
        try:
            self.silver = max(0, int(self.silver))
        except (TypeError, ValueError):
            self.silver = 0
        try:
            self.copper = max(0, int(self.copper))
        except (TypeError, ValueError):
            self.copper = 0


def _entry_archive_path(entry: PlayerSheetEntry) -> Path:
    if entry.archive_path:
        return Path(entry.archive_path)
    return character_sheet_archive_path(sheet_id_for_entry(entry))


def _entry_inventory_payload(entry: PlayerSheetEntry) -> dict:
    return normalize_inventory_payload(
        {
            "inventory": list(entry.inventory),
            "inventory_notes": entry.inventory_notes,
            "equipment": dict(entry.equipment),
            "gold": entry.gold,
            "silver": entry.silver,
            "copper": entry.copper,
        }
    )


def _entry_meta_payload(entry: PlayerSheetEntry, *, created_at: str | None = None) -> dict:
    payload: dict[str, object] = {
        "name": str(entry.name or "").strip(),
        "sheet_id": sheet_id_for_entry(entry),
        "world": str(entry.world or "").strip(),
        "campaign": str(entry.campaign or "").strip(),
        "group": str(entry.group or "").strip(),
        "tags": [str(tag).strip() for tag in entry.tags if str(tag).strip()],
        "created_at": str(created_at or "").strip(),
    }
    return payload


def _apply_entry_meta(entry: PlayerSheetEntry, meta: dict) -> None:
    if not isinstance(meta, dict):
        return

    name = str(meta.get("name") or "").strip()
    if name:
        entry.name = name

    if "world" in meta:
        world = str(meta.get("world") or "").strip()
        entry.world = world or None
    if "campaign" in meta:
        campaign = str(meta.get("campaign") or "").strip()
        entry.campaign = campaign or None
    if "group" in meta:
        group = str(meta.get("group") or "").strip()
        entry.group = group or None
    if "tags" in meta:
        raw_tags = meta.get("tags")
        if isinstance(raw_tags, list):
            entry.tags = normalize_tags(
                [str(tag).strip() for tag in raw_tags if str(tag).strip()]
            )


def _entry_from_archive(archive_path: Path) -> Optional[PlayerSheetEntry]:
    archive_meta = read_character_meta(archive_path)
    sheet_id = sanitize_filename(
        str(archive_meta.get("sheet_id") or archive_path.stem)
    )
    if not sheet_id:
        return None
    name = str(archive_meta.get("name") or sheet_id).strip() or sheet_id
    entry = PlayerSheetEntry(
        name=name,
        pdf_path=str(character_sheet_pdf_path(sheet_id)),
        archive_path=str(archive_path),
    )
    _apply_entry_meta(entry, archive_meta)
    ensure_entry_archive(entry)
    return entry


def _scan_archive_entries() -> List[PlayerSheetEntry]:
    root = character_sheets_dir()
    if not root.exists():
        return []
    entries: List[PlayerSheetEntry] = []
    for archive_path in sorted(root.glob(f"*{ARCHIVE_EXTENSION}")):
        entry = _entry_from_archive(archive_path)
        if entry is None:
            continue
        entries.append(entry)
    return entries


def ensure_entry_archive(entry: PlayerSheetEntry) -> bool:
    archive_path = _entry_archive_path(entry)
    if archive_path.exists():
        entry.archive_path = str(archive_path)
        archive_meta = read_character_meta(archive_path)
        _apply_entry_meta(entry, archive_meta)
        if not entry.pdf_path or not Path(entry.pdf_path).exists():
            target_pdf = character_sheet_pdf_path(sheet_id_for_entry(entry))
            if extract_character_pdf(archive_path, target_pdf):
                entry.pdf_path = str(target_pdf)
        archive_inventory = read_character_inventory(archive_path)
        entry.inventory = list(archive_inventory.get("inventory", []))
        entry.inventory_notes = str(archive_inventory.get("inventory_notes", ""))
        entry.equipment = _normalize_equipment(archive_inventory.get("equipment", {}))
        try:
            entry.gold = max(0, int(archive_inventory.get("gold", entry.gold)))
        except (TypeError, ValueError):
            pass
        try:
            entry.silver = max(0, int(archive_inventory.get("silver", entry.silver)))
        except (TypeError, ValueError):
            pass
        try:
            entry.copper = max(0, int(archive_inventory.get("copper", entry.copper)))
        except (TypeError, ValueError):
            pass
        return True

    source_pdf = Path(entry.pdf_path)
    if not source_pdf.exists():
        return False
    try:
        write_character_archive(
            archive_path,
            pdf_path=source_pdf,
            inventory_payload=_entry_inventory_payload(entry),
            meta=_entry_meta_payload(
                entry,
                created_at=read_character_meta(archive_path).get("created_at"),
            ),
        )
    except Exception:
        logger.exception("Failed to create character archive for %s", entry.name)
        return False
    entry.archive_path = str(archive_path)
    return True


def sync_entry_archive(entry: PlayerSheetEntry, pdf_source: str | None = None) -> bool:
    source = Path(pdf_source) if pdf_source else Path(entry.pdf_path)
    archive_path = _entry_archive_path(entry)
    if not source.exists() and archive_path.exists():
        fallback_pdf = character_sheet_pdf_path(sheet_id_for_entry(entry))
        if extract_character_pdf(archive_path, fallback_pdf):
            source = fallback_pdf
            entry.pdf_path = str(fallback_pdf)
    if not source.exists():
        return False
    old_meta = read_character_meta(archive_path)
    created_at = old_meta.get("created_at") or old_meta.get("updated_at")
    try:
        write_character_archive(
            archive_path,
            pdf_path=source,
            inventory_payload=_entry_inventory_payload(entry),
            meta=_entry_meta_payload(entry, created_at=created_at),
        )
    except Exception:
        logger.exception("Failed to sync character archive for %s", entry.name)
        return False
    entry.archive_path = str(archive_path)
    return True


def _entry_signature(entry: PlayerSheetEntry) -> tuple[str, str, str, str, tuple[str, ...]]:
    name = str(entry.name or "").strip().casefold()
    world = str(entry.world or "").strip().casefold()
    campaign = str(entry.campaign or "").strip().casefold()
    group = str(entry.group or "").strip().casefold()
    tags = tuple(sorted({str(tag).strip().casefold() for tag in entry.tags if str(tag).strip()}))
    return (name, world, campaign, group, tags)


def _is_legacy_mock_entry(entry: PlayerSheetEntry) -> bool:
    return _entry_signature(entry) in LEGACY_MOCK_CHARACTER_SIGNATURES


def load_entries_from_storage() -> List[PlayerSheetEntry]:
    """Load character rows from cache index and rebuild from .dmtchar archives when needed."""
    path = player_sheets_storage_path()
    entries: List[PlayerSheetEntry] = []
    removed_legacy_mock_entry = False

    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            raw = []
        if isinstance(raw, list):
            for payload in raw:
                entry = entry_from_dict(payload)
                if entry is None:
                    continue
                if _is_legacy_mock_entry(entry):
                    removed_legacy_mock_entry = True
                    continue
                ensure_entry_archive(entry)
                entries.append(entry)

    archive_entries = _scan_archive_entries()
    if archive_entries:
        by_sheet_id: dict[str, PlayerSheetEntry] = {}
        for entry in entries:
            by_sheet_id[sheet_id_for_entry(entry)] = entry
        for entry in archive_entries:
            by_sheet_id[sheet_id_for_entry(entry)] = entry
        entries = sorted(
            by_sheet_id.values(),
            key=lambda row: (str(row.name or "").casefold(), str(row.archive_path or "")),
        )

    if removed_legacy_mock_entry or archive_entries or not path.exists():
        try:
            save_entries_to_storage(entries)
        except Exception:
            logger.exception("Failed to persist character sheet cache index.")
    return entries


def save_entries_to_storage(entries: List[PlayerSheetEntry]) -> None:
    """Persist character sheet list metadata to cache (archives remain canonical payload)."""
    path = player_sheets_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: list[dict] = []
    for entry in entries:
        sync_entry_archive(entry)
        payload.append(entry_to_dict(entry))
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def refresh_character_sheet_index_cache() -> None:
    entries = _scan_archive_entries()
    save_entries_to_storage(entries)


def list_character_link_targets() -> List[PlayerSheetEntry]:
    return load_entries_from_storage()


def inventory_payload_for_sheet_id(sheet_id: str) -> Optional[dict]:
    target = str(sheet_id or "").strip()
    if not target:
        return None
    for entry in load_entries_from_storage():
        if sheet_id_for_entry(entry) == target:
            return _entry_inventory_payload(entry)
    return None


def ensure_network_linked_sheet_entry(
    sheet_id: str,
    sheet_name: str,
    inventory_payload: dict,
    *,
    emit_event: bool = True,
) -> tuple[bool, str, Optional[dict]]:
    target = str(sheet_id or "").strip()
    if not target:
        return False, "Missing character selection.", None

    entries = load_entries_from_storage()
    target_entry: PlayerSheetEntry | None = None
    for entry in entries:
        if sheet_id_for_entry(entry) == target:
            target_entry = entry
            break

    if target_entry is None:
        display_name = str(sheet_name or "").strip() or target
        if sanitize_filename(display_name) != target:
            # Keep incoming sheet id stable across host/client when names diverge.
            display_name = target

        pdf_path = character_sheet_pdf_path(target)
        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        if not pdf_path.exists():
            template_path = default_sheet_pdf_path()
            if template_path and Path(template_path).exists():
                try:
                    pdf_path.write_bytes(Path(template_path).read_bytes())
                except Exception:
                    logger.exception("Failed to copy default character sheet template for %s", target)
            if not pdf_path.exists():
                # Minimal fallback PDF bytes so archive/index creation can proceed.
                pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

        target_entry = PlayerSheetEntry(
            name=display_name,
            pdf_path=str(pdf_path),
        )
        entries.append(target_entry)

    normalized = normalize_inventory_payload(
        inventory_payload if isinstance(inventory_payload, dict) else {}
    )
    target_entry.inventory = list(
        normalized.get("inventory", [])
        if isinstance(normalized.get("inventory"), list)
        else []
    )
    target_entry.inventory_notes = str(normalized.get("inventory_notes", ""))
    target_entry.equipment = _normalize_equipment(normalized.get("equipment", {}))
    try:
        target_entry.gold = max(0, int(normalized.get("gold", 0)))
    except (TypeError, ValueError):
        target_entry.gold = 0
    try:
        target_entry.silver = max(0, int(normalized.get("silver", 0)))
    except (TypeError, ValueError):
        target_entry.silver = 0
    try:
        target_entry.copper = max(0, int(normalized.get("copper", 0)))
    except (TypeError, ValueError):
        target_entry.copper = 0

    sync_entry_archive(target_entry)
    save_entries_to_storage(entries)
    payload = _entry_inventory_payload(target_entry)
    if emit_event:
        PLAYER_SHEET_EVENTS.inventorySaved.emit(target, payload)
    return True, "Character synchronized.", payload


def set_inventory_payload_for_sheet_id(
    sheet_id: str,
    inventory_payload: dict,
    *,
    emit_event: bool = True,
) -> tuple[bool, str, Optional[dict]]:
    target = str(sheet_id or "").strip()
    if not target:
        return False, "Missing character selection.", None
    entries = load_entries_from_storage()
    target_entry: PlayerSheetEntry | None = None
    for entry in entries:
        if sheet_id_for_entry(entry) == target:
            target_entry = entry
            break
    if target_entry is None:
        return False, "Character not found.", None

    normalized = normalize_inventory_payload(
        inventory_payload if isinstance(inventory_payload, dict) else {}
    )
    target_entry.inventory = list(
        normalized.get("inventory", [])
        if isinstance(normalized.get("inventory"), list)
        else []
    )
    target_entry.inventory_notes = str(normalized.get("inventory_notes", ""))
    target_entry.equipment = _normalize_equipment(normalized.get("equipment", {}))
    try:
        target_entry.gold = max(0, int(normalized.get("gold", 0)))
    except (TypeError, ValueError):
        target_entry.gold = 0
    try:
        target_entry.silver = max(0, int(normalized.get("silver", 0)))
    except (TypeError, ValueError):
        target_entry.silver = 0
    try:
        target_entry.copper = max(0, int(normalized.get("copper", 0)))
    except (TypeError, ValueError):
        target_entry.copper = 0

    sync_entry_archive(target_entry)
    save_entries_to_storage(entries)
    payload = _entry_inventory_payload(target_entry)
    if emit_event:
        PLAYER_SHEET_EVENTS.inventorySaved.emit(target, payload)
    return True, "Inventory updated.", payload


def apply_claim_to_sheet(
    sheet_id: str,
    *,
    item_ids: list[str],
    note_lines: list[str],
) -> tuple[bool, str, Optional[dict]]:
    target = str(sheet_id or "").strip()
    if not target:
        return False, "Missing character selection.", None
    entries = load_entries_from_storage()
    target_entry: PlayerSheetEntry | None = None
    for entry in entries:
        if sheet_id_for_entry(entry) == target:
            target_entry = entry
            break
    if target_entry is None:
        return False, "Character not found.", None

    clean_items = [str(item).strip() for item in item_ids if str(item).strip()]
    clean_notes = [str(line).strip() for line in note_lines if str(line).strip()]
    if clean_items:
        target_entry.inventory.extend(clean_items)
    if clean_notes:
        existing = [line.strip() for line in str(target_entry.inventory_notes or "").splitlines() if line.strip()]
        target_entry.inventory_notes = "\n".join(existing + clean_notes)
    sync_entry_archive(target_entry)
    save_entries_to_storage(entries)
    payload = _entry_inventory_payload(target_entry)
    PLAYER_SHEET_EVENTS.inventorySaved.emit(target, payload)
    return True, "Claim applied.", payload


@dataclass
class PlayerSheetFilters:
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    tag_query: str = ""


class PlayerSheetsManager:
    def __init__(self, entries: Optional[List[PlayerSheetEntry]] = None) -> None:
        self.entries = list(entries or [])
        self.filters = PlayerSheetFilters()

    def set_filters(
        self,
        world: Optional[str],
        campaign: Optional[str],
        group: Optional[str],
        tag_query: str,
    ) -> None:
        self.filters = PlayerSheetFilters(
            world=world,
            campaign=campaign,
            group=group,
            tag_query=tag_query,
        )

    def add_sheet(self, entry: PlayerSheetEntry) -> None:
        self.entries.append(entry)

    def filtered_entries(self) -> List[PlayerSheetEntry]:
        return filter_entries(
            self.entries,
            world=self.filters.world,
            campaign=self.filters.campaign,
            group=self.filters.group,
            tag_query=self.filters.tag_query,
        )


def _normalize_tag(tag: str) -> str:
    return tag.strip().lower()


def parse_tag_query(text: str) -> List[str]:
    if not text:
        return []
    tokens = re.split(r"[,\s]+", text)
    return [_normalize_tag(token) for token in tokens if _normalize_tag(token)]


def normalize_tags(tags: Iterable[str]) -> List[str]:
    normalized: List[str] = []
    for tag in tags:
        cleaned = _normalize_tag(tag)
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


def _unique_in_order(items: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def list_worlds(world_data: list[dict]) -> List[str]:
    worlds: List[str] = []
    for world in world_data:
        if isinstance(world, dict):
            name = str(world.get("name") or "").strip()
        else:
            name = str(world or "").strip()
        if name:
            worlds.append(name)
    return _unique_in_order(worlds)


def list_campaigns(world_data: list[dict], world: Optional[str] = None) -> List[str]:
    if world:
        for world_entry in world_data:
            if not isinstance(world_entry, dict):
                continue
            if world_entry.get("name") == world:
                campaigns: List[str] = []
                for campaign in world_entry.get("campaigns", []):
                    if isinstance(campaign, dict):
                        name = str(campaign.get("name") or "").strip()
                    else:
                        name = str(campaign or "").strip()
                    if name:
                        campaigns.append(name)
                return campaigns
        return []

    campaigns: List[str] = []
    for world_entry in world_data:
        if not isinstance(world_entry, dict):
            continue
        for campaign in world_entry.get("campaigns", []):
            if isinstance(campaign, dict):
                name = str(campaign.get("name") or "").strip()
            else:
                name = str(campaign or "").strip()
            if name:
                campaigns.append(name)
    return _unique_in_order(campaigns)


def list_groups(
    world_data: list[dict],
    world: Optional[str] = None,
    campaign: Optional[str] = None,
) -> List[str]:
    groups: List[str] = []
    for world_entry in world_data:
        if not isinstance(world_entry, dict):
            continue
        if world and world_entry.get("name") != world:
            continue
        for campaign_entry in world_entry.get("campaigns", []):
            if not isinstance(campaign_entry, dict):
                continue
            if campaign and campaign_entry.get("name") != campaign:
                continue
            for group_entry in campaign_entry.get("groups", []):
                if isinstance(group_entry, dict):
                    group_name = str(group_entry.get("name") or "").strip()
                else:
                    group_name = str(group_entry or "").strip()
                if group_name:
                    groups.append(group_name)
    return _unique_in_order(groups)


def resolve_selection(options: Iterable[str], value: Optional[str]) -> Optional[str]:
    if value and value in options:
        return value
    return None


def coerce_hierarchy_selection(
    world_data: list[dict],
    world: Optional[str],
    campaign: Optional[str],
    group: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    campaigns = list_campaigns(world_data, world)
    campaign = resolve_selection(campaigns, campaign)
    groups = list_groups(world_data, world, campaign)
    group = resolve_selection(groups, group)
    return campaign, group


def matches_filters(
    entry: PlayerSheetEntry,
    world: Optional[str],
    campaign: Optional[str],
    group: Optional[str],
    tag_query: str,
) -> bool:
    if world and entry.world != world:
        return False
    if campaign and entry.campaign != campaign:
        return False
    if group and entry.group != group:
        return False

    required_tags = parse_tag_query(tag_query)
    if required_tags:
        entry_tags = set(entry.tags)
        if not all(tag in entry_tags for tag in required_tags):
            return False

    return True


def filter_entries(
    entries: Iterable[PlayerSheetEntry],
    world: Optional[str] = None,
    campaign: Optional[str] = None,
    group: Optional[str] = None,
    tag_query: str = "",
) -> List[PlayerSheetEntry]:
    return [
        entry
        for entry in entries
        if matches_filters(entry, world, campaign, group, tag_query)
    ]


def _combo_optional_value(combo: QComboBox) -> Optional[str]:
    value = combo.currentText().strip()
    if not value or value == ANY_LABEL:
        return None
    return value


def _populate_combo(
    combo: QComboBox, items: Iterable[str], current_value: Optional[str] = None
) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(ANY_LABEL)
    for item in items:
        combo.addItem(item)

    if current_value:
        match_index = combo.findText(current_value)
        if match_index != -1:
            combo.setCurrentIndex(match_index)
        else:
            combo.setCurrentIndex(0)
    else:
        combo.setCurrentIndex(0)
    combo.blockSignals(False)


class PlayerSheetDialog(QDialog):
    def __init__(
        self,
        world_data: list[dict],
        parent: Optional[QWidget] = None,
        entry: Optional[PlayerSheetEntry] = None,
        default_pdf_path: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._world_data = world_data
        self._entry: Optional[PlayerSheetEntry] = None
        self._original_entry = entry
        self._source_pdf_path: Optional[str] = None
        self._default_pdf_path = default_pdf_path or default_sheet_pdf_path()

        self.setWindowTitle("Edit Character Sheet" if entry else "New Character Sheet")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self._name_input = QLineEdit()
        form.addRow("Name", self._name_input)

        source_row = QWidget(self)
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(6)
        self._source_label = QLabel("No PDF selected")
        self._source_label.setWordWrap(True)
        self._default_button = QPushButton("Use 5E Sheet")
        self._default_button.setObjectName("SecondaryButton")
        self._default_button.clicked.connect(self._choose_default_pdf)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._choose_pdf)
        source_layout.addWidget(self._source_label, 1)
        source_layout.addWidget(self._default_button)
        source_layout.addWidget(browse_button)
        form.addRow("PDF Source", source_row)

        self._world_combo = QComboBox()
        self._campaign_combo = QComboBox()
        self._group_combo = QComboBox()

        form.addRow("World", self._world_combo)
        form.addRow("Campaign", self._campaign_combo)
        form.addRow("Group", self._group_combo)

        self._tags_input = QLineEdit()
        self._tags_input.setPlaceholderText("comma, separated, tags")
        form.addRow("Tags", self._tags_input)

        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

        if entry:
            self._name_input.setText(entry.name)
            if entry.tags:
                self._tags_input.setText(", ".join(entry.tags))
            self._set_pdf_source(
                entry.pdf_path, f"Current: {os.path.basename(entry.pdf_path)}"
            )
        elif self._default_pdf_path:
            self._set_pdf_source(
                self._default_pdf_path,
                f"Default: {os.path.basename(self._default_pdf_path)}",
            )
        else:
            self._source_label.setText("Default: Missing 5E sheet")
            self._default_button.setEnabled(False)

        _populate_combo(
            self._world_combo,
            list_worlds(self._world_data),
            entry.world if entry else None,
        )
        selected_campaign = self._update_campaigns(
            current_value=entry.campaign if entry else None
        )
        self._update_groups(
            current_value=entry.group if entry else None,
            campaign=selected_campaign,
        )

        self._world_combo.currentIndexChanged.connect(self._on_world_changed)
        self._campaign_combo.currentIndexChanged.connect(self._on_campaign_changed)

    def entry(self) -> Optional[PlayerSheetEntry]:
        return self._entry

    def _choose_pdf(self) -> None:
        default_path = self._default_pdf_path
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Character Sheet",
            os.path.dirname(default_path) if default_path else os.path.expanduser("~"),
            "PDF Files (*.pdf)",
        )
        if path:
            self._set_pdf_source(path, f"Custom: {os.path.basename(path)}")

    def _choose_default_pdf(self) -> None:
        if not self._default_pdf_path or not os.path.exists(self._default_pdf_path):
            QMessageBox.warning(
                self, "Missing PDF", "The default 5E sheet is not available."
            )
            return
        self._set_pdf_source(
            self._default_pdf_path,
            f"Default: {os.path.basename(self._default_pdf_path)}",
        )

    def _on_accept(self) -> None:
        name = self._name_input.text().strip()
        source_path = self._source_pdf_path
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter a sheet name.")
            return
        if not source_path:
            QMessageBox.warning(self, "Missing PDF", "Please select a PDF file.")
            return
        if not os.path.exists(source_path):
            QMessageBox.warning(
                self, "Missing PDF", "The selected PDF file does not exist."
            )
            return

        sheet_id = sanitize_filename(name)
        archive_path = character_sheet_archive_path(sheet_id)
        original_sheet_id = (
            sanitize_filename(self._original_entry.name)
            if self._original_entry is not None
            else ""
        )
        editing_same_sheet = bool(self._original_entry) and sheet_id == original_sheet_id
        if archive_path.exists() and not editing_same_sheet:
            if not self._confirm_overwrite(str(archive_path)):
                return

        self._entry = PlayerSheetEntry(
            name=name,
            pdf_path=source_path,
            archive_path=str(archive_path),
            world=_combo_optional_value(self._world_combo),
            campaign=_combo_optional_value(self._campaign_combo),
            group=_combo_optional_value(self._group_combo),
            tags=parse_tag_query(self._tags_input.text()),
            gold=self._original_entry.gold if self._original_entry else 0,
            silver=self._original_entry.silver if self._original_entry else 0,
            copper=self._original_entry.copper if self._original_entry else 0,
        )
        self.accept()

    def _confirm_overwrite(self, destination_path: str) -> bool:
        dialog = QDialog(self)
        dialog.setWindowTitle("Overwrite Character Sheet")
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        label = QLabel(
            "A sheet with this name already exists.\n"
            "Type CONFIRM to overwrite:\n"
            f"{destination_path}"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        input_field = QLineEdit()
        input_field.setPlaceholderText("Type CONFIRM to continue")
        layout.addWidget(input_field)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return False
        return input_field.text().strip() == "CONFIRM"

    def _set_pdf_source(self, path: Optional[str], label_text: str) -> None:
        self._source_pdf_path = path
        self._source_label.setText(label_text)

    def _on_world_changed(self) -> None:
        selected_campaign = self._update_campaigns()
        self._update_groups(campaign=selected_campaign)

    def _on_campaign_changed(self) -> None:
        self._update_groups()

    def _update_campaigns(self, current_value: Optional[str] = None) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        campaigns = list_campaigns(self._world_data, world)
        if current_value is None:
            current_value = _combo_optional_value(self._campaign_combo)
        selection = resolve_selection(campaigns, current_value)
        _populate_combo(self._campaign_combo, campaigns, selection)
        return selection

    def _update_groups(
        self, current_value: Optional[str] = None, campaign: Optional[str] = None
    ) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        if campaign is None:
            campaign = _combo_optional_value(self._campaign_combo)
        groups = list_groups(self._world_data, world, campaign)
        if current_value is None:
            current_value = _combo_optional_value(self._group_combo)
        selection = resolve_selection(groups, current_value)
        _populate_combo(self._group_combo, groups, selection)
        return selection


class InventoryItemPickerDialog(QDialog):
    def __init__(
        self,
        items: List[LootItem],
        icon_provider,
        preview_provider,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._items = items
        self._item_by_id = {item.item_id: item for item in items}
        self._icon_provider = icon_provider
        self._preview_provider = preview_provider
        self._preview_tooltip = LootPreviewTooltip()
        self._selected_item_id: Optional[str] = None

        self.setWindowTitle("Add Inventory Item")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        label = QLabel("Choose an item to add.")
        label.setObjectName("Subheader")
        layout.addWidget(label)

        search_height = QFontMetrics(self.font()).height() + 14
        self._search_container = QWidget(self)
        self._search_container.setFixedHeight(search_height)
        search_layout = QHBoxLayout(self._search_container)
        search_layout.setContentsMargins(8, 0, 8, 0)
        search_layout.setSpacing(6)

        self._search_input = QLineEdit(self._search_container)
        self._search_input.setPlaceholderText("Search items...")
        self._search_input.setFixedHeight(search_height)
        self._search_input.setStyleSheet("QLineEdit { padding: 6px 8px; }")
        self._search_input.textChanged.connect(self._filter_items)
        self._search_input.textChanged.connect(self._sync_search_clear)
        search_layout.addWidget(self._search_input, 1)

        self._search_clear_button = QToolButton(self._search_container)
        self._search_clear_button.setIcon(QIcon(os.path.join(ICON_DIR, "close.svg")))
        self._search_clear_button.setToolTip("Clear")
        self._search_clear_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._search_clear_button.setFixedSize(18, 18)
        self._search_clear_button.setIconSize(QSize(12, 12))
        self._search_clear_button.setStyleSheet(
            "QToolButton { padding: 0px; border: none; }"
        )
        self._search_clear_button.clicked.connect(self._search_input.clear)
        search_layout.addWidget(self._search_clear_button, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addWidget(self._search_container)

        self._list = QListWidget(self)
        self._list.setObjectName("InventoryPickerList")
        self._list.setViewMode(QListView.ViewMode.IconMode)
        self._list.setResizeMode(QListView.ResizeMode.Adjust)
        self._list.setMovement(QListView.Movement.Static)
        self._list.setWrapping(True)
        self._list.setSpacing(INVENTORY_GRID_SPACING)
        self._list.setIconSize(QSize(INVENTORY_ICON_SIZE, INVENTORY_ICON_SIZE))
        self._list.setGridSize(QSize(INVENTORY_ITEM_SIZE, INVENTORY_ITEM_SIZE))
        self._list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setItemDelegate(
            InventoryIconDelegate(
                INVENTORY_ICON_SIZE,
                INVENTORY_HIGHLIGHT_OUTSET,
                self._list,
            )
        )
        self._list.setMouseTracking(True)
        self._list.viewport().setMouseTracking(True)
        self._list.viewport().installEventFilter(self)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        self._list.itemDoubleClicked.connect(self._accept_current)
        self._list.setStyleSheet(
            "QListWidget#InventoryPickerList {"
            "background-color: #0d1117;"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
            "QListWidget#InventoryPickerList::item {"
            "padding: 0px;"
            "}"
            "QListWidget#InventoryPickerList::item:selected:active,"
            "QListWidget#InventoryPickerList::item:selected:!active {"
            "background-color: transparent;"
            "}"
        )

        for item in self._items:
            row = QListWidgetItem("")
            row.setData(Qt.ItemDataRole.UserRole, item.item_id)
            search_text = " ".join(
                [
                    item.title.lower(),
                    " ".join(sorted(item.tags)).lower(),
                    " ".join(sorted(item.categories)).lower(),
                    (item.category_label or "").lower(),
                ]
            ).strip()
            row.setData(Qt.ItemDataRole.UserRole + 1, search_text)
            icon_pixmap = self._icon_provider(item)
            row.setIcon(QIcon(icon_pixmap))
            row.setSizeHint(QSize(INVENTORY_ITEM_SIZE, INVENTORY_ITEM_SIZE))
            self._list.addItem(row)

        layout.addWidget(self._list, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add")
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)
        self._sync_buttons()
        self._sync_search_clear()
        self._filter_items(self._search_input.text())

    @property
    def selected_item_id(self) -> Optional[str]:
        return self._selected_item_id

    def _sync_buttons(self) -> None:
        ok_button = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is None:
            return
        ok_button.setEnabled(self._list.currentItem() is not None)

    def _sync_search_clear(self) -> None:
        text = self._search_input.text() if hasattr(self, "_search_input") else ""
        self._search_clear_button.setVisible(bool(text))

    def _accept_current(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        self._selected_item_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _on_accept(self) -> None:
        current = self._list.currentItem()
        if current is None:
            return
        self._selected_item_id = current.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _show_preview(self, item: QListWidgetItem) -> None:
        if item is None or self._preview_provider is None:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        loot_item = self._item_by_id.get(item_id)
        if loot_item is None:
            return
        global_pos = QCursor.pos()
        dpr = _screen_dpr_for_global_pos(global_pos, self)
        try:
            pixmap = self._preview_provider(
                loot_item,
                max_width=PREVIEW_TOOLTIP_WIDTH,
                max_height=None,
                dpr=dpr,
            )
        except TypeError:
            pixmap = self._preview_provider(loot_item)
        if pixmap is None:
            return
        self._preview_tooltip.show_preview(pixmap, global_pos)

    def _hide_preview(self) -> None:
        self._preview_tooltip.hide_preview()

    def _filter_items(self, text: str) -> None:
        query = text.strip().lower()
        parts = [part for part in query.split() if part]
        for index in range(self._list.count()):
            item = self._list.item(index)
            search_text = item.data(Qt.ItemDataRole.UserRole + 1) or ""
            if not parts:
                item.setHidden(False)
            else:
                item.setHidden(not all(part in search_text for part in parts))
        current = self._list.currentItem()
        if current is not None and current.isHidden():
            self._list.clearSelection()
        self._sync_buttons()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._list.viewport():
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint()
                item = self._list.itemAt(pos)
                if item is not None:
                    self._show_preview(item)
                else:
                    self._hide_preview()
            if event.type() == QEvent.Type.Leave:
                self._hide_preview()
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        self._hide_preview()
        super().closeEvent(event)


class InventoryIconDelegate(QStyledItemDelegate):
    def __init__(self, icon_size: int, highlight_pad: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._icon_size = icon_size
        self._highlight_outset = highlight_pad
        self._highlight_color = QColor("#58a6ff")

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = option.rect
        painter.fillRect(rect, Qt.GlobalColor.transparent)

        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            pixmap = icon.pixmap(self._icon_size, self._icon_size)
            x = rect.x() + (rect.width() - self._icon_size) // 2
            y = rect.y() + (rect.height() - self._icon_size) // 2
            icon_rect = QRect(x, y, self._icon_size, self._icon_size)
            painter.drawPixmap(x, y, pixmap)
            if option.state & QStyle.StateFlag.State_Selected:
                highlight_rect = icon_rect.adjusted(
                    -self._highlight_outset,
                    -self._highlight_outset,
                    self._highlight_outset,
                    self._highlight_outset,
                )
                pen = QPen(self._highlight_color)
                pen.setWidth(1)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(highlight_rect, 6, 6)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return QSize(INVENTORY_ITEM_SIZE, INVENTORY_ITEM_SIZE)


class CharacterSheetListDelegate(QStyledItemDelegate):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._line_spacing = 2
        self._vertical_padding = 8

    def _font_for_line(self, base_font: QFont, line_index: int) -> QFont:
        font = QFont(base_font)
        font.setBold(line_index == 0)
        return font

    def paint(self, painter: QPainter, option, index) -> None:
        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        text = str(item_option.text or "")
        item_option.text = ""

        style = item_option.widget.style() if item_option.widget else QApplication.style()
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            item_option,
            painter,
            item_option.widget,
        )

        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText,
            item_option,
            item_option.widget,
        )
        if not text_rect.isValid():
            text_rect = item_option.rect.adjusted(8, 4, -8, -4)

        lines = text.splitlines() if text else [""]
        if not lines:
            lines = [""]

        if item_option.state & QStyle.StateFlag.State_Selected:
            text_color = item_option.palette.color(item_option.palette.ColorRole.HighlightedText)
        else:
            text_color = item_option.palette.color(item_option.palette.ColorRole.Text)

        painter.save()
        painter.setPen(text_color)

        line_heights: list[int] = []
        line_metrics: list[QFontMetrics] = []
        line_fonts: list[QFont] = []
        for line_index, _line in enumerate(lines):
            line_font = self._font_for_line(item_option.font, line_index)
            metrics = QFontMetrics(line_font)
            line_fonts.append(line_font)
            line_metrics.append(metrics)
            line_heights.append(metrics.height())

        total_height = sum(line_heights) + self._line_spacing * max(0, len(lines) - 1)
        y = text_rect.top() + max(0, (text_rect.height() - total_height) // 2)

        for line_index, line in enumerate(lines):
            line_height = line_heights[line_index]
            metrics = line_metrics[line_index]
            line_font = line_fonts[line_index]
            line_rect = QRect(text_rect.left(), y, text_rect.width(), line_height)
            elided = metrics.elidedText(
                line,
                Qt.TextElideMode.ElideRight,
                line_rect.width(),
            )
            painter.setFont(line_font)
            painter.drawText(
                line_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided,
            )
            y += line_height + self._line_spacing

        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        item_option = QStyleOptionViewItem(option)
        self.initStyleOption(item_option, index)
        base_size = super().sizeHint(item_option, index)
        text = str(item_option.text or "")
        lines = text.splitlines() if text else [""]
        if not lines:
            lines = [""]

        total_height = 0
        for line_index, _line in enumerate(lines):
            metrics = QFontMetrics(self._font_for_line(item_option.font, line_index))
            total_height += metrics.height()
        total_height += self._line_spacing * max(0, len(lines) - 1)
        total_height += self._vertical_padding
        return QSize(base_size.width(), max(base_size.height(), total_height))


class InventoryListWidget(QListWidget):
    equipmentDropped = Signal(dict)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(False)
        self.viewport().setAcceptDrops(True)
        self._drag_start_pos = QPoint()

    def _start_drag_for_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        if not item_id:
            return
        payload = {
            "source": "backpack",
            "index": self.row(item),
            "item_id": item_id,
        }
        mime = QMimeData()
        mime.setData(INVENTORY_DRAG_MIME, _encode_inventory_drag(payload))
        drag = QDrag(self)
        drag.setMimeData(mime)
        icon = item.icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(INVENTORY_ICON_SIZE, INVENTORY_ICON_SIZE))
        drag.exec(Qt.DropAction.MoveAction)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            item = self.itemAt(self._drag_start_pos)
            if item is not None:
                self.setCurrentItem(item)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            return
        item = self.currentItem() or self.itemAt(self._drag_start_pos)
        if item is None:
            return
        self._start_drag_for_item(item)

    def dragEnterEvent(self, event) -> None:
        payload = _decode_inventory_drag(event.mimeData())
        if payload and payload.get("item_id"):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        payload = _decode_inventory_drag(event.mimeData())
        if payload and payload.get("item_id"):
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            return
        event.ignore()

    def dropEvent(self, event) -> None:
        payload = _decode_inventory_drag(event.mimeData())
        if payload and payload.get("source") == "equipment":
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()
            self.equipmentDropped.emit(payload)
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        event.accept()

    def viewportEvent(self, event) -> bool:
        if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            payload = _decode_inventory_drag(event.mimeData())
            if payload and payload.get("source") == "equipment":
                if event.type() == QEvent.Type.Drop:
                    self.equipmentDropped.emit(payload)
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return True
        return super().viewportEvent(event)

    def dropMimeData(self, index, data, action) -> bool:
        payload = _decode_inventory_drag(data)
        if payload and payload.get("source") == "equipment":
            self.equipmentDropped.emit(payload)
            return True
        return super().dropMimeData(index, data, action)


class EquipmentSlotWidget(QFrame):
    itemDropped = Signal(str, dict)
    slotSelected = Signal(str)
    itemHovered = Signal(str, object)

    def __init__(self, slot_id: str, label: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._slot_id = slot_id
        self._label = label
        self._item_id: Optional[str] = None
        self._pixmap: Optional[QPixmap] = None
        self._canvas_inset = 1
        self._selected = False
        self._drag_over = False
        self._drag_start_pos = QPoint()
        self.setObjectName("EquipmentSlot")
        self.setToolTip(label)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(EQUIPMENT_SLOT_SIZE, EQUIPMENT_SLOT_SIZE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._inner_frame = QFrame(self)
        self._inner_frame.setObjectName("TransparentContainer")
        self._inner_frame.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        inner_layout = QVBoxLayout(self._inner_frame)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._slot_canvas = QLabel(self._inner_frame)
        self._slot_canvas.setObjectName("EquipmentSlotIcon")
        self._slot_canvas.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._slot_canvas.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._slot_canvas.setScaledContents(False)
        self._slot_canvas.setStyleSheet("background-color: transparent;")
        inner_layout.addWidget(self._slot_canvas)
        layout.addWidget(self._inner_frame, 1, Qt.AlignmentFlag.AlignCenter)
        self.set_icon_size(EQUIPMENT_SLOT_SIZE)

    @property
    def slot_id(self) -> str:
        return self._slot_id

    @property
    def item_id(self) -> Optional[str]:
        return self._item_id

    def set_item(self, item_id: Optional[str], pixmap: Optional[QPixmap]) -> None:
        self._item_id = item_id
        self._pixmap = pixmap if item_id and pixmap is not None else None
        self.setToolTip("" if self._item_id else self._label)
        self._rebuild_slot_pixmap()

    def set_icon_size(self, size: int) -> None:
        safe = max(1, size)
        self._inner_frame.setFixedSize(safe, safe)
        # Keep a 1px inset so selection/drag border does not clip.
        label_size = max(1, safe - (self._canvas_inset * 2))
        self._slot_canvas.setFixedSize(label_size, label_size)
        self._rebuild_slot_pixmap()

    def set_canvas_inset(self, inset: int) -> None:
        safe = max(0, int(inset))
        if safe == self._canvas_inset:
            return
        self._canvas_inset = safe
        self.set_icon_size(self._inner_frame.width())

    def _slot_border_color(self) -> QColor:
        if self._drag_over:
            return QColor("#3fb950")
        if self._selected:
            return QColor("#58a6ff")
        return QColor("#30363d")

    def _rebuild_slot_pixmap(self) -> None:
        target = self._slot_canvas.size()
        if target.width() <= 0 or target.height() <= 0:
            self._slot_canvas.clear()
            return
        logical_size = min(target.width(), target.height())
        requested_dpr = max(1.0, float(self.devicePixelRatioF()))
        pixel_size, effective_dpr = _dpr_fitted_pixel_size(logical_size, requested_dpr)
        composed = QPixmap(pixel_size, pixel_size)
        composed.fill(Qt.GlobalColor.transparent)

        painter = QPainter(composed)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        base_alpha = 140 if self._selected else 89
        painter.fillRect(0, 0, pixel_size, pixel_size, QColor(13, 17, 23, base_alpha))

        background = _equipment_slot_background_pixmap(
            logical_size, dpr=requested_dpr, slot_id=self._slot_id
        )
        if not background.isNull():
            background_scaled = background.scaled(
                pixel_size,
                pixel_size,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(0, 0, background_scaled)

        if self._pixmap is not None and not self._pixmap.isNull():
            icon_scaled = self._pixmap.scaled(
                pixel_size,
                pixel_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            icon_x = (pixel_size - icon_scaled.width()) // 2
            icon_y = (pixel_size - icon_scaled.height()) // 2
            painter.drawPixmap(icon_x, icon_y, icon_scaled)

        border = self._slot_border_color()
        border_pen = QPen(border)
        border_pen.setWidth(1)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(0, 0, pixel_size - 1, pixel_size - 1)
        painter.end()

        composed.setDevicePixelRatio(effective_dpr)
        self._slot_canvas.setPixmap(composed)

    def set_selected(self, selected: bool) -> None:
        new_selected = bool(selected)
        if self._selected == new_selected:
            return
        self._selected = new_selected
        self.setProperty("selected", new_selected)
        self._rebuild_slot_pixmap()
        self.update()

    def _set_drag_over(self, active: bool) -> None:
        new_active = bool(active)
        if self._drag_over == new_active:
            return
        self._drag_over = new_active
        self.setProperty("dragover", new_active)
        self._rebuild_slot_pixmap()
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_slot_pixmap()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
            self.slotSelected.emit(self._slot_id)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            if self._item_id:
                self.itemHovered.emit(self._slot_id, self._item_id)
            super().mouseMoveEvent(event)
            return
        if not self._item_id:
            return
        distance = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if distance < QApplication.startDragDistance():
            return
        payload = {
            "source": "equipment",
            "slot": self._slot_id,
            "item_id": self._item_id,
        }
        mime = QMimeData()
        mime.setData(INVENTORY_DRAG_MIME, _encode_inventory_drag(payload))
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = self._slot_canvas.pixmap()
        if pixmap is not None:
            drag.setPixmap(pixmap)
        drag.exec(Qt.DropAction.MoveAction)

    def enterEvent(self, event) -> None:
        if self._item_id:
            self.itemHovered.emit(self._slot_id, self._item_id)
        else:
            self.itemHovered.emit(self._slot_id, None)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.itemHovered.emit(self._slot_id, None)
        super().leaveEvent(event)

    def dragEnterEvent(self, event) -> None:
        payload = _decode_inventory_drag(event.mimeData())
        if not payload or not payload.get("item_id"):
            event.ignore()
            return
        if payload.get("source") == "equipment" and payload.get("slot") == self._slot_id:
            event.ignore()
            return
        event.acceptProposedAction()
        self._set_drag_over(True)

    def dragMoveEvent(self, event) -> None:
        payload = _decode_inventory_drag(event.mimeData())
        if payload and payload.get("item_id"):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        payload = _decode_inventory_drag(event.mimeData())
        if not payload or not payload.get("item_id"):
            event.ignore()
            return
        event.acceptProposedAction()
        self._set_drag_over(False)
        self.itemDropped.emit(self._slot_id, payload)

class PlayerSheetsWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._world_data = load_navigation_data()
        self._storage_path = player_sheets_storage_path()
        self._manager = PlayerSheetsManager(entries=self._load_entries())
        self._current_entry: Optional[PlayerSheetEntry] = None
        self._initial_pdf_loaded = False
        self._pending_switch_item: Optional[QListWidgetItem] = None
        self._selection_guard = False
        self._syncing_currency = False
        self._inventory_item_library: List[LootItem] = []
        self._inventory_item_by_id: dict[str, LootItem] = {}
        self._inventory_icon_cache: dict[str, QPixmap] = {}
        self._equipment_icon_cache: dict[str, QPixmap] = {}
        self._inventory_preview_cache: dict[tuple[str, int, int, int], QPixmap] = {}
        self._inventory_preview_tooltip = LootPreviewTooltip()
        self._inventory_preview_item_id: Optional[str] = None
        self._inventory_preview_top_left: Optional[QPoint] = None
        self._inventory_stack: Optional[QStackedWidget] = None
        self._inventory_panel_min_height_lock = 0
        self._equipment_panel: Optional[QWidget] = None
        self._equipment_left_container: Optional[QWidget] = None
        self._equipment_right_container: Optional[QWidget] = None
        self._equipment_figure_frame: Optional[QFrame] = None
        self._equipment_figure_label: Optional[QLabel] = None
        self._equipment_figure_source_pixmap: Optional[QPixmap] = None
        self._equipment_weapon_strip: Optional[QWidget] = None
        self._equipment_row_separator: Optional[QFrame] = None
        self._equipment_misc_row_container: Optional[QWidget] = None
        self._equipment_misc_row_layout: Optional[QHBoxLayout] = None
        self._equipment_slot_widgets: dict[str, EquipmentSlotWidget] = {}
        self._equipment_weapon_slot_ids = [slot_id for slot_id, _ in EQUIPMENT_SLOTS_WEAPONS]
        self._equipment_misc_row_slot_ids = [slot_id for slot_id, _ in EQUIPMENT_SLOTS_MISC]
        self._equipment_selected_slot_id: Optional[str] = None
        self._equipment_preview_tooltip = LootPreviewTooltip()
        self._equipment_preview_slot_id: Optional[str] = None
        self._equipment_preview_item_id: Optional[str] = None
        self._equipment_preview_top_left: Optional[QPoint] = None
        self._inventory_backpack_button: Optional[QToolButton] = None
        self._inventory_equipment_button: Optional[QToolButton] = None
        self._inventory_notes_row: Optional[QWidget] = None
        self._inventory_notepad: Optional[QTextEdit] = None
        self._syncing_inventory_notes = False
        self._header_name_text = "Character: None"
        self._sheet_unsaved = False
        self._sheet_expanded = False
        self._detail_splitter: Optional[QSplitter] = None
        self._details_panel: Optional[QFrame] = None
        self._details_placeholder: Optional[QWidget] = None
        self._detail_splitter_index: Optional[int] = None
        self._detail_splitter_sizes: Optional[list[int]] = None
        self._detail_splitter_ratio: Optional[float] = DETAIL_SPLITTER_PRIMARY_RATIO
        self._expand_anim: Optional[QPropertyAnimation] = None
        self._blur_effect: Optional[QGraphicsBlurEffect] = None
        self._blur_anim: Optional[QPropertyAnimation] = None
        self._expanded_margin = 0
        self._expanded_blur_radius = 12.0
        self._collapsed_rect: Optional[QRect] = None
        self._detail_splitter_attached = False
        self._right_layout: Optional[QVBoxLayout] = None

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self._content_root = QWidget(self)
        content_layout = QVBoxLayout(self._content_root)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        self._overlay_root = QWidget(self)
        self._overlay_root.setObjectName("SheetExpandOverlay")
        self._overlay_root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._overlay_root.setStyleSheet("background-color: transparent;")
        self._overlay_root.setVisible(False)

        self._stack.addWidget(self._content_root)
        self._stack.addWidget(self._overlay_root)

        filter_bar = QFrame(self)
        filter_bar.setObjectName("Panel")
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(10)

        self._world_combo = QComboBox()
        self._campaign_combo = QComboBox()
        self._group_combo = QComboBox()
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Tags: healer, elf")

        self._reset_world_button = self._make_reset_button("Reset World")
        self._reset_world_button.clicked.connect(self._reset_world_filter)

        self._reset_campaign_button = self._make_reset_button("Reset Campaign")
        self._reset_campaign_button.clicked.connect(self._reset_campaign_filter)

        self._reset_group_button = self._make_reset_button("Reset Group")
        self._reset_group_button.clicked.connect(self._reset_group_filter)

        self._reset_tags_button = self._make_reset_button("Reset Tags")
        self._reset_tags_button.clicked.connect(self._reset_tags_filter)

        filter_layout.addWidget(
            self._build_filter_field("World", self._world_combo, self._reset_world_button),
            1,
        )
        filter_layout.addWidget(
            self._build_filter_field(
                "Campaign", self._campaign_combo, self._reset_campaign_button
            ),
            1,
        )
        filter_layout.addWidget(
            self._build_filter_field("Group", self._group_combo, self._reset_group_button),
            1,
        )
        filter_layout.addWidget(
            self._build_filter_field("Tags", self._tag_input, self._reset_tags_button),
            1,
        )

        self._new_button = QPushButton("New")
        self._new_button.setObjectName("PrimaryButton")
        self._new_button.setProperty("compact", True)
        self._new_button.setFixedSize(48, 48)
        self._new_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._new_button.setStyleSheet(
            "QPushButton#PrimaryButton {"
            "padding: 6px;"
            "min-width: 48px;"
            "max-width: 48px;"
            "min-height: 48px;"
            "max-height: 48px;"
            "border-radius: 8px;"
            "}"
        )
        self._new_button.clicked.connect(self._open_new_sheet_dialog)
        filter_layout.addWidget(self._new_button, 0, Qt.AlignmentFlag.AlignTop)

        content_layout.addWidget(filter_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        list_panel = QFrame(self)
        list_panel.setObjectName("Panel")
        list_panel.setMinimumWidth(300)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(10, 10, 10, 10)
        list_layout.setSpacing(8)

        list_title = QLabel("Characters")
        list_title.setObjectName("PanelTitle")
        list_layout.addWidget(list_title)

        self._sheet_list = QListWidget()
        self._sheet_list.setObjectName("NavList")
        self._sheet_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sheet_list.setItemDelegate(CharacterSheetListDelegate(self._sheet_list))
        self._sheet_list.currentItemChanged.connect(self._on_sheet_selected)
        list_layout.addWidget(self._sheet_list, 1)

        splitter.addWidget(list_panel)

        save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        save_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        save_shortcut.activated.connect(self._save_current_sheet)

        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        self._right_layout = right_layout
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        header_panel = QFrame(self)
        header_panel.setObjectName("Panel")
        header_layout = QHBoxLayout(header_panel)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._header_title_container = QWidget(header_panel)
        self._header_title_stack = QStackedLayout(self._header_title_container)
        self._header_title_stack.setContentsMargins(0, 0, 0, 0)

        self._header_name = QLabel(self._header_name_text)
        self._header_name.setObjectName("PanelTitle")
        self._header_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._header_name_center = QLabel(self._header_name_text)
        self._header_name_center.setObjectName("PanelTitle")
        self._header_name_center.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )

        self._header_title_stack.addWidget(self._header_name)
        self._header_title_stack.addWidget(self._header_name_center)
        self._header_title_stack.setCurrentWidget(self._header_name)
        header_layout.addWidget(self._header_title_container, 1)

        self._open_pdf_button = QToolButton()
        self._open_pdf_button.setObjectName("PrimaryButton")
        self._open_pdf_button.setIcon(QIcon(os.path.join(ICON_DIR, "external_link.svg")))
        self._open_pdf_button.setToolTip("Open PDF externally")
        self._open_pdf_button.clicked.connect(self._open_pdf)

        self._edit_button = QToolButton()
        self._edit_button.setObjectName("SecondaryButton")
        self._edit_button.setIcon(QIcon(os.path.join(ICON_DIR, "edit.svg")))
        self._edit_button.setToolTip("Edit Character Settings")
        self._edit_button.clicked.connect(self._open_edit_sheet_dialog)

        self._save_button = QToolButton()
        self._save_button.setObjectName("SecondaryButton")
        self._save_button.setIcon(QIcon(os.path.join(ICON_DIR, "save.svg")))
        self._save_button.setToolTip("Save")
        self._save_button.clicked.connect(self._save_current_sheet)

        self._delete_button = QToolButton()
        self._delete_button.setObjectName("DestructiveButton")
        self._delete_button.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
        self._delete_button.setToolTip("Delete to Trash")
        self._delete_button.clicked.connect(self._delete_current_sheet)

        self._disintegrate_button = QToolButton()
        self._disintegrate_button.setObjectName("DestructiveButton")
        self._disintegrate_button.setIcon(QIcon(os.path.join(ICON_DIR, "disintegrate.svg")))
        self._disintegrate_button.setToolTip("Permanently Delete")
        self._disintegrate_button.clicked.connect(self._disintegrate_current_sheet)

        for button in (
            self._open_pdf_button,
            self._edit_button,
            self._save_button,
            self._delete_button,
            self._disintegrate_button,
        ):
            button.setFixedSize(36, 36)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setStyleSheet("""
                QToolButton {
                    padding: 4px; 
                    border-radius: 6px; 
                    margin: 0px; 
                    min-width: 26px; 
                    max-width: 26px; 
                    min-height: 26px; 
                    max-height: 26px;
                }
            """)
            button.setIconSize(QSize(20, 20))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            header_layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)

        right_layout.addWidget(header_panel)

        self._detail_splitter = QSplitter(Qt.Orientation.Horizontal, right_container)
        detail_splitter = self._detail_splitter
        detail_splitter.setChildrenCollapsible(False)
        detail_splitter.setHandleWidth(10)

        self._details_panel = QFrame(self)
        details_panel = self._details_panel
        details_panel.setObjectName("PanelTransparent")
        details_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(10, 10, 10, 10)
        details_layout.setSpacing(8)

        self._sheet_panel: Optional[CharacterSheetPanel] = None
        if PDFIUM_VIEW_AVAILABLE:
            self._sheet_panel = CharacterSheetPanel(self)
            self._sheet_panel.unsavedChanged.connect(self._on_sheet_unsaved_changed)
            self._sheet_panel.statusMessage.connect(self._show_sheet_status)
            self._sheet_panel.pdfPathSelected.connect(self._on_sheet_pdf_selected)
            self._sheet_panel.expandToggled.connect(self._on_sheet_expand_toggled)
            details_layout.addWidget(self._sheet_panel, 1)
        else:
            message = "PDF viewer requires pypdfium2. Install it to enable in-app edits."
            if PDFIUM_VIEW_ERROR:
                message = f"{message}\n\nImport error: {PDFIUM_VIEW_ERROR}"
            hint = QLabel(message)
            hint.setObjectName("PanelPlaceholder")
            hint.setWordWrap(True)
            details_layout.addWidget(hint)
        detail_splitter.addWidget(details_panel)

        inventory_panel = QFrame(self)
        inventory_panel.setObjectName("Panel")
        inventory_panel.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        inventory_layout = QVBoxLayout(inventory_panel)
        inventory_layout.setContentsMargins(10, 10, 10, 10)
        inventory_layout.setSpacing(8)

        inventory_header = QWidget(inventory_panel)
        self._inventory_header = inventory_header
        inventory_header.setObjectName("TransparentContainer")
        inventory_header.setFixedHeight(48)
        inventory_header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        inventory_header_layout = QHBoxLayout(inventory_header)
        inventory_header_layout.setContentsMargins(0, 0, 0, 0)
        inventory_header_layout.setSpacing(8)
        inventory_header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._inventory_title = QLabel("Inventory")
        self._inventory_title.setObjectName("PanelTitle")
        inventory_header_layout.addWidget(self._inventory_title, 1)

        toggle_container = QWidget(inventory_panel)
        toggle_container.setObjectName("TransparentContainer")
        inventory_control_height = 42
        toggle_container.setFixedHeight(inventory_control_height)
        toggle_container.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(0, 0, 0, 0)
        toggle_layout.setSpacing(6)
        toggle_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._inventory_backpack_button = QToolButton(toggle_container)
        self._inventory_backpack_button.setObjectName("InventoryToggleButton")
        self._inventory_backpack_button.setText("Backpack")
        self._inventory_backpack_button.setCheckable(True)
        self._inventory_backpack_button.setChecked(True)
        self._inventory_backpack_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inventory_backpack_button.setFixedHeight(inventory_control_height)
        self._inventory_backpack_button.setMinimumWidth(92)
        self._inventory_backpack_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._inventory_backpack_button.setStyleSheet(
            "QToolButton#InventoryToggleButton {"
            "padding: 0px 10px;"
            "margin: 0px;"
            "min-height: 40px;"
            "max-height: 40px;"
            "}"
        )

        self._inventory_equipment_button = QToolButton(toggle_container)
        self._inventory_equipment_button.setObjectName("InventoryToggleButton")
        self._inventory_equipment_button.setText("Equipment")
        self._inventory_equipment_button.setCheckable(True)
        self._inventory_equipment_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inventory_equipment_button.setFixedHeight(inventory_control_height)
        self._inventory_equipment_button.setMinimumWidth(92)
        self._inventory_equipment_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._inventory_equipment_button.setStyleSheet(
            "QToolButton#InventoryToggleButton {"
            "padding: 0px 10px;"
            "margin: 0px;"
            "min-height: 40px;"
            "max-height: 40px;"
            "}"
        )

        toggle_group = QButtonGroup(self)
        toggle_group.setExclusive(True)
        toggle_group.addButton(self._inventory_backpack_button)
        toggle_group.addButton(self._inventory_equipment_button)

        toggle_layout.addWidget(self._inventory_backpack_button)
        toggle_layout.addWidget(self._inventory_equipment_button)
        inventory_header_layout.addWidget(toggle_container)

        self._inventory_add_button = QToolButton(inventory_panel)
        self._inventory_add_button.setObjectName("PrimaryButton")
        self._inventory_add_button.setIcon(QIcon(os.path.join(ICON_DIR, "plus.svg")))
        self._inventory_add_button.setToolTip("Add inventory item")
        self._inventory_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inventory_add_button.setFixedSize(inventory_control_height, inventory_control_height)
        self._inventory_add_button.setIconSize(QSize(18, 18))
        self._inventory_add_button.setStyleSheet(
            "QToolButton#PrimaryButton {"
            "padding: 4px;"
            "border-radius: 6px;"
            "margin: 0px;"
            "}"
        )
        self._inventory_add_button.clicked.connect(self._open_inventory_picker)
        inventory_header_layout.addWidget(self._inventory_add_button)

        self._inventory_remove_button = QToolButton(inventory_panel)
        self._inventory_remove_button.setObjectName("DestructiveButton")
        self._inventory_remove_button.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
        self._inventory_remove_button.setToolTip("Remove selected item")
        self._inventory_remove_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._inventory_remove_button.setFixedSize(inventory_control_height, inventory_control_height)
        self._inventory_remove_button.setIconSize(QSize(18, 18))
        self._inventory_remove_button.setStyleSheet(
            "QToolButton#DestructiveButton {"
            "padding: 4px;"
            "border-radius: 6px;"
            "margin: 0px;"
            "}"
        )
        self._inventory_remove_button.clicked.connect(self._remove_inventory_item)
        inventory_header_layout.addWidget(self._inventory_remove_button)

        self._inventory_backpack_button.raise_()
        self._inventory_equipment_button.raise_()
        self._inventory_add_button.raise_()
        self._inventory_remove_button.raise_()

        inventory_layout.addWidget(inventory_header)

        currency_row = QWidget(inventory_panel)
        self._currency_row = currency_row
        currency_layout = QHBoxLayout(currency_row)
        currency_layout.setContentsMargins(0, 0, 0, 0)
        currency_layout.setSpacing(10)
        currency_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        currency_font = self._inventory_title.font()
        currency_font.setPointSize(12)
        currency_metrics = QFontMetrics(currency_font)
        currency_icon_size = currency_metrics.height()
        currency_field_width = currency_metrics.horizontalAdvance("10,000,000") + 16

        def _make_currency_field(label_text: str, color: QColor) -> tuple[QWidget, QSpinBox]:
            container = QWidget(currency_row)
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.setSpacing(6)

            icon_label = QLabel(container)
            icon_label.setPixmap(_currency_icon_pixmap(color, currency_icon_size))
            icon_label.setFixedSize(currency_icon_size, currency_icon_size)
            icon_label.setStyleSheet("background-color: transparent;")

            label = QLabel(label_text, container)
            label.setFont(currency_font)
            label.setStyleSheet("background-color: transparent; color: #e6edf3;")

            field = QSpinBox(container)
            field.setRange(0, 10_000_000)
            field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            field.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            field.setFixedWidth(currency_field_width)
            field.setObjectName("CurrencyField")

            container_layout.addWidget(icon_label)
            container_layout.addWidget(label)
            container_layout.addWidget(field)
            return container, field

        gold_container, self._gold_spin = _make_currency_field(
            "Gold", QColor("#c9a13a")
        )
        silver_container, self._silver_spin = _make_currency_field(
            "Silver", QColor("#aeb4c2")
        )
        copper_container, self._copper_spin = _make_currency_field(
            "Copper", QColor("#b87333")
        )

        currency_layout.addWidget(gold_container)
        currency_layout.addWidget(silver_container)
        currency_layout.addWidget(copper_container)
        currency_layout.addStretch(1)

        self._gold_spin.valueChanged.connect(
            lambda value: self._on_currency_changed("gold", value)
        )
        self._silver_spin.valueChanged.connect(
            lambda value: self._on_currency_changed("silver", value)
        )
        self._copper_spin.valueChanged.connect(
            lambda value: self._on_currency_changed("copper", value)
        )

        inventory_layout.addWidget(currency_row)

        self._inventory_panel = inventory_panel
        self._inventory_panel.setAcceptDrops(True)
        self._inventory_stack = QStackedWidget(inventory_panel)
        self._inventory_stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        inventory_layout.addWidget(self._inventory_stack, 1)

        backpack_container = QWidget(self._inventory_stack)
        backpack_container.setObjectName("TransparentContainer")
        backpack_layout = QVBoxLayout(backpack_container)
        backpack_layout.setContentsMargins(0, 0, 0, 0)
        backpack_layout.setSpacing(0)

        self._inventory_list = InventoryListWidget(backpack_container)
        self._inventory_list.setObjectName("InventoryIconList")
        self._inventory_list.setViewMode(QListView.ViewMode.IconMode)
        self._inventory_list.setResizeMode(QListView.ResizeMode.Adjust)
        self._inventory_list.setMovement(QListView.Movement.Static)
        self._inventory_list.setWrapping(True)
        self._inventory_list.setSpacing(INVENTORY_GRID_SPACING)
        self._inventory_list.setIconSize(QSize(INVENTORY_ICON_SIZE, INVENTORY_ICON_SIZE))
        self._inventory_list.setGridSize(QSize(INVENTORY_ITEM_SIZE, INVENTORY_ITEM_SIZE))
        self._inventory_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._inventory_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._inventory_list.setItemDelegate(
            InventoryIconDelegate(
                INVENTORY_ICON_SIZE,
                INVENTORY_HIGHLIGHT_OUTSET,
                self._inventory_list,
            )
        )
        self._inventory_list.setMouseTracking(True)
        self._inventory_list.viewport().setMouseTracking(True)
        self._inventory_list.viewport().setAcceptDrops(True)
        self._inventory_list.viewport().installEventFilter(self)
        self._inventory_list.itemSelectionChanged.connect(self._sync_inventory_controls)
        self._inventory_list.equipmentDropped.connect(self._on_inventory_drop_from_equipment)
        self._inventory_list.setStyleSheet(
            "QListWidget#InventoryIconList {"
            "background-color: transparent;"
            "border: none;"
            "}"
            "QListWidget#InventoryIconList::item {"
            "padding: 0px;"
            "}"
            "QListWidget#InventoryIconList::item:selected:active,"
            "QListWidget#InventoryIconList::item:selected:!active {"
            "background-color: transparent;"
            "}"
        )
        backpack_layout.addWidget(self._inventory_list, 1)

        self._inventory_placeholder = QLabel("No inventory items yet.")
        self._inventory_placeholder.setObjectName("PanelPlaceholder")
        self._inventory_placeholder.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._inventory_placeholder.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self._inventory_placeholder.setParent(self._inventory_list.viewport())
        self._inventory_placeholder.setVisible(False)

        self._inventory_stack.addWidget(backpack_container)

        self._equipment_panel = QWidget(self._inventory_stack)
        self._equipment_panel.setObjectName("EquipmentPanel")
        equipment_layout = QVBoxLayout(self._equipment_panel)
        equipment_layout.setContentsMargins(0, 0, 0, 0)
        equipment_layout.setSpacing(0)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)

        equipment_left_container = QWidget(self._equipment_panel)
        self._equipment_left_container = equipment_left_container
        equipment_left_container.setObjectName("TransparentContainer")
        equipment_left_layout = QVBoxLayout(equipment_left_container)
        equipment_left_layout.setContentsMargins(0, 4, 0, 4)
        equipment_left_layout.setSpacing(10)
        equipment_left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for slot_id, label in EQUIPMENT_SLOTS_LEFT:
            slot = EquipmentSlotWidget(slot_id, label, equipment_left_container)
            slot.slotSelected.connect(self._on_equipment_slot_selected)
            slot.itemDropped.connect(self._on_equipment_slot_dropped)
            slot.itemHovered.connect(self._on_equipment_slot_hovered)
            self._equipment_slot_widgets[slot_id] = slot
            equipment_left_layout.addWidget(slot, 0, Qt.AlignmentFlag.AlignHCenter)

        equipment_right_container = QWidget(self._equipment_panel)
        self._equipment_right_container = equipment_right_container
        equipment_right_container.setObjectName("TransparentContainer")
        equipment_right_layout = QVBoxLayout(equipment_right_container)
        equipment_right_layout.setContentsMargins(0, 4, 0, 4)
        equipment_right_layout.setSpacing(10)
        equipment_right_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        for slot_id, label in EQUIPMENT_SLOTS_RIGHT:
            slot = EquipmentSlotWidget(slot_id, label, equipment_right_container)
            slot.slotSelected.connect(self._on_equipment_slot_selected)
            slot.itemDropped.connect(self._on_equipment_slot_dropped)
            slot.itemHovered.connect(self._on_equipment_slot_hovered)
            self._equipment_slot_widgets[slot_id] = slot
            equipment_right_layout.addWidget(slot, 0, Qt.AlignmentFlag.AlignHCenter)

        figure_frame = QFrame(self._equipment_panel)
        self._equipment_figure_frame = figure_frame
        figure_frame.setObjectName("EquipmentFigureFrame")
        figure_frame.setMinimumSize(EQUIPMENT_SLOT_SIZE, EQUIPMENT_SLOT_SIZE * 2)
        figure_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        figure_layout = QVBoxLayout(figure_frame)
        figure_layout.setContentsMargins(0, 4, 0, 4)
        figure_layout.setSpacing(0)

        silhouette_container = QWidget(figure_frame)
        silhouette_container.setObjectName("TransparentContainer")
        silhouette_layout = QVBoxLayout(silhouette_container)
        silhouette_layout.setContentsMargins(12, 12, 12, 8)
        silhouette_layout.setSpacing(0)
        figure_label = QLabel(silhouette_container)
        self._equipment_figure_label = figure_label
        figure_label.setObjectName("EquipmentFigure")
        figure_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        figure_label.setStyleSheet("background-color: transparent;")
        figure_label.setScaledContents(False)
        figure_label.installEventFilter(self)
        figure_pixmap = _equipment_silhouette_pixmap()
        self._equipment_figure_source_pixmap = figure_pixmap if not figure_pixmap.isNull() else None
        if not figure_pixmap.isNull():
            self._update_equipment_figure_pixmap()
        silhouette_layout.addWidget(figure_label, 1)
        figure_layout.addWidget(silhouette_container, 1)

        weapon_strip = QWidget(figure_frame)
        self._equipment_weapon_strip = weapon_strip
        weapon_strip.setObjectName("TransparentContainer")
        weapon_row = QHBoxLayout(weapon_strip)
        weapon_row.setContentsMargins(0, 0, 0, 0)
        weapon_row.setSpacing(12)
        weapon_row.addStretch(1)
        for slot_id, label in EQUIPMENT_SLOTS_WEAPONS:
            slot = EquipmentSlotWidget(slot_id, label, weapon_strip)
            slot.slotSelected.connect(self._on_equipment_slot_selected)
            slot.itemDropped.connect(self._on_equipment_slot_dropped)
            slot.itemHovered.connect(self._on_equipment_slot_hovered)
            self._equipment_slot_widgets[slot_id] = slot
            weapon_row.addWidget(slot)
        weapon_row.addStretch(1)
        figure_layout.addWidget(weapon_strip, 0, Qt.AlignmentFlag.AlignBottom)

        top_row.addWidget(equipment_left_container, 0, Qt.AlignmentFlag.AlignTop)
        top_row.addWidget(figure_frame, 1)
        top_row.addWidget(equipment_right_container, 0, Qt.AlignmentFlag.AlignTop)
        equipment_layout.addLayout(top_row)
        equipment_layout.addSpacing(22)

        separator = QFrame(self._equipment_panel)
        separator.setObjectName("EquipmentRowSeparator")
        separator.setFixedHeight(1)
        separator.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        separator.setStyleSheet(
            "QFrame#EquipmentRowSeparator {"
            "background-color: rgba(139, 148, 158, 0.32);"
            "border: none;"
            "}"
        )
        self._equipment_row_separator = separator
        equipment_layout.addWidget(separator)
        equipment_layout.addSpacing(1)

        misc_row_container = QWidget(self._equipment_panel)
        misc_row_container.setObjectName("TransparentContainer")
        misc_row_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._equipment_misc_row_container = misc_row_container
        misc_row_container_layout = QVBoxLayout(misc_row_container)
        misc_row_container_layout.setContentsMargins(0, 0, 0, 0)
        misc_row_container_layout.setSpacing(0)
        misc_row_container_layout.addStretch(1)

        misc_row = QHBoxLayout()
        misc_row.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        misc_row.setSpacing(8)
        misc_row.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._equipment_misc_row_layout = misc_row
        for slot_id, label in EQUIPMENT_SLOTS_MISC:
            slot = EquipmentSlotWidget(slot_id, label, self._equipment_panel)
            slot.slotSelected.connect(self._on_equipment_slot_selected)
            slot.itemDropped.connect(self._on_equipment_slot_dropped)
            slot.itemHovered.connect(self._on_equipment_slot_hovered)
            self._equipment_slot_widgets[slot_id] = slot
            misc_row.addWidget(slot)
        misc_row_container_layout.addLayout(misc_row)
        misc_row_container_layout.addStretch(1)
        equipment_layout.addWidget(misc_row_container, 1)

        self._inventory_stack.addWidget(self._equipment_panel)

        notes_row = QWidget(inventory_panel)
        notes_row.setObjectName("TransparentContainer")
        notes_row_layout = QVBoxLayout(notes_row)
        notes_row_layout.setContentsMargins(0, 4, 0, 0)
        notes_row_layout.setSpacing(4)
        notes_label = QLabel("Notepad", notes_row)
        notes_label.setObjectName("Subheader")
        notes_row_layout.addWidget(notes_label, 0)
        self._inventory_notepad = QTextEdit(notes_row)
        self._inventory_notepad.setPlaceholderText(
            "Write custom items here to add later."
        )
        self._inventory_notepad.setFixedHeight(168)
        self._inventory_notepad.textChanged.connect(self._on_inventory_notepad_changed)
        notes_row_layout.addWidget(self._inventory_notepad, 1)
        notes_size_policy = notes_row.sizePolicy()
        notes_size_policy.setRetainSizeWhenHidden(False)
        notes_row.setSizePolicy(notes_size_policy)
        self._inventory_notes_row = notes_row
        inventory_layout.addWidget(notes_row, 0)

        if self._inventory_backpack_button and self._inventory_equipment_button:
            self._inventory_backpack_button.clicked.connect(
                lambda: self._set_inventory_view("backpack")
            )
            self._inventory_equipment_button.clicked.connect(
                lambda: self._set_inventory_view("equipment")
            )
            self._inventory_backpack_button.setAcceptDrops(True)
            self._inventory_equipment_button.setAcceptDrops(True)
            self._inventory_backpack_button.installEventFilter(self)
            self._inventory_equipment_button.installEventFilter(self)

        self._inventory_stack.setCurrentIndex(0)
        self._sync_inventory_notepad_visibility()

        inventory_panel.installEventFilter(self)
        inventory_header.installEventFilter(self)
        currency_row.installEventFilter(self)
        if self._equipment_panel is not None:
            self._equipment_panel.installEventFilter(self)

        detail_splitter.addWidget(inventory_panel)
        detail_splitter.setStretchFactor(0, 3)
        detail_splitter.setStretchFactor(1, 1)
        detail_splitter.setSizes([3, 1])
        QTimer.singleShot(0, self._attach_detail_splitter)

        splitter.addWidget(right_container)
        # Character Sheets list starts 25% narrower to leave more room for detail panels.
        splitter.setSizes([240, 960])

        content_layout.addWidget(splitter, 1)

        self._blur_effect = QGraphicsBlurEffect(self._content_root)
        self._blur_effect.setBlurRadius(0.0)
        self._content_root.setGraphicsEffect(self._blur_effect)
        self._blur_anim = QPropertyAnimation(self._blur_effect, b"blurRadius", self)
        self._blur_anim.setDuration(260)
        self._blur_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        if self._details_panel is not None:
            self._expand_anim = QPropertyAnimation(self._details_panel, b"geometry", self)
            self._expand_anim.setDuration(260)
            self._expand_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._expand_anim.finished.connect(self._on_expand_anim_finished)

        _populate_combo(self._world_combo, list_worlds(self._world_data))
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)

        self._world_combo.currentIndexChanged.connect(self._on_world_changed)
        self._campaign_combo.currentIndexChanged.connect(self._on_campaign_changed)
        self._group_combo.currentIndexChanged.connect(self._apply_filters)
        self._tag_input.textChanged.connect(self._apply_filters)

        self._refresh_inventory_library()
        self._apply_filters()
        PLAYER_SHEET_EVENTS.inventorySaved.connect(self._on_external_inventory_saved)

    def _make_reset_button(self, tooltip: str) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("InlineResetButton")
        btn.setIcon(QIcon(RESET_ICON))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _attach_detail_splitter(self) -> None:
        if self._detail_splitter_attached or self._detail_splitter is None:
            return
        if self._right_layout is None:
            return
        self._right_layout.addWidget(self._detail_splitter, 1)
        self._detail_splitter_attached = True
        self._apply_fixed_detail_splitter_ratio()
        self._schedule_splitter_restore()

    def _build_filter_field(
        self,
        label_text: str,
        widget: QWidget,
        reset_button: Optional[QToolButton] = None,
    ) -> QWidget:
        container = QWidget(self)
        container.setObjectName("FilterFieldContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        label = QLabel(label_text)
        label.setObjectName("Subheader")
        layout.addWidget(label)
        row = QWidget(container)
        row.setObjectName("TransparentContainer")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
        row_layout.addWidget(widget, 1)
        if reset_button is not None:
            row_layout.addWidget(reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(row)
        return container

    def _seed_entries(self) -> List[PlayerSheetEntry]:
        return []

    def _load_entries(self) -> List[PlayerSheetEntry]:
        path = self._storage_path
        if not path.exists():
            return []
        entries = load_entries_from_storage()
        return entries

    def _save_entries(self) -> None:
        for entry in self._manager.entries:
            sync_entry_archive(entry)
        save_entries_to_storage(self._manager.entries)

    def _on_external_inventory_saved(self, sheet_id: str, inventory_payload: dict) -> None:
        target_sheet = str(sheet_id or "").strip()
        if not target_sheet:
            return
        target_entry: Optional[PlayerSheetEntry] = None
        for entry in self._manager.entries:
            if sheet_id_for_entry(entry) == target_sheet:
                target_entry = entry
                break
        if target_entry is None:
            return
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        target_entry.inventory = list(normalized.get("inventory", []))
        target_entry.inventory_notes = str(normalized.get("inventory_notes", ""))
        target_entry.equipment = _normalize_equipment(normalized.get("equipment", {}))
        try:
            target_entry.gold = max(0, int(normalized.get("gold", target_entry.gold)))
            target_entry.silver = max(0, int(normalized.get("silver", target_entry.silver)))
            target_entry.copper = max(0, int(normalized.get("copper", target_entry.copper)))
        except (TypeError, ValueError):
            pass
        if self._current_entry is target_entry:
            self._set_inventory(target_entry)

    def _on_world_changed(self) -> None:
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)
        self._apply_filters()

    def _on_campaign_changed(self) -> None:
        self._refresh_groups()
        self._apply_filters()

    def _refresh_campaigns(self, current_value: Optional[str] = None) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        campaigns = list_campaigns(self._world_data, world)
        if current_value is None:
            current_value = _combo_optional_value(self._campaign_combo)
        selection = resolve_selection(campaigns, current_value)
        _populate_combo(self._campaign_combo, campaigns, selection)
        return selection

    def _refresh_groups(
        self, current_value: Optional[str] = None, campaign: Optional[str] = None
    ) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        if campaign is None:
            campaign = _combo_optional_value(self._campaign_combo)
        groups = list_groups(self._world_data, world, campaign)
        if current_value is None:
            current_value = _combo_optional_value(self._group_combo)
        selection = resolve_selection(groups, current_value)
        _populate_combo(self._group_combo, groups, selection)
        return selection

    def _reset_world_filter(self) -> None:
        self._world_combo.setCurrentIndex(0)

    def _reset_campaign_filter(self) -> None:
        self._campaign_combo.setCurrentIndex(0)

    def _reset_group_filter(self) -> None:
        self._group_combo.setCurrentIndex(0)

    def _reset_tags_filter(self) -> None:
        self._tag_input.setText("")

    def _apply_filters(self) -> None:
        self._manager.set_filters(
            world=_combo_optional_value(self._world_combo),
            campaign=_combo_optional_value(self._campaign_combo),
            group=_combo_optional_value(self._group_combo),
            tag_query=self._tag_input.text().strip(),
        )
        entries = self._manager.filtered_entries()
        self._refresh_list(entries)

    def _refresh_list(self, entries: List[PlayerSheetEntry]) -> None:
        previous_entry = self._current_entry
        self._sheet_list.blockSignals(True)
        self._sheet_list.clear()
        selection_index = -1
        for index, entry in enumerate(entries):
            context_parts = [part for part in [entry.world, entry.campaign, entry.group] if part]
            context_line = " • ".join(context_parts) if context_parts else "Unassigned"
            tags_line = ", ".join(entry.tags) if entry.tags else "No tags"
            item_text = f"Character: {entry.name}\n{context_line}\n{tags_line}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._sheet_list.addItem(item)
            if entry is previous_entry:
                selection_index = index
        self._sheet_list.blockSignals(False)

        if entries:
            if selection_index == -1:
                selection_index = 0
            self._sheet_list.setCurrentRow(selection_index)
        else:
            self._set_details(None)

    def _set_details(self, entry: Optional[PlayerSheetEntry]) -> None:
        self._current_entry = entry
        self._set_unsaved_indicator(False)
        if not entry:
            self._set_header_name("Character: None")
            self._open_pdf_button.setEnabled(False)
            self._edit_button.setEnabled(False)
            self._save_button.setEnabled(False)
            self._load_pdf_preview(None)
            self._set_inventory(None)
            return

        self._set_header_name(f"Character: {entry.name}")
        self._open_pdf_button.setEnabled(bool(entry.pdf_path or entry.archive_path))
        self._edit_button.setEnabled(True)
        self._save_button.setEnabled(True)
        self._load_pdf_preview(entry)
        self._set_inventory(entry)

    def _refresh_selection_ui(self, entry: Optional[PlayerSheetEntry]) -> None:
        self._current_entry = entry
        if not entry:
            self._set_header_name("Character: None")
            self._open_pdf_button.setEnabled(False)
            self._edit_button.setEnabled(False)
            self._save_button.setEnabled(False)
            return
        self._set_header_name(f"Character: {entry.name}")
        self._open_pdf_button.setEnabled(bool(entry.pdf_path or entry.archive_path))
        self._edit_button.setEnabled(True)
        self._save_button.setEnabled(True)

    def _refresh_inventory_library(self) -> None:
        self._inventory_item_library, self._inventory_item_by_id = (
            _load_loot_item_library()
        )
        self._inventory_icon_cache.clear()
        self._equipment_icon_cache.clear()
        self._inventory_preview_cache.clear()

    def _inventory_item_for_id(self, item_id: str) -> Optional[LootItem]:
        return self._inventory_item_by_id.get(item_id)

    def _inventory_icon_for_item(self, item: Optional[LootItem]) -> QPixmap:
        if item is None:
            return _missing_inventory_icon_pixmap()
        cached = self._inventory_icon_cache.get(item.item_id)
        if cached is not None:
            return cached
        pixmap = _inventory_icon_pixmap(item)
        self._inventory_icon_cache[item.item_id] = pixmap
        return pixmap

    def _equipment_icon_for_item(self, item: Optional[LootItem]) -> QPixmap:
        # Keep equipment icon rendering consistent with backpack item icons.
        return self._inventory_icon_for_item(item)

    def _inventory_preview_pixmap(
        self,
        item: LootItem,
        *,
        max_width: int = PREVIEW_TOOLTIP_WIDTH,
        max_height: Optional[int] = None,
        dpr: Optional[float] = None,
    ) -> Optional[QPixmap]:
        safe_width = max(1, int(round(max_width)))
        safe_height = max_height if max_height is None else max(1, int(round(max_height)))
        safe_dpr = max(1.0, float(self.devicePixelRatioF() if dpr is None else dpr))
        cache_key = (
            item.item_id,
            safe_width,
            safe_height if safe_height is not None else 0,
            int(round(safe_dpr * 100.0)),
        )
        cached = self._inventory_preview_cache.get(cache_key)
        if cached is not None:
            return cached
        pixmap = _render_item_preview_pixmap(
            item,
            max_width=safe_width,
            max_height=safe_height,
            dpr=safe_dpr,
        )
        if pixmap is not None:
            self._inventory_preview_cache[cache_key] = pixmap
        return pixmap

    def _inventory_view(self) -> str:
        if self._inventory_stack is None:
            return "backpack"
        return "equipment" if self._inventory_stack.currentIndex() == 1 else "backpack"

    def _capture_inventory_ancestor_splitter_sizes(
        self,
    ) -> list[tuple[QSplitter, list[int]]]:
        snapshots: list[tuple[QSplitter, list[int]]] = []
        seen: set[int] = set()
        anchor = self._inventory_stack if self._inventory_stack is not None else self
        parent = anchor.parentWidget()
        while parent is not None:
            if isinstance(parent, QSplitter):
                splitter_id = id(parent)
                if splitter_id not in seen:
                    sizes = parent.sizes()
                    total = sum(max(0, int(size)) for size in sizes)
                    if total <= 0 or len(sizes) != parent.count():
                        parent = parent.parentWidget()
                        continue
                    seen.add(splitter_id)
                    snapshots.append((parent, sizes))
            parent = parent.parentWidget()
        return snapshots

    def _schedule_inventory_ancestor_splitter_restore(
        self, snapshots: list[tuple[QSplitter, list[int]]]
    ) -> None:
        if not snapshots:
            return
        # Restore immediately to avoid one-frame panel jumps while switching views.
        self._restore_inventory_ancestor_splitter_sizes(snapshots)

    def _restore_inventory_ancestor_splitter_sizes(
        self, snapshots: list[tuple[QSplitter, list[int]]]
    ) -> None:
        # Apply outer splitters first so child splitters can be restored with final widths.
        for splitter, sizes in reversed(snapshots):
            if splitter is None:
                continue
            if splitter.count() != len(sizes):
                continue
            splitter.setSizes(sizes)

    def _finalize_equipment_view_switch(
        self, snapshots: list[tuple[QSplitter, list[int]]]
    ) -> None:
        if self._inventory_stack is None:
            return
        if self._inventory_view() != "equipment":
            return
        self._update_equipment_layout_sizes()
        self._sync_inventory_controls()
        self._schedule_inventory_ancestor_splitter_restore(snapshots)

    def _set_inventory_view(self, view: str) -> None:
        if self._inventory_stack is None:
            return
        index = 0 if view == "backpack" else 1
        if self._inventory_stack.currentIndex() == index:
            return
        splitter_sizes = self._capture_inventory_ancestor_splitter_sizes()
        self._inventory_stack.setCurrentIndex(index)
        if self._inventory_backpack_button and self._inventory_equipment_button:
            self._inventory_backpack_button.setChecked(view == "backpack")
            self._inventory_equipment_button.setChecked(view == "equipment")
        if view == "backpack":
            self._clear_equipment_selection()
            self._hide_equipment_preview()
        else:
            self._inventory_list.clearSelection()
            self._inventory_list.setCurrentRow(-1)
        self._hide_inventory_preview()
        self._sync_inventory_notepad_visibility()
        self._sync_inventory_controls()
        if view == "equipment":
            self._finalize_equipment_view_switch(splitter_sizes)
            return
        self._schedule_inventory_ancestor_splitter_restore(splitter_sizes)

    def _sync_inventory_notepad_visibility(self) -> None:
        show_notepad = self._inventory_view() == "backpack"
        if self._inventory_notes_row is not None:
            self._inventory_notes_row.setVisible(show_notepad)
        if self._inventory_panel is None:
            return
        if show_notepad:
            # Keep a stable minimum from the backpack layout so toggling to equipment
            # does not collapse the entire right-side panel vertically.
            candidate = min(
                max(0, self._inventory_panel.minimumSizeHint().height()),
                max(0, self._inventory_panel.height()),
            )
            if candidate > self._inventory_panel_min_height_lock:
                self._inventory_panel_min_height_lock = candidate
        if self._inventory_panel_min_height_lock > 0:
            self._inventory_panel.setMinimumHeight(self._inventory_panel_min_height_lock)

    def _set_equipment_selection(self, slot_id: Optional[str]) -> None:
        self._equipment_selected_slot_id = slot_id
        for current_slot, widget in self._equipment_slot_widgets.items():
            widget.set_selected(current_slot == slot_id)
        self._sync_inventory_controls()

    def _clear_equipment_selection(self) -> None:
        self._set_equipment_selection(None)

    def _set_equipment(self, entry: Optional[PlayerSheetEntry]) -> None:
        if not self._equipment_slot_widgets:
            return
        if entry is None:
            for widget in self._equipment_slot_widgets.values():
                widget.set_item(None, None)
            self._clear_equipment_selection()
            return
        for slot_id, widget in self._equipment_slot_widgets.items():
            item_id = entry.equipment.get(slot_id)
            if item_id:
                loot_item = self._inventory_item_for_id(item_id)
                pixmap = self._equipment_icon_for_item(loot_item)
                widget.set_item(item_id, pixmap)
            else:
                widget.set_item(None, None)
        if self._equipment_selected_slot_id not in self._equipment_slot_widgets:
            self._equipment_selected_slot_id = None
        self._set_equipment_selection(self._equipment_selected_slot_id)
        self._update_equipment_layout_sizes()

    def _update_equipment_layout_sizes(self) -> None:
        if self._equipment_panel is None or not self._equipment_slot_widgets:
            return
        panel_layout = self._equipment_panel.layout()
        if panel_layout is not None:
            panel_layout.activate()
        panel_rect = self._equipment_panel.contentsRect()
        panel_height = max(1, panel_rect.height())
        panel_width = max(1, panel_rect.width())
        row_spacing = 24
        column_spacing = 10
        top_row_spacing = 12
        side_column_pad = 7
        min_misc_spacing = 9
        min_slot_size = 20
        slot_scale = 1.35
        slot_max_size = 180
        center_factor = 1.8
        slot_canvas_inset = 0
        slots_per_column = len(EQUIPMENT_SLOTS_LEFT)
        misc_slots_count = max(1, len(EQUIPMENT_SLOTS_MISC))
        height_limit = (
            panel_height
            - row_spacing
            - side_column_pad
            - (column_spacing * (slots_per_column - 1))
        ) / (
            slots_per_column + 1
        )
        top_width_limit = (panel_width - (top_row_spacing * 2)) / (2 + center_factor)
        misc_width_limit = (
            panel_width - (min_misc_spacing * (misc_slots_count - 1))
        ) / misc_slots_count
        base_slot_size = max(
            min_slot_size,
            min(height_limit, top_width_limit, misc_width_limit, slot_max_size),
        )
        slot_size = int(
            max(min_slot_size, min(slot_max_size, round(base_slot_size * slot_scale)))
        )
        # Never exceed vertical capacity; avoids misc-row overlap with upper section.
        slot_size = min(slot_size, max(min_slot_size, int(height_limit)))

        if misc_slots_count > 1:
            while slot_size > min_slot_size:
                free = panel_width - (slot_size * misc_slots_count)
                if free >= (min_misc_spacing * (misc_slots_count - 1)):
                    break
                slot_size -= 1
            free = max(0, panel_width - (slot_size * misc_slots_count))
            if free >= (min_misc_spacing * (misc_slots_count - 1)):
                misc_spacing = max(min_misc_spacing, free // (misc_slots_count - 1))
            else:
                misc_spacing = max(0, free // (misc_slots_count - 1))
            misc_left_margin = max(0, free - (misc_spacing * (misc_slots_count - 1)))
        else:
            misc_spacing = 0
            misc_left_margin = 0
        if self._equipment_misc_row_layout is not None:
            self._equipment_misc_row_layout.setSpacing(misc_spacing)
            self._equipment_misc_row_layout.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            self._equipment_misc_row_layout.setContentsMargins(
                misc_left_margin,
                0,
                0,
                0,
            )

        for widget in self._equipment_slot_widgets.values():
            widget.setFixedSize(slot_size, slot_size)
            widget.set_icon_size(slot_size)
            widget.set_canvas_inset(slot_canvas_inset)

        side_column_height = (
            (slot_size * slots_per_column)
            + (column_spacing * (slots_per_column - 1))
            + side_column_pad
        )
        if self._equipment_left_container is not None:
            self._equipment_left_container.setFixedWidth(slot_size)
            self._equipment_left_container.setFixedHeight(side_column_height)
        if self._equipment_right_container is not None:
            self._equipment_right_container.setFixedWidth(slot_size)
            self._equipment_right_container.setFixedHeight(side_column_height)
        if self._equipment_figure_frame is not None:
            self._equipment_figure_frame.setMinimumWidth(int(slot_size * center_factor))
            self._equipment_figure_frame.setFixedHeight(side_column_height)
        self._update_equipment_figure_pixmap()
        if self._equipment_weapon_strip is not None:
            self._equipment_weapon_strip.setFixedHeight(slot_size)
        if self._equipment_row_separator is not None:
            self._equipment_row_separator.setMaximumWidth(panel_width)

        self._equipment_panel.update()
        self._refresh_equipment_preview()

    def _on_equipment_slot_selected(self, slot_id: str) -> None:
        self._set_equipment_selection(slot_id)

    def _on_equipment_slot_dropped(self, slot_id: str, payload: dict) -> None:
        if not self._current_entry:
            return
        item_id = payload.get("item_id")
        if not item_id:
            return
        source = payload.get("source")
        if source == "equipment":
            source_slot = payload.get("slot")
            if not source_slot or source_slot == slot_id:
                return
            equipment = self._current_entry.equipment
            target_item = equipment.get(slot_id)
            equipment[slot_id] = item_id
            equipment[source_slot] = target_item
        elif source == "backpack":
            source_index = payload.get("index")
            equipment = self._current_entry.equipment
            existing_item = equipment.get(slot_id)
            equipment[slot_id] = item_id
            if existing_item:
                self._current_entry.inventory.append(existing_item)
            self._remove_inventory_item_by_index(item_id, source_index)
        else:
            return
        self._save_entries()
        self._set_inventory(self._current_entry)
        self._set_equipment_selection(slot_id)

    def _on_inventory_drop_from_equipment(self, payload: dict) -> None:
        if not self._current_entry:
            return
        item_id = payload.get("item_id")
        source_slot = payload.get("slot")
        if not item_id or not source_slot:
            return
        self._current_entry.inventory.append(item_id)
        self._current_entry.equipment[source_slot] = None
        self._save_entries()
        self._set_inventory(self._current_entry)
        self._clear_equipment_selection()

    def _on_equipment_slot_hovered(self, slot_id: str, item_id: Optional[str]) -> None:
        if not item_id:
            if self._equipment_preview_slot_id == slot_id:
                self._hide_equipment_preview()
            return
        if (
            self._equipment_preview_slot_id != slot_id
            or self._equipment_preview_item_id != item_id
        ):
            self._equipment_preview_top_left = None
        loot_item = self._inventory_item_for_id(item_id)
        if loot_item is None:
            return
        pixmap = self._equipment_preview_pixmap(slot_id, loot_item)
        if pixmap is None:
            return
        self._equipment_preview_slot_id = slot_id
        self._equipment_preview_item_id = item_id
        self._show_equipment_preview(slot_id, pixmap)

    def _equipment_slot_global_rect(self, slot_id: str) -> Optional[QRect]:
        widget = self._equipment_slot_widgets.get(slot_id)
        if widget is None or not widget.isVisible():
            return None
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return QRect(top_left, widget.size())

    def _equipment_preview_figure_rect(self) -> Optional[QRect]:
        if self._equipment_figure_frame is None:
            return None
        figure_top_left = self._equipment_figure_frame.mapToGlobal(QPoint(0, 0))
        figure_rect = QRect(figure_top_left, self._equipment_figure_frame.size()).adjusted(
            4, 4, -4, -4
        )
        if figure_rect.width() <= 8 or figure_rect.height() <= 8:
            return None
        return figure_rect

    def _equipment_preview_pixmap(self, slot_id: str, item: LootItem) -> Optional[QPixmap]:
        hover_rect = self._equipment_slot_global_rect(slot_id)
        if hover_rect is None:
            return None
        dpr = _screen_dpr_for_global_pos(QCursor.pos(), self)
        return self._inventory_preview_pixmap(
            item,
            max_width=PREVIEW_TOOLTIP_WIDTH,
            max_height=None,
            dpr=dpr,
        )

    def _show_equipment_preview(self, slot_id: str, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        hover_rect = self._equipment_slot_global_rect(slot_id)
        if hover_rect is None:
            return

        preview_pixmap = QPixmap(pixmap)
        preview_size = _pixmap_logical_size(preview_pixmap)
        if preview_size.width() <= 0 or preview_size.height() <= 0:
            self._hide_equipment_preview()
            return
        if preview_pixmap.isNull():
            self._hide_equipment_preview()
            return

        if self._equipment_preview_top_left is None:
            cursor_pos = QCursor.pos()
            screen = QGuiApplication.screenAt(cursor_pos)
            if screen is None:
                screen = QGuiApplication.screenAt(hover_rect.center())
            if screen is None:
                screen = QGuiApplication.primaryScreen()
            screen_rect = (
                screen.availableGeometry()
                if screen is not None
                else QRect(
                    hover_rect.left() - preview_size.width(),
                    hover_rect.top() - preview_size.height(),
                    preview_size.width() * 2,
                    preview_size.height() * 2,
                )
            )
            top_left = compute_cursor_preview_position(
                hover_rect=hover_rect,
                preview_size=preview_size,
                cursor_pos=cursor_pos,
                screen_rect=screen_rect,
            )
            self._equipment_preview_top_left = QPoint(top_left)
        else:
            top_left = QPoint(self._equipment_preview_top_left)
        self._equipment_preview_tooltip.show_preview_at(preview_pixmap, top_left)

    def _refresh_equipment_preview(self) -> None:
        if self._equipment_preview_item_id is None or self._equipment_preview_slot_id is None:
            return
        loot_item = self._inventory_item_for_id(self._equipment_preview_item_id)
        if loot_item is None:
            return
        pixmap = self._equipment_preview_pixmap(self._equipment_preview_slot_id, loot_item)
        if pixmap is None:
            return
        self._show_equipment_preview(self._equipment_preview_slot_id, pixmap)

    def _hide_equipment_preview(self) -> None:
        self._equipment_preview_slot_id = None
        self._equipment_preview_item_id = None
        self._equipment_preview_top_left = None
        self._equipment_preview_tooltip.hide_preview()

    def _remove_inventory_item_by_index(
        self, item_id: str, source_index: Optional[int]
    ) -> None:
        if not self._current_entry:
            return
        if isinstance(source_index, int):
            if 0 <= source_index < len(self._current_entry.inventory):
                if self._current_entry.inventory[source_index] == item_id:
                    self._current_entry.inventory.pop(source_index)
                    return
        try:
            self._current_entry.inventory.remove(item_id)
        except ValueError:
            pass

    def _set_inventory(self, entry: Optional[PlayerSheetEntry]) -> None:
        self._hide_inventory_preview()
        self._inventory_list.blockSignals(True)
        self._inventory_list.clear()
        if entry is None:
            self._inventory_placeholder.setText("Select a character sheet to view inventory.")
            self._inventory_list.setVisible(False)
            self._inventory_placeholder.setVisible(True)
            self._inventory_list.blockSignals(False)
            if self._inventory_notepad is not None:
                self._syncing_inventory_notes = True
                self._inventory_notepad.clear()
                self._syncing_inventory_notes = False
            self._sync_inventory_controls()
            self._set_currency_fields(None)
            self._set_equipment(None)
            return

        for item_id in entry.inventory:
            loot_item = self._inventory_item_for_id(item_id)
            row = QListWidgetItem("")
            row.setData(Qt.ItemDataRole.UserRole, item_id)
            row.setIcon(QIcon(self._inventory_icon_for_item(loot_item)))
            row.setSizeHint(QSize(INVENTORY_ITEM_SIZE, INVENTORY_ITEM_SIZE))
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsDragEnabled)
            self._inventory_list.addItem(row)

        self._inventory_list.blockSignals(False)
        has_items = self._inventory_list.count() > 0
        self._inventory_list.setVisible(True)
        self._inventory_placeholder.setText("No inventory items yet.")
        self._inventory_placeholder.setVisible(not has_items)
        if self._inventory_placeholder.parent() is self._inventory_list.viewport():
            self._inventory_placeholder.move(
                (self._inventory_list.viewport().width() - self._inventory_placeholder.sizeHint().width()) // 2,
                (self._inventory_list.viewport().height() - self._inventory_placeholder.sizeHint().height()) // 2,
            )
        if self._inventory_notepad is not None:
            self._syncing_inventory_notes = True
            self._inventory_notepad.setPlainText(entry.inventory_notes)
            self._syncing_inventory_notes = False
        self._sync_inventory_notepad_visibility()
        self._sync_inventory_controls()
        self._set_currency_fields(entry)
        self._set_equipment(entry)

    def _sync_inventory_controls(self) -> None:
        has_entry = self._current_entry is not None
        selected = bool(self._inventory_list.selectedItems())
        equipment_selected = False
        if self._equipment_selected_slot_id:
            widget = self._equipment_slot_widgets.get(self._equipment_selected_slot_id)
            equipment_selected = bool(widget and widget.item_id)
        view = self._inventory_view()
        self._inventory_add_button.setEnabled(has_entry)
        if self._inventory_notepad is not None:
            self._inventory_notepad.setEnabled(has_entry and view == "backpack")
        if view == "equipment":
            self._inventory_remove_button.setEnabled(has_entry and equipment_selected)
        else:
            self._inventory_remove_button.setEnabled(has_entry and selected)

    def _set_currency_fields(self, entry: Optional[PlayerSheetEntry]) -> None:
        self._syncing_currency = True
        if entry is None:
            self._gold_spin.setValue(0)
            self._silver_spin.setValue(0)
            self._copper_spin.setValue(0)
            self._gold_spin.setEnabled(False)
            self._silver_spin.setEnabled(False)
            self._copper_spin.setEnabled(False)
        else:
            self._gold_spin.setEnabled(True)
            self._silver_spin.setEnabled(True)
            self._copper_spin.setEnabled(True)
            self._gold_spin.setValue(max(0, int(entry.gold)))
            self._silver_spin.setValue(max(0, int(entry.silver)))
            self._copper_spin.setValue(max(0, int(entry.copper)))
        self._syncing_currency = False

    def _on_currency_changed(self, field: str, value: int) -> None:
        if self._syncing_currency or not self._current_entry:
            return
        if field == "gold":
            self._current_entry.gold = value
        elif field == "silver":
            self._current_entry.silver = value
        elif field == "copper":
            self._current_entry.copper = value
        self._save_entries()

    def _open_inventory_picker(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a character sheet first.")
            return
        self._refresh_inventory_library()
        if not self._inventory_item_library:
            QMessageBox.information(
                self,
                "No Items Available",
                "No items found in the loot library. Create items in Item Creator first.",
            )
            return
        dialog = InventoryItemPickerDialog(
            self._inventory_item_library,
            icon_provider=self._inventory_icon_for_item,
            preview_provider=self._inventory_preview_pixmap,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        item_id = dialog.selected_item_id
        if not item_id:
            return
        self._add_inventory_item(item_id)

    def _add_inventory_item(self, item_id: str) -> None:
        if not self._current_entry:
            return
        self._current_entry.inventory.append(item_id)
        self._save_entries()
        self._set_inventory(self._current_entry)
        if self._inventory_list.count() > 0:
            self._inventory_list.setCurrentRow(self._inventory_list.count() - 1)

    def _on_inventory_notepad_changed(self) -> None:
        if (
            self._syncing_inventory_notes
            or not self._current_entry
            or self._inventory_notepad is None
        ):
            return
        self._current_entry.inventory_notes = self._inventory_notepad.toPlainText()
        self._save_entries()

    def _remove_inventory_item(self) -> None:
        if not self._current_entry:
            return
        if self._inventory_view() == "equipment":
            slot_id = self._equipment_selected_slot_id
            widget = self._equipment_slot_widgets.get(slot_id) if slot_id else None
            if not slot_id or not widget or not widget.item_id:
                QMessageBox.information(self, "No Selection", "Select an equipment slot first.")
                return
            self._current_entry.equipment[slot_id] = None
            self._save_entries()
            self._set_inventory(self._current_entry)
            self._clear_equipment_selection()
            return
        selected = self._inventory_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "No Selection", "Select an inventory item first.")
            return
        for item in selected:
            row = self._inventory_list.row(item)
            self._inventory_list.takeItem(row)
        self._sync_inventory_from_list()
        self._hide_inventory_preview()
        self._sync_inventory_controls()

    def _sync_inventory_from_list(self) -> None:
        if not self._current_entry:
            return
        inventory: List[str] = []
        for index in range(self._inventory_list.count()):
            item = self._inventory_list.item(index)
            item_id = item.data(Qt.ItemDataRole.UserRole)
            if item_id:
                inventory.append(item_id)
        self._current_entry.inventory = inventory
        self._save_entries()
        self._set_inventory(self._current_entry)

    def _show_inventory_preview_for_item(self, item: QListWidgetItem) -> None:
        if item is None:
            return
        item_id = item.data(Qt.ItemDataRole.UserRole)
        loot_item = self._inventory_item_for_id(item_id)
        if loot_item is None:
            return
        existing_hover = self._inventory_preview_item_id == item_id
        anchor = self._inventory_preview_top_left
        if existing_hover and anchor is not None:
            dpr = _screen_dpr_for_global_pos(anchor, self)
        else:
            global_pos = QCursor.pos()
            dpr = _screen_dpr_for_global_pos(global_pos, self)
        pixmap = self._inventory_preview_pixmap(
            loot_item,
            max_width=PREVIEW_TOOLTIP_WIDTH,
            max_height=None,
            dpr=dpr,
        )
        if pixmap is None:
            return
        if existing_hover and anchor is not None:
            self._inventory_preview_tooltip.show_preview_at(pixmap, anchor)
            return
        global_pos = QCursor.pos()
        self._inventory_preview_tooltip.show_preview(pixmap, global_pos)
        self._inventory_preview_item_id = item_id
        self._inventory_preview_top_left = QPoint(self._inventory_preview_tooltip.pos())

    def _hide_inventory_preview(self) -> None:
        self._inventory_preview_item_id = None
        self._inventory_preview_top_left = None
        self._inventory_preview_tooltip.hide_preview()

    def eventFilter(self, obj, event) -> bool:
        if obj is self._inventory_list.viewport():
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
                payload = _decode_inventory_drag(event.mimeData())
                if payload and payload.get("source") == "equipment":
                    if event.type() == QEvent.Type.Drop:
                        self._on_inventory_drop_from_equipment(payload)
                    event.acceptProposedAction()
                    return True
            if event.type() == QEvent.Type.MouseMove:
                pos = event.position().toPoint()
                item = self._inventory_list.itemAt(pos)
                if item is not None:
                    self._show_inventory_preview_for_item(item)
                else:
                    self._hide_inventory_preview()
            if event.type() == QEvent.Type.MouseButtonPress:
                pos = event.position().toPoint()
                item = self._inventory_list.itemAt(pos)
                if item is None:
                    self._inventory_list.clearSelection()
                    self._inventory_list.setCurrentRow(-1)
                    self._sync_inventory_controls()
                    self._hide_inventory_preview()
            if event.type() == QEvent.Type.Leave:
                self._hide_inventory_preview()
            if event.type() == QEvent.Type.Resize and self._inventory_placeholder.parent() is self._inventory_list.viewport():
                self._inventory_placeholder.move(
                    (self._inventory_list.viewport().width() - self._inventory_placeholder.sizeHint().width()) // 2,
                    (self._inventory_list.viewport().height() - self._inventory_placeholder.sizeHint().height()) // 2,
                )
        if obj in (self._inventory_panel, self._inventory_header, self._currency_row, self._equipment_panel):
            if event.type() == QEvent.Type.MouseButtonPress:
                self._inventory_list.clearSelection()
                self._inventory_list.setCurrentRow(-1)
                self._clear_equipment_selection()
                self._sync_inventory_controls()
                self._hide_inventory_preview()
                self._hide_equipment_preview()
        if obj is self._equipment_panel and event.type() == QEvent.Type.Resize:
            self._update_equipment_layout_sizes()
        if obj is self._equipment_figure_label and event.type() == QEvent.Type.Resize:
            self._update_equipment_figure_pixmap()
        if obj in (self._inventory_backpack_button, self._inventory_equipment_button):
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
                payload = _decode_inventory_drag(event.mimeData())
                if payload and payload.get("item_id"):
                    event.acceptProposedAction()
                    if obj is self._inventory_backpack_button:
                        self._set_inventory_view("backpack")
                    elif obj is self._inventory_equipment_button:
                        self._set_inventory_view("equipment")
                    return True
        return super().eventFilter(obj, event)

    def _update_equipment_figure_pixmap(self) -> None:
        label = self._equipment_figure_label
        source = self._equipment_figure_source_pixmap
        if label is None or source is None or source.isNull():
            return
        target = label.size()
        if target.width() <= 0 or target.height() <= 0:
            return
        requested_dpr = max(1.0, float(label.devicePixelRatioF()))
        pixel_width, effective_dpr = _dpr_fitted_pixel_size(target.width(), requested_dpr)
        pixel_height, _ = _dpr_fitted_pixel_size(target.height(), requested_dpr)
        scaled = source.scaled(
            pixel_width,
            pixel_height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(effective_dpr)
        label.setPixmap(scaled)

    def _defer_restore_selection(self, previous: QListWidgetItem) -> None:
        def _restore() -> None:
            self._selection_guard = True
            selection_model = self._sheet_list.selectionModel()
            if selection_model is not None:
                selection_model.setCurrentIndex(
                    self._sheet_list.indexFromItem(previous),
                    QItemSelectionModel.SelectionFlag.ClearAndSelect
                    | QItemSelectionModel.SelectionFlag.Current,
                )
            else:
                self._sheet_list.clearSelection()
                self._sheet_list.setCurrentItem(previous)
                previous.setSelected(True)
            prev_entry = previous.data(Qt.ItemDataRole.UserRole)
            self._refresh_selection_ui(prev_entry)
            self._selection_guard = False

        QTimer.singleShot(0, _restore)

    def _on_sheet_unsaved_changed(self, modified: bool) -> None:
        self._set_unsaved_indicator(bool(modified))
        if not modified and self._pending_switch_item is not None:
            target = self._pending_switch_item
            self._pending_switch_item = None
            self._switch_to_item(target)

    def _on_sheet_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if self._selection_guard:
            return
        if current is None:
            self._set_details(None)
            return
        if self._sheet_panel is not None and previous is not None:
            self._selection_guard = True
            self._sheet_list.setCurrentItem(previous)
            prev_entry = previous.data(Qt.ItemDataRole.UserRole)
            self._refresh_selection_ui(prev_entry)
            self._selection_guard = False
            self._check_unsaved_before_switch(current, previous)
            return
        entry = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._set_details(entry)

    def _open_pdf(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a sheet to open.")
            return
        path = self._sheet_panel.current_path if self._sheet_panel else None
        if not path:
            path = self._current_entry.pdf_path
        if (not path or not os.path.exists(path)) and self._current_entry is not None:
            path = self._resolve_sheet_pdf_path(self._current_entry)
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Missing File", "The PDF file does not exist.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.warning(self, "Open Failed", "Unable to open the PDF file.")

    def _check_unsaved_before_switch(
        self, target: QListWidgetItem, previous: Optional[QListWidgetItem]
    ) -> None:
        if self._sheet_panel is None:
            self._switch_to_item(target)
            return
        modified = self._sheet_panel.is_modified()
        self._on_unsaved_checked(modified, target, previous)

    def _on_unsaved_checked(
        self,
        modified: bool,
        target: QListWidgetItem,
        previous: Optional[QListWidgetItem],
    ) -> None:
        self._set_unsaved_indicator(bool(modified))
        if not modified:
            self._switch_to_item(target)
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Unsaved Changes")
        dialog.setText("You have unsaved changes to this character sheet.")
        save_button = dialog.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton(
            "Discard", QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == save_button:
            self._pending_switch_item = target
            self._save_current_sheet()
        elif clicked == discard_button:
            self._switch_to_item(target)
        else:
            if previous is not None:
                self._defer_restore_selection(previous)

    def _switch_to_item(self, item: Optional[QListWidgetItem]) -> None:
        self._selection_guard = True
        if item is None:
            self._sheet_list.setCurrentRow(-1)
            self._selection_guard = False
            self._set_details(None)
            return
        self._sheet_list.setCurrentItem(item)
        self._selection_guard = False
        entry = item.data(Qt.ItemDataRole.UserRole)
        self._set_details(entry)
        self._pending_switch_item = None

    def _save_current_sheet(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a sheet to save.")
            return
        current_pdf_path: Optional[str] = None
        if self._sheet_panel is not None:
            self._sheet_panel.save_current()
            current_pdf_path = self._sheet_panel.current_path
        if current_pdf_path:
            self._current_entry.pdf_path = str(current_pdf_path)
            sync_entry_archive(self._current_entry, pdf_source=current_pdf_path)
        self._save_entries()
        sheet_id = sheet_id_for_entry(self._current_entry)
        PLAYER_SHEET_EVENTS.inventorySaved.emit(sheet_id, _entry_inventory_payload(self._current_entry))

    def _confirm_unsaved_before_destructive(self, action_name: str) -> bool:
        if self._sheet_panel is None or not self._sheet_panel.is_modified():
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Unsaved Changes")
        dialog.setText(
            f"You have unsaved changes. Save before you {action_name} this sheet?"
        )
        save_button = dialog.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton(
            "Discard", QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == save_button:
            self._save_current_sheet()
            return True
        if clicked == discard_button:
            return True
        return False

    def _remove_entry(self, entry: PlayerSheetEntry) -> None:
        self._manager.entries = [item for item in self._manager.entries if item is not entry]
        self._save_entries()
        self._apply_filters()
        if self._current_entry is entry:
            self._set_details(None)

    def _trash_payload_for_entry(self, entry: PlayerSheetEntry) -> dict:
        payload = entry_to_dict(entry)
        payload["sheet_id"] = sheet_id_for_entry(entry)
        return payload

    def _delete_current_sheet(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a sheet to delete.")
            return
        # Move to trash immediately - no confirmation needed since it's recoverable
        if self._sheet_panel is not None:
            self._sheet_panel.clear()
        trashed_path = move_entry_files_to_trash(self._current_entry)
        payload = self._trash_payload_for_entry(self._current_entry)
        if trashed_path:
            payload["pdf_path"] = trashed_path
        move_to_trash("character_sheet", payload)
        if trashed_path and Path(trashed_path).exists():
            logger.info("Moved player sheet PDF to trash: %s", trashed_path)
        else:
            logger.warning(
                "Failed to move player sheet PDF to trash for: %s",
                self._current_entry.pdf_path,
            )
        self._remove_entry(self._current_entry)

    def _disintegrate_current_sheet(self) -> None:
        if not self._current_entry:
            QMessageBox.information(
                self, "No Selection", "Select a sheet to disintegrate."
            )
            return
        # Skip unsaved check - user wants to delete anyway
        typed, ok = QInputDialog.getText(
            self,
            "Disintegrate Sheet",
            "Type DISINTEGRATE to permanently delete this sheet.",
        )
        if not ok:
            return
        if typed.strip().upper() != "DISINTEGRATE":
            QMessageBox.warning(
                self,
                "Confirmation Required",
                "Disintegration cancelled. The confirmation text did not match.",
            )
            return
        if self._sheet_panel is not None:
            self._sheet_panel.clear()
        disintegrate_entry_files(self._current_entry)
        self._remove_entry(self._current_entry)

    def _delete_entry_files(self, entry: PlayerSheetEntry) -> None:
        delete_entry_files(entry)

    def _load_pdf_preview(self, entry: Optional[PlayerSheetEntry]) -> None:
        if self._sheet_panel is None:
            return
        if not entry:
            self._sheet_panel.clear()
            return
        path = self._resolve_sheet_pdf_path(entry)
        if not path:
            self._sheet_panel.clear()
            return
        sheet_id = sheet_id_for_entry(entry)
        autosave_path = character_sheet_pdf_path(sheet_id)
        self._sheet_panel.set_autosave_path(str(autosave_path))
        self._sheet_panel.load_pdf(path)

    def _resolve_sheet_pdf_path(
        self, entry: PlayerSheetEntry, source_path: Optional[str] = None
    ) -> Optional[str]:
        sheet_id = sheet_id_for_entry(entry)
        storage_path = character_sheet_pdf_path(sheet_id)
        archive_path = _entry_archive_path(entry)
        source = source_path or entry.pdf_path

        if source and os.path.exists(source):
            source_path_obj = Path(source)
            if source_path_obj != storage_path:
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(source, storage_path)
                except OSError:
                    storage_path = source_path_obj
            else:
                storage_path.parent.mkdir(parents=True, exist_ok=True)
            entry.pdf_path = str(storage_path)
            sync_entry_archive(entry, pdf_source=str(storage_path))
            self._save_entries()
            return str(storage_path)

        if storage_path.exists():
            entry.pdf_path = str(storage_path)
            sync_entry_archive(entry, pdf_source=str(storage_path))
            return str(storage_path)

        if archive_path.exists() and extract_character_pdf(archive_path, storage_path):
            entry.archive_path = str(archive_path)
            entry.pdf_path = str(storage_path)
            archive_inventory = read_character_inventory(archive_path)
            entry.inventory = list(archive_inventory.get("inventory", []))
            entry.inventory_notes = str(archive_inventory.get("inventory_notes", ""))
            entry.equipment = _normalize_equipment(archive_inventory.get("equipment", {}))
            try:
                entry.gold = max(0, int(archive_inventory.get("gold", entry.gold)))
                entry.silver = max(0, int(archive_inventory.get("silver", entry.silver)))
                entry.copper = max(0, int(archive_inventory.get("copper", entry.copper)))
            except (TypeError, ValueError):
                pass
            self._save_entries()
            return str(storage_path)

        ensure_entry_archive(entry)
        return None

    def _on_sheet_pdf_selected(self, path: str) -> None:
        if not self._current_entry:
            return
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Missing File", "The PDF file does not exist.")
            return
        resolved = self._resolve_sheet_pdf_path(self._current_entry, source_path=path)
        if resolved:
            self._load_pdf_preview(self._current_entry)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if not self._sheet_expanded or self._details_panel is None:
            self._schedule_splitter_restore()
            return
        if self._expand_anim is not None and self._expand_anim.state() == QPropertyAnimation.State.Running:
            return
        self._details_panel.setGeometry(self._expanded_target_rect())

    def hideEvent(self, event) -> None:  # type: ignore[override]
        if self._expand_anim is not None and self._expand_anim.state() == QPropertyAnimation.State.Running:
            self._expand_anim.stop()
        if self._blur_anim is not None and self._blur_anim.state() == QPropertyAnimation.State.Running:
            self._blur_anim.stop()
        if self._sheet_expanded and self._details_panel is not None:
            self._overlay_root.setVisible(True)
            self._details_panel.setGeometry(self._expanded_target_rect())
            if self._blur_effect is not None:
                self._blur_effect.setBlurRadius(self._expanded_blur_radius)
        super().hideEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if not self._sheet_expanded or self._details_panel is None:
            self._schedule_splitter_restore()
            return
        self._overlay_root.setVisible(True)
        self._overlay_root.raise_()
        if self._details_panel.parent() is not self._overlay_root:
            if self._detail_splitter is not None:
                self._detail_splitter_index = self._detail_splitter.indexOf(self._details_panel)
                if self._detail_splitter_index == -1:
                    self._detail_splitter_index = 0
            self._details_panel.setParent(self._overlay_root)
            self._details_panel.show()
            self._ensure_details_placeholder()
            if self._detail_splitter is not None and self._details_placeholder is not None:
                if self._details_placeholder.parent() is not self._detail_splitter:
                    self._details_placeholder.setParent(self._detail_splitter)
                insert_at = self._detail_splitter_index or 0
                if insert_at < 0:
                    insert_at = 0
                self._detail_splitter.insertWidget(insert_at, self._details_placeholder)
                self._details_placeholder.show()
        if self._blur_effect is not None:
            self._blur_effect.setBlurRadius(self._expanded_blur_radius)
        self._details_panel.setGeometry(self._expanded_target_rect())

    def _on_sheet_expand_toggled(self, expanded: bool) -> None:
        self._set_sheet_expanded(expanded)

    def _set_sheet_expanded(self, expanded: bool) -> None:
        if expanded == self._sheet_expanded:
            return
        if self._sheet_panel is None or self._details_panel is None:
            return
        self._sheet_expanded = expanded
        self._sheet_panel.set_expanded(expanded)
        self._update_header_mode()
        if expanded:
            self._enter_sheet_expanded()
        else:
            self._exit_sheet_expanded()

    def _enter_sheet_expanded(self) -> None:
        if self._details_panel is None or self._detail_splitter is None:
            return
        self._overlay_root.setVisible(True)
        self._overlay_root.raise_()

        self._detail_splitter_index = self._detail_splitter.indexOf(self._details_panel)
        self._detail_splitter_sizes = self._detail_splitter.sizes()
        self._detail_splitter_ratio = DETAIL_SPLITTER_PRIMARY_RATIO
        self._collapsed_rect = self._map_rect_to_overlay(self._details_panel)

        self._details_panel.setParent(self._overlay_root)
        self._details_panel.raise_()
        self._details_panel.show()
        if self._collapsed_rect is not None:
            self._details_panel.setGeometry(self._collapsed_rect)

        self._ensure_details_placeholder()
        if self._details_placeholder is not None:
            if self._details_placeholder.parent() is not self._detail_splitter:
                self._details_placeholder.setParent(self._detail_splitter)
            insert_at = self._detail_splitter_index or 0
            if insert_at < 0:
                insert_at = 0
            self._detail_splitter.insertWidget(insert_at, self._details_placeholder)
            self._details_placeholder.show()
            if self._detail_splitter_sizes:
                self._detail_splitter.setSizes(self._detail_splitter_sizes)

        self._animate_blur(self._expanded_blur_radius)
        target_rect = self._expanded_target_rect()
        self._animate_expand(self._details_panel.geometry(), target_rect)

    def _exit_sheet_expanded(self) -> None:
        if self._details_panel is None:
            return
        target_rect = self._placeholder_rect()
        if target_rect.isNull():
            target_rect = self._collapsed_rect or self._details_panel.geometry()
        self._animate_blur(0.0)
        self._animate_expand(self._details_panel.geometry(), target_rect)

    def _ensure_details_placeholder(self) -> None:
        if self._details_placeholder is None:
            placeholder = QWidget(self._detail_splitter)
            placeholder.setObjectName("TransparentContainer")
            placeholder.setStyleSheet("background-color: transparent;")
            placeholder.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
            )
            self._details_placeholder = placeholder

    def _placeholder_rect(self) -> QRect:
        if self._details_placeholder is None:
            return self._collapsed_rect or QRect()
        return self._map_rect_to_overlay(self._details_placeholder)

    def _expanded_target_rect(self) -> QRect:
        rect = self._overlay_root.rect()
        margin = self._expanded_margin
        rect = rect.adjusted(margin, margin, -margin, -margin)
        if rect.width() <= 0 or rect.height() <= 0:
            return self._overlay_root.rect()
        return rect

    def _map_rect_to_overlay(self, widget: QWidget) -> QRect:
        rect = widget.geometry()
        top_left = widget.mapToGlobal(rect.topLeft())
        overlay_pos = self._overlay_root.mapFromGlobal(top_left)
        return QRect(overlay_pos, rect.size())

    def _animate_blur(self, target: float) -> None:
        if self._blur_effect is None or self._blur_anim is None:
            return
        self._blur_anim.stop()
        self._blur_anim.setStartValue(self._blur_effect.blurRadius())
        self._blur_anim.setEndValue(target)
        self._blur_anim.start()

    def _animate_expand(self, start_rect: QRect, end_rect: QRect) -> None:
        if self._expand_anim is None:
            if self._details_panel is not None:
                self._details_panel.setGeometry(end_rect)
            self._on_expand_anim_finished()
            return
        self._expand_anim.stop()
        self._expand_anim.setStartValue(start_rect)
        self._expand_anim.setEndValue(end_rect)
        self._expand_anim.start()

    def _on_expand_anim_finished(self) -> None:
        if self._details_panel is None or self._detail_splitter is None:
            return
        if self._sheet_expanded:
            self._details_panel.setGeometry(self._expanded_target_rect())
            return
        self._restore_details_panel()
        self._overlay_root.setVisible(False)

    def _restore_details_panel(self) -> None:
        if self._details_panel is None or self._detail_splitter is None:
            return
        insert_at = self._detail_splitter_index or 0
        if insert_at < 0:
            insert_at = 0
        if self._details_panel.parent() is not self._detail_splitter:
            self._detail_splitter.insertWidget(insert_at, self._details_panel)
        self._details_panel.show()
        self._schedule_splitter_restore()
        if self._details_placeholder is not None:
            self._details_placeholder.hide()
            self._details_placeholder.setParent(None)


    def _show_sheet_status(self, message: str) -> None:
        if not message:
            return
        QMessageBox.warning(self, "PDF Viewer", message)

    def _schedule_splitter_restore(self) -> None:
        QTimer.singleShot(0, self._restore_splitter_sizes)

    def _restore_splitter_sizes(self) -> None:
        if self._detail_splitter is None:
            return
        if self._detail_splitter_ratio is None:
            self._detail_splitter_ratio = DETAIL_SPLITTER_PRIMARY_RATIO
        self._apply_fixed_detail_splitter_ratio()

    def _apply_fixed_detail_splitter_ratio(self) -> None:
        if self._detail_splitter is None:
            return
        sizes = self._detail_splitter.sizes()
        total = sum(max(0, int(size)) for size in sizes)
        if total <= 0:
            total = max(2, self._detail_splitter.width() - self._detail_splitter.handleWidth())
        if total <= 0:
            return
        primary = max(1, int(total * self._detail_splitter_ratio))
        secondary = max(1, total - primary)
        self._detail_splitter.setSizes([primary, secondary])

    def _set_unsaved_indicator(self, unsaved: bool) -> None:
        self._sheet_unsaved = unsaved
        self._update_header_labels()
        self._sync_sheet_toolbar_title()

    def _set_header_name(self, text: str) -> None:
        self._header_name_text = text
        self._update_header_labels()
        self._sync_sheet_toolbar_title()

    def _update_header_labels(self) -> None:
        if not hasattr(self, "_header_name") or not hasattr(self, "_header_name_center"):
            return
        display_text = self._header_name_text
        if self._sheet_unsaved:
            display_text = f"{display_text} *"
        self._header_name.setText(display_text)
        self._header_name_center.setText(display_text)

    def _update_header_mode(self) -> None:
        if not hasattr(self, "_header_title_stack"):
            return
        self._header_title_stack.setCurrentWidget(self._header_name)

    def _sync_sheet_toolbar_title(self) -> None:
        if self._sheet_panel is None:
            return
        if self._current_entry is None:
            self._sheet_panel.set_center_title("")
            self._sheet_panel.set_center_unsaved(False)
            return
        self._sheet_panel.set_center_title(self._header_name_text)
        self._sheet_panel.set_center_unsaved(self._sheet_unsaved)

    def _open_new_sheet_dialog(self) -> None:
        dialog = PlayerSheetDialog(
            self._world_data,
            self,
            default_pdf_path=default_sheet_pdf_path(),
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.entry()
            if not entry:
                return
            self._manager.add_sheet(entry)
            self._save_entries()
            self._apply_filters()

    def _open_edit_sheet_dialog(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a sheet to edit.")
            return
        dialog = PlayerSheetDialog(self._world_data, self, entry=self._current_entry)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.entry()
        if not updated:
            return
        self._current_entry.name = updated.name
        self._current_entry.pdf_path = updated.pdf_path
        self._current_entry.archive_path = updated.archive_path
        self._current_entry.world = updated.world
        self._current_entry.campaign = updated.campaign
        self._current_entry.group = updated.group
        self._current_entry.tags = updated.tags
        ensure_entry_archive(self._current_entry)
        self._save_entries()
        self._apply_filters()
