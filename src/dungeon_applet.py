from __future__ import annotations

import base64
import hashlib
import os
import json
import math
import shutil
import sys
import time
import re
import uuid
from typing import Callable
from datetime import datetime, timezone
from pathlib import Path
from enum import Enum, auto
from PySide6.QtWidgets import (
    QWidget, 
    QVBoxLayout, 
    QHBoxLayout, 
    QGraphicsView, 
    QGraphicsScene, 
    QGraphicsItem,
    QFrame, 
    QPushButton, 
    QLabel, 
    QGridLayout,
    QSizePolicy,
    QButtonGroup,
    QProgressBar,
    QSpacerItem,
    QLineEdit,
    QTextEdit,
    QSpinBox,
    QStackedWidget,
    QListWidget,
    QListWidgetItem,
    QListView,
    QScrollArea,
    QToolButton,
    QComboBox,
    QAbstractSpinBox,
    QAbstractButton,
    QMenu,
    QInputDialog,
    QMessageBox,
    QFileDialog,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGraphicsPathItem,
    QAbstractItemView,
    QApplication,
)
from PySide6.QtCore import (
    Qt,
    QRect,
    QRectF,
    QPoint,
    QPointF,
    QObject,
    Signal,
    QSize,
    QEvent,
    QTimer,
    QPropertyAnimation,
    QAbstractAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
    Property,
    QSignalBlocker,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QPen,
    QWheelEvent,
    QMouseEvent,
    QIcon,
    QUndoStack,
    QResizeEvent,
    QPainterPath,
    QKeyEvent,
    QKeySequence,
    QPixmap,
    QImage,
    QShortcut,
    QFont,
    QFontMetrics,
    QCursor,
    QPolygonF,
)

from dungeon_constants import (
    GRID_SIZE,
    TOOL_ROOM,
    TOOL_ELLIPSE,
    TOOL_FOW_BRUSH,
    TOOL_FOW_ERASER,
    TOOL_ENCOUNTER,
    LAYER_FG,
    LAYER_MID,
    LAYER_BG,
    ROLE_LAYER,
    ROLE_KIND,
    ROLE_LABEL,
    ROLE_ICON,
    ROLE_OWNER_PLAYER_ID,
    ROLE_ENTITY_ID,
    ROLE_LINKED_SHEET_ID,
    ROLE_LINKED_SHEET_NAME,
    ROLE_LINKED_CHARACTER_ID,
    WALL_COLOR,
)
from dungeon_states import (
    SelectState, FreeDrawState, DrawingRectState, DrawingEllipseState, 
    DrawingPolygonState, PlacingState, EraserState, FogState, EncounterPlacingState,
    PingState, ImagePlacingState
)
from dungeon_items import EntityItem, FogItem
from ui.widgets import PlusMinusSpinBox
from online_session.authz import authorize_command
from online_session.controllers import ClientSessionController, HostSessionController
from online_session.types import OnlineRole
from dmt_package import list_dmt_package_assets, read_dmt_package_asset, read_dmt_package_info, write_dmt_package
from save_paths import (
    default_dnd_save_dir,
    dnd_saves_dir,
    items_dir,
    online_icon_cache_dir,
    online_loot_item_cache_dir,
    clear_online_runtime_cache as clear_online_runtime_storage,
    collection_icon_assets_dir,
    working_collection_icon_assets_dir,
)
from character_archive import (
    character_sync_content_hash,
    extract_character_pdf,
    normalize_inventory_payload,
    validate_character_archive_bytes,
)
from loot_applet import LootPreviewTooltip
from item_file_format import (
    ITEM_FILE_EXTENSION,
    ITEM_FILE_FORMAT,
    build_item_document,
    item_document_matches,
    item_id_from_payload,
    list_item_file_paths,
    load_item_document,
    load_item_payload,
    normalized_item_name_from_payload,
    normalize_item_name,
    write_item_document,
)
from user_settings import get_or_create_local_player_id
from unique_ids import generate_named_object_id, generate_probabilistic_unique_id, machine_entropy_string

class ToolType(Enum):
    SELECT = auto()
    FREE_DRAW = auto()
    RECTANGLE = auto()
    CIRCLE = auto()
    POLYGON = auto()
    ENTITY = auto()
    ENCOUNTER = auto()
    ERASER = auto()
    PING = auto()
    IMAGE = auto()
    FOW_BRUSH = auto()
    FOW_ERASER = auto()


DUNGEON_COLLECTION_VERSION = 1
OVERLAY_BG_RGBA = "rgba(9, 9, 11, 180)"
OVERLAY_BG_COLOR = QColor(9, 9, 11, 180)
OVERLAY_BORDER_RGBA = "rgba(255, 255, 255, 20)"
OVERLAY_BORDER_COLOR = QColor(255, 255, 255, 20)
INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
ONLINE_DEBUG_LOG_FILENAME = "dmt_online_debug.log"
COLLECTION_AUTOSAVE_SUFFIX = "_autosave"
COLLECTION_AUTOSAVE_INTERVAL_MS = 15000
COLLECTION_FILE_EXTENSION = ".dmtcollection"
COLLECTION_FILE_FORMAT = "dmtcollection.v1"
LOCAL_DUNGEON_PROFILE_FILENAME = "dungeon_profile.json"
FOG_OVERLAY_Z = 200.0
MAX_ONLINE_ICON_BYTES = 2 * 1024 * 1024


def _sanitize_filename(name: str, fallback: str = "dungeon_collection") -> str:
    cleaned = "".join(ch for ch in name.strip() if ch not in INVALID_FILENAME_CHARS)
    cleaned = cleaned.rstrip(" .")
    return cleaned or fallback


def _inventory_entry_item_id(raw: object) -> str:
    if isinstance(raw, dict):
        return str(raw.get("item_id") or "").strip()
    return str(raw or "").strip()


def _inventory_entry_quantity(raw: object) -> int:
    if isinstance(raw, dict):
        try:
            return max(1, int(raw.get("quantity", 1)))
        except (TypeError, ValueError):
            return 1
    return 1


def _inventory_payload_item_documents(payload: dict | None) -> dict[str, dict]:
    if not isinstance(payload, dict):
        return {}
    raw_documents = payload.get("item_documents")
    if isinstance(raw_documents, dict):
        iterable = raw_documents.values()
    elif isinstance(raw_documents, list):
        iterable = raw_documents
    else:
        iterable = []
    documents: dict[str, dict] = {}
    for raw_document in iterable:
        if not isinstance(raw_document, dict):
            continue
        if str(raw_document.get("format") or "").strip().lower() != ITEM_FILE_FORMAT:
            continue
        payload_data = raw_document.get("payload")
        if not isinstance(payload_data, dict):
            continue
        item_id = item_id_from_payload(payload_data)
        if not item_id:
            continue
        document_copy = json.loads(json.dumps(raw_document))
        documents[item_id] = document_copy
    return documents


def _looks_generated_item_label(raw: object) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    compact = re.sub(r"[^a-z0-9]", "", text.casefold())
    if not compact:
        return False
    if len(compact) >= 20 and re.fullmatch(r"[a-f0-9]+", compact):
        return True
    if re.fullmatch(r"item[0-9a-f]{8,}", compact):
        return True
    if re.fullmatch(r"[a-z]{1,8}[0-9]{10,}", compact):
        return True
    return False


def _humanize_item_token(raw: object) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    stem = Path(text).stem
    token = stem or text
    token = re.sub(r"[_\-]+", " ", token).strip()
    token = " ".join(token.split())
    if not token:
        return ""
    lower = token.casefold()
    if lower.startswith("item "):
        suffix = token[5:].strip()
        if not suffix or suffix.isdigit() or _looks_generated_item_label(suffix):
            return "Unknown Item"
        token = suffix
    if _looks_generated_item_label(token):
        return "Unknown Item"
    words = token.split(" ")
    return " ".join(
        word if any(ch.isupper() for ch in word[1:]) else word.capitalize()
        for word in words
    ).strip()


def _resolve_human_item_title(
    item_id: object,
    *,
    title: object = "",
    name: object = "",
    normalized_name: object = "",
    fallback: str = "Item",
) -> str:
    explicit_candidates = [str(title or "").strip(), str(name or "").strip()]
    for candidate in explicit_candidates:
        if candidate and not _looks_generated_item_label(candidate):
            return candidate
    for candidate in (
        explicit_candidates
        + [str(normalized_name or "").strip(), str(item_id or "").strip()]
    ):
        humanized = _humanize_item_token(candidate)
        if humanized:
            return humanized
    return str(fallback or "Item").strip() or "Item"


def _validate_online_icon_payload(raw: bytes) -> tuple[bool, str]:
    if not raw:
        return False, "Icon payload is empty"
    if len(raw) > MAX_ONLINE_ICON_BYTES:
        return False, "Icon too large"
    image = QImage.fromData(raw)
    if image.isNull():
        return False, "Invalid icon image"
    return True, ""


class _LootPreviewListEventFilter(QObject):
    def __init__(
        self,
        list_widget: QListWidget,
        *,
        show_preview: Callable[[QListWidgetItem, QPoint], None],
        hide_preview: Callable[[], None],
    ) -> None:
        super().__init__(list_widget)
        self._list_widget = list_widget
        self._show_preview = show_preview
        self._hide_preview = hide_preview

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is not self._list_widget.viewport():
            return False
        event_type = event.type()
        if event_type == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
            pos = event.position().toPoint()
            item = self._list_widget.itemAt(pos)
            if item is None:
                self._hide_preview()
            else:
                global_pos = self._list_widget.viewport().mapToGlobal(pos)
                self._show_preview(item, global_pos)
        elif event_type in (
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
        ):
            self._hide_preview()
        return False


def _in_test_env() -> bool:
    if os.environ.get("DMT_TEST_MODE") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def _machine_entropy_string() -> str:
    return machine_entropy_string()


def _generate_probabilistic_unique_id(prefix: str) -> str:
    return generate_probabilistic_unique_id(prefix)


def _extract_character_stats_from_pdf(pdf_path: str) -> dict:
    field_map = {
        "name": ["CharacterName", "Character Name", "Character_Name", "Name"],
        "strength": ["STR", "Strength", "Strength Score", "STR Score"],
        "dexterity": ["DEX", "Dexterity", "Dexterity Score", "DEX Score"],
        "constitution": ["CON", "Constitution", "Constitution Score", "CON Score"],
        "intelligence": ["INT", "Intelligence", "Intelligence Score", "INT Score"],
        "wisdom": ["WIS", "Wisdom", "Wisdom Score", "WIS Score"],
        "charisma": ["CHA", "Charisma", "Charisma Score", "CHA Score"],
        "ac": ["AC", "ArmorClass", "Armor Class", "Armour Class"],
        "hp_max": ["HPMax", "HP Max", "HitPoints", "Hit Points", "MaxHP", "HPmax"],
        "hp_current": ["HPCurrent", "CurrentHP", "Current Hit Points", "HP"],
    }

    def _parse_int(value: object) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        match = re.search(r"-?\d+", text)
        if not match:
            return None
        try:
            return int(match.group(0))
        except (TypeError, ValueError):
            return None

    def _normalize_field_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _extract_candidates(values: dict[str, str], candidates: list[str]) -> str | None:
        for candidate in candidates:
            candidate_key = _normalize_field_key(candidate)
            if not candidate_key:
                continue
            direct = values.get(candidate_key)
            if direct:
                return direct
            for key, value in values.items():
                if key.startswith(candidate_key):
                    suffix = key[len(candidate_key) :]
                    if not suffix or suffix.isdigit():
                        return value
        return None

    def _extract_pdf_literal(value: bytes) -> str:
        # Decode escaped PDF literal strings used in AcroForm /T and /V fields.
        decoded = value.decode("latin-1", errors="ignore")
        decoded = re.sub(
            r"\\([0-7]{1,3})",
            lambda match: chr(int(match.group(1), 8)),
            decoded,
        )
        decoded = decoded.replace("\\n", "\n")
        decoded = decoded.replace("\\r", "\r")
        decoded = decoded.replace("\\t", "\t")
        decoded = decoded.replace("\\b", "\b")
        decoded = decoded.replace("\\f", "\f")
        decoded = decoded.replace("\\(", "(")
        decoded = decoded.replace("\\)", ")")
        decoded = decoded.replace("\\\\", "\\")
        return decoded.strip()

    output = {
        "name": None,
        "strength": None,
        "dexterity": None,
        "constitution": None,
        "intelligence": None,
        "wisdom": None,
        "charisma": None,
        "ac": None,
        "hp_max": None,
        "hp_current": None,
        "hp": None,
    }

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        PdfReader = None  # type: ignore

    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            fields = reader.get_fields() or {}
            field_values: dict[str, str] = {}
            for field_name, raw_field in fields.items():
                if not isinstance(field_name, str):
                    continue
                raw_val = None
                if isinstance(raw_field, dict):
                    raw_val = raw_field.get("/V")
                if raw_val is None:
                    continue
                clean = str(raw_val).strip()
                if not clean:
                    continue
                field_values[_normalize_field_key(field_name)] = clean

            for key, candidates in field_map.items():
                clean = _extract_candidates(field_values, candidates)
                if not clean:
                    continue
                output[key] = clean if key == "name" else _parse_int(clean)
        except Exception:
            pass

    missing = [key for key, value in output.items() if value is None and key != "hp"]
    if missing:
        # Fallback for environments without pypdf: parse raw AcroForm tokens directly.
        # This follows the same intent as tmp.py (AcroForm first, text fallback second).
        try:
            token_values: dict[str, str] = {}
            raw_bytes = Path(pdf_path).read_bytes()
            pattern = re.compile(
                rb"/T\(((?:\\.|[^\\)])*)\)(?:(?!endobj).){0,1200}?/V\(((?:\\.|[^\\)])*)\)",
                re.DOTALL,
            )
            for match in pattern.finditer(raw_bytes):
                name = _extract_pdf_literal(match.group(1))
                value = _extract_pdf_literal(match.group(2))
                if not name or not value:
                    continue
                token_values[_normalize_field_key(name)] = value
            for key in missing:
                candidates = field_map.get(key)
                if not candidates:
                    continue
                clean = _extract_candidates(token_values, candidates)
                if not clean:
                    continue
                output[key] = clean if key == "name" else _parse_int(clean)
        except Exception:
            pass

    missing = [key for key, value in output.items() if value is None]
    if not [key for key in missing if key != "hp"]:
        if output.get("hp") is None:
            if isinstance(output.get("hp_max"), int):
                output["hp"] = output.get("hp_max")
            elif isinstance(output.get("hp_current"), int):
                output["hp"] = output.get("hp_current")
        return output

    # Text fallback for non-acroform or partially-populated form PDFs.
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(pdf_path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return output

    def _find(pattern: str) -> str | None:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    text_values = {
        "name": _find(r"Character\s*Name\s*[:\s]+([^\n\r]+)"),
        "strength": _find(r"\bSTR(?:ength)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "dexterity": _find(r"\bDEX(?:terity)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "constitution": _find(r"\bCON(?:stitution)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "intelligence": _find(r"\bINT(?:elligence)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "wisdom": _find(r"\bWIS(?:dom)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "charisma": _find(r"\bCHA(?:risma)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "ac": _find(r"\bAC\b\D{0,10}(\d{1,3})"),
        "hp_max": _find(r"\bHP(?:\s*Max(?:imum)?)?\b\D{0,10}(\d{1,3})"),
        "hp_current": _find(r"\bCurrent\s*Hit\s*Points?\b\D{0,10}(\d{1,3})"),
    }
    for key in missing:
        candidate = text_values.get(key)
        if candidate is None:
            continue
        if key == "name":
            output[key] = candidate
        else:
            output[key] = _parse_int(candidate)
    if output.get("hp") is None:
        if isinstance(output.get("hp_max"), int):
            output["hp"] = output.get("hp_max")
        elif isinstance(output.get("hp_current"), int):
            output["hp"] = output.get("hp_current")
    return output


def _serialize_path(path: QPainterPath) -> list[dict]:
    elements: list[dict] = []
    if path is None:
        return elements
    for index in range(path.elementCount()):
        element = path.elementAt(index)
        element_type = getattr(element, "type", None)
        if hasattr(element_type, "value"):
            element_type_value = int(element_type.value)
        else:
            element_type_value = int(element_type)
        elements.append(
            {
                "type": element_type_value,
                "x": float(element.x),
                "y": float(element.y),
            }
        )
    return elements


def _deserialize_path(elements: list[dict]) -> QPainterPath:
    path = QPainterPath()
    if not elements:
        return path
    move_to = int(QPainterPath.ElementType.MoveToElement.value)
    line_to = int(QPainterPath.ElementType.LineToElement.value)
    curve_to = int(QPainterPath.ElementType.CurveToElement.value)
    index = 0
    while index < len(elements):
        element = elements[index]
        element_type = int(element.get("type", 0))
        x = float(element.get("x", 0.0))
        y = float(element.get("y", 0.0))
        if element_type == move_to:
            path.moveTo(x, y)
            index += 1
            continue
        if element_type == line_to:
            path.lineTo(x, y)
            index += 1
            continue
        if element_type == curve_to:
            if index + 2 < len(elements):
                ctrl_two = elements[index + 1]
                end_point = elements[index + 2]
                path.cubicTo(
                    x,
                    y,
                    float(ctrl_two.get("x", 0.0)),
                    float(ctrl_two.get("y", 0.0)),
                    float(end_point.get("x", 0.0)),
                    float(end_point.get("y", 0.0)),
                )
                index += 3
            else:
                path.lineTo(x, y)
                index += 1
            continue
        path.lineTo(x, y)
        index += 1
    return path


def _extract_room_floor_path(room) -> QPainterPath:
    from dungeon_items import WallItem
    for child in room.childItems():
        if isinstance(child, WallItem):
            continue
        if isinstance(child, QGraphicsPathItem):
            path = child.path()
        else:
            path = child.shape()
        return path.translated(child.pos())
    return QPainterPath()


def _add_walls_from_path(room, path: QPainterPath) -> None:
    if path.isEmpty():
        return
    polygons = path.toSubpathPolygons()
    for poly in polygons:
        if poly.count() > 1:
            for i in range(poly.count()):
                p1 = poly[i]
                p2 = poly[(i + 1) % poly.count()]
                if (p1 - p2).manhattanLength() > 0.1:
                    room.add_wall(p1.x(), p1.y(), p2.x(), p2.y())


def _default_item_z(item_type: str, layer: str) -> float:
    """Default z-values used when loading legacy states without explicit z data."""
    if item_type == "room":
        if layer == LAYER_MID:
            return -50.0
        if layer == LAYER_BG:
            return -100.0
        return 0.0
    if item_type == "entity":
        if layer == LAYER_MID:
            return -40.0
        if layer == LAYER_BG:
            return -90.0
        return 10.0
    if item_type == "stroke":
        if layer == LAYER_MID:
            return 255.0
        if layer == LAYER_BG:
            return 205.0
        return 305.0
    if item_type == "image":
        if layer == LAYER_MID:
            return -45.0
        if layer == LAYER_BG:
            return -95.0
        return 5.0
    return 0.0


ONLINE_MODE_LOCAL_DM = "local_dm"
ONLINE_MODE_DM_HOST = "online_dm"
ONLINE_MODE_PLAYER = "online_player"
SESSION_ICON_PREFIX = "session_icon://"
PLAYER_ALLOWED_TOOLS = {
    ToolType.SELECT,
    ToolType.FREE_DRAW,
    ToolType.ERASER,
    ToolType.PING,
}
LOOT_RESULT_EXTENSION = ".dmtloot"


class SessionChatPanel(QFrame):
    messageSubmitted = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SubPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Session Chat", self)
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self.output = QTextEdit(self)
        self.output.setObjectName("TerminalOutput")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Chat messages appear here...")
        self.output.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.output, 1)

        self.input = QLineEdit(self)
        self.input.setObjectName("TerminalInput")
        self.input.setPlaceholderText("Type message and press Enter")
        self.input.returnPressed.connect(self._submit)
        layout.addWidget(self.input)

    def _submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.messageSubmitted.emit(text)
        self.input.clear()

    def append_message(self, actor_name: str, text: str, system: bool = False) -> None:
        safe_actor = actor_name.strip() or "Player"
        safe_text = text.strip()
        if not safe_text:
            return
        prefix = "[SYSTEM]" if system else safe_actor
        self.output.append(f"{prefix}: {safe_text}")


class ServerLogPanel(QFrame):
    ignoreOverwriteToggled = Signal(bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SubPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        title = QLabel("Server Log", self)
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self._ignore_overwrite_checkbox = QCheckBox("Ignore player overwrite requests", self)
        self._ignore_overwrite_checkbox.setChecked(False)
        self._ignore_overwrite_checkbox.toggled.connect(self.ignoreOverwriteToggled.emit)
        layout.addWidget(self._ignore_overwrite_checkbox)

        self.output = QTextEdit(self)
        self.output.setObjectName("TerminalOutput")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Server events appear here...")
        self.output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.output, 1)

    def append_log(self, line: str) -> None:
        text = line.rstrip()
        if not text:
            return
        self.output.append(text)

    def set_ignore_overwrite_visible(self, visible: bool) -> None:
        self._ignore_overwrite_checkbox.setVisible(bool(visible))

    def set_ignore_overwrite_checked(self, checked: bool) -> None:
        blocker = QSignalBlocker(self._ignore_overwrite_checkbox)
        self._ignore_overwrite_checkbox.setChecked(bool(checked))
        del blocker


class SessionPanelsToggleButton(QAbstractButton):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._expanded = True
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(110, 18)
        self.setToolTip("Collapse chat and server log")

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        if self._expanded:
            self.setToolTip("Collapse chat and server log")
        else:
            self.setToolTip("Expand chat and server log")
        self.update()

    def is_expanded(self) -> bool:
        return self._expanded

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            width = float(self.width())
            height = float(self.height())
            center_x = width / 2.0
            center_y = height / 2.0

            caret_color = QColor(229, 231, 235, 212 if self._hovered else 160)
            caret_pen = QPen(caret_color, 2.2)
            caret_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            caret_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(caret_pen)

            half = min(28.0, width * 0.30)
            if self._expanded:
                left = QPointF(center_x - half, center_y - 2.4)
                middle = QPointF(center_x, center_y + 2.4)
                right = QPointF(center_x + half, center_y - 2.4)
            else:
                left = QPointF(center_x - half, center_y + 2.4)
                middle = QPointF(center_x, center_y - 2.4)
                right = QPointF(center_x + half, center_y + 2.4)

            caret_path = QPainterPath()
            caret_path.moveTo(left)
            caret_path.lineTo(middle)
            caret_path.lineTo(right)
            painter.drawPath(caret_path)
        finally:
            if painter.isActive():
                painter.end()

class DungeonCanvas(QGraphicsView):
    mouseMoved = Signal(QPointF)
    zoomChanged = Signal(float)
    viewChanged = Signal(QPointF)
    toolChanged = Signal(ToolType)
    pingPlaced = Signal(QPointF)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._scene.setSceneRect(-50000, -50000, 100000, 100000)
        self.setScene(self._scene)
        
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setBackgroundBrush(QColor("#09090b"))
        self.setMouseTracking(True)
        
        self.grid_size = GRID_SIZE
        self._is_panning = False
        self._panning = False
        self._last_mouse_pos = QPointF()
        self._last_pan_point = None
        self._current_zoom = 1.0
        self._current_tool = ToolType.SELECT
        self.snap_to_grid = True
        self._stroke_color = QColor(WALL_COLOR)
        self._stroke_owner_player_id = ""
        self._interaction_blocked_checker: Callable[[], bool] | None = None
        self._delete_change_callback: Callable[[], None] | None = None
        
        # Undo stack for commands
        self.undo_stack = QUndoStack(self)
        
        # State machine
        self._states = {}
        self._current_state = None
        self.fog_item = None
        self._init_states()
        
        self.centerOn(0, 0)
        self._view_mode = "dm"
        self.set_current_layer(LAYER_FG)
    
    def _init_states(self):
        """Initialize state machine for different tools."""
        self._states = {
            ToolType.SELECT: SelectState(self),
            ToolType.FREE_DRAW: FreeDrawState(self),  # Free-form strokes
            ToolType.RECTANGLE: DrawingRectState(self, TOOL_ROOM),
            ToolType.CIRCLE: DrawingEllipseState(self),
            ToolType.POLYGON: DrawingPolygonState(self),
            ToolType.ENTITY: PlacingState(self, 'entity'),
            ToolType.ENCOUNTER: EncounterPlacingState(self),
            ToolType.ERASER: EraserState(self),  # Eraser tool
            ToolType.PING: PingState(self),
            ToolType.IMAGE: ImagePlacingState(self),
            ToolType.FOW_BRUSH: FogState(self, TOOL_FOW_BRUSH),
            ToolType.FOW_ERASER: FogState(self, TOOL_FOW_ERASER),
        }
        self._set_state(ToolType.SELECT)

    def _set_state(self, tool: ToolType):
        """Switch to a new tool state."""
        if self._current_state:
            self._current_state.on_exit()
        
        # Clear selection when switching to a drawing/placement tool
        if tool != ToolType.SELECT and self.scene():
            self.scene().clearSelection()

        self._current_tool = tool
        self._current_state = self._states.get(tool)
        if self._current_state:
            self._current_state.on_enter()
        self.toolChanged.emit(tool)

    @property
    def current_tool(self) -> ToolType:
        return self._current_tool

    @current_tool.setter
    def current_tool(self, tool: ToolType):
        self._set_state(tool)

    @property
    def stroke_color(self) -> QColor:
        return QColor(self._stroke_color)

    def set_stroke_color(self, color: QColor | str) -> None:
        if isinstance(color, QColor):
            next_color = QColor(color)
        else:
            next_color = QColor(str(color))
        if not next_color.isValid():
            return
        self._stroke_color = next_color

    def set_stroke_owner_player_id(self, player_id: str) -> None:
        self._stroke_owner_player_id = str(player_id or "").strip()

    def set_interaction_blocked_checker(
        self,
        checker: Callable[[], bool] | None,
    ) -> None:
        self._interaction_blocked_checker = checker

    def _interactions_blocked(self) -> bool:
        checker = self._interaction_blocked_checker
        if checker is None:
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def wheelEvent(self, event: QWheelEvent) -> None:
        modifiers = event.modifiers()
        
        # Sideways scrolling: Ctrl + Shift + Scroll
        if modifiers & Qt.KeyboardModifier.ControlModifier and modifiers & Qt.KeyboardModifier.ShiftModifier:
            delta = event.angleDelta().y()
            h_bar = self.horizontalScrollBar()
            h_bar.setValue(h_bar.value() - delta)
            event.accept()
            return

        # Zooming: Ctrl + Scroll
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def _get_center_scene_pos(self) -> QPointF:
        center_view = QPointF(self.viewport().width() / 2.0, self.viewport().height() / 2.0)
        inverse, ok = self.viewportTransform().inverted()
        if ok:
            return inverse.map(center_view)
        return self.mapToScene(int(center_view.x()), int(center_view.y()))

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        self.viewChanged.emit(self._get_center_scene_pos())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.viewChanged.emit(self._get_center_scene_pos())

    def zoom_in(self):
        factor = 1.2
        new_zoom = self._current_zoom * factor
        if new_zoom <= 10.0: # Max 1000%
            self._current_zoom = new_zoom
            self.scale(factor, factor)
            self.zoomChanged.emit(self._current_zoom)
            self.viewChanged.emit(self._get_center_scene_pos())

    def zoom_out(self):
        factor = 1 / 1.2
        new_zoom = self._current_zoom * factor
        if new_zoom >= 0.01: # Min 1%
            self._current_zoom = new_zoom
            self.scale(factor, factor)
            self.zoomChanged.emit(self._current_zoom)
            self.viewChanged.emit(self._get_center_scene_pos())

    def reset_view(self):
        self.centerOn(0, 0)
        self.viewChanged.emit(QPointF(0, 0))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        
        # Filter interaction to current layer
        if event.button() == Qt.MouseButton.LeftButton:
            # Check what's at the cursor
            items_at_pos = self.scene().items(scene_pos)
            top_matching = None
            top_any = None
            
            for item in items_at_pos:
                if top_any is None:
                    top_any = item
                
                layer = item.data(ROLE_LAYER) or LAYER_FG
                if layer == self._current_layer:
                    top_matching = item
                    break
            
            # If there's an item but it's NOT on the current layer, 
            # consume the event to prevent background selection/moving.
            if top_any and not top_matching:
                self.scene().clearSelection()
                event.accept()
                return

        # Let state handle the event first
        handled = False
        if self._current_state:
            handled = self._current_state.mousePressEvent(event, scene_pos)
        
        if handled:
            event.accept()
            return

        # Panning with right/middle button
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._is_panning = True
            self._pan_start = event.position()
            self._pan_start_scene = scene_pos
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        
        # Don't snap coordinate display if Alt is held
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            self.mouseMoved.emit(scene_pos)
        else:
            # Existing behavior: states might emit snapped pos, but we emit raw pos here?
            # Actually, self.mouseMoved is connected to self._update_coords.
            self.mouseMoved.emit(scene_pos)

        # Let state handle the event
        handled = False
        if self._current_state:
            handled = bool(self._current_state.mouseMoveEvent(event, scene_pos))
        if handled:
            event.accept()
            return

        if self._is_panning:
            # Calculate the difference in scene coords and center on new position
            rect = self.viewport().rect()
            current_center = self.mapToScene(rect).boundingRect().center()
            scene_delta = scene_pos - self._pan_start_scene
            new_center = current_center - scene_delta
            self.centerOn(new_center)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        # Let state handle the event
        handled = False
        if self._current_state:
            handled = bool(self._current_state.mouseReleaseEvent(event, scene_pos))
        if handled:
            event.accept()
            return
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._is_panning = False
            if self._current_state:
                self._current_state.on_enter()  # Restore state cursor
            else:
                self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
    
    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self._current_state:
            self._current_state.mouseDoubleClickEvent(event)
        super().mouseDoubleClickEvent(event)
    
    def _place_entity(self, scene_pos: QPointF):
        """Place an entity at the given position, snapped to cell CENTER."""
        from dungeon_items import EntityItem
        from dungeon_commands import CreateItemCommand
        from dungeon_constants import ROLE_KIND, GRID_SIZE
        
        # Snap to cell CENTER: use math.floor for proper handling of negative coords
        half_grid = GRID_SIZE / 2
        cell_x = math.floor(scene_pos.x() / GRID_SIZE)
        cell_y = math.floor(scene_pos.y() / GRID_SIZE)
        snapped_x = cell_x * GRID_SIZE + half_grid
        snapped_y = cell_y * GRID_SIZE + half_grid
        snapped_pos = QPointF(snapped_x, snapped_y)
        
        entity = EntityItem(snapped_pos)
        entity.set_view_mode(self._view_mode)
        if self._current_layer == LAYER_MID:
            entity.setZValue(entity.zValue() - 50)
        elif self._current_layer == LAYER_BG:
            entity.setZValue(entity.zValue() - 100)
        entity.setData(ROLE_LAYER, self._current_layer)
        entity.setData(ROLE_KIND, "entity")
        entity.setData(ROLE_ENTITY_ID, uuid.uuid4().hex)
        entity.setData(ROLE_OWNER_PLAYER_ID, "")
        entity.setData(ROLE_LINKED_SHEET_ID, "")
        entity.setData(ROLE_LINKED_SHEET_NAME, "")
        entity.setData(ROLE_LINKED_CHARACTER_ID, "")
        entity.linked_inventory = {}
        entity.setData(ROLE_ICON, "")
        cmd = CreateItemCommand(self.scene(), entity, "Place Entity")
        self.undo_stack.push(cmd)

    def get_encounter_data(self):
        """Prompt user to select an encounter using the custom selector dialog."""
        from PySide6.QtWidgets import QMessageBox, QDialog
        from ui.encounter_selector_dialog import EncounterSelectorDialog
        
        dialog = EncounterSelectorDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
            
        data = dialog.selected_data()
        if data is None:
            QMessageBox.warning(self, "Error", "Failed to load the selected encounter.")
            return None
            
        return data.get("monsters", [])

    def _spawn_encounter_entities(self, scene_pos: QPointF, monsters_data: list):
        """Spawn entities from encounter data arranged in a grid."""
        if not monsters_data:
            return

        from dungeon_items import EntityItem
        from dungeon_commands import CreateItemCommand
        from dungeon_constants import ROLE_KIND, ROLE_LABEL, GRID_SIZE
        
        # Expand monsters list by count
        all_entities = []
        for m_data in monsters_data:
            count = int(m_data.get("count", 1))
            for _ in range(count):
                all_entities.append(m_data)
                
        total_count = len(all_entities)
        if total_count == 0:
            return

        # Calculate grid size (n x n)
        n = math.ceil(math.sqrt(total_count))
        
        # Center of the initial click (snapped to grid center)
        half_grid = GRID_SIZE / 2
        center_cell_x = math.floor(scene_pos.x() / GRID_SIZE)
        center_cell_y = math.floor(scene_pos.y() / GRID_SIZE)
        
        # Calculate top-left offset to center the n x n grid around the click
        # If n is odd, center is center. If n is even, center is biased.
        # We want integer offsets relative to center cell index.
        # e.g. for n=2: indices 0, 1. Centering around 0.5. Start at -0.5?
        # Let's simple center the block of cells.
        start_col = -(n // 2)
        start_row = -(n // 2)
        
        self.undo_stack.beginMacro("Spawn Encounter")
        
        for i, m_data in enumerate(all_entities):
            # Grid position (row major)
            row_idx = i // n
            col_idx = i % n
            
            # Calculate target cell
            target_cell_x = center_cell_x + start_col + col_idx
            target_cell_y = center_cell_y + start_row + row_idx
            
            snapped_x = target_cell_x * GRID_SIZE + half_grid
            snapped_y = target_cell_y * GRID_SIZE + half_grid
            pos = QPointF(snapped_x, snapped_y)
            
            # Entity Stats
            name = m_data.get("name", "Unknown")
            hp = int(m_data.get("hp", 10))
            ac = int(m_data.get("ac", 10))
            strength = int(m_data.get("str", 10))
            dexterity = int(m_data.get("dex", 10))
            constitution = int(m_data.get("con", 10))
            intelligence = int(m_data.get("int", 10))
            wisdom = int(m_data.get("wis", 10))
            charisma = int(m_data.get("cha", 10))
            actions = m_data.get("actions", "")
            description = m_data.get("description", "")
            icon_path = m_data.get("icon_path", "")
            
            # Create Entity
            # Red color for encounter entities: #EF4444
            entity = EntityItem(
                pos, 
                color=QColor("#EF4444"), 
                hp=hp, 
                max_hp=hp, 
                ac=ac,
                strength=strength,
                dexterity=dexterity,
                constitution=constitution,
                intelligence=intelligence,
                wisdom=wisdom,
                charisma=charisma,
                actions=actions,
                description=description,
                icon_path=icon_path,
            )
            entity.set_view_mode(self._view_mode)
            entity.setData(ROLE_KIND, "entity")
            entity.setData(ROLE_ENTITY_ID, uuid.uuid4().hex)
            entity.setData(ROLE_OWNER_PLAYER_ID, "")
            entity.setData(ROLE_LINKED_SHEET_ID, "")
            entity.setData(ROLE_LINKED_SHEET_NAME, "")
            entity.setData(ROLE_LINKED_CHARACTER_ID, "")
            entity.linked_inventory = {}
            entity.setData(ROLE_ICON, icon_path or "")
            
            # Layer assignment
            if self._current_layer == LAYER_MID:
                entity.setZValue(entity.zValue() - 50)
            elif self._current_layer == LAYER_BG:
                entity.setZValue(entity.zValue() - 100)
            entity.setData(ROLE_LAYER, self._current_layer)
            entity.setData(ROLE_LABEL, name)
            
            cmd = CreateItemCommand(self.scene(), entity, f"Spawn {name}")
            self.undo_stack.push(cmd)
            
        self.undo_stack.endMacro()

    def undo(self):
        if self._interactions_blocked():
            return
        self.undo_stack.undo()

    def redo(self):
        if self._interactions_blocked():
            return
        self.undo_stack.redo()

    def delete_selected_items(self):
        if self._interactions_blocked():
            return
        selected = self.scene().selectedItems()
        if not selected:
            return
        
        # Filter items: verify they are in the scene and safely deletable
        # (For now assuming all selectable items are deletable)
        from dungeon_commands import DeleteItemsCommand
        
        # Create a single command for all
        cmd = DeleteItemsCommand(
            self.scene(),
            selected,
            on_change=self._delete_change_callback,
        )
        self.undo_stack.push(cmd)

    def set_delete_change_callback(self, callback: Callable[[], None] | None) -> None:
        self._delete_change_callback = callback

    def show_ping(self, scene_pos: QPointF, *, emit_signal: bool = True) -> None:
        from dungeon_items import PingItem

        ping_item = PingItem(scene_pos)
        self.scene().addItem(ping_item)
        if emit_signal:
            self.pingPlaced.emit(QPointF(scene_pos))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()
        if self._interactions_blocked():
            if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
                event.accept()
                return
            if modifiers & Qt.KeyboardModifier.ControlModifier and key in (
                Qt.Key.Key_Z,
                Qt.Key.Key_Y,
            ):
                event.accept()
                return
        
        # Delete
        if key == Qt.Key.Key_Delete or key == Qt.Key.Key_Backspace:
            self.delete_selected_items()
            event.accept()
            return
        
        # Undo/Redo
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            if key == Qt.Key.Key_Z:
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    self.redo()
                else:
                    self.undo()
                event.accept()
                return
            elif key == Qt.Key.Key_Y:
                self.redo()
                event.accept()
                return
                
        super().keyPressEvent(event)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawBackground(painter, rect)

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        super().drawForeground(painter, rect)
        
        left = math.floor(rect.left() / self.grid_size) * self.grid_size
        top = math.floor(rect.top() / self.grid_size) * self.grid_size
        right = math.ceil(rect.right() / self.grid_size) * self.grid_size
        bottom = math.ceil(rect.bottom() / self.grid_size) * self.grid_size
        
        # Faint grid (semi-transparent)
        pen = QPen(QColor(63, 63, 70, 60), 1)
        painter.setPen(pen)
        
        for x in range(int(left), int(right) + 1, self.grid_size):
            painter.drawLine(x, int(top), x, int(bottom))
        for y in range(int(top), int(bottom) + 1, self.grid_size):
            painter.drawLine(int(left), y, int(right), y)

        # Draw a robust, tiny cross at (0,0) above everything
        size = 4
        origin_rect = QRectF(-size, -size, size * 2, size * 2)
        if rect.intersects(origin_rect):
            painter.setPen(QPen(QColor(255, 255, 255, 20), 1))
            painter.drawLine(-size, 0, size, 0)
            painter.drawLine(0, -size, 0, size)
        
        # Draw fog brush preview if in fog tool mode
        if hasattr(self, '_fog_preview_pos') and self._fog_preview_pos is not None:
            preview_radius = getattr(self, '_fog_preview_radius', GRID_SIZE)
            preview_rect = QRectF(
                self._fog_preview_pos.x() - preview_radius,
                self._fog_preview_pos.y() - preview_radius,
                preview_radius * 2,
                preview_radius * 2
            )
            if rect.intersects(preview_rect):
                painter.setPen(QPen(QColor(255, 255, 255, 180), 1, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(preview_rect)

    def init_fog(self):
        if not self.fog_item:
            self.fog_item = FogItem()
            # Start empty or full?
            # User workflow: Spawn fog everywhere (button). 
            # So init empty is fine, button fills.
            self._scene.addItem(self.fog_item)
            
    def fill_fog(self):
        if not self.fog_item:
            self.init_fog()
            
        # Create a massive rectangle to cover everything
        # We use a reasonably large bounds.
        # Ideally, we should cover sceneBoundingRect or similar, but scene grows.
        # Let's use the scene rect we set (-50k to 50k)
        rect = self.sceneRect()
        path = QPainterPath()
        path.addRect(rect)
        
        # Undoable
        from dungeon_commands import ModifyFogCommand
        cmd = ModifyFogCommand(self.fog_item, self.fog_item.path(), path)
        self.undo_stack.push(cmd)

    def clear_fog(self):
        if not self.fog_item:
            return
            
        # Empty path
        path = QPainterPath()
        
        # Undoable
        from dungeon_commands import ModifyFogCommand
        cmd = ModifyFogCommand(self.fog_item, self.fog_item.path(), path)
        self.undo_stack.push(cmd)

    def set_view_mode(self, mode: str):
        self._view_mode = mode
        if self.fog_item:
            self.fog_item.set_view_mode(mode)
        
        from dungeon_items import EntityItem
        for item in self.scene().items():
            if isinstance(item, EntityItem):
                item.set_view_mode(mode)

    def set_current_layer(self, layer: str):
        self._current_layer = layer
        # Clear selection when switching layers to prevent cross-layer manipulation
        if self.scene():
            self.scene().clearSelection()
            
            from dungeon_items import DungeonImageItem
            # Update all items to be interactive only if they are on the current layer
            for item in self.scene().items():
                # Only manage items that are meant to be interactive (Rooms, entities, images, strokes)
                # These usually have ROLE_KIND set, or are specific classes.
                is_user_item = (item.data(ROLE_KIND) is not None or isinstance(item, DungeonImageItem))
                
                if is_user_item:
                    item_layer = item.data(ROLE_LAYER) or LAYER_FG
                    is_active = (item_layer == self._current_layer)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, is_active)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, is_active)

class ToolButton(QPushButton):
    def __init__(self, tool_type: ToolType, icon_path: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.tool_type = tool_type
        self.setCheckable(True)
        self.setFixedSize(40, 40)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        
        if os.path.exists(icon_path):
            self.setIcon(QIcon(icon_path))
            self.setIconSize(QSize(24, 24))
        
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 4px;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QPushButton:checked {
                background-color: rgba(255, 255, 255, 50);
                border: 1px solid rgba(255, 255, 255, 80);
            }
        """)

class DrawColorButton(QPushButton):
    colorPicked = Signal(QColor)

    def __init__(self, color: QColor, parent=None):
        super().__init__(parent)
        self._color = QColor(color)
        self._selected = False
        self._hovered = False
        self._reveal_progress = 0.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(32, 32)
        self.setToolTip(f"Draw Color: {self._color.name()}")
        self.setStyleSheet("QPushButton { background-color: transparent; border: none; padding: 0px; margin: 0px; }")

    def _get_reveal_progress(self) -> float:
        return float(self._reveal_progress)

    def _set_reveal_progress(self, value: float) -> None:
        self._reveal_progress = max(0.0, min(1.0, float(value)))
        self.update()

    revealProgress = Property(float, fget=_get_reveal_progress, fset=_set_reveal_progress)

    @property
    def color(self) -> QColor:
        return QColor(self._color)

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        self.update()

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.colorPicked.emit(self.color)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, _event) -> None:
        if self._reveal_progress <= 0.001:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            base_alpha = int(255 * self._reveal_progress)
            edge_alpha = int(170 * self._reveal_progress)
            center = QPointF(self.width() / 2.0, self.height() / 2.0)
            max_radius = max(2.0, (min(self.width(), self.height()) / 2.0) - 5.2)
            radius = max_radius * self._reveal_progress

            fill = QColor(self._color)
            fill.setAlpha(base_alpha)
            edge = QColor(255, 255, 255, edge_alpha)
            if self._hovered:
                edge = QColor(255, 255, 255, min(255, edge_alpha + 45))
            painter.setBrush(fill)
            painter.setPen(QPen(edge, 1.2))
            painter.drawEllipse(center, radius, radius)

            if self._selected:
                ring = QColor(147, 197, 253, int(220 * self._reveal_progress))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(ring, 2.2))
                painter.drawEllipse(center, radius + 2.2, radius + 2.2)
        finally:
            if painter.isActive():
                painter.end()


class DrawColorRail(QWidget):
    colorChanged = Signal(QColor)
    _ANIM_SLOWDOWN = 1.35

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DrawColorRail")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._buttons: list[DrawColorButton] = []
        self._anims: list[QPropertyAnimation] = []
        self._selected_color = QColor(WALL_COLOR)
        self._is_expanded = False

        self._rail = QFrame(self)
        self._rail.setObjectName("DrawColorRailFrame")
        self._rail.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._rail.setStyleSheet(
            f"""
            #DrawColorRailFrame {{
                background-color: {OVERLAY_BG_RGBA};
                border-radius: 8px;
                border: 1px solid {OVERLAY_BORDER_RGBA};
            }}
            """
        )
        rail_layout = QVBoxLayout(self._rail)
        rail_layout.setContentsMargins(6, 8, 6, 8)
        rail_layout.setSpacing(5)
        rail_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        palette = [
            "#ffffff",
            "#334155",
            "#3b82f6",
            "#facc15",
            "#22c55e",
            "#ef4444",
        ]
        for color_hex in palette:
            button = DrawColorButton(QColor(color_hex), self._rail)
            button.colorPicked.connect(self._on_color_picked)
            button._set_reveal_progress(0.0)
            rail_layout.addWidget(button)
            self._buttons.append(button)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._rail)
        self._apply_fixed_size(rail_layout)
        self.set_color(self._selected_color, emit_signal=False)
        self.hide()

    def _apply_fixed_size(self, rail_layout: QVBoxLayout) -> None:
        if not self._buttons:
            return
        margins = rail_layout.contentsMargins()
        spacing = rail_layout.spacing()
        button_w = max(btn.width() for btn in self._buttons)
        button_h = max(btn.height() for btn in self._buttons)
        button_count = len(self._buttons)
        content_w = margins.left() + margins.right() + button_w
        content_h = margins.top() + margins.bottom() + (button_h * button_count) + (max(0, button_count - 1) * spacing)
        self._rail.setFixedSize(content_w, content_h)
        self.setFixedSize(content_w, content_h)

    def _clear_animations(self) -> None:
        for anim in self._anims:
            anim.stop()
        self._anims.clear()

    def _animate_button(self, button: DrawColorButton, start: float, end: float, delay_ms: int) -> None:
        anim = QPropertyAnimation(button, b"revealProgress", self)
        anim.setStartValue(float(start))
        anim.setEndValue(float(end))
        anim.setDuration(int(round(85 * self._ANIM_SLOWDOWN)))
        anim.setEasingCurve(QEasingCurve.Type.OutCubic if end >= start else QEasingCurve.Type.InCubic)
        self._anims.append(anim)
        QTimer.singleShot(max(0, int(delay_ms)), anim.start)

    def _on_color_picked(self, color: QColor) -> None:
        self.set_color(color, emit_signal=True)

    def set_color(self, color: QColor, *, emit_signal: bool = True) -> None:
        self._selected_color = QColor(color)
        for button in self._buttons:
            button.set_selected(button.color.name().lower() == self._selected_color.name().lower())
        if emit_signal:
            self.colorChanged.emit(QColor(self._selected_color))

    def current_color(self) -> QColor:
        return QColor(self._selected_color)

    def show_animated(self) -> None:
        if self._is_expanded and self.isVisible():
            return
        self._clear_animations()
        self.setVisible(True)
        self._is_expanded = True
        per_item_delay = int(round(35 * self._ANIM_SLOWDOWN))
        for idx, button in enumerate(self._buttons):
            button._set_reveal_progress(0.0)
            self._animate_button(button, 0.0, 1.0, idx * per_item_delay)

    def hide_animated(self) -> None:
        self._clear_animations()
        if not self.isVisible() and not self._is_expanded:
            return
        self._is_expanded = False
        reversed_buttons = list(reversed(self._buttons))
        per_item_delay = int(round(28 * self._ANIM_SLOWDOWN))
        for idx, button in enumerate(reversed_buttons):
            self._animate_button(button, button.revealProgress, 0.0, idx * per_item_delay)
        final_delay = (max(1, len(reversed_buttons)) * per_item_delay) + int(round(100 * self._ANIM_SLOWDOWN))
        QTimer.singleShot(final_delay, self._hide_if_collapsed)

    def _hide_if_collapsed(self) -> None:
        if self._is_expanded:
            return
        self.hide()

class ActionButton(QPushButton):
    """Button for one-off actions like 'Fill Fog' or Toggles."""
    def __init__(self, icon_path: str, tooltip: str, parent=None, checkable=False):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        if checkable:
            self.setCheckable(True)
        
        if os.path.exists(icon_path):
            self.setIcon(QIcon(icon_path))
            self.setIconSize(QSize(24, 24))
            
        self.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 4px;
                margin: 2px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QPushButton:checked {
                background-color: rgba(59, 130, 246, 100); /* Blue for toggle state */
                border: 1px solid rgba(59, 130, 246, 150);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 50);
            }
        """)

class FloatingToolPanel(QWidget):
    toolChanged = Signal(ToolType)
    drawColorChanged = Signal(QColor)
    fogFillRequested = Signal()
    fogClearRequested = Signal()
    viewModeChanged = Signal(str) # "dm" or "player"
    undoRequested = Signal()
    redoRequested = Signal()
    deleteRequested = Signal()
    layerChanged = Signal(str) # "foreground" or "background"
    lootPoolRequested = Signal()
    lootAddItemsRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_layer = LAYER_FG
        self._tool_buttons: dict[ToolType, ToolButton] = {}
        self._action_buttons: list[QPushButton] = []
        self._online_action_buttons: list[QPushButton] = []
        self._default_grid_positions: dict[QWidget, tuple[int, int]] = {}
        self._draw_color_gap = 6
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.container = QFrame(self)
        self.container.setObjectName("ToolPanelContainer")
        self.container.setStyleSheet(f"""
            #ToolPanelContainer {{
                background-color: {OVERLAY_BG_RGBA};
                border-radius: 8px;
                border: 1px solid {OVERLAY_BORDER_RGBA};
            }}
        """)
        
        # Use Grid Layout for 2 columns
        self.layout = QGridLayout(self.container)
        self.layout.setContentsMargins(4, 4, 4, 4)
        self.layout.setSpacing(4)
        
        self.button_group = QButtonGroup(self)
        self.button_group.setExclusive(True)

        self._draw_color_rail = DrawColorRail(self)
        self._draw_color_rail.colorChanged.connect(self.drawColorChanged.emit)
        self._draw_color_slot_width = max(32, int(self._draw_color_rail.sizeHint().width()))
        self._draw_color_rail.setFixedWidth(self._draw_color_slot_width)

        main_layout = QVBoxLayout(self)
        # Reserve fixed space on the right for the floating color rail so tool columns never shrink.
        main_layout.setContentsMargins(
            36,
            0,
            self._draw_color_slot_width + self._draw_color_gap,
            0,
        )
        main_layout.setSpacing(0)
        main_layout.addWidget(self.container, 0, Qt.AlignmentFlag.AlignTop)
        
        self._init_tools()
        QTimer.singleShot(0, self._position_draw_color_rail)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_draw_color_rail()

    def _position_draw_color_rail(self) -> None:
        if not hasattr(self, "_draw_color_rail"):
            return
        rail_x = self.container.x() + self.container.width() + self._draw_color_gap
        rail_x = min(max(0, rail_x), max(0, self.width() - self._draw_color_slot_width))
        rail_y = self.container.y()
        self._draw_color_rail.move(int(rail_x), int(rail_y))
        self._draw_color_rail.raise_()

    def _place_widget(self, widget: QWidget, row: int, col: int) -> None:
        self.layout.addWidget(widget, row, col)
        self._default_grid_positions[widget] = (row, col)

    def _init_tools(self):
        # Use local DMT icons (white versions for dark background)
        base_dir = os.path.dirname(__file__)
        icon_dir = os.path.abspath(os.path.join(base_dir, "..", "assets", "icons"))

        # Column 0: Creation & General Tools
        tools_col0 = [
            (ToolType.SELECT, os.path.join(icon_dir, "select.svg"), "Select (V)"),
            (ToolType.FREE_DRAW, os.path.join(icon_dir, "pen.svg"), "Free Draw (P)"),
            (ToolType.ERASER, os.path.join(icon_dir, "eraser.svg"), "Eraser (X)"),
            (ToolType.RECTANGLE, os.path.join(icon_dir, "rect.svg"), "Rectangle Room (R)"),
            (ToolType.CIRCLE, os.path.join(icon_dir, "ellipse.svg"), "Circle Room (C)"),
            (ToolType.POLYGON, os.path.join(icon_dir, "hexagon.svg"), "Polygon Room (G)"),
            (ToolType.ENTITY, os.path.join(icon_dir, "person.svg"), "Place Entity (E)"),
            (ToolType.ENCOUNTER, os.path.join(icon_dir, "encounter.svg"), "Add Encounter"),
        ]

        for i, (tool_type, icon_path, tooltip) in enumerate(tools_col0):
            btn = ToolButton(tool_type, icon_path, tooltip)
            self._place_widget(btn, i, 0)
            self.button_group.addButton(btn)
            self._tool_buttons[tool_type] = btn
            if tool_type == ToolType.SELECT:
                btn.setChecked(True)

        # Column 1: Special Tools & Actions
        # Tools first
        self.btn_image = ToolButton(ToolType.IMAGE, os.path.join(icon_dir, "image.svg"), "Add Image (I)")
        self._place_widget(self.btn_image, 0, 1)
        self.button_group.addButton(self.btn_image)
        self._tool_buttons[ToolType.IMAGE] = self.btn_image

        self.btn_ping = ToolButton(ToolType.PING, os.path.join(icon_dir, "ping.svg"), "Ping (T)")
        self._place_widget(self.btn_ping, 1, 1)
        self.button_group.addButton(self.btn_ping)
        self._tool_buttons[ToolType.PING] = self.btn_ping

        self.btn_fow = ToolButton(ToolType.FOW_BRUSH, os.path.join(icon_dir, "cloud.svg"), "Fog Brush")
        self._place_widget(self.btn_fow, 2, 1)
        self.button_group.addButton(self.btn_fow)
        self._tool_buttons[ToolType.FOW_BRUSH] = self.btn_fow
        
        self.btn_fow_eraser = ToolButton(ToolType.FOW_ERASER, os.path.join(icon_dir, "clean.svg"), "Fog Eraser")
        self._place_widget(self.btn_fow_eraser, 3, 1)
        self.button_group.addButton(self.btn_fow_eraser)
        self._tool_buttons[ToolType.FOW_ERASER] = self.btn_fow_eraser

        # Actions next
        self.btn_fill_fog = ActionButton(os.path.join(icon_dir, "fill.svg"), "Fill Fog Everywhere")
        self.btn_fill_fog.clicked.connect(self.fogFillRequested.emit)
        self._place_widget(self.btn_fill_fog, 4, 1)

        self.btn_clear_fog = ActionButton(os.path.join(icon_dir, "clear_fill.svg"), "Remove Fog Everywhere")
        self.btn_clear_fog.clicked.connect(self.fogClearRequested.emit)
        self._place_widget(self.btn_clear_fog, 5, 1)
        
        self.btn_view_toggle = ActionButton(os.path.join(icon_dir, "eye.svg"), "Toggle DM/Player View (Currently DM)", checkable=True)
        self.btn_view_toggle.clicked.connect(self._toggle_view_mode)
        self._place_widget(self.btn_view_toggle, 6, 1)

        # Layer Toggle
        self.layer_icons = {
            LAYER_FG: os.path.join(icon_dir, "layers_foreground.svg"),
            LAYER_MID: os.path.join(icon_dir, "layers_middle.svg"),
            LAYER_BG: os.path.join(icon_dir, "layers_background.svg")
        }
        self.btn_layer = ActionButton(self.layer_icons[LAYER_FG], "Current Layer: Foreground (L)")
        self.btn_layer.clicked.connect(self._toggle_layer)
        self._place_widget(self.btn_layer, 7, 1)
        self.btn_loot_panel = ActionButton(
            os.path.join(icon_dir, "lootpool.png"),
            "Show Loot Pool",
        )
        self.btn_loot_panel.clicked.connect(self.lootPoolRequested.emit)
        self._loot_pool_tool_badge = QLabel("!", self.btn_loot_panel)
        self._loot_pool_tool_badge.setFixedSize(14, 14)
        self._loot_pool_tool_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loot_pool_tool_badge.setStyleSheet(
            "background-color: #3b82f6; color: white; border-radius: 7px; font-size: 10px; font-weight: bold;"
        )
        self._loot_pool_tool_badge.hide()
        self._position_loot_pool_tool_badge()
        self._place_widget(self.btn_loot_panel, 8, 0)
        self.btn_loot_panel.setVisible(False)
        self.btn_loot_panel.setEnabled(False)

        self.btn_loot_add_items = ActionButton(
            os.path.join(icon_dir, "add_items.png"),
            "Add Backpack + Equipment to Loot Pool",
        )
        self.btn_loot_add_items.clicked.connect(self.lootAddItemsRequested.emit)
        self._place_widget(self.btn_loot_add_items, 8, 1)
        self.btn_loot_add_items.setVisible(False)
        self.btn_loot_add_items.setEnabled(False)

        self._online_action_buttons = [
            self.btn_loot_panel,
            self.btn_loot_add_items,
        ]
        self._action_buttons = [
            self.btn_fill_fog,
            self.btn_clear_fog,
            self.btn_view_toggle,
            self.btn_layer,
        ]

        self.button_group.buttonClicked.connect(self._on_button_clicked)
        self._update_draw_color_visibility()

    def _position_loot_pool_tool_badge(self) -> None:
        if not hasattr(self, "_loot_pool_tool_badge"):
            return
        badge = self._loot_pool_tool_badge
        btn = self.btn_loot_panel
        badge_x = 3
        badge_y = max(0, btn.height() - badge.height() - 3)
        badge.move(badge_x, badge_y)
        badge.raise_()

    def set_loot_pool_badge_visible(self, visible: bool) -> None:
        if not hasattr(self, "_loot_pool_tool_badge"):
            return
        self._position_loot_pool_tool_badge()
        self._loot_pool_tool_badge.setVisible(bool(visible))

    def _toggle_layer(self):
        if self._current_layer == LAYER_FG:
            self._current_layer = LAYER_MID
        elif self._current_layer == LAYER_MID:
            self._current_layer = LAYER_BG
        else:
            self._current_layer = LAYER_FG
            
        self.btn_layer.setIcon(QIcon(self.layer_icons[self._current_layer]))
        self.btn_layer.setToolTip(f"Current Layer: {self._current_layer.title()} (L)")
        self.layerChanged.emit(self._current_layer)

    def _toggle_view_mode(self, checked):
        if checked:
             self.btn_view_toggle.setToolTip("Toggle DM/Player View (Currently Player)")
             self.viewModeChanged.emit("player")
        else:
             self.btn_view_toggle.setToolTip("Toggle DM/Player View (Currently DM)")
             self.viewModeChanged.emit("dm")

    def _on_button_clicked(self, button: ToolButton):
        self._update_draw_color_visibility(button.tool_type)
        self.toolChanged.emit(button.tool_type)

    def set_tool(self, tool: ToolType):
        for btn in self.button_group.buttons():
            if isinstance(btn, ToolButton) and btn.tool_type == tool:
                btn.setChecked(True)
                break
        self._update_draw_color_visibility(tool)

    def _checked_tool(self) -> ToolType | None:
        for btn in self.button_group.buttons():
            if isinstance(btn, ToolButton) and btn.isChecked():
                return btn.tool_type
        return None

    def _update_draw_color_visibility(self, active_tool: ToolType | None = None) -> None:
        tool = active_tool if active_tool is not None else self._checked_tool()
        free_draw_btn = self._tool_buttons.get(ToolType.FREE_DRAW)
        can_show = (
            tool == ToolType.FREE_DRAW
            and free_draw_btn is not None
            and free_draw_btn.isVisible()
            and free_draw_btn.isEnabled()
        )
        if can_show:
            self._draw_color_rail.show_animated()
        else:
            self._draw_color_rail.hide_animated()
        self._position_draw_color_rail()

    def current_draw_color(self) -> QColor:
        return self._draw_color_rail.current_color()

    def set_draw_color(self, color: QColor) -> None:
        self._draw_color_rail.set_color(color, emit_signal=True)

    def button_for_tool(self, tool: ToolType) -> ToolButton | None:
        return self._tool_buttons.get(tool)

    def _restore_default_layout(self) -> None:
        for widget, (row, col) in self._default_grid_positions.items():
            self.layout.addWidget(widget, row, col)

    def _apply_player_layout(self) -> None:
        # Player view should be a single vertical stack:
        # select, free draw, eraser, ping (ping below the first three).
        ordered_tools = (
            ToolType.SELECT,
            ToolType.FREE_DRAW,
            ToolType.ERASER,
            ToolType.PING,
        )
        for row, tool_type in enumerate(ordered_tools):
            button = self._tool_buttons.get(tool_type)
            if button is None:
                continue
            self.layout.addWidget(button, row, 0)

    def set_player_tool_restrictions(self, enabled: bool, allowed_tools: set[ToolType] | None = None) -> None:
        if not enabled:
            self._restore_default_layout()
            for button in self._tool_buttons.values():
                button.setVisible(True)
                button.setEnabled(True)
            for button in self._action_buttons:
                button.setVisible(True)
                button.setEnabled(True)
            self._update_draw_color_visibility()
            self.container.adjustSize()
            self.adjustSize()
            self.updateGeometry()
            return

        allowed = set(allowed_tools or {ToolType.SELECT})
        for tool_type, button in self._tool_buttons.items():
            is_allowed = tool_type in allowed
            button.setVisible(is_allowed)
            button.setEnabled(is_allowed)
            if not is_allowed and button.isChecked():
                select_btn = self._tool_buttons.get(ToolType.SELECT)
                if select_btn is not None:
                    select_btn.setChecked(True)

        for button in self._action_buttons:
            button.setVisible(False)
            button.setEnabled(False)

        self._apply_player_layout()
        self._update_draw_color_visibility()
        self.container.adjustSize()
        self.adjustSize()
        self.updateGeometry()

    def set_online_loot_actions(
        self,
        *,
        show_pool: bool,
        show_add_items: bool,
        player_mode: bool,
    ) -> None:
        if player_mode:
            # Keep player layout compact: place loot-panel tool below ping.
            self.layout.addWidget(self.btn_loot_panel, 4, 0)
            # Keep add-items directly under loot pool in player mode.
            self.layout.addWidget(self.btn_loot_add_items, 5, 0)
        else:
            self.layout.addWidget(self.btn_loot_panel, 8, 0)
            self.layout.addWidget(self.btn_loot_add_items, 8, 1)

        self.btn_loot_panel.setVisible(show_pool)
        self.btn_loot_panel.setEnabled(show_pool)
        self.btn_loot_add_items.setVisible(show_add_items)
        self.btn_loot_add_items.setEnabled(show_add_items)
        if player_mode:
            self.btn_loot_add_items.setToolTip("Add Backpack + Equipment to Loot Pool")
        else:
            self.btn_loot_add_items.setToolTip("Add Items to Loot Pool")
        self._position_loot_pool_tool_badge()
        self._update_draw_color_visibility()
        self.container.adjustSize()
        self.adjustSize()
        self.updateGeometry()

class ClickableLabel(QLabel):
    clicked = Signal()
    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

class EditableStat(QWidget):
    valueChanged = Signal(int)
    
    def __init__(self, value: int, min_val=0, max_val=99, parent=None):
        super().__init__(parent)
        layout = QStackedWidget(self)
        self.setLayout(QVBoxLayout())
        self.layout().setContentsMargins(0,0,0,0)
        self.layout().addWidget(layout)
        
        self.val = value
        
        # Display Mode
        self.lbl = ClickableLabel(str(value))
        self.lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl.setStyleSheet("color: #fafafa; font-family: monospace; font-size: 12px; padding: 2px;")
        self.lbl.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lbl.clicked.connect(self._to_edit_mode)
        
        # Edit Mode
        self.spin = QSpinBox()
        self.spin.setRange(min_val, max_val)
        self.spin.setValue(value)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin.setStyleSheet("""
            QSpinBox {
                background-color: #27272a;
                color: #fafafa;
                border: 1px solid #3f3f46;
                border-radius: 4px;
                padding: 0px 4px;
                font-family: monospace;
            }
        """)
        self.spin.editingFinished.connect(self._to_display_mode)
        
        layout.addWidget(self.lbl)
        layout.addWidget(self.spin)
        self.stack = layout
        
    def _to_edit_mode(self):
        self.stack.setCurrentIndex(1)
        self.spin.setFocus()
        self.spin.selectAll()
        
    def _to_display_mode(self):
        val = self.spin.value()
        self.val = val
        self.lbl.setText(str(val))
        self.stack.setCurrentIndex(0)
        self.valueChanged.emit(val)

class StatRow(QWidget):
    def __init__(self, label: str, value: int, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        lbl_name = QLabel(label)
        lbl_name.setStyleSheet("color: #a1a1aa; font-weight: bold; font-size: 11px;")
        
        # Increased limit for stats
        self.edit = EditableStat(value, 0, 999)
        
        layout.addWidget(lbl_name)
        layout.addStretch()
        layout.addWidget(self.edit)

class BarStat(QWidget):
    def __init__(self, name, color, current=65, max_val=100, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        # Header + Values
        top_layout = QHBoxLayout()
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        top_layout.addWidget(name_lbl)
        top_layout.addStretch()
        
        # Editable Current
        self.curr_edit = QSpinBox()
        self.curr_edit.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.curr_edit.setRange(0, 9999)
        self.curr_edit.setValue(current)
        self.curr_edit.setFixedWidth(50) # Increased width
        self.curr_edit.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.curr_edit.setStyleSheet("background: transparent; color: #fafafa; border: none; font-family: monospace; font-size: 11px;")
        
        # Slash
        slash = QLabel("/")
        slash.setStyleSheet("color: #71717a; font-size: 11px;")
        
        # Editable Max
        self.max_edit = QSpinBox()
        self.max_edit.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.max_edit.setRange(1, 9999)
        self.max_edit.setValue(max_val)
        self.max_edit.setFixedWidth(50) # Increased width
        self.max_edit.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.max_edit.setStyleSheet("background: transparent; color: #71717a; border: none; font-family: monospace; font-size: 11px;")

        top_layout.addWidget(self.curr_edit)
        top_layout.addWidget(slash)
        top_layout.addWidget(self.max_edit)
        layout.addLayout(top_layout)
        
        # Bar
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.bar.setRange(0, max_val)
        self.bar.setValue(current)
        self.bar.setStyleSheet(f"""
            QProgressBar {{
                background-color: #27272a;
                border-radius: 3px;
                border: none;
            }}
            QProgressBar::chunk {{
                background-color: {color};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.bar)
        
        self.curr_edit.valueChanged.connect(self._update_bar)
        self.max_edit.valueChanged.connect(self._update_bar)

    def _update_bar(self):
        curr = self.curr_edit.value()
        mx = self.max_edit.value()
        self.bar.setRange(0, mx)
        self.bar.setValue(curr)

    def set_data(self, current: int, max_val: int):
        self.curr_edit.blockSignals(True)
        self.max_edit.blockSignals(True)
        self.curr_edit.setValue(current)
        self.max_edit.setValue(max_val)
        self.curr_edit.blockSignals(False)
        self.max_edit.blockSignals(False)
        self._update_bar()


class ShieldWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 44)
        
        self.spin = QSpinBox(self)
        self.spin.setRange(0, 99)
        self.spin.setValue(10)
        self.spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin.setStyleSheet("""
            background: transparent;
            color: #fafafa;
            font-weight: bold;
            font-size: 14px;
            border: none;
            padding: 0px; 
            margin: 0px;
        """)
        
        # Center the spinbox
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 8) # Padding to center text in shield body
        layout.addWidget(self.spin)
        
    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            w = self.width()
            h = self.height()

            # Shield path
            shield_path = QPainterPath()
            margin = 1
            x = margin
            y = margin
            sw = w - 2 * margin
            sh = h - 2 * margin

            cx = x + sw / 2

            # Shield geometry
            shield_path.moveTo(cx, y)
            shield_path.quadTo(x + sw, y, x + sw, y + sh * 0.3)
            shield_path.lineTo(x + sw, y + sh * 0.6)
            shield_path.lineTo(cx, y + sh)
            shield_path.lineTo(x, y + sh * 0.6)
            shield_path.lineTo(x, y + sh * 0.3)
            shield_path.quadTo(x, y, cx, y)
            shield_path.closeSubpath()

            # Fill
            painter.setPen(QPen(QColor("#52525b"), 1))
            painter.setBrush(QColor("#3f3f46"))
            painter.drawPath(shield_path)
        finally:
            if painter.isActive():
                painter.end()


class EntityInspectorPanel(QWidget):
    entityEdited = Signal()
    ownerChanged = Signal(str)
    iconPathSelected = Signal(str)
    linkCharacterRequested = Signal()
    unlinkCharacterRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entity = None
        self.undo_stack = None
        self._player_assignment_enabled = True
        self._link_character_enabled = True
        self._defer_icon_apply = False
        self._pending_changes = {}
        self._change_timer = QTimer(self)
        self._change_timer.setInterval(400) # 400ms debounce
        self._change_timer.setSingleShot(True)
        self._change_timer.timeout.connect(self._commit_changes)
        
        self.setMinimumWidth(260)
        self.setMaximumWidth(720)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.container = QFrame(self)
        self.container.setObjectName("InspectorContainer")
        self.container.setFixedWidth(260)
        self.container.setStyleSheet("""
            #InspectorContainer {
                background-color: rgba(9, 9, 11, 240);
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 20);
            }
            QLineEdit {
                background: transparent;
                border: 1px solid transparent;
                color: #fafafa;
                selection-background-color: #3f3f46;
            }
            QLineEdit:focus, QLineEdit:hover {
                background: rgba(255, 255, 255, 10);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 4px;
            }
            QToolButton#SecondaryButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
                border: 1px solid #3b424b;
                border-radius: 6px;
                padding: 6px 12px;
                min-height: 32px;
            }
            QToolButton#SecondaryButton[compact="true"] {
                padding: 4px;
                min-height: 32px;
                min-width: 0;
            }
            QToolButton#SecondaryButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
                border-color: #58a6ff;
            }
            QToolButton#DestructiveButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #da3633, stop:1 #b62324);
                border: 1px solid #f85149;
                border-radius: 6px;
                color: #ffffff;
                padding: 6px 12px;
                min-height: 32px;
            }
            QToolButton#DestructiveButton[compact="true"] {
                padding: 4px;
                min-height: 32px;
                min-width: 0;
            }
            QToolButton#DestructiveButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f85149, stop:1 #da3633);
                border-color: #ff7b72;
            }
            QCheckBox {
                color: #c9d1d9;
                spacing: 6px;
            }
            QToolButton#TokenToggleButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
                border: 1px solid #3b424b;
                border-radius: 7px;
                min-width: 34px;
                max-width: 34px;
                min-height: 34px;
                max-height: 34px;
                padding: 0px;
            }
            QToolButton#TokenToggleButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
                border-color: #58a6ff;
            }
            QToolButton#TokenToggleButton:checked {
                border-color: #58a6ff;
            }
        """)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        
        # Name (Editable) + token controls toggle
        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(10)
        self.token_expand_btn = QToolButton(self.container)
        self.token_expand_btn.setObjectName("TokenToggleButton")
        self.token_expand_btn.setCheckable(True)
        self.token_expand_btn.setChecked(False)
        self.token_expand_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.token_expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.token_expand_btn.setToolTip("Toggle token controls")
        self.token_expand_btn.setFixedSize(34, 34)
        self.token_expand_btn.setIcon(self._make_token_toggle_icon(expanded=False))
        self.token_expand_btn.setIconSize(QSize(11, 11))
        name_row.addWidget(self.token_expand_btn, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        self.name_edit = QLineEdit("Goblin Grunt")
        self.name_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name_edit.setStyleSheet("""
            font-size: 14px; 
            font-weight: bold; 
            color: #fafafa;
            border: none;
            background: transparent;
        """)
        name_row.addWidget(self.name_edit, 1)
        name_center_spacer = QWidget(self.container)
        name_center_spacer.setFixedSize(34, 34)
        name_center_spacer.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        name_row.addWidget(name_center_spacer, 0, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        layout.addLayout(name_row)

        # NPC Label
        self.type_lbl = QLabel("NPC")
        self.type_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.type_lbl.setStyleSheet("color: #3b82f6; font-weight: bold; font-size: 12px; margin-bottom: 4px;")
        layout.addWidget(self.type_lbl)
        
        # Divider
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: rgba(255, 255, 255, 20);")
        layout.addWidget(line)
        
        # HP Bar
        self.hp_stat = BarStat("HP", "#22c55e", 65, 100)
        layout.addWidget(self.hp_stat)


        
        # AC Section
        ac_layout = QHBoxLayout()
        ac_lbl = QLabel("Armor Class")
        ac_lbl.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        self.shield_widget = ShieldWidget()
        ac_layout.addWidget(ac_lbl)
        ac_layout.addStretch()
        ac_layout.addWidget(self.shield_widget)
        layout.addLayout(ac_layout)

        # Stats Grid
        stats_group = QWidget()
        stats_group.setStyleSheet("background-color: rgba(255,255,255,5); border-radius: 8px;")
        stats_layout = QVBoxLayout(stats_group)
        stats_layout.setContentsMargins(12, 12, 12, 12)
        stats_layout.setSpacing(6)
        
        # Ability scores
        self.stat_widgets = {}
        stat_names = ["STR", "DEX", "CON", "INT", "WIS", "CHA"]
        
        for name in stat_names:
            widget = StatRow(name, 10)
            stats_layout.addWidget(widget)
            self.stat_widgets[name] = widget
            
        layout.addWidget(stats_group)
        
        # Divider 2
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet("color: rgba(255, 255, 255, 20); margin-top: 8px;")
        self._actions_divider = line2
        layout.addWidget(line2)
        
        # Actions Header
        lbl_actions = QLabel("Actions")
        lbl_actions.setStyleSheet("color: #a1a1aa; font-weight: bold; font-size: 12px; margin-top: 8px;")
        self.actions_header_lbl = lbl_actions
        layout.addWidget(lbl_actions)
        
        self.actions_text = QLabel("Multiattack. The goblin makes two attacks with its scimitar.\n\nScimitar. Melee Weapon Attack: +4 to hit, reach 5 ft., one target. Hit: 5 (1d6 + 2) slashing damage.")
        self.actions_text.setWordWrap(True)
        self.actions_text.setStyleSheet("color: #fafafa; font-size: 11px; line-height: 1.4;")
        layout.addWidget(self.actions_text)
        
        # Description Header
        lbl_desc = QLabel("Description")
        lbl_desc.setStyleSheet("color: #a1a1aa; font-weight: bold; font-size: 12px; margin-top: 8px;")
        self.desc_header_lbl = lbl_desc
        layout.addWidget(lbl_desc)
        
        self.desc_text = QLabel("Small, green-skinned humanoids that love to raid and pillage. They are often found in large groups.")
        self.desc_text.setWordWrap(True)
        self.desc_text.setStyleSheet("color: #fafafa; font-size: 11px; line-height: 1.4;")
        layout.addWidget(self.desc_text)
        
        layout.addStretch()
        
        shell_layout = QHBoxLayout(self)
        shell_layout.setContentsMargins(0, 0, 16, 0)
        shell_layout.setSpacing(10)

        self.token_controls_panel = QFrame(self)
        self.token_controls_panel.setObjectName("SubPanel")
        self.token_controls_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        token_layout = QVBoxLayout(self.token_controls_panel)
        token_layout.setContentsMargins(16, 16, 16, 16)
        token_layout.setSpacing(14)

        token_header = QHBoxLayout()
        token_header.setContentsMargins(0, 0, 0, 0)
        token_header.setSpacing(12)
        token_label = QLabel("Token Icon")
        token_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        token_header.addWidget(token_label)
        token_header.addStretch()
        icon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
        self.btn_set_icon = QToolButton(self.token_controls_panel)
        self.btn_set_icon.setObjectName("TokenIconSetButton")
        self.btn_set_icon.setFixedSize(36, 36)
        self.btn_set_icon.setIcon(QIcon(os.path.join(icon_dir, "folder_open.svg")))
        self.btn_set_icon.setIconSize(QSize(20, 20))
        self.btn_set_icon.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_set_icon.setToolTip("Set token icon")
        self.btn_set_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        # Keep this button square regardless of global button padding rules.
        self.btn_set_icon.setStyleSheet("""
            QToolButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);
                border: 1px solid #3b424b;
                border-radius: 6px;
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                padding: 4px;
            }
            QToolButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);
                border-color: #58a6ff;
            }
        """)
        self.btn_clear_icon = QToolButton(self.token_controls_panel)
        self.btn_clear_icon.setObjectName("TokenIconClearButton")
        self.btn_clear_icon.setFixedSize(36, 36)
        self.btn_clear_icon.setIcon(QIcon(os.path.join(icon_dir, "trash.svg")))
        self.btn_clear_icon.setIconSize(QSize(20, 20))
        self.btn_clear_icon.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_clear_icon.setToolTip("Clear token icon")
        self.btn_clear_icon.setCursor(Qt.CursorShape.PointingHandCursor)
        # Keep this button square regardless of global button padding rules.
        self.btn_clear_icon.setStyleSheet("""
            QToolButton {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #da3633, stop:1 #b62324);
                border: 1px solid #f85149;
                border-radius: 6px;
                color: #ffffff;
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                padding: 4px;
            }
            QToolButton:hover {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f85149, stop:1 #da3633);
                border-color: #ff7b72;
            }
        """)
        token_header.addWidget(self.btn_set_icon)
        token_header.addWidget(self.btn_clear_icon)
        token_layout.addLayout(token_header)

        self.icon_status_lbl = QLabel("Using default color token.")
        self.icon_status_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        self.icon_status_lbl.setWordWrap(True)
        token_layout.addWidget(self.icon_status_lbl)

        size_header = QLabel("Footprint")
        size_header.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        token_layout.addWidget(size_header)
        size_grid = QGridLayout()
        size_grid.setContentsMargins(0, 0, 0, 0)
        size_grid.setHorizontalSpacing(12)
        size_grid.setVerticalSpacing(10)
        w_label = QLabel("Width (cells)")
        w_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        self.size_w_spin = PlusMinusSpinBox()
        self.size_w_spin.setRange(1, 6)
        self.size_w_spin.setValue(1)
        self.size_w_spin.setFixedWidth(120)
        h_label = QLabel("Height (cells)")
        h_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        self.size_h_spin = PlusMinusSpinBox()
        self.size_h_spin.setRange(1, 6)
        self.size_h_spin.setValue(1)
        self.size_h_spin.setFixedWidth(120)
        size_grid.addWidget(w_label, 0, 0)
        size_grid.addWidget(self.size_w_spin, 0, 1, Qt.AlignmentFlag.AlignRight)
        size_grid.addWidget(h_label, 1, 0)
        size_grid.addWidget(self.size_h_spin, 1, 1, Qt.AlignmentFlag.AlignRight)
        token_layout.addLayout(size_grid)
        self.lock_square_check = QCheckBox("Lock square")
        self.lock_square_check.setChecked(True)
        token_layout.addWidget(self.lock_square_check)
        player_label = QLabel("Assigned Player")
        player_label.setStyleSheet("color: #a1a1aa; font-size: 12px;")
        token_layout.addWidget(player_label)
        self.connected_player_combo = QComboBox(self.token_controls_panel)
        self.connected_player_combo.addItem("None", "")
        self.connected_player_combo.setToolTip("Assign an owner for this entity.")
        self.connected_player_combo.setStyleSheet("""
            QComboBox {
                background-color: rgba(255, 255, 255, 8);
                color: #e5e7eb;
                border: 1px solid rgba(255, 255, 255, 24);
                border-radius: 6px;
                padding: 4px 8px;
                min-height: 28px;
            }
            QComboBox:hover {
                border: 1px solid rgba(88, 166, 255, 120);
            }
            QComboBox:focus {
                border: 1px solid rgba(88, 166, 255, 160);
                outline: none;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
                background: transparent;
            }
            QComboBox QAbstractItemView {
                background-color: #111827;
                color: #e5e7eb;
                border: 1px solid rgba(255, 255, 255, 24);
                selection-background-color: #1f2937;
                selection-color: #ffffff;
                outline: 0;
            }
        """)
        self.connected_player_combo.currentIndexChanged.connect(self._on_owner_combo_changed)
        token_layout.addWidget(self.connected_player_combo)
        self.link_character_btn = QPushButton("Link Character to Entity")
        self.link_character_btn.setObjectName("SecondaryButton")
        self.link_character_btn.setProperty("compact", "true")
        self.link_character_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.link_character_btn.clicked.connect(self.linkCharacterRequested.emit)
        token_layout.addWidget(self.link_character_btn)
        self.unlink_character_btn = QPushButton("Unlink Character")
        self.unlink_character_btn.setObjectName("SecondaryButton")
        self.unlink_character_btn.setProperty("compact", "true")
        self.unlink_character_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unlink_character_btn.clicked.connect(self.unlinkCharacterRequested.emit)
        token_layout.addWidget(self.unlink_character_btn)
        self.linked_character_lbl = QLabel("Linked Character: None")
        self.linked_character_lbl.setWordWrap(True)
        self.linked_character_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        token_layout.addWidget(self.linked_character_lbl)
        token_layout.addStretch(1)
        self._token_panel_width = max(300, self.token_controls_panel.sizeHint().width())

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        shell_layout.addStretch(1)
        shell_layout.addWidget(self.token_controls_panel, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.token_controls_panel.setMaximumWidth(0)
        self.token_controls_panel.setMinimumWidth(0)
        self.token_controls_panel.setVisible(False)
        self._token_anim_group = QParallelAnimationGroup(self)
        self._token_anim_max = QPropertyAnimation(self.token_controls_panel, b"maximumWidth", self)
        self._token_anim_min = QPropertyAnimation(self.token_controls_panel, b"minimumWidth", self)
        for anim in (self._token_anim_max, self._token_anim_min):
            anim.setDuration(220)
            anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
            self._token_anim_group.addAnimation(anim)
        self._token_anim_group.finished.connect(self._on_token_anim_finished)

        shell_layout.addWidget(self.container, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        shell_margins = shell_layout.contentsMargins()
        stable_width = (
            self.container.maximumWidth()
            + self._token_panel_width
            + shell_layout.spacing()
            + shell_margins.left()
            + shell_margins.right()
        )
        self.setFixedWidth(stable_width)
        self._set_token_controls_expanded(False)
        
        # Apply shadow
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 4)
        self.container.setGraphicsEffect(shadow)

        # Connect signals
        # Connect signals
        self.hp_stat.curr_edit.valueChanged.connect(lambda v: self._track_change('hp', v))
        # For max hp, we need acccess or separate tracker. EntityItem uses _max_hp
        self.hp_stat.max_edit.valueChanged.connect(lambda v: self._track_change('_max_hp', v))
        self.shield_widget.spin.valueChanged.connect(lambda v: self._track_change('ac', v))
        self.btn_set_icon.clicked.connect(self._set_icon)
        self.btn_clear_icon.clicked.connect(self._clear_icon)
        self.size_w_spin.valueChanged.connect(self._on_size_w_changed)
        self.size_h_spin.valueChanged.connect(self._on_size_h_changed)
        self.lock_square_check.toggled.connect(self._on_lock_square_toggled)
        self.token_expand_btn.toggled.connect(self._set_token_controls_expanded)
        
        # Connect Stat Rows
        # Map abbreviations to attribute names
        self.stat_map = {
            "STR": "strength",
            "DEX": "dexterity",
            "CON": "constitution",
            "INT": "intelligence",
            "WIS": "wisdom",
            "CHA": "charisma"
        }
        
        for name, widget in self.stat_widgets.items():
            attr = self.stat_map[name]
            widget.edit.valueChanged.connect(lambda v, a=attr: self._track_change(a, v))
            
        self.name_edit.editingFinished.connect(self._update_name)

    def set_entity(self, entity):
        self._commit_changes() # Commit any pending from previous entity
        self._entity = entity
        self._pending_changes.clear()
        
        if not entity:
            self.linked_character_lbl.setText("Linked Character: None")
            self.link_character_btn.setEnabled(False)
            self.unlink_character_btn.setEnabled(False)
            self.hide()
            return
            
        # Update UI from entity
        self.hp_stat.set_data(entity.hp, entity._max_hp)
        with QSignalBlocker(self.shield_widget.spin):
            self.shield_widget.spin.setValue(entity.ac)
        
        # Update stats
        for name, widget in self.stat_widgets.items():
            attr = self.stat_map[name]
            val = getattr(entity, attr, 10)
            with QSignalBlocker(widget.edit.spin):
                with QSignalBlocker(widget.edit):
                    widget.edit.spin.setValue(val)
                    widget.edit.lbl.setText(str(val))
            
        # Update optional lore text (shown only when actual content exists).
        self.actions_text.setText(str(getattr(entity, "actions", "") or "").strip())
        self.desc_text.setText(str(getattr(entity, "description", "") or "").strip())

        size_w = int(getattr(entity, "size_w_cells", 1))
        size_h = int(getattr(entity, "size_h_cells", 1))
        lock_square = bool(getattr(entity, "lock_square", True))
        with QSignalBlocker(self.size_w_spin):
            self.size_w_spin.setValue(size_w)
        with QSignalBlocker(self.size_h_spin):
            self.size_h_spin.setValue(size_h)
        with QSignalBlocker(self.lock_square_check):
            self.lock_square_check.setChecked(lock_square)
        self.size_h_spin.setEnabled(not lock_square)
        self._update_icon_status_label()
        
        # Name
        name = entity.data(ROLE_LABEL) or "Entity"
        self.name_edit.setText(name)
        owner_id = entity.data(ROLE_OWNER_PLAYER_ID) or ""
        owner_index = self.connected_player_combo.findData(owner_id)
        if owner_index < 0:
            owner_index = 0
        with QSignalBlocker(self.connected_player_combo):
            self.connected_player_combo.setCurrentIndex(owner_index)
        self.connected_player_combo.setEnabled(self._player_assignment_enabled)
        self._update_entity_type_label()
        linked_name = str(entity.data(ROLE_LINKED_SHEET_NAME) or "").strip()
        if linked_name:
            self.linked_character_lbl.setText(f"Linked Character: {linked_name}")
        else:
            self.linked_character_lbl.setText("Linked Character: None")
        self.link_character_btn.setEnabled(self._link_character_enabled)
        self._sync_linked_character_mode()
        
        self.show()

    def set_player_options(self, players: dict[str, str]) -> None:
        previous_owner = ""
        if self._entity is not None:
            previous_owner = self._entity.data(ROLE_OWNER_PLAYER_ID) or ""
        with QSignalBlocker(self.connected_player_combo):
            self.connected_player_combo.clear()
            self.connected_player_combo.addItem("None", "")
            for player_id, player_name in sorted(players.items(), key=lambda entry: entry[1].lower()):
                self.connected_player_combo.addItem(player_name, player_id)
            owner_index = self.connected_player_combo.findData(previous_owner)
            if owner_index < 0:
                owner_index = 0
            self.connected_player_combo.setCurrentIndex(owner_index)

    def set_owner_assignment_enabled(self, enabled: bool) -> None:
        self._player_assignment_enabled = bool(enabled)
        self.connected_player_combo.setEnabled(self._player_assignment_enabled and self._entity is not None)

    def set_link_character_enabled(self, enabled: bool) -> None:
        self._link_character_enabled = bool(enabled)
        has_entity = self._entity is not None
        has_link = bool(
            self._entity is not None
            and str(self._entity.data(ROLE_LINKED_SHEET_ID) or "").strip()
        )
        self.link_character_btn.setEnabled(self._link_character_enabled and has_entity)
        self.unlink_character_btn.setEnabled(self._link_character_enabled and has_entity and has_link)

    def set_linked_character_info(self, name: str) -> None:
        clean_name = str(name or "").strip()
        if clean_name:
            self.linked_character_lbl.setText(f"Linked Character: {clean_name}")
        else:
            self.linked_character_lbl.setText("Linked Character: None")
        self._sync_linked_character_mode()

    def _sync_linked_character_mode(self) -> None:
        actions_text = ""
        desc_text = ""
        has_link = False
        if self._entity is not None:
            actions_text = str(getattr(self._entity, "actions", "") or "").strip()
            desc_text = str(getattr(self._entity, "description", "") or "").strip()
            has_link = bool(str(self._entity.data(ROLE_LINKED_SHEET_ID) or "").strip())
        has_actions = bool(actions_text)
        has_desc = bool(desc_text)
        if getattr(self, "unlink_character_btn", None) is not None:
            self.unlink_character_btn.setEnabled(
                self._link_character_enabled and self._entity is not None and has_link
            )

        if getattr(self, "actions_header_lbl", None) is not None:
            self.actions_header_lbl.setVisible(has_actions)
        if getattr(self, "actions_text", None) is not None:
            self.actions_text.setVisible(has_actions)
        if getattr(self, "desc_header_lbl", None) is not None:
            self.desc_header_lbl.setVisible(has_desc)
        if getattr(self, "desc_text", None) is not None:
            self.desc_text.setVisible(has_desc)
        if getattr(self, "_actions_divider", None) is not None:
            self._actions_divider.setVisible(has_actions or has_desc)

        # Recompute compact height after lore visibility changes.
        container_layout = self.container.layout() if hasattr(self, "container") else None
        if container_layout is not None:
            container_layout.invalidate()
            container_layout.activate()
        own_layout = self.layout()
        if own_layout is not None:
            own_layout.invalidate()
            own_layout.activate()
        self.container.adjustSize()
        self.adjustSize()
        self.updateGeometry()

    def _update_entity_type_label(self) -> None:
        owner_id = ""
        if self._entity is not None:
            owner_id = str(self._entity.data(ROLE_OWNER_PLAYER_ID) or "").strip()
        self.type_lbl.setText("Player" if owner_id else "NPC")

    def set_defer_icon_apply(self, enabled: bool) -> None:
        self._defer_icon_apply = bool(enabled)

    def _on_owner_combo_changed(self, index: int) -> None:
        if not self._entity or not self._player_assignment_enabled:
            return
        new_owner = self.connected_player_combo.itemData(index) or ""
        old_owner = self._entity.data(ROLE_OWNER_PLAYER_ID) or ""
        if new_owner == old_owner:
            return
        if self.undo_stack is not None:
            from dungeon_commands import PropertyChangeCommand

            cmd = PropertyChangeCommand(
                self._entity,
                ROLE_OWNER_PLAYER_ID,
                old_owner,
                new_owner,
                "Assign Entity Owner",
            )
            self.undo_stack.push(cmd)
        else:
            self._entity.setData(ROLE_OWNER_PLAYER_ID, new_owner)
            self._entity.update()
        self._update_entity_type_label()
        self.ownerChanged.emit(str(new_owner))
        self.entityEdited.emit()

    def _update_name(self):
        if self._entity:
            from dungeon_commands import PropertyChangeCommand
            new_name = self.name_edit.text()
            old_name = self._entity.data(ROLE_LABEL) or ""
            if new_name == old_name:
                return
            if self.undo_stack:
                cmd = PropertyChangeCommand(self._entity, ROLE_LABEL, old_name, new_name, "Rename Entity")
                self.undo_stack.push(cmd)
            else:
                self._entity.setData(ROLE_LABEL, new_name)
            self.entityEdited.emit()

    def _set_icon(self) -> None:
        if not self._entity:
            return
        start_dir = str(Path(self._entity.icon_path).parent) if getattr(self._entity, "icon_path", "") else str(Path.home())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Entity Icon",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.svg)",
        )
        if not filename:
            return
        if self._defer_icon_apply:
            self.iconPathSelected.emit(filename)
            return
        self._track_change("icon_path", filename)

    def _set_token_controls_expanded(self, expanded: bool) -> None:
        expanded_bool = bool(expanded)
        self.token_expand_btn.setIcon(self._make_token_toggle_icon(expanded=expanded_bool))
        self._token_anim_group.stop()
        current_width = max(
            int(self.token_controls_panel.width()),
            int(self.token_controls_panel.maximumWidth()),
            int(self.token_controls_panel.minimumWidth()),
        )
        if expanded_bool:
            self.token_controls_panel.setVisible(True)
            target_width = self._token_panel_width
            self._token_anim_max.setStartValue(current_width)
            self._token_anim_max.setEndValue(target_width)
            self._token_anim_min.setStartValue(current_width)
            self._token_anim_min.setEndValue(target_width)
            self._token_anim_group.start()
        else:
            self._token_anim_max.setStartValue(current_width)
            self._token_anim_max.setEndValue(0)
            self._token_anim_min.setStartValue(current_width)
            self._token_anim_min.setEndValue(0)
            self._token_anim_group.start()

    def _on_token_anim_finished(self) -> None:
        if not self.token_expand_btn.isChecked():
            self.token_controls_panel.setVisible(False)

    def _make_token_toggle_icon(self, expanded: bool) -> QIcon:
        icon_size = 11
        pix = QPixmap(icon_size, icon_size)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d4d4d8"))
        if expanded:
            points = [
                QPointF(3.0, 2.0),
                QPointF(3.0, 9.0),
                QPointF(8.5, 5.5),
            ]
        else:
            points = [
                QPointF(8.0, 2.0),
                QPointF(8.0, 9.0),
                QPointF(2.5, 5.5),
            ]
        painter.drawPolygon(QPolygonF(points))
        painter.end()
        return QIcon(pix)

    def _clear_icon(self) -> None:
        if not self._entity:
            return
        self._track_change("icon_path", "")

    def _on_size_w_changed(self, value: int) -> None:
        if not self._entity:
            return
        self._track_change("size_w_cells", int(value))
        if self.lock_square_check.isChecked():
            if self.size_h_spin.value() != value:
                with QSignalBlocker(self.size_h_spin):
                    self.size_h_spin.setValue(value)
            self._track_change("size_h_cells", int(value))

    def _on_size_h_changed(self, value: int) -> None:
        if not self._entity or self.lock_square_check.isChecked():
            return
        self._track_change("size_h_cells", int(value))

    def _on_lock_square_toggled(self, checked: bool) -> None:
        if not self._entity:
            return
        is_checked = bool(checked)
        self.size_h_spin.setEnabled(not is_checked)
        self._track_change("lock_square", is_checked)
        if is_checked:
            width_value = self.size_w_spin.value()
            if self.size_h_spin.value() != width_value:
                with QSignalBlocker(self.size_h_spin):
                    self.size_h_spin.setValue(width_value)
                self._track_change("size_h_cells", int(width_value))

    def _update_icon_status_label(self) -> None:
        if not self._entity:
            self.icon_status_lbl.setText("No entity selected.")
            self.icon_status_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
            self.btn_clear_icon.setEnabled(False)
            return
        status = self._entity.icon_status() if hasattr(self._entity, "icon_status") else "default"
        if status == "ok":
            self.icon_status_lbl.setText(f"Using: {self._entity.icon_path}")
            self.icon_status_lbl.setStyleSheet("color: #86efac; font-size: 11px;")
        elif status == "missing":
            self.icon_status_lbl.setText(f"Missing file: {self._entity.icon_path}")
            self.icon_status_lbl.setStyleSheet("color: #fca5a5; font-size: 11px;")
        elif status == "invalid":
            self.icon_status_lbl.setText(f"Unreadable image: {self._entity.icon_path}")
            self.icon_status_lbl.setStyleSheet("color: #fca5a5; font-size: 11px;")
        else:
            self.icon_status_lbl.setText("Using default color token.")
            self.icon_status_lbl.setStyleSheet("color: #a1a1aa; font-size: 11px;")
        self.btn_clear_icon.setEnabled(bool(getattr(self._entity, "icon_path", "")))

    def _track_change(self, attr: str, new_value):
        if not self._entity:
            return
        current_val = getattr(self._entity, attr)
        if attr not in self._pending_changes:
            self._pending_changes[attr] = current_val
        setattr(self._entity, attr, new_value)
        if attr == "icon_path":
            self._entity.setData(ROLE_ICON, str(new_value or ""))
        if hasattr(self._entity, "update"):
            self._entity.update()
        if attr == "icon_path":
            self._update_icon_status_label()
        self._change_timer.start()

    def _commit_changes(self):
        if not self._entity or not self.undo_stack:
            self._pending_changes.clear()
            return
            
        from dungeon_commands import AttributeChangeCommand
            
        changed = False
        if self._pending_changes:
            self.undo_stack.beginMacro("Change Properties")
            for attr, old_val in self._pending_changes.items():
                new_val = getattr(self._entity, attr)
                if new_val != old_val:
                    cmd = AttributeChangeCommand(self._entity, attr, old_val, new_val)
                    self.undo_stack.push(cmd)
                    changed = True
            self.undo_stack.endMacro()
            
        self._pending_changes.clear()
        if changed:
            self.entityEdited.emit()










class DungeonShapePreview(QWidget):
    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAutoFillBackground(False)
        self.shape_width = 336
        self.rect_height = 60
        self.tri_height = 32
        self.tip_cut = 14
        self.join_cut = 12
        self.rect_bottom_cut = 14
        self.top_radius = 10
        self.text_box_width = 236
        self.text_box_height = 56
        self.text_box_offset_x = 0
        self.text_box_offset_y = 8
        self.text_box_padding = 4
        self.text_header_size = 20
        self.text_sub_size = 15
        self.text_line_gap = 4
        self.top_padding = 12
        self.outline_width = 1
        self.x_offset = 0
        self.setMinimumSize(360, 150)
        self.setStyleSheet("background-color: transparent; border: none;")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_shape_params(
        self,
        shape_width: int,
        rect_height: int,
        tri_height: int,
        tip_cut: int,
        join_cut: int,
        rect_bottom_cut: int,
        top_radius: int,
        text_box_width: int,
        text_box_height: int,
        text_box_offset_x: int,
        text_box_offset_y: int,
        text_box_padding: int,
        text_header_size: int,
        text_sub_size: int,
        text_line_gap: int,
        top_padding: int,
        outline_width: int,
        x_offset: int,
    ) -> None:
        self.shape_width = shape_width
        self.rect_height = rect_height
        self.tri_height = tri_height
        self.tip_cut = tip_cut
        self.join_cut = join_cut
        self.rect_bottom_cut = rect_bottom_cut
        self.top_radius = top_radius
        self.text_box_width = text_box_width
        self.text_box_height = text_box_height
        self.text_box_offset_x = text_box_offset_x
        self.text_box_offset_y = text_box_offset_y
        self.text_box_padding = text_box_padding
        self.text_header_size = text_header_size
        self.text_sub_size = text_sub_size
        self.text_line_gap = text_line_gap
        self.top_padding = top_padding
        self.outline_width = outline_width
        self.x_offset = x_offset
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        width = max(0, self.width() - 2)
        height = max(0, self.height() - 2)
        shape_width = max(1, min(self.shape_width, width))
        rect_height = max(1, self.rect_height)
        tri_height = max(0, self.tri_height)
        top_padding = max(0, self.top_padding)

        available_height = max(0, height - top_padding)
        rect_height = min(rect_height, available_height)
        tri_height = min(tri_height, max(0, available_height - rect_height))

        x = (self.width() - shape_width) / 2 + self.x_offset
        y = top_padding

        pen = QPen(OVERLAY_BORDER_COLOR, max(1, self.outline_width))
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        base_left_x = x
        base_left_y = y + rect_height
        base_right_x = x + shape_width
        base_right_y = base_left_y
        apex_x = x + shape_width / 2
        apex_y = base_left_y + tri_height

        corner_cut = max(0.0, float(self.rect_bottom_cut))
        max_corner_cut = max(0.0, rect_height - 1.0)
        corner_cut = min(corner_cut, max_corner_cut)

        top_radius = max(0.0, float(self.top_radius))
        max_top_radius = max(0.0, min(rect_height, shape_width / 2) - 1.0)
        top_radius = min(top_radius, max_top_radius)

        has_triangle = tri_height > 0.5
        left_dx = apex_x - base_left_x
        left_dy = apex_y - base_left_y
        right_dx = apex_x - base_right_x
        right_dy = apex_y - base_right_y
        left_len = math.hypot(left_dx, left_dy)
        right_len = math.hypot(right_dx, right_dy)

        tip_cut = max(0.0, float(self.tip_cut))
        join_cut = max(0.0, float(self.join_cut))
        if has_triangle and left_len > 0:
            left_tip_cut = min(tip_cut, max(0.0, left_len - join_cut - 1.0))
            left_join_cut = min(join_cut, max(0.0, left_len - left_tip_cut - 1.0))
            left_tip_t = left_tip_cut / left_len
            left_join_t = left_join_cut / left_len
            left_join_x = base_left_x + left_dx * left_join_t
            left_join_y = base_left_y + left_dy * left_join_t
            left_tip_x = apex_x - left_dx * left_tip_t
            left_tip_y = apex_y - left_dy * left_tip_t
        else:
            left_join_x = base_left_x
            left_join_y = base_left_y
            left_tip_x = base_left_x
            left_tip_y = base_left_y

        if has_triangle and right_len > 0:
            right_tip_cut = min(tip_cut, max(0.0, right_len - join_cut - 1.0))
            right_join_cut = min(join_cut, max(0.0, right_len - right_tip_cut - 1.0))
            right_tip_t = right_tip_cut / right_len
            right_join_t = right_join_cut / right_len
            right_join_x = base_right_x + right_dx * right_join_t
            right_join_y = base_right_y + right_dy * right_join_t
            right_tip_x = apex_x - right_dx * right_tip_t
            right_tip_y = apex_y - right_dy * right_tip_t
        else:
            right_join_x = base_right_x
            right_join_y = base_right_y
            right_tip_x = base_right_x
            right_tip_y = base_right_y

        def _unit(dx: float, dy: float) -> tuple[float, float]:
            length = math.hypot(dx, dy)
            if length <= 0:
                return (0.0, 0.0)
            return (dx / length, dy / length)

        connector_pen = QPen(OVERLAY_BORDER_COLOR, max(1, self.outline_width))
        connector_pen.setStyle(Qt.PenStyle.SolidLine)

        # Join gaps: connect rectangle sides to triangle lines with matched tangents.
        rect_left_end = QPointF(base_left_x, base_left_y - corner_cut)
        rect_right_end = QPointF(base_right_x, base_right_y - corner_cut)
        tri_left_start = QPointF(left_join_x, left_join_y)
        tri_right_start = QPointF(right_join_x, right_join_y)

        left_control = None
        right_control = None
        if has_triangle:
            left_dir = _unit(left_tip_x - left_join_x, left_tip_y - left_join_y)
            right_dir = _unit(right_tip_x - right_join_x, right_tip_y - right_join_y)

            def _vertical_tangent_control(rect_end: QPointF, tri_start: QPointF, tri_dir: tuple[float, float]) -> QPointF:
                if abs(tri_dir[0]) < 1e-6:
                    return QPointF(rect_end.x(), (rect_end.y() + tri_start.y()) / 2)
                t = (rect_end.x() - tri_start.x()) / tri_dir[0]
                return QPointF(tri_start.x() + tri_dir[0] * t, tri_start.y() + tri_dir[1] * t)

            if rect_left_end != tri_left_start:
                control = _vertical_tangent_control(rect_left_end, tri_left_start, left_dir)
                left_control = control

            if rect_right_end != tri_right_start:
                control = _vertical_tangent_control(rect_right_end, tri_right_start, right_dir)
                right_control = control

        # Tip gap: connect the loose ends with a quadratic (parabola) matching triangle slopes.
        left_tip = QPointF(left_tip_x, left_tip_y)
        right_tip = QPointF(right_tip_x, right_tip_y)
        tip_control = None
        if has_triangle:
            tip_dir_left = _unit(apex_x - left_tip_x, apex_y - left_tip_y)
            tip_dir_right = _unit(apex_x - right_tip_x, apex_y - right_tip_y)
            tip_gap = math.hypot(right_tip_x - left_tip_x, right_tip_y - left_tip_y)

            def _line_intersection(p: QPointF, r: tuple[float, float], q: QPointF, s: tuple[float, float]) -> QPointF | None:
                rxs = r[0] * s[1] - r[1] * s[0]
                if abs(rxs) < 1e-6:
                    return None
                qmpx = q.x() - p.x()
                qmpy = q.y() - p.y()
                t = (qmpx * s[1] - qmpy * s[0]) / rxs
                return QPointF(p.x() + r[0] * t, p.y() + r[1] * t)

            if tip_gap > 0.5:
                control = _line_intersection(left_tip, tip_dir_left, right_tip, tip_dir_right)
                if control is None:
                    control = QPointF((left_tip.x() + right_tip.x()) / 2, (left_tip.y() + right_tip.y()) / 2)
                tip_control = control

        fill_path = QPainterPath()
        if not has_triangle:
            fill_path.addRoundedRect(QRectF(x, y, shape_width, rect_height), top_radius, top_radius)
        else:
            if top_radius > 0:
                fill_path.moveTo(x + top_radius, y)
                fill_path.lineTo(x + shape_width - top_radius, y)
                fill_path.quadTo(x + shape_width, y, x + shape_width, y + top_radius)
            else:
                fill_path.moveTo(x, y)
                fill_path.lineTo(x + shape_width, y)

            if right_control is not None and left_control is not None:
                fill_path.lineTo(rect_right_end)
                fill_path.quadTo(right_control, tri_right_start)
                fill_path.lineTo(right_tip)
                if tip_control is not None:
                    fill_path.quadTo(tip_control, left_tip)
                else:
                    fill_path.lineTo(left_tip)
                fill_path.lineTo(tri_left_start)
                fill_path.quadTo(left_control, rect_left_end)
            else:
                fill_path.lineTo(base_right_x, base_right_y)
                fill_path.lineTo(base_left_x, base_left_y)

            fill_path.lineTo(x, y + top_radius)
            if top_radius > 0:
                fill_path.quadTo(x, y, x + top_radius, y)
            fill_path.closeSubpath()

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(OVERLAY_BG_COLOR)
        painter.drawPath(fill_path)
        painter.restore()

        rect_path = QPainterPath()
        if not has_triangle:
            rect_path.addRoundedRect(QRectF(x, y, shape_width, rect_height), top_radius, top_radius)
        else:
            if top_radius > 0:
                rect_path.moveTo(x + top_radius, y)
                rect_path.lineTo(x + shape_width - top_radius, y)
                rect_path.quadTo(x + shape_width, y, x + shape_width, y + top_radius)
                rect_path.moveTo(x, y + top_radius)
                rect_path.quadTo(x, y, x + top_radius, y)
            else:
                rect_path.moveTo(x, y)
                rect_path.lineTo(x + shape_width, y)
            rect_path.moveTo(x, y + top_radius)
            rect_path.lineTo(base_left_x, base_left_y - corner_cut)
            rect_path.moveTo(x + shape_width, y + top_radius)
            rect_path.lineTo(base_right_x, base_right_y - corner_cut)
        painter.drawPath(rect_path)

        if has_triangle:
            tri_path = QPainterPath()
            tri_path.moveTo(left_join_x, left_join_y)
            tri_path.lineTo(left_tip_x, left_tip_y)
            tri_path.moveTo(right_join_x, right_join_y)
            tri_path.lineTo(right_tip_x, right_tip_y)
            painter.drawPath(tri_path)

        if left_control is not None:
            join_left = QPainterPath()
            join_left.moveTo(rect_left_end)
            join_left.quadTo(left_control, tri_left_start)
            painter.save()
            painter.setPen(connector_pen)
            painter.drawPath(join_left)
            painter.restore()

        if right_control is not None:
            join_right = QPainterPath()
            join_right.moveTo(rect_right_end)
            join_right.quadTo(right_control, tri_right_start)
            painter.save()
            painter.setPen(connector_pen)
            painter.drawPath(join_right)
            painter.restore()

        if tip_control is not None:
            tip_curve = QPainterPath()
            tip_curve.moveTo(left_tip)
            tip_curve.quadTo(tip_control, right_tip)
            painter.save()
            painter.setPen(connector_pen)
            painter.drawPath(tip_curve)
            painter.restore()

class DungeonCollapseButton(QAbstractButton):
    def __init__(self, icon: QIcon, parent=None) -> None:
        super().__init__(parent)
        self._icon = icon
        self._hovered = False
        self._button_height = 22
        self.setFixedHeight(self._button_height)
        self.setMinimumWidth(120)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Collapse")

    def triangle_height(self) -> int:
        return 0

    def enterEvent(self, event: QEvent) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            width = float(self.width())
            height = float(self.height())
            bar_rect = QRectF(0.0, 0.0, width, height)

            fill = QColor(OVERLAY_BG_COLOR)
            if self._hovered:
                fill = fill.lighter(112)
            painter.setPen(QPen(OVERLAY_BORDER_COLOR, 1.0))
            painter.setBrush(fill)
            painter.drawRoundedRect(bar_rect, 6.0, 6.0)

            caret_pen = QPen(QColor("#e5e7eb"), 2.0)
            caret_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            caret_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(caret_pen)
            caret_half = min(20.0, width * 0.2)
            center_x = width / 2.0
            center_y = height / 2.0
            caret_path = QPainterPath()
            caret_path.moveTo(center_x - caret_half, center_y + 4.0)
            caret_path.lineTo(center_x, center_y - 4.0)
            caret_path.lineTo(center_x + caret_half, center_y + 4.0)
            painter.drawPath(caret_path)
        finally:
            if painter.isActive():
                painter.end()

class InlineRenameLineEdit(QLineEdit):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrame(False)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "background-color: transparent; border: none; color: #e5e7eb; padding: 0px; margin: 0px;"
        )
        self.setTextMargins(0, 0, 0, 0)
        self.setContentsMargins(0, 0, 0, 0)
        self._original_text = ""
        self._edit_committed = False

    def setFontWeight(self, weight: int) -> None:
        font = self.font()
        font.setWeight(QFont.Weight(weight))
        self.setFont(font)

    def start_edit(self, select_all: bool = True, cursor_pos: int | None = None) -> None:
        self._original_text = self.text()
        self._edit_committed = False
        self.setReadOnly(False)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        if cursor_pos is not None:
            self.setCursorPosition(max(0, min(cursor_pos, len(self.text()))))
            self.deselect()
        elif select_all:
            self.selectAll()
        else:
            self.setCursorPosition(len(self.text()))
            self.deselect()

    def finish_edit(self) -> None:
        if self.isReadOnly():
            return
        self.setReadOnly(True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.deselect()
        self.clearFocus()
        if not self._edit_committed:
            self._edit_committed = True
            self.editingFinished.emit()

    def focusOutEvent(self, event: QEvent) -> None:
        self.finish_edit()
        with QSignalBlocker(self):
            super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape):
            if event.key() == Qt.Key.Key_Escape:
                self.setText(self._original_text)
            self.finish_edit()
        super().keyPressEvent(event)


class DungeonTileWidget(QWidget):
    clicked = Signal(str)
    nameChanged = Signal(str, str)
    nameCommitted = Signal(str, str)

    def __init__(self, dungeon_id: str, name: str, preview: QPixmap, icon_size: QSize, parent=None) -> None:
        super().__init__(parent)
        self.dungeon_id = dungeon_id
        self._hovered = False
        self._selected = False
        self._placement_mode = False
        self._player_assigned = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 14)
        layout.setSpacing(8)

        self.preview_frame = QWidget(self)
        self.preview_frame.setFixedSize(icon_size)
        self.preview_frame.setObjectName("DungeonPreviewFrame")
        self.preview_frame.setStyleSheet(
            "background-color: #09090b; border: none; border-radius: 6px;"
        )
        preview_layout = QVBoxLayout(self.preview_frame)
        preview_layout.setContentsMargins(1, 1, 1, 1)
        preview_layout.setSpacing(0)

        inner_size = QSize(max(1, icon_size.width() - 2), max(1, icon_size.height() - 2))
        self.preview_label = QLabel(self.preview_frame)
        self.preview_label.setFixedSize(inner_size)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if preview and not preview.isNull():
            self.preview_label.setPixmap(
                preview.scaled(
                    inner_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        preview_layout.addWidget(self.preview_label, 0, Qt.AlignmentFlag.AlignCenter)

        self.player_badge = QLabel(self.preview_frame)
        self.player_badge.setFixedSize(18, 18)
        self.player_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.player_badge.setText("P")
        badge_font = self.player_badge.font()
        if badge_font.pointSize() <= 0:
            badge_font.setPointSize(9)
        badge_font.setBold(True)
        self.player_badge.setFont(badge_font)
        self.player_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.player_badge.setStyleSheet(
            "background-color: #f59e0b; color: #ffffff; border-radius: 4px;"
        )
        self.player_badge.hide()

        self.player_badge_ghost = QLabel(self.preview_frame)
        self.player_badge_ghost.setFixedSize(18, 18)
        self.player_badge_ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.player_badge_ghost.setText("P")
        ghost_font = self.player_badge_ghost.font()
        if ghost_font.pointSize() <= 0:
            ghost_font.setPointSize(9)
        ghost_font.setBold(True)
        self.player_badge_ghost.setFont(ghost_font)
        self.player_badge_ghost.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.player_badge_ghost.setStyleSheet(
            "background-color: rgba(245, 158, 11, 50); color: rgba(255, 255, 255, 120); border-radius: 4px;"
        )
        self.player_badge_ghost.hide()

        self._position_player_badges()

        self.name_edit = InlineRenameLineEdit(self)
        self.name_edit.setText(name)
        self.name_edit.setFont(self.font())
        name_metrics = QFontMetrics(self.name_edit.font())
        self.name_edit.setFixedHeight(name_metrics.height() + 12)
        self.name_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.name_edit.textChanged.connect(self._on_text_changed)
        self.name_edit.editingFinished.connect(self._commit_name)

        layout.addWidget(self.preview_frame, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.name_edit, 0, Qt.AlignmentFlag.AlignHCenter)

        self.preview_frame.installEventFilter(self)
        self.name_edit.installEventFilter(self)

    def _on_text_changed(self, text: str) -> None:
        self.nameChanged.emit(self.dungeon_id, text)

    def _commit_name(self) -> None:
        self.nameCommitted.emit(self.dungeon_id, self.name_edit.text())

    def set_selected(self, selected: bool) -> None:
        self._selected = bool(selected)
        color = "#60a5fa" if selected else "#e5e7eb"
        self.name_edit.setStyleSheet(
            f"background-color: transparent; border: none; color: {color}; padding: 0px; margin: 0px;"
        )
        self.name_edit.setFontWeight(600 if selected else 400)
        self.update()

    def set_player_assigned(self, assigned: bool) -> None:
        self._player_assigned = bool(assigned)
        self._update_player_badge_visibility()
        self.update()

    def set_player_placement_mode(self, enabled: bool) -> None:
        self._placement_mode = bool(enabled)
        self._update_player_badge_visibility()
        self.update()

    def start_edit(self) -> None:
        self.name_edit.start_edit()

    def _set_hovered(self, hovered: bool) -> None:
        if hovered:
            if not self._hovered:
                self._hovered = True
                self._update_player_badge_visibility()
                self.update()
            return
        cursor_pos = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(cursor_pos):
            return
        if self._hovered:
            self._hovered = False
            self._update_player_badge_visibility()
            self.update()

    def enterEvent(self, event: QEvent) -> None:
        self._set_hovered(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent) -> None:
        self._set_hovered(False)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            frame_rect = QRectF(self.preview_frame.geometry()).adjusted(-1.0, -1.0, 1.0, 1.0)
            border_color = QColor(255, 255, 255, 140)
            if self._hovered or self._selected:
                border_color = QColor("#60a5fa")
            if self._placement_mode and self._hovered:
                border_color = QColor("#f59e0b")
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(border_color, 2.0))
            painter.drawRoundedRect(frame_rect, 6.0, 6.0)
        finally:
            if painter.isActive():
                painter.end()

    def _position_player_badges(self) -> None:
        badge_margin = 6
        x = badge_margin
        y = badge_margin
        self.player_badge.move(x, y)
        self.player_badge_ghost.move(x, y)
        self.player_badge.raise_()
        self.player_badge_ghost.raise_()

    def _update_player_badge_visibility(self) -> None:
        if not hasattr(self, "player_badge"):
            return
        self.player_badge.setVisible(self._player_assigned)
        ghost_visible = self._placement_mode and self._hovered and not self._player_assigned
        self.player_badge_ghost.setVisible(ghost_visible)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched in (self.preview_frame, self.name_edit):
            if event.type() == QEvent.Type.Enter:
                self._set_hovered(True)
            elif event.type() == QEvent.Type.Leave:
                self._set_hovered(False)
        if event.type() == QEvent.Type.MouseButtonPress and isinstance(event, QMouseEvent):
            if event.button() == Qt.MouseButton.LeftButton:
                if watched is not self.name_edit and self.name_edit.hasFocus():
                    self.name_edit.finish_edit()
                self.clicked.emit(self.dungeon_id)
        if watched is self.name_edit and event.type() == QEvent.Type.MouseButtonDblClick:
            if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                self.name_edit.start_edit(select_all=True)
            return True
        return super().eventFilter(watched, event)

class DungeonSelectionWidget(QWidget):
    saveRequested = Signal()
    saveAsRequested = Signal()
    loadRequested = Signal()
    addRequested = Signal()
    deleteRequested = Signal()
    carouselLayoutChanged = Signal(int, int)
    expandedChanged = Signal(bool)
    collectionRenameRequested = Signal(str)
    playerPlacementToggled = Signal(bool)
    autosaveToggled = Signal(bool)
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._text_parent = self.parentWidget() or self
        self._ui_enabled = True
        if self._text_parent is not self:
            self._text_parent.installEventFilter(self)

        self._expanded = False
        self._expand_progress = 0.0
        self._expand_anim = QPropertyAnimation(self, b"expandProgress", self)
        self._expand_anim.setDuration(280)
        self._expand_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        self._collapsed = {
            "shape_width": 336,
            "rect_height": 60,
            "tri_height": 32,
            "tip_cut": 14,
            "join_cut": 12,
            "rect_bottom_cut": 14,
            "top_radius": 10,
            "text_box_width": 236,
            "text_box_height": 56,
            "text_box_offset_x": 0,
            "text_box_offset_y": 8,
            "text_box_padding": 4,
            "text_header_size": 20,
            "text_sub_size": 15,
            "text_line_gap": 0,
            "top_padding": 12,
            "outline_width": 1,
            "x_offset": 0,
            "outer_pad": 20,
        }
        self._current_params = dict(self._collapsed)
        self._text_min_height = 0
        self._carousel_layout = (0, 0)

        layout = QGridLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)

        self.preview = DungeonShapePreview(self)
        self.preview.clicked.connect(self._expand_only)
        layout.addWidget(self.preview, 0, 0, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        text_box_width = self._collapsed["text_box_width"]
        text_box_height = self._collapsed["text_box_height"]
        text_box_padding = self._collapsed["text_box_padding"]
        text_gap = self._collapsed["text_line_gap"]

        self.text_container = QWidget(self._text_parent)
        self.text_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.text_container.installEventFilter(self)
        self.text_container.setObjectName("TransparentContainer")
        text_layout = QVBoxLayout(self.text_container)
        text_layout.setContentsMargins(int(text_box_padding), int(text_box_padding), int(text_box_padding), int(text_box_padding))
        text_layout.setSpacing(int(text_gap))

        self._header_text = "Dungeon Selection"
        self._header_dirty_visible = False
        self._header_editing = False

        self.header_label = InlineRenameLineEdit(self.text_container)
        self.header_label.setText(self._header_text)
        header_font = QFont()
        header_font.setPixelSize(int(self._collapsed["text_header_size"]))
        self.header_label.setFont(header_font)
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.header_label.setStyleSheet(
            "background-color: transparent; border: none; color: #e5e7eb; padding: 0px; margin: 0px;"
        )
        self.header_label.editingFinished.connect(self._commit_header_name)
        self.header_label.installEventFilter(self)

        self.header_dirty = QLabel("*", self.text_container)
        self.header_dirty.setStyleSheet("color: #e5e7eb;")
        self.header_dirty.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.header_dirty.hide()

        self.sub_label = QLabel("Dungeon", self.text_container)
        sub_font = QFont()
        sub_font.setPixelSize(int(self._collapsed["text_sub_size"]))
        self.sub_label.setFont(sub_font)
        self.sub_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.sub_label.setStyleSheet("color: #60a5fa;")
        self.sub_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        header_metrics = QFontMetrics(header_font)
        sub_metrics = QFontMetrics(sub_font)
        header_height = header_metrics.height()
        sub_height = sub_metrics.height()
        header_extra = 0
        sub_extra = 0
        self.header_label.setContentsMargins(0, 0, 0, 0)
        self.sub_label.setContentsMargins(0, 0, 0, 0)
        self.header_label.setFixedHeight(header_height)
        self.sub_label.setFixedHeight(sub_height)
        self.header_dirty.setFixedHeight(header_height)

        needed_height = int(text_box_padding * 2 + text_gap + header_height + sub_height + header_extra + sub_extra)
        self._text_min_height = max(int(text_box_height), needed_height)
        self.text_container.setFixedSize(int(text_box_width), self._text_min_height)

        self.actions_container = QWidget(self._text_parent)
        self.actions_container.setObjectName("TransparentContainer")
        actions_layout = QHBoxLayout(self.actions_container)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        actions_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        icon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
        save_icon = os.path.join(icon_dir, "save.svg")
        save_as_icon = os.path.join(icon_dir, "save_as.svg")
        load_icon = os.path.join(icon_dir, "folder_open.svg")
        add_icon = os.path.join(icon_dir, "plus.svg")
        delete_icon = os.path.join(icon_dir, "trash.svg")
        collapse_icon = os.path.join(icon_dir, "caret_up_white.svg")
        button_size = 36
        icon_size_px = 20

        self.btn_save = QToolButton(self.actions_container)
        self.btn_save.setObjectName("SecondaryButton")
        self.btn_save.setToolTip("Save Collection")
        self.btn_save.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save.setIcon(QIcon(save_icon))
        self.btn_save.setIconSize(QSize(icon_size_px, icon_size_px))
        self.btn_save.setFixedSize(button_size, button_size)
        self.btn_save.setAutoRaise(False)
        self.btn_save.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_save.clicked.connect(self.saveRequested.emit)

        self.btn_save_as = QToolButton(self.actions_container)
        self.btn_save_as.setObjectName("SecondaryButton")
        self.btn_save_as.setToolTip("Save Collection As")
        self.btn_save_as.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_save_as.setIcon(QIcon(save_as_icon))
        self.btn_save_as.setIconSize(QSize(icon_size_px, icon_size_px))
        self.btn_save_as.setFixedSize(button_size, button_size)
        self.btn_save_as.setAutoRaise(False)
        self.btn_save_as.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_save_as.clicked.connect(self.saveAsRequested.emit)

        self.btn_load = QToolButton(self.actions_container)
        self.btn_load.setObjectName("SecondaryButton")
        self.btn_load.setToolTip("Load Collection")
        self.btn_load.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_load.setIcon(QIcon(load_icon))
        self.btn_load.setIconSize(QSize(icon_size_px, icon_size_px))
        self.btn_load.setFixedSize(button_size, button_size)
        self.btn_load.setAutoRaise(False)
        self.btn_load.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_load.clicked.connect(self.loadRequested.emit)

        self.btn_add = QToolButton(self.actions_container)
        self.btn_add.setObjectName("PrimaryButton")
        self.btn_add.setToolTip("Add Dungeon")
        self.btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_add.setIcon(QIcon(add_icon))
        self.btn_add.setIconSize(QSize(icon_size_px, icon_size_px))
        self.btn_add.setFixedSize(button_size, button_size)
        self.btn_add.setAutoRaise(False)
        self.btn_add.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_add.clicked.connect(self.addRequested.emit)

        self.btn_delete = QToolButton(self.actions_container)
        self.btn_delete.setObjectName("DestructiveButton")
        self.btn_delete.setToolTip("Delete Dungeon")
        self.btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_delete.setIcon(QIcon(delete_icon))
        self.btn_delete.setIconSize(QSize(icon_size_px, icon_size_px))
        self.btn_delete.setFixedSize(button_size, button_size)
        self.btn_delete.setAutoRaise(False)
        self.btn_delete.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_delete.clicked.connect(self.deleteRequested.emit)

        actions_layout.addWidget(self.btn_save)
        actions_layout.addWidget(self.btn_save_as)
        actions_layout.addWidget(self.btn_load)
        actions_layout.addWidget(self.btn_add)
        actions_layout.addWidget(self.btn_delete)
        self.actions_container.setMinimumHeight(button_size)
        self.actions_container.hide()

        for button in (self.btn_save, self.btn_save_as, self.btn_load, self.btn_add, self.btn_delete):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setStyleSheet("""
                QToolButton {
                    padding: 4px;
                    border-radius: 6px;
                    margin: 0px;
                    min-width: 36px;
                    max-width: 36px;
                    min-height: 36px;
                    max-height: 36px;
                }
            """)

        self.player_button = QToolButton(self._text_parent)
        self.player_button.setToolTip("Player Placement Mode")
        self.player_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.player_button.setText("P")
        self.player_button.setCheckable(True)
        self.player_button.setFixedSize(button_size, button_size)
        player_font = self.player_button.font()
        if player_font.pointSize() <= 0:
            player_font.setPointSize(12)
        player_font.setBold(True)
        self.player_button.setFont(player_font)
        self.player_button.setStyleSheet("""
            QToolButton {
                padding: 4px;
                border-radius: 6px;
                background-color: #f59e0b;
                color: #ffffff;
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                margin: 0px;
            }
            QToolButton:hover {
                background-color: #fbbf24;
            }
            QToolButton:pressed {
                background-color: #f97316;
            }
            QToolButton:checked {
                background-color: #f97316;
            }
        """)
        self.player_button.toggled.connect(self.playerPlacementToggled.emit)
        self.player_button.hide()

        self.autosave_button = QToolButton(self._text_parent)
        self.autosave_button.setToolTip("Autosave Collection")
        self.autosave_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.autosave_button.setText("AS")
        self.autosave_button.setCheckable(True)
        self.autosave_button.setFixedSize(button_size, button_size)
        autosave_font = self.autosave_button.font()
        if autosave_font.pointSize() <= 0:
            autosave_font.setPointSize(10)
        autosave_font.setBold(True)
        self.autosave_button.setFont(autosave_font)
        self.autosave_button.setStyleSheet(
            """
            QToolButton {
                padding: 4px;
                border-radius: 6px;
                background-color: #334155;
                color: #ffffff;
                min-width: 36px;
                max-width: 36px;
                min-height: 36px;
                max-height: 36px;
                margin: 0px;
            }
            QToolButton:hover {
                background-color: #475569;
            }
            QToolButton:pressed {
                background-color: #1d4ed8;
            }
            QToolButton:checked {
                background-color: #2563eb;
            }
        """
        )
        self.autosave_button.toggled.connect(self.autosaveToggled.emit)
        self.autosave_button.hide()

        collapse_icon_obj = QIcon(collapse_icon) if os.path.exists(collapse_icon) else QIcon()
        self.collapse_button = DungeonCollapseButton(collapse_icon_obj, self._text_parent)
        self.collapse_button.clicked.connect(self.collapse)
        self.collapse_button.hide()

        text_layout.addWidget(self.header_label)
        text_layout.addWidget(self.sub_label)

        self.carousel_container = QWidget(self._text_parent)
        self.carousel_container.setObjectName("TransparentContainer")
        self.carousel_layout = QHBoxLayout(self.carousel_container)
        self.carousel_layout.setContentsMargins(0, 0, 0, 8)
        self.carousel_layout.setSpacing(0)
        self._carousel_widget: QWidget | None = None
        self.carousel_container.hide()

        self._position_text_container()

        self._apply_progress()

    def set_ui_enabled(self, enabled: bool) -> None:
        enabled_bool = bool(enabled)
        self._ui_enabled = enabled_bool
        self.setEnabled(enabled_bool)
        self.setVisible(enabled_bool)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not enabled_bool)

        self.text_container.setEnabled(enabled_bool)
        self.text_container.setVisible(enabled_bool)
        self.text_container.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not enabled_bool)

        if not enabled_bool:
            self._expand_anim.stop()
            self._expanded = False
            self._expand_progress = 0.0
            self.preview.setEnabled(False)
            self.actions_container.setVisible(False)
            self.actions_container.setEnabled(False)
            self.carousel_container.setVisible(False)
            self.carousel_container.setEnabled(False)
            if hasattr(self, "player_button"):
                self.player_button.setVisible(False)
                self.player_button.setEnabled(False)
            if hasattr(self, "autosave_button"):
                self.autosave_button.setVisible(False)
                self.autosave_button.setEnabled(False)
            if hasattr(self, "collapse_button"):
                self.collapse_button.setVisible(False)
                self.collapse_button.setEnabled(False)
            return

        self.preview.setEnabled(True)
        self._position_text_container()
        self._update_overlay_visibility()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._expand_progress > 0:
            self._apply_progress()
        self._position_text_container()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        text_parent = getattr(self, "_text_parent", None)
        if watched is text_parent and event.type() == QEvent.Type.Resize:
            self._position_text_container()
            return super().eventFilter(watched, event)
        if watched is getattr(self, "header_label", None):
            if not self.header_label.isReadOnly():
                return super().eventFilter(watched, event)
            if event.type() == QEvent.Type.MouseButtonDblClick:
                if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                    if self._expanded:
                        self._start_header_edit()
                    else:
                        self._expand_only()
                    return True
            if event.type() == QEvent.Type.MouseButtonPress:
                if isinstance(event, QMouseEvent) and event.button() == Qt.MouseButton.LeftButton:
                    self._expand_only()
                    return True
        if watched is getattr(self, "text_container", None) and event.type() == QEvent.Type.MouseButtonPress:
            mouse_event = event
            if isinstance(mouse_event, QMouseEvent) and mouse_event.button() == Qt.MouseButton.LeftButton:
                self._expand_only()
                return True
        return super().eventFilter(watched, event)

    def _expand_only(self) -> None:
        if not self._ui_enabled:
            return
        if self._expanded:
            return
        self._expanded = True
        self._expand_anim.stop()
        self._expand_anim.setStartValue(self._expand_progress)
        self._expand_anim.setEndValue(1.0)
        self._expand_anim.start()
        self.expandedChanged.emit(self._expanded)

    def _toggle_expanded(self) -> None:
        if not self._ui_enabled:
            return
        self._expanded = not self._expanded
        self._expand_anim.stop()
        self._expand_anim.setStartValue(self._expand_progress)
        self._expand_anim.setEndValue(1.0 if self._expanded else 0.0)
        self._expand_anim.start()
        self.expandedChanged.emit(self._expanded)

    def collapse(self) -> None:
        if not self._ui_enabled:
            return
        if not self._expanded:
            return
        self._expanded = False
        self._expand_anim.stop()
        self._expand_anim.setStartValue(self._expand_progress)
        self._expand_anim.setEndValue(0.0)
        self._expand_anim.start()
        self.expandedChanged.emit(False)

    def _expanded_params(self) -> dict[str, float]:
        parent = self.parentWidget() or self
        target_width = max(280.0, float(parent.width()) * 0.5)
        target_height = max(160.0, float(parent.height()) * 0.3)
        shape_width = max(200.0, target_width)
        text_box_width = min(max(240.0, shape_width - 24.0), 640.0)
        text_box_height = max(72.0, float(getattr(self, "_text_min_height", 0) or 0))
        carousel_height = 0.0
        if hasattr(self, "carousel_container"):
            carousel_height = float(self.carousel_container.sizeHint().height())
        carousel_spacing = 12.0
        bottom_pad = 18.0
        desired_rect_height = 16.0 + text_box_height + carousel_spacing + carousel_height + bottom_pad
        rect_height = max(200.0, target_height, desired_rect_height)
        return {
            "shape_width": shape_width,
            "rect_height": rect_height,
            "tri_height": 0.0,
            "tip_cut": 0.0,
            "join_cut": 0.0,
            "rect_bottom_cut": 0.0,
            "top_radius": 12.0,
            "text_box_width": text_box_width,
            "text_box_height": text_box_height,
            "text_box_offset_x": 0.0,
            "text_box_offset_y": 16.0,
            "text_box_padding": 6.0,
            "text_header_size": 22.0,
            "text_sub_size": 16.0,
            "text_line_gap": 0.0,
            "top_padding": 12.0,
            "outline_width": 1.0,
            "x_offset": 0.0,
            "outer_pad": 20.0,
        }

    def _apply_progress(self) -> None:
        def lerp(a: float, b: float, t: float) -> float:
            return a + (b - a) * t

        expanded = self._expanded_params()
        t = self._expand_progress
        collapsed = self._collapsed

        stable_keys = {
            "text_box_padding",
            "text_header_size",
            "text_sub_size",
            "text_line_gap",
        }

        params = {}
        for key, c_val in collapsed.items():
            if key in stable_keys:
                params[key] = float(c_val)
                continue
            e_val = expanded.get(key, c_val)
            params[key] = lerp(float(c_val), float(e_val), t)

        self._current_params = params
        shape_width = params["shape_width"]
        tri_height = params["tri_height"]
        top_padding = params["top_padding"]
        outer_pad = params["outer_pad"]

        preview_width = max(200, int(shape_width + outer_pad * 2))
        preview_height = max(120, int(params["rect_height"] + tri_height + top_padding + outer_pad * 2))
        self.preview.setFixedSize(preview_width, preview_height)
        shape_width = max(1.0, float(preview_width) - outer_pad * 2)
        rect_height = max(1.0, float(preview_height) - tri_height - top_padding - outer_pad * 2)
        self.preview.set_shape_params(
            shape_width=shape_width,
            rect_height=rect_height,
            tri_height=tri_height,
            tip_cut=params["tip_cut"],
            join_cut=params["join_cut"],
            rect_bottom_cut=params["rect_bottom_cut"],
            top_radius=params["top_radius"],
            text_box_width=params["text_box_width"],
            text_box_height=params["text_box_height"],
            text_box_offset_x=params["text_box_offset_x"],
            text_box_offset_y=params["text_box_offset_y"],
            text_box_padding=params["text_box_padding"],
            text_header_size=params["text_header_size"],
            text_sub_size=params["text_sub_size"],
            text_line_gap=params["text_line_gap"],
            top_padding=top_padding,
            outline_width=params["outline_width"],
            x_offset=params["x_offset"],
        )
        self._position_text_container()
        self._update_overlay_visibility()

    def getExpandProgress(self) -> float:
        return self._expand_progress

    def setExpandProgress(self, value: float) -> None:
        self._expand_progress = max(0.0, min(1.0, float(value)))
        self._apply_progress()

    expandProgress = Property(float, fget=getExpandProgress, fset=setExpandProgress)

    def set_header_text(self, text: str) -> None:
        self._header_text = text
        if self.header_label.isReadOnly():
            self.header_label.setText(text)
            self.header_label.adjustSize()
        self.header_dirty.setFont(self.header_label.font())
        self._position_text_container()

    def set_header_dirty(self, dirty: bool) -> None:
        self._header_dirty_visible = bool(dirty)
        if self.header_label.isReadOnly():
            self.header_dirty.setVisible(self._header_dirty_visible)
        self._position_text_container()

    def set_sub_text(self, text: str) -> None:
        self.sub_label.setText(text)
        self.sub_label.adjustSize()
        self._position_text_container()

    def _commit_header_name(self) -> None:
        if not self._header_editing:
            return
        name = self.header_label.text().strip()
        self._header_editing = False
        if not name:
            self.header_label.setText(self._header_text)
            self.header_label.adjustSize()
        else:
            self.collectionRenameRequested.emit(name)
        self.header_dirty.setVisible(self._header_dirty_visible)
        self._position_text_container()

    def _start_header_edit(self) -> None:
        if self._header_editing:
            return
        self._header_editing = True
        self.header_dirty.hide()
        self.header_label.start_edit(select_all=True)
        self._position_text_container()

    def set_carousel_widget(self, widget: QWidget | None) -> None:
        if self._carousel_widget is widget:
            return
        if self._carousel_widget is not None:
            self.carousel_layout.removeWidget(self._carousel_widget)
            self._carousel_widget.setParent(None)
        self._carousel_widget = widget
        if widget is None:
            return
        widget.setParent(self.carousel_container)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.carousel_layout.addWidget(widget, 1)
        self.carousel_layout.setStretch(0, 1)
        self._position_text_container()

    def set_player_placement_active(self, active: bool) -> None:
        if not hasattr(self, "player_button"):
            return
        with QSignalBlocker(self.player_button):
            self.player_button.setChecked(bool(active))

    def set_autosave_active(self, active: bool) -> None:
        if not hasattr(self, "autosave_button"):
            return
        with QSignalBlocker(self.autosave_button):
            self.autosave_button.setChecked(bool(active))

    def refresh_overlay_positions(self) -> None:
        if self._expand_progress > 0:
            self._apply_progress()
        else:
            self._position_text_container()

    def carousel_metrics(self) -> tuple[int, int]:
        return self._carousel_layout

    def _update_overlay_visibility(self) -> None:
        if not self._ui_enabled:
            self.actions_container.setVisible(False)
            self.carousel_container.setVisible(False)
            self.actions_container.setEnabled(False)
            self.carousel_container.setEnabled(False)
            if hasattr(self, "player_button"):
                self.player_button.setVisible(False)
                self.player_button.setEnabled(False)
            if hasattr(self, "autosave_button"):
                self.autosave_button.setVisible(False)
                self.autosave_button.setEnabled(False)
            if hasattr(self, "collapse_button"):
                self.collapse_button.setVisible(False)
                self.collapse_button.setEnabled(False)
            return
        visible = self._expand_progress > 0.35
        self.actions_container.setVisible(visible)
        self.carousel_container.setVisible(visible)
        self.actions_container.setEnabled(visible)
        self.carousel_container.setEnabled(visible)
        if hasattr(self, "player_button"):
            self.player_button.setVisible(visible)
            self.player_button.setEnabled(visible)
        if hasattr(self, "autosave_button"):
            self.autosave_button.setVisible(visible)
            self.autosave_button.setEnabled(visible)
        if hasattr(self, "collapse_button"):
            self.collapse_button.setVisible(visible)
            self.collapse_button.setEnabled(visible)

    def _position_text_container(self) -> None:
        if not hasattr(self, "text_container"):
            return
        if not self._ui_enabled:
            return
        params = getattr(self, "_current_params", self._collapsed)
        base = self._collapsed
        text_box_width = float(base.get("text_box_width", self._collapsed["text_box_width"]))
        text_box_height = float(base.get("text_box_height", self._collapsed["text_box_height"]))
        text_box_padding = float(base.get("text_box_padding", self._collapsed["text_box_padding"]))
        text_line_gap = float(base.get("text_line_gap", self._collapsed["text_line_gap"]))
        text_box_height = max(text_box_height, float(self._text_min_height))
        offset_x = float(base.get("text_box_offset_x", self._collapsed["text_box_offset_x"]))
        offset_y = float(base.get("text_box_offset_y", self._collapsed["text_box_offset_y"]))
        top_padding = float(base.get("top_padding", self._collapsed["top_padding"]))
        top_margin = self.layout().contentsMargins().top() if self.layout() else 0

        parent = getattr(self, "_text_parent", None) or self
        global_center_x = parent.width() / 2
        global_x = global_center_x - text_box_width / 2 + offset_x
        global_y = top_margin + top_padding + offset_y

        local_x = int(round(global_x))
        local_y = int(round(global_y))
        label_width = max(0, int(text_box_width - text_box_padding * 2))
        self.header_label.setFixedWidth(label_width)
        self.sub_label.setFixedWidth(label_width)
        self.header_dirty.setFixedWidth(self.header_dirty.sizeHint().width())
        actions_size = self.actions_container.sizeHint()
        actions_height = max(self.actions_container.height(), int(actions_size.height()))
        header_height = max(self.header_label.height(), actions_height)
        sub_height = max(0, self.sub_label.height())
        needed_height = int(text_box_padding * 2 + text_line_gap + header_height + sub_height)
        text_box_height = max(text_box_height, needed_height)
        self.text_container.setFixedSize(int(text_box_width), int(text_box_height))
        self.text_container.move(local_x, local_y)
        self.text_container.raise_()

        shape_width = float(params.get("shape_width", self._collapsed["shape_width"]))
        rect_height = float(params.get("rect_height", self._collapsed["rect_height"]))
        shape_x = global_center_x - shape_width / 2 + float(params.get("x_offset", 0.0))
        shape_y = top_margin + float(params.get("top_padding", self._collapsed["top_padding"]))

        if self.header_dirty.isVisible():
            header_metrics = QFontMetrics(self.header_label.font())
            header_text = self.header_label.text()
            header_text_width = header_metrics.horizontalAdvance(header_text)
            dirty_width = self.header_dirty.sizeHint().width()
            header_x = float(text_box_padding) + max(0.0, (label_width - header_text_width) / 2.0) + header_text_width + 4.0
            header_x = min(header_x, float(text_box_padding) + label_width - dirty_width)
            header_y = float(text_box_padding) - 3.0
            self.header_dirty.move(int(round(header_x)), int(round(header_y)))
            self.header_dirty.raise_()

        actions_width = int(actions_size.width())
        actions_height = max(actions_height, 0)
        if actions_width > 0 and actions_height > 0:
            self.actions_container.resize(actions_width, actions_height)
            actions_x = int(round(shape_x + shape_width - actions_width - 16))
            actions_y = int(round(shape_y + 16))
            self.actions_container.move(actions_x, actions_y)
            self.actions_container.raise_()

        if hasattr(self, "player_button"):
            button = self.player_button
            button_x = int(round(shape_x + 16))
            button_y = int(round(shape_y + 16))
            button.move(button_x, button_y)
            button.raise_()
            if hasattr(self, "autosave_button"):
                autosave_button = self.autosave_button
                autosave_button.move(button_x + button.width() + 8, button_y)
                autosave_button.raise_()

        rect_height = float(params.get("rect_height", self._collapsed["rect_height"]))
        shape_width = float(params.get("shape_width", self._collapsed["shape_width"]))
        carousel_spacing = 12.0
        carousel_width = max(0.0, shape_width - 24.0)
        carousel_height_budget = max(0.0, rect_height - (text_box_height + carousel_spacing * 2))
        carousel_x = global_center_x - carousel_width / 2 + float(params.get("x_offset", 0.0))
        carousel_y = global_y + text_box_height + carousel_spacing

        carousel_height_target = max(1.0, float(self.carousel_container.sizeHint().height()))
        new_layout = (int(carousel_width), int(carousel_height_target))
        if new_layout != self._carousel_layout and self._expand_progress > 0.1:
            self._carousel_layout = new_layout
            self.carouselLayoutChanged.emit(new_layout[0], new_layout[1])

        carousel_height = carousel_height_target
        if carousel_width > 0 and carousel_height > 0:
            self.carousel_container.setFixedSize(int(carousel_width), int(carousel_height))
            self.carousel_container.move(int(round(carousel_x)), int(round(carousel_y)))
            self.carousel_container.raise_()

        if hasattr(self, "collapse_button"):
            button = self.collapse_button
            button_height = button.height()
            shape_x = global_center_x - shape_width / 2 + float(params.get("x_offset", 0.0))
            shape_y = top_margin + float(params.get("top_padding", self._collapsed["top_padding"]))
            button_width = int(max(120.0, min(shape_width - 32.0, 200.0)))
            button.resize(button_width, button_height)
            button_x = int(round(shape_x + shape_width / 2 - button_width / 2))
            button_y = int(round(shape_y + rect_height - button_height - 8))
            button.move(button_x, button_y)
            button.raise_()



class DungeonAppletWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("DungeonApplet")
        self._online_mode = ONLINE_MODE_LOCAL_DM
        self._host_controller: HostSessionController | None = None
        self._client_controller: ClientSessionController | None = None
        self._host_port: int | None = None
        self._host_ip: str = ""
        self._online_session_id: str = "local"
        self._online_runtime_cache_id: str = "local"
        self._local_player_id: str | None = None
        self._local_player_name: str = ""
        self._local_profile = self._load_or_create_local_profile()
        self._persistent_local_player_id: str = get_or_create_local_player_id()
        self._character_id_registry: dict[str, str] = dict(
            self._local_profile.get("character_ids", {})
            if isinstance(self._local_profile.get("character_ids"), dict)
            else {}
        )
        self._known_player_profiles: dict[str, dict] = dict(
            self._local_profile.get("known_players", {})
            if isinstance(self._local_profile.get("known_players"), dict)
            else {}
        )
        self._local_profile["player_id"] = self._persistent_local_player_id
        self._pending_player_state_update: dict | None = None
        self._pending_player_state_update_request_id: str = ""
        self._player_connection_ready: bool = False
        self._awaiting_player_snapshot: bool = False
        self._suppress_external_inventory_forward = False
        self._online_inventory_sync_fingerprints: dict[str, str] = {}
        self._approved_host_inventory_sync_characters: set[str] = set()
        self._pending_link_entity_requests: dict[str, dict] = {}
        self._pending_unlink_entity_requests: dict[str, dict] = {}
        self._pending_link_conflicts: dict[str, dict] = {}
        self._suppressed_link_conflicts: dict[str, str] = {}
        self._host_link_conflict_response_cache: dict[str, dict] = {}
        self._ignore_player_overwrite_requests: bool = False
        self._sent_character_override_fingerprints: dict[str, str] = {}
        self._host_unknown_item_review_cache: dict[str, dict] = {}
        self._suppress_client_disconnect_handler: bool = False
        self._join_retry_prompt_open: bool = False
        self._reconnect_status_dialog: QDialog | None = None
        self._reconnect_status_label: QLabel | None = None
        self._reconnect_retry_button: QPushButton | None = None
        self._reconnect_dismiss_button: QPushButton | None = None
        self._reconnect_status_message_base: str = ""
        self._reconnect_status_animate: bool = False
        self._reconnect_status_dot_count: int = 1
        self._reconnect_status_anim_timer = QTimer(self)
        self._reconnect_status_anim_timer.setSingleShot(False)
        self._reconnect_status_anim_timer.setInterval(420)
        self._reconnect_status_anim_timer.timeout.connect(self._on_reconnect_status_animation_tick)
        self._debug_instance_id: str = uuid.uuid4().hex[:8]
        self._debug_log_enabled: bool = str(
            os.environ.get("DMT_ONLINE_DEBUG_LOG", "0")
        ).strip().lower() not in {"0", "false", "no", "off"}
        self._debug_log_path: Path = self._resolve_debug_log_path()
        self._connected_players: dict[str, str] = {}
        self._suppress_network_sync = False
        self._suppress_ping_sync = False
        self._suppress_remote_apply = False
        self._view_mode = "dm"
        self._collection_name = "Dungeon Collection"
        self._collection_id = generate_named_object_id(self._collection_name, "collection")
        self._collection_path: Path | None = None
        self._collection_meta_dirty = False
        self._collection_dirty = False
        self._autosave_enabled = bool(self._local_profile.get("autosave_enabled", False))
        self._dungeons: list[dict] = []
        self._active_dungeon_id: str | None = None
        self._players_dungeon_id: str | None = None
        self._scene_item_refs: list[QGraphicsItem] = []
        self._collection_expanded = False
        self._suppress_change_tracking = False
        self._suppress_list_edits = False
        self._tile_size = QSize(160, 120)
        self._tile_widgets: dict[str, DungeonTileWidget] = {}
        self._refreshing_dungeon_list = False
        self._pending_dungeon_list_refresh = False
        self._pending_dungeon_list_preserve_selection = True
        self._player_placement_mode = False
        self._session_panels_collapsed = False
        self._session_loot_pool: list[dict] = []
        self._loot_claim_reservations: dict[str, dict] = {}
        self._loot_claim_entry_reservations: dict[str, str] = {}
        self._pending_loot_claim_finalizations: dict[str, dict] = {}
        self._loot_claim_finalize_response_cache: dict[str, dict] = {}
        self._pending_loot_claim_rollbacks: dict[str, dict] = {}
        self._pending_add_loot_from_inventory_requests: dict[str, dict] = {}
        self._loot_pool_dirty = False
        self._loot_pool_signature = ""
        self._loot_pool_has_unseen_updates = False
        self._initiative_state: dict = {
            "active": False,
            "collapsed": False,
            "player_entries": {},
            "entity_entries": {},
        }
        self._initiative_panel_anim: QPropertyAnimation | None = None
        self._loot_pool_panel_anim: QPropertyAnimation | None = None
        self._forwarding_initiative_key = False
        self._initiative_inactive_preview_visible = False
        self._initiative_last_target: tuple[str, str] | None = None
        self._initiative_draft_values: dict[str, str] = {}
        self._initiative_value_warning: str = ""
        self._suppress_initiative_sync = False
        self._host_scene_sync_pending = False
        self._last_host_scene_signature = ""
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(220)
        self._preview_timer.timeout.connect(self._update_active_preview)
        self._collection_autosave_timer = QTimer(self)
        self._collection_autosave_timer.setSingleShot(False)
        self._collection_autosave_timer.setInterval(COLLECTION_AUTOSAVE_INTERVAL_MS)
        self._collection_autosave_timer.timeout.connect(self._run_collection_autosave)
        self._host_scene_sync_timer = QTimer(self)
        self._host_scene_sync_timer.setSingleShot(True)
        self._host_scene_sync_timer.setInterval(180)
        self._host_scene_sync_timer.timeout.connect(self._flush_host_scene_sync)
        self._host_scene_watchdog_timer = QTimer(self)
        self._host_scene_watchdog_timer.setSingleShot(False)
        self._host_scene_watchdog_timer.setInterval(450)
        self._host_scene_watchdog_timer.timeout.connect(self._on_host_scene_watchdog_tick)
        self._loot_claim_reservation_timer = QTimer(self)
        self._loot_claim_reservation_timer.setSingleShot(False)
        self._loot_claim_reservation_timer.setInterval(1000)
        self._loot_claim_reservation_timer.timeout.connect(self._release_stale_loot_claim_reservations)
        
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setRowStretch(0, 1)
        self._app = QApplication.instance()

        # 1. The Canvas
        self.canvas = DungeonCanvas(self)
        self.canvas.set_interaction_blocked_checker(self._player_interactions_temporarily_blocked)
        layout.addWidget(self.canvas, 0, 0)

        self._session_toggle_btn = SessionPanelsToggleButton(self)
        self._session_toggle_btn.setVisible(False)
        self._session_toggle_btn.clicked.connect(self._toggle_session_panels_collapsed)

        self._session_bottom_panel = QFrame(self)
        self._session_bottom_panel.setObjectName("SubPanel")
        self._session_bottom_panel.setVisible(False)
        self._session_panel_height = 220.0
        self._session_bottom_panel.setMinimumHeight(0)
        self._session_bottom_panel.setMaximumHeight(16777215)
        self._chat_panel = SessionChatPanel(self._session_bottom_panel)
        self._chat_panel.messageSubmitted.connect(self._on_chat_submitted)
        self._server_log_panel = ServerLogPanel(self._session_bottom_panel)
        self._server_log_panel.setVisible(False)
        self._session_content = QWidget(self._session_bottom_panel)
        content_layout = QHBoxLayout(self._session_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(8)
        content_layout.addWidget(self._chat_panel, 2)
        content_layout.addWidget(self._server_log_panel, 1)
        bottom_layout = QVBoxLayout(self._session_bottom_panel)
        bottom_layout.setContentsMargins(8, 8, 8, 8)
        bottom_layout.setSpacing(0)
        bottom_layout.addWidget(self._session_content, 1)
        self._session_panel_height_anim = QPropertyAnimation(self, b"sessionPanelHeight", self)
        self._session_panel_height_anim.setDuration(200)
        self._session_panel_height_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._session_panel_height_anim.finished.connect(self._on_session_panel_anim_finished)
        self._position_session_overlay()


        # Icon Paths
        icon_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
        
        icon_origin = os.path.join(icon_dir, "origin.svg")
        icon_plus = os.path.join(icon_dir, "plus_white.svg")
        icon_minus = os.path.join(icon_dir, "minus_white.svg")
        icon_loot_pool = os.path.join(icon_dir, "lootpool.png")

        # 2. HUD Overlays (Transparent Containers)
        hud_style = "background-color: transparent; border: none;"

        self._loot_pool_btn = QToolButton(self)
        self._loot_pool_btn.setObjectName("SecondaryButton")
        self._loot_pool_btn.setToolTip("Show Loot Pool")
        self._loot_pool_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._loot_pool_btn.setFixedSize(40, 40)
        self._loot_pool_btn.setIcon(QIcon(icon_loot_pool))
        self._loot_pool_btn.setIconSize(QSize(24, 24))
        self._loot_pool_btn.clicked.connect(self._toggle_loot_pool_panel)
        self._loot_pool_btn.setVisible(False)
        self._loot_pool_badge = QLabel("!", self._loot_pool_btn)
        self._loot_pool_badge.setFixedSize(14, 14)
        self._loot_pool_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loot_pool_badge.setStyleSheet(
            "background-color: #3b82f6; color: white; border-radius: 7px; font-size: 10px; font-weight: bold;"
        )
        self._loot_pool_badge.hide()
        self._loot_pool_panel = self._build_loot_pool_panel(icon_dir)
        self._loot_pool_panel.hide()
        self._initiative_overlay = self._build_initiative_overlay()
        self._initiative_overlay.hide()
        
        # Top Left: Origin + Coords
        tl_hud = QWidget()
        self._tl_hud = tl_hud
        tl_hud.setStyleSheet("background-color: transparent;")
        tl_layout = QHBoxLayout(tl_hud)
        tl_layout.setContentsMargins(20, 20, 20, 20)
        tl_layout.setSpacing(10)

        self.btn_origin = QPushButton()
        self.btn_origin.setIcon(QIcon(icon_origin))
        self.btn_origin.setIconSize(QSize(22, 22))
        self.btn_origin.setFixedSize(32, 32)
        self.btn_origin.setToolTip("Go to Origin")
        self.btn_origin.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_origin.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 40);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 60);
            }
        """)
        self.btn_origin.clicked.connect(self.canvas.reset_view)

        self.coord_label = QLabel("X: 0, Y: 0")
        self.coord_label.setFixedHeight(32) # Match button height exactly
        self.coord_label.setStyleSheet("""
            color: #fafafa; 
            font-family: monospace; 
            font-size: 12px; 
            background-color: rgba(9, 9, 11, 150); 
            padding: 0 12px; 
            border-radius: 6px;
            border: 1px solid rgba(255, 255, 255, 20);
        """)
        self.coord_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.coord_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        tl_layout.addWidget(self.btn_origin, 0, Qt.AlignmentFlag.AlignVCenter)
        tl_layout.addWidget(self.coord_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(tl_hud, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        # Bottom Right: Zoom Controls
        br_hud = QWidget(self)
        self._br_hud = br_hud
        br_hud.setStyleSheet("background-color: transparent;")
        br_layout = QHBoxLayout(br_hud)
        br_layout.setContentsMargins(20, 20, 20, 20)
        br_layout.setSpacing(8)
        br_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.zoom_label = QLabel("100%")
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.zoom_label.setFixedWidth(80) # Fixed width for large numbers
        self.zoom_label.setStyleSheet("""
            color: #fafafa; 
            font-size: 12px; 
            background-color: rgba(9, 9, 11, 150); 
            padding: 0 8px; 
            border-radius: 6px; 
            border: 1px solid rgba(255, 255, 255, 20);
            min-height: 36px;
        """)
        
        zoom_btn_style = """
            QPushButton {
                background-color: transparent;
                border: none;
                border-radius: 18px;
            }
            QPushButton:hover {
                background-color: rgba(255, 255, 255, 40);
            }
            QPushButton:pressed {
                background-color: rgba(255, 255, 255, 60);
            }
        """

        self.btn_zoom_out = QPushButton()
        self.btn_zoom_out.setIcon(QIcon(icon_minus))
        self.btn_zoom_out.setIconSize(QSize(20, 20))
        self.btn_zoom_out.setFixedSize(36, 36)
        self.btn_zoom_out.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zoom_out.setStyleSheet(zoom_btn_style)
        self.btn_zoom_out.clicked.connect(self.canvas.zoom_out)
        
        self.btn_zoom_in = QPushButton()
        self.btn_zoom_in.setIcon(QIcon(icon_plus))
        self.btn_zoom_in.setIconSize(QSize(20, 20))
        self.btn_zoom_in.setFixedSize(36, 36)
        self.btn_zoom_in.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_zoom_in.setStyleSheet(zoom_btn_style)
        self.btn_zoom_in.clicked.connect(self.canvas.zoom_in)
        
        br_layout.addWidget(self.zoom_label)
        br_layout.addWidget(self.btn_zoom_out)
        br_layout.addWidget(self.btn_zoom_in)
        br_hud.adjustSize()

        self._autosave_status_label = QLabel("", self)
        self._autosave_status_label.setStyleSheet(
            "QLabel { color: rgba(175, 175, 175, 200); font-size: 11px; background-color: transparent; }"
        )
        self._autosave_status_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._autosave_status_label.hide()

        # Top Center: Dungeon Collection UI removed for fresh rebuild
        self._collection_overlay = None
        self._collection_shell = None
        self._collection_anim = None

        self._dungeon_list = QListWidget(self)
        self._dungeon_list.setObjectName("DungeonCollectionList")
        self._dungeon_list.setViewMode(QListWidget.ViewMode.IconMode)
        self._dungeon_list.setFlow(QListView.Flow.LeftToRight)
        self._dungeon_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self._dungeon_list.setMovement(QListWidget.Movement.Static)
        self._dungeon_list.setWrapping(False)
        self._dungeon_list.setSpacing(8)
        self._dungeon_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._dungeon_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._dungeon_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._dungeon_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._dungeon_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._dungeon_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._dungeon_list.customContextMenuRequested.connect(self._show_dungeon_context_menu)
        self._dungeon_list.currentItemChanged.connect(self._on_dungeon_selection_changed)
        self._dungeon_list.itemChanged.connect(self._on_dungeon_item_edited)
        self._dungeon_list.setStyleSheet("""
            QListWidget#DungeonCollectionList {
                background-color: transparent;
                border: none;
            }
            QListWidget#DungeonCollectionList::item {
                background-color: transparent;
                padding: 4px;
                margin: 0px;
                color: #e5e7eb;
            }
            QListWidget#DungeonCollectionList::item:hover {
                background-color: transparent;
            }
            QListWidget#DungeonCollectionList::item:selected {
                background-color: transparent;
                color: #60a5fa;
            }
            QListWidget#DungeonCollectionList::item:selected:active,
            QListWidget#DungeonCollectionList::item:selected:!active {
                background-color: transparent;
                color: #60a5fa;
            }
        """)

        # 3. Floating Tool Panel (Left)
        self.tool_panel = FloatingToolPanel(self)

        # 4. Entity Inspector (Right)
        self.inspector = EntityInspectorPanel(self)
        self.inspector.hide()
        # Pass undo stack to inspector
        self.inspector.undo_stack = self.canvas.undo_stack

        # 5. Dungeon Selection Widget (Top Center)
        self.selection_widget = DungeonSelectionWidget(self)
        layout.addWidget(self.selection_widget, 0, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        self.selection_widget.set_carousel_widget(self._dungeon_list)
        self.selection_widget.saveRequested.connect(self._save_collection)
        self.selection_widget.saveAsRequested.connect(self._save_collection_as)
        self.selection_widget.loadRequested.connect(self._load_collection_dialog)
        self.selection_widget.collectionRenameRequested.connect(self._rename_collection)
        self.selection_widget.addRequested.connect(self._add_dungeon)
        self.selection_widget.deleteRequested.connect(self._delete_active_dungeon)
        self.selection_widget.carouselLayoutChanged.connect(self._on_carousel_layout_changed)
        self.selection_widget.playerPlacementToggled.connect(self._on_player_placement_toggled)
        self.selection_widget.autosaveToggled.connect(self._on_collection_autosave_toggled)
        self.selection_widget.expandedChanged.connect(self._on_selection_expanded_changed)
        self.selection_widget.set_autosave_active(self._autosave_enabled)

        # Connect Signals
        self.canvas.viewChanged.connect(self._update_coords)
        self.canvas.zoomChanged.connect(self._update_zoom_label)
        self.canvas.toolChanged.connect(self.tool_panel.set_tool)
        self.tool_panel.toolChanged.connect(self._on_tool_changed)
        self.tool_panel.drawColorChanged.connect(self.canvas.set_stroke_color)
        self.tool_panel.lootPoolRequested.connect(self._toggle_loot_pool_panel)
        self.tool_panel.lootAddItemsRequested.connect(self._on_loot_add_items)
        self.canvas.pingPlaced.connect(self._on_local_ping_placed)
        self.canvas.scene().selectionChanged.connect(self._on_selection_changed)
        self.canvas.scene().changed.connect(self._on_scene_changed_for_online_sync)
        self.canvas.scene().changed.connect(self._refresh_scene_item_references)
        self.canvas.set_delete_change_callback(self._on_canvas_delete_items_changed)
        
        # FoW connections
        self.tool_panel.fogFillRequested.connect(self.canvas.fill_fog)
        self.tool_panel.fogClearRequested.connect(self.canvas.clear_fog)
        self.tool_panel.viewModeChanged.connect(self._on_view_mode_changed)
        self.tool_panel.undoRequested.connect(self.canvas.undo)
        self.tool_panel.redoRequested.connect(self.canvas.redo)
        self.tool_panel.deleteRequested.connect(self.canvas.delete_selected_items)
        self.tool_panel.layerChanged.connect(self.canvas.set_current_layer)
        self.inspector.set_player_options({})
        self.inspector.entityEdited.connect(self._mark_active_dungeon_dirty)
        self.inspector.entityEdited.connect(self._refresh_entity_duplicate_badges)
        self.inspector.ownerChanged.connect(self._on_entity_owner_changed)
        self.inspector.iconPathSelected.connect(self._on_deferred_icon_selected)
        self.inspector.linkCharacterRequested.connect(self._on_link_character_requested)
        self.inspector.unlinkCharacterRequested.connect(self._on_unlink_character_requested)
        self.canvas.undo_stack.indexChanged.connect(self._on_canvas_changed)
        try:
            from player_sheets import PLAYER_SHEET_EVENTS

            PLAYER_SHEET_EVENTS.inventorySaved.connect(self._on_external_character_inventory_saved)
        except Exception:
            pass

        self._save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self._save_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._save_shortcut.activated.connect(self._save_collection)
        self.canvas.set_stroke_color(self.tool_panel.current_draw_color())

        self._init_collection()
        self._refresh_loot_pool_list()
        QTimer.singleShot(0, self._update_collection_geometry)
        QTimer.singleShot(0, self._position_session_overlay)
        
        # Initial position: Use a timer to ensure the widget is laid out and has size
        # before centering, otherwise centerOn(0,0) might not work correctly.
        self.coord_label.setText("Centering...")
        QTimer.singleShot(250, self.canvas.reset_view)
        if self._app is not None:
            self._app.installEventFilter(self)
            self.destroyed.connect(self._remove_app_event_filter)
        self._debug_log("widget_init", app_event_filter=bool(self._app is not None))

    def start_online_host(self, port: int, collection_path: str | None = None) -> bool:
        self._debug_log(
            "start_online_host_begin",
            port=int(port),
            collection_path=str(collection_path or ""),
        )
        previous_runtime_cache_id = str(self._online_runtime_cache_id or "")
        self._session_loot_pool = []
        self._loot_claim_reservations.clear()
        self._loot_claim_entry_reservations.clear()
        self._pending_loot_claim_finalizations.clear()
        self._loot_claim_finalize_response_cache.clear()
        self._pending_loot_claim_rollbacks.clear()
        self._clear_pending_online_command_requests(reason="starting a hosted session")
        self._server_log_panel.set_ignore_overwrite_checked(False)
        self._initiative_state = {
            "active": False,
            "collapsed": False,
            "player_entries": {},
            "entity_entries": {},
        }
        self._initiative_draft_values.clear()
        self._refresh_loot_pool_list()
        if self._client_controller is not None:
            self._client_controller.disconnect()
        self._player_connection_ready = False
        self._awaiting_player_snapshot = False
        self._pending_player_state_update = None
        self._pending_player_state_update_request_id = ""
        self._approved_host_inventory_sync_characters.clear()
        self._host_unknown_item_review_cache.clear()
        if collection_path:
            path = Path(collection_path)
            if path.exists():
                if not self._load_collection_from_path(path):
                    return False
        if previous_runtime_cache_id and previous_runtime_cache_id != "local":
            self._clear_online_runtime_cache(previous_runtime_cache_id)
        self._online_session_id = f"host_{int(port)}"
        self._online_runtime_cache_id = self._runtime_cache_session_id_for(self._online_session_id)
        self._host_port = int(port)
        self._set_online_mode(ONLINE_MODE_DM_HOST)
        if self._host_controller is None:
            self._host_controller = HostSessionController(self)
            self._host_controller.log_line.connect(self._append_server_log)
            self._host_controller.players_changed.connect(self._update_connected_players)
            self._host_controller.chat_received.connect(self._append_chat_message)
            self._host_controller.command_received.connect(self._on_host_command_received)
            self._host_controller.snapshot_requested.connect(self._on_host_snapshot_requested)
        else:
            self._host_controller.stop()
        ok, error = self._host_controller.start(int(port))
        if not ok:
            self._debug_log("start_online_host_failed", port=int(port), error=str(error or ""))
            self._set_online_mode(ONLINE_MODE_LOCAL_DM)
            self._update_connected_players({})
            self._clear_online_runtime_cache(self._online_runtime_cache_id)
            QMessageBox.critical(self, "Host Failed", error or "Failed to start host server.")
            return False
        self._set_online_mode(ONLINE_MODE_DM_HOST)
        self._normalize_all_dungeon_icons_for_online()
        self._append_server_log(
            "Hosting started. Internet clients must connect to your public IP and forwarded port."
        )
        self._debug_log("start_online_host_ok", port=int(port))
        self._update_connected_players(self._host_controller.players)
        self._broadcast_snapshot_if_host()
        return True

    def join_online_session(
        self,
        host_ip: str,
        port: int,
        player_name: str,
        persistent_player_id: str | None = None,
    ) -> None:
        requested_player_name = str(player_name or "").strip() or "Player"
        requested_persistent_player_id = str(
            persistent_player_id or self._persistent_local_player_id or ""
        ).strip()
        if not requested_persistent_player_id:
            requested_persistent_player_id = generate_probabilistic_unique_id("player")
            self._append_server_log(
                "[WARN] Missing local player identity. Generated a temporary identity for this join."
            )
        self._debug_log(
            "join_online_session_begin",
            host_ip=str(host_ip),
            port=int(port),
            player_name=str(requested_player_name or ""),
            persistent_player_id=str(requested_persistent_player_id or ""),
        )
        previous_runtime_cache_id = str(self._online_runtime_cache_id or "")
        self._session_loot_pool = []
        self._loot_claim_reservations.clear()
        self._loot_claim_entry_reservations.clear()
        self._pending_loot_claim_finalizations.clear()
        self._loot_claim_finalize_response_cache.clear()
        self._pending_loot_claim_rollbacks.clear()
        self._clear_pending_online_command_requests(reason="starting a new join session")
        self._hide_reconnect_status_dialog()
        self._initiative_state = {
            "active": False,
            "collapsed": False,
            "player_entries": {},
            "entity_entries": {},
        }
        self._initiative_draft_values.clear()
        self._refresh_loot_pool_list()
        if self._host_controller is not None:
            self._host_controller.stop()
        if previous_runtime_cache_id and previous_runtime_cache_id != "local":
            self._clear_online_runtime_cache(previous_runtime_cache_id)
        self._update_connected_players({})
        self._collection_path = None
        self._collection_autosave_timer.stop()
        self._online_session_id = f"join_{host_ip}_{int(port)}".replace(":", "_")
        self._online_runtime_cache_id = self._runtime_cache_session_id_for(self._online_session_id)
        self._host_ip = host_ip
        self._host_port = int(port)
        self._local_player_name = requested_player_name
        self._local_profile["last_player_name"] = self._local_player_name
        self._remember_known_player(requested_persistent_player_id, self._local_player_name)
        self._save_local_profile()
        self._local_player_id = None
        self._player_connection_ready = False
        self._awaiting_player_snapshot = False
        self._pending_player_state_update = None
        self._pending_player_state_update_request_id = ""
        self._approved_host_inventory_sync_characters.clear()
        self._host_unknown_item_review_cache.clear()
        self._update_workspace_tab_title(f"Join: {self._local_player_name}")
        self._set_online_mode(ONLINE_MODE_PLAYER)
        if self._client_controller is None:
            self._suppress_client_disconnect_handler = False
            self._client_controller = ClientSessionController(self)
            self._client_controller.log_line.connect(self._append_server_log)
            self._client_controller.connected.connect(self._on_client_connected)
            self._client_controller.disconnected.connect(self._on_client_disconnected)
            self._client_controller.players_changed.connect(self._update_connected_players)
            self._client_controller.chat_received.connect(self._append_chat_message)
            self._client_controller.snapshot_received.connect(self._on_client_snapshot_received)
            self._client_controller.command_result.connect(self._on_client_command_result)
            self._client_controller.icon_asset_received.connect(self._on_client_icon_asset)
            self._client_controller.ping_received.connect(self._on_network_ping_received)
            self._client_controller.reconnect_state_changed.connect(self._on_client_reconnect_state_changed)
            self._client_controller.client.hello_ack.connect(self._on_client_hello_ack)
        else:
            existing_client = getattr(self._client_controller, "client", None)
            self._suppress_client_disconnect_handler = bool(
                existing_client is not None
                and (
                    existing_client.is_connected()
                    or existing_client.is_connecting()
                )
            )
            self._client_controller.disconnect()
        self._client_controller.connect_to_host(
            host_ip,
            int(port),
            self._local_player_name,
            persistent_player_id=requested_persistent_player_id,
        )

    def _clear_online_runtime_cache(self, session_id: str | None = None) -> None:
        target_session = str(
            session_id or self._active_online_runtime_cache_id() or self._online_session_id or ""
        ).strip()
        if not target_session or target_session == "local":
            return
        clear_online_runtime_storage(target_session)

    def _runtime_cache_session_id_for(self, session_id: str) -> str:
        clean_session = str(session_id or "").strip() or "local"
        if clean_session == "local":
            return "local"
        return f"{clean_session}__{self._debug_instance_id}"

    def _active_online_runtime_cache_id(self) -> str:
        logical_session_id = str(self._online_session_id or "").strip() or "local"
        runtime_cache_id = str(self._online_runtime_cache_id or "").strip()
        if logical_session_id == "local":
            return "local"
        expected_runtime_cache_id = self._runtime_cache_session_id_for(logical_session_id)
        if runtime_cache_id != expected_runtime_cache_id:
            self._online_runtime_cache_id = expected_runtime_cache_id
        return self._online_runtime_cache_id

    def _set_online_mode(self, mode: str) -> None:
        previous_mode = str(self._online_mode)
        self._online_mode = mode
        self._debug_log("set_online_mode", previous=previous_mode, current=str(mode))
        is_online = mode in (ONLINE_MODE_DM_HOST, ONLINE_MODE_PLAYER)
        show_server_log = mode in (ONLINE_MODE_DM_HOST, ONLINE_MODE_PLAYER)
        is_player_mode = mode == ONLINE_MODE_PLAYER
        self._server_log_panel.setVisible(show_server_log)
        self._server_log_panel.set_ignore_overwrite_visible(False)
        self.selection_widget.set_ui_enabled(not is_player_mode)
        self._dungeon_list.setVisible(not is_player_mode)
        self._dungeon_list.setEnabled(not is_player_mode)
        self.tool_panel.btn_view_toggle.setVisible(mode != ONLINE_MODE_PLAYER)
        self.tool_panel.btn_layer.setVisible(mode != ONLINE_MODE_PLAYER)
        self.inspector.set_owner_assignment_enabled(mode != ONLINE_MODE_PLAYER)
        self.inspector.set_defer_icon_apply(is_player_mode)
        if is_player_mode:
            self._view_mode = "player"
            self.canvas.set_view_mode("player")
        else:
            self._view_mode = "dm"
            self.canvas.set_view_mode("dm")
        self._session_toggle_btn.setVisible(is_online)
        self._loot_pool_btn.setVisible(False)
        if not is_online:
            self._loot_pool_panel.hide()
            self._initiative_overlay.hide()
            self._initiative_reopen_btn.hide()
        else:
            self._initiative_reopen_btn.setVisible(mode == ONLINE_MODE_DM_HOST)
        if not is_online:
            self._set_session_panels_collapsed(True, animate=False)
            self._position_session_overlay()
        else:
            self._set_session_panels_collapsed(False, animate=False)
        if mode != ONLINE_MODE_DM_HOST:
            self._server_log_panel.set_ignore_overwrite_checked(False)
            self._host_scene_sync_pending = False
            self._host_scene_sync_timer.stop()
            self._host_scene_watchdog_timer.stop()
            self._loot_claim_reservation_timer.stop()
            self._loot_claim_reservations.clear()
            self._loot_claim_entry_reservations.clear()
            self._pending_loot_claim_finalizations.clear()
            self._pending_loot_claim_rollbacks.clear()
            self._clear_pending_online_command_requests(reason="leaving the current online session")
            self._host_unknown_item_review_cache.clear()
        else:
            self._server_log_panel.set_ignore_overwrite_checked(False)
            self._last_host_scene_signature = self._current_players_scene_signature()
            self._host_scene_watchdog_timer.start()
            if not self._loot_claim_reservation_timer.isActive():
                self._loot_claim_reservation_timer.start()
        if mode == ONLINE_MODE_PLAYER:
            if bool(self._session_loot_pool) and self._loot_pool_panel.isHidden():
                self._loot_pool_has_unseen_updates = True
        else:
            self._hide_reconnect_status_dialog()
            self._loot_pool_has_unseen_updates = False
            self._player_connection_ready = False
            self._awaiting_player_snapshot = False
            self._pending_player_state_update = None
            self._pending_player_state_update_request_id = ""
            self._online_inventory_sync_fingerprints.clear()
            self._approved_host_inventory_sync_characters.clear()
            self._pending_link_conflicts.clear()
            self._suppressed_link_conflicts.clear()
            self._host_link_conflict_response_cache.clear()
            self._sent_character_override_fingerprints.clear()
        self._render_initiative_overlay()
        self._update_loot_pool_badge()
        self._apply_online_permissions()

    def _toggle_session_panels_collapsed(self) -> None:
        self._set_session_panels_collapsed(not self._session_panels_collapsed, animate=True)

    def _position_session_overlay(self) -> None:
        margin = 10
        toggle_gap = 4
        panel_height = max(0, int(round(self._session_panel_height)))
        available_width = max(0, self.width() - (margin * 2))
        panel_y = self.height() - margin - panel_height
        if (not self._session_bottom_panel.isHidden()) and panel_height > 0 and available_width > 0:
            self._session_bottom_panel.setGeometry(margin, panel_y, available_width, panel_height)
            self._session_bottom_panel.raise_()
        else:
            self._session_bottom_panel.setGeometry(0, self.height(), 0, 0)

        toggle_w = self._session_toggle_btn.width()
        toggle_h = self._session_toggle_btn.height()
        toggle_x = int((self.width() - toggle_w) / 2)
        if panel_height > 0:
            toggle_y = max(0, panel_y - toggle_h - toggle_gap)
        else:
            toggle_y = max(0, self.height() - margin - toggle_h)
        self._session_toggle_btn.setGeometry(toggle_x, toggle_y, toggle_w, toggle_h)
        self._session_toggle_btn.raise_()
        self._position_floating_overlays()

    def _overlay_top_y(self) -> int | None:
        panel_height = max(0, int(round(self._session_panel_height)))
        if self._session_bottom_panel.isHidden() or panel_height <= 0:
            return None
        return int(self.height() - 10 - panel_height)

    def _required_overlay_lift_for_bottom(self, bottom_y: int, padding: int = 3) -> int:
        overlay_top = self._overlay_top_y()
        if overlay_top is None:
            return 0
        return max(0, int(bottom_y + padding - overlay_top))

    def _required_session_overlay_lift(self) -> int:
        """Legacy aggregate lift helper retained for tests/diagnostics."""
        required = 0
        if hasattr(self, "_br_hud") and self._br_hud.isVisible():
            zoom_height = max(self._br_hud.sizeHint().height(), self._br_hud.height())
            zoom_base_y = max(0, self.height() - 20 - zoom_height)
            bottom_margin = 0
            if self._br_hud.layout() is not None:
                bottom_margin = self._br_hud.layout().contentsMargins().bottom()
            zoom_bottom = zoom_base_y + zoom_height - bottom_margin
            required = max(required, self._required_overlay_lift_for_bottom(zoom_bottom))
        if hasattr(self, "tool_panel") and self.tool_panel.isVisible():
            tool_height = max(self.tool_panel.sizeHint().height(), self.tool_panel.height())
            tool_base_y = max(0, int((self.height() - tool_height) / 2))
            tool_bottom = tool_base_y + tool_height
            required = max(required, self._required_overlay_lift_for_bottom(tool_bottom))
        if hasattr(self, "inspector") and self.inspector.isVisible():
            inspector_height = max(
                1,
                int(self.inspector.minimumSizeHint().height()),
                int(self.inspector.sizeHint().height()),
            )
            inspector_base_y = int((self.height() - inspector_height) / 2)
            inspector_bottom = inspector_base_y + inspector_height
            required = max(required, self._required_overlay_lift_for_bottom(inspector_bottom))
        return max(0, int(required))

    def _position_floating_overlays(self) -> None:
        def _current_overlay_size(widget: QWidget, *, prefer_size_hint_height: bool = False) -> tuple[int, int]:
            current_w = int(widget.width())
            current_h = int(widget.height())
            min_hint = widget.minimumSizeHint()
            hint = widget.sizeHint()
            if min_hint is not None:
                current_w = max(current_w, int(min_hint.width()))
                current_h = max(current_h, int(min_hint.height()))
            if current_w <= 0:
                current_w = int(hint.width())
            if prefer_size_hint_height:
                min_h = int(min_hint.height()) if min_hint is not None else 0
                current_h = max(min_h, int(hint.height()))
            elif current_h <= 0:
                current_h = int(hint.height())
            return max(1, current_w), max(1, current_h)

        if hasattr(self, "_br_hud"):
            zoom_w, zoom_h = _current_overlay_size(self._br_hud)
            zoom_x = max(0, self.width() - 20 - zoom_w)
            zoom_base_y = max(0, self.height() - 20 - zoom_h)
            bottom_margin = 0
            if self._br_hud.layout() is not None:
                bottom_margin = self._br_hud.layout().contentsMargins().bottom()
            zoom_visible_bottom = zoom_base_y + zoom_h - bottom_margin
            zoom_lift = self._required_overlay_lift_for_bottom(zoom_visible_bottom)
            zoom_y = max(8, zoom_base_y - zoom_lift)
            self._br_hud.setGeometry(zoom_x, zoom_y, zoom_w, zoom_h)
            self._br_hud.raise_()
        if hasattr(self, "tool_panel"):
            tool_w, tool_h = _current_overlay_size(self.tool_panel)
            tool_x = 0
            tool_base_y = max(0, int((self.height() - tool_h) / 2))
            tool_bottom = tool_base_y + tool_h
            tool_lift = self._required_overlay_lift_for_bottom(tool_bottom)
            tool_y = max(8, tool_base_y - tool_lift)
            self.tool_panel.setGeometry(tool_x, tool_y, tool_w, tool_h)
            self.tool_panel.raise_()
        if hasattr(self, "inspector"):
            inspector_w, inspector_h = _current_overlay_size(
                self.inspector,
                prefer_size_hint_height=True,
            )
            inspector_x = max(0, self.width() - 12 - inspector_w)
            inspector_base_y = int((self.height() - inspector_h) / 2)
            inspector_bottom = inspector_base_y + inspector_h
            required_lift = self._required_overlay_lift_for_bottom(inspector_bottom, padding=8)
            inspector_y = max(8, inspector_base_y - required_lift)
            self.inspector.setGeometry(inspector_x, inspector_y, inspector_w, inspector_h)
            self.inspector.raise_()
        if hasattr(self, "_loot_pool_btn") and self._loot_pool_btn is not None:
            btn_size = self._loot_pool_btn.size()
            btn_x = max(8, self.width() - btn_size.width() - 64)
            btn_y = 12
            self._loot_pool_btn.move(btn_x, btn_y)
            self._loot_pool_btn.raise_()
            if hasattr(self, "_loot_pool_badge"):
                badge_x = 3
                badge_y = max(0, btn_size.height() - self._loot_pool_badge.height() - 3)
                self._loot_pool_badge.move(badge_x, badge_y)
                self._loot_pool_badge.raise_()
        if hasattr(self, "_loot_pool_panel") and self._loot_pool_panel is not None and self._loot_pool_panel.isVisible():
            loot_anim = getattr(self, "_loot_pool_panel_anim", None)
            if loot_anim is None or loot_anim.state() != QAbstractAnimation.State.Running:
                self._loot_pool_panel.setGeometry(self._target_loot_pool_geometry())
            self._loot_pool_panel.raise_()
        if hasattr(self, "_autosave_status_label") and self._autosave_status_label is not None:
            is_dm_view = self._online_mode in (ONLINE_MODE_LOCAL_DM, ONLINE_MODE_DM_HOST)
            has_status_text = bool(str(self._autosave_status_label.text() or "").strip())
            show_autosave_status = bool(self._autosave_enabled and is_dm_view and has_status_text)
            self._autosave_status_label.setVisible(show_autosave_status)
            if show_autosave_status:
                self._autosave_status_label.adjustSize()
                label_w, label_h = _current_overlay_size(self._autosave_status_label)
                label_x = 14
                label_base_y = max(0, self.height() - 14 - label_h)
                label_bottom = label_base_y + label_h
                label_lift = self._required_overlay_lift_for_bottom(label_bottom, padding=6)
                label_y = max(8, label_base_y - label_lift)
                self._autosave_status_label.setGeometry(label_x, label_y, label_w, label_h)
                self._autosave_status_label.raise_()
        self._position_initiative_overlay()

    def _target_loot_pool_geometry(self) -> QRect:
        margin = 12
        available_w = max(240, self.width() - (margin * 2))
        available_h = max(220, self.height() - (margin * 2))
        panel_w = max(364, int(available_w * 0.322))
        panel_h = max(380, int(available_h * 0.51))
        panel_w = min(panel_w, available_w)
        panel_h = min(panel_h, available_h)
        panel_x = max(8, int((self.width() - panel_w) / 2))
        panel_y = max(8, int((self.height() - panel_h) / 2))
        return QRect(panel_x, panel_y, panel_w, panel_h)

    def _target_initiative_geometry(self) -> QRect:
        margin = 12
        available_w = max(240, self.width() - (margin * 2))
        available_h = max(220, self.height() - (margin * 2))
        panel_w = max(399, int(available_w * 0.336))
        panel_h = max(290, int(available_h * 0.42))
        panel_w = min(panel_w, available_w)
        panel_h = min(panel_h, available_h)
        panel_x = max(8, int((self.width() - panel_w) / 2))
        panel_y = max(8, int((self.height() - panel_h) / 2))
        return QRect(panel_x, panel_y, panel_w, panel_h)

    def _animate_center_panel(
        self,
        panel: QWidget,
        *,
        show: bool,
        target_rect: QRect,
        attr_name: str,
        duration_ms: int = 170,
    ) -> None:
        existing = getattr(self, attr_name, None)
        if isinstance(existing, QPropertyAnimation):
            existing.stop()
        center = target_rect.center()
        min_w = max(1, int(panel.minimumWidth()), int(panel.minimumSizeHint().width()))
        min_h = max(1, int(panel.minimumHeight()), int(panel.minimumSizeHint().height()))
        collapsed = QRect(
            int(center.x() - (min_w / 2)),
            int(center.y() - (min_h / 2)),
            int(min_w),
            int(min_h),
        )
        if collapsed.width() > target_rect.width():
            collapsed.setWidth(max(1, target_rect.width()))
            collapsed.moveCenter(center)
        if collapsed.height() > target_rect.height():
            collapsed.setHeight(max(1, target_rect.height()))
            collapsed.moveCenter(center)
        if show:
            panel.setGeometry(collapsed)
            # Qt can clamp child geometry to minimum constraints; keep the animated
            # start rect centered even after that clamping.
            constrained = panel.geometry()
            if constrained.center() != center:
                constrained.moveCenter(center)
                panel.setGeometry(constrained)
            panel.show()
            panel.raise_()
        elif panel.isHidden():
            return
        anim = QPropertyAnimation(panel, b"geometry", self)
        anim.setDuration(max(80, int(duration_ms)))
        anim.setEasingCurve(
            QEasingCurve.Type.OutCubic if show else QEasingCurve.Type.InCubic
        )
        anim.setStartValue(panel.geometry())
        anim.setEndValue(target_rect if show else collapsed)

        if not show:
            def _hide_on_finish() -> None:
                if getattr(self, attr_name, None) is anim:
                    panel.hide()
            anim.finished.connect(_hide_on_finish)
        setattr(self, attr_name, anim)
        anim.start()

    def _build_loot_pool_panel(self, icon_dir: str) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("SubPanel")
        panel.setMinimumSize(364, 420)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title = QLabel("Loot Pool", panel)
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._loot_pool_collapse_btn = QPushButton("Collapse", panel)
        self._loot_pool_collapse_btn.setObjectName("SecondaryButton")
        self._loot_pool_collapse_btn.setProperty("compact", "true")
        self._loot_pool_collapse_btn.clicked.connect(self._toggle_loot_pool_panel)
        header.addWidget(self._loot_pool_collapse_btn)
        layout.addLayout(header)

        self._loot_pool_list = QListWidget(panel)
        self._loot_pool_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._loot_pool_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._loot_pool_list.setSelectionRectVisible(False)
        self._loot_pool_list.setMouseTracking(True)
        self._loot_pool_viewport = self._loot_pool_list.viewport()
        self._loot_pool_viewport.setMouseTracking(True)
        self._loot_pool_viewport.installEventFilter(self)
        self._loot_pool_list.setIconSize(QSize(42, 42))
        self._loot_pool_item_cache: dict[str, object | None] = {}
        self._loot_pool_icon_cache: dict[str, QPixmap] = {}
        self._loot_pool_preview_cache: dict[str, QPixmap] = {}
        self._loot_pool_item_path_by_id: dict[str, Path] = {}
        self._loot_pool_preview_tooltip = LootPreviewTooltip()
        layout.addWidget(self._loot_pool_list, 1)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(6)
        controls.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._loot_add_btn = QToolButton(panel)
        self._loot_add_btn.setObjectName("SecondaryButton")
        self._loot_add_btn.setProperty("compact", "true")
        self._loot_add_btn.setToolTip("Add Items")
        self._loot_add_btn.setIcon(QIcon(os.path.join(icon_dir, "add_items.png")))
        self._loot_add_btn.setIconSize(QSize(18, 18))
        self._loot_add_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._loot_add_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        # Keep icon action buttons square regardless of global button padding rules.
        self._loot_add_btn.setStyleSheet(
            "QToolButton {"
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);"
            "border: 1px solid #3b424b;"
            "border-radius: 6px;"
            "padding: 4px;"
            "margin: 0px;"
            "}"
            "QToolButton:hover {"
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);"
            "border-color: #58a6ff;"
            "}"
        )
        control_height = 42
        self._loot_add_btn.setFixedSize(control_height, control_height)
        self._loot_add_btn.clicked.connect(self._on_loot_add_items)
        controls.addWidget(self._loot_add_btn)
        text_button_width = 124

        self._loot_add_note_btn = QPushButton("Add Custom", panel)
        self._loot_add_note_btn.setObjectName("SecondaryButton")
        self._loot_add_note_btn.setProperty("compact", "true")
        self._loot_add_note_btn.setFixedHeight(control_height)
        self._loot_add_note_btn.setStyleSheet(
            "QPushButton {"
            "padding: 0px 12px;"
            "margin: 0px;"
            "}"
        )
        self._loot_add_note_btn.clicked.connect(self._on_loot_add_note)
        self._loot_add_note_btn.setFixedWidth(text_button_width)
        self._loot_add_note_btn.setMinimumWidth(text_button_width)
        self._loot_add_note_btn.setMaximumWidth(text_button_width)
        controls.addWidget(self._loot_add_note_btn)

        self._loot_remove_btn = QPushButton("Remove", panel)
        self._loot_remove_btn.setObjectName("DestructiveButton")
        self._loot_remove_btn.setProperty("compact", "true")
        self._loot_remove_btn.setFixedHeight(control_height)
        self._loot_remove_btn.setStyleSheet(
            "QPushButton {"
            "padding: 0px 12px;"
            "margin: 0px;"
            "}"
        )
        self._loot_remove_btn.clicked.connect(self._on_loot_remove_selected)
        self._loot_remove_btn.setFixedWidth(text_button_width)
        self._loot_remove_btn.setMinimumWidth(text_button_width)
        self._loot_remove_btn.setMaximumWidth(text_button_width)
        controls.addWidget(self._loot_remove_btn)

        controls.addStretch(1)

        self._loot_claim_btn = QPushButton("Claim", panel)
        self._loot_claim_btn.setObjectName("PrimaryButton")
        self._loot_claim_btn.setProperty("compact", "true")
        self._loot_claim_btn.setFixedHeight(control_height)
        self._loot_claim_btn.setStyleSheet(
            "QPushButton {"
            "padding: 0px 12px;"
            "margin: 0px;"
            "}"
        )
        self._loot_claim_btn.clicked.connect(self._on_loot_claim_selected)
        controls.addWidget(self._loot_claim_btn)
        layout.addLayout(controls)
        QTimer.singleShot(0, self._sync_loot_pool_control_sizes)
        return panel

    def _sync_loot_pool_control_sizes(self) -> None:
        add_btn = getattr(self, "_loot_add_btn", None)
        custom_btn = getattr(self, "_loot_add_note_btn", None)
        remove_btn = getattr(self, "_loot_remove_btn", None)
        claim_btn = getattr(self, "_loot_claim_btn", None)
        if add_btn is None or custom_btn is None or remove_btn is None:
            return

        target_height = max(
            42,
            int(custom_btn.sizeHint().height()),
            int(remove_btn.sizeHint().height()),
            int(add_btn.sizeHint().height()),
            int(custom_btn.height()),
            int(remove_btn.height()),
            int(add_btn.height()),
        )
        text_width = max(
            124,
            int(custom_btn.sizeHint().width()),
            int(remove_btn.sizeHint().width()),
            int(custom_btn.width()),
            int(remove_btn.width()),
        )

        add_btn.setFixedSize(target_height, target_height)
        for btn in (custom_btn, remove_btn):
            btn.setFixedHeight(target_height)
            btn.setMinimumHeight(target_height)
            btn.setMaximumHeight(target_height)
            btn.setFixedWidth(text_width)
            btn.setMinimumWidth(text_width)
            btn.setMaximumWidth(text_width)

        if claim_btn is not None:
            claim_btn.setFixedHeight(target_height)
            claim_btn.setMinimumHeight(target_height)
            claim_btn.setMaximumHeight(target_height)

    def _sanitize_loot_pool_entry(self, payload: dict) -> dict:
        entry_type = str(payload.get("type") or "item")
        entry_id = str(payload.get("entry_id") or uuid.uuid4().hex)
        title = str(payload.get("title") or "").strip()
        note = str(payload.get("note") or "").strip()
        item_id = str(payload.get("item_id") or "").strip()
        path = str(payload.get("path") or "").strip()
        item_document = payload.get("item_document")
        if not isinstance(item_document, dict):
            item_document = None
        elif str(item_document.get("format") or "").strip().lower() != ITEM_FILE_FORMAT:
            item_document = None
        elif not isinstance(item_document.get("payload"), dict):
            item_document = None
        payload_data = item_document.get("payload") if isinstance(item_document, dict) else {}
        if not item_id and isinstance(payload_data, dict):
            item_id = item_id_from_payload(payload_data)
        if not path and item_id:
            path = item_id
        if entry_type == "note":
            title = note or title or "Note"
        else:
            entry_type = "item"
            payload_title = str(payload_data.get("title") or "").strip() if isinstance(payload_data, dict) else ""
            payload_name = str(payload_data.get("name") or "").strip() if isinstance(payload_data, dict) else ""
            payload_normalized_name = (
                str(payload_data.get("normalized_item_name") or "").strip()
                if isinstance(payload_data, dict)
                else ""
            )
            title = _resolve_human_item_title(
                item_id,
                title=title or payload_title,
                name=payload_name,
                normalized_name=payload_normalized_name,
                fallback="Item",
            )
        entry = {
            "entry_id": entry_id,
            "type": entry_type,
            "item_id": item_id,
            "title": title,
            "path": path,
            "note": note if entry_type == "note" else "",
        }
        if entry_type == "item" and isinstance(item_document, dict):
            entry["item_document"] = item_document
        return entry

    def _loot_pool_state_signature(self) -> str:
        rows: list[dict] = []
        for entry in self._session_loot_pool:
            if not isinstance(entry, dict):
                continue
            row = {
                "entry_id": str(entry.get("entry_id") or ""),
                "type": str(entry.get("type") or ""),
                "item_id": str(entry.get("item_id") or ""),
                "title": str(entry.get("title") or ""),
                "note": str(entry.get("note") or ""),
                "path": str(entry.get("path") or ""),
            }
            rows.append(row)
        try:
            payload = json.dumps(
                rows,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except Exception:
            payload = str(rows)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _loot_pool_item_document_from_path(self, item_path: Path) -> dict | None:
        candidate = Path(item_path).expanduser()
        if not candidate.exists():
            return None
        document = load_item_document(candidate)
        if isinstance(document, dict):
            return document
        payload = load_item_payload(candidate)
        if not isinstance(payload, dict):
            return None
        icon_source = payload.get("icon_path") or payload.get("icon") or payload.get("preview_image")
        try:
            return build_item_document(payload, str(icon_source or ""))
        except Exception:
            return None

    def _loot_pool_materialized_items_dir(self) -> Path:
        session_key = str(
            self._active_online_runtime_cache_id() or self._collection_name or "local"
        )
        materialized_dir = online_loot_item_cache_dir(session_key)
        materialized_dir.mkdir(parents=True, exist_ok=True)
        return materialized_dir

    def _loot_pool_materialize_item_document(self, entry: dict) -> Path | None:
        item_document = entry.get("item_document")
        if not isinstance(item_document, dict):
            return None
        if str(item_document.get("format") or "").strip().lower() != ITEM_FILE_FORMAT:
            return None
        payload = item_document.get("payload")
        if not isinstance(payload, dict):
            return None
        try:
            digest = hashlib.sha256(
                json.dumps(
                    item_document,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()[:16]
        except Exception:
            return None
        item_hint = (
            str(entry.get("item_id") or "").strip()
            or str(payload.get("item_id") or "").strip()
            or str(payload.get("title") or "").strip()
            or "item"
        )
        safe_name = _sanitize_filename(Path(item_hint).stem, "item")
        target_path = self._loot_pool_materialized_items_dir() / (
            f"{safe_name}_{digest}{ITEM_FILE_EXTENSION}"
        )
        if not target_path.exists():
            try:
                write_item_document(target_path, item_document)
            except Exception:
                return None
        return target_path

    def _path_is_within(self, path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
            return True
        except Exception:
            return False

    def _confirm_claimed_item_overwrite(
        self,
        *,
        normalized_item_name: str,
        existing_item_id: str,
        incoming_item_id: str,
        item_title: str,
    ) -> bool:
        if _in_test_env():
            return True
        display_title = item_title or normalized_item_name or incoming_item_id or "Item"
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Claim And Replace")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            f"The claimed item '{display_title}' will replace your local item definition."
        )
        dialog.setInformativeText(
            "Replacing updates every matching local reference on this machine across all local characters.\n\n"
            f"Existing item id: {existing_item_id or 'unknown'}\n"
            f"Incoming item id: {incoming_item_id or 'unknown'}"
        )
        replace_btn = dialog.addButton("Claim and Replace", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() == replace_btn

    def _persist_claimed_item_to_default_library(
        self,
        entry: dict,
        resolved_path: Path | None,
    ) -> tuple[Path | None, str | None]:
        if resolved_path is None:
            return None, None
        source = Path(resolved_path).expanduser()
        if not source.exists():
            return None, None
        library_root = items_dir()
        try:
            library_root.mkdir(parents=True, exist_ok=True)
        except Exception:
            return source, None
        try:
            source_resolved = source.resolve()
        except Exception:
            source_resolved = source
        try:
            library_resolved = library_root.resolve()
        except Exception:
            library_resolved = library_root
        if self._path_is_within(source_resolved, library_resolved):
            return source_resolved, None

        item_document: dict | None = None
        raw_document = entry.get("item_document")
        if (
            isinstance(raw_document, dict)
            and str(raw_document.get("format") or "").strip().lower() == ITEM_FILE_FORMAT
            and isinstance(raw_document.get("payload"), dict)
        ):
            item_document = raw_document
        if item_document is None:
            item_document = self._loot_pool_item_document_from_path(source_resolved)

        persisted_path: Path | None = None
        payload_item_id = ""
        payload_normalized_name = ""
        if isinstance(item_document, dict):
            payload = item_document.get("payload")
            if isinstance(payload, dict):
                payload_item_id = item_id_from_payload(payload, fallback_path=source_resolved)
                payload_title = str(payload.get("title") or "").strip()
                payload_normalized_name = normalized_item_name_from_payload(
                    payload,
                    fallback_path=source_resolved,
                )
            else:
                payload_title = ""
            canonical_path: Path | None = None
            same_name_paths: list[Path] = []
            same_name_item_ids: list[str] = []
            if payload_normalized_name:
                for existing_path in list_item_file_paths(library_root):
                    existing_payload = load_item_payload(existing_path)
                    if not isinstance(existing_payload, dict):
                        continue
                    existing_normalized_name = normalized_item_name_from_payload(
                        existing_payload,
                        fallback_path=existing_path,
                    )
                    if existing_normalized_name != payload_normalized_name:
                        continue
                    same_name_paths.append(existing_path)
                    existing_item_id = item_id_from_payload(existing_payload, fallback_path=existing_path)
                    if existing_item_id:
                        same_name_item_ids.append(existing_item_id)
                    if canonical_path is None:
                        canonical_path = existing_path

            if canonical_path is not None:
                existing_payload = load_item_payload(canonical_path)
                existing_item_id = item_id_from_payload(existing_payload, fallback_path=canonical_path)
                existing_document = load_item_document(canonical_path)
                if existing_item_id == payload_item_id:
                    persisted_path = canonical_path
                elif (
                    existing_document is not None
                    and item_document_matches(existing_document, item_document)
                ):
                    persisted_path = canonical_path
                else:
                    if not self._confirm_claimed_item_overwrite(
                        normalized_item_name=payload_normalized_name,
                        existing_item_id=existing_item_id,
                        incoming_item_id=payload_item_id,
                        item_title=payload_title,
                    ):
                        return None, "Claim cancelled. Local item replacement was not confirmed."
                    try:
                        write_item_document(canonical_path, item_document)
                        persisted_path = canonical_path
                    except Exception:
                        persisted_path = None
                    if persisted_path is not None:
                        try:
                            from player_sheets import replace_item_references
                        except Exception:
                            replace_item_references = None  # type: ignore[assignment]
                        if replace_item_references is not None and same_name_item_ids and payload_item_id:
                            replace_item_references(same_name_item_ids, payload_item_id)
                        for duplicate_path in same_name_paths:
                            if duplicate_path == canonical_path:
                                continue
                            try:
                                if duplicate_path.exists():
                                    duplicate_path.unlink()
                            except Exception:
                                logger.exception(
                                    "Failed to prune replaced item definition: %s",
                                    duplicate_path,
                                )
            try:
                digest = hashlib.sha256(
                    json.dumps(
                        item_document,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()[:16]
            except Exception:
                digest = ""
            item_hint = (
                str(entry.get("item_id") or "").strip()
                or payload_item_id
                or payload_title
                or source_resolved.stem
                or "item"
            )
            safe_name = _sanitize_filename(Path(item_hint).stem, "item")
            filename = (
                f"{safe_name}_{digest}{ITEM_FILE_EXTENSION}"
                if digest
                else f"{safe_name}{ITEM_FILE_EXTENSION}"
            )
            if persisted_path is None:
                target_path = library_root / filename
                if target_path.exists():
                    existing_document = load_item_document(target_path)
                    if not item_document_matches(existing_document, item_document):
                        try:
                            write_item_document(target_path, item_document)
                        except Exception:
                            target_path = None
                else:
                    try:
                        write_item_document(target_path, item_document)
                    except Exception:
                        target_path = None
                persisted_path = target_path

        if persisted_path is None:
            try:
                raw = source_resolved.read_bytes()
            except Exception:
                return source_resolved, None
            if not raw:
                return source_resolved, None
            digest = hashlib.sha256(raw).hexdigest()[:16]
            extension = source_resolved.suffix or ITEM_FILE_EXTENSION
            item_hint = (
                str(entry.get("item_id") or "").strip()
                or str(entry.get("title") or "").strip()
                or source_resolved.stem
                or "item"
            )
            safe_name = _sanitize_filename(Path(item_hint).stem, "item")
            target_path = library_root / f"{safe_name}_{digest}{extension}"
            if not target_path.exists():
                try:
                    target_path.write_bytes(raw)
                except Exception:
                    return source_resolved, None
            persisted_path = target_path

        if persisted_path is None or not persisted_path.exists():
            return source_resolved, None
        try:
            persisted_resolved = persisted_path.resolve()
        except Exception:
            persisted_resolved = persisted_path
        entry_item_id = str(entry.get("item_id") or "").strip()
        if entry_item_id:
            self._loot_pool_item_path_by_id[entry_item_id] = persisted_resolved
        if payload_item_id:
            self._loot_pool_item_path_by_id[payload_item_id] = persisted_resolved
        if payload_normalized_name:
            self._loot_pool_item_path_by_id[payload_normalized_name] = persisted_resolved
        self._loot_pool_item_path_by_id[str(persisted_resolved)] = persisted_resolved
        return persisted_resolved, None

    def _set_loot_pool_entries(self, entries: list[dict], *, broadcast: bool = False) -> None:
        self._loot_claim_reservations.clear()
        self._loot_claim_entry_reservations.clear()
        self._session_loot_pool = [
            self._sanitize_loot_pool_entry(entry)
            for entry in entries
            if isinstance(entry, dict)
        ]
        self._refresh_loot_pool_list()
        if broadcast and self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _refresh_loot_pool_list(self) -> None:
        if not hasattr(self, "_loot_pool_list"):
            return
        signature = self._loot_pool_state_signature()
        signature_changed = signature != self._loot_pool_signature
        if signature_changed:
            self._loot_pool_signature = signature
            if self._online_mode == ONLINE_MODE_PLAYER and bool(self._session_loot_pool):
                panel_visible = bool(
                    hasattr(self, "_loot_pool_panel")
                    and self._loot_pool_panel is not None
                    and self._loot_pool_panel.isVisible()
                )
                if not panel_visible:
                    self._loot_pool_has_unseen_updates = True
            elif not self._session_loot_pool:
                self._loot_pool_has_unseen_updates = False
        self._loot_pool_list.blockSignals(True)
        self._loot_pool_list.clear()
        ordered_entries = [
            entry
            for entry in self._session_loot_pool
            if str(entry.get("type") or "item") != "note"
        ] + [
            entry
            for entry in self._session_loot_pool
            if str(entry.get("type") or "item") == "note"
        ]
        for entry in ordered_entries:
            is_note = str(entry.get("type") or "item") == "note"
            row_title = str(entry.get("title") or "Entry").strip() or "Entry"
            row = QListWidgetItem(row_title)
            row.setData(Qt.ItemDataRole.UserRole, str(entry.get("entry_id") or ""))
            row.setData(Qt.ItemDataRole.UserRole + 1, dict(entry))
            if is_note:
                row.setForeground(QColor("#9ca3af"))
            else:
                icon = self._loot_pool_icon_for_entry(entry)
                if icon is not None and not icon.isNull():
                    row.setIcon(QIcon(icon))
            row.setSizeHint(QSize(0, 48))
            self._loot_pool_list.addItem(row)
        self._loot_pool_list.blockSignals(False)
        self._hide_loot_pool_preview()
        self._update_loot_pool_badge()

    def _loot_pool_item_cache_key(self, entry: dict) -> str:
        path = str(entry.get("path") or "").strip()
        item_id = str(entry.get("item_id") or "").strip()
        entry_id = str(entry.get("entry_id") or "").strip()
        document = entry.get("item_document")
        doc_sig = ""
        if isinstance(document, dict):
            try:
                doc_sig = hashlib.sha256(
                    json.dumps(
                        document,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()[:12]
            except Exception:
                doc_sig = "doc"
        return f"{path}|{item_id}|{entry_id}|{doc_sig}"

    def _loot_pool_resolve_item_path(self, entry: dict) -> Path | None:
        path = str(entry.get("path") or "").strip()
        if path:
            candidate = Path(path).expanduser()
            if candidate.exists():
                return candidate
        item_id = str(entry.get("item_id") or "").strip()
        if not item_id:
            return None
        # Canonical item ids in DMT are often absolute item-file paths.
        item_id_path = Path(item_id).expanduser()
        if item_id_path.exists():
            return item_id_path
        cached = self._loot_pool_item_path_by_id.get(item_id)
        if cached is not None and cached.exists():
            return cached
        materialized = self._loot_pool_materialize_item_document(entry)
        if materialized is not None and materialized.exists():
            if item_id:
                self._loot_pool_item_path_by_id[item_id] = materialized
            self._loot_pool_item_path_by_id.setdefault(
                str(materialized.resolve()),
                materialized,
            )
            return materialized
        root = items_dir()
        if not root.exists():
            return None
        for item_path in list_item_file_paths(root):
            payload = load_item_payload(item_path)
            if not isinstance(payload, dict):
                continue
            candidate_id = item_id_from_payload(payload, fallback_path=item_path)
            if candidate_id:
                self._loot_pool_item_path_by_id.setdefault(candidate_id, item_path)
            self._loot_pool_item_path_by_id.setdefault(str(item_path.resolve()), item_path)
        resolved = self._loot_pool_item_path_by_id.get(item_id)
        if resolved is None or not resolved.exists():
            return None
        return resolved

    def _loot_pool_item_for_entry(self, entry: dict) -> object | None:
        if str(entry.get("type") or "item") == "note":
            return None
        key = self._loot_pool_item_cache_key(entry)
        if key in self._loot_pool_item_cache:
            return self._loot_pool_item_cache[key]
        item = None
        path = self._loot_pool_resolve_item_path(entry)
        if path is not None:
            try:
                from player_sheets import _loot_item_from_path

                item = _loot_item_from_path(path)
            except Exception:
                item = None
        self._loot_pool_item_cache[key] = item
        return item

    def _fallback_loot_icon_pixmap(self, *, size: int = 28, icon_path: str = "") -> QPixmap:
        icon_size = max(16, int(size))
        pixmap = QPixmap(icon_size, icon_size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0.5, 0.5, float(icon_size - 1), float(icon_size - 1))
        painter.setPen(QPen(QColor("#4b5563"), 1))
        painter.setBrush(QColor("#111827"))
        painter.drawRoundedRect(rect, 5.0, 5.0)
        icon_pixmap = QPixmap(icon_path) if icon_path else QPixmap()
        if isinstance(icon_pixmap, QPixmap) and not icon_pixmap.isNull():
            inner_size = max(12, icon_size - 8)
            scaled = icon_pixmap.scaled(
                inner_size,
                inner_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (icon_size - scaled.width()) // 2,
                (icon_size - scaled.height()) // 2,
                scaled,
            )
        else:
            painter.setPen(QColor("#e5e7eb"))
            font = QFont(painter.font())
            font.setBold(True)
            font.setPointSize(max(8, int(icon_size * 0.45)))
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "?")
        painter.end()
        return pixmap

    def _loot_pool_payload_for_entry(self, entry: dict) -> dict:
        path = self._loot_pool_resolve_item_path(entry)
        if path is not None:
            payload = load_item_payload(path)
            if isinstance(payload, dict):
                return payload
        item_document = entry.get("item_document")
        payload = item_document.get("payload") if isinstance(item_document, dict) else {}
        if isinstance(payload, dict):
            return dict(payload)
        return {}

    def _fallback_loot_preview_pixmap(self, entry: dict) -> QPixmap:
        width = 322
        height = 156
        dpr = max(1.0, float(self.devicePixelRatioF()))
        pixmap = QPixmap(int(round(width * dpr)), int(round(height * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        payload = self._loot_pool_payload_for_entry(entry)
        title = _resolve_human_item_title(
            entry.get("item_id"),
            title=payload.get("title") or entry.get("title"),
            name=payload.get("name") if isinstance(payload, dict) else "",
            normalized_name=payload.get("normalized_item_name") if isinstance(payload, dict) else "",
            fallback="Unknown Item",
        )
        rarity_key = str(payload.get("rarity") or "").strip().lower()
        accent = {
            "common": QColor("#9ca3af"),
            "uncommon": QColor("#22c55e"),
            "rare": QColor("#3b82f6"),
            "epic": QColor("#a855f7"),
            "legendary": QColor("#f59e0b"),
            "artifact": QColor("#14b8a6"),
        }.get(rarity_key, QColor("#60a5fa"))
        subtitle_parts: list[str] = []
        if rarity_key:
            subtitle_parts.append(rarity_key.title())
        level_value = payload.get("level", payload.get("required_level"))
        try:
            level = max(1, int(level_value))
        except (TypeError, ValueError):
            level = 0
        if level > 0:
            subtitle_parts.append(f"Level {level}")
        raw_category = payload.get("category", payload.get("categories"))
        if isinstance(raw_category, (list, tuple, set)):
            category_text = ", ".join(
                str(part or "").strip().replace("_", " ").title()
                for part in raw_category
                if str(part or "").strip()
            )
        else:
            category_text = str(raw_category or "").strip().replace("_", " ").title()
        if category_text:
            subtitle_parts.append(category_text)
        subtitle = " | ".join(part for part in subtitle_parts if part)
        description = " ".join(
            str(payload.get("description") or payload.get("effect") or "").split()
        )
        item_id_text = str(entry.get("item_id") or "").strip()
        if _looks_generated_item_label(item_id_text):
            item_id_text = ""
        icon_path = str(payload.get("icon_path") or payload.get("icon") or "").strip()
        icon_pixmap = QPixmap(icon_path) if icon_path else QPixmap()
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        outer = QRectF(0.5, 0.5, float(width - 1), float(height - 1))
        painter.setPen(QPen(QColor("#374151"), 1))
        painter.setBrush(QColor("#0f172a"))
        painter.drawRoundedRect(outer, 10.0, 10.0)
        painter.fillRect(QRectF(12.0, 12.0, 4.0, float(height - 24)), accent)

        icon_rect = QRectF(20.0, 22.0, 72.0, 72.0)
        painter.setPen(QPen(QColor("#475569"), 1))
        painter.setBrush(QColor("#111827"))
        painter.drawRoundedRect(icon_rect, 8.0, 8.0)
        if isinstance(icon_pixmap, QPixmap) and not icon_pixmap.isNull():
            scaled = icon_pixmap.scaled(
                int(icon_rect.width()) - 12,
                int(icon_rect.height()) - 12,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            draw_x = int(round(icon_rect.left() + (icon_rect.width() - scaled.width()) / 2.0))
            draw_y = int(round(icon_rect.top() + (icon_rect.height() - scaled.height()) / 2.0))
            painter.drawPixmap(draw_x, draw_y, scaled)
        else:
            fallback_icon = self._fallback_loot_icon_pixmap(size=int(icon_rect.width()) - 12)
            draw_x = int(round(icon_rect.left() + (icon_rect.width() - fallback_icon.width()) / 2.0))
            draw_y = int(round(icon_rect.top() + (icon_rect.height() - fallback_icon.height()) / 2.0))
            painter.drawPixmap(draw_x, draw_y, fallback_icon)

        text_left = 108.0
        text_width = float(width) - text_left - 18.0
        painter.setPen(QColor("#e5e7eb"))
        title_font = QFont(painter.font())
        title_font.setBold(True)
        title_font.setPointSize(12)
        painter.setFont(title_font)
        title_metrics = QFontMetrics(title_font)
        title_rect = QRectF(text_left, 18.0, text_width, 28.0)
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_metrics.elidedText(title, Qt.TextElideMode.ElideRight, int(title_rect.width())),
        )
        if subtitle:
            painter.setPen(QColor("#93c5fd"))
            subtitle_font = QFont(painter.font())
            subtitle_font.setPointSize(9)
            painter.setFont(subtitle_font)
            subtitle_metrics = QFontMetrics(subtitle_font)
            subtitle_rect = QRectF(text_left, 48.0, text_width, 18.0)
            painter.drawText(
                subtitle_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                subtitle_metrics.elidedText(
                    subtitle,
                    Qt.TextElideMode.ElideRight,
                    int(subtitle_rect.width()),
                ),
            )
        if description:
            painter.setPen(QColor("#cbd5e1"))
            body_font = QFont(painter.font())
            body_font.setPointSize(9)
            painter.setFont(body_font)
            description_rect = QRectF(text_left, 72.0, text_width, 44.0)
            painter.drawText(
                description_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                description,
            )
        if item_id_text:
            painter.setPen(QColor("#64748b"))
            id_font = QFont(painter.font())
            id_font.setPointSize(8)
            painter.setFont(id_font)
            id_metrics = QFontMetrics(id_font)
            id_rect = QRectF(20.0, 126.0, float(width - 40), 16.0)
            painter.drawText(
                id_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                id_metrics.elidedText(
                    item_id_text,
                    Qt.TextElideMode.ElideMiddle,
                    int(id_rect.width()),
                ),
            )
        painter.end()
        return pixmap

    def _loot_pool_icon_for_entry(self, entry: dict) -> QPixmap | None:
        key = self._loot_pool_item_cache_key(entry)
        cached = self._loot_pool_icon_cache.get(key)
        if cached is not None:
            return cached
        try:
            from player_sheets import _inventory_icon_pixmap, _missing_inventory_icon_pixmap
        except Exception:
            fallback = self._fallback_loot_icon_pixmap()
            self._loot_pool_icon_cache[key] = fallback
            return fallback
        item = self._loot_pool_item_for_entry(entry)
        if item is not None:
            pixmap = _inventory_icon_pixmap(item)
        else:
            payload = self._loot_pool_payload_for_entry(entry)
            icon_path = str(payload.get("icon_path") or payload.get("icon") or "").strip()
            pixmap = (
                self._fallback_loot_icon_pixmap(icon_path=icon_path)
                if icon_path
                else _missing_inventory_icon_pixmap()
            )
        if not isinstance(pixmap, QPixmap) or pixmap.isNull():
            pixmap = self._fallback_loot_icon_pixmap()
        self._loot_pool_icon_cache[key] = pixmap
        return pixmap

    def _loot_pool_preview_for_entry(self, entry: dict) -> QPixmap | None:
        item = self._loot_pool_item_for_entry(entry)
        dpr = max(1.0, float(self.devicePixelRatioF()))
        key = f"{self._loot_pool_item_cache_key(entry)}|{int(round(dpr * 100))}"
        cached = self._loot_pool_preview_cache.get(key)
        if cached is not None:
            return cached
        pixmap: QPixmap | None = None
        if item is not None:
            try:
                from player_sheets import _render_item_preview_pixmap
            except Exception:
                _render_item_preview_pixmap = None  # type: ignore[assignment]
            if _render_item_preview_pixmap is not None:
                pixmap = _render_item_preview_pixmap(
                    item,
                    max_width=322,
                    max_height=460,
                    dpr=dpr,
                )
        if pixmap is None or pixmap.isNull():
            pixmap = self._fallback_loot_preview_pixmap(entry)
        self._loot_pool_preview_cache[key] = pixmap
        return pixmap

    def _show_loot_pool_preview_for_item(self, row: QListWidgetItem, global_pos: QPoint) -> None:
        if not hasattr(self, "_loot_pool_preview_tooltip"):
            return
        entry = row.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(entry, dict):
            self._hide_loot_pool_preview()
            return
        if str(entry.get("type") or "item") == "note":
            self._hide_loot_pool_preview()
            return
        pixmap = self._loot_pool_preview_for_entry(entry)
        if pixmap is None or pixmap.isNull():
            self._hide_loot_pool_preview()
            return
        self._loot_pool_preview_tooltip.show_preview(pixmap, global_pos)

    def _hide_loot_pool_preview(self) -> None:
        tooltip = getattr(self, "_loot_pool_preview_tooltip", None)
        if tooltip is not None:
            tooltip.hide_preview()

    def _install_loot_preview_tracking(self, list_widget: QListWidget) -> None:
        viewport = list_widget.viewport()
        list_widget.setMouseTracking(True)
        viewport.setMouseTracking(True)
        existing_filter = getattr(list_widget, "_loot_preview_filter", None)
        if isinstance(existing_filter, QObject):
            try:
                viewport.removeEventFilter(existing_filter)
            except RuntimeError:
                pass
        preview_filter = _LootPreviewListEventFilter(
            list_widget,
            show_preview=self._show_loot_pool_preview_for_item,
            hide_preview=self._hide_loot_pool_preview,
        )
        viewport.installEventFilter(preview_filter)
        setattr(list_widget, "_loot_preview_filter", preview_filter)

    def _update_loot_pool_badge(self) -> None:
        has_entries = bool(self._session_loot_pool)
        if hasattr(self, "_loot_pool_badge"):
            show_floating_badge = has_entries
            if self._online_mode == ONLINE_MODE_PLAYER:
                show_floating_badge = bool(self._loot_pool_has_unseen_updates)
            self._loot_pool_badge.setVisible(show_floating_badge)
        if hasattr(self, "tool_panel") and hasattr(self.tool_panel, "btn_loot_panel"):
            count = len(self._session_loot_pool)
            if count > 0:
                self.tool_panel.btn_loot_panel.setToolTip(f"Show Loot Pool ({count} entries)")
            else:
                self.tool_panel.btn_loot_panel.setToolTip("Show Loot Pool")
            if hasattr(self.tool_panel, "set_loot_pool_badge_visible"):
                show_tool_badge = (
                    has_entries
                    and self._online_mode == ONLINE_MODE_PLAYER
                    and bool(self._loot_pool_has_unseen_updates)
                )
                self.tool_panel.set_loot_pool_badge_visible(show_tool_badge)

    def _toggle_loot_pool_panel(self) -> None:
        if self._online_mode not in (ONLINE_MODE_DM_HOST, ONLINE_MODE_PLAYER):
            return
        showing = self._loot_pool_panel.isHidden()
        if showing:
            self._loot_pool_has_unseen_updates = False
            self._update_loot_pool_badge()
        target = self._target_loot_pool_geometry()
        self._animate_center_panel(
            self._loot_pool_panel,
            show=showing,
            target_rect=target,
            attr_name="_loot_pool_panel_anim",
            duration_ms=170,
        )
        if showing:
            self._sync_loot_pool_control_sizes()
        else:
            self._hide_loot_pool_preview()
        self._position_floating_overlays()

    def _selected_loot_pool_ids(self) -> list[str]:
        if not hasattr(self, "_loot_pool_list"):
            return []
        selected = []
        for item in self._loot_pool_list.selectedItems():
            selected_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if selected_id:
                selected.append(selected_id)
        return selected

    def _on_loot_add_items(self) -> None:
        if self._online_mode == ONLINE_MODE_PLAYER:
            self._on_loot_add_from_player_inventory()
            return
        source = self._choose_loot_add_source()
        if source == "library":
            self._on_loot_add_from_library()
        elif source == "tables":
            self._on_loot_import_saved_results()
        elif source == "inventory":
            self._on_loot_add_from_player_inventory()

    def _choose_loot_add_source(self) -> str | None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Add To Loot Pool")
        dialog.setModal(True)
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(
            "Choose what you want to add to the session loot pool:",
            dialog,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        choice: dict[str, str | None] = {"value": None}

        library_btn = QPushButton("Item Library", dialog)
        library_btn.setObjectName("SecondaryButton")
        library_btn.setMinimumHeight(36)
        library_btn.clicked.connect(lambda: (choice.update(value="library"), dialog.accept()))
        layout.addWidget(library_btn)

        inventory_btn = QPushButton("Player Backpack + Equipment", dialog)
        inventory_btn.setObjectName("SecondaryButton")
        inventory_btn.setMinimumHeight(36)
        inventory_btn.clicked.connect(lambda: (choice.update(value="inventory"), dialog.accept()))
        layout.addWidget(inventory_btn)

        tables_btn = QPushButton("Loot Tables", dialog)
        tables_btn.setObjectName("SecondaryButton")
        tables_btn.setMinimumHeight(36)
        tables_btn.clicked.connect(lambda: (choice.update(value="tables"), dialog.accept()))
        layout.addWidget(tables_btn)

        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected = str(choice.get("value") or "").strip()
        return selected or None

    def _inventory_loot_rows_for_sheet(self, sheet_id: str) -> list[dict]:
        clean_sheet_id = str(sheet_id or "").strip()
        if not clean_sheet_id:
            return []
        try:
            from player_sheets import (
                inventory_payload_for_sheet_id,
                EQUIPMENT_SLOT_LABELS,
                loot_item_path_for_id,
            )
        except Exception:
            inventory_payload_for_sheet_id = None  # type: ignore[assignment]
            EQUIPMENT_SLOT_LABELS = {}  # type: ignore[assignment]
            loot_item_path_for_id = None  # type: ignore[assignment]
        if inventory_payload_for_sheet_id is None:
            return []
        inventory_payload = normalize_inventory_payload(inventory_payload_for_sheet_id(clean_sheet_id) or {})
        if not isinstance(inventory_payload, dict):
            return []
        inventory_rows = inventory_payload.get("inventory")
        if not isinstance(inventory_rows, list):
            return []

        rows: list[dict] = []
        for index, value in enumerate(inventory_rows):
            item_id = _inventory_entry_item_id(value)
            if not item_id:
                continue
            quantity = _inventory_entry_quantity(value)
            title = _resolve_human_item_title(item_id, fallback="Unknown Item")
            resolved_path = loot_item_path_for_id(item_id) if loot_item_path_for_id is not None else None
            path = str(resolved_path) if resolved_path is not None else str(item_id)
            item_document = None
            candidate_path = resolved_path or Path(item_id).expanduser()
            if candidate_path.exists():
                item_document = self._loot_pool_item_document_from_path(candidate_path)
                payload = load_item_payload(candidate_path)
                if isinstance(payload, dict):
                    title = _resolve_human_item_title(
                        item_id,
                        title=payload.get("title"),
                        name=payload.get("name"),
                        normalized_name=payload.get("normalized_item_name"),
                        fallback=title,
                    )
            for unit_index in range(quantity):
                rows.append(
                    {
                        "source_type": "backpack",
                        "source_index": int(index),
                        "source_unit_index": int(unit_index),
                        "item_id": item_id,
                        "title": title,
                        "path": path,
                        "item_document": item_document,
                    }
                )
        equipment_rows = inventory_payload.get("equipment")
        if isinstance(equipment_rows, dict):
            for slot_id_raw, value in equipment_rows.items():
                slot_id = str(slot_id_raw or "").strip()
                item_id = _inventory_entry_item_id(value)
                if not slot_id or not item_id:
                    continue
                title = _resolve_human_item_title(item_id, fallback="Unknown Item")
                resolved_path = loot_item_path_for_id(item_id) if loot_item_path_for_id is not None else None
                path = str(resolved_path) if resolved_path is not None else str(item_id)
                item_document = None
                candidate_path = resolved_path or Path(item_id).expanduser()
                if candidate_path.exists():
                    item_document = self._loot_pool_item_document_from_path(candidate_path)
                    payload = load_item_payload(candidate_path)
                    if isinstance(payload, dict):
                        title = _resolve_human_item_title(
                            item_id,
                            title=payload.get("title"),
                            name=payload.get("name"),
                            normalized_name=payload.get("normalized_item_name"),
                            fallback=title,
                        )
                slot_label = str(EQUIPMENT_SLOT_LABELS.get(slot_id) or "").strip()
                if not slot_label:
                    slot_label = slot_id.replace("_", " ").title()
                rows.append(
                    {
                        "source_type": "equipment",
                        "source_slot": slot_id,
                        "source_label": f"Equipment: {slot_label}",
                        "item_id": item_id,
                        "title": title,
                        "path": path,
                        "item_document": item_document,
                    }
                )

        total_by_item: dict[str, int] = {}
        for row in rows:
            key = str(row.get("item_id") or "")
            total_by_item[key] = int(total_by_item.get(key, 0)) + 1
        seen_by_item: dict[str, int] = {}
        for row in rows:
            key = str(row.get("item_id") or "")
            seen = int(seen_by_item.get(key, 0)) + 1
            seen_by_item[key] = seen
            label = str(row.get("title") or key or "Item").strip() or "Item"
            total = int(total_by_item.get(key, 0))
            if total > 1:
                label = f"{label} ({seen}/{total})"
            source_type = str(row.get("source_type") or "backpack").strip().lower()
            if source_type == "equipment":
                source_hint = str(row.get("source_label") or "Equipment")
                label = f"{label} - {source_hint}"
            else:
                label = f"{label} - Backpack"
            row["label"] = label
        return rows

    def _choose_inventory_rows_for_loot(
        self,
        *,
        sheet_name: str,
        rows: list[dict],
    ) -> list[dict] | None:
        if not rows:
            return None
        dialog = QDialog(self)
        dialog.setWindowTitle("Add Inventory Items")
        dialog.setModal(True)
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(
            f"Select one or more backpack/equipment items from {sheet_name} to add to the loot pool:",
            dialog,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        list_widget = QListWidget(dialog)
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for row in rows:
            text = str(row.get("label") or row.get("title") or row.get("item_id") or "Item")
            item = QListWidgetItem(text)
            icon_entry = {
                "type": "item",
                "item_id": str(row.get("item_id") or ""),
                "title": str(row.get("title") or ""),
                "path": str(row.get("path") or ""),
                "item_document": row.get("item_document"),
            }
            icon_pixmap = self._loot_pool_icon_for_entry(icon_entry)
            if isinstance(icon_pixmap, QPixmap) and not icon_pixmap.isNull():
                item.setIcon(QIcon(icon_pixmap))
            item.setData(Qt.ItemDataRole.UserRole, dict(row))
            list_widget.addItem(item)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
        layout.addWidget(list_widget, 1)

        controls = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        ok_button = controls.button(QDialogButtonBox.StandardButton.Ok)
        if ok_button is not None:
            ok_button.setText("Add Selected")
            ok_button.setEnabled(False)
        controls.accepted.connect(dialog.accept)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)

        def _sync_ok_state() -> None:
            if ok_button is None:
                return
            ok_button.setEnabled(bool(list_widget.selectedItems()))

        list_widget.itemSelectionChanged.connect(_sync_ok_state)
        _sync_ok_state()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        selected_rows: list[dict] = []
        for item in list_widget.selectedItems():
            payload = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(payload, dict):
                selected_rows.append(dict(payload))
        return selected_rows

    def _on_loot_add_from_player_inventory(self) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER or self._client_controller is None:
            QMessageBox.information(
                self,
                "Loot Pool",
                "Inventory/equipment-to-loot transfers are available in online player sessions.",
            )
            return
        selected_sheet = self._choose_sheet_for_claim()
        if selected_sheet is None:
            return
        sheet_id, sheet_name = selected_sheet
        rows = self._inventory_loot_rows_for_sheet(sheet_id)
        if not rows:
            QMessageBox.information(
                self,
                "Loot Pool",
                f"{sheet_name} has no backpack/equipment items to add.",
            )
            return
        selected_rows = self._choose_inventory_rows_for_loot(
            sheet_name=sheet_name,
            rows=rows,
        )
        if not selected_rows:
            return
        transfer_items: list[dict] = []
        for row in selected_rows:
            item_id = str(row.get("item_id") or "").strip()
            if not item_id:
                continue
            transfer_payload = {
                "item_id": item_id,
                "title": str(row.get("title") or item_id or "Item"),
                "path": str(row.get("path") or item_id),
                "source": str(row.get("source_type") or "backpack"),
            }
            if transfer_payload["source"] == "equipment":
                transfer_payload["source_slot"] = str(row.get("source_slot") or "").strip()
            elif isinstance(row.get("source_index"), int):
                transfer_payload["source_index"] = int(row.get("source_index"))
            item_document = row.get("item_document")
            if isinstance(item_document, dict):
                transfer_payload["item_document"] = dict(item_document)
            transfer_items.append(transfer_payload)
        if not transfer_items:
            return
        request_id = self._dispatch_player_command_with_request_id(
            "add_loot_from_inventory",
            {
                "sheet_id": sheet_id,
                "items": transfer_items,
                "dungeon_id": str(self._active_dungeon_id or ""),
            },
            unavailable_title="Loot Pool",
            unavailable_message="You are currently disconnected. Please wait for reconnect.",
        )
        if request_id:
            self._pending_add_loot_from_inventory_requests[request_id] = {
                "sheet_id": sheet_id,
                "sheet_name": sheet_name,
            }

    def _on_loot_add_from_library(self) -> None:
        try:
            from player_sheets import (
                InventoryItemPickerDialog,
                _inventory_icon_pixmap,
                _load_loot_item_library,
                _render_item_preview_pixmap,
            )
        except Exception:
            InventoryItemPickerDialog = None  # type: ignore[assignment]
            _inventory_icon_pixmap = None  # type: ignore[assignment]
            _load_loot_item_library = None  # type: ignore[assignment]
            _render_item_preview_pixmap = None  # type: ignore[assignment]

        if InventoryItemPickerDialog is not None and _load_loot_item_library is not None:
            items, item_by_id = _load_loot_item_library()
            if not items:
                QMessageBox.information(self, "Loot Pool", "No item library entries found.")
                return
            dialog = InventoryItemPickerDialog(
                items,
                lambda item: _inventory_icon_pixmap(item),  # type: ignore[misc]
                lambda item, max_width=322, max_height=None, dpr=1.0: _render_item_preview_pixmap(  # type: ignore[misc]
                    item,
                    max_width=max_width,
                    max_height=max_height,
                    dpr=dpr,
                ),
                self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected_item_id = str(getattr(dialog, "selected_item_id", "") or "").strip()
            if not selected_item_id:
                return
            selected_item = item_by_id.get(selected_item_id)
            if selected_item is None:
                return
            item_id = str(getattr(selected_item, "item_id", "") or selected_item_id).strip()
            path = str(getattr(selected_item, "path", "") or "").strip()
            title = str(getattr(selected_item, "title", "") or "").strip() or "Item"
            item_document = None
            if path:
                item_document = self._loot_pool_item_document_from_path(Path(path))
            self._session_loot_pool.append(
                self._sanitize_loot_pool_entry(
                    {
                        "entry_id": uuid.uuid4().hex,
                        "type": "item",
                        "item_id": item_id,
                        "title": title,
                        "path": path,
                        "item_document": item_document,
                    }
                )
            )
        else:
            library: list[tuple[str, str, str]] = []
            root = items_dir()
            if root.exists():
                for item_path in list_item_file_paths(root):
                    data = load_item_payload(item_path)
                    if not isinstance(data, dict):
                        continue
                    title = str(data.get("title") or data.get("name") or item_path.stem).strip()
                    item_id = item_id_from_payload(data, fallback_path=item_path)
                    library.append((title, item_id, str(item_path)))
            if not library:
                QMessageBox.information(self, "Loot Pool", "No item library entries found.")
                return
            labels = [f"{title} ({Path(path).stem})" for title, _item_id, path in library]
            selected, ok = QInputDialog.getItem(self, "Add Loot Item", "Item:", labels, 0, False)
            if not ok or not selected:
                return
            for index, (title, item_id, path) in enumerate(library):
                if labels[index] != selected:
                    continue
                item_document = None
                if path:
                    item_document = self._loot_pool_item_document_from_path(Path(path))
                self._session_loot_pool.append(
                    self._sanitize_loot_pool_entry(
                        {
                            "entry_id": uuid.uuid4().hex,
                            "type": "item",
                            "item_id": item_id,
                            "title": title,
                            "path": path,
                            "item_document": item_document,
                        }
                    )
                )
                break
        self._refresh_loot_pool_list()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _on_loot_import_saved_results(self) -> None:
        results_dir = Path(default_dnd_save_dir()) / "loot" / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Loot Tables",
            str(results_dir),
            f"DMT Loot Tables (*{LOOT_RESULT_EXTENSION})",
        )
        if not filenames:
            return
        for filename in filenames:
            try:
                payload = json.loads(Path(filename).read_text(encoding="utf-8"))
            except Exception as exc:
                QMessageBox.critical(self, "Import Failed", str(exc))
                continue
            rows = payload.get("results") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                QMessageBox.warning(self, "Import Failed", "Selected file has no loot table results payload.")
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                row_path = str(row.get("path") or "")
                item_document = None
                if row_path:
                    item_document = self._loot_pool_item_document_from_path(Path(row_path))
                self._session_loot_pool.append(
                    self._sanitize_loot_pool_entry(
                        {
                            "entry_id": uuid.uuid4().hex,
                            "type": "item",
                            "item_id": str(row.get("item_id") or ""),
                            "title": str(row.get("title") or row.get("item_id") or "Item"),
                            "path": row_path,
                            "item_document": item_document,
                        }
                    )
                )
        self._refresh_loot_pool_list()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _on_loot_add_note(self) -> None:
        note, ok = QInputDialog.getText(self, "Add Custom", "Custom entry:")
        if not ok:
            return
        clean_note = str(note or "").strip()
        if not clean_note:
            return
        self._session_loot_pool.append(
            self._sanitize_loot_pool_entry(
                {
                    "entry_id": uuid.uuid4().hex,
                    "type": "note",
                    "title": clean_note,
                    "note": clean_note,
                }
            )
        )
        self._refresh_loot_pool_list()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _on_loot_remove_selected(self) -> None:
        selected = set(self._selected_loot_pool_ids())
        if not selected:
            return
        self._session_loot_pool = [
            entry for entry in self._session_loot_pool if str(entry.get("entry_id") or "") not in selected
        ]
        self._drop_invalid_loot_claim_reservations()
        self._refresh_loot_pool_list()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _linked_sheet_options_for_local_player(self) -> list[tuple[str, str]]:
        options: dict[str, str] = {}
        local_id = str(self._local_player_id or "")
        for item in self.canvas.scene().items():
            if not isinstance(item, EntityItem):
                continue
            if self._online_mode == ONLINE_MODE_PLAYER and local_id:
                if str(item.data(ROLE_OWNER_PLAYER_ID) or "") != local_id:
                    continue
            sheet_id = str(item.data(ROLE_LINKED_SHEET_ID) or "").strip()
            if not sheet_id:
                continue
            name = str(item.data(ROLE_LINKED_SHEET_NAME) or sheet_id).strip() or sheet_id
            options[sheet_id] = name
        return sorted(options.items(), key=lambda entry: entry[1].lower())

    def _choose_sheet_for_claim(self) -> tuple[str, str] | None:
        options = self._linked_sheet_options_for_local_player()
        if not options:
            QMessageBox.information(
                self,
                "Claim",
                "No linked character available. Link a character to one of your entities first.",
            )
            return None
        if len(options) == 1:
            return options[0]
        labels = [name for _sheet_id, name in options]
        selected, ok = QInputDialog.getItem(self, "Claim To Character", "Character:", labels, 0, False)
        if not ok or not selected:
            return None
        for sheet_id, name in options:
            if name == selected:
                return (sheet_id, name)
        return None

    def _apply_claim_entries_to_sheet(self, sheet_id: str, claimed_entries: list[dict]) -> tuple[bool, str]:
        try:
            from player_sheets import apply_claim_to_sheet
        except Exception:
            return False, "Player sheets integration unavailable."
        item_ids: list[str] = []
        notes: list[str] = []
        for entry in claimed_entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("type") or "") == "note":
                text = str(entry.get("note") or entry.get("title") or "").strip()
                if text:
                    notes.append(text)
                continue
            item_id = str(entry.get("item_id") or "").strip()
            resolved = self._loot_pool_resolve_item_path(entry)
            persisted, persist_error = self._persist_claimed_item_to_default_library(entry, resolved)
            if persist_error:
                return False, persist_error
            if persisted is not None and persisted.exists():
                persisted_payload = load_item_payload(persisted)
                canonical_item_id = item_id_from_payload(persisted_payload, fallback_path=persisted)
                item_ids.append(canonical_item_id or str(persisted.resolve()))
            elif resolved is not None and resolved.exists():
                resolved_payload = load_item_payload(resolved)
                canonical_item_id = item_id_from_payload(resolved_payload, fallback_path=resolved)
                item_ids.append(canonical_item_id or str(resolved.resolve()))
            elif item_id:
                item_ids.append(item_id)
        ok, message, _payload = apply_claim_to_sheet(sheet_id, item_ids=item_ids, note_lines=notes)
        return ok, message

    def _capture_sheet_inventory_snapshot(self, sheet_id: str) -> dict | None:
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return None
        try:
            from player_sheets import inventory_payload_for_sheet_id
        except Exception:
            return None
        payload = inventory_payload_for_sheet_id(clean_sheet)
        if not isinstance(payload, dict):
            return None
        return normalize_inventory_payload(payload)

    def _restore_sheet_inventory_snapshot(self, sheet_id: str, inventory_payload: dict) -> tuple[bool, str]:
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return False, "Missing character selection."
        try:
            from player_sheets import set_inventory_payload_for_sheet_id
        except Exception:
            return False, "Player sheets integration unavailable."
        ok, message, _payload = set_inventory_payload_for_sheet_id(
            clean_sheet,
            normalize_inventory_payload(inventory_payload if isinstance(inventory_payload, dict) else {}),
            emit_event=True,
        )
        return bool(ok), str(message or "")

    def _apply_local_loot_claim(self, payload: dict) -> None:
        selected_ids = payload.get("entry_ids")
        sheet_id = str(payload.get("sheet_id") or "").strip()
        if not isinstance(selected_ids, list) or not sheet_id:
            return
        selected_set = {str(entry_id).strip() for entry_id in selected_ids if str(entry_id).strip()}
        if not selected_set:
            return
        claimed = [
            entry for entry in self._session_loot_pool if str(entry.get("entry_id") or "") in selected_set
        ]
        if not claimed:
            return
        ok, message = self._apply_claim_entries_to_sheet(sheet_id, claimed)
        if not ok:
            QMessageBox.warning(self, "Claim", message or "Unable to claim selected entries.")
            return
        self._session_loot_pool = [
            entry for entry in self._session_loot_pool if str(entry.get("entry_id") or "") not in selected_set
        ]
        self._refresh_loot_pool_list()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _on_loot_claim_selected(self) -> None:
        selected_ids = self._selected_loot_pool_ids()
        if not selected_ids:
            QMessageBox.information(self, "Claim", "Select one or more loot entries to claim.")
            return
        selected_sheet = self._choose_sheet_for_claim()
        if selected_sheet is None:
            return
        sheet_id, _sheet_name = selected_sheet
        self._run_session_action(
            "claim_loot",
            {"entry_ids": selected_ids, "sheet_id": sheet_id},
            local_handler=self._apply_local_loot_claim,
            unavailable_title="Claim",
            unavailable_message="You are currently disconnected. Please wait for reconnect.",
        )

    def _build_initiative_overlay(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("SubPanel")
        panel.setMinimumWidth(322)
        panel.setMinimumHeight(240)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(6)
        title = QLabel("Initiative", panel)
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch(1)
        self._initiative_sort_btn = QPushButton("Sort Cards", panel)
        self._initiative_sort_btn.setObjectName("SecondaryButton")
        self._initiative_sort_btn.setProperty("compact", "true")
        self._initiative_sort_btn.clicked.connect(self._on_initiative_sort_cards_requested)
        header.addWidget(self._initiative_sort_btn)
        self._initiative_request_btn = QPushButton("Request New", panel)
        self._initiative_request_btn.setObjectName("SecondaryButton")
        self._initiative_request_btn.setProperty("compact", "true")
        self._initiative_request_btn.clicked.connect(
            lambda: self._request_initiative_round(clear_existing=True, source="request_button")
        )
        header.addWidget(self._initiative_request_btn)
        self._initiative_collapse_btn = QPushButton("Collapse", panel)
        self._initiative_collapse_btn.setObjectName("SecondaryButton")
        self._initiative_collapse_btn.setProperty("compact", "true")
        self._initiative_collapse_btn.clicked.connect(
            lambda: self._collapse_initiative_overlay(force=True)
        )
        header.addWidget(self._initiative_collapse_btn)
        layout.addLayout(header)

        self._initiative_scroll = QScrollArea(panel)
        self._initiative_scroll.setWidgetResizable(True)
        self._initiative_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._initiative_rows_root = QWidget(self._initiative_scroll)
        self._initiative_rows_layout = QVBoxLayout(self._initiative_rows_root)
        self._initiative_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._initiative_rows_layout.setSpacing(6)
        self._initiative_scroll.setWidget(self._initiative_rows_root)
        layout.addWidget(self._initiative_scroll, 1)

        self._initiative_hint = QLabel("", panel)
        self._initiative_hint.setWordWrap(True)
        self._initiative_hint.setStyleSheet("color: #9ca3af; font-size: 11px;")
        layout.addWidget(self._initiative_hint)

        self._initiative_reopen_btn = QToolButton(self)
        self._initiative_reopen_btn.setObjectName("SecondaryButton")
        self._initiative_reopen_btn.setToolTip("Initiative")
        light_icon = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "lightning.svg"))
        self._initiative_reopen_btn.setIcon(QIcon(light_icon))
        self._initiative_reopen_btn.setIconSize(QSize(18, 18))
        self._initiative_reopen_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self._initiative_reopen_btn.setProperty("compact", "true")
        self._initiative_reopen_btn.setFixedSize(34, 34)
        # Keep icon-only action square even with global button style padding.
        self._initiative_reopen_btn.setStyleSheet(
            "QToolButton {"
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #1c2128, stop:1 #0d1117);"
            "border: 1px solid #3b424b;"
            "border-radius: 6px;"
            "padding: 4px;"
            "margin: 0px;"
            "min-width: 34px;"
            "max-width: 34px;"
            "min-height: 34px;"
            "max-height: 34px;"
            "}"
            "QToolButton:hover {"
            "background-color: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #21262d, stop:1 #161b22);"
            "border-color: #58a6ff;"
            "}"
        )
        self._initiative_reopen_btn.clicked.connect(self._on_initiative_reopen_clicked)
        self._initiative_reopen_btn.hide()

        return panel

    def _position_initiative_overlay(self) -> None:
        if not hasattr(self, "_initiative_overlay"):
            return
        if self._initiative_overlay.isVisible():
            initiative_anim = getattr(self, "_initiative_panel_anim", None)
            if initiative_anim is None or initiative_anim.state() != QAbstractAnimation.State.Running:
                self._initiative_overlay.setGeometry(self._target_initiative_geometry())
            self._initiative_overlay.raise_()
        if hasattr(self, "_initiative_reopen_btn") and self._initiative_reopen_btn is not None:
            btn_x = max(8, self.width() - self._initiative_reopen_btn.width() - 20)
            self._initiative_reopen_btn.move(btn_x, 20)
            self._initiative_reopen_btn.raise_()

    def _seed_initiative_state(self) -> None:
        if self._online_mode == ONLINE_MODE_PLAYER:
            player_entries = self._initiative_state.get("player_entries", {})
            if not isinstance(player_entries, dict):
                self._initiative_state["player_entries"] = {}
            entity_entries = self._initiative_state.get("entity_entries", {})
            if not isinstance(entity_entries, dict):
                self._initiative_state["entity_entries"] = {}
            return
        previous_player_entries = self._initiative_state.setdefault("player_entries", {})
        if not isinstance(previous_player_entries, dict):
            previous_player_entries = {}
        player_entries: dict[str, dict] = {}
        entity_entries = self._initiative_state.setdefault("entity_entries", {})
        if not isinstance(entity_entries, dict):
            entity_entries = {}
            self._initiative_state["entity_entries"] = entity_entries

        current_entity_entries: dict[str, str] = {}
        for item in self.canvas.scene().items():
            if not isinstance(item, EntityItem):
                continue
            entity_id = str(item.data(ROLE_ENTITY_ID) or "").strip()
            if not entity_id:
                continue
            label = str(item.data(ROLE_LABEL) or "Entity").strip() or "Entity"
            owner_player_id = str(item.data(ROLE_OWNER_PLAYER_ID) or "").strip()
            if not owner_player_id or owner_player_id not in self._connected_players:
                current_entity_entries[entity_id] = label
                continue
            row_id = f"{owner_player_id}:{entity_id}"
            previous = previous_player_entries.get(row_id, {})
            initiative = previous.get("initiative") if isinstance(previous, dict) else None
            if not isinstance(initiative, int):
                initiative = None
            player_name = self._connected_players.get(owner_player_id, owner_player_id)
            player_entries[row_id] = {
                "player_id": owner_player_id,
                "entity_id": entity_id,
                "name": f"{player_name} - {label}",
                "initiative": initiative,
            }
        self._initiative_state["player_entries"] = player_entries

        for entity_id, name in current_entity_entries.items():
            entry = entity_entries.setdefault(entity_id, {})
            entry["name"] = name
            entry.setdefault("initiative", None)
        stale_entities = [eid for eid in list(entity_entries.keys()) if eid not in current_entity_entries]
        for entity_id in stale_entities:
            entity_entries.pop(entity_id, None)

    def _request_initiative_round(
        self,
        *,
        clear_existing: bool = True,
        source: str = "",
    ) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        self._initiative_state["active"] = True
        self._initiative_state["collapsed"] = False
        self._initiative_inactive_preview_visible = False
        self._seed_initiative_state()
        if clear_existing:
            for group_key in ("player_entries", "entity_entries"):
                group = self._initiative_state.get(group_key, {})
                if not isinstance(group, dict):
                    continue
                for row in group.values():
                    if isinstance(row, dict):
                        row["initiative"] = None
        self._initiative_draft_values.clear()
        self._initiative_value_warning = ""
        self._debug_log(
            "initiative_round_requested",
            clear_existing=bool(clear_existing),
            source=str(source or ""),
        )
        self._show_initiative_overlay(activate=True)
        self._broadcast_snapshot_if_host()

    def _on_initiative_sort_cards_requested(self, _checked: bool = False) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        changed = False
        for group_key in ("player_entries", "entity_entries"):
            group = self._initiative_state.get(group_key, {})
            if not isinstance(group, dict):
                continue
            sorted_items = sorted(group.items(), key=self._initiative_sort_key)
            ordered = {key: value for key, value in sorted_items}
            if list(group.keys()) != list(ordered.keys()):
                self._initiative_state[group_key] = ordered
                changed = True
        self._debug_log("initiative_sort_cards_requested", changed=bool(changed))
        self._render_initiative_overlay()
        if changed and self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _initiative_sort_key(self, item: tuple[str, dict]) -> tuple[int, int, str]:
        entry_id, entry = item
        if not isinstance(entry, dict):
            return (1, 0, str(entry_id).lower())
        initiative = entry.get("initiative")
        name = str(entry.get("name") or entry_id).lower()
        if isinstance(initiative, int):
            return (0, -initiative, name)
        return (1, 0, name)

    def _initiative_cache_key(self, kind: str, key: str) -> str:
        return f"{kind}:{key}"

    def _find_initiative_input(self, kind: str, key: str) -> QLineEdit | None:
        if not hasattr(self, "_initiative_rows_root") or self._initiative_rows_root is None:
            return None
        for candidate in self._initiative_rows_root.findChildren(QLineEdit):
            if not bool(candidate.property("initiative_input")):
                continue
            if str(candidate.property("initiative_kind") or "") != kind:
                continue
            if str(candidate.property("initiative_id") or "") != key:
                continue
            return candidate
        return None

    def _commit_initiative_input(self, edit: QLineEdit | None) -> bool:
        if edit is None or not edit.isEnabled():
            return False
        if not bool(edit.property("initiative_input")):
            return False
        kind = str(edit.property("initiative_kind") or "").strip()
        key = str(edit.property("initiative_id") or "").strip()
        if not kind or not key:
            return False
        self._on_initiative_value_changed(kind, key, edit.text())
        return True

    def _on_initiative_text_edited(self, kind: str, key: str, raw_value: str) -> None:
        cache_key = self._initiative_cache_key(kind, key)
        self._initiative_draft_values[cache_key] = str(raw_value or "")
        self._debug_log(
            "initiative_text_edited",
            kind=str(kind),
            row_id=str(key),
            raw=str(raw_value or ""),
        )

    def _all_players_have_initiative(self) -> bool:
        entries = self._initiative_state.get("player_entries", {})
        if not isinstance(entries, dict):
            return True
        players_with_entities: dict[str, list[dict]] = {}
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            player_id = str(entry.get("player_id") or "").strip()
            if not player_id:
                continue
            players_with_entities.setdefault(player_id, []).append(entry)
        if not players_with_entities:
            return True
        for owned_rows in players_with_entities.values():
            if not owned_rows:
                continue
            for entry in owned_rows:
                if entry.get("initiative") is None:
                    return False
        return True

    def _player_has_visible_initiative_rows(self) -> bool:
        if self._online_mode != ONLINE_MODE_PLAYER:
            return True
        entries = self._initiative_state.get("player_entries", {})
        if not isinstance(entries, dict) or not entries:
            return False
        local_id = str(self._local_player_id or "").strip()
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            row_player_id = str(entry.get("player_id") or "").strip()
            if local_id and row_player_id != local_id:
                continue
            return True
        return False

    def _on_initiative_value_changed(self, kind: str, key: str, raw_value: str) -> None:
        cache_key = self._initiative_cache_key(kind, key)
        self._initiative_draft_values.pop(cache_key, None)
        value_text = str(raw_value or "").strip()
        value: int | None = None
        if value_text:
            try:
                value = int(value_text)
            except (TypeError, ValueError):
                value = None
        target = self._initiative_state.get("player_entries" if kind == "player" else "entity_entries", {})
        if not isinstance(target, dict):
            return
        row = target.setdefault(key, {})
        previous_value = row.get("initiative")
        if not isinstance(previous_value, int):
            previous_value = None
        if value_text and value is None:
            self._initiative_value_warning = "Use numbers only for initiative."
            self._debug_log(
                "initiative_value_invalid_rejected",
                kind=str(kind),
                row_id=str(key),
                raw=str(raw_value or ""),
            )
            self._append_server_log("[WARN] Initiative accepts numbers only.")
            self._render_initiative_overlay()
            return
        self._initiative_value_warning = ""
        row["initiative"] = value
        self._debug_log(
            "initiative_value_changed_local",
            kind=str(kind),
            row_id=str(key),
            raw=str(raw_value or ""),
            parsed=value,
        )
        if previous_value == value:
            self._debug_log(
                "initiative_value_unchanged_skip_sync",
                kind=str(kind),
                row_id=str(key),
                value=value,
            )
            return

        if (
            self._online_mode == ONLINE_MODE_PLAYER
            and kind == "player"
        ):
            local_id = str(self._local_player_id or "")
            row_player_id = str(row.get("player_id") or "")
            if row_player_id == local_id:
                self._dispatch_player_command(
                    "initiative_update",
                    {"kind": kind, "id": key, "initiative": value},
                    silent=True,
                )
        elif self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()
        self._render_initiative_overlay()

    def _render_initiative_overlay(self) -> None:
        if not hasattr(self, "_initiative_rows_layout"):
            return
        active = bool(self._initiative_state.get("active", False))
        inactive_preview = bool(self._initiative_inactive_preview_visible) and not active
        focus_kind = ""
        focus_key = ""
        focus_cursor: int | None = None
        focus_selection_start: int | None = None
        focus_selection_length = 0
        focus_target_edit: QLineEdit | None = None
        first_editable_player_edit: QLineEdit | None = None
        focused_widget = QApplication.focusWidget()
        if isinstance(focused_widget, QLineEdit) and bool(focused_widget.property("initiative_input")):
            focus_kind = str(focused_widget.property("initiative_kind") or "")
            focus_key = str(focused_widget.property("initiative_id") or "")
            focus_cursor = int(focused_widget.cursorPosition())
            if focused_widget.hasSelectedText():
                focus_selection_start = int(focused_widget.selectionStart())
                focus_selection_length = len(focused_widget.selectedText() or "")
        elif self._initiative_last_target is not None:
            focus_kind, focus_key = self._initiative_last_target
        if not active and not inactive_preview:
            self._debug_log("initiative_render_inactive")
            self._initiative_draft_values.clear()
            while self._initiative_rows_layout.count():
                child = self._initiative_rows_layout.takeAt(0)
                widget = child.widget()
                if widget is not None:
                    for edit in widget.findChildren(QLineEdit):
                        if bool(edit.property("initiative_input")):
                            edit.blockSignals(True)
                    widget.hide()
                    widget.setParent(None)
                    widget.deleteLater()
            self._initiative_collapse_btn.setEnabled(False)
            self._initiative_hint.setText("Initiative is inactive. DM can start it with /initiative.")
            return
        self._seed_initiative_state()
        while self._initiative_rows_layout.count():
            child = self._initiative_rows_layout.takeAt(0)
            widget = child.widget()
            if widget is not None:
                for edit in widget.findChildren(QLineEdit):
                    if bool(edit.property("initiative_input")):
                        edit.blockSignals(True)
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        is_dm = self._online_mode == ONLINE_MODE_DM_HOST
        is_player = self._online_mode == ONLINE_MODE_PLAYER
        local_id = str(self._local_player_id or "")

        def _wire_initiative_input(
            edit: QLineEdit,
            *,
            kind: str,
            key: str,
            value: object,
            editable: bool,
        ) -> None:
            edit.setFixedWidth(70)
            edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cache_key = self._initiative_cache_key(kind, key)
            draft = self._initiative_draft_values.get(cache_key)
            if draft is not None:
                edit.setText(draft)
            elif isinstance(value, int):
                edit.setText(str(value))
            edit.setEnabled(editable)
            edit.setProperty("initiative_input", True)
            edit.setProperty("initiative_kind", kind)
            edit.setProperty("initiative_id", key)
            edit.textEdited.connect(
                lambda text, row_kind=kind, row_key=key: self._on_initiative_text_edited(
                    row_kind, row_key, text
                )
            )
            edit.editingFinished.connect(
                lambda row_kind=kind, row_key=key, source=edit: self._on_initiative_value_changed(
                    row_kind,
                    row_key,
                    source.text(),
                )
            )
            edit.returnPressed.connect(
                lambda row_kind=kind, row_key=key, source=edit: self._on_initiative_value_changed(
                    row_kind,
                    row_key,
                    source.text(),
                )
            )
            nonlocal focus_target_edit
            if focus_kind == kind and focus_key == key:
                focus_target_edit = edit

        player_entries = self._initiative_state.get("player_entries", {})
        displayed_player_rows = 0
        if isinstance(player_entries, dict):
            for player_id, entry in sorted(
                player_entries.items(),
                key=self._initiative_sort_key,
            ):
                if not isinstance(entry, dict):
                    continue
                entry_player_id = str(entry.get("player_id") or "").strip()
                if is_player and entry_player_id != local_id:
                    continue
                displayed_player_rows += 1
                row_widget = QWidget(self._initiative_rows_root)
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 0, 0, 0)
                row_layout.setSpacing(6)
                value = entry.get("initiative")
                label = QLabel(str(entry.get("name") or player_id), row_widget)
                row_layout.addWidget(label)
                check = QLabel("OK" if isinstance(value, int) else "", row_widget)
                check.setStyleSheet("color: #22c55e; font-weight: bold;")
                row_layout.addWidget(check)
                row_layout.addStretch(1)
                edit = QLineEdit(row_widget)
                editable = is_dm or (is_player and entry_player_id == local_id)
                _wire_initiative_input(
                    edit,
                    kind="player",
                    key=player_id,
                    value=value,
                    editable=editable,
                )
                if is_player and editable and first_editable_player_edit is None:
                    first_editable_player_edit = edit
                row_layout.addWidget(edit)
                self._initiative_rows_layout.addWidget(row_widget)

        if is_dm:
            entity_entries = self._initiative_state.get("entity_entries", {})
            if isinstance(entity_entries, dict):
                for entity_id, entry in sorted(
                    entity_entries.items(),
                    key=self._initiative_sort_key,
                ):
                    if not isinstance(entry, dict):
                        continue
                    row_widget = QWidget(self._initiative_rows_root)
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(0, 0, 0, 0)
                    row_layout.setSpacing(6)
                    value = entry.get("initiative")
                    label = QLabel(f"Entity: {str(entry.get('name') or entity_id)}", row_widget)
                    row_layout.addWidget(label)
                    check = QLabel("OK" if isinstance(value, int) else "", row_widget)
                    check.setStyleSheet("color: #22c55e; font-weight: bold;")
                    row_layout.addWidget(check)
                    row_layout.addStretch(1)
                    edit = QLineEdit(row_widget)
                    _wire_initiative_input(
                        edit,
                        kind="entity",
                        key=entity_id,
                        value=value,
                        editable=True,
                    )
                    row_layout.addWidget(edit)
                    self._initiative_rows_layout.addWidget(row_widget)

        self._initiative_rows_layout.addStretch(1)
        entity_entries = self._initiative_state.get("entity_entries", {})
        entity_count = len(entity_entries) if isinstance(entity_entries, dict) else 0
        all_submitted = self._all_players_have_initiative()
        self._initiative_sort_btn.setVisible(is_dm)
        self._initiative_request_btn.setVisible(is_dm)
        self._initiative_collapse_btn.setEnabled(is_dm or is_player)
        self._debug_log(
            "initiative_render",
            active=bool(self._initiative_state.get("active", False)),
            collapsed=bool(self._initiative_state.get("collapsed", False)),
            player_rows=int(displayed_player_rows),
            entity_rows=int(entity_count),
            all_submitted=bool(all_submitted),
            focus_target=f"{focus_kind}:{focus_key}" if focus_kind and focus_key else "",
        )
        if inactive_preview:
            hint_text = "Initiative is inactive. DM can inspect entries here and start it with /initiative."
        elif is_player and displayed_player_rows == 0:
            hint_text = "No entity is assigned to you, so no initiative entry is required."
        elif is_dm and all_submitted:
            hint_text = "All players submitted. DM can collapse and reopen with the light button."
        elif is_dm:
            hint_text = "Waiting for player initiative entries. DM can still collapse and reopen this panel."
        else:
            hint_text = "Players can edit their own initiative and can collapse this panel locally if needed."
        warning_text = str(self._initiative_value_warning or "").strip()
        if warning_text:
            hint_text = f"{hint_text}\n{warning_text}"
        self._initiative_hint.setText(hint_text)
        if focus_target_edit is not None and focus_target_edit.isEnabled():
            focus_target_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self._initiative_last_target = (focus_kind, focus_key)
            current_text_len = len(focus_target_edit.text() or "")
            if focus_cursor is not None:
                focus_target_edit.setCursorPosition(max(0, min(int(focus_cursor), current_text_len)))
            if (
                focus_selection_start is not None
                and focus_selection_length > 0
                and current_text_len > 0
            ):
                start = max(0, min(int(focus_selection_start), current_text_len))
                length = max(0, min(int(focus_selection_length), current_text_len - start))
                if length > 0:
                    focus_target_edit.setSelection(start, length)
        elif is_player and first_editable_player_edit is not None and first_editable_player_edit.isEnabled():
            current_focus = QApplication.focusWidget()
            if not (
                isinstance(current_focus, QLineEdit)
                and bool(current_focus.property("initiative_input"))
            ):
                first_editable_player_edit.setFocus(Qt.FocusReason.OtherFocusReason)
                self._initiative_last_target = (
                    str(first_editable_player_edit.property("initiative_kind") or ""),
                    str(first_editable_player_edit.property("initiative_id") or ""),
                )

    def _show_initiative_overlay(
        self,
        _checked: bool = False,
        *,
        activate: bool = False,
        allow_inactive: bool = False,
    ) -> None:
        if self._online_mode not in (ONLINE_MODE_DM_HOST, ONLINE_MODE_PLAYER):
            return
        self._debug_log(
            "initiative_overlay_show_requested",
            activate=bool(activate),
            allow_inactive=bool(allow_inactive),
            currently_active=bool(self._initiative_state.get("active", False)),
        )
        if activate:
            self._initiative_state["active"] = True
            self._initiative_inactive_preview_visible = False
        elif allow_inactive and not bool(self._initiative_state.get("active", False)):
            self._initiative_inactive_preview_visible = True
        else:
            self._initiative_inactive_preview_visible = False
        if not bool(self._initiative_state.get("active", False)) and not allow_inactive:
            self._debug_log("initiative_overlay_show_skipped_inactive")
            return
        if self._online_mode == ONLINE_MODE_PLAYER and not self._player_has_visible_initiative_rows():
            self._debug_log("initiative_overlay_show_skipped_no_player_rows")
            self._initiative_overlay.hide()
            return
        if bool(self._initiative_state.get("active", False)):
            self._initiative_state["collapsed"] = False
        if self._initiative_overlay.isVisible():
            # Snapshot refreshes can call this repeatedly; keep it centered without re-running
            # open animation to avoid side-jumps/flicker.
            self._render_initiative_overlay()
            self._position_initiative_overlay()
            return
        self._render_initiative_overlay()
        self._animate_center_panel(
            self._initiative_overlay,
            show=True,
            target_rect=self._target_initiative_geometry(),
            attr_name="_initiative_panel_anim",
            duration_ms=170,
        )
        self._position_initiative_overlay()

    def _on_initiative_reopen_clicked(self, _checked: bool = False) -> None:
        self._debug_log(
            "initiative_reopen_clicked",
            overlay_hidden=bool(self._initiative_overlay.isHidden()),
        )
        if not self._initiative_overlay.isHidden():
            if self._online_mode == ONLINE_MODE_DM_HOST:
                self._collapse_initiative_overlay(force=True)
            else:
                self._collapse_initiative_overlay(force=True)
            return
        if self._online_mode == ONLINE_MODE_DM_HOST and not bool(self._initiative_state.get("active", False)):
            self._show_initiative_overlay(allow_inactive=True)
            return
        self._show_initiative_overlay()

    def _collapse_initiative_overlay(self, *, force: bool = False) -> None:
        if self._online_mode == ONLINE_MODE_PLAYER:
            self._initiative_state["collapsed"] = True
            self._initiative_inactive_preview_visible = False
            existing = getattr(self, "_initiative_panel_anim", None)
            if isinstance(existing, QPropertyAnimation):
                existing.stop()
            self._initiative_overlay.hide()
            self._initiative_reopen_btn.hide()
            self._position_initiative_overlay()
            return
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        self._debug_log(
            "initiative_collapse_requested",
            force=bool(force),
            all_submitted=bool(self._all_players_have_initiative()),
        )
        if not force and not self._all_players_have_initiative():
            self._debug_log("initiative_collapse_blocked")
            return
        self._initiative_state["collapsed"] = True
        self._initiative_inactive_preview_visible = False
        self._animate_center_panel(
            self._initiative_overlay,
            show=False,
            target_rect=self._target_initiative_geometry(),
            attr_name="_initiative_panel_anim",
            duration_ms=150,
        )
        self._initiative_reopen_btn.setVisible(True)
        self._position_initiative_overlay()
        self._broadcast_snapshot_if_host()

    def _get_session_panel_height(self) -> float:
        return float(self._session_panel_height)

    def _set_session_panel_height(self, value: float) -> None:
        self._session_panel_height = max(0.0, float(value))
        self._position_session_overlay()

    sessionPanelHeight = Property(
        float,
        fget=_get_session_panel_height,
        fset=_set_session_panel_height,
    )

    def _set_session_panels_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        self._session_panels_collapsed = bool(collapsed)
        self._session_toggle_btn.set_expanded(not self._session_panels_collapsed)
        self._update_session_bottom_panel_height(animate=animate)

    def _update_session_bottom_panel_height(self, animate: bool = True) -> None:
        target_height = 220 if not self._session_panels_collapsed else 0
        if not self._session_panels_collapsed:
            self._session_bottom_panel.setVisible(True)
            self._session_content.setVisible(True)
        if not animate:
            self._session_panel_height_anim.stop()
            self._set_session_panel_height(float(target_height))
            if self._session_panels_collapsed:
                self._session_content.setVisible(False)
                self._session_bottom_panel.setVisible(False)
            return
        start_height = int(round(self._session_panel_height))
        if start_height == target_height:
            if self._session_panels_collapsed:
                self._session_content.setVisible(False)
                self._session_bottom_panel.setVisible(False)
            self._position_session_overlay()
            return
        self._session_panel_height_anim.stop()
        self._session_panel_height_anim.setStartValue(float(start_height))
        self._session_panel_height_anim.setEndValue(float(target_height))
        self._session_panel_height_anim.start()

    def _on_session_panel_anim_finished(self) -> None:
        if self._session_panels_collapsed:
            self._session_content.setVisible(False)
            self._session_bottom_panel.setVisible(False)
        self._position_session_overlay()

    def _player_network_actions_available(self) -> bool:
        if self._online_mode != ONLINE_MODE_PLAYER or self._client_controller is None:
            return False
        if isinstance(self._client_controller, ClientSessionController):
            return bool(self._player_connection_ready)
        return callable(getattr(self._client_controller, "send_command", None))

    def _dispatch_player_command_with_request_id(
        self,
        action: str,
        payload: dict,
        *,
        unavailable_title: str = "",
        unavailable_message: str = "",
        silent: bool = False,
        request_id: str | None = None,
    ) -> str | None:
        if self._online_mode != ONLINE_MODE_PLAYER or self._client_controller is None:
            return None
        if not self._player_network_actions_available():
            if (not silent) and unavailable_title and unavailable_message:
                QMessageBox.warning(self, unavailable_title, unavailable_message)
            return None
        send_command = getattr(self._client_controller, "send_command", None)
        if not callable(send_command):
            return None
        outgoing_request_id = str(request_id or uuid.uuid4().hex)
        sent = send_command(
            action,
            payload,
            request_id=outgoing_request_id,
        )
        if sent is False:
            return None
        return outgoing_request_id

    def _dispatch_player_command(
        self,
        action: str,
        payload: dict,
        *,
        unavailable_title: str = "",
        unavailable_message: str = "",
        silent: bool = False,
    ) -> bool:
        return self._dispatch_player_command_with_request_id(
            action,
            payload,
            unavailable_title=unavailable_title,
            unavailable_message=unavailable_message,
            silent=silent,
        ) is not None

    def _dispatch_player_link_character_request(self, request_payload: dict) -> bool:
        payload = dict(request_payload) if isinstance(request_payload, dict) else {}
        request_id = self._dispatch_player_command_with_request_id(
            "link_character_entity",
            payload,
            silent=True,
        )
        if not request_id:
            return False
        self._pending_link_entity_requests[request_id] = payload
        return True

    def _dispatch_player_unlink_character_request(self, request_payload: dict) -> bool:
        payload = dict(request_payload) if isinstance(request_payload, dict) else {}
        request_id = self._dispatch_player_command_with_request_id(
            "unlink_character_entity",
            payload,
            silent=True,
        )
        if not request_id:
            return False
        self._pending_unlink_entity_requests[request_id] = payload
        return True

    def _has_pending_character_link_resolution_for_entity(self, entity_id: str) -> bool:
        clean_entity = str(entity_id or "").strip()
        if not clean_entity:
            return False
        for payload in self._pending_link_entity_requests.values():
            if str(payload.get("entity_id") or "").strip() == clean_entity:
                return True
        for payload in self._pending_unlink_entity_requests.values():
            if str(payload.get("entity_id") or "").strip() == clean_entity:
                return True
        return False

    def _pending_online_command_action_for_request(self, request_id: str) -> str:
        clean_request_id = str(request_id or "").strip()
        if not clean_request_id:
            return ""
        if clean_request_id == self._pending_player_state_update_request_id:
            return "state_update"
        if clean_request_id in self._pending_link_entity_requests:
            return "link_character_entity"
        if clean_request_id in self._pending_unlink_entity_requests:
            return "unlink_character_entity"
        if clean_request_id in self._pending_add_loot_from_inventory_requests:
            return "add_loot_from_inventory"
        return ""

    def _clear_pending_online_command_requests(self, *, reason: str = "") -> None:
        pending_count = (
            len(self._pending_link_entity_requests)
            + len(self._pending_unlink_entity_requests)
            + len(self._pending_add_loot_from_inventory_requests)
        )
        if pending_count <= 0:
            return
        self._pending_link_entity_requests.clear()
        self._pending_unlink_entity_requests.clear()
        self._pending_add_loot_from_inventory_requests.clear()
        if reason:
            noun = "request" if pending_count == 1 else "requests"
            self._append_server_log(
                f"[WARN] Cleared {pending_count} pending online command {noun} after {reason}."
            )

    def _linked_character_conflict_signature(self, conflict: dict) -> str:
        payload = dict(conflict) if isinstance(conflict, dict) else {}
        requested_character_id = str(payload.get("requested_character_id") or "").strip()
        if not requested_character_id or requested_character_id == str(payload.get("character_id") or "").strip():
            payload.pop("requested_character_id", None)
        payload["inventory"] = normalize_inventory_payload(payload.get("inventory") or {})
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    def _has_pending_link_conflict_for_character(self, character_id: str) -> bool:
        clean_character = str(character_id or "").strip()
        if not clean_character:
            return False
        for conflict in self._pending_link_conflicts.values():
            if not isinstance(conflict, dict):
                continue
            if str(conflict.get("character_id") or "").strip() == clean_character:
                return True
            if str(conflict.get("requested_character_id") or "").strip() == clean_character:
                return True
        return False

    def _cache_host_link_conflict_response(
        self,
        cache_key: str,
        signature: str,
        *,
        ok: bool,
        message: str,
        data: dict | None = None,
    ) -> None:
        clean_cache_key = str(cache_key or "").strip()
        if not clean_cache_key:
            return
        self._host_link_conflict_response_cache[clean_cache_key] = {
            "signature": str(signature or "").strip(),
            "ok": bool(ok),
            "message": str(message or "").strip(),
            "data": dict(data) if isinstance(data, dict) else {},
            "created_monotonic": float(time.monotonic()),
        }

    def _replay_host_link_conflict_response(
        self,
        player_id: str,
        cache_key: str,
        signature: str,
        *,
        request_id: str | None = None,
    ) -> bool:
        if self._host_controller is None:
            return False
        cached = self._host_link_conflict_response_cache.get(str(cache_key or "").strip())
        if not isinstance(cached, dict):
            return False
        if str(cached.get("signature") or "").strip() != str(signature or "").strip():
            return False
        self._host_controller.send_command_result(
            player_id,
            ok=bool(cached.get("ok")),
            message=str(cached.get("message") or "Command rejected"),
            request_id=request_id,
            data=dict(cached.get("data") or {}),
        )
        return True

    def _build_linked_character_conflict(
        self,
        *,
        dungeon_id: str,
        entity_id: str,
        character_id: str,
        sheet_id: str,
        sheet_name: str,
        save_revision: int = 0,
        last_saved_at: str = "",
        content_hash: str = "",
        inventory: dict | None = None,
        requested_character_id: str = "",
        allow_force_push: bool = True,
        requires_local_create: bool = False,
    ) -> dict:
        clean_character = str(character_id or "").strip()
        clean_entity = str(entity_id or "").strip()
        clean_dungeon = str(dungeon_id or "").strip()
        conflict_key = "::".join(
            [
                clean_dungeon or "",
                clean_entity or "",
                clean_character or "",
            ]
        )
        return {
            "conflict_key": conflict_key,
            "dungeon_id": clean_dungeon,
            "entity_id": clean_entity,
            "character_id": clean_character,
            "requested_character_id": str(requested_character_id or "").strip(),
            "sheet_id": str(sheet_id or "").strip(),
            "sheet_name": str(sheet_name or sheet_id or character_id).strip(),
            "save_revision": max(0, int(save_revision or 0)),
            "last_saved_at": str(last_saved_at or ""),
            "content_hash": str(content_hash or ""),
            "inventory": normalize_inventory_payload(inventory or {}),
            "allow_force_push": bool(allow_force_push),
            "requires_local_create": bool(requires_local_create),
        }

    def _prompt_linked_character_conflict(self, conflict: dict, *, force: bool = False) -> bool:
        normalized = dict(conflict) if isinstance(conflict, dict) else {}
        conflict_key = str(normalized.get("conflict_key") or "").strip()
        if not conflict_key:
            return False
        signature = self._linked_character_conflict_signature(normalized)
        existing_signature = self._suppressed_link_conflicts.get(conflict_key, "")
        if (not force) and existing_signature == signature:
            return False
        self._pending_link_conflicts[conflict_key] = normalized
        self._append_server_log(
            "[WARN] Linked character data conflict detected. Resolve it before retrying inventory sync."
        )
        return True

    def _queue_pending_player_state_update(self, payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        self._pending_player_state_update = dict(payload)
        self._pending_player_state_update_request_id = ""

    def _send_player_state_update(self, payload: dict) -> bool:
        if not isinstance(payload, dict):
            return False
        pending = dict(payload)
        request_id = self._dispatch_player_command_with_request_id(
            "state_update",
            pending,
            silent=True,
        )
        self._pending_player_state_update = pending
        self._pending_player_state_update_request_id = str(request_id or "")
        return request_id is not None

    def _flush_pending_player_state_update(self) -> bool:
        pending = self._pending_player_state_update
        if not isinstance(pending, dict):
            return False
        if self._pending_player_state_update_request_id:
            return False
        request_id = self._dispatch_player_command_with_request_id(
            "state_update",
            dict(pending),
            silent=True,
        )
        if request_id is None:
            return False
        self._pending_player_state_update_request_id = request_id
        return True

    def _queue_loot_claim_finalize(self, claim_id: str, *, applied: bool, error: str = "") -> None:
        clean_claim_id = str(claim_id or "").strip()
        if not clean_claim_id:
            return
        self._pending_loot_claim_finalizations[clean_claim_id] = {
            "claim_id": clean_claim_id,
            "applied": bool(applied),
            "error": str(error or ""),
            "inflight": False,
        }
        self._flush_pending_loot_claim_finalizations()

    def _flush_pending_loot_claim_finalizations(self) -> int:
        if not self._pending_loot_claim_finalizations:
            return 0
        if self._online_mode != ONLINE_MODE_PLAYER or self._client_controller is None:
            return 0
        if not self._player_network_actions_available():
            return 0
        sent_count = 0
        for claim_id, finalize_payload in list(self._pending_loot_claim_finalizations.items()):
            if bool(finalize_payload.get("inflight")):
                continue
            sent = self._dispatch_player_command(
                "claim_loot_finalize",
                {
                    "claim_id": claim_id,
                    "applied": bool(finalize_payload.get("applied")),
                    "error": str(finalize_payload.get("error") or ""),
                },
                silent=True,
            )
            if sent:
                finalize_payload["inflight"] = True
                self._pending_loot_claim_finalizations[claim_id] = finalize_payload
                sent_count += 1
        return sent_count

    def _pending_loot_claim_id_for_sheet(self, sheet_id: str, *, status: str = "") -> str:
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return ""
        for claim_id, pending in self._pending_loot_claim_rollbacks.items():
            if not isinstance(pending, dict):
                continue
            if str(pending.get("sheet_id") or "").strip() != clean_sheet:
                continue
            if status and str(pending.get("status") or "").strip() != status:
                continue
            return str(claim_id)
        return ""

    def _pending_loot_claim_id_for_conflict(self, conflict_key: str) -> str:
        clean_conflict_key = str(conflict_key or "").strip()
        if not clean_conflict_key:
            return ""
        for claim_id, pending in self._pending_loot_claim_rollbacks.items():
            if not isinstance(pending, dict):
                continue
            if str(pending.get("conflict_key") or "").strip() == clean_conflict_key:
                return str(claim_id)
        return ""

    def _finalize_pending_loot_claim_success(self, claim_id: str) -> None:
        clean_claim_id = str(claim_id or "").strip()
        if not clean_claim_id:
            return
        pending = self._pending_loot_claim_rollbacks.get(clean_claim_id)
        if isinstance(pending, dict):
            pending["status"] = "awaiting_finalize_ack"
            pending["sync_request_id"] = ""
            pending["conflict_key"] = ""
            self._pending_loot_claim_rollbacks[clean_claim_id] = pending
        self._queue_loot_claim_finalize(clean_claim_id, applied=True)

    def _rollback_pending_loot_claim(
        self,
        claim_id: str,
        *,
        reason: str = "",
        notify_host: bool = False,
    ) -> None:
        clean_claim_id = str(claim_id or "").strip()
        if not clean_claim_id:
            return
        pending = self._pending_loot_claim_rollbacks.pop(clean_claim_id, None)
        self._pending_loot_claim_finalizations.pop(clean_claim_id, None)
        if isinstance(pending, dict):
            ok, rollback_message = self._restore_sheet_inventory_snapshot(
                str(pending.get("sheet_id") or ""),
                dict(pending.get("inventory") or {}),
            )
            if not ok:
                self._append_server_log(
                    f"[WARN] Failed to roll back local loot claim: {rollback_message}"
                )
        if notify_host:
            self._queue_loot_claim_finalize(
                clean_claim_id,
                applied=False,
                error=str(reason or "Claim was canceled."),
            )

    def _dispatch_pending_loot_claim_inventory_sync(self, claim_id: str) -> bool:
        clean_claim_id = str(claim_id or "").strip()
        pending = self._pending_loot_claim_rollbacks.get(clean_claim_id)
        if not isinstance(pending, dict):
            return False
        if str(pending.get("status") or "").strip() != "awaiting_sync_dispatch":
            return False
        sheet_id = str(pending.get("sheet_id") or "").strip()
        if not sheet_id:
            self._rollback_pending_loot_claim(
                clean_claim_id,
                reason="Claim is missing its character selection.",
                notify_host=True,
            )
            return False
        inventory_payload = self._capture_sheet_inventory_snapshot(sheet_id)
        if not isinstance(inventory_payload, dict):
            self._rollback_pending_loot_claim(
                clean_claim_id,
                reason="Unable to read the claimed inventory state.",
                notify_host=True,
            )
            return False
        request_id, character_id = self._dispatch_online_character_inventory_sync(
            sheet_id,
            inventory_payload,
            claim_id=clean_claim_id,
            log_conflict_blocked=False,
        )
        pending = self._pending_loot_claim_rollbacks.get(clean_claim_id)
        if not isinstance(pending, dict):
            return False
        pending["character_id"] = character_id
        if request_id is None:
            pending["status"] = "awaiting_sync_dispatch"
            self._pending_loot_claim_rollbacks[clean_claim_id] = pending
            return False
        pending["status"] = "sync_inflight"
        pending["sync_request_id"] = request_id
        self._pending_loot_claim_rollbacks[clean_claim_id] = pending
        return True

    def _resume_pending_loot_claim_after_host_sync(
        self,
        claim_id: str,
        *,
        character_id: str,
        host_inventory: dict,
        sheet_name: str,
        archive_b64: str,
        save_revision: int,
        last_saved_at: str,
        content_hash: str,
    ) -> bool:
        clean_claim_id = str(claim_id or "").strip()
        pending = self._pending_loot_claim_rollbacks.get(clean_claim_id)
        if not isinstance(pending, dict):
            return False
        pending["status"] = "awaiting_sync_dispatch"
        pending["sync_request_id"] = ""
        pending["conflict_key"] = ""
        pending["character_id"] = str(character_id or "")
        self._pending_loot_claim_rollbacks[clean_claim_id] = pending
        ok, message = self._sync_local_sheet_inventory_from_host(
            character_id,
            host_inventory,
            sheet_name=sheet_name,
            archive_b64=archive_b64,
            save_revision=save_revision,
            last_saved_at=last_saved_at,
            content_hash=content_hash,
            refresh_entities=True,
        )
        if not ok:
            QMessageBox.warning(
                self,
                "Character Sync",
                str(message or "Unable to synchronize local character data."),
            )
            pending = self._pending_loot_claim_rollbacks.get(clean_claim_id)
            if isinstance(pending, dict):
                pending["status"] = "awaiting_sync_dispatch"
                pending["conflict_key"] = ""
                self._pending_loot_claim_rollbacks[clean_claim_id] = pending
            return False
        self._approved_host_inventory_sync_characters.add(str(character_id or "").strip())
        claimed_entries = [
            entry
            for entry in pending.get("claimed_entries", [])
            if isinstance(entry, dict)
        ]
        ok, message = self._apply_claim_entries_to_sheet(
            str(pending.get("sheet_id") or ""),
            claimed_entries,
        )
        if not ok:
            self._append_server_log(f"[WARN] {message}")
            self._rollback_pending_loot_claim(
                clean_claim_id,
                reason=str(message or "Unable to apply claim."),
                notify_host=True,
            )
            return False
        latest_pending = self._pending_loot_claim_rollbacks.get(clean_claim_id)
        if (
            isinstance(latest_pending, dict)
            and str(latest_pending.get("status") or "").strip() == "awaiting_sync_dispatch"
        ):
            self._dispatch_pending_loot_claim_inventory_sync(clean_claim_id)
        return True

    def _run_session_action(
        self,
        action: str,
        payload: dict,
        *,
        local_handler,
        unavailable_title: str = "",
        unavailable_message: str = "",
    ) -> bool:
        if self._online_mode == ONLINE_MODE_PLAYER:
            return self._dispatch_player_command(
                action,
                payload,
                unavailable_title=unavailable_title,
                unavailable_message=unavailable_message,
            )
        local_handler(dict(payload))
        return True

    def _player_interactions_temporarily_blocked(self) -> bool:
        return (
            self._online_mode == ONLINE_MODE_PLAYER
            and isinstance(self._client_controller, ClientSessionController)
            and not self._player_connection_ready
        )

    def _apply_online_permissions(self) -> None:
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self.canvas.set_stroke_owner_player_id("")
            self.tool_panel.set_player_tool_restrictions(False)
            self.tool_panel.set_online_loot_actions(
                show_pool=True,
                show_add_items=True,
                player_mode=False,
            )
            self.inspector.set_owner_assignment_enabled(True)
            self.inspector.set_link_character_enabled(True)
            self._loot_add_btn.setVisible(True)
            self._loot_add_btn.setToolTip("Add Items")
            self._loot_add_note_btn.setVisible(True)
            self._loot_remove_btn.setVisible(True)
            self._loot_claim_btn.setVisible(False)
            for item in self.canvas.scene().items():
                if isinstance(item, EntityItem):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                    item.set_player_stats_visible(False)
                elif item.data(ROLE_KIND) == "stroke":
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                elif item.data(ROLE_KIND):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            self._update_loot_pool_badge()
            return

        if self._online_mode == ONLINE_MODE_PLAYER:
            interactions_blocked = self._player_interactions_temporarily_blocked()
            player_can_edit = bool((not interactions_blocked) and self._local_player_id)
            self.canvas.set_stroke_owner_player_id(str(self._local_player_id or "") if player_can_edit else "")
            allowed_tools = PLAYER_ALLOWED_TOOLS if not interactions_blocked else {ToolType.SELECT}
            self.tool_panel.set_player_tool_restrictions(True, allowed_tools)
            self.tool_panel.set_online_loot_actions(
                show_pool=True,
                show_add_items=player_can_edit,
                player_mode=True,
            )
            if self.canvas.current_tool not in allowed_tools:
                self.canvas.current_tool = ToolType.SELECT
            self.inspector.set_owner_assignment_enabled(False)
            self.inspector.set_link_character_enabled(player_can_edit)
            self._loot_add_btn.setVisible(player_can_edit)
            self._loot_add_btn.setToolTip("Add Backpack + Equipment to Loot Pool")
            self._loot_add_note_btn.setVisible(False)
            self._loot_remove_btn.setVisible(False)
            self._loot_claim_btn.setVisible(True)
            self._loot_claim_btn.setEnabled(player_can_edit)
            if not player_can_edit:
                self.inspector.set_entity(None)

            for item in self.canvas.scene().items():
                if isinstance(item, EntityItem):
                    owned = player_can_edit and self._is_entity_owned_by_local_player(item)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, owned)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, owned)
                    item.set_player_stats_visible(owned)
                elif item.data(ROLE_KIND) == "stroke":
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                elif item.data(ROLE_KIND):
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
                    item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
            self._update_loot_pool_badge()
            return

        # Local DM mode
        self.canvas.set_stroke_owner_player_id("")
        self.tool_panel.set_player_tool_restrictions(False)
        self.tool_panel.set_online_loot_actions(
            show_pool=False,
            show_add_items=False,
            player_mode=False,
        )
        self.inspector.set_owner_assignment_enabled(True)
        self.inspector.set_link_character_enabled(True)
        self._loot_add_btn.setVisible(True)
        self._loot_add_btn.setToolTip("Add Items")
        self._loot_add_note_btn.setVisible(True)
        self._loot_remove_btn.setVisible(True)
        self._loot_claim_btn.setVisible(False)
        for item in self.canvas.scene().items():
            if isinstance(item, EntityItem):
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
                item.set_player_stats_visible(False)
            elif item.data(ROLE_KIND) == "stroke":
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
            elif item.data(ROLE_KIND):
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
                item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._update_loot_pool_badge()

    def _on_chat_submitted(self, text: str) -> None:
        command = str(text or "").strip()
        self._debug_log("chat_submitted", text=command)
        if command.lower() == "/initiative":
            self._debug_log(
                "initiative_command_received",
                allowed=bool(self._online_mode == ONLINE_MODE_DM_HOST),
            )
            if self._online_mode == ONLINE_MODE_DM_HOST:
                self._request_initiative_round(clear_existing=True, source="chat_command")
            else:
                self._append_chat_message(
                    "System",
                    "Initiative command is available only for online DM sessions.",
                    True,
                )
            return
        if self._online_mode == ONLINE_MODE_DM_HOST and self._host_controller is not None:
            self._host_controller.broadcast_chat(actor_name="DM", text=text, system=False)
            return
        if self._online_mode == ONLINE_MODE_PLAYER and self._client_controller is not None:
            if not self._player_network_actions_available():
                self._append_server_log("[WARN] Chat unavailable while disconnected")
                return
            self._client_controller.send_chat(text)
            return
        self._append_chat_message("Local", text, False)

    def _show_network_ping(self, x: float, y: float, dungeon_id: str = "") -> None:
        target_dungeon = str(dungeon_id or "")
        current_dungeon = str(self._active_dungeon_id or "")
        if target_dungeon and current_dungeon and target_dungeon != current_dungeon:
            return
        self._suppress_ping_sync = True
        try:
            self.canvas.show_ping(QPointF(float(x), float(y)), emit_signal=False)
        finally:
            self._suppress_ping_sync = False

    def _on_local_ping_placed(self, scene_pos: QPointF) -> None:
        if self._suppress_ping_sync:
            return
        x = float(scene_pos.x())
        y = float(scene_pos.y())
        dungeon_id = str(self._active_dungeon_id or "")
        if self._online_mode == ONLINE_MODE_DM_HOST and self._host_controller is not None:
            self._host_controller.broadcast_ping(x=x, y=y, dungeon_id=dungeon_id)
            return
        self._dispatch_player_command(
            "ping",
            {"x": x, "y": y, "dungeon_id": dungeon_id},
            silent=True,
        )

    def _on_network_ping_received(self, x: float, y: float, dungeon_id: str) -> None:
        self._show_network_ping(x, y, dungeon_id)

    def _append_chat_message(self, actor_name: str, text: str, system: bool = False) -> None:
        self._chat_panel.append_message(actor_name, text, system)

    def _append_server_log(self, line: str) -> None:
        self._server_log_panel.append_log(line)

    def _update_connected_players(self, players: dict[str, str]) -> None:
        previous_players = {str(player_id) for player_id in self._connected_players.keys()}
        next_players = {str(player_id) for player_id in players.keys()}
        removed_players = previous_players - next_players
        if self._online_mode == ONLINE_MODE_DM_HOST and removed_players:
            for player_id in removed_players:
                self._release_loot_claim_reservations_for_player(player_id)
        self._connected_players = dict(players)
        registry_changed = False
        for player_id, player_name in self._connected_players.items():
            if self._remember_known_player(str(player_id or ""), str(player_name or "")):
                registry_changed = True
        if registry_changed and self._online_mode == ONLINE_MODE_DM_HOST:
            self._collection_meta_dirty = True
            self._refresh_collection_dirty()
            self._save_local_profile()
        self._debug_log("connected_players_updated", count=int(len(self._connected_players)))
        self.inspector.set_player_options(self._connected_players)
        self._seed_initiative_state()
        self._render_initiative_overlay()
        if self._online_mode == ONLINE_MODE_PLAYER:
            self._apply_online_permissions()

    def _ensure_reconnect_status_dialog(self) -> QDialog:
        if self._reconnect_status_dialog is not None:
            return self._reconnect_status_dialog
        dialog = QDialog(self)
        dialog.setModal(False)
        dialog.setWindowTitle("Connection Lost")
        dialog.setMinimumWidth(420)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        label = QLabel(
            "Connection lost. Trying to reconnect...",
            dialog,
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)

        retry_button = QPushButton("Retry Reconnect", dialog)
        retry_button.setObjectName("SecondaryButton")
        retry_button.setMinimumHeight(36)
        retry_button.setMinimumWidth(150)
        retry_button.clicked.connect(self._on_reconnect_dialog_retry_clicked)
        actions.addWidget(retry_button)

        dismiss_button = QPushButton("Dismiss", dialog)
        dismiss_button.setObjectName("SecondaryButton")
        dismiss_button.setMinimumHeight(36)
        dismiss_button.setMinimumWidth(150)
        dismiss_button.clicked.connect(self._hide_reconnect_status_dialog)
        actions.addWidget(dismiss_button)

        layout.addLayout(actions)

        self._reconnect_status_dialog = dialog
        self._reconnect_status_label = label
        self._reconnect_retry_button = retry_button
        self._reconnect_dismiss_button = dismiss_button
        return dialog

    def _refresh_reconnect_status_label(self) -> None:
        label = self._reconnect_status_label
        if label is None:
            return
        base = str(self._reconnect_status_message_base or "").strip() or "Connection lost. Trying to reconnect"
        if not self._reconnect_status_animate:
            label.setText(base)
            return
        dots = "." * max(1, min(3, int(self._reconnect_status_dot_count)))
        label.setText(f"{base}{dots}")

    def _on_reconnect_status_animation_tick(self) -> None:
        if not self._reconnect_status_animate:
            return
        if self._reconnect_status_dialog is not None and not self._reconnect_status_dialog.isVisible():
            self._reconnect_status_anim_timer.stop()
            return
        self._reconnect_status_dot_count = 1 if self._reconnect_status_dot_count >= 3 else self._reconnect_status_dot_count + 1
        self._refresh_reconnect_status_label()

    def _show_reconnect_status_dialog(
        self,
        message: str,
        *,
        allow_retry: bool,
        animate_waiting: bool,
    ) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER:
            return
        dialog = self._ensure_reconnect_status_dialog()
        self._reconnect_status_message_base = str(message or "Connection lost. Trying to reconnect").strip()
        self._reconnect_status_animate = bool(animate_waiting)
        self._reconnect_status_dot_count = 1
        self._refresh_reconnect_status_label()
        retry_button = self._reconnect_retry_button
        if retry_button is not None:
            retry_button.setEnabled(bool(allow_retry))
            retry_button.setText("Retry Reconnect")
        if self._reconnect_status_animate:
            self._reconnect_status_anim_timer.start()
        else:
            self._reconnect_status_anim_timer.stop()
        if not dialog.isVisible():
            dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _hide_reconnect_status_dialog(self) -> None:
        self._reconnect_status_anim_timer.stop()
        self._reconnect_status_animate = False
        self._reconnect_status_message_base = ""
        self._reconnect_status_dot_count = 1
        if self._reconnect_status_dialog is not None:
            self._reconnect_status_dialog.hide()

    def _on_reconnect_dialog_retry_clicked(self) -> None:
        controller = self._client_controller
        if controller is None:
            self._append_server_log("[WARN] Reconnect retry unavailable: no client controller.")
            return
        retry = getattr(controller, "retry_reconnect", None)
        if not callable(retry):
            self._append_server_log("[WARN] Reconnect retry unavailable on this client controller.")
            return
        if not bool(retry()):
            self._append_server_log("[WARN] Manual reconnect retry is not available right now.")

    def _on_client_reconnect_state_changed(self, state: dict) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER:
            return
        status = str((state or {}).get("status") or "").strip().lower()
        attempt = max(0, int((state or {}).get("attempt") or 0))
        max_attempts = max(1, int((state or {}).get("max_attempts") or 1))
        next_delay_ms = max(0, int((state or {}).get("next_delay_ms") or 0))
        manual_retry_available = bool((state or {}).get("manual_retry_available"))

        if status in {"connected", "idle"}:
            self._hide_reconnect_status_dialog()
            return
        if status == "scheduled":
            delay_s = next_delay_ms / 1000.0
            self._show_reconnect_status_dialog(
                (
                    "Connection lost. Trying to reconnect automatically "
                    f"(attempt {attempt}/{max_attempts}) in {delay_s:.1f}s"
                ),
                allow_retry=False,
                animate_waiting=True,
            )
            return
        if status == "attempting":
            self._show_reconnect_status_dialog(
                f"Trying to reconnect now (attempt {attempt}/{max_attempts})",
                allow_retry=False,
                animate_waiting=True,
            )
            return
        if status == "paused":
            self._show_reconnect_status_dialog(
                (
                    "Automatic reconnect attempts are exhausted. "
                    "Press retry to try another reconnect cycle."
                ),
                allow_retry=manual_retry_available,
                animate_waiting=False,
            )
            return
        self._show_reconnect_status_dialog(
            "Connection lost. Trying to reconnect",
            allow_retry=False,
            animate_waiting=True,
        )

    def _redact_player_scene_while_disconnected(self) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER:
            return
        self.inspector.set_entity(None)
        self._initiative_overlay.hide()
        self._initiative_reopen_btn.hide()
        previous_suppress = bool(self._suppress_network_sync)
        self._suppress_network_sync = True
        try:
            self._load_dungeon_state(self._blank_dungeon_state())
        finally:
            self._suppress_network_sync = previous_suppress

    def _on_client_connected(self) -> None:
        self._suppress_client_disconnect_handler = False
        if self._online_mode == ONLINE_MODE_PLAYER:
            self._hide_reconnect_status_dialog()
            self._append_server_log("[INFO] Connected to host")

    @staticmethod
    def _is_name_taken_join_error(message: str) -> bool:
        normalized = str(message or "").strip().casefold()
        return (
            "name already in use" in normalized
            or "choose a different name" in normalized
            or "player name already in use" in normalized
        )

    @staticmethod
    def _is_persistent_id_taken_join_error(message: str) -> bool:
        normalized = str(message or "").strip().casefold()
        return (
            "persistent id already in use" in normalized
            or "this player is already connected" in normalized
        )

    def _retry_join_with_different_player_name(self, reason: str) -> bool:
        if _in_test_env():
            return False
        name_taken = self._is_name_taken_join_error(reason)
        persistent_id_taken = self._is_persistent_id_taken_join_error(reason)
        if not name_taken and not persistent_id_taken:
            return False
        if self._join_retry_prompt_open:
            self._append_server_log(
                "[WARN] Ignoring duplicate join retry prompt while another retry prompt is open."
            )
            return False
        host_ip = str(self._host_ip or "").strip()
        try:
            host_port = int(self._host_port or 0)
        except (TypeError, ValueError):
            host_port = 0
        if not host_ip or host_port <= 0:
            return False
        current_name = str(self._local_player_name or "").strip() or "Player"
        prompt_title = "Player Name In Use"
        prompt = "Player name is already taken. Enter a different name to retry:"
        same_name_prompt = "That name is already in use. Enter a different player name:"
        if persistent_id_taken and not name_taken:
            prompt_title = "Player Already Connected"
            prompt = (
                "This local player identity is already connected.\n"
                "Enter a different player name to join as an additional local player:"
            )
            same_name_prompt = "Enter a different player name to join this session:"
        self._join_retry_prompt_open = True
        try:
            for _attempt in range(5):
                typed, ok = QInputDialog.getText(
                    self,
                    prompt_title,
                    prompt,
                    text=current_name,
                )
                if not ok:
                    return False
                next_name = str(typed or "").strip()
                if not next_name:
                    prompt = "Player name cannot be empty. Enter a different name:"
                    continue
                if next_name.casefold() == current_name.casefold():
                    prompt = same_name_prompt
                    continue
                retry_persistent_player_id = ""
                if persistent_id_taken:
                    retry_persistent_player_id = generate_probabilistic_unique_id("player")
                    self._append_server_log(
                        "[WARN] Existing local player identity is active in another client. "
                        "Retrying with a temporary local identity."
                    )
                self._append_server_log(f"[INFO] Retrying join as '{next_name}'.")

                def _deferred_join(
                    join_host: str = host_ip,
                    join_port: int = host_port,
                    join_name: str = next_name,
                    join_persistent_id: str = retry_persistent_player_id,
                ) -> None:
                    try:
                        if join_persistent_id:
                            self.join_online_session(
                                join_host,
                                join_port,
                                join_name,
                                persistent_player_id=join_persistent_id,
                            )
                            return
                        self.join_online_session(join_host, join_port, join_name)
                    except RuntimeError as exc:
                        self._append_server_log(f"[WARN] Join retry was cancelled: {exc}")

                # Defer the next join attempt to avoid re-entering join teardown from disconnect handlers.
                QTimer.singleShot(0, _deferred_join)
                return True
        finally:
            self._join_retry_prompt_open = False
        return False

    def _on_client_disconnected(self) -> None:
        if self._suppress_client_disconnect_handler:
            self._suppress_client_disconnect_handler = False
            return
        was_ready = bool(self._player_connection_ready)
        was_waiting_for_snapshot = bool(self._awaiting_player_snapshot)
        terminal_disconnect_message = ""
        reconnect_after_established_session = False
        if self._client_controller is not None:
            consume_terminal_message = getattr(
                self._client_controller,
                "consume_terminal_disconnect_message",
                None,
            )
            if callable(consume_terminal_message):
                terminal_disconnect_message = str(consume_terminal_message() or "").strip()
            reconnect_after_established_session = not bool(
                getattr(self._client_controller, "_reconnect_requires_established_session", True)
            )
        self._player_connection_ready = False
        self._awaiting_player_snapshot = False
        if isinstance(self._pending_player_state_update, dict):
            self._pending_player_state_update = None
            self._pending_player_state_update_request_id = ""
            self._append_server_log(
                "[WARN] Dropped pending player state update on disconnect to avoid replaying stale local state after reconnect."
            )
        self._clear_pending_online_command_requests(reason="connection loss")
        pending_claim_ids = [
            str(claim_id)
            for claim_id, pending in self._pending_loot_claim_rollbacks.items()
            if str((pending or {}).get("status") or "").strip() != "awaiting_finalize_ack"
        ]
        for finalize_payload in self._pending_loot_claim_finalizations.values():
            if isinstance(finalize_payload, dict):
                finalize_payload["inflight"] = False
        for claim_id in pending_claim_ids:
            self._rollback_pending_loot_claim(claim_id)
        self._local_player_id = None
        self._update_connected_players({})
        if self._online_mode != ONLINE_MODE_PLAYER:
            return
        should_redact_scene = not (
            isinstance(self._client_controller, ClientSessionController)
            and not reconnect_after_established_session
        )
        if should_redact_scene:
            self._redact_player_scene_while_disconnected()
        else:
            self._apply_online_permissions()
        if terminal_disconnect_message:
            if self._retry_join_with_different_player_name(terminal_disconnect_message):
                return
            self._pending_player_state_update = None
            self._pending_player_state_update_request_id = ""
            self._approved_host_inventory_sync_characters.clear()
            self._append_server_log(f"[WARN] {terminal_disconnect_message}")
            self._append_chat_message("System", terminal_disconnect_message, True)
            self._hide_reconnect_status_dialog()
            self._set_online_mode(ONLINE_MODE_LOCAL_DM)
            return
        if was_waiting_for_snapshot:
            self._append_server_log("[WARN] Disconnected before first snapshot. Waiting for reconnect...")
            self._append_chat_message(
                "System",
                "Connection dropped before the host snapshot arrived. Waiting for reconnect.",
                True,
            )
            self._show_reconnect_status_dialog(
                "Connection dropped before the first snapshot. Trying to reconnect",
                allow_retry=False,
                animate_waiting=True,
            )
            self._apply_online_permissions()
            return
        if not was_ready and not reconnect_after_established_session:
            self._pending_player_state_update = None
            self._pending_player_state_update_request_id = ""
            self._approved_host_inventory_sync_characters.clear()
            if self._client_controller is not None:
                self._client_controller.disconnect()
            self._append_server_log("[WARN] Unable to connect to host. Returned to local mode.")
            self._append_chat_message(
                "System",
                "Unable to connect to host. Check the address, port, player name, or your network connection.",
                True,
            )
            self._hide_reconnect_status_dialog()
            self._set_online_mode(ONLINE_MODE_LOCAL_DM)
            return
        self._append_server_log("[WARN] Disconnected from host. Waiting for reconnect...")
        self._append_chat_message(
            "System",
            "Connection lost. Actions are temporarily disabled until reconnect.",
            True,
        )
        self._show_reconnect_status_dialog(
            "Connection lost. Trying to reconnect automatically",
            allow_retry=False,
            animate_waiting=True,
        )
        self._apply_online_permissions()

    def _on_client_hello_ack(self, player_id: str, resumed: bool = False) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER:
            if self._client_controller is not None:
                self._client_controller.disconnect()
            return
        if self._client_controller is not None:
            if hasattr(self._client_controller, "_session_established"):
                self._client_controller._session_established = True
            if hasattr(self._client_controller, "_reconnect_requires_established_session"):
                self._client_controller._reconnect_requires_established_session = False
        self._local_player_id = player_id
        self._player_connection_ready = False
        self._awaiting_player_snapshot = True
        self._debug_log("client_hello_ack", player_id=str(player_id or ""), resumed=bool(resumed))
        self._append_chat_message(
            "System",
            (
                f"Reconnected as {self._local_player_name}. Waiting for host snapshot..."
                if resumed
                else f"Joined as {self._local_player_name}. Waiting for host snapshot..."
            ),
            True,
        )
        self._apply_online_permissions()

    def _copy_state_payload(self, state: object) -> dict:
        if not isinstance(state, dict):
            return self._blank_dungeon_state()
        try:
            copied = json.loads(json.dumps(state))
        except Exception:
            return self._blank_dungeon_state()
        return copied if isinstance(copied, dict) else self._blank_dungeon_state()

    def _player_visible_initiative_state(self, player_id: str) -> dict:
        base_state = self._initiative_state if isinstance(self._initiative_state, dict) else {}
        raw_players = base_state.get("player_entries")
        visible_players: dict[str, dict] = {}
        if isinstance(raw_players, dict):
            for key, value in raw_players.items():
                if not isinstance(value, dict):
                    continue
                if str(value.get("player_id") or "") != str(player_id or ""):
                    continue
                visible_players[str(key)] = dict(value)
        return {
            "active": bool(base_state.get("active", False)),
            "collapsed": bool(base_state.get("collapsed", False)),
            "player_entries": visible_players,
            "entity_entries": {},
        }

    def _build_online_snapshot(self, for_player_id: str | None = None) -> dict:
        self._save_active_dungeon_state()
        self._initiative_state.setdefault("active", False)
        players_dungeon = self._find_dungeon(self._players_dungeon_id or "")
        if players_dungeon is None:
            players_dungeon = self._current_dungeon()
        players_scene = (
            players_dungeon.get("state")
            if isinstance(players_dungeon, dict)
            else self._blank_dungeon_state()
        )
        players_scene = self._copy_state_payload(players_scene)
        players_dungeon_id = ""
        players_dungeon_name = "Dungeon"
        if isinstance(players_dungeon, dict):
            players_dungeon_id = str(players_dungeon.get("id") or "")
            players_dungeon_name = str(players_dungeon.get("name") or players_dungeon_name)
        if for_player_id:
            players_scene = self._redact_linked_character_payload_for_player(
                players_scene,
                str(for_player_id),
            )
            initiative_state = self._player_visible_initiative_state(str(for_player_id))
            dungeons_payload = [
                {
                    "id": players_dungeon_id,
                    "name": players_dungeon_name,
                    "state": players_scene,
                }
            ]
            active_dungeon_id = players_dungeon_id
        else:
            dungeons_payload = []
            for dungeon in self._dungeons:
                dungeons_payload.append(
                    {
                        "id": str(dungeon.get("id") or ""),
                        "name": str(dungeon.get("name") or "Dungeon"),
                        "state": self._copy_state_payload(dungeon.get("state")),
                    }
                )
            initiative_state = dict(self._initiative_state)
            active_dungeon_id = self._active_dungeon_id
        return {
            "scene": players_scene,
            "active_dungeon_id": active_dungeon_id,
            "players_dungeon_id": players_dungeon_id or self._players_dungeon_id,
            "collection_name": self._collection_name,
            "collection_id": str(self._collection_id or ""),
            "dungeons": dungeons_payload,
            "players": self._connected_players,
            "loot_pool": list(self._session_loot_pool),
            "initiative_state": initiative_state,
        }

    def _redact_linked_character_payload_for_player(self, state: dict, player_id: str) -> dict:
        if not isinstance(state, dict):
            return self._blank_dungeon_state()
        items = state.get("items")
        if not isinstance(items, list):
            return state
        owner_player_id = str(player_id or "").strip()
        for item_data in items:
            if not isinstance(item_data, dict):
                continue
            if item_data.get("type") != "entity":
                continue
            entity_owner = str(item_data.get("owner_player_id") or "").strip()
            if owner_player_id and entity_owner == owner_player_id:
                continue
            # Never expose other players' linked character package payloads.
            item_data["linked_sheet_id"] = ""
            item_data["linked_sheet_name"] = ""
            item_data["linked_character_id"] = ""
            item_data["linked_save_revision"] = 0
            item_data["linked_last_saved_at"] = ""
            item_data["linked_content_hash"] = ""
            item_data["linked_sheet_archive_b64"] = ""
            item_data["linked_inventory"] = normalize_inventory_payload({})
        return state

    def _state_for_scene_signature(self, state: dict) -> dict:
        if not isinstance(state, dict):
            return self._blank_dungeon_state()
        reduced = self._copy_state_payload(state)
        items = reduced.get("items")
        if not isinstance(items, list):
            return reduced
        for item_data in items:
            if not isinstance(item_data, dict):
                continue
            if item_data.get("type") != "entity":
                continue
            # Large linked archives do not affect normal scene-diff decisions and
            # make the host watchdog do unnecessary heavy work every tick.
            item_data["linked_sheet_archive_b64"] = ""
        return reduced

    def _scene_signature(self, state: dict) -> str:
        if not isinstance(state, dict):
            return ""
        try:
            return json.dumps(
                self._state_for_scene_signature(state),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        except Exception:
            return ""

    def _current_players_scene_signature(self) -> str:
        players_id = str(self._players_dungeon_id or "")
        active_id = str(self._active_dungeon_id or "")
        if players_id and active_id and players_id == active_id:
            state = self._serialize_scene()
        else:
            players_dungeon = self._find_dungeon(players_id)
            if players_dungeon is None:
                players_dungeon = self._current_dungeon()
            state = (
                players_dungeon.get("state")
                if isinstance(players_dungeon, dict)
                else self._blank_dungeon_state()
            )
        if not isinstance(state, dict):
            state = self._blank_dungeon_state()
        return self._scene_signature(state)

    def _on_scene_changed_for_online_sync(self, _regions: object = None) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        if self._suppress_change_tracking or self._suppress_network_sync:
            return
        self._host_scene_sync_pending = True
        self._host_scene_sync_timer.start()

    def _refresh_scene_item_references(self, _regions: object = None) -> None:
        # PySide can drop wrappers for Python-defined QGraphicsItems loaded
        # from serialized state unless we keep references on the Python side.
        self._scene_item_refs = list(self.canvas.scene().items())

    def _flush_host_scene_sync(self, *, force: bool = False) -> None:
        if not force and not self._host_scene_sync_pending:
            return
        self._host_scene_sync_pending = False
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        if self._suppress_change_tracking or self._suppress_network_sync:
            return
        current_sig = self._current_players_scene_signature()
        if current_sig and current_sig == self._last_host_scene_signature:
            self._debug_log("host_scene_sync_skip_unchanged")
            return
        self._debug_log("host_scene_sync_flush")
        self._sync_host_scene_icons_for_online()
        self._seed_initiative_state()
        self._render_initiative_overlay()
        self._mark_active_dungeon_dirty()
        self._preview_timer.start()
        self._broadcast_snapshot_if_host()

    def _on_host_scene_watchdog_tick(self) -> None:
        self._flush_host_scene_sync(force=True)

    def _broadcast_snapshot_if_host(self) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        self._normalize_all_dungeon_icons_for_online()
        if self._host_controller is None:
            return
        canonical_scene_signature = self._current_players_scene_signature()
        send_snapshot_to = getattr(self._host_controller, "send_snapshot_to", None)
        players = getattr(self._host_controller, "players", {})
        if callable(send_snapshot_to) and isinstance(players, dict) and players:
            for player_id in list(players.keys()):
                snapshot = self._build_online_snapshot(for_player_id=str(player_id))
                try:
                    send_snapshot_to(str(player_id), snapshot)
                    self._send_snapshot_icon_assets_to_player(str(player_id), snapshot)
                except Exception as exc:
                    self._append_server_log(
                        f"[WARN] Failed to send snapshot to {player_id}: {exc}"
                    )
                    continue
            self._last_host_scene_signature = canonical_scene_signature
            return
        snapshot = self._build_online_snapshot()
        self._last_host_scene_signature = canonical_scene_signature
        broadcast_snapshot = getattr(self._host_controller, "broadcast_snapshot", None)
        if not callable(broadcast_snapshot):
            return
        try:
            broadcast_snapshot(snapshot)
        except Exception as exc:
            self._append_server_log(f"[WARN] Failed to broadcast snapshot: {exc}")

    def _on_host_snapshot_requested(self, player_id: str) -> None:
        if self._host_controller is None:
            return
        self._normalize_all_dungeon_icons_for_online()
        snapshot = self._build_online_snapshot(for_player_id=player_id)
        try:
            self._host_controller.send_snapshot_to(player_id, snapshot)
            self._send_snapshot_icon_assets_to_player(player_id, snapshot)
        except Exception as exc:
            self._append_server_log(f"[WARN] Failed to serve snapshot request: {exc}")

    def _iter_snapshot_icon_assets(self, snapshot: dict) -> list[tuple[str, str]]:
        assets: list[tuple[str, str]] = []
        dungeons_payload = snapshot.get("dungeons")
        if not isinstance(dungeons_payload, list):
            dungeons_payload = []
        for dungeon_entry in dungeons_payload:
            if not isinstance(dungeon_entry, dict):
                continue
            dungeon_state = dungeon_entry.get("state")
            if not isinstance(dungeon_state, dict):
                continue
            items = dungeon_state.get("items")
            if not isinstance(items, list):
                continue
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                entity_id = str(item_data.get("entity_id") or "")
                icon_ref = str(item_data.get("icon_path") or "")
                if not entity_id or not icon_ref.startswith(SESSION_ICON_PREFIX):
                    continue
                cache_name = icon_ref[len(SESSION_ICON_PREFIX) :]
                safe_cache_name = _sanitize_filename(Path(cache_name).name, "")
                if not safe_cache_name:
                    continue
                assets.append((entity_id, safe_cache_name))
        return assets

    def _send_snapshot_icon_assets_to_player(self, player_id: str, snapshot: dict) -> None:
        if self._host_controller is None:
            return
        sent_keys: set[tuple[str, str]] = set()
        for entity_id, cache_name in self._iter_snapshot_icon_assets(snapshot):
            dedupe_key = (entity_id, cache_name)
            if dedupe_key in sent_keys:
                continue
            sent_keys.add(dedupe_key)
            cache_path = online_icon_cache_dir(self._active_online_runtime_cache_id()) / cache_name
            if not cache_path.exists():
                continue
            try:
                raw = cache_path.read_bytes()
            except Exception:
                continue
            if not raw or len(raw) > 2 * 1024 * 1024:
                continue
            self._host_controller.send_icon_asset(
                player_id,
                entity_id=entity_id,
                filename=cache_name,
                content_b64=base64.b64encode(raw).decode("ascii"),
            )

    def _on_host_command_received(self, player_id: str, message: dict) -> None:
        if self._host_controller is None:
            return
        request_id = message.get("request_id")
        action = str(message.get("action") or "")
        payload = message.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        if action == "upload_icon":
            self._handle_uploaded_icon(player_id, payload, request_id=request_id)
            return
        decision = authorize_command(
            role=OnlineRole.PLAYER,
            action=action,
            actor_id=player_id,
        )
        if not decision.allowed:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message=decision.reason,
                request_id=request_id,
            )
            return

        if action == "ping":
            try:
                x = float(payload.get("x"))
                y = float(payload.get("y"))
            except (TypeError, ValueError):
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message="Invalid ping coordinates",
                    request_id=request_id,
                )
                return
            allowed_dungeon_id = self._player_action_dungeon_id()
            dungeon_id = str(payload.get("dungeon_id") or "").strip()
            if not dungeon_id:
                dungeon_id = allowed_dungeon_id
            if allowed_dungeon_id and dungeon_id and dungeon_id != allowed_dungeon_id:
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message="Players can only ping in the assigned players dungeon.",
                    request_id=request_id,
                )
                return
            self._show_network_ping(x, y, dungeon_id)
            self._host_controller.broadcast_ping(
                x=x,
                y=y,
                dungeon_id=dungeon_id,
                sender_player_id=player_id,
            )
            self._host_controller.send_command_result(
                player_id,
                ok=True,
                message="Ping sent",
                request_id=request_id,
            )
            return

        if action == "state_update":
            state = payload.get("state")
            if not isinstance(state, dict):
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message="Invalid state payload",
                    request_id=request_id,
                    data={"action": "state_update"},
                )
                return
            allowed_dungeon_id = str(self._players_dungeon_id or self._active_dungeon_id or "")
            target_dungeon_id = str(payload.get("dungeon_id") or allowed_dungeon_id)
            if allowed_dungeon_id and target_dungeon_id != allowed_dungeon_id:
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message="Players can only update the assigned players dungeon",
                    request_id=request_id,
                    data={"action": "state_update"},
                )
                return
            target_dungeon = self._find_dungeon(target_dungeon_id)
            if target_dungeon is None:
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message="Target dungeon not found",
                    request_id=request_id,
                    data={"action": "state_update"},
                )
                return
            changed = self._apply_player_state_update(
                player_id=player_id,
                target_dungeon=target_dungeon,
                incoming_state=state,
            )
            self._host_controller.send_command_result(
                player_id,
                ok=True,
                message="State merged" if changed else "No owned entity changes detected",
                request_id=request_id,
                data={"action": "state_update"},
            )
            if changed:
                self._broadcast_snapshot_if_host()
            return

        if action == "sync_character_inventory":
            self._handle_host_sync_character_inventory(player_id, payload, request_id=request_id)
            return

        if action == "link_character_entity":
            self._handle_host_link_character_entity(player_id, payload, request_id=request_id)
            return

        if action == "unlink_character_entity":
            self._handle_host_unlink_character_entity(player_id, payload, request_id=request_id)
            return

        if action == "resolve_linked_character_conflict":
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Linked character conflict resolution is no longer supported.",
                request_id=request_id,
                data={"action": "resolve_linked_character_conflict"},
            )
            return

        if action == "claim_loot":
            self._handle_host_claim_loot(player_id, payload, request_id=request_id)
            return

        if action == "add_loot_from_inventory":
            self._handle_host_add_loot_from_inventory(player_id, payload, request_id=request_id)
            return

        if action == "claim_loot_finalize":
            self._handle_host_finalize_loot_claim(player_id, payload, request_id=request_id)
            return

        if action == "initiative_update":
            self._handle_host_initiative_update(player_id, payload, request_id=request_id)
            return

        self._host_controller.send_command_result(
            player_id,
            ok=False,
            message=f"Unknown action: {action}",
            request_id=request_id,
        )

    def _merge_player_owned_entity_state(self, current: dict, incoming: dict) -> dict:
        merged = dict(current)
        int_fields = {
            "hp",
            "max_hp",
            "ac",
            "strength",
            "dexterity",
            "constitution",
            "intelligence",
            "wisdom",
            "charisma",
            "size_w_cells",
            "size_h_cells",
        }
        # Player state updates must not overwrite host-side icon file paths.
        str_fields = {"color", "actions", "description", "label", "layer"}
        bool_fields = {"lock_square"}
        float_fields = {"z"}

        pos_value = incoming.get("pos")
        if (
            isinstance(pos_value, (list, tuple))
            and len(pos_value) >= 2
        ):
            try:
                merged["pos"] = [float(pos_value[0]), float(pos_value[1])]
            except (TypeError, ValueError):
                pass

        for field in int_fields:
            if field not in incoming:
                continue
            try:
                merged[field] = int(incoming.get(field))
            except (TypeError, ValueError):
                continue
        for field in float_fields:
            if field not in incoming:
                continue
            try:
                merged[field] = float(incoming.get(field))
            except (TypeError, ValueError):
                continue
        for field in str_fields:
            if field in incoming:
                merged[field] = str(incoming.get(field) or "")
        for field in bool_fields:
            if field in incoming:
                merged[field] = bool(incoming.get(field))

        return merged

    def _stroke_sync_key(self, item_data: dict) -> str:
        stroke_id = str(item_data.get("stroke_id") or item_data.get("entity_id") or "").strip()
        if stroke_id:
            return f"id:{stroke_id}"
        payload = {
            "path": item_data.get("path"),
            "pos": item_data.get("pos"),
            "layer": item_data.get("layer"),
            "pen_color": item_data.get("pen_color"),
            "pen_width": item_data.get("pen_width"),
        }
        try:
            serialized = json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except Exception:
            serialized = str(payload)
        digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return f"legacy:{digest}"

    def _normalize_incoming_player_stroke(self, incoming_item: dict, *, player_id: str) -> dict | None:
        if not isinstance(incoming_item, dict):
            return None
        if incoming_item.get("type") != "stroke":
            return None
        owner_player_id = str(incoming_item.get("owner_player_id") or "").strip()
        if owner_player_id != str(player_id or ""):
            return None
        path_data = incoming_item.get("path")
        if not isinstance(path_data, list) or not path_data:
            return None
        normalized = dict(incoming_item)
        stroke_id = str(normalized.get("stroke_id") or normalized.get("entity_id") or "").strip()
        if not stroke_id:
            stroke_id = uuid.uuid4().hex
        normalized["stroke_id"] = stroke_id
        normalized["owner_player_id"] = owner_player_id
        normalized["type"] = "stroke"
        normalized["pen_color"] = str(normalized.get("pen_color") or WALL_COLOR)
        try:
            normalized["pen_width"] = float(normalized.get("pen_width") or 1.0)
        except (TypeError, ValueError):
            normalized["pen_width"] = 1.0
        try:
            normalized["z"] = float(normalized.get("z", _default_item_z("stroke", normalized.get("layer", LAYER_FG))))
        except (TypeError, ValueError):
            normalized["z"] = _default_item_z("stroke", normalized.get("layer", LAYER_FG))
        pos = normalized.get("pos")
        if isinstance(pos, (list, tuple)) and len(pos) >= 2:
            try:
                normalized["pos"] = [float(pos[0]), float(pos[1])]
            except (TypeError, ValueError):
                normalized["pos"] = [0.0, 0.0]
        else:
            normalized["pos"] = [0.0, 0.0]
        normalized.setdefault("layer", LAYER_FG)
        return normalized

    def _apply_player_state_update(
        self,
        *,
        player_id: str,
        target_dungeon: dict,
        incoming_state: dict,
    ) -> bool:
        target_state = target_dungeon.get("state")
        if not isinstance(target_state, dict):
            target_state = self._blank_dungeon_state()
        source_items = target_state.get("items")
        incoming_items = incoming_state.get("items")
        if not isinstance(source_items, list) or not isinstance(incoming_items, list):
            return False

        incoming_entities: dict[str, dict] = {}
        incoming_player_strokes: dict[str, dict] = {}
        for incoming_item in incoming_items:
            if not isinstance(incoming_item, dict):
                continue
            item_type = str(incoming_item.get("type") or "")
            if item_type == "entity":
                entity_id = str(incoming_item.get("entity_id") or "")
                if not entity_id:
                    continue
                incoming_entities[entity_id] = incoming_item
                continue
            if item_type != "stroke":
                continue
            normalized_stroke = self._normalize_incoming_player_stroke(
                incoming_item,
                player_id=player_id,
            )
            if normalized_stroke is None:
                continue
            incoming_player_strokes[self._stroke_sync_key(normalized_stroke)] = normalized_stroke

        updated_items: list[object] = []
        changed = False
        player_id_text = str(player_id or "")
        for source_item in source_items:
            if not isinstance(source_item, dict):
                updated_items.append(source_item)
                continue
            item_copy = dict(source_item)
            item_type = str(item_copy.get("type") or "")
            if item_type == "stroke":
                if str(item_copy.get("owner_player_id") or "") != player_id_text:
                    updated_items.append(item_copy)
                    continue
                stroke_key = self._stroke_sync_key(item_copy)
                incoming_stroke = incoming_player_strokes.pop(stroke_key, None)
                if incoming_stroke is None:
                    changed = True
                    continue
                updated_items.append(incoming_stroke)
                if incoming_stroke != item_copy:
                    changed = True
                continue
            if item_type != "entity":
                updated_items.append(item_copy)
                continue
            if str(item_copy.get("owner_player_id") or "") != player_id_text:
                updated_items.append(item_copy)
                continue
            entity_id = str(item_copy.get("entity_id") or "")
            if not entity_id:
                updated_items.append(item_copy)
                continue
            incoming_entity = incoming_entities.get(entity_id)
            if not isinstance(incoming_entity, dict):
                updated_items.append(item_copy)
                continue
            merged = self._merge_player_owned_entity_state(item_copy, incoming_entity)
            updated_items.append(merged)
            if merged != item_copy:
                changed = True

        if incoming_player_strokes:
            changed = True
            for stroke_key in sorted(incoming_player_strokes.keys()):
                updated_items.append(incoming_player_strokes[stroke_key])

        if not changed:
            return False

        target_dungeon["state"] = {
            **target_state,
            "items": updated_items,
        }
        target_dungeon["dirty"] = True
        target_dungeon["preview"] = None
        target_dungeon["preview_signature"] = None
        self._suppress_network_sync = True
        try:
            if str(target_dungeon.get("id") or "") == str(self._active_dungeon_id or ""):
                self._load_dungeon_state(target_dungeon["state"])
        finally:
            self._suppress_network_sync = False
        self._refresh_collection_dirty()
        self._refresh_dungeon_list(preserve_selection=True)
        return True

    def _remove_player_from_host_session(self, player_id: str, *, reason: str) -> None:
        if self._host_controller is None:
            return
        disconnect_player = getattr(self._host_controller, "disconnect_player", None)
        if callable(disconnect_player):
            disconnect_player(player_id, message=str(reason or "Removed from host."))
            return
        kick_player = getattr(self._host_controller, "kick_player", None)
        if callable(kick_player):
            kick_player(player_id, message=str(reason or "Removed from host."))
            return
        self._append_server_log(
            f"[WARN] Unable to remove player '{player_id}': no disconnect helper on host controller."
        )

    def _handle_host_sync_character_inventory(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        sheet_id = str(payload.get("sheet_id") or "").strip()
        character_id = str(payload.get("character_id") or "").strip()
        claim_id = str(payload.get("claim_id") or "").strip()
        claim_result_data = (
            {
                "action": "sync_character_inventory",
                "claim_id": claim_id,
            }
            if claim_id
            else None
        )
        try:
            save_revision = max(0, int(payload.get("save_revision") or 0))
        except (TypeError, ValueError):
            save_revision = 0
        last_saved_at = str(payload.get("last_saved_at") or "").strip()
        content_hash = str(payload.get("content_hash") or "").strip()
        archive_ok, archive_b64, archive_bytes = self._validate_archive_payload(
            str(payload.get("archive_b64") or "")
        )
        archive_supplied = "archive_b64" in payload
        inventory_payload = payload.get("inventory")
        stats_payload = payload.get("stats") if isinstance(payload.get("stats"), dict) else {}
        if not sheet_id or not isinstance(inventory_payload, dict):
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Invalid inventory sync payload",
                request_id=request_id,
                data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
            )
            return
        if not archive_ok:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Linked character archive payload is invalid.",
                request_id=request_id,
                data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
            )
            return
        allowed_dungeon_id = self._player_action_dungeon_id()
        if not character_id:
            linked_sheet_entries = self._linked_entity_state_entries_for_sheet(
                player_id=player_id,
                sheet_id=sheet_id,
                dungeon_id=allowed_dungeon_id,
            )
            if linked_sheet_entries:
                _linked_dungeon, linked_item_data = linked_sheet_entries[0]
                character_id = str(linked_item_data.get("linked_character_id") or "").strip()
        if not character_id:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Character sync requires a character id.",
                request_id=request_id,
                data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
            )
            return
        if not self._player_owns_linked_character(
            player_id,
            sheet_id,
            character_id,
            dungeon_id=allowed_dungeon_id,
        ):
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message=(
                    "Character sync target is not linked to one of your owned entities "
                    "in the assigned players dungeon."
                ),
                request_id=request_id,
                data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
            )
            return
        if claim_id:
            claim = self._loot_claim_reservations.get(claim_id)
            if (
                isinstance(claim, dict)
                and str(claim.get("player_id") or "").strip() == str(player_id or "").strip()
            ):
                claim["hold_open"] = True
                self._loot_claim_reservations[claim_id] = claim

        linked_entries = self._linked_entity_state_entries_for_character(
            player_id=player_id,
            character_id=character_id,
            sheet_id=sheet_id,
            dungeon_id=allowed_dungeon_id,
        )
        if linked_entries:
            _conflict_dungeon, host_item_data = linked_entries[0]
            fallback_archive_b64 = str(host_item_data.get("linked_sheet_archive_b64") or "").strip()
            if not fallback_archive_b64:
                for _other_dungeon, other_item_data in linked_entries:
                    candidate_archive_b64 = str(
                        other_item_data.get("linked_sheet_archive_b64") or ""
                    ).strip()
                    if candidate_archive_b64:
                        fallback_archive_b64 = candidate_archive_b64
                        break
            metadata_ok, archive_b64, content_hash, metadata_message = self._validated_linked_character_sync_metadata(
                character_id=character_id,
                inventory_payload=inventory_payload,
                incoming_content_hash=content_hash,
                archive_b64=archive_b64,
                archive_bytes=archive_bytes,
                fallback_archive_b64=fallback_archive_b64,
                archive_required=True,
            )
            if not metadata_ok:
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message=metadata_message,
                    request_id=request_id,
                    data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
                )
                return
            if self._host_should_reject_stale_inventory_sync(
                host_item_data=host_item_data,
                incoming_inventory=inventory_payload,
                incoming_save_revision=save_revision,
                incoming_content_hash=content_hash,
            ):
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message=(
                        "Host has newer linked character data. "
                        "Pull the latest host state and retry."
                    ),
                    request_id=request_id,
                    data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
                )
                return
        else:
            metadata_ok, archive_b64, content_hash, metadata_message = self._validated_linked_character_sync_metadata(
                character_id=character_id,
                inventory_payload=inventory_payload,
                incoming_content_hash=content_hash,
                archive_b64=archive_b64,
                archive_bytes=archive_bytes,
                archive_required=True,
            )
            if not metadata_ok:
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message=metadata_message,
                    request_id=request_id,
                    data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
                )
                return

        existing_inventory = {}
        sheet_name_for_review = sheet_id
        if linked_entries:
            _first_linked_dungeon, first_linked_item = linked_entries[0]
            if isinstance(first_linked_item, dict):
                existing_inventory = normalize_inventory_payload(
                    first_linked_item.get("linked_inventory") or {}
                )
                sheet_name_for_review = (
                    str(first_linked_item.get("linked_sheet_name") or sheet_id).strip()
                    or sheet_id
                )
        unknown_status, resolved_payload, unknown_status_note = self._resolve_unknown_linked_items_for_host(
            player_id=player_id,
            character_id=character_id,
            sheet_name=sheet_name_for_review,
            inventory_payload=inventory_payload,
            existing_inventory=existing_inventory,
        )
        if unknown_status == "kick":
            reason = unknown_status_note or "DM rejected unknown linked items and removed the player."
            self._remove_player_from_host_session(player_id, reason=reason)
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message=reason,
                request_id=request_id,
                data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
            )
            return
        if unknown_status != "ok":
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message=unknown_status_note or "Linked item review is unresolved.",
                request_id=request_id,
                data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
            )
            return
        authoritative_payload = normalize_inventory_payload(resolved_payload)
        updated = self._apply_inventory_sync_to_linked_entities(
            owner_player_id=player_id,
            character_id=character_id,
            inventory_payload=authoritative_payload,
            save_revision=save_revision,
            last_saved_at=last_saved_at,
            content_hash=content_hash,
            stats=stats_payload,
            archive_b64=archive_b64,
        )
        if unknown_status_note:
            self._append_server_log(f"[INFO] {unknown_status_note}")
        self._host_controller.send_command_result(
            player_id,
            ok=True,
            message=f"Synced inventory to {updated} linked entit(y/ies)",
            request_id=request_id,
            data=dict(claim_result_data) if isinstance(claim_result_data, dict) else None,
        )
        if updated > 0:
            self._review_active_unknown_linked_items_for_dm(
                player_id=player_id,
                character_id=character_id,
                sheet_name=sheet_id,
                inventory_payload=authoritative_payload,
            )
            self._broadcast_snapshot_if_host()

    def _handle_host_link_character_entity(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
        result_data: dict | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        def _send_link_result(
            *,
            ok: bool,
            message: str,
            data: dict | None = None,
        ) -> None:
            response_data = dict(result_data) if isinstance(result_data, dict) else {}
            if isinstance(data, dict):
                response_data.update(data)
            response_data.setdefault("action", "link_character_entity")
            self._host_controller.send_command_result(
                player_id,
                ok=ok,
                message=message,
                request_id=request_id,
                data=response_data,
            )
        entity_id = str(payload.get("entity_id") or "").strip()
        sheet_id = str(payload.get("sheet_id") or "").strip()
        sheet_name = str(payload.get("sheet_name") or sheet_id).strip() or sheet_id
        character_id = str(payload.get("character_id") or "").strip()
        try:
            save_revision = max(0, int(payload.get("save_revision") or 0))
        except (TypeError, ValueError):
            save_revision = 0
        last_saved_at = str(payload.get("last_saved_at") or "").strip()
        content_hash = str(payload.get("content_hash") or "").strip()
        archive_ok, archive_b64, archive_bytes = self._validate_archive_payload(
            str(payload.get("archive_b64") or "")
        )
        archive_supplied = "archive_b64" in payload
        allowed_dungeon_id = self._player_action_dungeon_id()
        dungeon_id = str(payload.get("dungeon_id") or "").strip()
        if not dungeon_id:
            dungeon_id = allowed_dungeon_id
        if allowed_dungeon_id and dungeon_id and dungeon_id != allowed_dungeon_id:
            _send_link_result(
                ok=False,
                message="Players can only link characters in the assigned players dungeon.",
            )
            return
        stats = payload.get("stats")
        inventory = payload.get("inventory")
        if not entity_id or not sheet_id or not isinstance(stats, dict) or not isinstance(inventory, dict):
            _send_link_result(ok=False, message="Invalid link payload")
            return
        if not archive_ok:
            _send_link_result(
                ok=False,
                message="Linked character archive payload is invalid.",
            )
            return

        dungeon, item_data = self._find_entity_state_entry(entity_id, dungeon_id)
        if dungeon is None or item_data is None:
            _send_link_result(ok=False, message="Target entity not found")
            return
        if str(item_data.get("owner_player_id") or "").strip() != player_id:
            _send_link_result(ok=False, message="Entity owned by different player")
            return
        existing_sheet_id = str(item_data.get("linked_sheet_id") or "").strip()
        existing_character_id = str(item_data.get("linked_character_id") or "").strip()
        if not character_id:
            for other_dungeon in self._dungeons:
                state = other_dungeon.get("state")
                if not isinstance(state, dict):
                    continue
                items = state.get("items")
                if not isinstance(items, list):
                    continue
                for other_item in items:
                    if not isinstance(other_item, dict):
                        continue
                    if other_item.get("type") != "entity":
                        continue
                    if str(other_item.get("entity_id") or "").strip() == entity_id:
                        continue
                    if str(other_item.get("owner_player_id") or "").strip() != player_id:
                        continue
                    if str(other_item.get("linked_sheet_id") or "").strip() != sheet_id:
                        continue
                    character_id = str(other_item.get("linked_character_id") or "").strip()
                    if character_id:
                        break
                if character_id:
                    break

        duplicate_link_found = False
        for other_dungeon in self._dungeons:
            state = other_dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            for other_item in items:
                if not isinstance(other_item, dict):
                    continue
                if other_item.get("type") != "entity":
                    continue
                if str(other_item.get("entity_id") or "").strip() == entity_id:
                    continue
                other_owner = str(other_item.get("owner_player_id") or "").strip()
                if not other_owner:
                    continue
                if other_owner == player_id:
                    continue
                if character_id:
                    if str(other_item.get("linked_character_id") or "").strip() != character_id:
                        continue
                else:
                    if str(other_item.get("linked_sheet_id") or "").strip() != sheet_id:
                        continue
                duplicate_link_found = True
                break
            if duplicate_link_found:
                break
        if duplicate_link_found:
            _send_link_result(
                ok=False,
                message="That character is already actively assigned to another player-owned entity.",
            )
            return

        normalized_inventory = normalize_inventory_payload(inventory)
        resolved_character_id = (
            str(character_id or "").strip()
            or existing_character_id
            or _generate_probabilistic_unique_id("character")
        )
        fallback_archive_b64 = str(item_data.get("linked_sheet_archive_b64") or "").strip()
        if not fallback_archive_b64:
            matching_entries = self._linked_entity_state_entries_for_character(
                player_id=player_id,
                character_id=resolved_character_id,
                sheet_id=sheet_id,
                dungeon_id=allowed_dungeon_id,
            )
            for _other_dungeon, other_item_data in matching_entries:
                candidate_archive_b64 = str(
                    other_item_data.get("linked_sheet_archive_b64") or ""
                ).strip()
                if candidate_archive_b64:
                    fallback_archive_b64 = candidate_archive_b64
                    break
        metadata_ok, archive_b64, content_hash, metadata_message = self._validated_linked_character_sync_metadata(
            character_id=resolved_character_id,
            inventory_payload=normalized_inventory,
            incoming_content_hash=content_hash,
            archive_b64=archive_b64,
            archive_bytes=archive_bytes,
            fallback_archive_b64=fallback_archive_b64,
            archive_required=bool(archive_supplied),
        )
        if not metadata_ok:
            _send_link_result(ok=False, message=metadata_message)
            return
        unknown_status, resolved_payload, unknown_status_note = self._resolve_unknown_linked_items_for_host(
            player_id=player_id,
            character_id=resolved_character_id,
            sheet_name=sheet_name,
            inventory_payload=normalized_inventory,
            existing_inventory=normalize_inventory_payload(item_data.get("linked_inventory") or {}),
        )
        if unknown_status == "kick":
            reason = unknown_status_note or "DM rejected unknown linked items and removed the player."
            self._remove_player_from_host_session(player_id, reason=reason)
            _send_link_result(ok=False, message=reason)
            return
        if unknown_status != "ok":
            _send_link_result(
                ok=False,
                message=unknown_status_note or "Linked item review is unresolved.",
            )
            return
        normalized_inventory = normalize_inventory_payload(resolved_payload)
        label, max_hp, hp, ac, abilities = self._normalized_linked_stats(stats, fallback_name=sheet_name)
        item_data["linked_sheet_id"] = sheet_id
        item_data["linked_sheet_name"] = sheet_name
        item_data["linked_character_id"] = resolved_character_id
        item_data["linked_save_revision"] = save_revision
        item_data["linked_last_saved_at"] = last_saved_at
        item_data["linked_content_hash"] = content_hash
        item_data["linked_inventory"] = dict(normalized_inventory)
        item_data["linked_sheet_archive_b64"] = archive_b64
        if label:
            item_data["label"] = label
        if max_hp is not None:
            item_data["max_hp"] = int(max_hp)
        if hp is not None:
            item_data["hp"] = int(hp)
        if ac is not None:
            item_data["ac"] = int(ac)
        for stat_key, stat_value in abilities.items():
            item_data[stat_key] = int(stat_value)

        if isinstance(dungeon, dict):
            dungeon["dirty"] = True
            dungeon["preview"] = None
            dungeon["preview_signature"] = None

        target_entity = self._find_entity_by_id(entity_id)
        if isinstance(target_entity, EntityItem):
            self._apply_character_link_to_entity(
                target_entity,
                sheet_id=sheet_id,
                sheet_name=sheet_name,
                character_id=str(item_data.get("linked_character_id") or ""),
                save_revision=int(item_data.get("linked_save_revision") or 0),
                last_saved_at=str(item_data.get("linked_last_saved_at") or ""),
                content_hash=str(item_data.get("linked_content_hash") or ""),
                linked_inventory=normalized_inventory,
                stats=stats,
                archive_b64=str(item_data.get("linked_sheet_archive_b64") or ""),
            )
            target_entity.update()
            if getattr(self.inspector, "_entity", None) is target_entity:
                self.inspector.set_entity(target_entity)

        success_data = dict(result_data) if isinstance(result_data, dict) else {}
        success_data.setdefault("action", "link_character_entity")
        success_data.setdefault("entity_id", entity_id)
        success_data.setdefault("character_id", resolved_character_id)
        success_data.setdefault("sheet_id", sheet_id)
        success_data.setdefault("sheet_name", sheet_name)
        success_data.setdefault("save_revision", int(item_data.get("linked_save_revision") or 0))
        success_data.setdefault("last_saved_at", str(item_data.get("linked_last_saved_at") or ""))
        success_data.setdefault("content_hash", str(item_data.get("linked_content_hash") or ""))
        success_data.setdefault("inventory", normalize_inventory_payload(item_data.get("linked_inventory") or {}))
        success_data.setdefault("stats", dict(stats))
        success_data.setdefault("archive_b64", str(item_data.get("linked_sheet_archive_b64") or ""))
        self._host_controller.send_command_result(
            player_id,
            ok=True,
            message="Linked character synced",
            request_id=request_id,
            data=success_data,
        )
        if unknown_status_note:
            self._append_server_log(f"[INFO] {unknown_status_note}")
        self._review_active_unknown_linked_items_for_dm(
            player_id=player_id,
            character_id=resolved_character_id,
            sheet_name=sheet_name,
            inventory_payload=normalized_inventory,
        )
        if self._online_mode != ONLINE_MODE_PLAYER:
            self._cleanup_unlinked_managed_character_artifacts()
        self._broadcast_snapshot_if_host()

    def _handle_host_unlink_character_entity(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        def _send_unlink_result(
            *,
            ok: bool,
            message: str,
            data: dict | None = None,
        ) -> None:
            response_data = dict(data) if isinstance(data, dict) else {}
            response_data.setdefault("action", "unlink_character_entity")
            self._host_controller.send_command_result(
                player_id,
                ok=ok,
                message=message,
                request_id=request_id,
                data=response_data,
            )
        entity_id = str(payload.get("entity_id") or "").strip()
        allowed_dungeon_id = self._player_action_dungeon_id()
        dungeon_id = str(payload.get("dungeon_id") or "").strip() or allowed_dungeon_id
        if allowed_dungeon_id and dungeon_id and dungeon_id != allowed_dungeon_id:
            _send_unlink_result(
                ok=False,
                message="Players can only unlink characters in the assigned players dungeon.",
            )
            return
        if not entity_id:
            _send_unlink_result(ok=False, message="Invalid unlink payload")
            return
        dungeon, item_data = self._find_entity_state_entry(entity_id, dungeon_id)
        if dungeon is None or item_data is None:
            _send_unlink_result(ok=False, message="Target entity not found")
            return
        if str(item_data.get("owner_player_id") or "").strip() != player_id:
            _send_unlink_result(ok=False, message="Entity owned by different player")
            return
        cleared_character_id = str(item_data.get("linked_character_id") or "").strip()
        cleared_sheet_id = str(item_data.get("linked_sheet_id") or "").strip()
        if not cleared_character_id and not cleared_sheet_id:
            _send_unlink_result(
                ok=True,
                message="Entity is already unlinked",
                data={
                    "entity_id": entity_id,
                    "character_id": "",
                    "sheet_id": "",
                },
            )
            return

        self._clear_character_link_state_payload(item_data)
        if isinstance(dungeon, dict):
            dungeon["dirty"] = True
            dungeon["preview"] = None
            dungeon["preview_signature"] = None

        target_entity = self._find_entity_by_id(entity_id)
        if isinstance(target_entity, EntityItem):
            self._clear_character_link_from_entity(target_entity)
            target_entity.update()
            if getattr(self.inspector, "_entity", None) is target_entity:
                self.inspector.set_linked_character_info("")
                self.inspector.set_entity(target_entity)

        _send_unlink_result(
            ok=True,
            message="Character unlinked",
            data={
                "entity_id": entity_id,
                "character_id": cleared_character_id,
                "sheet_id": cleared_sheet_id,
            },
        )
        if self._online_mode != ONLINE_MODE_PLAYER:
            self._cleanup_unlinked_managed_character_artifacts()
        self._broadcast_snapshot_if_host()

    def _handle_host_resolve_linked_character_conflict(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        self._host_controller.send_command_result(
            player_id,
            ok=False,
            message="Linked character conflict resolution is no longer supported.",
            request_id=request_id,
            data={"action": "resolve_linked_character_conflict"},
        )

    def _player_action_dungeon_id(self) -> str:
        return str(self._players_dungeon_id or self._active_dungeon_id or "").strip()

    def _player_has_linked_sheet(self, player_id: str, sheet_id: str) -> bool:
        return self._player_has_linked_sheet_in_dungeon(
            player_id,
            sheet_id,
            dungeon_id="",
        )

    def _player_has_linked_sheet_in_dungeon(
        self,
        player_id: str,
        sheet_id: str,
        *,
        dungeon_id: str = "",
    ) -> bool:
        clean_sheet = str(sheet_id or "").strip()
        clean_player = str(player_id or "").strip()
        if not clean_sheet or not clean_player:
            return False
        return bool(
            self._linked_entity_state_entries_for_sheet(
                player_id=clean_player,
                sheet_id=clean_sheet,
                dungeon_id=dungeon_id,
            )
        )

    def _player_owns_linked_character(
        self,
        player_id: str,
        sheet_id: str,
        character_id: str,
        *,
        dungeon_id: str = "",
    ) -> bool:
        clean_player = str(player_id or "").strip()
        clean_sheet = str(sheet_id or "").strip()
        clean_character = str(character_id or "").strip()
        if not clean_player or not clean_sheet or not clean_character:
            return False
        return bool(
            self._linked_entity_state_entries_for_character(
                player_id=clean_player,
                character_id=clean_character,
                sheet_id=clean_sheet,
                dungeon_id=dungeon_id,
            )
        )

    def _linked_inventory_payload_for_player_sheet(
        self,
        *,
        player_id: str,
        sheet_id: str,
        dungeon_id: str = "",
    ) -> dict | None:
        clean_sheet = str(sheet_id or "").strip()
        clean_player = str(player_id or "").strip()
        if not clean_sheet or not clean_player:
            return None
        linked_entries = self._linked_entity_state_entries_for_sheet(
            player_id=clean_player,
            sheet_id=clean_sheet,
            dungeon_id=dungeon_id,
        )
        if linked_entries:
            _linked_dungeon, item_data = linked_entries[0]
            linked_inventory = item_data.get("linked_inventory")
            if isinstance(linked_inventory, dict):
                return normalize_inventory_payload(linked_inventory)
            return normalize_inventory_payload({})
        return None

    def _linked_entity_state_entries_for_sheet(
        self,
        *,
        player_id: str,
        sheet_id: str,
        dungeon_id: str = "",
    ) -> list[tuple[dict, dict]]:
        clean_player = str(player_id or "").strip()
        clean_sheet = str(sheet_id or "").strip()
        clean_dungeon = str(dungeon_id or "").strip()
        if not clean_player or not clean_sheet:
            return []
        matches: list[tuple[dict, dict]] = []
        for dungeon in self._dungeons:
            if clean_dungeon and str(dungeon.get("id") or "").strip() != clean_dungeon:
                continue
            state = dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                if str(item_data.get("owner_player_id") or "").strip() != clean_player:
                    continue
                if str(item_data.get("linked_sheet_id") or "").strip() != clean_sheet:
                    continue
                matches.append((dungeon, item_data))
        return matches

    def _linked_entity_state_entries_for_character(
        self,
        *,
        player_id: str,
        character_id: str,
        sheet_id: str = "",
        dungeon_id: str = "",
    ) -> list[tuple[dict, dict]]:
        clean_player = str(player_id or "").strip()
        clean_character = str(character_id or "").strip()
        clean_sheet = str(sheet_id or "").strip()
        clean_dungeon = str(dungeon_id or "").strip()
        if not clean_player or not clean_character:
            return []
        matches: list[tuple[dict, dict]] = []
        for dungeon in self._dungeons:
            if clean_dungeon and str(dungeon.get("id") or "").strip() != clean_dungeon:
                continue
            state = dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                if str(item_data.get("owner_player_id") or "").strip() != clean_player:
                    continue
                if str(item_data.get("linked_character_id") or "").strip() != clean_character:
                    continue
                if clean_sheet and str(item_data.get("linked_sheet_id") or "").strip() != clean_sheet:
                    continue
                matches.append((dungeon, item_data))
        return matches

    def _host_should_reject_stale_inventory_sync(
        self,
        *,
        host_item_data: dict,
        incoming_inventory: dict,
        incoming_save_revision: int,
        incoming_content_hash: str,
    ) -> bool:
        if not isinstance(host_item_data, dict):
            return False
        host_inventory = normalize_inventory_payload(host_item_data.get("linked_inventory") or {})
        host_content_hash = str(host_item_data.get("linked_content_hash") or "").strip()
        try:
            host_save_revision = max(0, int(host_item_data.get("linked_save_revision") or 0))
        except (TypeError, ValueError):
            host_save_revision = 0
        if incoming_save_revision > host_save_revision:
            return False
        if incoming_save_revision < host_save_revision:
            return True
        if incoming_content_hash and host_content_hash:
            return incoming_content_hash != host_content_hash
        if incoming_save_revision > 0 or host_save_revision > 0 or host_content_hash:
            return (
                self._inventory_payload_fingerprint(incoming_inventory)
                != self._inventory_payload_fingerprint(host_inventory)
            )
        return False

    def _validate_archive_payload(self, archive_b64: str) -> tuple[bool, str, bytes | None]:
        clean_archive_b64 = str(archive_b64 or "").strip()
        if not clean_archive_b64:
            return True, "", None
        try:
            raw_archive = base64.b64decode(clean_archive_b64.encode("ascii"), validate=True)
        except Exception:
            return False, "", None
        if not validate_character_archive_bytes(raw_archive):
            return False, "", None
        return True, clean_archive_b64, raw_archive

    def _validated_linked_character_sync_metadata(
        self,
        *,
        character_id: str,
        inventory_payload: dict,
        incoming_content_hash: str,
        archive_b64: str,
        archive_bytes: bytes | None,
        fallback_archive_b64: str = "",
        archive_required: bool = True,
    ) -> tuple[bool, str, str, str]:
        effective_archive_b64 = str(archive_b64 or "").strip()
        effective_archive_bytes = archive_bytes
        if effective_archive_bytes is None and fallback_archive_b64:
            fallback_ok, validated_fallback_b64, validated_fallback_bytes = self._validate_archive_payload(
                fallback_archive_b64
            )
            if not fallback_ok:
                return False, "", "", "Stored authoritative linked character archive payload is invalid."
            effective_archive_b64 = validated_fallback_b64
            effective_archive_bytes = validated_fallback_bytes
        if effective_archive_bytes is None and archive_required:
            return False, "", "", "Linked character archive payload is required."
        if effective_archive_bytes is None:
            return True, "", str(incoming_content_hash or "").strip(), ""

        clean_character = str(character_id or "").strip()
        clean_content_hash = str(incoming_content_hash or "").strip()
        if not clean_character:
            return False, "", "", "Character sync requires a character id."
        try:
            verified_content_hash = character_sync_content_hash(
                clean_character,
                inventory_payload,
                effective_archive_bytes,
            )
        except ValueError:
            return False, "", "", "Linked character archive payload is invalid."
        if clean_content_hash and clean_content_hash != verified_content_hash:
            return (
                False,
                "",
                "",
                "Linked character payload does not match the claimed content hash.",
            )
        return True, effective_archive_b64, verified_content_hash, ""

    def _apply_authoritative_item_documents_to_inventory_payload(
        self,
        inventory_payload: dict,
        *,
        item_ids: set[str],
        existing_inventory: dict | None = None,
    ) -> dict:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        selected_ids = {
            str(item_id or "").strip()
            for item_id in item_ids
            if str(item_id or "").strip()
        }
        if not selected_ids:
            return normalized
        updated_documents = _inventory_payload_item_documents(normalized)
        existing_documents = _inventory_payload_item_documents(existing_inventory or {})
        for item_id in sorted(selected_ids):
            authoritative_document = (
                self._linked_item_document_by_id(item_id)
                or existing_documents.get(item_id)
            )
            if authoritative_document is None:
                continue
            updated_documents[item_id] = authoritative_document
        normalized["item_documents"] = updated_documents
        return normalize_inventory_payload(normalized)

    def _linked_inventory_sync_metadata(
        self,
        *,
        owner_player_id: str = "",
        character_id: str = "",
        sheet_id: str = "",
    ) -> dict:
        clean_character = str(character_id or "").strip()
        clean_sheet = str(sheet_id or "").strip()
        owner_filter = str(owner_player_id or "").strip()
        metadata = {
            "save_revision": 0,
            "last_saved_at": "",
            "content_hash": "",
        }
        if not clean_character and not clean_sheet:
            return metadata
        for dungeon in self._dungeons:
            state = dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                if clean_character:
                    if str(item_data.get("linked_character_id") or "").strip() != clean_character:
                        continue
                elif str(item_data.get("linked_sheet_id") or "").strip() != clean_sheet:
                    continue
                if owner_filter and str(item_data.get("owner_player_id") or "").strip() != owner_filter:
                    continue
                try:
                    save_revision = max(0, int(item_data.get("linked_save_revision") or 0))
                except (TypeError, ValueError):
                    save_revision = 0
                if save_revision >= int(metadata["save_revision"]):
                    metadata["save_revision"] = save_revision
                    metadata["last_saved_at"] = str(item_data.get("linked_last_saved_at") or "").strip()
                    metadata["content_hash"] = str(item_data.get("linked_content_hash") or "").strip()
        return metadata

    def _next_linked_inventory_sync_metadata(
        self,
        *,
        inventory_payload: dict,
        owner_player_id: str = "",
        character_id: str = "",
        sheet_id: str = "",
    ) -> dict:
        current = self._linked_inventory_sync_metadata(
            owner_player_id=owner_player_id,
            character_id=character_id,
            sheet_id=sheet_id,
        )
        try:
            current_revision = max(0, int(current.get("save_revision") or 0))
        except (TypeError, ValueError):
            current_revision = 0
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        return {
            "save_revision": current_revision + 1,
            "last_saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "content_hash": self._inventory_payload_fingerprint(normalized),
        }

    @staticmethod
    def _remove_selected_items_from_inventory_payload(
        inventory_payload: dict,
        selected_items: list[dict],
    ) -> tuple[bool, dict, list[str]]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        remaining_inventory = [
            dict(entry)
            for entry in (
                normalized.get("inventory", [])
                if isinstance(normalized.get("inventory"), list)
                else []
            )
            if isinstance(entry, dict)
        ]
        raw_equipment = normalized.get("equipment")
        equipment: dict[str, dict | None] = {}
        if isinstance(raw_equipment, dict):
            for key, value in raw_equipment.items():
                slot_id = str(key or "").strip()
                if not slot_id:
                    continue
                if value is None:
                    equipment[slot_id] = None
                    continue
                if isinstance(value, dict):
                    equipment[slot_id] = dict(value)
                else:
                    clean_value = str(value).strip()
                    equipment[slot_id] = (
                        {"item_id": clean_value, "normalized_item_name": normalize_item_name(clean_value), "quantity": 1}
                        if clean_value
                        else None
                    )
        missing: list[str] = []
        for selected in selected_items:
            if not isinstance(selected, dict):
                continue
            clean_item_id = str(selected.get("item_id") or "").strip()
            if not clean_item_id:
                continue
            source = str(selected.get("source") or "backpack").strip().lower()
            if source == "equipment":
                source_slot = str(selected.get("source_slot") or "").strip()
                removed = False
                if (
                    source_slot
                    and _inventory_entry_item_id(equipment.get(source_slot)) == clean_item_id
                ):
                    equipment[source_slot] = None
                    removed = True
                if not removed:
                    for slot_id, value in equipment.items():
                        if _inventory_entry_item_id(value) != clean_item_id:
                            continue
                        equipment[slot_id] = None
                        removed = True
                        break
                if not removed:
                    missing.append(clean_item_id)
                continue
            removed = False
            source_index = selected.get("source_index")
            if isinstance(source_index, int):
                if 0 <= source_index < len(remaining_inventory):
                    stack_entry = remaining_inventory[source_index]
                    if _inventory_entry_item_id(stack_entry) == clean_item_id:
                        quantity = _inventory_entry_quantity(stack_entry)
                        if quantity <= 1:
                            remaining_inventory.pop(source_index)
                        else:
                            stack_entry["quantity"] = quantity - 1
                        removed = True
            if not removed:
                for matched_index, stack_entry in enumerate(remaining_inventory):
                    if _inventory_entry_item_id(stack_entry) != clean_item_id:
                        continue
                    quantity = _inventory_entry_quantity(stack_entry)
                    if quantity <= 1:
                        remaining_inventory.pop(matched_index)
                    else:
                        stack_entry["quantity"] = quantity - 1
                    removed = True
                    break
            if not removed:
                missing.append(clean_item_id)
        if missing:
            return False, normalized, missing
        normalized["inventory"] = remaining_inventory
        normalized["equipment"] = equipment
        return True, normalize_inventory_payload(normalized), []

    def _handle_host_add_loot_from_inventory(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        def _send_loot_transfer_result(
            *,
            ok: bool,
            message: str,
            data: dict | None = None,
        ) -> None:
            response_data = dict(data) if isinstance(data, dict) else {}
            response_data.setdefault("action", "add_loot_from_inventory")
            self._host_controller.send_command_result(
                player_id,
                ok=ok,
                message=message,
                request_id=request_id,
                data=response_data,
            )
        sheet_id = str(payload.get("sheet_id") or "").strip()
        selected_items = payload.get("items")
        if not sheet_id or not isinstance(selected_items, list):
            _send_loot_transfer_result(
                ok=False,
                message="Invalid inventory transfer payload",
            )
            return
        allowed_dungeon_id = self._player_action_dungeon_id()
        if not self._player_has_linked_sheet_in_dungeon(
            player_id,
            sheet_id,
            dungeon_id=allowed_dungeon_id,
        ):
            _send_loot_transfer_result(
                ok=False,
                message="Transfer target character is not linked to your entities in the assigned players dungeon.",
            )
            return
        linked_inventory = self._linked_inventory_payload_for_player_sheet(
            player_id=player_id,
            sheet_id=sheet_id,
            dungeon_id=allowed_dungeon_id,
        )
        if not isinstance(linked_inventory, dict):
            _send_loot_transfer_result(
                ok=False,
                message="Character inventory is unavailable on host.",
            )
            return
        character_id = ""
        linked_sheet_name = sheet_id
        linked_sheet_entries = self._linked_entity_state_entries_for_sheet(
            player_id=player_id,
            sheet_id=sheet_id,
            dungeon_id=allowed_dungeon_id,
        )
        if linked_sheet_entries:
            _linked_dungeon, linked_item_data = linked_sheet_entries[0]
            character_id = str(linked_item_data.get("linked_character_id") or "").strip()
            linked_sheet_name = (
                str(linked_item_data.get("linked_sheet_name") or sheet_id).strip() or sheet_id
            )

        parsed_items: list[dict] = []
        for item in selected_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id") or "").strip()
            if not item_id:
                continue
            item_document = item.get("item_document")
            item_payload_data = item_document.get("payload") if isinstance(item_document, dict) else {}
            item_payload = {
                "item_id": item_id,
                "title": _resolve_human_item_title(
                    item_id,
                    title=item.get("title"),
                    name=item_payload_data.get("name") if isinstance(item_payload_data, dict) else "",
                    normalized_name=(
                        item_payload_data.get("normalized_item_name")
                        if isinstance(item_payload_data, dict)
                        else ""
                    ),
                    fallback="Item",
                ),
                "path": str(item.get("path") or item_id),
                "source": str(item.get("source") or "backpack"),
            }
            if item_payload["source"] == "equipment":
                item_payload["source_slot"] = str(item.get("source_slot") or "").strip()
            source_index = item.get("source_index")
            if isinstance(source_index, int):
                item_payload["source_index"] = int(source_index)
            if (
                isinstance(item_document, dict)
                and str(item_document.get("format") or "").strip().lower() == ITEM_FILE_FORMAT
                and isinstance(item_document.get("payload"), dict)
            ):
                item_payload["item_document"] = dict(item_document)
            parsed_items.append(item_payload)
        if not parsed_items:
            _send_loot_transfer_result(
                ok=False,
                message="No inventory/equipment items selected",
            )
            return

        removed_ok, updated_inventory, missing = self._remove_selected_items_from_inventory_payload(
            linked_inventory,
            parsed_items,
        )
        if not removed_ok:
            missing_preview = ", ".join(missing[:3])
            message = "Selected inventory/equipment items are no longer available."
            if missing_preview:
                message = f"{message} Missing: {missing_preview}"
            _send_loot_transfer_result(ok=False, message=message)
            return

        linked_inventory_documents = _inventory_payload_item_documents(linked_inventory)
        authoritative_item_documents: dict[str, dict] = {}
        unknown_items: list[dict] = []
        for item in parsed_items:
            item_id = str(item.get("item_id") or "").strip()
            if not item_id or item_id in authoritative_item_documents:
                continue
            authoritative_document = self._linked_item_document_by_id(item_id)
            if isinstance(authoritative_document, dict):
                authoritative_item_documents[item_id] = self._clone_item_document_with_item_id(
                    authoritative_document,
                    item_id,
                )
                continue
            unknown_items.append(dict(item))
        if unknown_items:
            unknown_entries_for_import: list[dict] = []
            seen_unknown_item_ids: set[str] = set()
            for item in unknown_items:
                item_id = str(item.get("item_id") or "").strip()
                if not item_id or item_id in seen_unknown_item_ids:
                    continue
                seen_unknown_item_ids.add(item_id)
                candidate_document = linked_inventory_documents.get(item_id) or item.get("item_document")
                unknown_entries_for_import.append(
                    {
                        "item_id": item_id,
                        "title": _resolve_human_item_title(
                            item_id,
                            title=item.get("title"),
                            fallback="Unknown Item",
                        ),
                        "item_document": (
                            dict(candidate_document)
                            if (
                                isinstance(candidate_document, dict)
                                and str(
                                    (candidate_document or {}).get("format")
                                    or ""
                                ).strip().lower()
                                == ITEM_FILE_FORMAT
                                and isinstance((candidate_document or {}).get("payload"), dict)
                            )
                            else None
                        ),
                    }
                )
            missing_documents = [
                str(entry.get("title") or entry.get("item_id") or "Item")
                for entry in unknown_entries_for_import
                if not isinstance(entry.get("item_document"), dict)
            ]
            if missing_documents:
                preview = ", ".join(missing_documents[:3])
                suffix = "..." if len(missing_documents) > 3 else ""
                _send_loot_transfer_result(
                    ok=False,
                    message=(
                        "Unknown loot item definitions are missing and cannot be transferred. "
                        f"Missing: {preview}{suffix}"
                    ),
                )
                return
            accept_unknown = self._prompt_unknown_items_with_preview(
                title="Unknown Loot Items",
                heading="Some selected loot items are unknown to the DM item library.",
                details="Accept and store these item definitions in DM local storage before transfer?",
                entries=unknown_entries_for_import,
                accept_label="Accept And Store",
                reject_label="Reject Transfer",
                default_accept=True,
            )
            if not accept_unknown:
                _send_loot_transfer_result(
                    ok=False,
                    message="DM rejected unknown loot item definitions. No items were transferred.",
                )
                return
            _persisted_item_ids, unresolved_item_ids, import_messages = self._persist_item_documents_to_local_library(
                unknown_entries_for_import,
                overwrite_existing=True,
            )
            if import_messages:
                self._append_server_log(f"[WARN] {' '.join(import_messages)}")
            if unresolved_item_ids:
                _send_loot_transfer_result(
                    ok=False,
                    message="Unable to persist unknown loot item definitions into DM storage.",
                )
                return
            for imported_entry in unknown_entries_for_import:
                item_id = str(imported_entry.get("item_id") or "").strip()
                if not item_id:
                    continue
                authoritative_document = self._linked_item_document_by_id(item_id)
                if not isinstance(authoritative_document, dict):
                    _send_loot_transfer_result(
                        ok=False,
                        message="Unable to resolve imported unknown loot item definitions.",
                    )
                    return
                authoritative_item_documents[item_id] = self._clone_item_document_with_item_id(
                    authoritative_document,
                    item_id,
                )

        added_entries: list[dict] = []
        for item in parsed_items:
            item_id = str(item.get("item_id") or "").strip()
            incoming_document = item.get("item_document") or linked_inventory_documents.get(item_id)
            incoming_payload = (
                incoming_document.get("payload")
                if isinstance(incoming_document, dict)
                else {}
            )
            entry_payload = {
                "entry_id": uuid.uuid4().hex,
                "type": "item",
                "item_id": item_id,
                "title": _resolve_human_item_title(
                    item_id,
                    title=item.get("title"),
                    name=incoming_payload.get("name") if isinstance(incoming_payload, dict) else "",
                    normalized_name=(
                        incoming_payload.get("normalized_item_name")
                        if isinstance(incoming_payload, dict)
                        else ""
                    ),
                    fallback="Item",
                ),
                "path": item_id,
            }
            item_document = authoritative_item_documents.get(item_id)
            if isinstance(item_document, dict):
                entry_payload["item_document"] = dict(item_document)
            else:
                if (
                    isinstance(incoming_document, dict)
                    and str(incoming_document.get("format") or "").strip().lower() == ITEM_FILE_FORMAT
                    and isinstance(incoming_document.get("payload"), dict)
                ):
                    entry_payload["item_document"] = dict(incoming_document)
            added_entries.append(self._sanitize_loot_pool_entry(entry_payload))

        if not added_entries:
            _send_loot_transfer_result(
                ok=False,
                message="No valid inventory/equipment items selected",
            )
            return

        self._session_loot_pool.extend(added_entries)
        self._refresh_loot_pool_list()
        sync_metadata = self._next_linked_inventory_sync_metadata(
            owner_player_id=player_id,
            character_id=character_id,
            sheet_id=sheet_id,
            inventory_payload=updated_inventory,
        )
        self._apply_inventory_sync_to_linked_entities(
            owner_player_id=player_id,
            character_id=character_id,
            sheet_id=sheet_id,
            inventory_payload=updated_inventory,
            save_revision=int(sync_metadata.get("save_revision") or 0),
            last_saved_at=str(sync_metadata.get("last_saved_at") or ""),
            content_hash=str(sync_metadata.get("content_hash") or ""),
        )
        _send_loot_transfer_result(
            ok=True,
            message=f"Added {len(added_entries)} inventory/equipment item(s) to loot pool",
            data={
                "sheet_id": sheet_id,
                "sheet_name": linked_sheet_name,
                "character_id": character_id,
                "save_revision": int(sync_metadata.get("save_revision") or 0),
                "last_saved_at": str(sync_metadata.get("last_saved_at") or ""),
                "content_hash": str(sync_metadata.get("content_hash") or ""),
                "inventory": dict(updated_inventory),
                "added_entries": [dict(entry) for entry in added_entries],
            },
        )
        self._broadcast_snapshot_if_host()

    def _handle_host_claim_loot(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        selected_ids = payload.get("entry_ids")
        sheet_id = str(payload.get("sheet_id") or "").strip()
        if not isinstance(selected_ids, list) or not sheet_id:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Invalid claim payload",
                request_id=request_id,
            )
            return
        selected_order: list[str] = []
        selected_set: set[str] = set()
        for entry_id in selected_ids:
            clean_id = str(entry_id).strip()
            if not clean_id or clean_id in selected_set:
                continue
            selected_set.add(clean_id)
            selected_order.append(clean_id)
        if not selected_order:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="No loot entries selected",
                request_id=request_id,
            )
            return
        allowed_dungeon_id = self._player_action_dungeon_id()
        if not self._player_has_linked_sheet_in_dungeon(
            player_id,
            sheet_id,
            dungeon_id=allowed_dungeon_id,
        ):
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Claim target character is not linked to your entities in the assigned players dungeon.",
                request_id=request_id,
            )
            return
        linked_entries = self._linked_entity_state_entries_for_sheet(
            player_id=player_id,
            sheet_id=sheet_id,
            dungeon_id=allowed_dungeon_id,
        )
        if not linked_entries:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Character inventory is unavailable on host.",
                request_id=request_id,
            )
            return
        _linked_dungeon, linked_item_data = linked_entries[0]
        baseline_inventory = normalize_inventory_payload(linked_item_data.get("linked_inventory") or {})
        try:
            baseline_save_revision = max(0, int(linked_item_data.get("linked_save_revision") or 0))
        except (TypeError, ValueError):
            baseline_save_revision = 0
        baseline_last_saved_at = str(linked_item_data.get("linked_last_saved_at") or "").strip()
        baseline_content_hash = str(linked_item_data.get("linked_content_hash") or "").strip()

        self._release_stale_loot_claim_reservations()
        loot_entries_by_id: dict[str, dict] = {}
        for entry in self._session_loot_pool:
            entry_id = str(entry.get("entry_id") or "").strip()
            if entry_id and isinstance(entry, dict):
                loot_entries_by_id.setdefault(entry_id, dict(entry))
        for entry_id in selected_order:
            if self._loot_claim_entry_reservations.get(entry_id):
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message="Selected loot entries are temporarily reserved.",
                    request_id=request_id,
                )
                return
        missing_entry_ids = [entry_id for entry_id in selected_order if entry_id not in loot_entries_by_id]
        if missing_entry_ids:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Selected loot entries are no longer available.",
                request_id=request_id,
            )
            return
        claimed_entries: list[dict] = []
        for entry_id in selected_order:
            claimed_entries.append(dict(loot_entries_by_id[entry_id]))
        if not claimed_entries:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Selected loot entries are no longer available.",
                request_id=request_id,
            )
            return
        claim_id = uuid.uuid4().hex
        claim_entry_ids = [str(entry.get("entry_id") or "").strip() for entry in claimed_entries]
        self._session_loot_pool = [
            entry
            for entry in self._session_loot_pool
            if str(entry.get("entry_id") or "").strip() not in selected_set
        ]
        self._refresh_loot_pool_list()
        self._loot_claim_reservations[claim_id] = {
            "claim_id": claim_id,
            "player_id": str(player_id or ""),
            "sheet_id": sheet_id,
            "dungeon_id": allowed_dungeon_id,
            "character_id": str(linked_item_data.get("linked_character_id") or "").strip(),
            "baseline_inventory": dict(baseline_inventory),
            "baseline_save_revision": baseline_save_revision,
            "baseline_last_saved_at": baseline_last_saved_at,
            "baseline_content_hash": baseline_content_hash,
            "claimed_entries": [dict(entry) for entry in claimed_entries],
            "entry_ids": [entry_id for entry_id in claim_entry_ids if entry_id],
            "created_monotonic": time.monotonic(),
            "hold_open": False,
        }
        for entry_id in claim_entry_ids:
            if entry_id:
                self._loot_claim_entry_reservations[entry_id] = claim_id
        self._host_controller.send_command_result(
            player_id,
            ok=True,
            message="Claim prepared",
            request_id=request_id,
            data={
                "claim_id": claim_id,
                "claimed_entries": claimed_entries,
                "sheet_id": sheet_id,
            },
        )
        self._broadcast_snapshot_if_host()

    def _handle_host_finalize_loot_claim(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        claim_id = str(payload.get("claim_id") or "").strip()
        applied = bool(payload.get("applied"))
        error_text = str(payload.get("error") or "").strip()
        if not claim_id:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Invalid claim finalize payload",
                request_id=request_id,
            )
            return
        claim = self._loot_claim_reservations.get(claim_id)
        if not isinstance(claim, dict):
            if self._replay_loot_claim_finalize_response(
                claim_id,
                player_id,
                request_id=request_id,
            ):
                return
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Claim is no longer active.",
                request_id=request_id,
                data={
                    "action": "claim_loot_finalize",
                    "claim_id": claim_id,
                },
            )
            return
        if str(claim.get("player_id") or "") != str(player_id or ""):
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Claim belongs to a different player.",
                request_id=request_id,
                data={
                    "action": "claim_loot_finalize",
                    "claim_id": claim_id,
                },
            )
            return

        if applied:
            if not self._host_claim_finalize_observed_authority_update(claim):
                restored_any = self._release_loot_claim_reservation(claim_id, restore_entries=True)
                reason = "Claim was not committed to host-authoritative character data."
                self._cache_loot_claim_finalize_response(
                    claim_id,
                    player_id,
                    ok=False,
                    message=reason,
                    data={
                        "action": "claim_loot_finalize",
                        "claim_id": claim_id,
                    },
                )
                self._host_controller.send_command_result(
                    player_id,
                    ok=False,
                    message=reason,
                    request_id=request_id,
                    data={
                        "action": "claim_loot_finalize",
                        "claim_id": claim_id,
                    },
                )
                if restored_any:
                    self._broadcast_snapshot_if_host()
                return
            self._release_loot_claim_reservation(claim_id)
            self._cache_loot_claim_finalize_response(
                claim_id,
                player_id,
                ok=True,
                message="Claim committed",
                data={
                    "action": "claim_loot_finalize",
                    "claim_id": claim_id,
                },
            )
            self._host_controller.send_command_result(
                player_id,
                ok=True,
                message="Claim committed",
                request_id=request_id,
                data={
                    "action": "claim_loot_finalize",
                    "claim_id": claim_id,
                },
            )
            return

        restored_any = self._release_loot_claim_reservation(claim_id, restore_entries=True)
        reason = error_text or "Claim was not applied on client."
        self._cache_loot_claim_finalize_response(
            claim_id,
            player_id,
            ok=False,
            message=reason,
            data={
                "action": "claim_loot_finalize",
                "claim_id": claim_id,
            },
        )
        self._host_controller.send_command_result(
            player_id,
            ok=False,
            message=reason,
            request_id=request_id,
            data={
                "action": "claim_loot_finalize",
                "claim_id": claim_id,
            },
        )
        if restored_any:
            self._broadcast_snapshot_if_host()

    @staticmethod
    def _inventory_item_quantity_map(inventory_payload: dict) -> dict[str, int]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        quantities: dict[str, int] = {}
        inventory_rows = normalized.get("inventory")
        if not isinstance(inventory_rows, list):
            return quantities
        for entry in inventory_rows:
            item_id = _inventory_entry_item_id(entry)
            if not item_id:
                continue
            quantities[item_id] = quantities.get(item_id, 0) + _inventory_entry_quantity(entry)
        return quantities

    @staticmethod
    def _inventory_note_line_counts(inventory_payload: dict) -> dict[str, int]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        counts: dict[str, int] = {}
        notes_text = str(normalized.get("inventory_notes") or "")
        if not notes_text:
            return counts
        for line in notes_text.splitlines():
            clean_line = str(line or "").strip()
            if not clean_line:
                continue
            counts[clean_line] = counts.get(clean_line, 0) + 1
        return counts

    @classmethod
    def _claimed_entries_reflected_in_inventory(
        cls,
        claimed_entries: list[dict],
        *,
        baseline_inventory: dict,
        current_inventory: dict,
    ) -> bool:
        claimed_item_counts: dict[str, int] = {}
        claimed_note_counts: dict[str, int] = {}
        for entry in claimed_entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("type") or "").strip().lower() == "note":
                note_text = str(entry.get("note") or entry.get("title") or "").strip()
                if note_text:
                    claimed_note_counts[note_text] = claimed_note_counts.get(note_text, 0) + 1
                continue
            item_id = str(entry.get("item_id") or "").strip()
            if item_id:
                claimed_item_counts[item_id] = claimed_item_counts.get(item_id, 0) + 1

        baseline_item_counts = cls._inventory_item_quantity_map(baseline_inventory)
        current_item_counts = cls._inventory_item_quantity_map(current_inventory)
        for item_id, delta in claimed_item_counts.items():
            required = baseline_item_counts.get(item_id, 0) + int(delta)
            if current_item_counts.get(item_id, 0) < required:
                return False

        baseline_note_counts = cls._inventory_note_line_counts(baseline_inventory)
        current_note_counts = cls._inventory_note_line_counts(current_inventory)
        for note_text, delta in claimed_note_counts.items():
            required = baseline_note_counts.get(note_text, 0) + int(delta)
            if current_note_counts.get(note_text, 0) < required:
                return False
        return True

    def _host_claim_finalize_observed_authority_update(self, claim: dict) -> bool:
        player_id = str(claim.get("player_id") or "").strip()
        sheet_id = str(claim.get("sheet_id") or "").strip()
        dungeon_id = str(claim.get("dungeon_id") or "").strip()
        if not player_id or not sheet_id:
            return False
        linked_entries = self._linked_entity_state_entries_for_sheet(
            player_id=player_id,
            sheet_id=sheet_id,
            dungeon_id=dungeon_id,
        )
        if not linked_entries:
            return False
        _linked_dungeon, linked_item_data = linked_entries[0]
        current_inventory = normalize_inventory_payload(linked_item_data.get("linked_inventory") or {})
        baseline_inventory = normalize_inventory_payload(claim.get("baseline_inventory") or {})
        try:
            baseline_save_revision = max(0, int(claim.get("baseline_save_revision") or 0))
        except (TypeError, ValueError):
            baseline_save_revision = 0
        try:
            current_save_revision = max(0, int(linked_item_data.get("linked_save_revision") or 0))
        except (TypeError, ValueError):
            current_save_revision = 0
        baseline_content_hash = str(claim.get("baseline_content_hash") or "").strip()
        current_content_hash = str(linked_item_data.get("linked_content_hash") or "").strip()
        authority_advanced = False
        if current_save_revision > baseline_save_revision:
            authority_advanced = True
        elif (current_content_hash or baseline_content_hash) and current_content_hash != baseline_content_hash:
            authority_advanced = True
        elif (
            self._inventory_payload_fingerprint(current_inventory)
            != self._inventory_payload_fingerprint(baseline_inventory)
        ):
            authority_advanced = True
        if not authority_advanced:
            return False
        claimed_entries = [
            entry
            for entry in claim.get("claimed_entries", [])
            if isinstance(entry, dict)
        ]
        return self._claimed_entries_reflected_in_inventory(
            claimed_entries,
            baseline_inventory=baseline_inventory,
            current_inventory=current_inventory,
        )

    def _cache_loot_claim_finalize_response(
        self,
        claim_id: str,
        player_id: str,
        *,
        ok: bool,
        message: str,
        data: dict | None = None,
    ) -> None:
        clean_claim_id = str(claim_id or "").strip()
        clean_player_id = str(player_id or "").strip()
        if not clean_claim_id or not clean_player_id:
            return
        self._loot_claim_finalize_response_cache[clean_claim_id] = {
            "player_id": clean_player_id,
            "ok": bool(ok),
            "message": str(message or ""),
            "data": dict(data) if isinstance(data, dict) else {},
        }

    def _replay_loot_claim_finalize_response(
        self,
        claim_id: str,
        player_id: str,
        *,
        request_id: str | None = None,
    ) -> bool:
        clean_claim_id = str(claim_id or "").strip()
        clean_player_id = str(player_id or "").strip()
        if not clean_claim_id or not clean_player_id:
            return False
        cached = self._loot_claim_finalize_response_cache.get(clean_claim_id)
        if not isinstance(cached, dict):
            return False
        if str(cached.get("player_id") or "").strip() != clean_player_id:
            return False
        self._host_controller.send_command_result(
            clean_player_id,
            ok=bool(cached.get("ok")),
            message=str(cached.get("message") or ""),
            request_id=request_id,
            data=dict(cached.get("data") or {}),
        )
        return True

    def _rollback_host_loot_claim_authority(self, claim: dict) -> bool:
        if not isinstance(claim, dict):
            return False
        if not self._host_claim_finalize_observed_authority_update(claim):
            return False
        updated = self._apply_inventory_sync_to_linked_entities(
            owner_player_id=str(claim.get("player_id") or ""),
            character_id=str(claim.get("character_id") or ""),
            sheet_id=str(claim.get("sheet_id") or ""),
            inventory_payload=normalize_inventory_payload(claim.get("baseline_inventory") or {}),
            save_revision=int(claim.get("baseline_save_revision") or 0),
            last_saved_at=str(claim.get("baseline_last_saved_at") or ""),
            content_hash=str(claim.get("baseline_content_hash") or ""),
        )
        return updated > 0

    def _restore_claimed_loot_entries(self, claim: dict) -> bool:
        claimed_entries = claim.get("claimed_entries", [])
        if not isinstance(claimed_entries, list):
            return False
        restored_any = False
        existing_ids = {
            str(entry.get("entry_id") or "").strip()
            for entry in self._session_loot_pool
            if isinstance(entry, dict)
        }
        for entry in claimed_entries:
            if not isinstance(entry, dict):
                continue
            entry_id = str(entry.get("entry_id") or "").strip()
            if not entry_id or entry_id in existing_ids:
                continue
            self._session_loot_pool.append(dict(entry))
            existing_ids.add(entry_id)
            restored_any = True
        if restored_any:
            self._refresh_loot_pool_list()
        return restored_any

    def _release_loot_claim_reservation(self, claim_id: str, *, restore_entries: bool = False) -> bool:
        claim = self._loot_claim_reservations.pop(str(claim_id or ""), None)
        if not isinstance(claim, dict):
            return False
        restored_any = False
        if restore_entries:
            authority_restored = False
            if bool(claim.get("hold_open")):
                authority_restored = self._rollback_host_loot_claim_authority(claim)
            restored_any = self._restore_claimed_loot_entries(claim) or authority_restored
        for entry_id in claim.get("entry_ids", []):
            clean_id = str(entry_id or "").strip()
            if not clean_id:
                continue
            if self._loot_claim_entry_reservations.get(clean_id) == claim_id:
                self._loot_claim_entry_reservations.pop(clean_id, None)
        return restored_any

    def _release_stale_loot_claim_reservations(self) -> None:
        now = time.monotonic()
        stale_claim_ids = []
        for claim_id, claim in self._loot_claim_reservations.items():
            if bool(claim.get("hold_open")):
                continue
            created = float(claim.get("created_monotonic") or 0.0)
            if now - created >= 45.0:
                stale_claim_ids.append(claim_id)
        restored_any = False
        for claim_id in stale_claim_ids:
            if self._release_loot_claim_reservation(claim_id, restore_entries=True):
                restored_any = True
        if restored_any:
            self._broadcast_snapshot_if_host()

    def _release_loot_claim_reservations_for_player(self, player_id: str) -> None:
        clean_player_id = str(player_id or "").strip()
        if not clean_player_id:
            return
        claim_ids = [
            str(claim_id)
            for claim_id, claim in self._loot_claim_reservations.items()
            if str(claim.get("player_id") or "").strip() == clean_player_id
        ]
        restored_any = False
        for claim_id in claim_ids:
            if self._release_loot_claim_reservation(claim_id, restore_entries=True):
                restored_any = True
        if restored_any:
            self._broadcast_snapshot_if_host()

    def _drop_invalid_loot_claim_reservations(self) -> None:
        current_entry_ids = {
            str(entry.get("entry_id") or "").strip()
            for entry in self._session_loot_pool
            if str(entry.get("entry_id") or "").strip()
        }
        release_claim_ids: list[str] = []
        for claim_id, claim in self._loot_claim_reservations.items():
            claim_entry_ids = {
                str(entry_id).strip()
                for entry_id in claim.get("entry_ids", [])
                if str(entry_id).strip()
            }
            if not claim_entry_ids:
                release_claim_ids.append(claim_id)
                continue
            missing_entry_ids = [
                entry_id for entry_id in claim_entry_ids if entry_id not in current_entry_ids
            ]
            invalid_missing = [
                entry_id
                for entry_id in missing_entry_ids
                if self._loot_claim_entry_reservations.get(entry_id) != claim_id
            ]
            if invalid_missing:
                release_claim_ids.append(claim_id)
        for claim_id in release_claim_ids:
            self._release_loot_claim_reservation(claim_id)

    def _handle_host_initiative_update(
        self,
        player_id: str,
        payload: dict,
        *,
        request_id: str | None = None,
    ) -> None:
        if self._host_controller is None:
            return
        self._debug_log(
            "host_initiative_update_received",
            player_id=str(player_id or ""),
            request_id=str(request_id or ""),
            payload_kind=str(payload.get("kind") or ""),
            payload_id=str(payload.get("id") or ""),
            payload_initiative=payload.get("initiative"),
        )
        if not bool(self._initiative_state.get("active", False)):
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Initiative is not active.",
                request_id=request_id,
            )
            return
        kind = str(payload.get("kind") or "")
        entry_id = str(payload.get("id") or "")
        if kind not in {"player", "entity"} or not entry_id:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Invalid initiative payload",
                request_id=request_id,
            )
            return
        if kind != "player":
            self._debug_log(
                "host_initiative_update_denied",
                player_id=str(player_id or ""),
                kind=str(kind),
                row_id=str(entry_id),
                reason="non-player-row",
            )
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Initiative entry is not owned by this player.",
                request_id=request_id,
            )
            return
        raw_value = payload.get("initiative")
        value: int | None = None
        if raw_value is not None:
            try:
                value = int(raw_value)
            except (TypeError, ValueError):
                value = None
        target = self._initiative_state.get("player_entries", {})
        if not isinstance(target, dict):
            target = {}
            self._initiative_state["player_entries"] = target
        row = target.get(entry_id)
        if not isinstance(row, dict):
            self._debug_log(
                "host_initiative_update_denied",
                player_id=str(player_id or ""),
                kind=str(kind),
                row_id=str(entry_id),
                reason="missing-row",
            )
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Initiative entry is not owned by this player.",
                request_id=request_id,
            )
            return
        row_player_id = str(row.get("player_id") or "").strip()
        row_entity_id = str(row.get("entity_id") or "").strip()
        expected_row_id = f"{row_player_id}:{row_entity_id}" if row_player_id and row_entity_id else ""
        if (
            not row_player_id
            or row_player_id != player_id
            or not row_entity_id
            or expected_row_id != entry_id
        ):
            self._debug_log(
                "host_initiative_update_denied",
                player_id=str(player_id or ""),
                kind=str(kind),
                row_id=str(entry_id),
                row_player_id=str(row_player_id),
                row_entity_id=str(row_entity_id),
                reason="ownership-mismatch",
            )
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Initiative entry is not owned by this player.",
                request_id=request_id,
            )
            return
        player_name = self._connected_players.get(player_id, player_id)
        entity_name = str(row.get("name") or "")
        if entity_name and " - " in entity_name:
            row["name"] = entity_name
        else:
            row["name"] = str(row.get("name") or player_name)
        row["initiative"] = value
        self._debug_log(
            "host_initiative_update_applied",
            player_id=str(player_id or ""),
            kind=str(kind),
            row_id=str(entry_id),
            value=value,
        )
        self._render_initiative_overlay()
        self._host_controller.send_command_result(
            player_id,
            ok=True,
            message="Initiative updated",
            request_id=request_id,
        )
        self._broadcast_snapshot_if_host()

    def _find_entity_state_entry(self, entity_id: str, dungeon_id: str = "") -> tuple[dict | None, dict | None]:
        target_dungeon_id = str(dungeon_id or self._players_dungeon_id or self._active_dungeon_id or "")
        dungeon = self._find_dungeon(target_dungeon_id)
        if dungeon is None:
            return None, None
        state = dungeon.get("state")
        if not isinstance(state, dict):
            return dungeon, None
        items = state.get("items")
        if not isinstance(items, list):
            return dungeon, None
        for item_data in items:
            if not isinstance(item_data, dict):
                continue
            if item_data.get("type") != "entity":
                continue
            if str(item_data.get("entity_id") or "") == entity_id:
                return dungeon, item_data
        return dungeon, None

    def _collection_working_icon_dir(self, target_collection_path: Path | None = None) -> Path:
        if target_collection_path is not None:
            return collection_icon_assets_dir(target_collection_path)
        if self._collection_path is not None:
            return collection_icon_assets_dir(self._collection_path)
        return working_collection_icon_assets_dir(self._collection_name)

    def _normalize_icon_to_session_asset(
        self,
        filename: str,
        raw: bytes,
        *,
        persist_collection_copy: bool = False,
    ) -> tuple[str, str, Path]:
        ext = Path(filename).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            ext = ".png"
        digest = hashlib.sha256(raw).hexdigest()
        cache_name = f"{digest}{ext}"
        cache_dir = online_icon_cache_dir(self._active_online_runtime_cache_id())
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / cache_name
        if not cache_path.exists():
            cache_path.write_bytes(raw)
        if persist_collection_copy:
            try:
                working_dir = self._collection_working_icon_dir()
                working_dir.mkdir(parents=True, exist_ok=True)
                working_path = working_dir / cache_name
                if not working_path.exists():
                    working_path.write_bytes(raw)
            except Exception:
                pass
        return cache_name, f"{SESSION_ICON_PREFIX}{cache_name}", cache_path

    def _normalize_all_dungeon_icons_for_online(self) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        for dungeon in self._dungeons:
            state = dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                icon_ref = str(item_data.get("icon_path") or "")
                if not icon_ref or icon_ref.startswith(SESSION_ICON_PREFIX):
                    continue
                icon_path = Path(icon_ref)
                if not icon_path.exists():
                    continue
                try:
                    raw = icon_path.read_bytes()
                except Exception:
                    continue
                if not raw or len(raw) > 2 * 1024 * 1024:
                    continue
                cache_name, session_icon_ref, cache_path = self._normalize_icon_to_session_asset(
                    icon_path.name,
                    raw,
                    persist_collection_copy=True,
                )
                item_data["icon_path"] = session_icon_ref
                entity_id = str(item_data.get("entity_id") or "")
                if not entity_id:
                    entity_id = uuid.uuid4().hex
                    item_data["entity_id"] = entity_id
                active_id = str(self._active_dungeon_id or "")
                if active_id and active_id == str(dungeon.get("id") or ""):
                    target_entity = self._find_entity_by_id(entity_id)
                    if target_entity is not None:
                        target_entity.setData(ROLE_ICON, session_icon_ref)
                        target_entity.icon_path = str(cache_path)
                        target_entity.update()
                if self._host_controller is not None:
                    self._host_controller.broadcast_icon_asset(
                        entity_id=entity_id,
                        filename=cache_name,
                        content_b64=base64.b64encode(raw).decode("ascii"),
                    )

    def _sync_host_scene_icons_for_online(self) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST or self._host_controller is None:
            return
        for item in self.canvas.scene().items():
            if not isinstance(item, EntityItem):
                continue
            icon_ref = str(item.data(ROLE_ICON) or getattr(item, "icon_path", "") or "")
            if not icon_ref or icon_ref.startswith(SESSION_ICON_PREFIX):
                continue
            icon_file = Path(icon_ref)
            if not icon_file.exists():
                continue
            try:
                raw = icon_file.read_bytes()
            except Exception:
                continue
            if not raw or len(raw) > 2 * 1024 * 1024:
                continue
            cache_name, session_icon_ref, cache_path = self._normalize_icon_to_session_asset(
                icon_file.name,
                raw,
                persist_collection_copy=True,
            )
            item.setData(ROLE_ICON, session_icon_ref)
            item.icon_path = str(cache_path)
            item.update()
            entity_id = str(item.data(ROLE_ENTITY_ID) or "")
            if not entity_id:
                entity_id = uuid.uuid4().hex
                item.setData(ROLE_ENTITY_ID, entity_id)
            target_dungeon, target_entity_state = self._find_entity_state_entry(
                entity_id,
                str(self._active_dungeon_id or ""),
            )
            if target_dungeon is not None and isinstance(target_entity_state, dict):
                target_entity_state["icon_path"] = session_icon_ref
            self._host_controller.broadcast_icon_asset(
                entity_id=entity_id,
                filename=cache_name,
                content_b64=base64.b64encode(raw).decode("ascii"),
            )

    def _handle_uploaded_icon(self, player_id: str, payload: dict, request_id: str | None = None) -> None:
        if self._host_controller is None:
            return
        entity_id = str(payload.get("entity_id") or "")
        filename = str(payload.get("filename") or "icon.png")
        content_b64 = str(payload.get("content_b64") or "")
        allowed_dungeon_id = self._player_action_dungeon_id()
        dungeon_id = str(payload.get("dungeon_id") or "").strip()
        if not dungeon_id:
            dungeon_id = allowed_dungeon_id
        if allowed_dungeon_id and dungeon_id and dungeon_id != allowed_dungeon_id:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Players can only upload icons in the assigned players dungeon.",
                request_id=request_id,
            )
            return
        target_dungeon, target_entity_state = self._find_entity_state_entry(entity_id, dungeon_id)
        if target_dungeon is None:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Target dungeon not found",
                request_id=request_id,
            )
            return
        target_entity = self._find_entity_by_id(entity_id) if dungeon_id == str(self._active_dungeon_id or "") else None
        owner_id = ""
        if target_entity is not None:
            owner_id = str(target_entity.data(ROLE_OWNER_PLAYER_ID) or "")
        if not owner_id and isinstance(target_entity_state, dict):
            owner_id = str(target_entity_state.get("owner_player_id") or "")
        decision = authorize_command(
            role=OnlineRole.PLAYER,
            action="upload_icon",
            actor_id=player_id,
            target_owner_id=owner_id,
        )
        if not decision.allowed:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message=decision.reason,
                request_id=request_id,
            )
            return
        try:
            raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
        except Exception:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message="Invalid icon encoding",
                request_id=request_id,
            )
            return
        payload_ok, payload_error = _validate_online_icon_payload(raw)
        if not payload_ok:
            self._host_controller.send_command_result(
                player_id,
                ok=False,
                message=str(payload_error or "Invalid icon payload"),
                request_id=request_id,
            )
            return
        cache_name, icon_ref, cache_path = self._normalize_icon_to_session_asset(
            filename,
            raw,
            persist_collection_copy=True,
        )
        if isinstance(target_entity_state, dict):
            target_entity_state["icon_path"] = icon_ref
            if not target_entity_state.get("owner_player_id"):
                target_entity_state["owner_player_id"] = owner_id
        target_dungeon["dirty"] = True
        target_dungeon["preview"] = None
        target_dungeon["preview_signature"] = None
        if target_entity is not None:
            target_entity.setData(ROLE_ICON, icon_ref)
            target_entity.icon_path = str(cache_path)
            target_entity.update()
        self._refresh_collection_dirty()
        self._host_controller.send_command_result(
            player_id,
            ok=True,
            message="Icon updated",
            request_id=request_id,
        )
        self._host_controller.broadcast_icon_asset(
            entity_id=entity_id,
            filename=cache_name,
            content_b64=content_b64,
        )
        self._broadcast_snapshot_if_host()

    def _inventory_payload_fingerprint(self, inventory_payload: dict) -> str:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        try:
            serialized = json.dumps(
                normalized,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except Exception:
            serialized = str(normalized)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _active_linked_character_ids_in_collection(self) -> set[str]:
        active_character_ids: set[str] = set()
        for dungeon in self._dungeons:
            state = dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                character_id = str(item_data.get("linked_character_id") or "").strip()
                if character_id:
                    active_character_ids.add(character_id)
        return active_character_ids

    def _cleanup_unlinked_managed_character_artifacts(self) -> None:
        try:
            from player_sheets import cleanup_managed_linked_entries
        except Exception:
            return
        active_character_ids = self._active_linked_character_ids_in_collection()
        try:
            removed = int(cleanup_managed_linked_entries(active_character_ids))
        except Exception as exc:
            self._append_server_log(
                f"[WARN] Failed to clean up unlinked managed character artifacts: {exc}"
            )
            return
        if removed > 0:
            self._append_server_log(
                f"[INFO] Removed {removed} unlinked managed character artifact(s)."
            )

    def _linked_item_document_library_path_by_id(self, item_id: str) -> Path | None:
        clean_item_id = str(item_id or "").strip()
        if not clean_item_id:
            return None
        root = items_dir()
        if not root.exists():
            return None
        for item_path in list_item_file_paths(root):
            payload = load_item_payload(item_path)
            if not isinstance(payload, dict):
                continue
            candidate_id = item_id_from_payload(payload, fallback_path=item_path)
            if candidate_id == clean_item_id:
                return item_path
        return None

    def _linked_item_document_by_id(self, item_id: str) -> dict | None:
        clean_item_id = str(item_id or "").strip()
        if not clean_item_id:
            return None
        library_path = self._linked_item_document_library_path_by_id(clean_item_id)
        if library_path is not None:
            document = load_item_document(library_path)
            if isinstance(document, dict):
                return document
        return None

    def _authoritative_item_document_for_item_id(
        self,
        item_id: str,
        *,
        inventory_payload: dict | None = None,
    ) -> dict | None:
        clean_item_id = str(item_id or "").strip()
        if not clean_item_id:
            return None
        inventory_documents = _inventory_payload_item_documents(inventory_payload or {})
        authoritative_document = inventory_documents.get(clean_item_id)
        if not isinstance(authoritative_document, dict):
            authoritative_document = self._linked_item_document_by_id(clean_item_id)
        if not isinstance(authoritative_document, dict):
            return None
        return self._clone_item_document_with_item_id(authoritative_document, clean_item_id)

    def _clone_item_document_with_item_id(self, document: dict, item_id: str) -> dict:
        cloned = json.loads(json.dumps(document))
        payload = cloned.get("payload")
        if not isinstance(payload, dict):
            payload = {}
            cloned["payload"] = payload
        payload["item_id"] = str(item_id or "").strip()
        if not str(payload.get("normalized_item_name") or "").strip():
            payload["normalized_item_name"] = normalize_item_name(
                payload.get("title") or payload.get("name") or item_id
            )
        cloned["format"] = ITEM_FILE_FORMAT
        return cloned

    def _linked_item_review_signature(self, entries: list[dict]) -> str:
        try:
            serialized = json.dumps(
                entries,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
        except Exception:
            serialized = str(entries)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _unknown_item_preview_entries(self, entries: list[dict]) -> list[dict]:
        preview_entries: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id") or "").strip()
            item_document = entry.get("item_document")
            if not item_id and isinstance(item_document, dict):
                payload = item_document.get("payload")
                if isinstance(payload, dict):
                    item_id = item_id_from_payload(payload)
            if not item_id:
                continue
            payload = item_document.get("payload") if isinstance(item_document, dict) else {}
            title = _resolve_human_item_title(
                item_id,
                title=entry.get("title"),
                name=payload.get("name") if isinstance(payload, dict) else "",
                normalized_name=payload.get("normalized_item_name") if isinstance(payload, dict) else "",
                fallback="Unknown Item",
            )
            preview_payload = {
                "entry_id": f"preview_{uuid.uuid4().hex}",
                "type": "item",
                "item_id": item_id,
                "title": title,
                "path": str(entry.get("path") or item_id),
            }
            if (
                isinstance(item_document, dict)
                and str(item_document.get("format") or "").strip().lower() == ITEM_FILE_FORMAT
                and isinstance(item_document.get("payload"), dict)
            ):
                preview_payload["item_document"] = dict(item_document)
            preview_entries.append(self._sanitize_loot_pool_entry(preview_payload))
        return preview_entries

    def _prompt_unknown_items_with_preview(
        self,
        *,
        title: str,
        heading: str,
        details: str,
        entries: list[dict],
        accept_label: str,
        reject_label: str,
        default_accept: bool = False,
    ) -> bool:
        if _in_test_env():
            return bool(default_accept)
        preview_entries = self._unknown_item_preview_entries(entries)
        if not preview_entries:
            return bool(default_accept)

        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowTitle(str(title or "Unknown Items"))
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        heading_label = QLabel(str(heading or "Unknown items require review."), dialog)
        heading_label.setWordWrap(True)
        layout.addWidget(heading_label)

        details_label = QLabel(str(details or ""), dialog)
        details_label.setWordWrap(True)
        layout.addWidget(details_label)

        list_widget = QListWidget(dialog)
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        list_widget.setMouseTracking(True)
        list_widget.viewport().setMouseTracking(True)
        self._install_loot_preview_tracking(list_widget)
        layout.addWidget(list_widget, 1)

        for preview_entry in preview_entries:
            row = QListWidgetItem(
                str(preview_entry.get("title") or preview_entry.get("item_id") or "Item"),
                list_widget,
            )
            row.setData(Qt.ItemDataRole.UserRole + 1, dict(preview_entry))
            icon_pixmap = self._loot_pool_icon_for_entry(preview_entry)
            if isinstance(icon_pixmap, QPixmap) and not icon_pixmap.isNull():
                row.setIcon(QIcon(icon_pixmap))

        buttons = QDialogButtonBox(parent=dialog)
        accept_button = buttons.addButton(str(accept_label or "Accept"), QDialogButtonBox.ButtonRole.AcceptRole)
        reject_button = buttons.addButton(str(reject_label or "Reject"), QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        decision = {"accepted": bool(default_accept)}

        def _show_preview(item: QListWidgetItem | None) -> None:
            if item is None:
                self._hide_loot_pool_preview()
                return
            self._show_loot_pool_preview_for_item(item, QCursor.pos())

        list_widget.currentItemChanged.connect(lambda current, _previous: _show_preview(current))
        list_widget.itemEntered.connect(_show_preview)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
            _show_preview(list_widget.currentItem())

        accept_button.clicked.connect(lambda: (decision.update(accepted=True), dialog.accept()))
        reject_button.clicked.connect(lambda: (decision.update(accepted=False), dialog.reject()))
        dialog.exec()
        self._hide_loot_pool_preview()
        return bool(decision.get("accepted"))

    def _review_active_unknown_linked_items_for_dm(
        self,
        *,
        player_id: str,
        character_id: str,
        sheet_name: str,
        inventory_payload: dict,
    ) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        incoming_documents = _inventory_payload_item_documents(normalized)
        unresolved_entries: list[dict] = []
        for item_id in self._inventory_referenced_item_ids(normalized):
            if self._linked_item_document_by_id(item_id) is not None:
                continue
            incoming_document = incoming_documents.get(item_id)
            payload = incoming_document.get("payload") if isinstance(incoming_document, dict) else {}
            title = _resolve_human_item_title(
                item_id,
                title=payload.get("title") if isinstance(payload, dict) else "",
                name=payload.get("name") if isinstance(payload, dict) else "",
                normalized_name=payload.get("normalized_item_name") if isinstance(payload, dict) else "",
                fallback="Unknown Item",
            )
            unresolved_entries.append(
                {
                    "item_id": item_id,
                    "title": title or item_id,
                    "item_document": dict(incoming_document) if isinstance(incoming_document, dict) else None,
                }
            )
        if not unresolved_entries:
            return
        review_signature = self._linked_item_review_signature(unresolved_entries)
        review_cache_key = (
            f"active_unknown::{str(player_id or '').strip()}::"
            f"{str(character_id or '').strip()}::{review_signature}"
        )
        cached = self._host_unknown_item_review_cache.get(review_cache_key)
        if isinstance(cached, dict):
            cached_action = str(cached.get("action") or "").strip().lower()
            if cached_action in {"import", "dismiss"}:
                return
        action = "dismiss"
        if _in_test_env():
            action = "dismiss"
        else:
            accepted = self._prompt_unknown_items_with_preview(
                title="Unknown Character Items",
                heading=(
                    f"'{sheet_name or character_id or 'Character'}' contains items "
                    "unknown to the DM item library."
                ),
                details="Copy these item definitions into DM local storage?",
                entries=unresolved_entries,
                accept_label="Copy To DM Storage",
                reject_label="Dismiss",
                default_accept=False,
            )
            action = "import" if accepted else "dismiss"
        if action == "import":
            persisted_item_ids, unresolved_item_ids, import_messages = self._persist_item_documents_to_local_library(
                unresolved_entries,
                overwrite_existing=True,
            )
            if import_messages:
                self._append_server_log(f"[WARN] {' '.join(import_messages)}")
            if unresolved_item_ids:
                self._append_server_log(
                    "[WARN] Unknown linked item definitions were not persisted into DM storage. "
                    "The review prompt will reappear until persistence succeeds or is dismissed."
                )
                return
            self._append_server_log(
                f"[INFO] Imported {len(persisted_item_ids)} unknown linked item definition(s) into DM storage."
            )
        else:
            self._append_server_log(
                "[INFO] Dismissed unknown linked item definitions for DM-local storage."
            )
        self._host_unknown_item_review_cache[review_cache_key] = {
            "action": action,
            "signature": review_signature,
        }

    def _unknown_linked_item_entries(
        self,
        inventory_payload: dict,
        *,
        existing_inventory: dict | None = None,
    ) -> list[dict]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        incoming_documents = _inventory_payload_item_documents(normalized)
        existing_documents = _inventory_payload_item_documents(existing_inventory or {})
        item_ids: list[str] = []
        seen: set[str] = set()
        inventory_rows = normalized.get("inventory")
        if isinstance(inventory_rows, list):
            for entry in inventory_rows:
                item_id = _inventory_entry_item_id(entry)
                if item_id and item_id not in seen:
                    item_ids.append(item_id)
                    seen.add(item_id)
        equipment_rows = normalized.get("equipment")
        if isinstance(equipment_rows, dict):
            for value in equipment_rows.values():
                item_id = _inventory_entry_item_id(value)
                if item_id and item_id not in seen:
                    item_ids.append(item_id)
                    seen.add(item_id)

        unresolved: list[dict] = []
        for item_id in item_ids:
            existing_document = existing_documents.get(item_id)
            library_document = self._linked_item_document_by_id(item_id)
            incoming_document = incoming_documents.get(item_id)
            authoritative_document = library_document or existing_document
            if (
                authoritative_document is not None
                and incoming_document is not None
                and not item_document_matches(authoritative_document, incoming_document)
            ):
                payload = incoming_document.get("payload") if isinstance(incoming_document, dict) else {}
                title = _resolve_human_item_title(
                    item_id,
                    title=payload.get("title") if isinstance(payload, dict) else "",
                    name=payload.get("name") if isinstance(payload, dict) else "",
                    normalized_name=payload.get("normalized_item_name") if isinstance(payload, dict) else "",
                    fallback="Unknown Item",
                )
                unresolved.append(
                    {
                        "item_id": item_id,
                        "title": title or item_id,
                        "path": "",
                        "item_document": dict(incoming_document),
                        "authority_document": dict(authoritative_document),
                        "conflicts_with_authority": True,
                    }
                )
                continue
            if authoritative_document is not None:
                continue
            payload = incoming_document.get("payload") if isinstance(incoming_document, dict) else {}
            title = _resolve_human_item_title(
                item_id,
                title=payload.get("title") if isinstance(payload, dict) else "",
                name=payload.get("name") if isinstance(payload, dict) else "",
                normalized_name=payload.get("normalized_item_name") if isinstance(payload, dict) else "",
                fallback="Unknown Item",
            )
            unresolved.append(
                {
                    "item_id": item_id,
                    "title": title or item_id,
                    "path": "",
                    "item_document": dict(incoming_document) if isinstance(incoming_document, dict) else None,
                    "authority_document": None,
                    "conflicts_with_authority": False,
                }
            )
        return unresolved

    def _remove_item_ids_from_inventory_payload(
        self,
        inventory_payload: dict,
        *,
        removed_item_ids: set[str],
    ) -> dict:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        remove_ids = {
            str(item_id or "").strip()
            for item_id in removed_item_ids
            if str(item_id or "").strip()
        }
        if not remove_ids:
            return normalized
        inventory_rows = normalized.get("inventory")
        if isinstance(inventory_rows, list):
            normalized["inventory"] = [
                dict(entry)
                for entry in inventory_rows
                if isinstance(entry, dict)
                and str(entry.get("item_id") or "").strip() not in remove_ids
            ]
        equipment_rows = normalized.get("equipment")
        if isinstance(equipment_rows, dict):
            updated_equipment: dict[str, dict | None] = {}
            for slot_id, value in equipment_rows.items():
                item_id = _inventory_entry_item_id(value)
                if item_id and item_id in remove_ids:
                    updated_equipment[str(slot_id)] = None
                elif isinstance(value, dict):
                    updated_equipment[str(slot_id)] = dict(value)
                else:
                    updated_equipment[str(slot_id)] = None
            normalized["equipment"] = updated_equipment
        item_documents = _inventory_payload_item_documents(normalized)
        normalized["item_documents"] = {
            item_id: document
            for item_id, document in item_documents.items()
            if item_id not in remove_ids
        }
        return normalize_inventory_payload(normalized)

    def _import_linked_item_documents_to_dm_library(
        self,
        entries: list[dict],
        *,
        overwrite_existing: bool = False,
    ) -> tuple[int, list[str]]:
        imported = 0
        messages: list[str] = []
        library_root = items_dir()
        library_root.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id") or "").strip()
            item_document = entry.get("item_document")
            if not item_id or not isinstance(item_document, dict):
                messages.append(f"Unable to import '{item_id or 'item'}' because its item document is missing.")
                continue
            item_document = self._clone_item_document_with_item_id(item_document, item_id)
            existing_document = self._linked_item_document_by_id(item_id)
            target_path = self._linked_item_document_library_path_by_id(item_id)
            if existing_document is not None and not overwrite_existing:
                continue
            if target_path is None:
                try:
                    digest = hashlib.sha256(
                        json.dumps(
                            item_document,
                            sort_keys=True,
                            separators=(",", ":"),
                            ensure_ascii=False,
                        ).encode("utf-8")
                    ).hexdigest()[:16]
                except Exception:
                    digest = _sanitize_filename(item_id, "item")
                target_name = f"{_sanitize_filename(item_id, 'item')}_{digest}{ITEM_FILE_EXTENSION}"
                target_path = library_root / target_name
            try:
                write_item_document(target_path, item_document)
                imported += 1
                self._loot_pool_item_path_by_id[item_id] = target_path
            except Exception as exc:
                messages.append(f"Failed to import '{item_id}': {exc}")
        return imported, messages

    def _persist_item_documents_to_local_library(
        self,
        entries: list[dict],
        *,
        overwrite_existing: bool = False,
    ) -> tuple[list[str], list[str], list[str]]:
        requested_item_ids: list[str] = []
        seen_item_ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id") or "").strip()
            if not item_id or item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            requested_item_ids.append(item_id)

        _imported_count, messages = self._import_linked_item_documents_to_dm_library(
            entries,
            overwrite_existing=overwrite_existing,
        )
        persisted_item_ids: list[str] = []
        unresolved_item_ids: list[str] = []
        for item_id in requested_item_ids:
            if self._linked_item_document_by_id(item_id) is not None:
                persisted_item_ids.append(item_id)
            else:
                unresolved_item_ids.append(item_id)
        if unresolved_item_ids:
            preview = ", ".join(unresolved_item_ids[:3])
            suffix = "..." if len(unresolved_item_ids) > 3 else ""
            messages = list(messages)
            messages.append(
                "Unable to verify persistence for "
                f"{len(unresolved_item_ids)} item definition(s) in the local item library: "
                f"{preview}{suffix}"
            )
        return persisted_item_ids, unresolved_item_ids, list(messages)

    def _review_unknown_linked_items(
        self,
        *,
        player_id: str,
        character_id: str,
        sheet_name: str,
        entries: list[dict],
    ) -> dict:
        signature = self._linked_item_review_signature(entries)
        cache_key = f"{str(player_id or '').strip()}::{str(character_id or '').strip()}::{signature}"
        cached = self._host_unknown_item_review_cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)
        if _in_test_env():
            decision = {
                "action": "import",
                "selected_item_ids": [
                    str(entry.get("item_id") or "").strip()
                    for entry in entries
                    if str(entry.get("item_id") or "").strip()
                ],
                "signature": signature,
            }
            self._host_unknown_item_review_cache[cache_key] = dict(decision)
            return decision

        dialog = QDialog(self)
        dialog.setWindowTitle("Unknown Character Items")
        dialog.setModal(True)
        dialog.setMinimumWidth(520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        heading = QLabel(
            f"'{sheet_name or character_id or 'Character'}' contains item definitions that need DM review.",
            dialog,
        )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        info = QLabel(
            "Select one or more items to import into the DM item library, keep the DM version for conflicts, "
            "or remove them from the incoming character update. You can also kick the player "
            "to reject the entire update.",
            dialog,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        list_widget = QListWidget(dialog)
        list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        list_widget.setMouseTracking(True)
        list_widget.viewport().setMouseTracking(True)
        self._install_loot_preview_tracking(list_widget)
        layout.addWidget(list_widget, 1)

        for entry in entries:
            row_payload = self._sanitize_loot_pool_entry(
                {
                    "entry_id": str(entry.get("entry_id") or uuid.uuid4().hex),
                    "type": "item",
                    "item_id": str(entry.get("item_id") or ""),
                    "title": str(entry.get("title") or ""),
                    "path": str(entry.get("path") or entry.get("item_id") or ""),
                    "item_document": entry.get("item_document"),
                }
            )
            row_entry = dict(entry)
            row_entry.update(row_payload)
            row = QListWidgetItem(str(row_entry.get("title") or row_entry.get("item_id") or "Item"))
            row.setData(Qt.ItemDataRole.UserRole, str(row_entry.get("item_id") or ""))
            row.setData(Qt.ItemDataRole.UserRole + 1, row_entry)
            icon_pixmap = self._loot_pool_icon_for_entry(row_entry)
            if isinstance(icon_pixmap, QPixmap) and not icon_pixmap.isNull():
                row.setIcon(QIcon(icon_pixmap))
            list_widget.addItem(row)
        if list_widget.count() > 0:
            list_widget.setCurrentRow(0)
            for index in range(list_widget.count()):
                row = list_widget.item(index)
                row_entry = row.data(Qt.ItemDataRole.UserRole + 1)
                if isinstance(row_entry, dict) and not bool(row_entry.get("conflicts_with_authority")):
                    row.setSelected(True)

        buttons = QDialogButtonBox(parent=dialog)
        import_button = buttons.addButton("Import Selected", QDialogButtonBox.ButtonRole.AcceptRole)
        select_all_button = buttons.addButton("Select All", QDialogButtonBox.ButtonRole.ActionRole)
        use_authority_button = buttons.addButton("Keep DM Version", QDialogButtonBox.ButtonRole.ActionRole)
        remove_button = buttons.addButton("Remove Selected", QDialogButtonBox.ButtonRole.DestructiveRole)
        kick_button = buttons.addButton("Kick Player", QDialogButtonBox.ButtonRole.RejectRole)
        layout.addWidget(buttons)

        decision: dict[str, object] = {"action": "blocked", "selected_item_ids": [], "signature": signature}

        def _selected_item_ids() -> list[str]:
            selected: list[str] = []
            for item in list_widget.selectedItems():
                item_id = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
                if item_id:
                    selected.append(item_id)
            return selected

        def _sync_buttons() -> None:
            selected_rows = list_widget.selectedItems()
            has_selection = bool(selected_rows)
            has_conflict_selection = False
            for selected_row in selected_rows:
                row_entry = selected_row.data(Qt.ItemDataRole.UserRole + 1)
                if isinstance(row_entry, dict) and bool(row_entry.get("conflicts_with_authority")):
                    has_conflict_selection = True
                    break
            import_button.setEnabled(has_selection)
            use_authority_button.setEnabled(has_conflict_selection)
            remove_button.setEnabled(has_selection)

        def _show_preview(item: QListWidgetItem | None) -> None:
            if item is None:
                self._hide_loot_pool_preview()
                return
            self._show_loot_pool_preview_for_item(item, QCursor.pos())

        list_widget.itemSelectionChanged.connect(_sync_buttons)
        list_widget.currentItemChanged.connect(lambda current, _previous: _show_preview(current))
        list_widget.itemEntered.connect(_show_preview)
        _sync_buttons()

        def _choose(action: str) -> None:
            decision["action"] = action
            decision["selected_item_ids"] = _selected_item_ids()
            dialog.accept()

        import_button.clicked.connect(lambda: _choose("import"))
        select_all_button.clicked.connect(list_widget.selectAll)
        use_authority_button.clicked.connect(lambda: _choose("use_authority"))
        remove_button.clicked.connect(lambda: _choose("remove"))
        kick_button.clicked.connect(lambda: _choose("kick"))
        dialog.exec()
        self._hide_loot_pool_preview()

        resolved = {
            "action": str(decision.get("action") or "blocked"),
            "selected_item_ids": [
                str(item_id or "").strip()
                for item_id in decision.get("selected_item_ids", [])
                if str(item_id or "").strip()
            ],
            "signature": signature,
        }
        if resolved["action"] in {"blocked", "remove", "kick"}:
            self._host_unknown_item_review_cache[cache_key] = dict(resolved)
        return resolved

    def _resolve_unknown_linked_items_for_host(
        self,
        *,
        player_id: str,
        character_id: str,
        sheet_name: str,
        inventory_payload: dict,
        existing_inventory: dict | None = None,
    ) -> tuple[str, dict, str]:
        working_payload = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        status_note = ""
        while True:
            unresolved_entries = self._unknown_linked_item_entries(
                working_payload,
                existing_inventory=existing_inventory,
            )
            if not unresolved_entries:
                return "ok", working_payload, status_note
            review_signature = self._linked_item_review_signature(unresolved_entries)
            review_cache_key = (
                f"{str(player_id or '').strip()}::"
                f"{str(character_id or '').strip()}::"
                f"{review_signature}"
            )
            cached_decision = self._host_unknown_item_review_cache.get(review_cache_key)
            if isinstance(cached_decision, dict):
                decision = dict(cached_decision)
            else:
                decision = self._review_unknown_linked_items(
                    player_id=player_id,
                    character_id=character_id,
                    sheet_name=sheet_name,
                    entries=unresolved_entries,
                )
            action = str(decision.get("action") or "blocked").strip().lower()
            selected_item_ids = {
                str(item_id or "").strip()
                for item_id in decision.get("selected_item_ids", [])
                if str(item_id or "").strip()
            }
            if action == "kick":
                return "kick", working_payload, "DM rejected unknown linked items and removed the player."
            if action == "remove" and selected_item_ids:
                working_payload = self._remove_item_ids_from_inventory_payload(
                    working_payload,
                    removed_item_ids=selected_item_ids,
                )
                status_note = "Removed unapproved linked items from the incoming character update."
                continue
            if action == "use_authority" and selected_item_ids:
                working_payload = self._apply_authoritative_item_documents_to_inventory_payload(
                    working_payload,
                    item_ids=selected_item_ids,
                    existing_inventory=existing_inventory,
                )
                status_note = "Kept DM-authoritative definitions for conflicting linked items."
                continue
            if action == "import" and selected_item_ids:
                selected_entries = [
                    entry
                    for entry in unresolved_entries
                    if str(entry.get("item_id") or "").strip() in selected_item_ids
                ]
                persisted_item_ids, unresolved_item_ids, import_messages = self._persist_item_documents_to_local_library(
                    selected_entries,
                    overwrite_existing=True,
                )
                if import_messages:
                    self._append_server_log(f"[WARN] {' '.join(import_messages)}")
                if unresolved_item_ids:
                    self._host_unknown_item_review_cache[review_cache_key] = {
                        "action": "blocked",
                        "selected_item_ids": sorted(selected_item_ids),
                        "signature": review_signature,
                    }
                    return "blocked", working_payload, "Linked item review is still unresolved."
                status_note = (
                    f"Imported {len(persisted_item_ids)} selected linked item(s) into the DM library."
                )
                continue
            self._host_unknown_item_review_cache[review_cache_key] = {
                "action": "blocked",
                "selected_item_ids": sorted(selected_item_ids),
                "signature": review_signature,
            }
            return "blocked", working_payload, "Linked item review is still unresolved."

    def _canonicalize_linked_inventory_payload(
        self,
        inventory_payload: dict,
        *,
        existing_inventory: dict | None = None,
    ) -> tuple[dict, list[str]]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        referenced_item_ids: list[str] = []
        seen_item_ids: set[str] = set()
        for entry in normalized.get("inventory", []) if isinstance(normalized.get("inventory"), list) else []:
            item_id = _inventory_entry_item_id(entry)
            if item_id and item_id not in seen_item_ids:
                referenced_item_ids.append(item_id)
                seen_item_ids.add(item_id)
        equipment_payload = normalized.get("equipment")
        if isinstance(equipment_payload, dict):
            for value in equipment_payload.values():
                item_id = _inventory_entry_item_id(value)
                if item_id and item_id not in seen_item_ids:
                    referenced_item_ids.append(item_id)
                    seen_item_ids.add(item_id)

        incoming_documents = _inventory_payload_item_documents(normalized)
        existing_documents = _inventory_payload_item_documents(existing_inventory or {})
        authoritative_by_id: dict[str, dict] = {}
        authoritative_by_fingerprint: dict[str, tuple[str, dict]] = {}
        for source_item_id, source_document in existing_documents.items():
            authoritative_by_id.setdefault(source_item_id, source_document)
            try:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        source_document,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
            except Exception:
                fingerprint = ""
            if fingerprint and fingerprint not in authoritative_by_fingerprint:
                authoritative_by_fingerprint[fingerprint] = (source_item_id, source_document)
        remap: dict[str, str] = {}
        canonical_documents: dict[str, dict] = {}
        notes: list[str] = []

        for item_id in referenced_item_ids:
            existing_document = existing_documents.get(item_id)
            library_document = self._linked_item_document_by_id(item_id)
            incoming_document = incoming_documents.get(item_id)
            chosen_item_id = item_id
            chosen_document = library_document or existing_document
            if chosen_document is not None:
                if incoming_document is not None and not item_document_matches(chosen_document, incoming_document):
                    notes.append(
                        f"Kept the DM-authoritative item definition for '{item_id}' instead of the conflicting player version."
                    )
                elif incoming_document is None and library_document is None and existing_document is None:
                    notes.append(
                        f"Missing authoritative item document for linked item '{item_id}'."
                    )
            elif incoming_document is not None:
                notes.append(
                    f"Missing authoritative item document for linked item '{item_id}'."
                )
                continue
            else:
                notes.append(
                    f"Missing authoritative item document for linked item '{item_id}'."
                )
                continue

            if not isinstance(chosen_document, dict):
                continue
            remap[item_id] = chosen_item_id
            canonical_documents[chosen_item_id] = chosen_document
            authoritative_by_id[chosen_item_id] = chosen_document
            try:
                fingerprint = hashlib.sha256(
                    json.dumps(
                        chosen_document,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                    ).encode("utf-8")
                ).hexdigest()
            except Exception:
                fingerprint = ""
            if fingerprint:
                authoritative_by_fingerprint[fingerprint] = (chosen_item_id, chosen_document)

        if remap:
            inventory_rows = normalized.get("inventory")
            if isinstance(inventory_rows, list):
                for entry in inventory_rows:
                    if not isinstance(entry, dict):
                        continue
                    item_id = str(entry.get("item_id") or "").strip()
                    if item_id in remap:
                        entry["item_id"] = remap[item_id]
            equipment_rows = normalized.get("equipment")
            if isinstance(equipment_rows, dict):
                for slot_id, value in list(equipment_rows.items()):
                    if not isinstance(value, dict):
                        continue
                    item_id = str(value.get("item_id") or "").strip()
                    if item_id in remap:
                        updated_value = dict(value)
                        updated_value["item_id"] = remap[item_id]
                        equipment_rows[slot_id] = updated_value

        normalized["item_documents"] = canonical_documents
        return normalize_inventory_payload(normalized), notes

    def _unknown_local_inventory_item_entries(self, inventory_payload: dict) -> list[dict]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        incoming_documents = _inventory_payload_item_documents(normalized)
        inventory_quantities: dict[str, int] = {}
        equipment_slots: dict[str, list[str]] = {}
        item_order: list[str] = []
        seen_item_ids: set[str] = set()

        inventory_rows = normalized.get("inventory")
        if isinstance(inventory_rows, list):
            for entry in inventory_rows:
                item_id = _inventory_entry_item_id(entry)
                if not item_id:
                    continue
                inventory_quantities[item_id] = inventory_quantities.get(item_id, 0) + _inventory_entry_quantity(entry)
                if item_id not in seen_item_ids:
                    item_order.append(item_id)
                    seen_item_ids.add(item_id)
        equipment_rows = normalized.get("equipment")
        if isinstance(equipment_rows, dict):
            for slot_id, value in equipment_rows.items():
                item_id = _inventory_entry_item_id(value)
                if not item_id:
                    continue
                equipment_slots.setdefault(item_id, []).append(str(slot_id or "").strip() or "slot")
                if item_id not in seen_item_ids:
                    item_order.append(item_id)
                    seen_item_ids.add(item_id)

        unknown_entries: list[dict] = []
        for item_id in item_order:
            if self._linked_item_document_by_id(item_id) is not None:
                continue
            incoming_document = incoming_documents.get(item_id)
            payload = incoming_document.get("payload") if isinstance(incoming_document, dict) else {}
            title = _resolve_human_item_title(
                item_id,
                title=payload.get("title") if isinstance(payload, dict) else "",
                name=payload.get("name") if isinstance(payload, dict) else "",
                normalized_name=payload.get("normalized_item_name") if isinstance(payload, dict) else "",
                fallback="Unknown Item",
            )
            unknown_entries.append(
                {
                    "item_id": item_id,
                    "title": title or item_id,
                    "quantity": int(inventory_quantities.get(item_id, 0)),
                    "equipment_slots": list(equipment_slots.get(item_id, [])),
                    "item_document": dict(incoming_document) if isinstance(incoming_document, dict) else None,
                }
            )
        return unknown_entries

    def _convert_unknown_inventory_items_to_notes(
        self,
        inventory_payload: dict,
        entries: list[dict],
    ) -> tuple[dict, list[str]]:
        remove_ids = {
            str(entry.get("item_id") or "").strip()
            for entry in entries
            if isinstance(entry, dict) and str(entry.get("item_id") or "").strip()
        }
        if not remove_ids:
            return normalize_inventory_payload(inventory_payload), []
        normalized = self._remove_item_ids_from_inventory_payload(
            inventory_payload,
            removed_item_ids=remove_ids,
        )
        existing_notes = [
            str(line or "").strip()
            for line in str(normalized.get("inventory_notes") or "").splitlines()
            if str(line or "").strip()
        ]
        added_notes: list[str] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            item_id = str(entry.get("item_id") or "").strip()
            if not item_id:
                continue
            title = str(entry.get("title") or item_id).strip() or item_id
            try:
                quantity = max(0, int(entry.get("quantity") or 0))
            except (TypeError, ValueError):
                quantity = 0
            raw_slots = entry.get("equipment_slots")
            slot_labels: list[str] = []
            if isinstance(raw_slots, list):
                for slot in raw_slots:
                    clean_slot = str(slot or "").strip()
                    if not clean_slot:
                        continue
                    slot_labels.append(clean_slot.replace("_", " ").title())
            if quantity > 0 and slot_labels:
                note = (
                    f"Unknown synced item '{title}' x{quantity} (equipment: {', '.join(slot_labels)})."
                )
            elif quantity > 0:
                note = f"Unknown synced item '{title}' x{quantity}."
            elif slot_labels:
                note = f"Unknown synced equipment '{title}' ({', '.join(slot_labels)})."
            else:
                note = f"Unknown synced item '{title}'."
            added_notes.append(note)
        if added_notes:
            normalized["inventory_notes"] = "\n".join(existing_notes + added_notes)
        return normalize_inventory_payload(normalized), added_notes

    def _prepare_incoming_host_inventory_for_local_sync(
        self,
        *,
        inventory_payload: dict,
        sheet_name: str,
        character_id: str,
    ) -> tuple[dict, list[str]]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        unknown_entries = self._unknown_local_inventory_item_entries(normalized)
        if not unknown_entries:
            return normalized, []

        should_import = self._prompt_unknown_items_with_preview(
            title="Unknown Character Items",
            heading=(
                f"'{sheet_name or character_id or 'Character'}' includes items your local library does not know."
            ),
            details=(
                "Copy these item definitions into your local items folder?\n"
                "If not, these unknown items will be converted into inventory notes."
            ),
            entries=unknown_entries,
            accept_label="Copy To Local Items",
            reject_label="Convert To Notes",
            default_accept=True,
        )

        if should_import:
            _persisted_item_ids, unresolved_item_ids, import_messages = self._persist_item_documents_to_local_library(
                unknown_entries,
                overwrite_existing=True,
            )
            if import_messages:
                self._append_server_log(f"[WARN] {' '.join(import_messages)}")
            if not unresolved_item_ids:
                return normalized, []
            entries_to_convert = [
                entry
                for entry in unknown_entries
                if str(entry.get("item_id") or "").strip() in set(unresolved_item_ids)
            ]
            converted_payload, notes = self._convert_unknown_inventory_items_to_notes(
                normalized,
                entries_to_convert,
            )
            self._append_server_log(
                "[WARN] Some unknown synced items could not be copied into the local item library "
                "and were converted into inventory notes instead."
            )
            return converted_payload, notes
        entries_to_convert = list(unknown_entries)
        converted_payload, notes = self._convert_unknown_inventory_items_to_notes(
            normalized,
            entries_to_convert,
        )
        return converted_payload, notes

    def _local_character_replace_options(self) -> list[dict]:
        try:
            from player_sheets import character_id_for_entry, list_character_link_targets, sheet_id_for_entry
        except Exception:
            return []
        options: list[dict] = []
        seen_sheet_ids: set[str] = set()
        for entry in list_character_link_targets():
            try:
                sheet_id = str(sheet_id_for_entry(entry) or "").strip()
                if not sheet_id or sheet_id in seen_sheet_ids:
                    continue
                sheet_name = str(getattr(entry, "name", "") or sheet_id).strip() or sheet_id
                character_id = str(character_id_for_entry(entry) or "").strip() or self._character_id_for_sheet(
                    sheet_id,
                    sheet_name=sheet_name,
                )
            except Exception:
                continue
            options.append(
                {
                    "sheet_id": sheet_id,
                    "sheet_name": sheet_name,
                    "character_id": character_id,
                    "label": f"{sheet_name} ({sheet_id})",
                }
            )
            seen_sheet_ids.add(sheet_id)
        return sorted(
            options,
            key=lambda option: str(option.get("sheet_name") or option.get("sheet_id") or "").lower(),
        )

    def _prompt_missing_local_linked_character_resolution(
        self,
        *,
        sheet_id: str,
        sheet_name: str,
        character_id: str,
        replace_options: list[dict],
    ) -> tuple[str, str]:
        if _in_test_env():
            return "save_local", ""

        dialog = QDialog(self)
        dialog.setModal(True)
        dialog.setWindowTitle("Linked Character Not Found Locally")
        dialog.setMinimumWidth(560)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        linked_name = str(sheet_name or sheet_id or character_id or "Character").strip()
        linked_sheet = str(sheet_id or "").strip()
        linked_character = str(character_id or "").strip()
        summary = QLabel(
            (
                f"This entity is linked to '{linked_name}', but that character is not available locally.\n\n"
                f"Sheet: {linked_sheet or 'unknown'}\n"
                f"Character id: {linked_character or 'unknown'}\n\n"
                "Choose how to resolve this link:"
            ),
            dialog,
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        choice: dict[str, str] = {"action": "", "sheet_id": ""}

        save_btn = QPushButton("Save Character Locally", dialog)
        save_btn.setObjectName("SecondaryButton")
        save_btn.setMinimumHeight(36)
        save_btn.clicked.connect(
            lambda: (choice.update(action="save_local", sheet_id=""), dialog.accept())
        )
        layout.addWidget(save_btn)

        replace_row = QHBoxLayout()
        replace_row.setSpacing(8)
        replace_btn = QPushButton("Replace With Character", dialog)
        replace_btn.setObjectName("SecondaryButton")
        replace_btn.setMinimumHeight(36)
        replace_combo = QComboBox(dialog)
        replace_combo.setMinimumHeight(36)
        replace_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        for option in replace_options:
            replace_combo.addItem(
                str(option.get("label") or option.get("sheet_name") or option.get("sheet_id") or ""),
                str(option.get("sheet_id") or ""),
            )
        if replace_combo.count() <= 0:
            replace_combo.addItem("No local characters available", "")
            replace_combo.setEnabled(False)
            replace_btn.setEnabled(False)

        def _choose_replace() -> None:
            selected_sheet = str(replace_combo.currentData() or "").strip()
            if not selected_sheet:
                return
            choice.update(action="replace", sheet_id=selected_sheet)
            dialog.accept()

        replace_btn.clicked.connect(_choose_replace)
        replace_row.addWidget(replace_btn)
        replace_row.addWidget(replace_combo, 1)
        layout.addLayout(replace_row)

        unlink_btn = QPushButton("Unlink Character", dialog)
        unlink_btn.setObjectName("SecondaryButton")
        unlink_btn.setMinimumHeight(36)
        unlink_btn.clicked.connect(
            lambda: (choice.update(action="unlink", sheet_id=""), dialog.accept())
        )
        layout.addWidget(unlink_btn)

        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, parent=dialog)
        controls.rejected.connect(dialog.reject)
        layout.addWidget(controls)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "", ""
        return str(choice.get("action") or "").strip(), str(choice.get("sheet_id") or "").strip()

    def _local_link_sync_payload_for_sheet(
        self,
        sheet_id: str,
        *,
        fallback_sheet_name: str = "",
    ) -> tuple[dict | None, str]:
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return None, "Missing character selection."
        try:
            from player_sheets import character_id_for_sheet_id
        except Exception:
            character_id_for_sheet_id = None  # type: ignore[assignment]
        sheet_name_hint = str(fallback_sheet_name or clean_sheet).strip() or clean_sheet
        character_id = ""
        if character_id_for_sheet_id is not None:
            character_id = str(character_id_for_sheet_id(clean_sheet) or "").strip()
        if not character_id:
            character_id = self._character_id_for_sheet(clean_sheet, sheet_name=sheet_name_hint)
        local_payload = self._resolve_local_sheet_sync_payload(character_id)
        if not isinstance(local_payload, dict):
            return None, "Unable to load selected local character data."
        archive_b64 = str(local_payload.get("archive_b64") or "").strip()
        if not archive_b64:
            return (
                None,
                "Selected local character archive is missing. Open and save that character first.",
            )
        return {
            "sheet_id": str(local_payload.get("sheet_id") or clean_sheet).strip() or clean_sheet,
            "sheet_name": str(local_payload.get("sheet_name") or sheet_name_hint).strip() or sheet_name_hint,
            "character_id": str(local_payload.get("character_id") or character_id).strip() or character_id,
            "save_revision": int(local_payload.get("save_revision") or 0),
            "last_saved_at": str(local_payload.get("last_saved_at") or ""),
            "content_hash": str(local_payload.get("content_hash") or ""),
            "inventory": normalize_inventory_payload(local_payload.get("inventory") or {}),
            "stats": dict(local_payload.get("stats") or {}),
            "archive_b64": archive_b64,
        }, ""

    def _request_replace_missing_local_character_link(
        self,
        *,
        entity_id: str,
        replacement_sheet_id: str,
        dungeon_id: str,
        fallback_sheet_name: str,
    ) -> tuple[bool, str]:
        local_payload, error = self._local_link_sync_payload_for_sheet(
            replacement_sheet_id,
            fallback_sheet_name=fallback_sheet_name,
        )
        if not isinstance(local_payload, dict):
            return False, str(error or "Unable to load selected local character.")
        request_payload = {
            "entity_id": str(entity_id or "").strip(),
            "sheet_id": str(local_payload.get("sheet_id") or "").strip(),
            "sheet_name": str(local_payload.get("sheet_name") or "").strip(),
            "character_id": str(local_payload.get("character_id") or "").strip(),
            "save_revision": int(local_payload.get("save_revision") or 0),
            "last_saved_at": str(local_payload.get("last_saved_at") or ""),
            "content_hash": str(local_payload.get("content_hash") or ""),
            "inventory": normalize_inventory_payload(local_payload.get("inventory") or {}),
            "stats": dict(local_payload.get("stats") or {}),
            "archive_b64": str(local_payload.get("archive_b64") or ""),
            "dungeon_id": str(dungeon_id or self._active_dungeon_id or ""),
        }
        if not self._dispatch_player_link_character_request(request_payload):
            return False, "Unable to request linked character replacement."
        return True, "Requested replacement with local character."

    def _request_unlink_missing_local_character_link(
        self,
        *,
        entity_id: str,
        dungeon_id: str,
    ) -> tuple[bool, str]:
        request_payload = {
            "entity_id": str(entity_id or "").strip(),
            "dungeon_id": str(dungeon_id or self._active_dungeon_id or ""),
        }
        if not self._dispatch_player_unlink_character_request(request_payload):
            return False, "Unable to request character unlink."
        return True, "Requested character unlink."

    def _sync_local_sheet_inventory_from_host(
        self,
        character_id: str,
        inventory_payload: dict,
        *,
        sheet_name: str = "",
        archive_b64: str = "",
        save_revision: int = 0,
        last_saved_at: str = "",
        content_hash: str = "",
        refresh_entities: bool = True,
        sheet_id: str = "",
        entity_id: str = "",
        dungeon_id: str = "",
    ) -> tuple[bool, str]:
        clean_character = str(character_id or "").strip()
        if not clean_character:
            return False, "Missing character id for inventory sync."
        clean_sheet = str(sheet_id or "").strip()
        clean_entity = str(entity_id or "").strip()
        clean_dungeon = str(dungeon_id or "").strip()
        local_sync_payload = self._resolve_local_sheet_sync_payload(clean_character)
        if local_sync_payload is None:
            try:
                from player_sheets import character_id_for_sheet_id
            except Exception:
                character_id_for_sheet_id = None  # type: ignore[assignment]
            if character_id_for_sheet_id is not None:
                mapped_character_id = str(character_id_for_sheet_id(clean_character) or "").strip()
                if mapped_character_id:
                    clean_character = mapped_character_id
                    local_sync_payload = self._resolve_local_sheet_sync_payload(clean_character)
        if (
            local_sync_payload is None
            and self._online_mode == ONLINE_MODE_PLAYER
            and clean_entity
        ):
            if self._has_pending_character_link_resolution_for_entity(clean_entity):
                return True, "Awaiting linked character relink/unlink response."
            replace_options = self._local_character_replace_options()
            action, replacement_sheet_id = self._prompt_missing_local_linked_character_resolution(
                sheet_id=clean_sheet,
                sheet_name=str(sheet_name or clean_sheet or clean_character),
                character_id=clean_character,
                replace_options=replace_options,
            )
            if action == "replace":
                return self._request_replace_missing_local_character_link(
                    entity_id=clean_entity,
                    replacement_sheet_id=replacement_sheet_id,
                    dungeon_id=clean_dungeon,
                    fallback_sheet_name=str(sheet_name or clean_sheet or clean_character),
                )
            if action == "unlink":
                return self._request_unlink_missing_local_character_link(
                    entity_id=clean_entity,
                    dungeon_id=clean_dungeon,
                )
            if action != "save_local":
                return True, "Linked character sync deferred by player."
        payload = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        fingerprint = self._inventory_payload_fingerprint(payload)
        local_revision = int(local_sync_payload.get("save_revision") or 0) if isinstance(local_sync_payload, dict) else 0
        local_last_saved_at = (
            str(local_sync_payload.get("last_saved_at") or "") if isinstance(local_sync_payload, dict) else ""
        )
        local_hash = str(local_sync_payload.get("content_hash") or "") if isinstance(local_sync_payload, dict) else ""
        resolved_save_revision = int(save_revision or 0)
        resolved_last_saved_at = str(last_saved_at or "")
        resolved_content_hash = str(content_hash or "")
        if (
            resolved_save_revision <= 0
            and not resolved_last_saved_at
            and not resolved_content_hash
            and isinstance(local_sync_payload, dict)
        ):
            resolved_save_revision = local_revision
            resolved_last_saved_at = local_last_saved_at
            resolved_content_hash = local_hash
        if (
            self._online_inventory_sync_fingerprints.get(clean_character) == fingerprint
            and local_revision == resolved_save_revision
            and local_hash == resolved_content_hash
        ):
            return True, "Inventory already synchronized."
        payload, converted_notes = self._prepare_incoming_host_inventory_for_local_sync(
            inventory_payload=payload,
            sheet_name=str(sheet_name or clean_character),
            character_id=clean_character,
        )
        if converted_notes:
            self._append_server_log(
                f"[INFO] Converted {len(converted_notes)} unknown synced item(s) into inventory notes."
            )
        try:
            from player_sheets import (
                apply_remote_character_package_for_character_id,
            )
        except Exception:
            return False, "Player sheets integration unavailable."
        archive_bytes: bytes | None = None
        clean_archive_b64 = str(archive_b64 or "").strip()
        if clean_archive_b64:
            try:
                archive_bytes = base64.b64decode(clean_archive_b64.encode("ascii"), validate=True)
            except Exception:
                return False, "Linked character archive payload is invalid."
        self._suppress_external_inventory_forward = True
        try:
            ok, message, saved_payload = apply_remote_character_package_for_character_id(
                clean_character,
                str(sheet_name or clean_character),
                payload,
                archive_bytes=archive_bytes,
                save_revision=resolved_save_revision,
                last_saved_at=resolved_last_saved_at,
                content_hash=resolved_content_hash,
                emit_event=True,
            )
        finally:
            self._suppress_external_inventory_forward = False
        if not ok:
            return False, str(message or "Unable to synchronize inventory.")
        saved = saved_payload if isinstance(saved_payload, dict) else dict(payload)
        self._online_inventory_sync_fingerprints[clean_character] = self._inventory_payload_fingerprint(saved)
        if refresh_entities:
            self._apply_inventory_sync_to_linked_entities(
                owner_player_id=str(self._local_player_id or ""),
                character_id=clean_character,
                inventory_payload=saved,
                save_revision=resolved_save_revision,
                last_saved_at=resolved_last_saved_at,
                content_hash=resolved_content_hash,
            )
        return True, "Inventory synchronized."

    def _local_character_sheet_exists(self, character_id: str) -> bool:
        clean_character = str(character_id or "").strip()
        if not clean_character:
            return False
        try:
            from player_sheets import character_id_for_entry, list_character_link_targets
        except Exception:
            return False
        for entry in list_character_link_targets():
            try:
                if character_id_for_entry(entry) == clean_character:
                    return True
            except Exception:
                continue
        return False

    def _resolve_local_sheet_sync_payload(self, character_id: str) -> dict | None:
        clean_character = str(character_id or "").strip()
        if not clean_character:
            return None
        try:
            import player_sheets as player_sheets_module
        except Exception:
            return None
        character_id_for_entry = getattr(player_sheets_module, "character_id_for_entry", None)
        list_character_link_targets = getattr(player_sheets_module, "list_character_link_targets", None)
        sheet_id_for_entry = getattr(player_sheets_module, "sheet_id_for_entry", None)
        inventory_payload_for_sheet_id = getattr(player_sheets_module, "inventory_payload_for_sheet_id", None)
        ensure_entry_archive = getattr(player_sheets_module, "ensure_entry_archive", None)
        character_sheet_pdf_path = getattr(player_sheets_module, "character_sheet_pdf_path", None)
        character_sheet_archive_path = getattr(player_sheets_module, "character_sheet_archive_path", None)
        archive_bytes_for_character_id = getattr(player_sheets_module, "archive_bytes_for_character_id", None)
        if not all(
            callable(fn)
            for fn in (
                character_id_for_entry,
                list_character_link_targets,
                sheet_id_for_entry,
                inventory_payload_for_sheet_id,
                character_sheet_pdf_path,
                character_sheet_archive_path,
            )
        ):
            return None

        target_entry = None
        for entry in list_character_link_targets():
            try:
                if character_id_for_entry(entry) == clean_character:
                    target_entry = entry
                    break
            except Exception:
                continue
        if target_entry is None:
            return None

        if callable(ensure_entry_archive):
            try:
                ensure_entry_archive(target_entry)
            except Exception:
                pass

        sheet_id = str(sheet_id_for_entry(target_entry) or "").strip()
        sheet_name = str(getattr(target_entry, "name", "") or clean_character).strip() or clean_character
        linked_inventory = normalize_inventory_payload(inventory_payload_for_sheet_id(sheet_id) or {})
        pdf_path_text = str(getattr(target_entry, "pdf_path", "") or "").strip()
        pdf_candidate = Path(pdf_path_text) if pdf_path_text else character_sheet_pdf_path(sheet_id)
        archive_path_text = str(getattr(target_entry, "archive_path", "") or "").strip()
        archive_candidate = (
            Path(archive_path_text) if archive_path_text else character_sheet_archive_path(sheet_id)
        )
        if pdf_candidate.suffix.lower() == ".dmtchar" or not pdf_candidate.exists():
            extracted_path = character_sheet_pdf_path(sheet_id)
            if archive_candidate.exists() and extract_character_pdf(archive_candidate, extracted_path):
                pdf_candidate = extracted_path
            elif extracted_path.exists():
                pdf_candidate = extracted_path

        stats = {}
        if pdf_candidate.exists():
            stats = _extract_character_stats_from_pdf(str(pdf_candidate))
        if not isinstance(stats, dict):
            stats = {}
        if not str(stats.get("name") or "").strip():
            stats["name"] = sheet_name
        archive_bytes = archive_bytes_for_character_id(clean_character) if callable(archive_bytes_for_character_id) else b""
        archive_b64 = (
            base64.b64encode(archive_bytes).decode("ascii")
            if archive_bytes
            else ""
        )

        return {
            "sheet_id": sheet_id,
            "sheet_name": sheet_name,
            "character_id": str(character_id_for_entry(target_entry) or "").strip()
            or self._character_id_for_sheet(sheet_id, sheet_name=sheet_name),
            "save_revision": int(getattr(target_entry, "save_revision", 0) or 0),
            "last_saved_at": str(getattr(target_entry, "last_saved_at", "") or "").strip(),
            "content_hash": str(getattr(target_entry, "content_hash", "") or "").strip(),
            "inventory": linked_inventory,
            "stats": stats,
            "archive_b64": archive_b64,
        }

    def _on_client_snapshot_received(self, snapshot: dict) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER:
            return
        self._hide_reconnect_status_dialog()
        was_waiting_for_snapshot = bool(self._awaiting_player_snapshot)
        self._awaiting_player_snapshot = False
        self._player_connection_ready = True
        self._apply_online_permissions()
        self._flush_pending_loot_claim_finalizations()

        def _sync_owned_sheet_inventories_from_snapshot() -> None:
            if self._online_mode != ONLINE_MODE_PLAYER:
                return
            local_player_id = str(self._local_player_id or "").strip()
            if not local_player_id:
                return
            host_state_by_character: dict[str, dict] = {}
            for dungeon in self._dungeons:
                state = dungeon.get("state")
                if not isinstance(state, dict):
                    continue
                items = state.get("items")
                if not isinstance(items, list):
                    continue
                for item_data in items:
                    if not isinstance(item_data, dict):
                        continue
                    if item_data.get("type") != "entity":
                        continue
                    if str(item_data.get("owner_player_id") or "").strip() != local_player_id:
                        continue
                    sheet_id = str(item_data.get("linked_sheet_id") or "").strip()
                    character_id = str(item_data.get("linked_character_id") or "").strip()
                    if not sheet_id or not character_id:
                        continue
                    sheet_name = str(item_data.get("linked_sheet_name") or sheet_id).strip() or sheet_id
                    linked_inventory = item_data.get("linked_inventory")
                    if not isinstance(linked_inventory, dict):
                        continue
                    host_inventory = normalize_inventory_payload(linked_inventory)
                    try:
                        host_save_revision = max(0, int(item_data.get("linked_save_revision") or 0))
                    except (TypeError, ValueError):
                        host_save_revision = 0
                    candidate = {
                        "sheet_id": sheet_id,
                        "sheet_name": sheet_name,
                        "entity_id": str(item_data.get("entity_id") or "").strip(),
                        "dungeon_id": str(dungeon.get("id") or "").strip(),
                        "save_revision": host_save_revision,
                        "last_saved_at": str(item_data.get("linked_last_saved_at") or "").strip(),
                        "content_hash": str(item_data.get("linked_content_hash") or "").strip(),
                        "inventory": host_inventory,
                        "archive_b64": str(item_data.get("linked_sheet_archive_b64") or "").strip(),
                    }
                    current = host_state_by_character.get(character_id)
                    if not isinstance(current, dict):
                        host_state_by_character[character_id] = candidate
                        continue
                    try:
                        current_revision = max(0, int(current.get("save_revision") or 0))
                    except (TypeError, ValueError):
                        current_revision = 0
                    if host_save_revision >= current_revision:
                        host_state_by_character[character_id] = candidate

            for character_id, sync_payload in host_state_by_character.items():
                sheet_id = str(sync_payload.get("sheet_id") or "").strip()
                inventory_payload = sync_payload.get("inventory", {})
                sheet_name = str(sync_payload.get("sheet_name") or character_id)
                host_save_revision = int(sync_payload.get("save_revision") or 0)
                host_content_hash = str(sync_payload.get("content_hash") or "").strip()
                entity_id = str(sync_payload.get("entity_id") or "").strip()
                dungeon_id = str(sync_payload.get("dungeon_id") or "").strip()
                local_payload = self._resolve_local_sheet_sync_payload(character_id)
                if isinstance(local_payload, dict) and sheet_id:
                    try:
                        local_save_revision = max(0, int(local_payload.get("save_revision") or 0))
                    except (TypeError, ValueError):
                        local_save_revision = 0
                    local_inventory = normalize_inventory_payload(local_payload.get("inventory") or {})
                    local_content_hash = str(local_payload.get("content_hash") or "").strip()
                    if local_save_revision > host_save_revision:
                        self._append_server_log(
                            "[WARN] Replaced newer local linked character data with the latest host session state."
                        )
                    if local_save_revision == host_save_revision:
                        if local_content_hash and host_content_hash and local_content_hash == host_content_hash:
                            continue
                        if (
                            self._inventory_payload_fingerprint(local_inventory)
                            == self._inventory_payload_fingerprint(
                                normalize_inventory_payload(inventory_payload)
                            )
                        ):
                            continue
                sync_kwargs = {
                    "sheet_name": sheet_name,
                    "archive_b64": str(sync_payload.get("archive_b64") or ""),
                    "save_revision": int(sync_payload.get("save_revision") or 0),
                    "last_saved_at": str(sync_payload.get("last_saved_at") or ""),
                    "content_hash": str(sync_payload.get("content_hash") or ""),
                    "refresh_entities": True,
                }
                if local_payload is None:
                    sync_kwargs.update(
                        {
                            "sheet_id": sheet_id,
                            "entity_id": entity_id,
                            "dungeon_id": dungeon_id,
                        }
                    )
                ok, message = self._sync_local_sheet_inventory_from_host(
                    character_id,
                    inventory_payload,
                    **sync_kwargs,
                )
                if ok and self._local_character_sheet_exists(character_id):
                    self._approved_host_inventory_sync_characters.add(character_id)
                elif message:
                    self._append_server_log(f"[WARN] {message}")

        def _run_post_snapshot_character_sync() -> None:
            _sync_owned_sheet_inventories_from_snapshot()
            self._cleanup_unlinked_managed_character_artifacts()

        initiative_state_raw = snapshot.get("initiative_state")
        player_entry_count = 0
        entity_entry_count = 0
        initiative_active = False
        initiative_collapsed = False
        if isinstance(initiative_state_raw, dict):
            raw_player_entries = initiative_state_raw.get("player_entries")
            raw_entity_entries = initiative_state_raw.get("entity_entries")
            if isinstance(raw_player_entries, dict):
                player_entry_count = len(raw_player_entries)
            if isinstance(raw_entity_entries, dict):
                entity_entry_count = len(raw_entity_entries)
            initiative_active = bool(initiative_state_raw.get("active", False))
            initiative_collapsed = bool(initiative_state_raw.get("collapsed", False))
        self._debug_log(
            "client_snapshot_received",
            keys=",".join(sorted(str(k) for k in snapshot.keys())),
            player_count=int(len(snapshot.get("players", {})))
            if isinstance(snapshot.get("players"), dict)
            else 0,
            loot_pool_count=int(len(snapshot.get("loot_pool", [])))
            if isinstance(snapshot.get("loot_pool"), list)
            else 0,
            initiative_active=initiative_active,
            initiative_collapsed=initiative_collapsed,
            initiative_player_rows=int(player_entry_count),
            initiative_entity_rows=int(entity_entry_count),
        )
        if was_waiting_for_snapshot:
            self._append_server_log("[INFO] Host snapshot received. Player actions restored.")
        preserved_entity_id = self._selected_entity_id()
        players = snapshot.get("players")
        if isinstance(players, dict):
            self._update_connected_players({str(k): str(v) for k, v in players.items()})
        loot_pool = snapshot.get("loot_pool")
        if isinstance(loot_pool, list):
            self._set_loot_pool_entries([entry for entry in loot_pool if isinstance(entry, dict)], broadcast=False)
        initiative_state = snapshot.get("initiative_state")
        if isinstance(initiative_state, dict):
            self._initiative_state = {
                "active": bool(initiative_state.get("active", False)),
                "collapsed": bool(initiative_state.get("collapsed", False)),
                "player_entries": dict(initiative_state.get("player_entries", {}))
                if isinstance(initiative_state.get("player_entries"), dict)
                else {},
                "entity_entries": dict(initiative_state.get("entity_entries", {}))
                if isinstance(initiative_state.get("entity_entries"), dict)
                else {},
            }
            if not self._initiative_state.get("active"):
                self._initiative_overlay.hide()
            elif self._initiative_state.get("collapsed"):
                self._initiative_overlay.hide()
            elif self._online_mode == ONLINE_MODE_PLAYER:
                if self._player_has_visible_initiative_rows():
                    self._show_initiative_overlay()
                else:
                    self._initiative_overlay.hide()
            self._render_initiative_overlay()
        collection_name = snapshot.get("collection_name")
        if isinstance(collection_name, str) and collection_name.strip():
            self._collection_name = collection_name.strip()
        snapshot_collection_id = str(snapshot.get("collection_id") or "").strip()
        if snapshot_collection_id:
            self._collection_id = snapshot_collection_id
        dungeons_payload = snapshot.get("dungeons")
        if isinstance(dungeons_payload, list):
            dungeons: list[dict] = []
            for entry in dungeons_payload:
                if not isinstance(entry, dict):
                    continue
                dungeon_state = entry.get("state")
                if not isinstance(dungeon_state, dict):
                    dungeon_state = self._blank_dungeon_state()
                dungeons.append(
                    {
                        "id": str(entry.get("id") or uuid.uuid4().hex),
                        "name": str(entry.get("name") or f"Dungeon {len(dungeons) + 1}"),
                        "state": dungeon_state,
                        "preview": None,
                        "preview_signature": None,
                        "dirty": False,
                    }
                )
            if dungeons:
                valid_ids = {d["id"] for d in dungeons}
                preferred_players = str(snapshot.get("players_dungeon_id") or "")
                preferred_active = str(snapshot.get("active_dungeon_id") or "")
                if preferred_players not in valid_ids:
                    preferred_players = dungeons[0]["id"]
                target_id = preferred_players
                if target_id not in valid_ids and preferred_active in valid_ids:
                    target_id = preferred_active
                if target_id not in valid_ids:
                    target_id = dungeons[0]["id"]
                target_dungeon = next((d for d in dungeons if d["id"] == target_id), None)
                target_state = (target_dungeon or {}).get("state") or self._blank_dungeon_state()
                current_active = str(self._active_dungeon_id or "")
                current_players = str(self._players_dungeon_id or "")
                skip_reload = False
                if current_active == target_id and current_players == preferred_players:
                    try:
                        skip_reload = self._serialize_scene() == target_state
                    except Exception:
                        skip_reload = False
                self._dungeons = dungeons
                self._players_dungeon_id = preferred_players
                self._active_dungeon_id = target_id
                if not skip_reload:
                    self._suppress_network_sync = True
                    try:
                        self._load_dungeon_state(target_state)
                    finally:
                        self._suppress_network_sync = False
                self._collection_meta_dirty = False
                self._refresh_dungeon_list(preserve_selection=True)
                self._refresh_collection_dirty()
                self._update_active_dungeon_label()
                self._apply_online_permissions()
                self._restore_entity_selection(preserved_entity_id)
                self._update_loot_pool_badge()
                if (
                    self._initiative_state.get("active")
                    and not self._initiative_state.get("collapsed")
                    and self._online_mode == ONLINE_MODE_PLAYER
                ):
                    if self._player_has_visible_initiative_rows():
                        self._show_initiative_overlay()
                    else:
                        self._initiative_overlay.hide()
                self._render_initiative_overlay()
                _run_post_snapshot_character_sync()
                self._flush_pending_player_state_update()
                return
        scene = snapshot.get("scene")
        if not isinstance(scene, dict):
            return
        self._suppress_network_sync = True
        try:
            self._load_dungeon_state(scene)
        finally:
            self._suppress_network_sync = False
        self._apply_online_permissions()
        self._restore_entity_selection(preserved_entity_id)
        self._update_loot_pool_badge()
        if (
            self._initiative_state.get("active")
            and not self._initiative_state.get("collapsed")
            and self._online_mode == ONLINE_MODE_PLAYER
        ):
            if self._player_has_visible_initiative_rows():
                self._show_initiative_overlay()
            else:
                self._initiative_overlay.hide()
        self._render_initiative_overlay()
        _run_post_snapshot_character_sync()
        self._flush_pending_player_state_update()

    def _on_client_command_result(self, result: dict) -> None:
        request_id = str(result.get("request_id") or "").strip()
        data = result.get("data")
        action = str(data.get("action") or "").strip() if isinstance(data, dict) else ""
        if not action and request_id:
            action = self._pending_online_command_action_for_request(request_id)
        conflict = data.get("conflict") if isinstance(data, dict) else None
        conflict_key = str(conflict.get("conflict_key") or "").strip() if isinstance(conflict, dict) else ""
        correlated_claim_id = ""
        if isinstance(data, dict):
            correlated_claim_id = str(data.get("claim_id") or "").strip()
        if (not correlated_claim_id) and conflict_key:
            correlated_claim_id = self._pending_loot_claim_id_for_conflict(conflict_key)
        if isinstance(data, dict) and str(data.get("action") or "") == "claim_loot_finalize":
            claim_id = str(data.get("claim_id") or "").strip()
            if claim_id:
                self._pending_loot_claim_finalizations.pop(claim_id, None)
        if action == "state_update" and request_id:
            if request_id == self._pending_player_state_update_request_id:
                self._pending_player_state_update_request_id = ""
                self._pending_player_state_update = None
        if result.get("ok"):
            if action == "link_character_entity" and isinstance(data, dict):
                pending_request = (
                    self._pending_link_entity_requests.pop(request_id, None)
                    if request_id
                    else None
                )
                entity_id = str(data.get("entity_id") or "").strip()
                if not entity_id and isinstance(pending_request, dict):
                    entity_id = str(pending_request.get("entity_id") or "").strip()
                target_entity = self._find_entity_by_id(entity_id) if entity_id else None
                linked_character_id = str(data.get("character_id") or "").strip()
                if not linked_character_id and isinstance(pending_request, dict):
                    linked_character_id = str(pending_request.get("character_id") or "").strip()
                if linked_character_id:
                    self._approved_host_inventory_sync_characters.add(linked_character_id)
                if isinstance(target_entity, EntityItem):
                    sheet_id = str(data.get("sheet_id") or "").strip()
                    if not sheet_id and isinstance(pending_request, dict):
                        sheet_id = str(pending_request.get("sheet_id") or "").strip()
                    sheet_name = str(data.get("sheet_name") or "").strip()
                    if not sheet_name and isinstance(pending_request, dict):
                        sheet_name = str(pending_request.get("sheet_name") or sheet_id).strip()
                    linked_inventory = data.get("inventory")
                    if not isinstance(linked_inventory, dict) and isinstance(pending_request, dict):
                        linked_inventory = pending_request.get("inventory")
                    stats_payload = data.get("stats")
                    if not isinstance(stats_payload, dict) and isinstance(pending_request, dict):
                        stats_payload = pending_request.get("stats")
                    self._apply_character_link_to_entity(
                        target_entity,
                        sheet_id=sheet_id,
                        sheet_name=sheet_name or sheet_id,
                        character_id=linked_character_id,
                        save_revision=int(data.get("save_revision") or 0),
                        last_saved_at=str(data.get("last_saved_at") or ""),
                        content_hash=str(data.get("content_hash") or ""),
                        linked_inventory=linked_inventory if isinstance(linked_inventory, dict) else {},
                        stats=stats_payload if isinstance(stats_payload, dict) else {},
                        archive_b64=str(data.get("archive_b64") or ""),
                    )
                    target_entity.update()
                    if getattr(self.inspector, "_entity", None) is target_entity:
                        self.inspector.set_linked_character_info(sheet_name)
                        self.inspector.set_entity(target_entity)
                    self._position_floating_overlays()
            if action == "unlink_character_entity":
                pending_request = (
                    self._pending_unlink_entity_requests.pop(request_id, None)
                    if request_id
                    else None
                )
                cleared_character_id = str(data.get("character_id") or "").strip() if isinstance(data, dict) else ""
                if cleared_character_id:
                    self._approved_host_inventory_sync_characters.discard(cleared_character_id)
                entity_id = str(data.get("entity_id") or "").strip() if isinstance(data, dict) else ""
                if not entity_id and isinstance(pending_request, dict):
                    entity_id = str(pending_request.get("entity_id") or "").strip()
                target_entity = self._find_entity_by_id(entity_id) if entity_id else None
                if isinstance(target_entity, EntityItem):
                    self._clear_character_link_from_entity(target_entity)
                    target_entity.update()
                    if getattr(self.inspector, "_entity", None) is target_entity:
                        self.inspector.set_linked_character_info("")
                        self.inspector.set_entity(target_entity)
                    self._position_floating_overlays()
            if action == "claim_loot_finalize":
                claim_id = str(data.get("claim_id") or "").strip()
                if claim_id:
                    self._pending_loot_claim_rollbacks.pop(claim_id, None)
            if action == "sync_character_inventory" and correlated_claim_id:
                self._finalize_pending_loot_claim_success(correlated_claim_id)
                return
            if action == "add_loot_from_inventory":
                pending_request = (
                    self._pending_add_loot_from_inventory_requests.pop(request_id, None)
                    if request_id
                    else None
                )
                if pending_request is None:
                    self._append_server_log(
                        "[WARN] Ignored uncorrelated loot-transfer inventory sync result."
                    )
                else:
                    target_character = str(data.get("character_id") or data.get("sheet_id") or "").strip()
                    inventory_payload = data.get("inventory")
                    ok, message = self._sync_local_sheet_inventory_from_host(
                        target_character,
                        inventory_payload,
                        sheet_name=str(
                            data.get("sheet_name")
                            or pending_request.get("sheet_name")
                            or target_character
                        ),
                        save_revision=int(data.get("save_revision") or 0),
                        last_saved_at=str(data.get("last_saved_at") or ""),
                        content_hash=str(data.get("content_hash") or ""),
                        refresh_entities=True,
                    )
                    if not ok:
                        self._append_server_log(f"[WARN] {message}")
            if isinstance(data, dict) and isinstance(data.get("claimed_entries"), list):
                claimed_entries = [entry for entry in data.get("claimed_entries", []) if isinstance(entry, dict)]
                sheet_id = str(data.get("sheet_id") or "").strip()
                claim_id = str(data.get("claim_id") or "").strip()
                rollback_payload = self._capture_sheet_inventory_snapshot(sheet_id)
                if claim_id and isinstance(rollback_payload, dict):
                    self._pending_loot_claim_rollbacks[claim_id] = {
                        "sheet_id": sheet_id,
                        "inventory": rollback_payload,
                        "claimed_entries": [dict(entry) for entry in claimed_entries],
                        "status": "awaiting_sync_dispatch",
                        "sync_request_id": "",
                        "conflict_key": "",
                        "character_id": "",
                    }
                ok, message = self._apply_claim_entries_to_sheet(sheet_id, claimed_entries)
                if not ok:
                    self._append_server_log(f"[WARN] {message}")
                    if claim_id:
                        self._pending_loot_claim_rollbacks.pop(claim_id, None)
                        self._queue_loot_claim_finalize(
                            claim_id,
                            applied=False,
                            error=str(message or "Unable to apply claim."),
                        )
                elif claim_id:
                    pending_claim = self._pending_loot_claim_rollbacks.get(claim_id)
                    if (
                        isinstance(pending_claim, dict)
                        and str(pending_claim.get("status") or "").strip() == "awaiting_sync_dispatch"
                    ):
                        self._dispatch_pending_loot_claim_inventory_sync(claim_id)
                    elif claim_id not in self._pending_loot_claim_rollbacks:
                        self._queue_loot_claim_finalize(
                            claim_id,
                            applied=True,
                            error="",
                        )
            return
        if action == "link_character_entity" and request_id:
            self._pending_link_entity_requests.pop(request_id, None)
        if action == "unlink_character_entity" and request_id:
            self._pending_unlink_entity_requests.pop(request_id, None)
        if action == "add_loot_from_inventory" and request_id:
            self._pending_add_loot_from_inventory_requests.pop(request_id, None)
        if action == "claim_loot_finalize":
            claim_id = str(data.get("claim_id") or "").strip()
            if claim_id:
                self._rollback_pending_loot_claim(claim_id)
        if action == "sync_character_inventory" and correlated_claim_id:
            self._rollback_pending_loot_claim(
                correlated_claim_id,
                reason=str(result.get("message") or "Unable to synchronize the claimed loot."),
                notify_host=True,
            )
        if action == "state_update" and request_id == self._pending_player_state_update_request_id:
            self._pending_player_state_update_request_id = ""
            self._pending_player_state_update = None
        message = str(result.get("message") or "Command rejected")
        self._append_server_log(f"[WARN] {message}")

    def _on_client_icon_asset(self, entity_id: str, filename: str, content_b64: str) -> None:
        try:
            raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
        except Exception:
            return
        payload_ok, _payload_error = _validate_online_icon_payload(raw)
        if not payload_ok:
            return
        cache_dir = online_icon_cache_dir(self._active_online_runtime_cache_id())
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_filename = _sanitize_filename(Path(filename).name, "icon.png")
        cache_path = cache_dir / safe_filename
        if not cache_path.exists():
            cache_path.write_bytes(raw)
        target_entity = self._find_entity_by_id(entity_id)
        if target_entity is None:
            return
        target_entity.setData(ROLE_ICON, f"{SESSION_ICON_PREFIX}{safe_filename}")
        target_entity.icon_path = str(cache_path)
        target_entity.update()

    def _find_entity_by_id(self, entity_id: str) -> EntityItem | None:
        if not entity_id:
            return None
        for item in self.canvas.scene().items():
            if not isinstance(item, EntityItem):
                continue
            if (item.data(ROLE_ENTITY_ID) or "") == entity_id:
                return item
        return None

    def _selected_entity_id(self) -> str | None:
        for item in self.canvas.scene().selectedItems():
            if not isinstance(item, EntityItem):
                continue
            entity_id = str(item.data(ROLE_ENTITY_ID) or "").strip()
            if entity_id:
                return entity_id
        return None

    def _restore_entity_selection(self, entity_id: str | None) -> None:
        target_id = str(entity_id or "").strip()
        if not target_id:
            return
        entity = self._find_entity_by_id(target_id)
        if entity is None:
            return
        if entity.flags() & QGraphicsItem.GraphicsItemFlag.ItemIsSelectable:
            entity.setSelected(True)

    def _resolve_runtime_icon_path(self, icon_ref_or_path: str) -> str:
        if not icon_ref_or_path:
            return ""
        if icon_ref_or_path.startswith(SESSION_ICON_PREFIX):
            cache_name = icon_ref_or_path[len(SESSION_ICON_PREFIX) :]
            safe_cache_name = _sanitize_filename(Path(cache_name).name, "")
            if not safe_cache_name:
                return ""
            return str(online_icon_cache_dir(self._active_online_runtime_cache_id()) / safe_cache_name)
        return icon_ref_or_path

    def _on_deferred_icon_selected(self, filename: str) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER or self._client_controller is None:
            return
        entity = self.inspector._entity
        if not isinstance(entity, EntityItem):
            return
        if not self._is_entity_owned_by_local_player(entity):
            return
        path = Path(filename)
        if not path.exists():
            return
        raw = path.read_bytes()
        if not raw or len(raw) > 2 * 1024 * 1024:
            QMessageBox.warning(self, "Icon Upload", "Icon must be non-empty and <= 2MB.")
            return
        entity_id = entity.data(ROLE_ENTITY_ID) or ""
        if not entity_id:
            entity_id = uuid.uuid4().hex
            entity.setData(ROLE_ENTITY_ID, entity_id)
        self._dispatch_player_command(
            "upload_icon",
            {
                "entity_id": entity_id,
                "filename": path.name,
                "content_b64": base64.b64encode(raw).decode("ascii"),
                "owner_player_id": str(self._local_player_id or ""),
                "dungeon_id": str(self._active_dungeon_id or ""),
            },
            silent=True,
        )

    def _on_tool_changed(self, tool: ToolType):
        if self._online_mode == ONLINE_MODE_PLAYER:
            if tool not in PLAYER_ALLOWED_TOOLS:
                self.canvas.current_tool = ToolType.SELECT
                return
        self.canvas.current_tool = tool

    def closeEvent(self, event) -> None:
        if self._online_mode != ONLINE_MODE_PLAYER and self._collection_dirty and not self._confirm_unsaved_changes():
            event.ignore()
            return
        current_session = str(self._online_session_id or "")
        current_runtime_cache_id = str(self._active_online_runtime_cache_id() or "")
        self._debug_log("close_event", session=current_session)
        self._suppress_change_tracking = True
        self._suppress_network_sync = True
        self._hide_reconnect_status_dialog()
        loot_pool_viewport = getattr(self, "_loot_pool_viewport", None)
        if loot_pool_viewport is not None:
            try:
                loot_pool_viewport.removeEventFilter(self)
            except RuntimeError:
                pass
        self._loot_pool_viewport = None
        self._loot_pool_list = None
        self._remove_app_event_filter()
        self._host_scene_sync_pending = False
        self._preview_timer.stop()
        self._collection_autosave_timer.stop()
        self._host_scene_sync_timer.stop()
        self._host_scene_watchdog_timer.stop()
        self._loot_claim_reservation_timer.stop()
        self._save_local_profile()
        if self._host_controller is not None:
            self._host_controller.stop()
        if self._client_controller is not None:
            self._client_controller.disconnect()
        self._clear_online_runtime_cache(current_runtime_cache_id)
        self._preview_timer.stop()
        self._host_scene_sync_timer.stop()
        self._host_scene_watchdog_timer.stop()
        self._loot_claim_reservation_timer.stop()
        self._scene_item_refs = []
        super().closeEvent(event)

    def _local_profile_path(self) -> Path:
        return dnd_saves_dir() / "settings" / LOCAL_DUNGEON_PROFILE_FILENAME

    def _load_or_create_local_profile(self) -> dict:
        default_profile = {
            "version": 1,
            "player_id": get_or_create_local_player_id(),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "machine_fingerprint": hashlib.sha256(
                _machine_entropy_string().encode("utf-8")
            ).hexdigest(),
            "character_ids": {},
            "known_players": {},
            "last_player_name": "",
            "autosave_enabled": False,
        }
        path = self._local_profile_path()
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    merged = dict(default_profile)
                    merged.update(payload)
                    if not str(merged.get("player_id") or "").strip():
                        merged["player_id"] = get_or_create_local_player_id()
                    if not isinstance(merged.get("character_ids"), dict):
                        merged["character_ids"] = {}
                    if not isinstance(merged.get("known_players"), dict):
                        merged["known_players"] = {}
                    return merged
        except Exception:
            pass
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(default_profile, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return default_profile

    def _save_local_profile(self) -> None:
        path = self._local_profile_path()
        try:
            payload = dict(getattr(self, "_local_profile", {}) or {})
            payload["player_id"] = str(getattr(self, "_persistent_local_player_id", "") or "")
            payload["character_ids"] = dict(getattr(self, "_character_id_registry", {}) or {})
            payload["known_players"] = dict(getattr(self, "_known_player_profiles", {}) or {})
            payload["last_player_name"] = str(
                getattr(self, "_local_player_name", "") or payload.get("last_player_name") or ""
            )
            payload["autosave_enabled"] = bool(getattr(self, "_autosave_enabled", False))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            return

    def _character_id_for_sheet(self, sheet_id: str, *, sheet_name: str = "") -> str:
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return _generate_probabilistic_unique_id("character")
        existing = str(self._character_id_registry.get(clean_sheet) or "").strip()
        if existing:
            return existing
        character_id = _generate_probabilistic_unique_id("character")
        self._character_id_registry[clean_sheet] = character_id
        self._save_local_profile()
        return character_id

    def _remember_known_player(self, player_id: str, player_name: str) -> bool:
        clean_id = str(player_id or "").strip()
        clean_name = str(player_name or "").strip()
        if not clean_id:
            return False
        existing = self._known_player_profiles.get(clean_id)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        next_payload = {
            "name": clean_name or clean_id,
            "last_seen": now,
        }
        if isinstance(existing, dict):
            merged = dict(existing)
            merged.update(next_payload)
            next_payload = merged
        changed = existing != next_payload
        self._known_player_profiles[clean_id] = next_payload
        return changed

    def _update_workspace_tab_title(self, title: str) -> None:
        desired_title = str(title or "").strip()
        if not desired_title:
            return

        def _apply() -> None:
            parent = self.parentWidget()
            while parent is not None:
                set_tab_text = getattr(parent, "setTabText", None)
                index_of = getattr(parent, "indexOf", None)
                if callable(set_tab_text) and callable(index_of):
                    try:
                        index = int(index_of(self))
                    except Exception:
                        index = -1
                    if index >= 0:
                        set_tab_text(index, desired_title)
                        return
                parent = parent.parentWidget()

        QTimer.singleShot(0, _apply)

    def _resolve_debug_log_path(self) -> Path:
        try:
            return dnd_saves_dir() / "cache" / "logs" / ONLINE_DEBUG_LOG_FILENAME
        except Exception:
            return Path(default_dnd_save_dir()) / "cache" / "logs" / ONLINE_DEBUG_LOG_FILENAME

    def _debug_widget_ref(self, widget: object) -> str:
        if widget is None:
            return "None"
        ref = type(widget).__name__
        if isinstance(widget, QWidget):
            object_name = str(widget.objectName() or "").strip()
            if object_name:
                ref = f"{ref}#{object_name}"
            if isinstance(widget, QLineEdit) and bool(widget.property("initiative_input")):
                kind = str(widget.property("initiative_kind") or "")
                row_id = str(widget.property("initiative_id") or "")
                ref = f"{ref}[{kind}:{row_id}]"
        return ref

    def _debug_log(self, event: str, **fields: object) -> None:
        if not getattr(self, "_debug_log_enabled", False):
            return
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "pid": os.getpid(),
            "instance": str(getattr(self, "_debug_instance_id", "")),
            "mode": str(getattr(self, "_online_mode", "")),
            "session": str(getattr(self, "_online_session_id", "")),
            "local_player_id": str(getattr(self, "_local_player_id", "") or ""),
            "event": str(event),
        }
        for key, value in fields.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                payload[str(key)] = value
            else:
                payload[str(key)] = str(value)
        try:
            log_path = Path(getattr(self, "_debug_log_path", self._resolve_debug_log_path()))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=True))
                handle.write("\n")
        except Exception:
            pass

    def _remove_app_event_filter(self) -> None:
        if self._app is not None:
            try:
                self._app.removeEventFilter(self)
            except RuntimeError:
                pass
            self._app = None

    def _watched_is_self_or_descendant(self, watched: QObject) -> bool:
        if not isinstance(watched, QWidget):
            return False
        if watched is self:
            return True
        current = watched.parentWidget()
        while current is not None:
            if current is self:
                return True
            current = current.parentWidget()
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        try:
            event_type = event.type()
        except RecursionError:
            self._debug_log(
                "eventfilter_event_type_recursion",
                watched=self._debug_widget_ref(watched),
                event_class=type(event).__name__,
            )
            return False
        except Exception as exc:
            self._debug_log(
                "eventfilter_event_type_error",
                watched=self._debug_widget_ref(watched),
                event_class=type(event).__name__,
                error=str(exc),
            )
            return False
        try:
            watched_in_tree = self._watched_is_self_or_descendant(watched)
        except RuntimeError:
            return False
        if event_type == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if not watched_in_tree:
                return False
            focus_widget = QApplication.focusWidget()
            focus_is_initiative_input = (
                isinstance(focus_widget, QLineEdit)
                and bool(focus_widget.property("initiative_input"))
                and focus_widget.isEnabled()
            )
            initiative_key_context_active = bool(self._initiative_state.get("active", False)) and (
                focus_is_initiative_input or self._initiative_last_target is not None
            )
            if not initiative_key_context_active:
                return False
            # Avoid rerouting key presses from stale/hidden initiative editors that are pending
            # deferred deletion after overlay rerenders.
            if isinstance(watched, QLineEdit) and bool(watched.property("initiative_input")):
                return False
            if not self._forwarding_initiative_key:
                target_widget: QLineEdit | None = None
                self._debug_log(
                    "initiative_eventfilter_keypress",
                    watched=self._debug_widget_ref(watched),
                    focus=self._debug_widget_ref(focus_widget),
                    key=int(event.key()),
                    text=str(event.text() or ""),
                    last_target=(
                        f"{self._initiative_last_target[0]}:{self._initiative_last_target[1]}"
                        if self._initiative_last_target
                        else ""
                    ),
                )
                if (
                    focus_is_initiative_input
                    and watched is not focus_widget
                ):
                    target_widget = focus_widget
                elif self._initiative_last_target is not None:
                    kind, key = self._initiative_last_target
                    candidate = self._find_initiative_input(kind, key)
                    if candidate is not None and candidate.isEnabled() and watched is not candidate:
                        target_widget = candidate
                if target_widget is not None:
                    modifiers = event.modifiers()
                    if not (
                        modifiers
                        & (
                            Qt.KeyboardModifier.ControlModifier
                            | Qt.KeyboardModifier.AltModifier
                            | Qt.KeyboardModifier.MetaModifier
                        )
                    ) and event.key() not in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                        forwarded = QKeyEvent(
                            QEvent.Type.KeyPress,
                            event.key(),
                            modifiers,
                            event.text(),
                            event.isAutoRepeat(),
                            event.count(),
                        )
                        self._forwarding_initiative_key = True
                        try:
                            QApplication.sendEvent(target_widget, forwarded)
                        finally:
                            self._forwarding_initiative_key = False
                        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                            committed = self._commit_initiative_input(target_widget)
                            self._debug_log(
                                "initiative_eventfilter_enter_commit",
                                target=self._debug_widget_ref(target_widget),
                                committed=bool(committed),
                                text=str(target_widget.text() or ""),
                            )
                            if committed:
                                self._initiative_last_target = (
                                    str(target_widget.property("initiative_kind") or ""),
                                    str(target_widget.property("initiative_id") or ""),
                                )
                                return True
                        if forwarded.isAccepted():
                            self._initiative_last_target = (
                                str(target_widget.property("initiative_kind") or ""),
                                str(target_widget.property("initiative_id") or ""),
                            )
                            self._debug_log(
                                "initiative_eventfilter_forwarded",
                                target=self._debug_widget_ref(target_widget),
                                key=int(event.key()),
                                text=str(event.text() or ""),
                            )
                            return True
        if (
            watched_in_tree
            and event_type == QEvent.Type.MouseButtonPress
            and isinstance(watched, QLineEdit)
        ):
            if bool(watched.property("initiative_input")):
                kind = str(watched.property("initiative_kind") or "")
                key = str(watched.property("initiative_id") or "")
                if kind and key:
                    self._initiative_last_target = (kind, key)
                    watched.setFocus(Qt.FocusReason.MouseFocusReason)
                    self._debug_log(
                        "initiative_input_mouse_focus",
                        target=self._debug_widget_ref(watched),
                    )
        loot_pool_list = getattr(self, "_loot_pool_list", None)
        loot_pool_viewport = getattr(self, "_loot_pool_viewport", None)
        if loot_pool_list is not None and loot_pool_viewport is None:
            try:
                loot_pool_viewport = loot_pool_list.viewport()
                self._loot_pool_viewport = loot_pool_viewport
            except RuntimeError:
                loot_pool_list = None
                loot_pool_viewport = None
                self._loot_pool_list = None
                self._loot_pool_viewport = None
                self._hide_loot_pool_preview()
        if loot_pool_list is not None and loot_pool_viewport is not None and watched is loot_pool_viewport:
            try:
                if event_type == QEvent.Type.MouseMove and isinstance(event, QMouseEvent):
                    item = loot_pool_list.itemAt(event.pos())
                    if item is None:
                        self._hide_loot_pool_preview()
                    else:
                        global_pos = loot_pool_viewport.mapToGlobal(event.pos())
                        self._show_loot_pool_preview_for_item(item, global_pos)
                elif event_type in (
                    QEvent.Type.Leave,
                    QEvent.Type.MouseButtonPress,
                    QEvent.Type.MouseButtonDblClick,
                    QEvent.Type.Wheel,
                ):
                    self._hide_loot_pool_preview()
            except RuntimeError:
                self._loot_pool_list = None
                self._loot_pool_viewport = None
                self._hide_loot_pool_preview()
                return False
        if (
            watched_in_tree
            and event_type == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
        ):
            focus_widget = QApplication.focusWidget()
            click_pos = event.globalPosition().toPoint()
            clicked_widget = QApplication.widgetAt(click_pos)
            if (
                self.inspector is not None
                and self.inspector.isVisible()
                and focus_widget is not None
                and self.inspector.isAncestorOf(focus_widget)
                and isinstance(focus_widget, (QLineEdit, QAbstractSpinBox))
            ):
                clicked_inside_focused = bool(
                    clicked_widget is not None
                    and (clicked_widget is focus_widget or focus_widget.isAncestorOf(clicked_widget))
                )
                if not clicked_inside_focused:
                    focus_widget.clearFocus()
                    if clicked_widget is None or not self.inspector.isAncestorOf(clicked_widget):
                        self.canvas.setFocus(Qt.FocusReason.MouseFocusReason)
            if isinstance(focus_widget, InlineRenameLineEdit):
                local_pos = focus_widget.mapFromGlobal(click_pos)
                if not focus_widget.rect().contains(local_pos):
                    focus_widget.finish_edit()
        return False

    def _on_selection_changed(self):
        selected = self.canvas.scene().selectedItems()
        if len(selected) != 1 or not isinstance(selected[0], EntityItem):
            self.inspector.set_entity(None)
            self._position_floating_overlays()
            return
        entity = selected[0]
        if self._online_mode == ONLINE_MODE_PLAYER:
            if self._is_entity_owned_by_local_player(entity):
                self.inspector.set_entity(entity)
            else:
                self.inspector.set_entity(None)
            self._position_floating_overlays()
            return
        if self._view_mode == "dm":
            self.inspector.set_entity(entity)
        else:
            self.inspector.set_entity(None)
        self._position_floating_overlays()
            
    def _on_view_mode_changed(self, mode: str):
        if self._online_mode not in (ONLINE_MODE_LOCAL_DM, ONLINE_MODE_DM_HOST):
            return
        self._view_mode = mode
        self.canvas.set_view_mode(mode)
        
        if mode == "player":
            self.inspector.hide()
        else:
            # Re-evaluate selection to show inspector if needed
            self._on_selection_changed()

    def _update_coords(self, pos: QPointF):
        self.coord_label.setText(f"X: {round(pos.x())}, Y: {round(pos.y())}")

    def _update_zoom_label(self, zoom: float):
        self.zoom_label.setText(f"{int(zoom * 100)}%")

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_collection_geometry()
        self._position_session_overlay()

    def _update_collection_geometry(self) -> None:
        panel_width, panel_height = (0, 0)
        if self.selection_widget is not None:
            panel_width, panel_height = self.selection_widget.carousel_metrics()
        if panel_width <= 0:
            panel_width = int(self.width() * 0.5)
        self._update_tile_sizes(panel_width, max_height=panel_height if panel_height > 0 else None)

    def _update_tile_sizes(self, panel_width: int, max_height: int | None = None) -> None:
        if panel_width <= 0:
            return
        side_padding = 16
        available_width = max(1, panel_width - side_padding)
        if panel_width >= 680:
            visible_tiles = 5
        elif panel_width >= 520:
            visible_tiles = 4
        elif panel_width >= 380:
            visible_tiles = 3
        else:
            visible_tiles = 2
        list_spacing = self._dungeon_list.spacing()
        available_for_tiles = max(1, available_width - (visible_tiles - 1) * list_spacing)
        tile_width = max(120, min(180, int(available_for_tiles / visible_tiles)))
        icon_side = max(72, tile_width - 16)
        label_metrics = QFontMetrics(self._dungeon_list.font())
        label_height = label_metrics.height() + 12
        content_spacing = 8
        content_margins = 22
        tile_height = icon_side + label_height + content_spacing + content_margins
        self._tile_size = QSize(tile_width, tile_height)
        self._dungeon_list.setGridSize(self._tile_size)
        self._dungeon_list.setIconSize(QSize(icon_side, icon_side))
        scroll_bar = self._dungeon_list.horizontalScrollBar()
        scroll_bar.setSingleStep(max(8, int(self._tile_size.width() / 6)))
        scroll_bar.setPageStep(max(12, int(self._tile_size.width() / 2)))
        scroll_height = scroll_bar.sizeHint().height()
        self._dungeon_list.setFixedHeight(tile_height + scroll_height + 40)
        if self._dungeons:
            self._refresh_dungeon_list(preserve_selection=True)

    def _scroll_dungeon_list(self, direction: int) -> None:
        if direction == 0:
            return
        scroll_bar = self._dungeon_list.horizontalScrollBar()
        step = self._tile_size.width() + self._dungeon_list.spacing()
        scroll_bar.setValue(scroll_bar.value() + (step * direction))

    def _delete_active_dungeon(self) -> None:
        item = self._dungeon_list.currentItem()
        dungeon_id = None
        if item is not None:
            dungeon_id = item.data(Qt.ItemDataRole.UserRole)
        if not dungeon_id:
            dungeon_id = self._active_dungeon_id
        if dungeon_id:
            self._confirm_delete_dungeon(dungeon_id)

    def _on_carousel_layout_changed(self, width: int, height: int) -> None:
        if width <= 0:
            return
        self._update_tile_sizes(width, max_height=height)
        self.selection_widget.refresh_overlay_positions()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        focus_widget = QApplication.focusWidget()
        if (
            isinstance(focus_widget, QLineEdit)
            and bool(focus_widget.property("initiative_input"))
            and focus_widget.isEnabled()
        ):
            self._debug_log(
                "initiative_keypress_widget",
                focus=self._debug_widget_ref(focus_widget),
                key=int(event.key()),
                text=str(event.text() or ""),
            )
            forwarded = QKeyEvent(
                QEvent.Type.KeyPress,
                event.key(),
                event.modifiers(),
                event.text(),
                event.isAutoRepeat(),
                event.count(),
            )
            QApplication.sendEvent(focus_widget, forwarded)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                committed = self._commit_initiative_input(focus_widget)
                self._debug_log(
                    "initiative_keypress_widget_enter_commit",
                    focus=self._debug_widget_ref(focus_widget),
                    committed=bool(committed),
                    text=str(focus_widget.text() or ""),
                )
                if committed:
                    event.accept()
                    return
            if forwarded.isAccepted():
                self._debug_log(
                    "initiative_keypress_widget_forwarded",
                    focus=self._debug_widget_ref(focus_widget),
                    key=int(event.key()),
                    text=str(event.text() or ""),
                )
                event.accept()
                return
        if event.key() == Qt.Key.Key_L:
            if self._online_mode == ONLINE_MODE_PLAYER:
                event.accept()
                return
            self.tool_panel._toggle_layer()
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_collection_panel(self) -> None:
        if self._collection_shell is None or self._collection_anim is None:
            return
        self._set_collection_expanded(not self._collection_expanded, animate=True)

    def _set_collection_expanded(self, expanded: bool, animate: bool = True) -> None:
        if self._collection_shell is None or self._collection_anim is None:
            return
        if expanded == self._collection_expanded:
            return
        self._collection_expanded = expanded
        self._collection_shell.set_expanded(expanded)
        target_morph = 1.0 if expanded else 0.0
        self._collection_anim.stop()
        if not animate:
            self._collection_shell.set_morph(target_morph)
            return
        self._collection_anim.setStartValue(self._collection_shell.morph)
        self._collection_anim.setEndValue(target_morph)
        self._collection_anim.start()

    def _init_collection(self) -> None:
        self._collection_path = None
        self._collection_id = generate_named_object_id(self._collection_name, "collection")
        self._collection_meta_dirty = False
        self._collection_dirty = False
        self._dungeons = []
        first = self._create_dungeon_entry("Dungeon 1")
        self._dungeons.append(first)
        self._active_dungeon_id = first["id"]
        self._players_dungeon_id = first["id"]
        self._load_dungeon_state(first["state"])
        self._refresh_dungeon_list(preserve_selection=True)
        self._refresh_collection_dirty()
        self._update_active_dungeon_label()

    def _create_dungeon_entry(self, name: str, state: dict | None = None) -> dict:
        return {
            "id": uuid.uuid4().hex,
            "name": name,
            "state": state or self._blank_dungeon_state(),
            "preview": None,
            "preview_signature": None,
            "dirty": False,
        }

    def _blank_dungeon_state(self) -> dict:
        return {"items": [], "fog": {"path": []}}

    def _current_dungeon(self) -> dict | None:
        for dungeon in self._dungeons:
            if dungeon["id"] == self._active_dungeon_id:
                return dungeon
        return None

    def _find_dungeon(self, dungeon_id: str) -> dict | None:
        for dungeon in self._dungeons:
            if dungeon["id"] == dungeon_id:
                return dungeon
        return None

    def _refresh_dungeon_list(self, preserve_selection: bool = True) -> None:
        if self._refreshing_dungeon_list:
            self._pending_dungeon_list_refresh = True
            self._pending_dungeon_list_preserve_selection = (
                self._pending_dungeon_list_preserve_selection or preserve_selection
            )
            return

        self._pending_dungeon_list_preserve_selection = preserve_selection
        while True:
            requested_preserve_selection = self._pending_dungeon_list_preserve_selection
            self._pending_dungeon_list_refresh = False
            self._pending_dungeon_list_preserve_selection = True

            current_id = self._active_dungeon_id if requested_preserve_selection else None
            self._refreshing_dungeon_list = True
            self._dungeon_list.blockSignals(True)
            try:
                self._dungeon_list.clear()
                self._tile_widgets = {}
                icon_size = self._dungeon_list.iconSize()
                if not icon_size.isValid():
                    fallback_side = max(64, min(self._tile_size.width(), self._tile_size.height()) - 32)
                    icon_size = QSize(fallback_side, fallback_side)
                    self._dungeon_list.setIconSize(icon_size)
                preview_signature = self._preview_render_signature(icon_size)
                for dungeon in self._dungeons:
                    item = QListWidgetItem("")
                    item.setData(Qt.ItemDataRole.UserRole, dungeon["id"])
                    item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                    item.setSizeHint(self._tile_size)
                    preview = dungeon.get("preview")
                    if (
                        preview is None
                        or (isinstance(preview, QPixmap) and preview.isNull())
                        or dungeon.get("preview_signature") != preview_signature
                    ):
                        preview = self._render_state_preview(
                            dungeon.get("state") or self._blank_dungeon_state(),
                            icon_size,
                        )
                        dungeon["preview"] = preview
                        dungeon["preview_signature"] = preview_signature
                    self._dungeon_list.addItem(item)
                    if item.listWidget() is not self._dungeon_list:
                        self._debug_log(
                            "dungeon_list_item_detached_before_widget_bind",
                            dungeon_id=str(dungeon.get("id") or ""),
                        )
                        continue
                    tile_widget = DungeonTileWidget(
                        dungeon["id"],
                        dungeon["name"],
                        preview if isinstance(preview, QPixmap) else QPixmap(),
                        icon_size,
                        parent=self._dungeon_list,
                    )
                    tile_widget.clicked.connect(self._on_tile_clicked)
                    tile_widget.nameChanged.connect(self._on_tile_name_changed)
                    tile_widget.nameCommitted.connect(self._on_tile_name_committed)
                    tile_widget.set_selected(dungeon["id"] == self._active_dungeon_id)
                    tile_widget.set_player_assigned(dungeon["id"] == self._players_dungeon_id)
                    tile_widget.set_player_placement_mode(self._player_placement_mode)
                    tile_widget.setFixedSize(self._tile_size)
                    try:
                        self._dungeon_list.setItemWidget(item, tile_widget)
                    except RuntimeError:
                        self._debug_log(
                            "dungeon_list_set_item_widget_runtime_error",
                            dungeon_id=str(dungeon.get("id") or ""),
                        )
                        tile_widget.deleteLater()
                        continue
                    self._tile_widgets[dungeon["id"]] = tile_widget
                if current_id:
                    for index in range(self._dungeon_list.count()):
                        item = self._dungeon_list.item(index)
                        if item.data(Qt.ItemDataRole.UserRole) == current_id:
                            self._dungeon_list.setCurrentItem(item)
                            break
                self._update_tile_selection(current_id)
            finally:
                self._dungeon_list.blockSignals(False)
                self._refreshing_dungeon_list = False

            QTimer.singleShot(0, self._refresh_hover_state)
            if not self._pending_dungeon_list_refresh:
                break

    def _refresh_hover_state(self) -> None:
        list_widget = self._dungeon_list
        if list_widget is None:
            return
        try:
            viewport = list_widget.viewport()
            hover_item = list_widget.itemAt(viewport.mapFromGlobal(QCursor.pos()))
        except RuntimeError:
            return
        hover_widget = None
        if hover_item is not None:
            try:
                hover_widget = list_widget.itemWidget(hover_item)
            except RuntimeError:
                return
        for dungeon_id, widget in self._tile_widgets.items():
            if widget is None:
                continue
            try:
                widget._set_hovered(widget is hover_widget)
            except RuntimeError:
                continue

    def _on_dungeon_selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return
        try:
            dungeon_id = current.data(Qt.ItemDataRole.UserRole)
        except RuntimeError:
            return
        if dungeon_id == self._active_dungeon_id:
            self._update_tile_selection(dungeon_id)
            QTimer.singleShot(0, self._refresh_hover_state)
            return
        self._switch_to_dungeon(dungeon_id)
        self._update_tile_selection(dungeon_id)
        QTimer.singleShot(0, self._refresh_hover_state)

    def _on_tile_clicked(self, dungeon_id: str) -> None:
        if self._player_placement_mode:
            self._assign_players_to_dungeon(dungeon_id)
            self._set_player_placement_mode(False)
        for index in range(self._dungeon_list.count()):
            item = self._dungeon_list.item(index)
            try:
                item_id = item.data(Qt.ItemDataRole.UserRole)
            except RuntimeError:
                continue
            if item_id == dungeon_id:
                self._dungeon_list.setCurrentItem(item)
                break
        self._update_tile_selection(dungeon_id)
        QTimer.singleShot(0, self._refresh_hover_state)

    def _on_player_placement_toggled(self, active: bool) -> None:
        self._set_player_placement_mode(active)

    def _on_selection_expanded_changed(self, expanded: bool) -> None:
        if not expanded and self._player_placement_mode:
            self._set_player_placement_mode(False)

    def _on_collection_autosave_toggled(self, enabled: bool) -> None:
        self._autosave_enabled = bool(enabled)
        self._save_local_profile()
        if self._autosave_enabled:
            self._schedule_collection_autosave()
        else:
            self._collection_autosave_timer.stop()
        self._position_floating_overlays()

    def _autosave_collection_path(self) -> Path:
        if self._collection_path is not None:
            stem = self._collection_path.stem
            if stem.endswith(COLLECTION_AUTOSAVE_SUFFIX):
                filename = f"{stem}{self._collection_path.suffix}"
            else:
                filename = (
                    f"{stem}{COLLECTION_AUTOSAVE_SUFFIX}"
                    f"{self._collection_path.suffix or COLLECTION_FILE_EXTENSION}"
                )
            return self._collection_path.with_name(filename)
        base_dir = self._collection_dir()
        stem = _sanitize_filename(self._collection_name, "dungeon_collection")
        return base_dir / f"{stem}{COLLECTION_AUTOSAVE_SUFFIX}{COLLECTION_FILE_EXTENSION}"

    def _schedule_collection_autosave(self) -> None:
        if not self._autosave_enabled:
            return
        if not self._collection_dirty:
            return
        if self._collection_autosave_timer.isActive():
            return
        self._collection_autosave_timer.start()

    def _run_collection_autosave(self) -> None:
        if not self._autosave_enabled:
            self._collection_autosave_timer.stop()
            return
        if self._online_mode == ONLINE_MODE_PLAYER:
            self._collection_autosave_timer.stop()
            return
        if not self._collection_dirty:
            self._collection_autosave_timer.stop()
            return
        autosave_path = self._autosave_collection_path()
        if self._save_collection_to_path(autosave_path, commit_as_primary=False):
            for dungeon in self._dungeons:
                dungeon["dirty"] = False
            self._collection_meta_dirty = False
            self._refresh_collection_dirty()
            autosave_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._autosave_status_label.setText(f"autosaved-{autosave_timestamp}")
            self._position_floating_overlays()

    def _set_player_placement_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._player_placement_mode == enabled:
            if hasattr(self, "selection_widget"):
                self.selection_widget.set_player_placement_active(enabled)
            return
        self._player_placement_mode = enabled
        for widget in self._tile_widgets.values():
            if widget is not None:
                widget.set_player_placement_mode(enabled)
        if hasattr(self, "selection_widget"):
            self.selection_widget.set_player_placement_active(enabled)
        QTimer.singleShot(0, self._refresh_hover_state)

    def _assign_players_to_dungeon(self, dungeon_id: str) -> None:
        if not dungeon_id:
            return
        if dungeon_id == self._players_dungeon_id:
            self._update_player_badges()
            return
        self._players_dungeon_id = dungeon_id
        self._collection_meta_dirty = True
        self._refresh_collection_dirty()
        self._update_player_badges()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _ensure_player_assignment(self, preferred_id: str | None = None, mark_dirty: bool = True) -> None:
        if not self._dungeons:
            self._players_dungeon_id = None
            return
        valid_ids = {d["id"] for d in self._dungeons}
        current = self._players_dungeon_id
        if current in valid_ids:
            self._update_player_badges()
            return
        target = None
        if preferred_id and preferred_id in valid_ids:
            target = preferred_id
        else:
            target = self._dungeons[0]["id"]
        self._players_dungeon_id = target
        if mark_dirty:
            self._collection_meta_dirty = True
            self._refresh_collection_dirty()
        self._update_player_badges()

    def _update_player_badges(self) -> None:
        for dungeon in self._dungeons:
            widget = self._tile_widgets.get(dungeon["id"])
            if widget:
                widget.set_player_assigned(dungeon["id"] == self._players_dungeon_id)

    def _is_entity_owned_by_local_player(self, entity: EntityItem) -> bool:
        local_id = self._local_player_id or ""
        if not local_id:
            return False
        return (entity.data(ROLE_OWNER_PLAYER_ID) or "") == local_id

    def _on_entity_owner_changed(self, _new_owner: str) -> None:
        target_entity = self.inspector._entity
        if self._online_mode == ONLINE_MODE_DM_HOST and isinstance(target_entity, EntityItem):
            self._apply_takeover_filter_for_entity(target_entity)
        self._mark_active_dungeon_dirty()
        self._apply_online_permissions()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _inventory_referenced_item_ids(self, inventory_payload: dict) -> list[str]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        ordered_item_ids: list[str] = []
        seen: set[str] = set()
        for entry in (
            normalized.get("inventory", [])
            if isinstance(normalized.get("inventory"), list)
            else []
        ):
            item_id = _inventory_entry_item_id(entry)
            if item_id and item_id not in seen:
                seen.add(item_id)
                ordered_item_ids.append(item_id)
        equipment_rows = normalized.get("equipment")
        if isinstance(equipment_rows, dict):
            for value in equipment_rows.values():
                item_id = _inventory_entry_item_id(value)
                if item_id and item_id not in seen:
                    seen.add(item_id)
                    ordered_item_ids.append(item_id)
        return ordered_item_ids

    def _filter_inventory_payload_to_dm_known_items(
        self,
        inventory_payload: dict,
    ) -> tuple[dict, list[str]]:
        normalized = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        referenced_item_ids = self._inventory_referenced_item_ids(normalized)
        missing_item_ids = {
            item_id
            for item_id in referenced_item_ids
            if self._linked_item_document_by_id(item_id) is None
        }
        if not missing_item_ids:
            return normalized, []
        filtered = self._remove_item_ids_from_inventory_payload(
            normalized,
            removed_item_ids=missing_item_ids,
        )
        filtered_documents: dict[str, dict] = {}
        for item_id in self._inventory_referenced_item_ids(filtered):
            document = self._linked_item_document_by_id(item_id)
            if isinstance(document, dict):
                filtered_documents[item_id] = self._clone_item_document_with_item_id(
                    document,
                    item_id,
                )
        filtered["item_documents"] = filtered_documents
        return normalize_inventory_payload(filtered), sorted(missing_item_ids)

    def _apply_takeover_filter_for_entity(self, entity: EntityItem) -> None:
        if self._online_mode != ONLINE_MODE_DM_HOST:
            return
        if not isinstance(entity, EntityItem):
            return
        owner_player_id = str(entity.data(ROLE_OWNER_PLAYER_ID) or "").strip()
        if not owner_player_id:
            return
        character_id = str(entity.data(ROLE_LINKED_CHARACTER_ID) or "").strip()
        sheet_id = str(entity.data(ROLE_LINKED_SHEET_ID) or "").strip()
        if not character_id and not sheet_id:
            return
        linked_inventory = (
            dict(entity.linked_inventory)
            if isinstance(getattr(entity, "linked_inventory", None), dict)
            else normalize_inventory_payload({})
        )
        filtered_inventory, removed_item_ids = self._filter_inventory_payload_to_dm_known_items(
            linked_inventory
        )
        if not removed_item_ids:
            return
        sync_metadata = self._next_linked_inventory_sync_metadata(
            owner_player_id="",
            character_id=character_id,
            sheet_id=sheet_id,
            inventory_payload=filtered_inventory,
        )
        updated = self._apply_inventory_sync_to_linked_entities(
            owner_player_id="",
            character_id=character_id,
            sheet_id=sheet_id,
            inventory_payload=filtered_inventory,
            save_revision=int(sync_metadata.get("save_revision") or 0),
            last_saved_at=str(sync_metadata.get("last_saved_at") or ""),
            content_hash=str(sync_metadata.get("content_hash") or ""),
        )
        if updated > 0:
            preview = ", ".join(removed_item_ids[:3])
            suffix = "..." if len(removed_item_ids) > 3 else ""
            self._append_server_log(
                "[INFO] Takeover filtered character inventory to DM-known items only "
                f"and removed {len(removed_item_ids)} item(s): {preview}{suffix}"
            )

    def _normalized_linked_stats(
        self,
        stats: dict,
        *,
        fallback_name: str = "",
    ) -> tuple[str, int | None, int | None, int | None, dict[str, int]]:
        clean_stats = stats if isinstance(stats, dict) else {}

        def _int_value(key: str) -> int | None:
            value = clean_stats.get(key)
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                return None
            return parsed

        label = str(clean_stats.get("name") or fallback_name or "").strip()
        hp_max = _int_value("hp_max")
        hp_current = _int_value("hp_current")
        hp_fallback = _int_value("hp")
        if hp_max is None:
            hp_max = hp_fallback
        hp = hp_current if hp_current is not None else hp_max
        if hp_max is not None and hp_max > 0 and hp is not None:
            hp = max(0, min(hp_max, hp))
        elif hp_max is not None and hp_max > 0:
            hp = hp_max
        else:
            hp_max = None
            hp = None
        ac = _int_value("ac")
        if ac is not None and ac <= 0:
            ac = None
        abilities: dict[str, int] = {}
        for key in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma"):
            value = _int_value(key)
            if value is not None:
                abilities[key] = value
        return label, hp_max, hp, ac, abilities

    def _apply_character_link_to_entity(
        self,
        entity: EntityItem,
        *,
        sheet_id: str,
        sheet_name: str,
        character_id: str = "",
        save_revision: int = 0,
        last_saved_at: str = "",
        content_hash: str = "",
        linked_inventory: dict,
        stats: dict,
        archive_b64: str = "",
    ) -> None:
        normalized_inventory = normalize_inventory_payload(
            linked_inventory if isinstance(linked_inventory, dict) else {}
        )
        entity.setData(ROLE_LINKED_SHEET_ID, sheet_id)
        entity.setData(ROLE_LINKED_SHEET_NAME, sheet_name)
        entity.setData(
            ROLE_LINKED_CHARACTER_ID,
            str(character_id or entity.data(ROLE_LINKED_CHARACTER_ID) or ""),
        )
        entity.linked_save_revision = int(save_revision or 0)
        entity.linked_last_saved_at = str(last_saved_at or "")
        entity.linked_content_hash = str(content_hash or "")
        entity.linked_inventory = dict(normalized_inventory)
        entity.linked_sheet_archive_b64 = str(archive_b64 or "")

        label, hp_max, hp, ac, abilities = self._normalized_linked_stats(stats, fallback_name=sheet_name)
        if label:
            entity.setData(ROLE_LABEL, label)
            if hasattr(self.inspector, "name_edit") and self.inspector.name_edit is not None:
                self.inspector.name_edit.setText(label)
        if hp_max is not None and hp_max > 0:
            entity._max_hp = hp_max
            entity.hp = hp if hp is not None else hp_max
        if ac is not None and ac > 0:
            entity.ac = ac
        for stat_key, stat_value in abilities.items():
            setattr(entity, stat_key, stat_value)

    def _clear_character_link_state_payload(self, item_data: dict) -> None:
        if not isinstance(item_data, dict):
            return
        item_data["linked_sheet_id"] = ""
        item_data["linked_sheet_name"] = ""
        item_data["linked_character_id"] = ""
        item_data["linked_save_revision"] = 0
        item_data["linked_last_saved_at"] = ""
        item_data["linked_content_hash"] = ""
        item_data["linked_sheet_archive_b64"] = ""
        item_data["linked_inventory"] = normalize_inventory_payload({})

    def _clear_character_link_from_entity(self, entity: EntityItem) -> None:
        entity.setData(ROLE_LINKED_SHEET_ID, "")
        entity.setData(ROLE_LINKED_SHEET_NAME, "")
        entity.setData(ROLE_LINKED_CHARACTER_ID, "")
        entity.linked_save_revision = 0
        entity.linked_last_saved_at = ""
        entity.linked_content_hash = ""
        entity.linked_sheet_archive_b64 = ""
        entity.linked_inventory = normalize_inventory_payload({})

    def _on_link_character_requested(self) -> None:
        entity = self.inspector._entity
        if not isinstance(entity, EntityItem):
            QMessageBox.information(self, "Link Character", "Select an entity first.")
            return
        if self._online_mode == ONLINE_MODE_PLAYER and not self._is_entity_owned_by_local_player(entity):
            QMessageBox.information(
                self,
                "Link Character",
                "You can only link characters to entities assigned to you.",
            )
            return
        if self._online_mode == ONLINE_MODE_DM_HOST:
            owner_player_id = str(entity.data(ROLE_OWNER_PLAYER_ID) or "").strip()
            linked_character_id = str(entity.data(ROLE_LINKED_CHARACTER_ID) or "").strip()
            linked_sheet_id = str(entity.data(ROLE_LINKED_SHEET_ID) or "").strip()
            if owner_player_id and owner_player_id in self._connected_players and (
                linked_character_id or linked_sheet_id
            ):
                QMessageBox.information(
                    self,
                    "Link Character",
                    "This assigned player's linked character is authoritative while they are connected.",
                )
                return
        try:
            from player_sheets import (
                character_id_for_entry,
                list_character_link_targets,
                sheet_id_for_entry,
                inventory_payload_for_sheet_id,
                ensure_entry_archive,
                character_sheet_pdf_path,
                character_sheet_archive_path,
            )
        except Exception:
            QMessageBox.warning(self, "Link Character", "Player sheets integration is unavailable.")
            return

        entries = list_character_link_targets()
        if not entries:
            QMessageBox.information(self, "Link Character", "No character sheets are available.")
            return
        labels: list[str] = []
        lookup: dict[str, object] = {}
        for entry in entries:
            sheet_id = sheet_id_for_entry(entry)
            label = f"{entry.name} ({sheet_id})"
            labels.append(label)
            lookup[label] = entry
        selected_label, ok = QInputDialog.getItem(
            self,
            "Link Character",
            "Character:",
            labels,
            0,
            False,
        )
        if not ok or not selected_label:
            return
        entry = lookup.get(selected_label)
        if entry is None:
            return
        try:
            sheet_id = sheet_id_for_entry(entry)  # type: ignore[arg-type]
            stored_character_id = character_id_for_entry(entry)  # type: ignore[arg-type]
            ensure_entry_archive(entry)  # type: ignore[arg-type]
            sheet_name = str(getattr(entry, "name", "") or sheet_id)
            pdf_path = str(getattr(entry, "pdf_path", "") or "").strip()
        except Exception:
            QMessageBox.warning(self, "Link Character", "Selected character entry is invalid.")
            return

        pdf_candidate = Path(pdf_path) if pdf_path else character_sheet_pdf_path(sheet_id)
        archive_path_text = str(getattr(entry, "archive_path", "") or "").strip()
        archive_candidate = Path(archive_path_text) if archive_path_text else character_sheet_archive_path(sheet_id)
        if pdf_candidate.suffix.lower() == ".dmtchar" or not pdf_candidate.exists():
            extracted_path = character_sheet_pdf_path(sheet_id)
            if archive_candidate.exists() and extract_character_pdf(archive_candidate, extracted_path):
                pdf_candidate = extracted_path
            elif extracted_path.exists():
                pdf_candidate = extracted_path

        if not pdf_candidate.exists():
            QMessageBox.warning(
                self,
                "Link Character",
                "Linked character PDF is missing. Open and save that character in Player Sheets first.",
            )
            return

        stats = _extract_character_stats_from_pdf(str(pdf_candidate))
        linked_inventory = inventory_payload_for_sheet_id(sheet_id) or {}
        character_id = str(stored_character_id or "").strip() or self._character_id_for_sheet(
            sheet_id,
            sheet_name=sheet_name,
        )
        save_revision = int(getattr(entry, "save_revision", 0) or 0)
        last_saved_at = str(getattr(entry, "last_saved_at", "") or "").strip()
        content_hash = str(getattr(entry, "content_hash", "") or "").strip()
        local_sync_payload = self._resolve_local_sheet_sync_payload(character_id) or {}
        archive_b64 = str(local_sync_payload.get("archive_b64") or "").strip()
        if not archive_b64:
            QMessageBox.warning(
                self,
                "Link Character",
                "Linked character archive is missing. Open and save that character in Player Sheets first.",
            )
            return
        if self._online_mode == ONLINE_MODE_PLAYER:
            entity_id = str(entity.data(ROLE_ENTITY_ID) or "").strip()
            if not entity_id:
                entity_id = uuid.uuid4().hex
                entity.setData(ROLE_ENTITY_ID, entity_id)
            if entity_id:
                request_payload = {
                    "entity_id": entity_id,
                    "sheet_id": sheet_id,
                    "sheet_name": sheet_name,
                    "character_id": character_id,
                    "save_revision": save_revision,
                    "last_saved_at": last_saved_at,
                    "content_hash": content_hash,
                    "inventory": normalize_inventory_payload(
                        linked_inventory if isinstance(linked_inventory, dict) else {}
                    ),
                    "stats": dict(stats),
                    "archive_b64": archive_b64,
                    "dungeon_id": str(self._active_dungeon_id or ""),
                }
                self._dispatch_player_link_character_request(request_payload)
            return

        self._apply_character_link_to_entity(
            entity,
            sheet_id=sheet_id,
            sheet_name=sheet_name,
            character_id=character_id,
            save_revision=save_revision,
            last_saved_at=last_saved_at,
            content_hash=content_hash,
            linked_inventory=linked_inventory,
            stats=stats,
            archive_b64=archive_b64,
        )

        if all(
            stats.get(key) is None
            for key in (
                "name",
                "strength",
                "dexterity",
                "constitution",
                "intelligence",
                "wisdom",
                "charisma",
                "ac",
                "hp_max",
                "hp_current",
                "hp",
            )
        ):
            QMessageBox.information(
                self,
                "Link Character",
                "Character linked, but no stats could be read from the PDF fields.",
            )

        entity.update()
        self.inspector.set_linked_character_info(sheet_name)
        self.inspector.set_entity(entity)
        self._position_floating_overlays()
        self._mark_active_dungeon_dirty()
        self._cleanup_unlinked_managed_character_artifacts()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _on_unlink_character_requested(self) -> None:
        entity = self.inspector._entity
        if not isinstance(entity, EntityItem):
            QMessageBox.information(self, "Unlink Character", "Select an entity first.")
            return
        linked_sheet_id = str(entity.data(ROLE_LINKED_SHEET_ID) or "").strip()
        linked_name = str(entity.data(ROLE_LINKED_SHEET_NAME) or linked_sheet_id).strip()
        if not linked_sheet_id:
            QMessageBox.information(self, "Unlink Character", "This entity has no linked character.")
            return
        if self._online_mode == ONLINE_MODE_PLAYER and not self._is_entity_owned_by_local_player(entity):
            QMessageBox.information(
                self,
                "Unlink Character",
                "You can only unlink characters from entities assigned to you.",
            )
            return
        prompt_name = linked_name or linked_sheet_id or "this character"
        confirm = QMessageBox.question(
            self,
            "Unlink Character",
            f"Unlink '{prompt_name}' from this entity?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        if self._online_mode == ONLINE_MODE_PLAYER:
            entity_id = str(entity.data(ROLE_ENTITY_ID) or "").strip()
            if not entity_id:
                QMessageBox.warning(
                    self,
                    "Unlink Character",
                    "This entity cannot be unlinked because it has no persistent entity id.",
                )
                return
            request_payload = {
                "entity_id": entity_id,
                "dungeon_id": str(self._active_dungeon_id or ""),
            }
            self._dispatch_player_unlink_character_request(request_payload)
            return
        cleared_character_id = str(entity.data(ROLE_LINKED_CHARACTER_ID) or "").strip()
        if cleared_character_id:
            self._approved_host_inventory_sync_characters.discard(cleared_character_id)
        self._clear_character_link_from_entity(entity)
        entity.update()
        self.inspector.set_linked_character_info("")
        self.inspector.set_entity(entity)
        self._position_floating_overlays()
        self._mark_active_dungeon_dirty()
        self._cleanup_unlinked_managed_character_artifacts()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _apply_inventory_sync_to_linked_entities(
        self,
        *,
        owner_player_id: str,
        character_id: str,
        sheet_id: str = "",
        inventory_payload: dict,
        save_revision: int | None = None,
        last_saved_at: str | None = None,
        content_hash: str | None = None,
        stats: dict | None = None,
        archive_b64: str | None = None,
    ) -> int:
        clean_character = str(character_id or "").strip()
        clean_sheet = str(sheet_id or "").strip()
        if not clean_character and not clean_sheet:
            return 0
        normalized = normalize_inventory_payload(inventory_payload if isinstance(inventory_payload, dict) else {})
        owner_filter = str(owner_player_id or "").strip()
        stats_payload = dict(stats or {})
        updated = 0
        for dungeon in self._dungeons:
            state = dungeon.get("state")
            if not isinstance(state, dict):
                continue
            items = state.get("items")
            if not isinstance(items, list):
                continue
            dungeon_updated = False
            for item_data in items:
                if not isinstance(item_data, dict):
                    continue
                if item_data.get("type") != "entity":
                    continue
                if clean_character:
                    if str(item_data.get("linked_character_id") or "") != clean_character:
                        continue
                elif str(item_data.get("linked_sheet_id") or "") != clean_sheet:
                    continue
                if owner_filter and str(item_data.get("owner_player_id") or "") != owner_filter:
                    continue
                item_data["linked_inventory"] = dict(normalized)
                if save_revision is not None:
                    item_data["linked_save_revision"] = int(save_revision)
                if last_saved_at is not None:
                    item_data["linked_last_saved_at"] = str(last_saved_at)
                if content_hash is not None:
                    item_data["linked_content_hash"] = str(content_hash)
                if archive_b64 is not None:
                    item_data["linked_sheet_archive_b64"] = str(archive_b64)
                label, max_hp, hp, ac, abilities = self._normalized_linked_stats(
                    stats_payload,
                    fallback_name=str(item_data.get("linked_sheet_name") or item_data.get("label") or ""),
                )
                if label:
                    item_data["label"] = label
                if max_hp is not None:
                    item_data["max_hp"] = int(max_hp)
                if hp is not None:
                    item_data["hp"] = int(hp)
                if ac is not None:
                    item_data["ac"] = int(ac)
                for stat_key, stat_value in abilities.items():
                    item_data[stat_key] = int(stat_value)
                dungeon_updated = True
                updated += 1
            if dungeon_updated:
                dungeon["dirty"] = True
                dungeon["preview"] = None
                dungeon["preview_signature"] = None

        prior_suppress_network_sync = bool(self._suppress_network_sync)
        self._suppress_network_sync = True
        try:
            for item in self.canvas.scene().items():
                if not isinstance(item, EntityItem):
                    continue
                if clean_character:
                    if str(item.data(ROLE_LINKED_CHARACTER_ID) or "") != clean_character:
                        continue
                elif str(item.data(ROLE_LINKED_SHEET_ID) or "") != clean_sheet:
                    continue
                if owner_filter and str(item.data(ROLE_OWNER_PLAYER_ID) or "") != owner_filter:
                    continue
                item.linked_inventory = dict(normalized)
                if save_revision is not None:
                    item.linked_save_revision = int(save_revision)
                if last_saved_at is not None:
                    item.linked_last_saved_at = str(last_saved_at)
                if content_hash is not None:
                    item.linked_content_hash = str(content_hash)
                if archive_b64 is not None:
                    item.linked_sheet_archive_b64 = str(archive_b64)
                label, max_hp, hp, ac, abilities = self._normalized_linked_stats(
                    stats_payload,
                    fallback_name=str(item.data(ROLE_LINKED_SHEET_NAME) or item.data(ROLE_LABEL) or ""),
                )
                if label:
                    item.setData(ROLE_LABEL, label)
                if max_hp is not None and max_hp > 0:
                    item._max_hp = max_hp
                    item.hp = hp if hp is not None else max_hp
                if ac is not None and ac > 0:
                    item.ac = ac
                for stat_key, stat_value in abilities.items():
                    setattr(item, stat_key, stat_value)
                item.update()
        finally:
            self._suppress_network_sync = prior_suppress_network_sync

        return updated

    def _dispatch_online_character_inventory_sync(
        self,
        sheet_id: str,
        inventory_payload: dict,
        *,
        claim_id: str = "",
        log_conflict_blocked: bool = True,
    ) -> tuple[str | None, str]:
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return None, ""
        payload = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        try:
            from player_sheets import character_id_for_sheet_id, inventory_payload_for_sheet_id
        except Exception:
            character_id_for_sheet_id = None  # type: ignore[assignment]
            inventory_payload_for_sheet_id = None  # type: ignore[assignment]
        if inventory_payload_for_sheet_id is not None:
            persisted_payload = inventory_payload_for_sheet_id(clean_sheet)
            if isinstance(persisted_payload, dict):
                payload = normalize_inventory_payload(persisted_payload)
        character_id = ""
        if character_id_for_sheet_id is not None:
            character_id = str(character_id_for_sheet_id(clean_sheet) or "").strip()
        if self._online_mode != ONLINE_MODE_PLAYER:
            return None, character_id
        if not character_id:
            return None, ""
        sync_payload = self._resolve_local_sheet_sync_payload(character_id) or {}
        sync_request = {
            "character_id": character_id,
            "sheet_id": clean_sheet,
            "save_revision": int(sync_payload.get("save_revision") or 0),
            "last_saved_at": str(sync_payload.get("last_saved_at") or ""),
            "content_hash": str(sync_payload.get("content_hash") or ""),
            "inventory": payload,
            "stats": dict(sync_payload.get("stats") or {}),
            "archive_b64": str(sync_payload.get("archive_b64") or ""),
            "dungeon_id": str(self._active_dungeon_id or ""),
        }
        clean_claim_id = str(claim_id or "").strip()
        if clean_claim_id:
            sync_request["claim_id"] = clean_claim_id
        request_id = self._dispatch_player_command_with_request_id(
            "sync_character_inventory",
            sync_request,
            silent=True,
        )
        return request_id, character_id

    def _on_external_character_inventory_saved(self, sheet_id: str, inventory_payload: dict) -> None:
        if self._suppress_external_inventory_forward:
            return
        clean_sheet = str(sheet_id or "").strip()
        if not clean_sheet:
            return
        if self._online_mode == ONLINE_MODE_PLAYER:
            claim_id = self._pending_loot_claim_id_for_sheet(
                clean_sheet,
                status="awaiting_sync_dispatch",
            )
            request_id, character_id = self._dispatch_online_character_inventory_sync(
                clean_sheet,
                inventory_payload,
                claim_id=claim_id,
                log_conflict_blocked=not bool(claim_id),
            )
            if claim_id:
                pending = self._pending_loot_claim_rollbacks.get(claim_id)
                if isinstance(pending, dict):
                    pending["character_id"] = character_id
                    if request_id is None:
                        pending["status"] = "awaiting_sync_dispatch"
                    else:
                        pending["status"] = "sync_inflight"
                        pending["sync_request_id"] = request_id
                    self._pending_loot_claim_rollbacks[claim_id] = pending
            return
        payload = normalize_inventory_payload(
            inventory_payload if isinstance(inventory_payload, dict) else {}
        )
        try:
            from player_sheets import character_id_for_sheet_id
        except Exception:
            character_id_for_sheet_id = None  # type: ignore[assignment]
        character_id = ""
        if character_id_for_sheet_id is not None:
            character_id = str(character_id_for_sheet_id(clean_sheet) or "").strip()
        owner = ""
        if self._online_mode == ONLINE_MODE_DM_HOST:
            owner = ""
        sync_payload = self._resolve_local_sheet_sync_payload(character_id) if character_id else None
        if isinstance(sync_payload, dict):
            save_revision = int(sync_payload.get("save_revision") or 0)
            last_saved_at = str(sync_payload.get("last_saved_at") or "")
            content_hash = str(sync_payload.get("content_hash") or "")
        else:
            fallback_metadata = self._next_linked_inventory_sync_metadata(
                owner_player_id=owner,
                character_id=character_id,
                sheet_id=clean_sheet,
                inventory_payload=payload,
            )
            save_revision = int(fallback_metadata.get("save_revision") or 0)
            last_saved_at = str(fallback_metadata.get("last_saved_at") or "")
            content_hash = str(fallback_metadata.get("content_hash") or "")
        archive_b64 = None
        if isinstance(sync_payload, dict):
            resolved_archive_b64 = str(sync_payload.get("archive_b64") or "").strip()
            if resolved_archive_b64:
                archive_b64 = resolved_archive_b64
        self._apply_inventory_sync_to_linked_entities(
            owner_player_id=owner,
            character_id=character_id,
            sheet_id=clean_sheet,
            inventory_payload=payload,
            save_revision=save_revision,
            last_saved_at=last_saved_at,
            content_hash=content_hash,
            stats=dict(sync_payload.get("stats") or {}) if isinstance(sync_payload, dict) else {},
            archive_b64=archive_b64,
        )
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._broadcast_snapshot_if_host()

    def _update_tile_selection(self, current_id: str | None) -> None:
        if current_id is None:
            item = self._dungeon_list.currentItem()
            if item is not None:
                try:
                    current_id = item.data(Qt.ItemDataRole.UserRole)
                except RuntimeError:
                    current_id = None
            if current_id is None:
                current_id = self._active_dungeon_id
        for dungeon in self._dungeons:
            widget = self._tile_widgets.get(dungeon["id"])
            if widget:
                widget.set_selected(dungeon["id"] == current_id)

    def _on_tile_name_changed(self, dungeon_id: str, name: str) -> None:
        if self._suppress_list_edits:
            return
        dungeon = self._find_dungeon(dungeon_id)
        if not dungeon:
            return
        tile_widget = self._tile_widgets.get(dungeon_id)
        if tile_widget:
            tile_widget.set_selected(dungeon_id == self._active_dungeon_id)
        new_name = name.strip()
        if not new_name:
            return
        if new_name != dungeon["name"]:
            dungeon["name"] = new_name
            dungeon["dirty"] = True
            self._collection_meta_dirty = True
            self._refresh_collection_dirty()
            if dungeon_id == self._active_dungeon_id:
                self._update_active_dungeon_label()

    def _on_tile_name_committed(self, dungeon_id: str, name: str) -> None:
        dungeon = self._find_dungeon(dungeon_id)
        if not dungeon:
            return
        tile_widget = self._tile_widgets.get(dungeon_id)
        if tile_widget:
            tile_widget.set_selected(dungeon_id == self._active_dungeon_id)
        new_name = name.strip()
        if not new_name:
            if tile_widget:
                self._suppress_list_edits = True
                tile_widget.name_edit.setText(dungeon["name"])
                self._suppress_list_edits = False
            return
        if new_name != dungeon["name"]:
            dungeon["name"] = new_name
            dungeon["dirty"] = True
            self._collection_meta_dirty = True
            self._refresh_collection_dirty()
        if dungeon_id == self._active_dungeon_id:
            self._update_active_dungeon_label()

    def _on_dungeon_item_edited(self, item: QListWidgetItem) -> None:
        if self._suppress_list_edits:
            return
        dungeon_id = item.data(Qt.ItemDataRole.UserRole)
        dungeon = self._find_dungeon(dungeon_id)
        if not dungeon:
            return
        new_name = item.text().strip()
        if not new_name:
            self._suppress_list_edits = True
            item.setText(dungeon["name"])
            self._suppress_list_edits = False
            return
        if new_name == dungeon["name"]:
            return
        dungeon["name"] = new_name
        dungeon["dirty"] = True
        self._collection_meta_dirty = True
        self._refresh_collection_dirty()
        if dungeon_id == self._active_dungeon_id:
            self._update_active_dungeon_label()

    def _switch_to_dungeon(self, dungeon_id: str, save_current: bool = True) -> None:
        if save_current:
            self._save_active_dungeon_state()
        target = self._find_dungeon(dungeon_id)
        if not target:
            return
        self._active_dungeon_id = dungeon_id
        self._load_dungeon_state(target["state"])
        self._refresh_dungeon_list(preserve_selection=True)
        self._update_active_dungeon_label()
        self._broadcast_snapshot_if_host()

    def _save_active_dungeon_state(self) -> None:
        dungeon = self._current_dungeon()
        if not dungeon:
            return
        dungeon["state"] = self._serialize_scene()
        icon_size = self._dungeon_list.iconSize()
        if icon_size.isValid():
            dungeon["preview"] = self._render_scene_preview(icon_size)
            dungeon["preview_signature"] = self._preview_render_signature(icon_size)

    def _bind_image_resize_undo(self, scene: QGraphicsScene, item) -> None:
        if scene is not self.canvas.scene():
            item.set_resize_finished_callback(None)
            return
        from dungeon_commands import ResizeImageCommand
        item.set_resize_finished_callback(
            lambda old_rect, new_rect, old_pos, new_pos, image_item=item: self.canvas.undo_stack.push(
                ResizeImageCommand(image_item, old_rect, new_rect, old_pos, new_pos)
            )
        )

    def _serialize_scene(self) -> dict:
        from dungeon_items import RoomGroup, DungeonImageItem
        from dungeon_constants import ROLE_KIND, ROLE_LABEL, ROLE_LOCKED, WALL_COLOR, WALL_WIDTH

        items_data: list[dict] = []
        fog_path_data: list[dict] = []
        for item in self.canvas.scene().items():
            if item.parentItem() is not None:
                continue
            if isinstance(item, FogItem):
                fog_path_data = _serialize_path(item.path())
                continue
            if isinstance(item, RoomGroup):
                floor_path = _extract_room_floor_path(item)
                if floor_path.isEmpty():
                    continue
                items_data.append(
                    {
                        "type": "room",
                        "kind": item.data(ROLE_KIND) or TOOL_ROOM,
                        "locked": bool(item.data(ROLE_LOCKED)),
                        "layer": item.data(ROLE_LAYER) or LAYER_FG,
                        "z": float(item.zValue()),
                        "pos": [float(item.pos().x()), float(item.pos().y())],
                        "floor_path": _serialize_path(floor_path),
                    }
                )
                continue
            if isinstance(item, EntityItem):
                linked_inventory = getattr(item, "linked_inventory", {})
                items_data.append(
                    {
                        "type": "entity",
                        "pos": [float(item.pos().x()), float(item.pos().y())],
                        "color": item._color.name(),
                        "hp": int(item.hp),
                        "max_hp": int(item._max_hp),
                        "ac": int(item.ac),
                        "strength": int(getattr(item, "strength", 10)),
                        "dexterity": int(getattr(item, "dexterity", 10)),
                        "constitution": int(getattr(item, "constitution", 10)),
                        "intelligence": int(getattr(item, "intelligence", 10)),
                        "wisdom": int(getattr(item, "wisdom", 10)),
                        "charisma": int(getattr(item, "charisma", 10)),
                        "actions": getattr(item, "actions", ""),
                        "description": getattr(item, "description", ""),
                        "icon_path": item.data(ROLE_ICON) or getattr(item, "icon_path", ""),
                        "size_w_cells": int(getattr(item, "size_w_cells", 1)),
                        "size_h_cells": int(getattr(item, "size_h_cells", 1)),
                        "lock_square": bool(getattr(item, "lock_square", True)),
                        "label": item.data(ROLE_LABEL) or "",
                        "owner_player_id": item.data(ROLE_OWNER_PLAYER_ID) or "",
                        "entity_id": item.data(ROLE_ENTITY_ID) or uuid.uuid4().hex,
                        "linked_sheet_id": item.data(ROLE_LINKED_SHEET_ID) or "",
                        "linked_sheet_name": item.data(ROLE_LINKED_SHEET_NAME) or "",
                        "linked_character_id": item.data(ROLE_LINKED_CHARACTER_ID) or "",
                        "linked_save_revision": int(getattr(item, "linked_save_revision", 0) or 0),
                        "linked_last_saved_at": str(getattr(item, "linked_last_saved_at", "") or ""),
                        "linked_content_hash": str(getattr(item, "linked_content_hash", "") or ""),
                        "linked_sheet_archive_b64": str(getattr(item, "linked_sheet_archive_b64", "") or ""),
                        "linked_inventory": normalize_inventory_payload(linked_inventory if isinstance(linked_inventory, dict) else {}),
                        "layer": item.data(ROLE_LAYER) or LAYER_FG,
                        "z": float(item.zValue()),
                    }
                )
                continue
            if isinstance(item, DungeonImageItem):
                items_data.append(
                    {
                        "type": "image",
                        "source_path": item.source_path,
                        "pos": [float(item.pos().x()), float(item.pos().y())],
                        "width": float(item._rect.width()),
                        "height": float(item._rect.height()),
                        "keep_aspect": bool(item.keep_aspect),
                        "aspect_ratio": float(item._aspect_ratio),
                        "layer": item.data(ROLE_LAYER) or LAYER_FG,
                        "z": float(item.zValue()),
                    }
                )
                continue
            if isinstance(item, QGraphicsPathItem) and item.data(ROLE_KIND) == "stroke":
                pen = item.pen()
                stroke_id = str(item.data(ROLE_ENTITY_ID) or "").strip()
                if not stroke_id:
                    stroke_id = uuid.uuid4().hex
                    item.setData(ROLE_ENTITY_ID, stroke_id)
                owner_player_id = str(item.data(ROLE_OWNER_PLAYER_ID) or "").strip()
                items_data.append(
                    {
                        "type": "stroke",
                        "stroke_id": stroke_id,
                        "owner_player_id": owner_player_id,
                        "pos": [float(item.pos().x()), float(item.pos().y())],
                        "path": _serialize_path(item.path()),
                        "pen_color": pen.color().name() or WALL_COLOR,
                        "pen_width": float(pen.widthF() or WALL_WIDTH),
                        "layer": item.data(ROLE_LAYER) or LAYER_FG,
                        "z": float(item.zValue()),
                    }
                )
                continue
        return {"items": items_data, "fog": {"path": fog_path_data}}

    def _populate_scene(self, scene: QGraphicsScene, state: dict, include_fog: bool = True) -> FogItem | None:
        from dungeon_items import RoomGroup, DungeonImageItem
        from dungeon_constants import ROLE_KIND, ROLE_LABEL, ROLE_LOCKED, WALL_COLOR, WALL_WIDTH

        fog_item: FogItem | None = None
        for item_data in state.get("items", []):
            item_type = item_data.get("type")
            if item_type == "room":
                path = _deserialize_path(item_data.get("floor_path", []))
                if path.isEmpty():
                    continue
                layer = item_data.get("layer", LAYER_FG) or LAYER_FG
                room = RoomGroup()
                room.setZValue(float(item_data.get("z", _default_item_z("room", layer))))
                room.setData(ROLE_LAYER, layer)
                room.setData(ROLE_KIND, item_data.get("kind", TOOL_ROOM))
                room.setData(ROLE_LOCKED, bool(item_data.get("locked", False)))
                room.add_path_floor(path)
                _add_walls_from_path(room, path)
                pos = item_data.get("pos", [0.0, 0.0])
                room.setPos(float(pos[0]), float(pos[1]))
                scene.addItem(room)
                continue
            if item_type == "entity":
                pos = item_data.get("pos", [0.0, 0.0])
                layer = item_data.get("layer", LAYER_FG) or LAYER_FG
                color = QColor(item_data.get("color", "#3B82F6"))
                hp = int(item_data.get("hp", 100))
                max_hp = int(item_data.get("max_hp", hp))
                ac = int(item_data.get("ac", 10))
                icon_ref = str(item_data.get("icon_path", "") or "")
                runtime_icon_path = self._resolve_runtime_icon_path(icon_ref)
                entity = EntityItem(
                    QPointF(float(pos[0]), float(pos[1])),
                    color=color,
                    hp=hp,
                    max_hp=max_hp,
                    ac=ac,
                    strength=int(item_data.get("strength", 10)),
                    dexterity=int(item_data.get("dexterity", 10)),
                    constitution=int(item_data.get("constitution", 10)),
                    intelligence=int(item_data.get("intelligence", 10)),
                    wisdom=int(item_data.get("wisdom", 10)),
                    charisma=int(item_data.get("charisma", 10)),
                    actions=item_data.get("actions", ""),
                    description=item_data.get("description", ""),
                    icon_path=runtime_icon_path,
                    size_w_cells=int(item_data.get("size_w_cells", 1)),
                    size_h_cells=int(item_data.get("size_h_cells", 1)),
                    lock_square=bool(item_data.get("lock_square", True)),
                )
                entity.set_view_mode(self._view_mode)
                entity.setZValue(float(item_data.get("z", _default_item_z("entity", layer))))
                entity.setData(ROLE_KIND, "entity")
                entity.setData(ROLE_LAYER, layer)
                entity.setData(ROLE_ICON, icon_ref)
                entity.setData(ROLE_OWNER_PLAYER_ID, item_data.get("owner_player_id", "") or "")
                entity.setData(ROLE_ENTITY_ID, item_data.get("entity_id") or uuid.uuid4().hex)
                entity.setData(ROLE_LINKED_SHEET_ID, item_data.get("linked_sheet_id", "") or "")
                entity.setData(ROLE_LINKED_SHEET_NAME, item_data.get("linked_sheet_name", "") or "")
                entity.setData(ROLE_LINKED_CHARACTER_ID, item_data.get("linked_character_id", "") or "")
                entity.linked_save_revision = int(item_data.get("linked_save_revision", 0) or 0)
                entity.linked_last_saved_at = str(item_data.get("linked_last_saved_at", "") or "")
                entity.linked_content_hash = str(item_data.get("linked_content_hash", "") or "")
                entity.linked_sheet_archive_b64 = str(item_data.get("linked_sheet_archive_b64", "") or "")
                linked_inventory = item_data.get("linked_inventory")
                entity.linked_inventory = normalize_inventory_payload(linked_inventory if isinstance(linked_inventory, dict) else {})
                label = item_data.get("label")
                if label:
                    entity.setData(ROLE_LABEL, label)
                scene.addItem(entity)
                continue
            if item_type == "image":
                layer = item_data.get("layer", LAYER_FG) or LAYER_FG
                pos = item_data.get("pos", [0.0, 0.0])
                width = max(20, int(float(item_data.get("width", 120))))
                height = max(20, int(float(item_data.get("height", 90))))
                source_path = str(item_data.get("source_path", "") or "")
                pixmap = QPixmap(source_path) if source_path else QPixmap()
                if pixmap.isNull():
                    pixmap = DungeonImageItem._placeholder_pixmap(width, height)
                image_item = DungeonImageItem(
                    pixmap,
                    QPointF(float(pos[0]), float(pos[1])),
                    source_path=source_path,
                )
                image_item.set_rect_size(width, height)
                image_item.keep_aspect = bool(item_data.get("keep_aspect", False))
                aspect_ratio = float(item_data.get("aspect_ratio", 0.0))
                if aspect_ratio > 0:
                    image_item._aspect_ratio = aspect_ratio
                image_item.setData(ROLE_KIND, "image")
                image_item.setData(ROLE_LAYER, layer)
                image_item.setZValue(float(item_data.get("z", _default_item_z("image", layer))))
                self._bind_image_resize_undo(scene, image_item)
                scene.addItem(image_item)
                continue
            if item_type == "stroke":
                path = _deserialize_path(item_data.get("path", []))
                if path.isEmpty():
                    continue
                layer = item_data.get("layer", LAYER_FG) or LAYER_FG
                stroke = QGraphicsPathItem(path)
                pen_color = QColor(item_data.get("pen_color", WALL_COLOR))
                pen_width = float(item_data.get("pen_width", WALL_WIDTH))
                stroke.setPen(QPen(pen_color, pen_width))
                try:
                    stroke_z = float(item_data.get("z", _default_item_z("stroke", layer)))
                except (TypeError, ValueError):
                    stroke_z = _default_item_z("stroke", layer)
                if stroke_z <= FOG_OVERLAY_Z:
                    stroke_z = _default_item_z("stroke", layer)
                stroke.setZValue(stroke_z)
                stroke.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsSelectable, True)
                stroke.setFlag(QGraphicsPathItem.GraphicsItemFlag.ItemIsMovable, True)
                stroke.setData(ROLE_KIND, "stroke")
                stroke.setData(ROLE_LAYER, layer)
                stroke.setData(ROLE_LOCKED, False)
                stroke.setData(
                    ROLE_OWNER_PLAYER_ID,
                    str(item_data.get("owner_player_id") or "").strip(),
                )
                stroke_id = str(item_data.get("stroke_id") or item_data.get("entity_id") or "").strip()
                if not stroke_id:
                    stroke_id = uuid.uuid4().hex
                stroke.setData(ROLE_ENTITY_ID, stroke_id)
                pos = item_data.get("pos", [0.0, 0.0])
                stroke.setPos(float(pos[0]), float(pos[1]))
                scene.addItem(stroke)
                continue
        if include_fog:
            fog_data = state.get("fog", {}).get("path")
            if fog_data:
                fog_item = FogItem()
                fog_item.setPath(_deserialize_path(fog_data))
                fog_item.set_view_mode(self._view_mode)
                scene.addItem(fog_item)
        return fog_item

    def _load_dungeon_state(self, state: dict) -> None:
        was_suppressed = self._suppress_change_tracking
        self._suppress_change_tracking = True
        try:
            scene = self.canvas.scene()
            scene.clear()
            self.canvas.fog_item = None
            self.canvas.undo_stack.clear()
            fog_item = self._populate_scene(scene, state, include_fog=True)
            self.canvas.fog_item = fog_item
            self.canvas.set_view_mode(self._view_mode)
            self.canvas.undo_stack.clear()
            self._refresh_scene_item_references()
        finally:
            self._suppress_change_tracking = was_suppressed
        self._refresh_entity_duplicate_badges()
        self._apply_online_permissions()

    def _render_scene_preview(self, size: QSize) -> QPixmap:
        square_size = min(size.width(), size.height())
        if square_size <= 0:
            return QPixmap()
        dpr = self._effective_device_pixel_ratio()
        pixel_size = max(1, int(round(square_size * dpr)))
        image = QImage(QSize(pixel_size, pixel_size), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#09090b"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        bounds = self._preview_bounds(self.canvas.scene())
        target = QRectF(0, 0, pixel_size, pixel_size)
        self.canvas.scene().render(painter, target, bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self._draw_preview_grid(painter, bounds, target)
        painter.end()
        image.setDevicePixelRatio(dpr)
        return QPixmap.fromImage(image)

    def _render_state_preview(self, state: dict, size: QSize) -> QPixmap:
        square_size = min(size.width(), size.height())
        if square_size <= 0:
            return QPixmap()
        dpr = self._effective_device_pixel_ratio()
        pixel_size = max(1, int(round(square_size * dpr)))
        scene = QGraphicsScene()
        scene.setSceneRect(-50000, -50000, 100000, 100000)
        self._populate_scene(scene, state, include_fog=True)
        image = QImage(QSize(pixel_size, pixel_size), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#09090b"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        bounds = self._preview_bounds(scene)
        target = QRectF(0, 0, pixel_size, pixel_size)
        scene.render(painter, target, bounds, Qt.AspectRatioMode.KeepAspectRatio)
        self._draw_preview_grid(painter, bounds, target)
        painter.end()
        image.setDevicePixelRatio(dpr)
        return QPixmap.fromImage(image)

    def _draw_preview_grid(self, painter: QPainter, bounds: QRectF, target: QRectF) -> None:
        if bounds is None or bounds.isNull() or bounds.width() <= 0 or bounds.height() <= 0:
            return
        scale = min(target.width() / bounds.width(), target.height() / bounds.height())
        if scale <= 0:
            return
        offset_x = target.left() + (target.width() - bounds.width() * scale) / 2.0
        offset_y = target.top() + (target.height() - bounds.height() * scale) / 2.0
        step = GRID_SIZE * scale
        if step < 4:
            return
        pen = QPen(QColor(255, 255, 255, 18), 1.0)
        painter.save()
        painter.setPen(pen)
        start_x = math.floor(bounds.left() / GRID_SIZE) * GRID_SIZE
        end_x = bounds.right()
        x = start_x
        while x <= end_x:
            px = offset_x + (x - bounds.left()) * scale
            painter.drawLine(int(px), int(offset_y), int(px), int(offset_y + bounds.height() * scale))
            x += GRID_SIZE
        start_y = math.floor(bounds.top() / GRID_SIZE) * GRID_SIZE
        end_y = bounds.bottom()
        y = start_y
        while y <= end_y:
            py = offset_y + (y - bounds.top()) * scale
            painter.drawLine(int(offset_x), int(py), int(offset_x + bounds.width() * scale), int(py))
            y += GRID_SIZE
        painter.restore()

    def _preview_bounds(self, scene: QGraphicsScene) -> QRectF:
        bounds: QRectF | None = None
        for item in scene.items():
            if isinstance(item, FogItem):
                continue
            item_bounds = item.sceneBoundingRect()
            if bounds is None:
                bounds = QRectF(item_bounds)
            else:
                bounds = bounds.united(item_bounds)
        if bounds is None or bounds.isNull() or bounds.width() < 1 or bounds.height() < 1:
            side = max(1.0, float(GRID_SIZE * 2))
            return QRectF(-side / 2, -side / 2, side, side)
        side = max(bounds.width(), bounds.height(), 1.0)
        center = bounds.center()
        return QRectF(center.x() - side / 2, center.y() - side / 2, side, side)

    def _update_active_preview(self) -> None:
        dungeon = self._current_dungeon()
        if not dungeon:
            return
        icon_size = self._dungeon_list.iconSize()
        if not icon_size.isValid():
            return
        dungeon["preview"] = self._render_scene_preview(icon_size)
        dungeon["preview_signature"] = self._preview_render_signature(icon_size)
        self._refresh_dungeon_list(preserve_selection=True)

    def _preview_render_signature(self, size: QSize) -> tuple[int, int, int]:
        dpr_key = int(round(self._effective_device_pixel_ratio() * 100.0))
        return (max(1, size.width()), max(1, size.height()), dpr_key)

    def _effective_device_pixel_ratio(self) -> float:
        dpr = float(self.devicePixelRatioF())
        if dpr <= 0:
            return 1.0
        return dpr

    def _on_canvas_changed(self) -> None:
        if self._suppress_change_tracking:
            return
        if self._suppress_network_sync:
            return
        self._refresh_entity_duplicate_badges()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._sync_host_scene_icons_for_online()
            self._seed_initiative_state()
            self._render_initiative_overlay()
        self._mark_active_dungeon_dirty()
        self._preview_timer.start()
        if self._online_mode == ONLINE_MODE_DM_HOST:
            self._host_scene_sync_pending = False
            self._host_scene_sync_timer.stop()
            self._broadcast_snapshot_if_host()
        elif (
            self._online_mode == ONLINE_MODE_PLAYER
        ):
            self._apply_online_permissions()
            state_update_payload = {
                "state": self._serialize_scene(),
                "dungeon_id": self._active_dungeon_id,
            }
            self._send_player_state_update(state_update_payload)

    def _on_canvas_delete_items_changed(self) -> None:
        self._save_active_dungeon_state()
        if self._online_mode != ONLINE_MODE_PLAYER:
            self._cleanup_unlinked_managed_character_artifacts()

    def _refresh_entity_duplicate_badges(self) -> None:
        scene = self.canvas.scene()
        for item in scene.items():
            if isinstance(item, EntityItem):
                item.update()

    def _mark_active_dungeon_dirty(self) -> None:
        dungeon = self._current_dungeon()
        if not dungeon:
            return
        if not dungeon.get("dirty"):
            dungeon["dirty"] = True
        self._refresh_collection_dirty()

    def _refresh_collection_dirty(self) -> None:
        dirty = self._collection_meta_dirty or any(d.get("dirty") for d in self._dungeons)
        self._collection_dirty = dirty
        self._update_collection_header()
        if dirty and self._online_mode != ONLINE_MODE_PLAYER:
            self._schedule_collection_autosave()
        else:
            self._collection_autosave_timer.stop()

    def _update_collection_header(self) -> None:
        if not hasattr(self, "selection_widget"):
            return
        self.selection_widget.set_header_text(self._collection_name)
        self.selection_widget.set_header_dirty(self._collection_dirty)

    def _update_active_dungeon_label(self) -> None:
        if not hasattr(self, "selection_widget"):
            return
        dungeon = self._current_dungeon()
        name = dungeon["name"] if dungeon else "Dungeon"
        self.selection_widget.set_sub_text(name)

    def _rename_collection(self, name: str) -> None:
        cleaned = name.strip()
        if not cleaned:
            return
        self._collection_name = cleaned
        self._collection_meta_dirty = True
        self._refresh_collection_dirty()

    def _collection_dir(self) -> Path:
        from save_paths import dungeon_collections_dir
        return dungeon_collections_dir()

    def _materialize_state_icons_for_archive(self, state: dict, assets: dict[str, bytes]) -> dict:
        if not isinstance(state, dict):
            return state
        items = state.get("items")
        if not isinstance(items, list):
            return state
        for item_data in items:
            if not isinstance(item_data, dict):
                continue
            if item_data.get("type") != "entity":
                continue
            linked_inventory = item_data.get("linked_inventory")
            if isinstance(linked_inventory, dict):
                normalized_linked_inventory = normalize_inventory_payload(linked_inventory)
                normalized_linked_inventory["item_documents"] = {}
                item_data["linked_inventory"] = normalize_inventory_payload(normalized_linked_inventory)
            icon_ref = str(item_data.get("icon_path") or "")
            if not icon_ref:
                continue
            runtime_path = self._resolve_runtime_icon_path(icon_ref) if icon_ref.startswith(SESSION_ICON_PREFIX) else icon_ref
            icon_file = Path(runtime_path)
            if not icon_file.exists():
                continue
            try:
                raw = icon_file.read_bytes()
            except Exception:
                continue
            if not raw:
                continue
            ext = icon_file.suffix.lower()
            if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
                ext = ".png"
            digest = hashlib.sha256(raw).hexdigest()
            filename = f"{digest}{ext}"
            asset_name = f"assets/icons/{filename}"
            assets.setdefault(asset_name, raw)
            item_data["icon_path"] = asset_name
        return state

    def _sync_collection_icon_assets_dir(self, icon_dir: Path, assets: dict[str, bytes]) -> None:
        expected_assets: dict[str, bytes] = {}
        for asset_name, raw in assets.items():
            if not str(asset_name).startswith("assets/icons/"):
                continue
            icon_name = _sanitize_filename(Path(asset_name).name, "")
            if not icon_name:
                continue
            if not isinstance(raw, bytes) or not raw:
                continue
            expected_assets[icon_name] = raw

        if expected_assets:
            icon_dir.mkdir(parents=True, exist_ok=True)
            for icon_name, raw in expected_assets.items():
                target_path = icon_dir / icon_name
                if target_path.exists():
                    try:
                        if target_path.read_bytes() == raw:
                            continue
                    except Exception:
                        pass
                target_path.write_bytes(raw)

        expected_names = set(expected_assets.keys())
        if icon_dir.exists():
            for stale_path in list(icon_dir.iterdir()):
                if stale_path.is_dir():
                    shutil.rmtree(stale_path, ignore_errors=True)
                    continue
                if stale_path.name in expected_names:
                    continue
                try:
                    stale_path.unlink()
                except Exception:
                    continue
            try:
                if not any(icon_dir.iterdir()):
                    icon_dir.rmdir()
                    parent = icon_dir.parent
                    if parent.exists() and not any(parent.iterdir()):
                        parent.rmdir()
            except Exception:
                return

    def _build_collection_payload(self) -> tuple[dict, dict[str, bytes]]:
        self._save_active_dungeon_state()
        assets: dict[str, bytes] = {}
        dungeons_payload = []
        for dungeon in self._dungeons:
            dungeon_state = dungeon.get("state") or self._blank_dungeon_state()
            state_for_save = json.loads(json.dumps(dungeon_state))
            state_for_save = self._materialize_state_icons_for_archive(state_for_save, assets)
            dungeons_payload.append(
                {
                    "id": dungeon["id"],
                    "name": dungeon["name"],
                    "state": state_for_save,
                }
            )
        payload = {
            "format": COLLECTION_FILE_FORMAT,
            "object_type": "collection",
            "object_id": str(self._collection_id or ""),
            "version": DUNGEON_COLLECTION_VERSION,
            "collection_name": self._collection_name,
            "active_dungeon_id": self._active_dungeon_id,
            "players_dungeon_id": self._players_dungeon_id,
            "autosave_enabled": bool(self._autosave_enabled),
            "local_player_profile_id": str(self._persistent_local_player_id or ""),
            "known_player_profiles": dict(self._known_player_profiles),
            "dungeons": dungeons_payload,
        }
        return payload, assets

    def _save_collection(self) -> bool:
        if self._collection_path is None:
            return self._save_collection_as()
        return self._save_collection_to_path(self._collection_path)

    def _save_collection_as(self) -> bool:
        base_dir = self._collection_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        default_name = _sanitize_filename(self._collection_name, "dungeon_collection") + COLLECTION_FILE_EXTENSION
        default_path = str(base_dir / default_name)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Dungeon Collection",
            default_path,
            f"Dungeon Collection (*{COLLECTION_FILE_EXTENSION})",
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.lower() != COLLECTION_FILE_EXTENSION:
            path = path.with_suffix(COLLECTION_FILE_EXTENSION)
        return self._save_collection_to_path(path)

    def _save_collection_to_path(self, path: Path, *, commit_as_primary: bool = True) -> bool:
        if path.suffix.lower() != COLLECTION_FILE_EXTENSION:
            path = path.with_suffix(COLLECTION_FILE_EXTENSION)
        if self._online_mode != ONLINE_MODE_PLAYER:
            self._cleanup_unlinked_managed_character_artifacts()
        payload, assets = self._build_collection_payload()
        if not str(payload.get("object_id") or "").strip():
            payload["object_id"] = generate_named_object_id(self._collection_name, "collection")
            self._collection_id = str(payload["object_id"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_dmt_package(path, info=payload, assets=assets)
        except Exception as exc:
            if commit_as_primary:
                QMessageBox.critical(self, "Save Failed", str(exc))
            return False
        try:
            self._sync_collection_icon_assets_dir(self._collection_working_icon_dir(path), assets)
        except Exception as exc:
            print(f"[WARN] Failed to synchronize collection icon assets for {path}: {exc}", file=sys.stderr)
        if commit_as_primary:
            self._collection_path = path
            for dungeon in self._dungeons:
                dungeon["dirty"] = False
            self._collection_meta_dirty = False
            self._refresh_collection_dirty()
        return True

    def _load_collection_dialog(self) -> None:
        if not self._confirm_unsaved_before_load():
            return
        base_dir = self._collection_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load Dungeon Collection",
            str(base_dir),
            f"Dungeon Collection (*{COLLECTION_FILE_EXTENSION})",
        )
        if not filename:
            return
        self._load_collection_from_path(Path(filename))

    def _confirm_unsaved_changes(self) -> bool:
        if not self._collection_dirty:
            return True
        if os.environ.get("DMT_TEST_MODE") == "1":
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Unsaved Changes")
        dialog.setText("You have unsaved changes to this dungeon collection.")
        save_button = dialog.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard_button = dialog.addButton(
            "Discard", QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == save_button:
            return self._save_collection()
        if clicked == discard_button:
            return True
        return False

    def _confirm_unsaved_before_load(self) -> bool:
        return self._confirm_unsaved_changes()

    def _load_collection_from_path(self, path: Path) -> bool:
        payload = read_dmt_package_info(path)
        if not isinstance(payload, dict) or str(payload.get("format") or "") != COLLECTION_FILE_FORMAT:
            QMessageBox.critical(self, "Load Failed", "Collection file is invalid.")
            return False
        try:
            icon_assets = list_dmt_package_assets(path)
        except Exception:
            icon_assets = []
        icon_bytes_by_asset: dict[str, bytes] = {}
        for asset_name in icon_assets:
            if not str(asset_name).startswith("assets/icons/"):
                continue
            raw = read_dmt_package_asset(path, asset_name)
            if raw:
                icon_bytes_by_asset[str(asset_name)] = raw
        try:
            icons_dir = self._collection_working_icon_dir(path)
            self._sync_collection_icon_assets_dir(icons_dir, icon_bytes_by_asset)
        except Exception as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))
            return False
        name = payload.get("collection_name") or path.stem
        loaded_object_id = str(payload.get("object_id") or "").strip()
        if loaded_object_id:
            self._collection_id = loaded_object_id
        else:
            self._collection_id = generate_named_object_id(str(name or "collection"), "collection")
        dungeons: list[dict] = []
        for entry in payload.get("dungeons", []):
            dungeon_id = entry.get("id") or uuid.uuid4().hex
            dungeon_name = entry.get("name") or f"Dungeon {len(dungeons) + 1}"
            dungeon_state = entry.get("state") or self._blank_dungeon_state()
            if isinstance(dungeon_state, dict):
                items = dungeon_state.get("items")
                if isinstance(items, list):
                    for item_data in items:
                        if not isinstance(item_data, dict):
                            continue
                        if item_data.get("type") != "entity":
                            continue
                        icon_ref = str(item_data.get("icon_path") or "")
                        if not icon_ref.startswith("assets/icons/"):
                            continue
                        icon_name = Path(icon_ref).name
                        runtime_icon = self._collection_working_icon_dir(path) / icon_name
                        if runtime_icon.exists():
                            item_data["icon_path"] = str(runtime_icon)
            dungeons.append(
                {
                    "id": dungeon_id,
                    "name": dungeon_name,
                    "state": dungeon_state,
                    "preview": None,
                    "preview_signature": None,
                    "dirty": False,
                }
            )
        if not dungeons:
            dungeons.append(self._create_dungeon_entry("Dungeon 1"))
        self._collection_name = name
        self._collection_path = path
        loaded_known_players = payload.get("known_player_profiles")
        if isinstance(loaded_known_players, dict):
            for player_id, player_payload in loaded_known_players.items():
                clean_id = str(player_id or "").strip()
                if not clean_id:
                    continue
                if isinstance(player_payload, dict):
                    self._known_player_profiles[clean_id] = dict(player_payload)
                else:
                    self._known_player_profiles[clean_id] = {
                        "name": str(player_payload or clean_id),
                    }
        self._autosave_enabled = bool(payload.get("autosave_enabled", self._autosave_enabled))
        self.selection_widget.set_autosave_active(self._autosave_enabled)
        self._save_local_profile()
        self._collection_meta_dirty = False
        self._dungeons = dungeons
        active_id = payload.get("active_dungeon_id")
        if not active_id or not any(d["id"] == active_id for d in dungeons):
            active_id = dungeons[0]["id"]
        self._active_dungeon_id = active_id
        self._players_dungeon_id = payload.get("players_dungeon_id")
        self._ensure_player_assignment(preferred_id=self._active_dungeon_id, mark_dirty=False)
        active_dungeon = self._current_dungeon()
        if active_dungeon:
            self._load_dungeon_state(active_dungeon["state"])
        self._refresh_dungeon_list(preserve_selection=True)
        self._refresh_collection_dirty()
        self._preview_timer.start()
        self._update_active_dungeon_label()
        self._cleanup_unlinked_managed_character_artifacts()
        return True

    def open_linked_dungeon(self, collection_path: str, dungeon_id: str) -> bool:
        clean_dungeon_id = str(dungeon_id or "").strip()
        if not clean_dungeon_id:
            return False

        requested_collection = str(collection_path or "").strip()
        if requested_collection:
            target_path = Path(requested_collection).expanduser().resolve()
            if not target_path.exists():
                return False
            current_path = self._collection_path.resolve() if self._collection_path is not None else None
            if current_path is None or current_path != target_path:
                if not self._confirm_unsaved_before_load():
                    return False
                if not self._load_collection_from_path(target_path):
                    return False

        target_dungeon = self._find_dungeon(clean_dungeon_id)
        if target_dungeon is None:
            return False

        if str(self._active_dungeon_id or "") != clean_dungeon_id:
            self._switch_to_dungeon(clean_dungeon_id, save_current=True)

        for index in range(self._dungeon_list.count()):
            item = self._dungeon_list.item(index)
            if item is None:
                continue
            try:
                item_id = item.data(Qt.ItemDataRole.UserRole)
            except RuntimeError:
                continue
            if item_id == clean_dungeon_id:
                self._dungeon_list.setCurrentItem(item)
                break
        self._update_tile_selection(clean_dungeon_id)
        return str(self._active_dungeon_id or "") == clean_dungeon_id

    def _add_dungeon(self) -> None:
        base_name = "Dungeon"
        existing = {d["name"] for d in self._dungeons}
        index = 1
        new_name = f"{base_name} {index}"
        while new_name in existing:
            index += 1
            new_name = f"{base_name} {index}"
        new_dungeon = self._create_dungeon_entry(new_name)
        new_dungeon["dirty"] = True
        self._dungeons.append(new_dungeon)
        self._collection_meta_dirty = True
        self._refresh_collection_dirty()
        self._switch_to_dungeon(new_dungeon["id"])

    def _show_dungeon_context_menu(self, pos) -> None:
        item = self._dungeon_list.itemAt(pos)
        if not item:
            return
        dungeon_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rename_action = menu.addAction("Rename Dungeon")
        delete_action = menu.addAction("Delete Dungeon")
        action = menu.exec(self._dungeon_list.viewport().mapToGlobal(pos))
        if action == rename_action:
            tile_widget = self._dungeon_list.itemWidget(item)
            if isinstance(tile_widget, DungeonTileWidget):
                tile_widget.start_edit()
        elif action == delete_action:
            self._confirm_delete_dungeon(dungeon_id)

    def _prompt_rename_dungeon(self, dungeon_id: str) -> None:
        dungeon = self._find_dungeon(dungeon_id)
        if not dungeon:
            return
        typed, ok = QInputDialog.getText(
            self,
            "Rename Dungeon",
            "Dungeon name:",
            text=dungeon["name"],
        )
        if not ok:
            return
        new_name = typed.strip()
        if not new_name or new_name == dungeon["name"]:
            return
        dungeon["name"] = new_name
        dungeon["dirty"] = True
        self._collection_meta_dirty = True
        self._refresh_collection_dirty()
        self._refresh_dungeon_list(preserve_selection=True)

    def _confirm_delete_dungeon(self, dungeon_id: str) -> None:
        dungeon = self._find_dungeon(dungeon_id)
        if not dungeon:
            return
        if len(self._dungeons) <= 1:
            QMessageBox.information(
                self,
                "Delete Dungeon",
                "A dungeon collection must contain at least one dungeon.",
            )
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Delete Dungeon")
        dialog.setText(f"Delete '{dungeon['name']}' from this collection?")
        dialog.setInformativeText("This removes it from the collection. Saved files stay unchanged until you save.")
        delete_button = dialog.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
        dialog.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() != delete_button:
            return
        deleting_active = dungeon_id == self._active_dungeon_id
        self._dungeons = [d for d in self._dungeons if d["id"] != dungeon_id]
        self._collection_meta_dirty = True
        if deleting_active:
            self._active_dungeon_id = self._dungeons[0]["id"]
            active_dungeon = self._current_dungeon()
            if active_dungeon:
                self._load_dungeon_state(active_dungeon["state"])
            self._update_active_dungeon_label()
        self._ensure_player_assignment(preferred_id=self._active_dungeon_id)
        self._refresh_dungeon_list(preserve_selection=True)
        self._refresh_collection_dirty()
        if self._online_mode != ONLINE_MODE_PLAYER:
            self._cleanup_unlinked_managed_character_artifacts()
