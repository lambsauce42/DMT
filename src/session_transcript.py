from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QPushButton,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from asset_paths import icon_path, icons_dir
try:
    from PySide6.QtSvg import QSvgRenderer

    SVG_AVAILABLE = True
except Exception:
    SVG_AVAILABLE = False

from save_paths import dnd_saves_dir, session_transcript_dir
from user_settings import load_app_settings, save_app_settings


TRANSCRIPT_MANIFEST_FORMAT = "dmt.session_transcript.v1"
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "gpt-oss:20b"
DEFAULT_SOURCE_MODE = "mic"
MANUAL_TRANSCRIPT_ENTRY_TOKENS = 4200
TRANSCRIPT_SETTINGS_KEYS = (
    "recap_ollama_host",
    "recap_ollama_model",
)
SYSTEM_AUDIO_KEYWORDS = (
    "loopback",
    "monitor",
    "stereo mix",
    "what u hear",
    "speakers",
    "output",
)
CAPTURE_CHUNK_MS = 15000
SYSTEM_LOOPBACK_SAMPLE_RATE = 16000
SYSTEM_LOOPBACK_BLOCK_FRAMES = 2048
RECAP_PIPELINE_VERSION = "v8.gist-two-pass-full-transcript"
RECAP_AUTO_GENERATE_MAX_TOKENS = 90000
RECAP_MAX_INPUT_TOKENS = 110000
RECAP_TARGET_INPUT_TOKENS = RECAP_AUTO_GENERATE_MAX_TOKENS
RECAP_INVESTIGATION_WINDOW_TOKENS = 5200
RECAP_SEGMENT_BUNDLE_TOKENS = 6200
RECAP_COVERAGE_BUNDLE_TOKENS = 6200
RECAP_TEXT_SLICE_TOKENS = 380
RECAP_CHECKLIST_LINE_MAX_CHARS = 180
RECAP_MICRO_BLOCK_TOKENS = 520
RECAP_SCENE_TARGET_TOKENS = 1700
RECAP_STAGE_MAX_ATTEMPTS = 3
RECAP_REASONING_BUDGET_TOKENS = 10000
MANAGED_WHISPER_REPO_URL = "https://github.com/ggml-org/whisper.cpp.git"
MANAGED_WHISPER_MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin?download=true"
MANAGED_WHISPER_MODEL_FILE = "ggml-base.en.bin"
MANAGED_WHISPER_MODEL_LABEL = "base.en"
BUTTON_ICON_TINT = QColor("#ffffff")
RECAP_ALLOWED_BLOCK_MODES = (
    "setup",
    "investigation",
    "combat",
    "interrogation",
    "loot",
    "planning",
    "travel",
    "aftermath",
    "other",
)
ICON_DIR = icons_dir()
VENDOR_DIR = dnd_saves_dir() / "vendor"
FIELD_HEIGHT = 34
ACTION_BUTTON_SIZE = 34
ACTION_ICON_SIZE = 16
ACTION_TEXT_BUTTON_HEIGHT = 40
ACTION_ROW_HEIGHT = 54
RECAP_MAX_CHRONOLOGY_ITEMS = 10
RECAP_MAX_FACT_ITEMS = 12
RECAP_MAX_DECISION_ITEMS = 12
RECAP_MAX_TASK_ITEMS = 12
RECAP_MAX_OPEN_THREAD_ITEMS = 12
RECAP_MAX_RULING_ITEMS = 8
RECAP_MAX_FOLLOW_UP_ITEMS = 8
RECAP_MAX_CONTINUITY_ITEMS = 10
TRANSCRIPT_TURN_PATTERN = re.compile(r"(?:(?<=^)|(?<=\n)|(?<=\s))(DM|GM|NPC|[A-Z][A-Za-z0-9'_-]{0,31}):\s*")


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _icon_path(icon_name: str) -> str:
    return str(icon_path(icon_name))


def _is_svg_icon(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"<svg" in handle.read(512).lower()
    except Exception:
        return False


def _load_icon_pixmap(path: Path, size: int) -> tuple[Optional[QPixmap], bool]:
    if not path.exists():
        return None, False
    is_svg = path.suffix.lower() == ".svg" or _is_svg_icon(path)
    if SVG_AVAILABLE and is_svg:
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            return None, False
        image = QImage(size, size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        return QPixmap.fromImage(image), True
    pixmap = QPixmap(str(path))
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


def _tint_pixmap_white(pixmap: QPixmap) -> QPixmap:
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            alpha = QColor.fromRgba(image.pixel(x, y)).alpha()
            if alpha:
                image.setPixelColor(x, y, QColor(BUTTON_ICON_TINT.red(), BUTTON_ICON_TINT.green(), BUTTON_ICON_TINT.blue(), alpha))
    return QPixmap.fromImage(image)


def _button_icon(icon_name: str) -> QIcon:
    icon_path = Path(_icon_path(icon_name))
    pixmap, is_svg = _load_icon_pixmap(icon_path, ACTION_ICON_SIZE)
    if pixmap is not None:
        if is_svg:
            pixmap = _tint_pixmap_white(pixmap)
        return QIcon(pixmap)
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


class _HoverTextPopup(QFrame):
    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip)
        self.setObjectName("HoverTextPopup")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(0)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._label)
        self.setStyleSheet(
            "QFrame#HoverTextPopup {"
            "background: #161b22;"
            "border: 1px solid #30363d;"
            "border-radius: 6px;"
            "}"
            "QFrame#HoverTextPopup QLabel { color: #e6edf3; }"
        )

    def show_for(self, anchor: QWidget, text: str) -> None:
        clean_text = str(text or "").strip()
        if not clean_text:
            self.hide()
            return
        self._label.setText(clean_text)
        self._label.setMaximumWidth(240)
        self.adjustSize()
        screen = anchor.screen() or QApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else anchor.rect()
        origin = anchor.mapToGlobal(QPoint(anchor.width() + 10, anchor.height() // 2))
        x = min(origin.x(), available.right() - self.width() - 8)
        y = origin.y() - (self.height() // 2)
        x = max(available.left() + 8, x)
        y = max(available.top() + 8, min(y, available.bottom() - self.height() - 8))
        self.move(QPoint(x, y))
        self.show()


class _IconToolButton(QToolButton):
    _hover_popup: Optional[_HoverTextPopup] = None

    def __init__(self, parent: QWidget, hover_text: str) -> None:
        super().__init__(parent)
        self._hover_text = str(hover_text or "").strip()
        self.setMouseTracking(True)

    @classmethod
    def _popup(cls) -> _HoverTextPopup:
        if cls._hover_popup is None:
            cls._hover_popup = _HoverTextPopup()
        return cls._hover_popup

    def set_hover_text(self, text: str) -> None:
        self._hover_text = str(text or "").strip()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self._hover_text:
            self._popup().show_for(self, self._hover_text)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._popup().hide()

    def mouseMoveEvent(self, event) -> None:
        super().mouseMoveEvent(event)
        if self.underMouse() and self._hover_text:
            self._popup().show_for(self, self._hover_text)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        if self._popup().isVisible():
            self._popup().hide()


def _make_icon_tool_button(
    parent: QWidget,
    icon_name: str,
    tooltip: str,
    *,
    object_name: str = "SecondaryButton",
    button_size: int = ACTION_BUTTON_SIZE,
) -> QToolButton:
    button = _IconToolButton(parent, tooltip)
    button.setObjectName(object_name)
    button.setProperty("compact", True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setAccessibleName(tooltip)
    button.setToolTip("")
    button.setStatusTip(tooltip)
    button.setToolTipDuration(8000)
    button.setAutoRaise(False)
    button.setFixedSize(button_size, button_size)
    button.setIconSize(QSize(ACTION_ICON_SIZE, ACTION_ICON_SIZE))
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button.setStyleSheet(
        f"padding: 0px; border-radius: 6px; min-width: {button_size}px; max-width: {button_size}px; "
        f"min-height: {button_size}px; max-height: {button_size}px;"
    )
    icon_file = Path(_icon_path(icon_name))
    if icon_file.exists():
        button.setIcon(_button_icon(icon_name))
    else:
        button.setText(tooltip[:1].upper())
    return button


def _make_action_button(
    parent: QWidget,
    icon_name: str,
    label: str,
    tooltip: str,
    *,
    object_name: str = "SecondaryButton",
    minimum_width: int = 112,
) -> QPushButton:
    button = QPushButton(label, parent)
    button.setObjectName(object_name)
    button.setProperty("compact", False)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setAccessibleName(tooltip)
    button.setToolTip("")
    button.setStatusTip(tooltip)
    font = button.font()
    if font.pointSize() <= 0:
        font.setPointSize(11)
    button.setFont(font)
    button.setFixedHeight(ACTION_TEXT_BUTTON_HEIGHT)
    button.setProperty("baseMinimumWidth", int(minimum_width))
    button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    button.setIcon(_button_icon(icon_name))
    button.setIconSize(QSize(ACTION_ICON_SIZE, ACTION_ICON_SIZE))
    button.setProperty(
        "baseStyleSheet",
        (
            f"padding: 0px 12px; "
            f"height: {ACTION_TEXT_BUTTON_HEIGHT}px; "
            f"min-height: {ACTION_TEXT_BUTTON_HEIGHT}px; "
            f"max-height: {ACTION_TEXT_BUTTON_HEIGHT}px; "
            "border-radius: 6px;"
        ),
    )
    button.setStyleSheet(str(button.property("baseStyleSheet") or ""))
    _fit_action_button_width(button, label)
    return button


def _set_icon_tool_button_state(
    button: QToolButton,
    icon_name: str,
    tooltip: str,
    *,
    object_name: Optional[str] = None,
) -> None:
    if object_name:
        button.setObjectName(object_name)
    button.setAccessibleName(tooltip)
    button.setToolTip("")
    button.setStatusTip(tooltip)
    button.setToolTipDuration(8000)
    if isinstance(button, _IconToolButton):
        button.set_hover_text(tooltip)
    icon_file = Path(_icon_path(icon_name))
    if icon_file.exists():
        button.setIcon(_button_icon(icon_name))
        if isinstance(button, QToolButton):
            button.setText("")
    else:
        button.setIcon(QIcon())
        button.setText(tooltip[:1].upper())
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


def _set_action_button_state(
    button: QPushButton,
    icon_name: str,
    label: str,
    tooltip: str,
    *,
    object_name: Optional[str] = None,
) -> None:
    if object_name:
        button.setObjectName(object_name)
    button.setText(label)
    button.setAccessibleName(tooltip)
    button.setStatusTip(tooltip)
    button.setToolTip("")
    button.setIcon(_button_icon(icon_name))
    _fit_action_button_width(button, label)
    button.style().unpolish(button)
    button.style().polish(button)
    button.update()


def _fit_action_button_width(button: QPushButton, label: str) -> None:
    base_width = max(0, int(button.property("baseMinimumWidth") or 0))
    text_width = button.fontMetrics().horizontalAdvance(str(label or "")) + ACTION_ICON_SIZE + 40
    button.setMinimumWidth(max(base_width, text_width))


def _equalize_button_widths(*buttons: QPushButton) -> None:
    valid_buttons = [button for button in buttons if button is not None]
    if not valid_buttons:
        return
    target_width = max(button.sizeHint().width() for button in valid_buttons)
    for button in valid_buttons:
        base_style = str(button.property("baseStyleSheet") or "").strip()
        width_style = f" min-width: {target_width}px; max-width: {target_width}px;"
        button.setStyleSheet(f"{base_style}{width_style}")
        button.setMinimumWidth(target_width)
        button.setMaximumWidth(target_width)

def _make_hint_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setWordWrap(True)
    label.setMinimumWidth(0)
    label.setStyleSheet("color: #8b949e;")
    return label


def _make_section_label(text: str, parent: QWidget) -> QLabel:
    label = QLabel(text, parent)
    label.setObjectName("Subheader")
    label.setMinimumWidth(0)
    return label


def _safe_component(value: str, fallback: str) -> str:
    invalid = set('<>:"/\\|?*')
    cleaned = "".join(ch for ch in str(value or "").strip() if ch not in invalid).strip(" .")
    return cleaned or fallback


def _source_mode_sources(source_mode: str) -> list[str]:
    mode = str(source_mode or DEFAULT_SOURCE_MODE).strip().lower()
    if mode == "system":
        return ["system"]
    if mode == "mixed":
        return ["mic", "system"]
    return ["mic"]


def _display_source_name(source: str) -> str:
    normalized = str(source or "").strip().lower()
    if normalized == "system":
        return "System"
    if normalized == "manual":
        return "Manual"
    return "Mic"


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[WARN] Failed to read {path}: {exc}", file=sys.stderr)
        return ""


def _estimate_text_tokens(text: str) -> int:
    raw_text = str(text or "")
    if not raw_text:
        return 0
    words = len(re.findall(r"\S+", raw_text))
    chars = len(raw_text)
    return max(1, int(max(words * 1.45, chars / 3.05)))


def _normalize_line_item(text: str, *, max_chars: int = RECAP_CHECKLIST_LINE_MAX_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3].rstrip()}..."


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in values:
        value = _normalize_line_item(raw_value)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _split_text_sentences(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    paragraphs = [segment.strip() for segment in re.split(r"\n{2,}", raw) if segment.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]
        if sentences:
            pieces.extend(sentences)
        else:
            pieces.append(paragraph)
    return pieces


def _split_text_by_token_budget(text: str, token_budget: int) -> list[str]:
    clean_text = str(text or "").strip()
    if not clean_text:
        return []
    safe_budget = max(120, int(token_budget))
    pieces = _split_text_sentences(clean_text)
    if not pieces:
        return [clean_text]
    output: list[str] = []
    current_parts: list[str] = []
    current_tokens = 0
    for piece in pieces:
        piece_tokens = _estimate_text_tokens(piece)
        if piece_tokens > safe_budget:
            words = piece.split()
            chunk_words: list[str] = []
            chunk_tokens = 0
            for word in words:
                word_tokens = _estimate_text_tokens(word)
                if chunk_words and chunk_tokens + word_tokens > safe_budget:
                    output.append(" ".join(chunk_words).strip())
                    chunk_words = [word]
                    chunk_tokens = word_tokens
                else:
                    chunk_words.append(word)
                    chunk_tokens += word_tokens
            if chunk_words:
                output.append(" ".join(chunk_words).strip())
            continue
        if current_parts and current_tokens + piece_tokens > safe_budget:
            output.append(" ".join(current_parts).strip())
            current_parts = [piece]
            current_tokens = piece_tokens
            continue
        current_parts.append(piece)
        current_tokens += piece_tokens
    if current_parts:
        output.append(" ".join(current_parts).strip())
    return [segment for segment in output if segment]


def _strip_transcript_prefixes(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    return re.sub(r"^\[[^\]]*\]\s*\[[^\]]*\]\s*", "", cleaned).strip()


def _split_dialogue_turns(text: str) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for raw_block in re.split(r"\n+", str(text or "")):
        block = _strip_transcript_prefixes(raw_block)
        if not block:
            continue
        matches = list(TRANSCRIPT_TURN_PATTERN.finditer(block))
        if not matches:
            turns.append({"speaker": "", "text": re.sub(r"\s+", " ", block).strip()})
            continue
        for index, match in enumerate(matches):
            speaker = str(match.group(1) or "").strip()
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
            utterance = re.sub(r"\s+", " ", block[start:end]).strip()
            if utterance:
                turns.append({"speaker": speaker, "text": utterance})
    return turns


def _ensure_sentence(text: str, *, max_chars: int = 320) -> str:
    cleaned = _normalize_line_item(text, max_chars=max_chars)
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?":
        cleaned = f"{cleaned}."
    return cleaned


def _strip_sentence_ending(text: str) -> str:
    return re.sub(r"[.?!]+$", "", str(text or "").strip()).strip()


def _contains_any_token(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in tokens)


def _is_mechanics_only_text(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9\s]+", "", str(text or "").strip().lower())
    if not normalized:
        return True
    if len(normalized) <= 4 and normalized.isdigit():
        return True
    mechanics_tokens = {
        "roll",
        "roll it",
        "roll attack",
        "stealth",
        "athletics",
        "arcana check",
        "intimidation with advantage",
        "hits",
        "hit",
        "miss",
        "misses",
        "sure",
        "probably",
        "good",
        "noted",
        "coward",
        "correct",
        "nice",
        "okay",
        "quick recap",
        "okay quick recap",
    }
    if normalized in mechanics_tokens:
        return True
    if re.fullmatch(r"(natural\s+)?(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|\d+)(\s+damage)?", normalized):
        return True
    return False


def _is_low_signal_recap_text(text: str) -> bool:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip()).strip()
    if not cleaned:
        return True
    lowered = cleaned.lower()
    banned_tokens = (
        "coverage window",
        "slice range",
        "no concise summary",
        "structured brief",
        "merge round",
        "bundle:",
    )
    if any(token in lowered for token in banned_tokens):
        return True
    if len(cleaned) < 24:
        return True
    return False


def _compose_summary_sentences(candidates: list[str], *, max_sentences: int = 3, max_chars: int = 620) -> str:
    sentences: list[str] = []
    total_chars = 0
    for candidate in candidates:
        sentence = _ensure_sentence(candidate, max_chars=max_chars)
        if not sentence or _is_low_signal_recap_text(sentence):
            continue
        sentence_key = sentence.casefold()
        if any(existing.casefold() == sentence_key for existing in sentences):
            continue
        projected_chars = total_chars + len(sentence) + (1 if sentences else 0)
        if sentences and projected_chars > max_chars:
            break
        sentences.append(sentence)
        total_chars = projected_chars
        if len(sentences) >= max_sentences:
            break
    return " ".join(sentences).strip()


def _normalize_model_output(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _parse_choice_response(text: str, allowed: tuple[str, ...]) -> tuple[bool, str, str]:
    cleaned = _normalize_model_output(text).lower()
    allowed_set = {value.strip().lower() for value in allowed}
    if cleaned in allowed_set:
        return True, cleaned, ""
    return False, "", f"Expected exactly one of {', '.join(allowed)} but received {cleaned!r}."


def _parse_flag_lines_response(
    text: str,
    required_keys: dict[str, tuple[str, ...]],
) -> tuple[bool, dict[str, str], str]:
    cleaned = _normalize_model_output(text)
    if not cleaned:
        return False, {}, "Response was empty."
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) != len(required_keys):
        return False, {}, f"Expected exactly {len(required_keys)} non-empty lines but received {len(lines)}."
    parsed: dict[str, str] = {}
    expected_order = list(required_keys.keys())
    for index, expected_key in enumerate(expected_order):
        line = lines[index]
        prefix = f"{expected_key}:"
        if not line.startswith(prefix):
            return False, {}, f"Line {index + 1} must start with {prefix!r} but received {line!r}."
        value = line[len(prefix) :].strip().lower()
        allowed_values = {choice.strip().lower() for choice in required_keys[expected_key]}
        if value not in allowed_values:
            return False, {}, f"Line {index + 1} for {expected_key} must be one of {required_keys[expected_key]} but received {value!r}."
        parsed[expected_key] = value
    return True, parsed, ""


def _parse_prefixed_lines_response(
    text: str,
    *,
    prefix: str,
    max_items: int,
    allow_none: bool = True,
) -> tuple[bool, list[str], str]:
    cleaned = _normalize_model_output(text)
    if not cleaned:
        return False, [], "Response was empty."
    if allow_none and cleaned.lower() == "none":
        return True, [], ""
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return False, [], "Response did not contain any non-empty lines."
    parsed: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith(prefix):
            return False, [], f"Line {index + 1} must start with {prefix!r} but received {line!r}."
        value = _normalize_line_item(line[len(prefix) :].strip(), max_chars=320)
        if not value or value.lower() == "none":
            continue
        parsed.append(value)
    if not parsed and not allow_none:
        return False, [], f"Response did not contain any usable {prefix!r} lines."
    if len(parsed) > max_items:
        return False, [], f"Response exceeded the maximum of {max_items} {prefix!r} lines."
    return True, _dedupe_preserve_order(parsed)[:max_items], ""


def _parse_single_prefixed_line_response(
    text: str,
    *,
    prefix: str,
    allow_none: bool = False,
) -> tuple[bool, str, str]:
    ok, values, error_message = _parse_prefixed_lines_response(
        text,
        prefix=prefix,
        max_items=1,
        allow_none=allow_none,
    )
    if not ok:
        return False, "", error_message
    if not values:
        return True, "", ""
    return True, values[0], ""


def _parse_paragraph_lines_response(text: str) -> tuple[bool, list[str], str]:
    cleaned = _normalize_model_output(text)
    if not cleaned:
        return False, [], "Response was empty."
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if len(lines) < 2 or len(lines) > 3:
        return False, [], f"Expected 2 or 3 paragraph lines but received {len(lines)}."
    paragraphs: list[str] = []
    expected_prefixes = ("P1:", "P2:", "P3:")
    for index, line in enumerate(lines):
        prefix = expected_prefixes[index]
        if not line.startswith(prefix):
            return False, [], f"Line {index + 1} must start with {prefix!r} but received {line!r}."
        body = _normalize_line_item(line[len(prefix) :].strip(), max_chars=900)
        if not body:
            return False, [], f"Line {index + 1} was empty after {prefix!r}."
        if body.startswith("-") or "## " in body or "slice range" in body.lower():
            return False, [], f"Line {index + 1} contained forbidden formatting or metadata."
        paragraphs.append(body)
    return True, paragraphs, ""


def _parse_plain_recap_response(
    text: str,
    *,
    min_chars: int = 140,
    max_paragraphs: int = 4,
    max_sentences: int = 15,
) -> tuple[bool, str, str]:
    cleaned = _normalize_model_output(text)
    if not cleaned:
        return False, "", "Response was empty."
    lines = [line.rstrip() for line in cleaned.splitlines()]
    if any(line.lstrip().startswith(("P1:", "P2:", "P3:", "-", "*", "#")) for line in lines if line.strip()):
        return False, "", "Response must be plain prose without headings, bullets, or prefixed paragraph labels."
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n{2,}", cleaned)
        if paragraph.strip()
    ]
    if not paragraphs:
        return False, "", "Response did not contain any usable prose paragraphs."
    if len(paragraphs) > max_paragraphs:
        return False, "", f"Response contained {len(paragraphs)} paragraphs but the maximum is {max_paragraphs}."
    normalized_paragraphs: list[str] = []
    seen: set[str] = set()
    forbidden_tokens = ("coverage window", "slice range", "merge round", "prompt", "metadata")
    for paragraph in paragraphs:
        if any(token in paragraph.lower() for token in forbidden_tokens):
            return False, "", "Response contained recap metadata instead of session prose."
        sentence = paragraph.strip()
        if len(sentence) < 40:
            return False, "", "Response paragraph was too short to be useful."
        key = sentence.casefold()
        if key in seen:
            return False, "", "Response repeated the same paragraph."
        seen.add(key)
        normalized_paragraphs.append(sentence)
    normalized = "\n\n".join(normalized_paragraphs).strip()
    if len(normalized) < min_chars:
        return False, "", "Response was too short to qualify as a session recap."
    sentence_count = len(re.findall(r"[.!?]+(?:\s|$)", normalized))
    if sentence_count <= 0:
        sentence_count = 1
    if sentence_count > max_sentences:
        return False, "", f"Response contained {sentence_count} sentences but the maximum is {max_sentences}."
    return True, normalized, ""


def _parse_plain_audit_notes_response(text: str) -> tuple[bool, str, str]:
    cleaned = _normalize_model_output(text)
    if not cleaned:
        return False, "", "Response was empty."
    lines = [line.rstrip() for line in cleaned.splitlines()]
    if any(line.lstrip().startswith(("-", "*", "#", "STATUS:", "MISSING:")) for line in lines if line.strip()):
        return False, "", "Response must be plain prose without bullets, headings, or status prefixes."
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n{2,}", cleaned)
        if paragraph.strip()
    ]
    if not paragraphs:
        return False, "", "Response did not contain any usable audit notes."
    if len(paragraphs) > 2:
        return False, "", f"Response contained {len(paragraphs)} paragraphs but the maximum is 2."
    normalized = "\n\n".join(paragraphs).strip()
    if len(normalized) < 20:
        return False, "", "Response was too short to be a useful audit note."
    return True, normalized, ""


def _new_recap_stream_snapshot() -> dict[str, object]:
    return {
        "running": False,
        "host": "",
        "model": "",
        "stage_name": "",
        "message": "",
        "thinking_log": "",
        "response_log": "",
    }


def _parse_status_missing_response(text: str) -> tuple[bool, dict[str, object], str]:
    cleaned = _normalize_model_output(text)
    if not cleaned:
        return False, {}, "Response was empty."
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return False, {}, "Response did not contain any non-empty lines."
    first = lines[0]
    if not first.startswith("STATUS:"):
        return False, {}, f"First line must start with 'STATUS:' but received {first!r}."
    status = first[len("STATUS:") :].strip().lower()
    if status not in {"pass", "fail"}:
        return False, {}, f"STATUS must be 'pass' or 'fail' but received {status!r}."
    missing: list[str] = []
    for index, line in enumerate(lines[1:], start=2):
        if not line.startswith("MISSING:"):
            return False, {}, f"Line {index} must start with 'MISSING:' but received {line!r}."
        value = _normalize_line_item(line[len("MISSING:") :].strip(), max_chars=320)
        if value:
            missing.append(value)
    if status == "pass" and missing:
        return False, {}, "Audit returned STATUS: pass with MISSING lines."
    if status == "fail" and not missing:
        return False, {}, "Audit returned STATUS: fail without any MISSING lines."
    return True, {"status": status, "missing": _dedupe_preserve_order(missing)[:6]}, ""


def load_transcript_runtime_settings() -> dict[str, str]:
    settings = load_app_settings()
    return {
        "whisper_cli_path": str(_managed_whisper_cli_path()),
        "whisper_model_path": str(_managed_whisper_model_path()),
        "ollama_host": str(settings.get("recap_ollama_host") or DEFAULT_OLLAMA_HOST).strip()
        or DEFAULT_OLLAMA_HOST,
        "ollama_model": str(settings.get("recap_ollama_model") or DEFAULT_OLLAMA_MODEL).strip()
        or DEFAULT_OLLAMA_MODEL,
    }


def save_transcript_runtime_settings(
    whisper_cli_path: str,
    whisper_model_path: str,
    ollama_host: str,
    ollama_model: str,
) -> dict[str, str]:
    normalized = {
        "recap_ollama_host": str(ollama_host or DEFAULT_OLLAMA_HOST).strip() or DEFAULT_OLLAMA_HOST,
        "recap_ollama_model": str(ollama_model or DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL,
    }
    save_app_settings(normalized)
    return load_transcript_runtime_settings()


def _managed_whisper_root() -> Path:
    return VENDOR_DIR / "whisper.cpp"


def _managed_whisper_source_dir() -> Path:
    return _managed_whisper_root() / "source"


def _managed_whisper_build_dir() -> Path:
    return _managed_whisper_root() / "build"


def _managed_whisper_models_dir() -> Path:
    return _managed_whisper_root() / "models"


def _managed_whisper_model_path() -> Path:
    return _managed_whisper_models_dir() / MANAGED_WHISPER_MODEL_FILE


def _managed_whisper_cli_candidates() -> list[Path]:
    build_dir = _managed_whisper_build_dir()
    return [
        build_dir / "bin" / "whisper-cli.exe",
        build_dir / "bin" / "Release" / "whisper-cli.exe",
        build_dir / "bin" / "whisper-cli",
        build_dir / "bin" / "Release" / "whisper-cli",
    ]


def _managed_whisper_cli_path() -> Path:
    for candidate in _managed_whisper_cli_candidates():
        if candidate.exists():
            return candidate
    return _managed_whisper_build_dir() / "bin" / "whisper-cli.exe"


def _run_managed_whisper_command(command: list[str], *, cwd: Optional[Path] = None, label: str) -> None:
    print(f"[INFO] {label}: {' '.join(command)}", file=sys.stderr)
    result = subprocess.run(
        command,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return
    stdout = str(result.stdout or "").strip()
    stderr = str(result.stderr or "").strip()
    raise RuntimeError(stderr or stdout or f"{label} failed with exit code {result.returncode}.")


def ensure_managed_whisper_runtime() -> tuple[Path, Path]:
    root = _managed_whisper_root()
    source_dir = _managed_whisper_source_dir()
    build_dir = _managed_whisper_build_dir()
    model_path = _managed_whisper_model_path()
    root.mkdir(parents=True, exist_ok=True)
    if not source_dir.exists():
        _run_managed_whisper_command(
            ["git", "clone", "--depth", "1", MANAGED_WHISPER_REPO_URL, str(source_dir)],
            label="Cloning whisper.cpp",
        )
    if not model_path.exists():
        _managed_whisper_models_dir().mkdir(parents=True, exist_ok=True)
        print(f"[INFO] Downloading Whisper model {MANAGED_WHISPER_MODEL_LABEL} to {model_path}", file=sys.stderr)
        with urllib_request.urlopen(MANAGED_WHISPER_MODEL_URL, timeout=600) as response:
            model_path.write_bytes(response.read())
    cli_path = next((candidate for candidate in _managed_whisper_cli_candidates() if candidate.exists()), None)
    if cli_path is None:
        build_dir.mkdir(parents=True, exist_ok=True)
        _run_managed_whisper_command(
            [
                "cmake",
                "-S",
                str(source_dir),
                "-B",
                str(build_dir),
                "-G",
                "Ninja",
                "-DCMAKE_BUILD_TYPE=Release",
                "-DWHISPER_BUILD_TESTS=OFF",
            ],
            label="Configuring whisper.cpp",
        )
        _run_managed_whisper_command(
            ["cmake", "--build", str(build_dir), "--config", "Release", "--target", "whisper-cli", "-j", "4"],
            label="Building whisper.cpp",
        )
        cli_path = next((candidate for candidate in _managed_whisper_cli_candidates() if candidate.exists()), None)
    if cli_path is None:
        raise RuntimeError("Managed whisper.cpp build completed without producing whisper-cli.")
    return cli_path, model_path


class SessionTranscriptStore:
    def __init__(self, session_id: str) -> None:
        self.session_id = _safe_component(str(session_id or ""), "session")
        self.root = session_transcript_dir(self.session_id)
        self.audio_dir = self.root / "audio"
        self.transcript_dir = self.root / "transcript"
        self.recap_dir = self.root / "recap"
        self.recap_checkpoint_dir = self.recap_dir / "checkpoints"
        self.recap_investigation_dir = self.recap_dir / "investigations"
        self.recap_dossier_dir = self.recap_dir / "dossiers"
        self.recap_merge_dir = self.recap_dir / "merge_rounds"
        self.recap_coverage_dir = self.recap_dir / "coverage"
        self.recap_debug_dir = self.recap_dir / "debug"
        self.manifest_path = self.root / "manifest.json"
        self.full_transcript_path = self.transcript_dir / "full_transcript.txt"
        self.manual_transcript_path = self.transcript_dir / "manual_transcript.txt"
        self.final_recap_path = self.recap_dir / "final_recap.md"
        self._lock = threading.RLock()
        self._ensure_dirs()
        self._manifest = self._load_manifest()

    def _ensure_dirs(self) -> None:
        for path in (
            self.root,
            self.audio_dir,
            self.transcript_dir,
            self.recap_dir,
            self.recap_checkpoint_dir,
            self.recap_investigation_dir,
            self.recap_dossier_dir,
            self.recap_merge_dir,
            self.recap_coverage_dir,
            self.recap_debug_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _default_manifest(self) -> dict:
        now = _now_timestamp()
        runtime = load_transcript_runtime_settings()
        return {
            "format": TRANSCRIPT_MANIFEST_FORMAT,
            "session_id": self.session_id,
            "state": "idle",
            "created_at": now,
            "updated_at": now,
            "source_mode": DEFAULT_SOURCE_MODE,
            "capture_devices": {
                "mic_id": "",
                "mic_name": "",
                "system_id": "",
                "system_name": "",
            },
            "runtime": {
                "whisper_cli_path": runtime["whisper_cli_path"],
                "whisper_model_path": runtime["whisper_model_path"],
                "ollama_host": runtime["ollama_host"],
                "ollama_model": runtime["ollama_model"],
            },
            "next_chunk_sequence": 1,
            "chunks": [],
            "manual_transcript": {
                "enabled": False,
                "path": "",
                "updated_at": "",
                "estimated_tokens": 0,
            },
            "recap": {
                "status": "idle",
                "last_error": "",
                "checkpoint_count": 0,
                "processed_chunk_count": 0,
                "final_path": "",
                "updated_at": "",
                "model": "",
                "strategy": RECAP_PIPELINE_VERSION,
                "input_budget_tokens": RECAP_TARGET_INPUT_TOKENS,
                "prompt_eval_max": 0,
                "merge_rounds": 0,
                "investigation_windows": 0,
            },
            "events": [],
        }

    def _load_manifest(self) -> dict:
        if not self.manifest_path.exists():
            manifest = self._default_manifest()
            self._save_locked(manifest)
            return manifest
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] Failed to load transcript manifest {self.manifest_path}: {exc}", file=sys.stderr)
            manifest = self._default_manifest()
            manifest["events"].append(
                {"at": _now_timestamp(), "level": "error", "message": f"Recovered from invalid manifest: {exc}"}
            )
            self._save_locked(manifest)
            return manifest
        if not isinstance(manifest, dict) or manifest.get("format") != TRANSCRIPT_MANIFEST_FORMAT:
            print(
                f"[WARN] Transcript manifest {self.manifest_path} had an unexpected format. Resetting.",
                file=sys.stderr,
            )
            manifest = self._default_manifest()
            manifest["events"].append(
                {"at": _now_timestamp(), "level": "error", "message": "Recovered from unsupported manifest format."}
            )
            self._save_locked(manifest)
        return manifest

    def _save_locked(self, manifest: Optional[dict] = None) -> None:
        active = manifest if manifest is not None else self._manifest
        active["updated_at"] = _now_timestamp()
        tmp_path = self.manifest_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(active, indent=2), encoding="utf-8")
        tmp_path.replace(self.manifest_path)

    def _manual_transcript_meta_locked(self) -> dict:
        return self._manifest.setdefault(
            "manual_transcript",
            {
                "enabled": False,
                "path": "",
                "updated_at": "",
                "estimated_tokens": 0,
            },
        )

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._manifest)

    def set_state(self, state: str, message: str = "") -> None:
        with self._lock:
            self._manifest["state"] = str(state or "idle")
            if message:
                self._append_event_locked("info", message)
            self._save_locked()

    def append_event(self, level: str, message: str) -> None:
        with self._lock:
            self._append_event_locked(level, message)
            self._save_locked()

    def _append_event_locked(self, level: str, message: str) -> None:
        events = self._manifest.setdefault("events", [])
        events.append(
            {
                "at": _now_timestamp(),
                "level": str(level or "info").strip().lower() or "info",
                "message": str(message or "").strip(),
            }
        )
        if len(events) > 200:
            del events[:-200]

    def update_runtime_settings(
        self,
        whisper_cli_path: str,
        whisper_model_path: str,
        ollama_host: str,
        ollama_model: str,
    ) -> None:
        with self._lock:
            runtime = self._manifest.setdefault("runtime", {})
            runtime["whisper_cli_path"] = str(whisper_cli_path or "").strip()
            runtime["whisper_model_path"] = str(whisper_model_path or "").strip()
            runtime["ollama_host"] = str(ollama_host or DEFAULT_OLLAMA_HOST).strip() or DEFAULT_OLLAMA_HOST
            runtime["ollama_model"] = str(ollama_model or DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
            self._save_locked()

    def update_capture_preferences(
        self,
        source_mode: str,
        mic_id: str,
        mic_name: str,
        system_id: str,
        system_name: str,
    ) -> None:
        with self._lock:
            self._manifest["source_mode"] = str(source_mode or DEFAULT_SOURCE_MODE).strip().lower() or DEFAULT_SOURCE_MODE
            devices = self._manifest.setdefault("capture_devices", {})
            devices["mic_id"] = str(mic_id or "").strip()
            devices["mic_name"] = str(mic_name or "").strip()
            devices["system_id"] = str(system_id or "").strip()
            devices["system_name"] = str(system_name or "").strip()
            self._save_locked()

    def begin_live_chunk(
        self,
        source: str,
        *,
        device_id: str,
        device_name: str,
        file_suffix: str = ".wav",
    ) -> dict:
        with self._lock:
            chunk = self._create_chunk_locked(
                source=source,
                capture_kind="live",
                device_id=device_id,
                device_name=device_name,
                file_suffix=file_suffix,
            )
            chunk["capture_state"] = "capturing"
            self._append_event_locked("info", f"Started {_display_source_name(source)} capture chunk {chunk['chunk_id']}.")
            self._save_locked()
            return copy.deepcopy(chunk)

    def add_imported_audio(self, source: str, source_path: str) -> dict:
        file_path = Path(source_path)
        if not file_path.exists():
            raise FileNotFoundError(source_path)
        file_suffix = file_path.suffix or ".wav"
        with self._lock:
            chunk = self._create_chunk_locked(
                source=source,
                capture_kind="imported",
                device_id="",
                device_name=file_path.name,
                file_suffix=file_suffix,
            )
            destination = self.root / chunk["audio_path"]
            shutil.copyfile(file_path, destination)
            chunk["capture_state"] = "captured"
            chunk["ended_at"] = _now_timestamp()
            chunk["size_bytes"] = destination.stat().st_size
            self._append_event_locked(
                "info",
                f"Imported audio into {_display_source_name(source)} chunk {chunk['chunk_id']}.",
            )
            self._save_locked()
            return copy.deepcopy(chunk)

    def _create_chunk_locked(
        self,
        *,
        source: str,
        capture_kind: str,
        device_id: str,
        device_name: str,
        file_suffix: str,
    ) -> dict:
        sequence = max(1, int(self._manifest.get("next_chunk_sequence") or 1))
        self._manifest["next_chunk_sequence"] = sequence + 1
        clean_source = str(source or "mic").strip().lower() or "mic"
        clean_suffix = str(file_suffix or ".wav").strip() or ".wav"
        if not clean_suffix.startswith("."):
            clean_suffix = f".{clean_suffix}"
        chunk_id = f"{sequence:06d}_{clean_source}"
        chunk = {
            "chunk_id": chunk_id,
            "sequence": sequence,
            "source": clean_source,
            "capture_kind": capture_kind,
            "capture_state": "pending",
            "transcript_state": "pending",
            "audio_path": str(Path("audio") / f"{chunk_id}{clean_suffix}").replace("\\", "/"),
            "transcript_path": "",
            "started_at": _now_timestamp(),
            "ended_at": "",
            "device_id": str(device_id or "").strip(),
            "device_name": str(device_name or "").strip(),
            "size_bytes": 0,
            "last_error": "",
            "text_preview": "",
        }
        self._manifest.setdefault("chunks", []).append(chunk)
        return chunk

    def finalize_live_chunk(self, chunk_id: str, size_bytes: int) -> None:
        with self._lock:
            chunk = self._chunk_locked(chunk_id)
            if chunk is None:
                return
            if max(0, int(size_bytes)) <= 0:
                self._drop_chunk_locked(chunk_id)
                self._append_event_locked("warn", f"Dropped empty chunk {chunk_id}.")
                self._save_locked()
                return
            chunk["capture_state"] = "captured"
            chunk["ended_at"] = _now_timestamp()
            chunk["size_bytes"] = max(0, int(size_bytes))
            self._append_event_locked("info", f"Committed capture chunk {chunk_id}.")
            self._save_locked()

    def mark_chunk_capture_failed(self, chunk_id: str, error_message: str) -> None:
        with self._lock:
            chunk = self._chunk_locked(chunk_id)
            if chunk is None:
                return
            chunk["capture_state"] = "failed"
            chunk["last_error"] = str(error_message or "").strip()
            self._append_event_locked("error", f"Capture failed for {chunk_id}: {chunk['last_error']}")
            self._save_locked()

    def requeue_failed_chunks(self) -> int:
        count = 0
        with self._lock:
            for chunk in self._manifest.get("chunks", []):
                if chunk.get("transcript_state") != "failed":
                    continue
                chunk["transcript_state"] = "pending"
                chunk["last_error"] = ""
                count += 1
            if count:
                self._append_event_locked("info", f"Re-queued {count} failed transcript chunk(s).")
                self._save_locked()
        return count

    def _drop_chunk_locked(self, chunk_id: str) -> None:
        chunks = self._manifest.get("chunks", [])
        for index, chunk in enumerate(list(chunks)):
            if chunk.get("chunk_id") != chunk_id:
                continue
            audio_rel = Path(str(chunk.get("audio_path") or ""))
            transcript_rel = Path(str(chunk.get("transcript_path") or ""))
            try:
                if audio_rel:
                    audio_path = self.root / audio_rel
                    if audio_path.exists():
                        audio_path.unlink()
            except Exception as exc:
                print(f"[WARN] Failed to remove dropped audio chunk {chunk_id}: {exc}", file=sys.stderr)
            try:
                if transcript_rel:
                    transcript_path = self.root / transcript_rel
                    if transcript_path.exists():
                        transcript_path.unlink()
            except Exception as exc:
                print(f"[WARN] Failed to remove dropped transcript {chunk_id}: {exc}", file=sys.stderr)
            del chunks[index]
            break

    def _chunk_locked(self, chunk_id: str) -> Optional[dict]:
        clean_chunk_id = str(chunk_id or "").strip()
        if not clean_chunk_id:
            return None
        for chunk in self._manifest.get("chunks", []):
            if chunk.get("chunk_id") == clean_chunk_id:
                return chunk
        return None

    def chunk_audio_path(self, chunk: dict) -> Path:
        return self.root / Path(str(chunk.get("audio_path") or ""))

    def claim_next_transcript_chunk(self) -> Optional[dict]:
        with self._lock:
            for chunk in sorted(self._manifest.get("chunks", []), key=lambda entry: int(entry.get("sequence") or 0)):
                if chunk.get("capture_state") != "captured":
                    continue
                if chunk.get("transcript_state") != "pending":
                    continue
                chunk["transcript_state"] = "running"
                chunk["last_error"] = ""
                self._append_event_locked("info", f"Transcribing chunk {chunk['chunk_id']}.")
                self._save_locked()
                return copy.deepcopy(chunk)
        return None

    def mark_chunk_transcribed(self, chunk_id: str, text: str) -> None:
        clean_text = str(text or "").strip()
        with self._lock:
            chunk = self._chunk_locked(chunk_id)
            if chunk is None:
                return
            transcript_rel = Path("transcript") / f"{chunk_id}.json"
            transcript_path = self.root / transcript_rel
            payload = {
                "chunk_id": chunk_id,
                "source": chunk.get("source", "mic"),
                "started_at": chunk.get("started_at", ""),
                "ended_at": chunk.get("ended_at", ""),
                "text": clean_text,
                "transcribed_at": _now_timestamp(),
            }
            transcript_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            chunk["transcript_state"] = "completed"
            chunk["transcript_path"] = str(transcript_rel).replace("\\", "/")
            chunk["text_preview"] = clean_text[:240]
            chunk["last_error"] = ""
            self._append_event_locked("info", f"Finished transcription for {chunk_id}.")
            self._write_full_transcript_locked()
            self._invalidate_recap_locked("Transcript changed. Regenerate the recap.")
            self._save_locked()

    def mark_chunk_transcript_failed(self, chunk_id: str, error_message: str) -> None:
        with self._lock:
            chunk = self._chunk_locked(chunk_id)
            if chunk is None:
                return
            chunk["transcript_state"] = "failed"
            chunk["last_error"] = str(error_message or "").strip()
            self._append_event_locked("error", f"Transcription failed for {chunk_id}: {chunk['last_error']}")
            self._save_locked()

    def _load_transcript_entry_locked(self, chunk: dict) -> Optional[dict]:
        transcript_rel = str(chunk.get("transcript_path") or "").strip()
        if not transcript_rel:
            return None
        path = self.root / transcript_rel
        if not path.exists():
            print(f"[WARN] Missing transcript file for chunk {chunk.get('chunk_id')}: {path}", file=sys.stderr)
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[WARN] Failed to load transcript chunk {path}: {exc}", file=sys.stderr)
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _generated_transcript_entries_locked(self) -> list[dict]:
        entries: list[dict] = []
        for chunk in sorted(self._manifest.get("chunks", []), key=lambda entry: int(entry.get("sequence") or 0)):
            if chunk.get("transcript_state") != "completed":
                continue
            payload = self._load_transcript_entry_locked(chunk)
            if payload is None:
                continue
            payload["sequence"] = int(chunk.get("sequence") or 0)
            entries.append(payload)
        return entries

    def transcript_entries(self) -> list[dict]:
        with self._lock:
            manual_entries = self._manual_transcript_entries_locked()
            if manual_entries:
                return manual_entries
            return self._generated_transcript_entries_locked()

    def _manual_transcript_entries_locked(self) -> list[dict]:
        meta = self._manual_transcript_meta_locked()
        if not bool(meta.get("enabled")):
            return []
        text = _read_text_if_exists(self.manual_transcript_path).strip()
        if not text:
            return []
        updated_at = str(meta.get("updated_at") or "")
        segments = _split_text_by_token_budget(text, MANUAL_TRANSCRIPT_ENTRY_TOKENS)
        entries: list[dict] = []
        for index, segment in enumerate(segments, start=1):
            entries.append(
                {
                    "chunk_id": f"manual_{index:04d}",
                    "source": "manual",
                    "started_at": updated_at,
                    "ended_at": updated_at,
                    "text": segment,
                    "transcribed_at": updated_at,
                    "sequence": index,
                    "manual": True,
                }
            )
        return entries

    def _write_full_transcript_locked(self) -> None:
        lines: list[str] = []
        for entry in self._generated_transcript_entries_locked():
            source = _display_source_name(str(entry.get("source") or "mic"))
            started_at = str(entry.get("started_at") or "")
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            prefix = f"[{started_at}] [{source}]".strip()
            lines.append(f"{prefix} {text}".strip())
        self.full_transcript_path.write_text("\n\n".join(lines), encoding="utf-8")

    def transcript_text(self) -> str:
        with self._lock:
            manual_meta = self._manual_transcript_meta_locked()
            if bool(manual_meta.get("enabled")) and self.manual_transcript_path.exists():
                return _read_text_if_exists(self.manual_transcript_path)
            if self.full_transcript_path.exists():
                return _read_text_if_exists(self.full_transcript_path)
            self._write_full_transcript_locked()
            return _read_text_if_exists(self.full_transcript_path)

    def generated_transcript_text(self) -> str:
        with self._lock:
            self._write_full_transcript_locked()
            return _read_text_if_exists(self.full_transcript_path)

    def save_manual_transcript(self, text: str) -> None:
        clean_text = str(text or "").strip()
        with self._lock:
            if not clean_text:
                self._clear_manual_transcript_locked(message="Cleared manual transcript override.")
                self._save_locked()
                return
            meta = self._manual_transcript_meta_locked()
            self.manual_transcript_path.write_text(clean_text, encoding="utf-8")
            meta["enabled"] = True
            meta["path"] = str(Path("transcript") / self.manual_transcript_path.name).replace("\\", "/")
            meta["updated_at"] = _now_timestamp()
            meta["estimated_tokens"] = _estimate_text_tokens(clean_text)
            self._append_event_locked("info", "Saved manual transcript text.")
            self._invalidate_recap_locked("Transcript changed. Regenerate the recap.")
            self._save_locked()

    def clear_manual_transcript(self) -> None:
        with self._lock:
            self._clear_manual_transcript_locked(message="Reverted to generated transcript text.")
            self._save_locked()

    def _clear_manual_transcript_locked(self, *, message: str) -> None:
        meta = self._manual_transcript_meta_locked()
        try:
            if self.manual_transcript_path.exists():
                self.manual_transcript_path.unlink()
        except Exception as exc:
            print(f"[WARN] Failed to remove manual transcript {self.manual_transcript_path}: {exc}", file=sys.stderr)
        meta["enabled"] = False
        meta["path"] = ""
        meta["updated_at"] = _now_timestamp()
        meta["estimated_tokens"] = 0
        self._append_event_locked("info", message)
        self._invalidate_recap_locked("Transcript changed. Regenerate the recap.")

    def _invalidate_recap_locked(self, message: str) -> None:
        recap = self._manifest.setdefault("recap", {})
        had_recap = bool(recap.get("final_path")) or int(recap.get("checkpoint_count") or 0) > 0
        recap["status"] = "idle"
        recap["last_error"] = ""
        recap["checkpoint_count"] = 0
        recap["processed_chunk_count"] = 0
        recap["final_path"] = ""
        recap["updated_at"] = _now_timestamp()
        recap["prompt_eval_max"] = 0
        recap["merge_rounds"] = 0
        recap["investigation_windows"] = 0
        try:
            if self.final_recap_path.exists():
                self.final_recap_path.unlink()
        except Exception as exc:
            print(f"[WARN] Failed to remove stale recap {self.final_recap_path}: {exc}", file=sys.stderr)
        if had_recap:
            self._append_event_locked("info", message)

    def clear_recap_error(self) -> None:
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            recap["last_error"] = ""
            if recap.get("status") == "failed":
                recap["status"] = "idle"
            self._save_locked()

    def mark_recap_running(self, model: str) -> None:
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            recap["status"] = "running"
            recap["last_error"] = ""
            recap["model"] = str(model or "").strip()
            recap["strategy"] = RECAP_PIPELINE_VERSION
            recap["input_budget_tokens"] = RECAP_TARGET_INPUT_TOKENS
            recap["updated_at"] = _now_timestamp()
            self._append_event_locked("info", "Recap generation started.")
            self._save_locked()

    def save_recap_checkpoint(self, summary: str, processed_chunk_count: int, model: str) -> None:
        clean_summary = str(summary or "").strip()
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            checkpoint_count = int(recap.get("checkpoint_count") or 0) + 1
            checkpoint_path = self.recap_checkpoint_dir / f"checkpoint_{checkpoint_count:04d}.json"
            checkpoint_payload = {
                "checkpoint_index": checkpoint_count,
                "processed_chunk_count": max(0, int(processed_chunk_count)),
                "summary": clean_summary,
                "created_at": _now_timestamp(),
                "model": str(model or "").strip(),
            }
            checkpoint_path.write_text(json.dumps(checkpoint_payload, indent=2), encoding="utf-8")
            recap["checkpoint_count"] = checkpoint_count
            recap["processed_chunk_count"] = max(0, int(processed_chunk_count))
            recap["model"] = str(model or "").strip()
            recap["status"] = "running"
            recap["strategy"] = RECAP_PIPELINE_VERSION
            recap["updated_at"] = _now_timestamp()
            self._append_event_locked("info", f"Saved recap checkpoint {checkpoint_count}.")
            self._save_locked()

    def load_latest_recap_checkpoint(self) -> str:
        with self._lock:
            checkpoint_count = int(self._manifest.get("recap", {}).get("checkpoint_count") or 0)
            if checkpoint_count <= 0:
                return ""
            checkpoint_path = self.recap_checkpoint_dir / f"checkpoint_{checkpoint_count:04d}.json"
            if not checkpoint_path.exists():
                return ""
            try:
                payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"[WARN] Failed to read recap checkpoint {checkpoint_path}: {exc}", file=sys.stderr)
                return ""
            if not isinstance(payload, dict):
                return ""
            return str(payload.get("summary") or "").strip()

    def mark_recap_failed(self, error_message: str, model: str) -> None:
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            recap["status"] = "failed"
            recap["last_error"] = str(error_message or "").strip()
            recap["model"] = str(model or "").strip()
            recap["strategy"] = RECAP_PIPELINE_VERSION
            recap["updated_at"] = _now_timestamp()
            self._append_event_locked("error", f"Recap failed: {recap['last_error']}")
            self._save_locked()

    def stop_recap(self, model: str, message: str = "") -> None:
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            recap["status"] = "idle"
            recap["last_error"] = ""
            recap["model"] = str(model or recap.get("model") or "").strip()
            recap["strategy"] = RECAP_PIPELINE_VERSION
            recap["updated_at"] = _now_timestamp()
            if message:
                self._append_event_locked("info", message)
            self._save_locked()

    def save_final_recap(self, text: str, model: str) -> None:
        clean_text = str(text or "").strip()
        self.final_recap_path.write_text(clean_text, encoding="utf-8")
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            recap["status"] = "ready"
            recap["last_error"] = ""
            recap["updated_at"] = _now_timestamp()
            recap["model"] = str(model or "").strip()
            recap["strategy"] = RECAP_PIPELINE_VERSION
            recap["final_path"] = str(Path("recap") / self.final_recap_path.name).replace("\\", "/")
            self._append_event_locked("info", "Final recap is ready.")
            self._save_locked()

    def save_recap_text(self, text: str, model: str) -> None:
        clean_text = str(text or "").strip()
        if clean_text and not clean_text.lstrip().startswith("#"):
            clean_text = f"## Session Recap\n\n{clean_text}".strip()
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            recap["last_error"] = ""
            recap["updated_at"] = _now_timestamp()
            recap["model"] = str(model or recap.get("model") or "").strip()
            recap["strategy"] = RECAP_PIPELINE_VERSION
            if clean_text:
                self.final_recap_path.write_text(clean_text, encoding="utf-8")
                recap["status"] = "ready"
                recap["final_path"] = str(Path("recap") / self.final_recap_path.name).replace("\\", "/")
            else:
                recap["status"] = "idle"
                recap["final_path"] = ""
                try:
                    if self.final_recap_path.exists():
                        self.final_recap_path.unlink()
                except Exception as exc:
                    print(f"[WARN] Failed to remove recap {self.final_recap_path}: {exc}", file=sys.stderr)
            self._save_locked()

    def recap_text(self) -> str:
        if not self.final_recap_path.exists():
            return ""
        return _read_text_if_exists(self.final_recap_path)

    def save_recap_artifact(self, relative_path: str, content: str) -> Path:
        target = self.recap_dir / Path(str(relative_path or "").strip())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content or "").strip(), encoding="utf-8")
        return target

    def save_recap_json_artifact(self, relative_path: str, payload: dict) -> Path:
        target = self.recap_dir / Path(str(relative_path or "").strip())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return target

    def update_recap_progress(
        self,
        *,
        windows: Optional[int] = None,
        merge_rounds: Optional[int] = None,
        prompt_eval_max: Optional[int] = None,
        processed_chunk_count: Optional[int] = None,
    ) -> None:
        with self._lock:
            recap = self._manifest.setdefault("recap", {})
            if windows is not None:
                recap["investigation_windows"] = max(0, int(windows))
            if merge_rounds is not None:
                recap["merge_rounds"] = max(0, int(merge_rounds))
            if prompt_eval_max is not None:
                recap["prompt_eval_max"] = max(int(recap.get("prompt_eval_max") or 0), int(prompt_eval_max))
            if processed_chunk_count is not None:
                recap["processed_chunk_count"] = max(0, int(processed_chunk_count))
            recap["strategy"] = RECAP_PIPELINE_VERSION
            recap["input_budget_tokens"] = RECAP_TARGET_INPUT_TOKENS
            recap["updated_at"] = _now_timestamp()
            self._save_locked()

    def has_pending_transcript_work(self) -> bool:
        with self._lock:
            for chunk in self._manifest.get("chunks", []):
                if chunk.get("capture_state") == "captured" and chunk.get("transcript_state") == "pending":
                    return True
        return False

    def transcript_counts(self) -> dict[str, int]:
        counts = {"capturing": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0}
        with self._lock:
            for chunk in self._manifest.get("chunks", []):
                transcript_state = str(chunk.get("transcript_state") or "").strip().lower()
                capture_state = str(chunk.get("capture_state") or "").strip().lower()
                if capture_state == "capturing":
                    counts["capturing"] += 1
                if transcript_state in counts:
                    counts[transcript_state] += 1
        return counts

    def last_event(self) -> dict:
        with self._lock:
            events = self._manifest.get("events", [])
            if not events:
                return {}
            return copy.deepcopy(events[-1])

    def delete(self) -> None:
        try:
            if self.root.exists():
                shutil.rmtree(self.root, ignore_errors=True)
        except Exception as exc:
            print(f"[WARN] Failed to delete transcript state {self.root}: {exc}", file=sys.stderr)


def delete_session_transcript_state(session_id: str) -> None:
    root = session_transcript_dir(_safe_component(str(session_id or ""), "session"))
    try:
        if root.exists():
            shutil.rmtree(root, ignore_errors=True)
    except Exception as exc:
        print(f"[WARN] Failed to delete transcript state {root}: {exc}", file=sys.stderr)


@dataclass
class AudioInputDescriptor:
    device_id: str
    name: str


@dataclass
class OllamaGenerationResult:
    text: str
    prompt_eval_count: int = 0
    eval_count: int = 0
    thinking_text: str = ""
    thinking_truncated: bool = False


def _soundcard_modules() -> tuple[object | None, object | None, str]:
    try:
        import numpy as np
    except Exception as exc:
        return None, None, f"System audio capture requires NumPy: {exc}"
    try:
        import soundcard as sc
    except Exception as exc:
        return None, None, f"System audio capture requires the open-source SoundCard package: {exc}"
    return sc, np, ""


def _soundcard_loopback_identifier(device) -> str:
    raw_id = str(getattr(device, "id", "") or "").strip()
    if raw_id:
        return raw_id
    return str(getattr(device, "name", "") or "").strip()


def _list_soundcard_loopback_inputs() -> tuple[list[AudioInputDescriptor], str]:
    soundcard_module, _, error_message = _soundcard_modules()
    if soundcard_module is None:
        return [], error_message
    try:
        devices: list[AudioInputDescriptor] = []
        seen: set[str] = set()
        for device in soundcard_module.all_microphones(include_loopback=True):
            if not bool(getattr(device, "isloopback", False)):
                continue
            device_id = _soundcard_loopback_identifier(device)
            if not device_id or device_id in seen:
                continue
            seen.add(device_id)
            name = str(getattr(device, "name", "") or device_id).strip()
            devices.append(AudioInputDescriptor(device_id=device_id, name=name))
    except Exception as exc:
        return [], f"Unable to enumerate system audio loopback devices: {exc}"
    if not devices:
        return [], "No system audio loopback devices were detected."
    return devices, ""


def _resolve_soundcard_loopback_device(device_id: str):
    target_id = str(device_id or "").strip()
    if not target_id:
        raise RuntimeError("Select a system audio loopback device before starting capture.")
    soundcard_module, _, error_message = _soundcard_modules()
    if soundcard_module is None:
        raise RuntimeError(error_message)
    try:
        for device in soundcard_module.all_microphones(include_loopback=True):
            if not bool(getattr(device, "isloopback", False)):
                continue
            if _soundcard_loopback_identifier(device) == target_id:
                return device
    except Exception as exc:
        raise RuntimeError(f"Unable to enumerate system audio loopback devices: {exc}") from exc
    raise RuntimeError(f"System audio loopback device '{target_id}' was not found.")


class WhisperCppRunner:
    def transcribe(self, audio_path: Path, cli_path: str, model_path: str) -> str:
        cli = Path(str(cli_path or "").strip()) if str(cli_path or "").strip() else _managed_whisper_cli_path()
        model = Path(str(model_path or "").strip()) if str(model_path or "").strip() else _managed_whisper_model_path()
        if not cli.exists() or not model.exists():
            cli, model = ensure_managed_whisper_runtime()
        output_prefix = audio_path.with_suffix("")
        txt_output = output_prefix.with_suffix(".txt")
        try:
            if txt_output.exists():
                txt_output.unlink()
        except Exception:
            pass
        command = [
            str(cli),
            "-m",
            str(model),
            "-f",
            str(audio_path),
            "-of",
            str(output_prefix),
            "-otxt",
            "-np",
        ]
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = str(result.stdout or "").strip()
        stderr = str(result.stderr or "").strip()
        if result.returncode != 0:
            raise RuntimeError(stderr or stdout or f"whisper.cpp exited with code {result.returncode}.")
        if txt_output.exists():
            text = txt_output.read_text(encoding="utf-8").strip()
            if text:
                return text
        if stdout:
            print(
                "[WARN] whisper.cpp did not emit a .txt file; using stdout transcript output instead.",
                file=sys.stderr,
            )
            return stdout
        raise RuntimeError("whisper.cpp completed without producing transcript text.")


class OllamaRecapRunner:
    def generate(
        self,
        host: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        *,
        format_hint: object = "",
        num_predict: int = 0,
        stream_callback: Optional[Callable[[str, str], None]] = None,
    ) -> OllamaGenerationResult:
        clean_host = str(host or DEFAULT_OLLAMA_HOST).strip() or DEFAULT_OLLAMA_HOST
        clean_model = str(model or DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL
        model_name = clean_model.lower()
        url = f"{clean_host.rstrip('/')}/api/generate"
        think_setting: object = False
        if "gpt-oss" in model_name:
            think_setting = "medium"
        payload_obj: dict[str, object] = {
            "model": clean_model,
            "system": str(system_prompt or "").strip(),
            "prompt": str(user_prompt or ""),
            "stream": True,
            "think": think_setting,
            "options": {
                "temperature": 1.0,
            },
        }
        if format_hint:
            payload_obj["format"] = format_hint
        if num_predict > 0:
            minimum_predict = 160 if "gpt-oss" in model_name else 64
            payload_obj["options"]["num_predict"] = max(minimum_predict, int(num_predict))
        payload = json.dumps(payload_obj).encode("utf-8")
        req = urllib_request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib_request.urlopen(req, timeout=300) as response:
                final_payload: Optional[dict[str, object]] = None
                response_chunks: list[str] = []
                thinking_chunks: list[str] = []
                saw_payload = False
                thinking_truncated = False
                truncation_notice = (
                    f"\n\n[reasoning truncated after about {RECAP_REASONING_BUDGET_TOKENS} estimated tokens]\n"
                )
                while True:
                    raw_line = response.readline()
                    if not raw_line:
                        break
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    saw_payload = True
                    try:
                        payload_obj = json.loads(line)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            f"Ollama returned invalid streaming JSON: {line[:240]}"
                        ) from exc
                    if not isinstance(payload_obj, dict):
                        raise RuntimeError("Ollama returned an invalid streaming response payload.")
                    error_message = str(payload_obj.get("error") or "").strip()
                    if error_message:
                        raise RuntimeError(f"Ollama request failed: {error_message}")
                    thinking_chunk = str(payload_obj.get("thinking") or "")
                    response_chunk = str(payload_obj.get("response") or "")
                    if thinking_chunk:
                        if not thinking_truncated:
                            candidate_thinking = "".join((*thinking_chunks, thinking_chunk))
                            if _estimate_text_tokens(candidate_thinking) > RECAP_REASONING_BUDGET_TOKENS:
                                thinking_truncated = True
                                thinking_chunks.append(truncation_notice)
                                if stream_callback is not None:
                                    stream_callback("thinking", truncation_notice)
                            else:
                                thinking_chunks.append(thinking_chunk)
                                if stream_callback is not None:
                                    stream_callback("thinking", thinking_chunk)
                    if response_chunk:
                        response_chunks.append(response_chunk)
                        if stream_callback is not None:
                            stream_callback("response", response_chunk)
                    if bool(payload_obj.get("done")):
                        final_payload = payload_obj
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
            raise RuntimeError(f"Ollama request failed: {detail or exc}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(
                f"Unable to reach Ollama at {clean_host}. Is the local server running?"
            ) from exc
        if not saw_payload:
            raise RuntimeError("Ollama returned an empty streaming response.")
        if final_payload is None:
            raise RuntimeError("Ollama stream ended without a final payload.")
        text = "".join(response_chunks).strip()
        return OllamaGenerationResult(
            text=text,
            prompt_eval_count=max(0, int(final_payload.get("prompt_eval_count") or 0)),
            eval_count=max(0, int(final_payload.get("eval_count") or 0)),
            thinking_text="".join(thinking_chunks).strip(),
            thinking_truncated=thinking_truncated,
        )


class _QtChunkRecorder(QObject):
    chunkCommitted = Signal()
    fatalError = Signal(str)

    def __init__(
        self,
        store: SessionTranscriptStore,
        *,
        source: str,
        device_id: str,
        device_name: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._source = str(source or "mic").strip().lower() or "mic"
        self._device_id = str(device_id or "").strip()
        self._device_name = str(device_name or "").strip()
        self._audio_source = None
        self._io_device = None
        self._chunk_timer = QTimer(self)
        self._chunk_timer.setInterval(CAPTURE_CHUNK_MS)
        self._chunk_timer.timeout.connect(self._rotate_chunk)
        self._wave_file = None
        self._wave_writer = None
        self._chunk_bytes = 0
        self._active_chunk_id = ""
        self._format = None
        self._qt_audio_module = None

    def start(self) -> None:
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        except Exception as exc:
            raise RuntimeError(f"Qt audio capture is unavailable: {exc}") from exc

        self._qt_audio_module = (QAudioFormat, QAudioSource, QMediaDevices)
        device = self._resolve_device(QMediaDevices)
        audio_format = self._select_format(QAudioFormat, device)
        self._format = audio_format
        self._audio_source = QAudioSource(device, audio_format, self)
        io_device = self._audio_source.start()
        if io_device is None:
            raise RuntimeError(f"Unable to open {_display_source_name(self._source)} audio input.")
        self._io_device = io_device
        self._io_device.readyRead.connect(self._drain_audio)
        self._open_new_chunk()
        self._chunk_timer.start()

    def halt(self) -> None:
        self._chunk_timer.stop()
        self._drain_audio()
        if self._audio_source is not None:
            try:
                self._audio_source.stop()
            except Exception:
                pass
        self._finalize_current_chunk()

    def _resolve_device(self, media_devices_cls):
        inputs = list(media_devices_cls.audioInputs())
        target_id = self._device_id
        if target_id:
            for device in inputs:
                if self._device_identifier(device) == target_id:
                    return device
        default_device = media_devices_cls.defaultAudioInput()
        if target_id:
            raise RuntimeError(
                f"Audio device '{target_id}' was not found for {_display_source_name(self._source)} capture."
            )
        return default_device

    def _select_format(self, audio_format_cls, device):
        preferred = device.preferredFormat()
        try:
            target = audio_format_cls()
            target.setSampleRate(16000)
            target.setChannelCount(1 if self._source == "mic" else max(1, int(preferred.channelCount() or 2)))
            target.setSampleFormat(audio_format_cls.SampleFormat.Int16)
            if device.isFormatSupported(target):
                return target
            if preferred.sampleFormat() == audio_format_cls.SampleFormat.Int16:
                return preferred
            alt = audio_format_cls()
            alt.setSampleRate(max(8000, int(preferred.sampleRate() or 16000)))
            alt.setChannelCount(max(1, int(preferred.channelCount() or 1)))
            alt.setSampleFormat(audio_format_cls.SampleFormat.Int16)
            if device.isFormatSupported(alt):
                return alt
        except Exception:
            pass
        raise RuntimeError(
            f"{_display_source_name(self._source)} capture requires a PCM Int16 device format."
        )

    def _open_new_chunk(self) -> None:
        chunk = self._store.begin_live_chunk(
            self._source,
            device_id=self._device_id,
            device_name=self._device_name,
            file_suffix=".wav",
        )
        audio_path = self._store.chunk_audio_path(chunk)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        self._wave_file = open(audio_path, "wb")
        self._wave_writer = wave.open(self._wave_file, "wb")
        self._wave_writer.setnchannels(max(1, int(self._format.channelCount())))
        self._wave_writer.setsampwidth(self._sample_width_bytes())
        self._wave_writer.setframerate(max(8000, int(self._format.sampleRate())))
        self._active_chunk_id = str(chunk.get("chunk_id") or "")
        self._chunk_bytes = 0

    def _sample_width_bytes(self) -> int:
        sample_format = self._format.sampleFormat()
        enum_name = str(getattr(sample_format, "name", sample_format))
        if "UInt8" in enum_name:
            return 1
        if "Int16" in enum_name:
            return 2
        if "Int32" in enum_name or "Float" in enum_name:
            return 4
        raise RuntimeError("Unsupported Qt sample format for WAV output.")

    def _rotate_chunk(self) -> None:
        self._drain_audio()
        self._finalize_current_chunk()
        self._open_new_chunk()

    def _finalize_current_chunk(self) -> None:
        if not self._active_chunk_id:
            return
        active_chunk_id = self._active_chunk_id
        chunk_size = self._chunk_bytes
        self._active_chunk_id = ""
        try:
            if self._wave_writer is not None:
                self._wave_writer.close()
        except Exception as exc:
            self._store.mark_chunk_capture_failed(active_chunk_id, str(exc))
            self.fatalError.emit(str(exc))
        finally:
            self._wave_writer = None
            if self._wave_file is not None:
                try:
                    self._wave_file.close()
                except Exception:
                    pass
            self._wave_file = None
        self._store.finalize_live_chunk(active_chunk_id, chunk_size)
        if chunk_size > 0:
            self.chunkCommitted.emit()

    def _drain_audio(self) -> None:
        if self._io_device is None or self._wave_writer is None:
            return
        try:
            data = self._io_device.readAll()
        except Exception as exc:
            self._store.mark_chunk_capture_failed(self._active_chunk_id, str(exc))
            self.fatalError.emit(str(exc))
            return
        raw = bytes(data)
        if not raw:
            return
        try:
            self._wave_writer.writeframesraw(raw)
            self._chunk_bytes += len(raw)
        except Exception as exc:
            self._store.mark_chunk_capture_failed(self._active_chunk_id, str(exc))
            self.fatalError.emit(str(exc))

    @staticmethod
    def _device_identifier(device) -> str:
        try:
            raw = bytes(device.id())
            text = raw.decode("utf-8", errors="ignore").strip()
            if text:
                return text
        except Exception:
            pass
        return str(device.description() or "").strip()


class _SoundCardLoopbackRecorder(QObject):
    chunkCommitted = Signal()
    fatalError = Signal(str)

    def __init__(
        self,
        store: SessionTranscriptStore,
        *,
        source: str,
        device_id: str,
        device_name: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._source = str(source or "system").strip().lower() or "system"
        self._device_id = str(device_id or "").strip()
        self._device_name = str(device_name or "").strip()
        self._worker: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wave_file = None
        self._wave_writer = None
        self._chunk_bytes = 0
        self._active_chunk_id = ""
        self._chunk_failed = False
        self._numpy = None
        self._recorder_device = None

    def start(self) -> None:
        _, numpy_module, error_message = _soundcard_modules()
        if numpy_module is None:
            raise RuntimeError(error_message)
        self._numpy = numpy_module
        self._recorder_device = _resolve_soundcard_loopback_device(self._device_id)
        if not self._device_name:
            self._device_name = str(getattr(self._recorder_device, "name", "") or self._device_id).strip()
        self._stop_event.clear()
        self._open_new_chunk()
        self._worker = threading.Thread(target=self._record_loop, daemon=True)
        self._worker.start()

    def halt(self) -> None:
        self._stop_event.set()
        worker = self._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=5)
        self._worker = None

    def _record_loop(self) -> None:
        try:
            with self._recorder_device.recorder(samplerate=SYSTEM_LOOPBACK_SAMPLE_RATE) as recorder:
                next_rotation_at = time.monotonic() + (CAPTURE_CHUNK_MS / 1000.0)
                while not self._stop_event.is_set():
                    frames = recorder.record(numframes=SYSTEM_LOOPBACK_BLOCK_FRAMES)
                    self._write_frames(frames)
                    if time.monotonic() < next_rotation_at:
                        continue
                    self._finalize_current_chunk()
                    if self._stop_event.is_set():
                        break
                    self._open_new_chunk()
                    next_rotation_at = time.monotonic() + (CAPTURE_CHUNK_MS / 1000.0)
        except Exception as exc:
            self._mark_current_chunk_failed(str(exc))
            self.fatalError.emit(str(exc))
        finally:
            self._finalize_current_chunk()

    def _open_new_chunk(self) -> None:
        chunk = self._store.begin_live_chunk(
            self._source,
            device_id=self._device_id,
            device_name=self._device_name,
            file_suffix=".wav",
        )
        audio_path = self._store.chunk_audio_path(chunk)
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        self._wave_file = open(audio_path, "wb")
        self._wave_writer = wave.open(self._wave_file, "wb")
        self._wave_writer.setnchannels(1)
        self._wave_writer.setsampwidth(2)
        self._wave_writer.setframerate(SYSTEM_LOOPBACK_SAMPLE_RATE)
        self._active_chunk_id = str(chunk.get("chunk_id") or "")
        self._chunk_bytes = 0
        self._chunk_failed = False

    def _write_frames(self, frames) -> None:
        if self._wave_writer is None or self._numpy is None:
            return
        array = self._numpy.asarray(frames)
        if array.size <= 0:
            return
        if array.ndim > 1:
            array = array.mean(axis=1)
        array = self._numpy.clip(array, -1.0, 1.0)
        pcm = (array * 32767.0).astype(self._numpy.int16)
        raw = pcm.tobytes()
        if not raw:
            return
        self._wave_writer.writeframesraw(raw)
        self._chunk_bytes += len(raw)

    def _mark_current_chunk_failed(self, error_message: str) -> None:
        if not self._active_chunk_id or self._chunk_failed:
            return
        self._chunk_failed = True
        self._store.mark_chunk_capture_failed(self._active_chunk_id, error_message)

    def _finalize_current_chunk(self) -> None:
        if not self._active_chunk_id:
            return
        active_chunk_id = self._active_chunk_id
        chunk_size = self._chunk_bytes
        chunk_failed = self._chunk_failed
        self._active_chunk_id = ""
        self._chunk_bytes = 0
        self._chunk_failed = False
        close_error = ""
        try:
            if self._wave_writer is not None:
                self._wave_writer.close()
        except Exception as exc:
            close_error = str(exc)
            chunk_failed = True
        finally:
            self._wave_writer = None
            if self._wave_file is not None:
                try:
                    self._wave_file.close()
                except Exception:
                    pass
            self._wave_file = None
        if close_error:
            self._store.mark_chunk_capture_failed(active_chunk_id, close_error)
            self.fatalError.emit(close_error)
            return
        if chunk_failed:
            return
        self._store.finalize_live_chunk(active_chunk_id, chunk_size)
        if chunk_size > 0:
            self.chunkCommitted.emit()


class TranscriptSessionController(QObject):
    stateChanged = Signal()
    transcriptChanged = Signal(str)
    recapChanged = Signal(str)
    recapStreamChanged = Signal(object)

    def __init__(
        self,
        parent: Optional[QObject] = None,
        *,
        transcriber: Optional[WhisperCppRunner] = None,
        recap_runner: Optional[OllamaRecapRunner] = None,
    ) -> None:
        super().__init__(parent)
        self._transcriber = transcriber or WhisperCppRunner()
        self._recap_runner = recap_runner or OllamaRecapRunner()
        self._store: Optional[SessionTranscriptStore] = None
        self._session_name = ""
        self._recorders: dict[str, object] = {}
        self._worker_lock = threading.Lock()
        self._worker_running = False
        self._pending_recap_request = False
        self._stop_requested = False
        self._session_generation = 0
        self._mic_devices_cache: list[AudioInputDescriptor] = []
        self._system_devices_cache: list[AudioInputDescriptor] = []
        self._mic_devices_error = ""
        self._system_devices_error = ""
        self._recap_stream_lock = threading.Lock()
        self._recap_stream_state = _new_recap_stream_snapshot()
        self._recap_stream_last_stage_by_channel = {"thinking": "", "response": ""}

    def close(self) -> None:
        self.halt(announce=False)
        self._session_generation += 1
        self._reset_recap_stream()

    def bind_session(self, session_id: Optional[str], session_name: str = "") -> None:
        self.halt(announce=False)
        self._session_generation += 1
        self._stop_requested = False
        self._session_name = str(session_name or "").strip()
        if not session_id:
            self._store = None
            self._reset_recap_stream()
            self.stateChanged.emit()
            self.transcriptChanged.emit("")
            self.recapChanged.emit("")
            return
        self._store = SessionTranscriptStore(str(session_id))
        runtime = load_transcript_runtime_settings()
        self._store.update_runtime_settings(
            runtime["whisper_cli_path"],
            runtime["whisper_model_path"],
            runtime["ollama_host"],
            runtime["ollama_model"],
        )
        self._reset_recap_stream()
        self.stateChanged.emit()
        self.transcriptChanged.emit(self.transcript_text())
        self.recapChanged.emit(self.recap_text())

    def snapshot(self) -> dict:
        if self._store is None:
            return {
                "has_session": False,
                "session_name": "",
                "state": "idle",
                "counts": {"capturing": 0, "pending": 0, "running": 0, "completed": 0, "failed": 0},
                "last_event": {},
                "runtime": load_transcript_runtime_settings(),
                "source_mode": DEFAULT_SOURCE_MODE,
                "capture_devices": {"mic_id": "", "mic_name": "", "system_id": "", "system_name": ""},
                "manual_transcript": {"enabled": False, "path": "", "updated_at": "", "estimated_tokens": 0},
                "recap": {"status": "idle", "last_error": "", "checkpoint_count": 0, "processed_chunk_count": 0},
                "transcript_estimated_tokens": 0,
                "session_dir": "",
                "recording": False,
                "audio_devices_error": self._combined_audio_devices_error(),
            }
        manifest = self._store.snapshot()
        return {
            "has_session": True,
            "session_name": self._session_name,
            "state": manifest.get("state", "idle"),
            "counts": self._store.transcript_counts(),
            "last_event": self._store.last_event(),
            "runtime": manifest.get("runtime", {}),
            "source_mode": manifest.get("source_mode", DEFAULT_SOURCE_MODE),
            "capture_devices": manifest.get(
                "capture_devices",
                {"mic_id": "", "mic_name": "", "system_id": "", "system_name": ""},
            ),
            "manual_transcript": manifest.get(
                "manual_transcript",
                {"enabled": False, "path": "", "updated_at": "", "estimated_tokens": 0},
            ),
            "recap": manifest.get("recap", {}),
            "transcript_estimated_tokens": self.estimated_transcript_tokens(),
            "session_dir": str(self._store.root),
            "recording": bool(self._recorders),
            "audio_devices_error": self._combined_audio_devices_error(),
        }

    def transcript_text(self) -> str:
        if self._store is None:
            return ""
        return self._store.transcript_text()

    def recap_text(self) -> str:
        if self._store is None:
            return ""
        return self._store.recap_text()

    def recap_stream_snapshot(self) -> dict[str, object]:
        with self._recap_stream_lock:
            return dict(self._recap_stream_state)

    def estimated_transcript_tokens(self) -> int:
        if self._store is None:
            return 0
        return _estimate_text_tokens(self._store.transcript_text())

    def recap_generation_preflight(self, *, store: Optional[SessionTranscriptStore] = None) -> tuple[bool, int, str]:
        active_store = store or self._store
        if active_store is None:
            return False, 0, "Create or select a session first."
        transcript_text = active_store.transcript_text().strip()
        if not transcript_text:
            return False, 0, "Transcript is empty. Generate transcript text first."
        estimated_tokens = _estimate_text_tokens(transcript_text)
        if estimated_tokens > RECAP_AUTO_GENERATE_MAX_TOKENS:
            return (
                False,
                estimated_tokens,
                f"Cannot auto generate recap because the transcript is estimated at {estimated_tokens} tokens and the limit is {RECAP_AUTO_GENERATE_MAX_TOKENS}.",
            )
        return True, estimated_tokens, ""

    def generated_transcript_text(self) -> str:
        if self._store is None:
            return ""
        return self._store.generated_transcript_text()

    def update_runtime_settings(
        self,
        whisper_cli_path: str,
        whisper_model_path: str,
        ollama_host: str,
        ollama_model: str,
    ) -> None:
        runtime = save_transcript_runtime_settings(
            whisper_cli_path,
            whisper_model_path,
            ollama_host,
            ollama_model,
        )
        if self._store is not None:
            self._store.update_runtime_settings(
                runtime["whisper_cli_path"],
                runtime["whisper_model_path"],
                runtime["ollama_host"],
                runtime["ollama_model"],
            )
        self.stateChanged.emit()

    def update_capture_preferences(
        self,
        source_mode: str,
        *,
        mic_id: str,
        mic_name: str,
        system_id: str,
        system_name: str,
    ) -> None:
        if self._store is None:
            return
        self._store.update_capture_preferences(
            source_mode,
            mic_id=mic_id,
            mic_name=mic_name,
            system_id=system_id,
            system_name=system_name,
        )
        self.stateChanged.emit()

    def save_manual_transcript(self, text: str) -> None:
        if self._store is None:
            return
        self._store.save_manual_transcript(text)
        self.stateChanged.emit()
        self.transcriptChanged.emit(self.transcript_text())
        self.recapChanged.emit(self.recap_text())

    def clear_manual_transcript(self) -> None:
        if self._store is None:
            return
        self._store.clear_manual_transcript()
        self.stateChanged.emit()
        self.transcriptChanged.emit(self.transcript_text())
        self.recapChanged.emit(self.recap_text())

    def save_recap_text(self, text: str) -> None:
        if self._store is None:
            return
        snapshot = self.snapshot()
        model = str(
            snapshot.get("recap", {}).get("model")
            or snapshot.get("runtime", {}).get("ollama_model")
            or DEFAULT_OLLAMA_MODEL
        )
        self._store.save_recap_text(text, model)
        self.stateChanged.emit()
        self.recapChanged.emit(self.recap_text())

    def _combined_audio_devices_error(self) -> str:
        messages = [message for message in (self._mic_devices_error, self._system_devices_error) if message]
        return "\n".join(messages)

    def list_mic_inputs(self, *, force_refresh: bool = False) -> tuple[list[AudioInputDescriptor], str]:
        if self._mic_devices_cache and not force_refresh:
            return list(self._mic_devices_cache), self._mic_devices_error
        try:
            from PySide6.QtMultimedia import QMediaDevices
        except Exception as exc:
            self._mic_devices_cache = []
            self._mic_devices_error = f"Microphone input support is unavailable: {exc}"
            return [], self._mic_devices_error
        try:
            devices = []
            for device in QMediaDevices.audioInputs():
                device_id = _QtChunkRecorder._device_identifier(device)
                devices.append(AudioInputDescriptor(device_id=device_id, name=str(device.description() or device_id)))
        except Exception as exc:
            self._mic_devices_cache = []
            self._mic_devices_error = f"Unable to enumerate microphone inputs: {exc}"
            return [], self._mic_devices_error
        self._mic_devices_cache = devices
        self._mic_devices_error = "" if devices else "No microphone inputs were detected."
        return list(self._mic_devices_cache), self._mic_devices_error

    def list_system_audio_inputs(self, *, force_refresh: bool = False) -> tuple[list[AudioInputDescriptor], str]:
        if self._system_devices_cache and not force_refresh:
            return list(self._system_devices_cache), self._system_devices_error
        devices, error_message = _list_soundcard_loopback_inputs()
        self._system_devices_cache = list(devices)
        self._system_devices_error = error_message
        return list(self._system_devices_cache), self._system_devices_error

    def suggest_system_audio_device_id(self) -> str:
        devices, _ = self.list_system_audio_inputs()
        for device in devices:
            lowered = device.name.strip().lower()
            if any(keyword in lowered for keyword in SYSTEM_AUDIO_KEYWORDS):
                return device.device_id
        if devices:
            return devices[0].device_id
        return ""

    def import_audio_files(self, paths: list[str], source: str) -> int:
        if self._store is None:
            return 0
        imported = 0
        for path in paths:
            clean_path = str(path or "").strip()
            if not clean_path:
                continue
            try:
                self._store.add_imported_audio(source, clean_path)
                imported += 1
            except Exception as exc:
                self._store.append_event("error", f"Failed to import audio {clean_path}: {exc}")
                break
        if imported:
            self._store.set_state("halted", f"Imported {imported} audio file(s) for {_display_source_name(source)}.")
            self.request_processing(run_recap=False)
        self.stateChanged.emit()
        return imported

    def start_capture(
        self,
        source_mode: str,
        *,
        mic_id: str,
        mic_name: str,
        system_id: str,
        system_name: str,
    ) -> None:
        if self._store is None:
            return
        if self._recorders:
            self._store.append_event("warn", "Capture is already running.")
            self.stateChanged.emit()
            return
        requested_sources = _source_mode_sources(source_mode)
        if "mic" in requested_sources and not mic_id:
            self._store.append_event("error", "Select a microphone input before starting capture.")
            self.stateChanged.emit()
            return
        if "system" in requested_sources and not system_id:
            self._store.append_event(
                "error",
                "Select a system audio loopback/monitor input before starting capture.",
            )
            self.stateChanged.emit()
            return
        self.update_capture_preferences(
            source_mode,
            mic_id=mic_id,
            mic_name=mic_name,
            system_id=system_id,
            system_name=system_name,
        )
        self._stop_requested = False
        created_recorders: dict[str, object] = {}
        try:
            if "mic" in requested_sources:
                created_recorders["mic"] = self._build_recorder("mic", mic_id, mic_name)
            if "system" in requested_sources:
                created_recorders["system"] = self._build_recorder("system", system_id, system_name)
            for recorder in created_recorders.values():
                recorder.start()
        except Exception as exc:
            for recorder in created_recorders.values():
                try:
                    recorder.halt()
                except Exception:
                    pass
            self._recorders = {}
            self._store.set_state("error", f"Failed to start capture: {exc}")
            self.stateChanged.emit()
            return
        self._recorders = created_recorders
        self._store.set_state("recording", "Capture started.")
        self.request_processing(run_recap=False)
        self.stateChanged.emit()

    def _build_recorder(self, source: str, device_id: str, device_name: str):
        if str(source or "").strip().lower() == "system":
            recorder = _SoundCardLoopbackRecorder(
                self._store,
                source=source,
                device_id=device_id,
                device_name=device_name,
                parent=self,
            )
        else:
            recorder = _QtChunkRecorder(
                self._store,
                source=source,
                device_id=device_id,
                device_name=device_name,
                parent=self,
            )
        recorder.chunkCommitted.connect(lambda: self.request_processing(run_recap=False))
        recorder.fatalError.connect(self._on_capture_error)
        return recorder

    def _on_capture_error(self, message: str) -> None:
        if self._store is not None:
            self._store.set_state("error", f"Capture error: {message}")
        self.halt(announce=False)
        self.stateChanged.emit()

    def halt(self, *, announce: bool = True) -> None:
        self._stop_requested = True
        active_recorders = list(self._recorders.values())
        self._recorders = {}
        had_recorders = bool(active_recorders)
        for recorder in active_recorders:
            try:
                recorder.halt()
            except Exception as exc:
                if self._store is not None:
                    self._store.append_event("error", f"Failed to halt capture cleanly: {exc}")
        if self._store is not None:
            if had_recorders:
                message = "Capture stopped. Final chunk saved and queued for transcription." if announce else ""
            else:
                message = "Work halted." if announce else ""
            self._store.set_state("halted", message)
        if self.recap_stream_snapshot().get("running"):
            if self._store is not None:
                recap_model = str(self._store.snapshot().get("recap", {}).get("model") or DEFAULT_OLLAMA_MODEL)
                self._store.stop_recap(recap_model)
            self._finish_recap_stream("", clear_reasoning=True)
        if had_recorders:
            self.request_processing(run_recap=False)
        self.stateChanged.emit()

    def retry_failed_chunks(self) -> None:
        if self._store is None:
            return
        retried = self._store.requeue_failed_chunks()
        if retried:
            self.request_processing(run_recap=False)
        self.stateChanged.emit()

    def request_processing(self, *, run_recap: bool) -> None:
        if self._store is None:
            return
        self._stop_requested = False
        with self._worker_lock:
            self._pending_recap_request = self._pending_recap_request or bool(run_recap)
            if self._worker_running:
                return
            self._worker_running = True
            generation = self._session_generation
            worker = threading.Thread(
                target=self._worker_loop,
                args=(generation,),
                daemon=True,
            )
            worker.start()

    def _worker_loop(self, generation: int) -> None:
        try:
            while True:
                if generation != self._session_generation or self._store is None:
                    return
                if self._stop_requested:
                    return
                self.transcribe_pending_now(store=self._store, generation=generation)
                if generation != self._session_generation or self._store is None:
                    return
                run_recap = False
                with self._worker_lock:
                    run_recap = self._pending_recap_request
                    self._pending_recap_request = False
                if run_recap and not self._stop_requested:
                    self.generate_recap_now(store=self._store, generation=generation)
                if generation != self._session_generation or self._store is None:
                    return
                with self._worker_lock:
                    if self._pending_recap_request or self._store.has_pending_transcript_work():
                        continue
                    self._worker_running = False
                    break
        finally:
            with self._worker_lock:
                self._worker_running = False
            if generation == self._session_generation:
                self.stateChanged.emit()
                self.transcriptChanged.emit(self.transcript_text())
                self.recapChanged.emit(self.recap_text())

    def transcribe_pending_now(
        self,
        *,
        store: Optional[SessionTranscriptStore] = None,
        generation: Optional[int] = None,
    ) -> int:
        active_store = store or self._store
        if active_store is None:
            return 0
        processed = 0
        while not self._stop_requested:
            if generation is not None and generation != self._session_generation:
                break
            chunk = active_store.claim_next_transcript_chunk()
            if chunk is None:
                break
            runtime = active_store.snapshot().get("runtime", {})
            try:
                text = self._transcriber.transcribe(
                    active_store.chunk_audio_path(chunk),
                    str(runtime.get("whisper_cli_path") or ""),
                    str(runtime.get("whisper_model_path") or ""),
                )
            except Exception as exc:
                active_store.mark_chunk_transcript_failed(chunk["chunk_id"], str(exc))
                break
            active_store.mark_chunk_transcribed(chunk["chunk_id"], text)
            processed += 1
            if generation is None or generation == self._session_generation:
                self.transcriptChanged.emit(active_store.transcript_text())
                self.stateChanged.emit()
        return processed

    def request_recap(self) -> None:
        if self._store is None:
            return
        allowed, _, error_message = self.recap_generation_preflight()
        if not allowed:
            if error_message:
                self._store.mark_recap_failed(error_message, "")
                self.stateChanged.emit()
                self.recapChanged.emit(self.recap_text())
            return
        self._store.clear_recap_error()
        self.request_processing(run_recap=True)
        self.stateChanged.emit()

    def generate_recap_now(
        self,
        *,
        store: Optional[SessionTranscriptStore] = None,
        generation: Optional[int] = None,
    ) -> bool:
        active_store = store or self._store
        if active_store is None:
            return False
        allowed, transcript_tokens, error_message = self.recap_generation_preflight(store=active_store)
        entries = active_store.transcript_entries()
        if not allowed:
            self._reset_recap_stream(message=error_message)
            active_store.mark_recap_failed(error_message, "")
            return False
        transcript_text = active_store.transcript_text().strip()
        runtime = active_store.snapshot().get("runtime", {})
        host = str(runtime.get("ollama_host") or DEFAULT_OLLAMA_HOST)
        model = str(runtime.get("ollama_model") or DEFAULT_OLLAMA_MODEL)
        active_store.mark_recap_running(model)
        self._reset_recap_stream(running=True, host=host, model=model, message="Recap generation started.")
        active_store.save_recap_artifact("pipeline_prompts.md", self._pipeline_prompts_markdown())
        try:
            self._ensure_recap_generation_active(active_store, generation)
            active_store.update_recap_progress(windows=1, merge_rounds=0, processed_chunk_count=len(entries))
            stage_one = self._run_validated_recap_stage(
                active_store,
                host,
                model,
                stage_name="stage1_summary",
                system_prompt=self._stage_one_recap_system_prompt(),
                user_prompt=self._build_stage_one_recap_prompt(transcript_text, transcript_tokens),
                format_requirements=(
                    "Return only the recap gist in plain prose. Use 1 to 3 short paragraphs, no headings, no bullet points, and no more than 15 sentences total."
                ),
                parser=lambda raw: _parse_plain_recap_response(raw, min_chars=90, max_paragraphs=3, max_sentences=15),
            )
            active_store.save_recap_artifact("stage1_summary.md", stage_one)
            active_store.save_recap_artifact("final_draft.md", stage_one)
            active_store.save_recap_checkpoint(stage_one, len(entries), model)
            self._ensure_recap_generation_active(active_store, generation)
            stage_two = self._run_validated_recap_stage(
                active_store,
                host,
                model,
                stage_name="stage2_refine",
                system_prompt=self._stage_two_recap_system_prompt(),
                user_prompt=self._build_stage_two_recap_prompt(transcript_text, stage_one, transcript_tokens),
                format_requirements=(
                    "Return only the refined recap gist in plain prose. Use 1 to 3 short paragraphs, no headings, no bullet points, no more than 15 sentences total, keep only the most important developments, and remove anything not clearly supported by the transcript."
                ),
                parser=lambda raw: _parse_plain_recap_response(raw, min_chars=90, max_paragraphs=3, max_sentences=15),
            )
            active_store.save_recap_artifact("stage2_refined.md", stage_two)
            final_text = stage_two
            active_store.save_recap_checkpoint(final_text, len(entries), model)
            active_store.update_recap_progress(windows=2, merge_rounds=0, processed_chunk_count=len(entries))
        except Exception as exc:
            if str(exc) == "Recap halted by user.":
                self._finish_recap_stream("", clear_reasoning=True)
                active_store.stop_recap(model)
                if generation is None or generation == self._session_generation:
                    self.stateChanged.emit()
                return False
            self._finish_recap_stream(str(exc))
            active_store.mark_recap_failed(str(exc), model)
            return False
        final_recap = self._compose_final_recap_markdown(final_text, {}, {})
        active_store.save_final_recap(final_recap, model)
        self._finish_recap_stream("Final recap is ready.")
        if generation is None or generation == self._session_generation:
            self.recapChanged.emit(active_store.recap_text())
            self.stateChanged.emit()
        return True

    def _reset_recap_stream(
        self,
        *,
        running: bool = False,
        host: str = "",
        model: str = "",
        message: str = "",
    ) -> None:
        with self._recap_stream_lock:
            self._recap_stream_state = _new_recap_stream_snapshot()
            self._recap_stream_last_stage_by_channel = {"thinking": "", "response": ""}
            self._recap_stream_state.update(
                {
                    "running": bool(running),
                    "host": str(host or "").strip(),
                    "model": str(model or "").strip(),
                    "message": str(message or "").strip(),
                }
            )
            snapshot = dict(self._recap_stream_state)
        self.recapStreamChanged.emit(snapshot)

    def _ensure_recap_stream_stage_locked(self, stage_name: str) -> None:
        clean_stage_name = str(stage_name or "").strip()
        if self._recap_stream_state.get("stage_name") == clean_stage_name:
            return
        self._recap_stream_state["stage_name"] = clean_stage_name

    def _append_recap_stream_chunk(self, stage_name: str, channel: str, text: str) -> None:
        chunk = str(text or "")
        if not chunk:
            return
        normalized_channel = "thinking" if str(channel or "").strip().lower() == "thinking" else "response"
        target_key = "thinking_log" if normalized_channel == "thinking" else "response_log"
        with self._recap_stream_lock:
            self._ensure_recap_stream_stage_locked(stage_name)
            existing = str(self._recap_stream_state.get(target_key) or "")
            if self._recap_stream_last_stage_by_channel.get(normalized_channel) != str(stage_name or "").strip():
                header = f"=== {str(stage_name or '').strip()} ===\n"
                existing = f"{existing}\n\n{header}" if existing else header
                self._recap_stream_last_stage_by_channel[normalized_channel] = str(stage_name or "").strip()
            self._recap_stream_state[target_key] = f"{existing}{chunk}"
            snapshot = dict(self._recap_stream_state)
        self.recapStreamChanged.emit(snapshot)

    def _finish_recap_stream(self, message: str, *, clear_reasoning: bool = False) -> None:
        with self._recap_stream_lock:
            self._recap_stream_state["running"] = False
            self._recap_stream_state["message"] = str(message or "").strip()
            if clear_reasoning:
                self._recap_stream_state["thinking_log"] = ""
            snapshot = dict(self._recap_stream_state)
        self.recapStreamChanged.emit(snapshot)

    def _mark_recap_stream_stage(self, stage_name: str) -> None:
        with self._recap_stream_lock:
            self._ensure_recap_stream_stage_locked(stage_name)
            snapshot = dict(self._recap_stream_state)
        self.recapStreamChanged.emit(snapshot)

    def _ensure_recap_generation_active(
        self,
        active_store: SessionTranscriptStore,
        generation: Optional[int],
    ) -> None:
        if self._stop_requested:
            active_store.set_state("halted", "Recap halted.")
            raise RuntimeError("Recap halted by user.")
        if generation is not None and generation != self._session_generation:
            raise RuntimeError("Recap generation was superseded by another session.")

    def _pipeline_prompts_markdown(self) -> str:
        lines = [
            "# Recap Prompt Chain",
            "",
            f"- Strategy: `{RECAP_PIPELINE_VERSION}`",
            f"- Automatic recap is refused above `{RECAP_AUTO_GENERATE_MAX_TOKENS}` estimated transcript tokens.",
            f"- Hard ceiling enforced per Ollama call: `{RECAP_MAX_INPUT_TOKENS}` estimated tokens.",
            "- Stage 1 writes a gist recap from the full transcript.",
            "- Stage 2 refines and compresses that gist against the full transcript.",
            "- Final recap target is 15 sentences or fewer.",
            "- Each model stage is format-validated in code and retried up to three times on invalid output.",
            "- If a stage still fails validation, recap generation stops and debug artifacts are written under `recap/debug/`.",
            "",
            "## Stage 1",
            "",
            self._stage_one_recap_system_prompt().strip(),
            "",
            "## Stage 2",
            "",
            self._stage_two_recap_system_prompt().strip(),
            "",
        ]
        return "\n".join(lines).strip()

    def _stage_one_recap_system_prompt(self) -> str:
        return (
            "You are writing a gist recap of a DnD session transcript.\n"
            "Write in the language of the transcript and use past tense.\n"
            "Capture only the biggest developments, major decisions, important discoveries, and the ending state.\n"
            "Omit minor tactical detail unless it changes the outcome.\n"
            "Keep reasoning brief and decisive. Make one pass and do not loop or restate the same point.\n"
            "Return only plain prose in 1 to 3 short paragraphs and no more than 15 sentences total.\n"
            "Do not use headings or bullet points.\n"
        )

    def _stage_two_recap_system_prompt(self) -> str:
        return (
            "You are refining a gist recap of a DnD session.\n"
            "Use the transcript as the source of truth.\n"
            "Refine and compress the recap in the language of the transcript and use past tense.\n"
            "Remove things which cannot be clearly derived from transcript context.\n"
            "Keep only the most important developments, decisions, discoveries, and ending-state facts.\n"
            "Prefer gist over detail.\n"
            "Keep reasoning brief and decisive. Make one pass and do not loop or restate the same point.\n"
            "Return only plain prose in 1 to 3 short paragraphs and no more than 15 sentences total.\n"
            "Do not use headings or bullet points.\n"
        )

    def _build_stage_one_recap_prompt(self, transcript_text: str, transcript_tokens: int) -> str:
        return (
            f"Session: {self._session_name or 'Unnamed Session'}\n"
            f"Estimated transcript tokens: {transcript_tokens}\n\n"
            "Transcript:\n"
            f"{transcript_text.strip()}\n"
        )

    def _build_stage_two_recap_prompt(self, transcript_text: str, stage_one_summary: str, transcript_tokens: int) -> str:
        return (
            f"Session: {self._session_name or 'Unnamed Session'}\n"
            f"Estimated transcript tokens: {transcript_tokens}\n\n"
            "Stage 1 recap draft:\n"
            f"{stage_one_summary.strip()}\n\n"
            "Transcript:\n"
            f"{transcript_text.strip()}\n"
        )

    def _stage_three_audit_system_prompt(self) -> str:
        return (
            "You are checking whether a DnD session recap missed any important facts from the transcript.\n"
            "Use the transcript as the source of truth.\n"
            "Respond in English.\n"
            "In 2 to 4 short sentences, write plain prose audit notes for the repair pass.\n"
            "Focus on final decisions, ending state, named leads, recovered items, and unresolved hooks that still matter.\n"
            "Only call out material omissions or underemphasized facts that change a reader's understanding of the outcome.\n"
            "Ignore wording-only differences and facts already covered with different phrasing.\n"
            "If no material omissions stand out, say so once in plain prose and stop.\n"
            "Keep your reasoning brief and decisive.\n"
            "Make one pass over the evidence and do not loop, restate earlier conclusions, or revisit the same point unless new transcript evidence changes it.\n"
            "Do not repeat the same candidate omission, second-guess yourself out loud, or list more than two candidate omissions.\n"
            "Do not use sentinel phrases, bullets, headings, JSON, or status prefixes.\n"
            "Do not rewrite the recap.\n"
        )

    def _stage_three_repair_system_prompt(self) -> str:
        return (
            "You are repairing a DnD session recap.\n"
            "Use the transcript as the source of truth and the audit notes as required coverage.\n"
            "Treat the current recap as the baseline and revise it with the smallest possible edits.\n"
            "Keep it relatively short.\n"
            "Preserve all supported facts, names, decisions, end-state details, and unresolved hooks already present in the current recap unless the transcript contradicts them.\n"
            "Only add the audit-noted missing points that the transcript supports.\n"
            "If the audit notes say the recap is already complete, return the current recap unchanged.\n"
            "Keep your reasoning brief and decisive.\n"
            "Make one pass over the transcript and audit notes and do not loop, restate earlier conclusions, or revisit the same point unless new transcript evidence changes it.\n"
            "Do not drop supported end-state facts just to make room for new ones.\n"
            "Return only plain prose in 1 to 3 short paragraphs, ideally keeping the existing paragraph structure.\n"
            "Do not use headings or bullet points.\n"
        )

    def _build_stage_three_audit_prompt(self, transcript_text: str, recap_text: str, transcript_tokens: int) -> str:
        return (
            f"Session: {self._session_name or 'Unnamed Session'}\n"
            f"Estimated transcript tokens: {transcript_tokens}\n\n"
            "Current recap:\n"
            f"{recap_text.strip()}\n\n"
            "Transcript:\n"
            f"{transcript_text.strip()}\n"
        )

    def _build_stage_three_repair_prompt(
        self,
        transcript_text: str,
        recap_text: str,
        audit_notes: str,
        transcript_tokens: int,
    ) -> str:
        return (
            f"Session: {self._session_name or 'Unnamed Session'}\n"
            f"Estimated transcript tokens: {transcript_tokens}\n\n"
            "Current recap:\n"
            f"{recap_text.strip()}\n\n"
            "Audit notes:\n"
            f"{audit_notes.strip()}\n\n"
            "Transcript:\n"
            f"{transcript_text.strip()}\n"
        )

    def _run_stage_three_audit(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        *,
        stage_name: str,
        transcript_text: str,
        recap_text: str,
        transcript_tokens: int,
    ) -> str:
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=stage_name,
            system_prompt=self._stage_three_audit_system_prompt(),
            user_prompt=self._build_stage_three_audit_prompt(transcript_text, recap_text, transcript_tokens),
            format_requirements=(
                "Return plain prose audit notes in English. Use 1 or 2 short paragraphs, no bullets, headings, JSON, sentinel phrases, or status prefixes."
            ),
            parser=_parse_plain_audit_notes_response,
        )

    def _build_investigation_windows(self, entries: list[dict]) -> list[dict[str, object]]:
        slices: list[dict[str, object]] = []
        for entry in entries:
            started_at = str(entry.get("started_at") or "")
            source = str(entry.get("source") or "mic")
            entry_sequence = max(1, int(entry.get("sequence") or len(slices) + 1))
            prefix = f"[{started_at}] [{_display_source_name(source)}] ".strip()
            prefix_tokens = _estimate_text_tokens(prefix)
            slice_budget = max(140, RECAP_TEXT_SLICE_TOKENS - prefix_tokens)
            segments = _split_text_by_token_budget(str(entry.get("text") or ""), slice_budget)
            for index, segment in enumerate(segments, start=1):
                display_text = f"{prefix} {segment}".strip()
                slice_id = f"{entry_sequence:06d}.{index:02d}"
                slices.append(
                    {
                        "slice_id": slice_id,
                        "entry_sequence": entry_sequence,
                        "started_at": started_at,
                        "source": source,
                        "display_text": display_text,
                        "estimated_tokens": _estimate_text_tokens(display_text),
                    }
                )
        windows: list[dict[str, object]] = []
        current_slices: list[dict[str, object]] = []
        current_tokens = 0
        seen_entries: set[int] = set()
        for slice_payload in slices:
            slice_tokens = max(1, int(slice_payload.get("estimated_tokens") or 0))
            if current_slices and current_tokens + slice_tokens > RECAP_INVESTIGATION_WINDOW_TOKENS:
                windows.append(self._finalize_window(current_slices, len(windows) + 1, seen_entries))
                current_slices = []
                current_tokens = 0
                seen_entries = set()
            current_slices.append(slice_payload)
            current_tokens += slice_tokens
            seen_entries.add(int(slice_payload.get("entry_sequence") or 0))
        if current_slices:
            windows.append(self._finalize_window(current_slices, len(windows) + 1, seen_entries))
        return windows

    def _finalize_window(
        self,
        slices: list[dict[str, object]],
        window_index: int,
        seen_entries: set[int],
    ) -> dict[str, object]:
        first_id = str(slices[0].get("slice_id") or "")
        last_id = str(slices[-1].get("slice_id") or "")
        text = "\n".join(str(item.get("display_text") or "") for item in slices).strip()
        return {
            "window_index": window_index,
            "slice_range": f"{first_id} -> {last_id}",
            "text": text,
            "estimated_tokens": _estimate_text_tokens(text),
            "processed_entry_count": len(seen_entries),
            "slices": copy.deepcopy(slices),
        }

    def _call_recap_model(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        *,
        stage_name: str,
        system_prompt: str,
        user_prompt: str,
        format_hint: object = "",
        num_predict: int = 0,
    ) -> str:
        estimated_input_tokens = _estimate_text_tokens(system_prompt) + _estimate_text_tokens(user_prompt)
        if estimated_input_tokens > RECAP_MAX_INPUT_TOKENS:
            raise RuntimeError(
                f"Refused to call Ollama for stage '{stage_name}' because the prompt budget would exceed "
                f"{RECAP_MAX_INPUT_TOKENS} estimated tokens."
            )
        active_store.save_recap_artifact(
            f"debug/{stage_name}_request.md",
            (
                f"# {stage_name}\n\n"
                f"Estimated input tokens: {estimated_input_tokens}\n\n"
                "## System Prompt\n\n"
                f"{system_prompt.strip()}\n\n"
                "## User Prompt\n\n"
                f"{user_prompt.strip()}\n"
            ),
        )
        self._mark_recap_stream_stage(stage_name)
        result = self._recap_runner.generate(
            host,
            model,
            system_prompt,
            user_prompt,
            format_hint=format_hint,
            num_predict=num_predict,
            stream_callback=lambda channel, chunk: self._append_recap_stream_chunk(stage_name, channel, chunk),
        )
        active_store.save_recap_artifact(f"debug/{stage_name}_response.txt", result.text)
        if result.thinking_text:
            active_store.save_recap_artifact(f"debug/{stage_name}_thinking.txt", result.thinking_text)
        if result.thinking_truncated:
            active_store.append_event(
                "warn",
                f"Stage '{stage_name}' reasoning stream was truncated after about {RECAP_REASONING_BUDGET_TOKENS} estimated tokens.",
            )
        active_store.update_recap_progress(prompt_eval_max=result.prompt_eval_count)
        if result.prompt_eval_count > RECAP_MAX_INPUT_TOKENS:
            active_store.append_event(
                "warn",
                f"Stage '{stage_name}' used {result.prompt_eval_count} prompt tokens according to Ollama.",
            )
        return result.text

    def _run_validated_recap_stage(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        *,
        stage_name: str,
        system_prompt: str,
        user_prompt: str,
        format_requirements: str,
        parser: Callable[[str], tuple[bool, object, str]],
        num_predict: int = 0,
    ):
        attempt_errors: list[str] = []
        raw_attempts: list[str] = []
        base_prompt = str(user_prompt or "").strip()
        for attempt in range(1, RECAP_STAGE_MAX_ATTEMPTS + 1):
            repair_prompt = base_prompt
            if attempt_errors:
                repair_prompt = (
                    f"{base_prompt}\n\n"
                    "FORMAT REQUIREMENTS:\n"
                    f"{format_requirements.strip()}\n\n"
                    "LAST RESPONSE WAS INVALID:\n"
                    f"{attempt_errors[-1]}\n\n"
                    "Return only a valid answer in the exact required format.\n"
                )
            attempt_stage_name = f"{stage_name}_attempt_{attempt:02d}"
            raw = self._call_recap_model(
                active_store,
                host,
                model,
                stage_name=attempt_stage_name,
                system_prompt=system_prompt,
                user_prompt=repair_prompt,
                num_predict=num_predict,
            )
            raw_attempts.append(raw)
            ok, parsed, error_message = parser(raw)
            validation_report = [
                f"# {attempt_stage_name}",
                "",
                f"Valid: {ok}",
                "",
                "## Format Requirements",
                "",
                format_requirements.strip(),
                "",
                "## Raw Response",
                "",
                _normalize_model_output(raw) or "<empty>",
                "",
            ]
            if error_message:
                validation_report.extend(("## Validation Error", "", error_message.strip(), ""))
            active_store.save_recap_artifact(
                f"debug/{attempt_stage_name}_validation.md",
                "\n".join(validation_report).strip(),
            )
            if ok:
                return parsed
            attempt_errors.append(str(error_message or "Unknown validation failure.").strip())
        failure_lines = [
            f"# {stage_name} Failure",
            "",
            f"Stage failed after {RECAP_STAGE_MAX_ATTEMPTS} invalid responses.",
            "",
            "## Format Requirements",
            "",
            format_requirements.strip(),
            "",
        ]
        for index, raw in enumerate(raw_attempts, start=1):
            failure_lines.extend(
                (
                    f"## Attempt {index}",
                    "",
                    f"Validation Error: {attempt_errors[index - 1]}",
                    "",
                    "Raw Response:",
                    "",
                    _normalize_model_output(raw) or "<empty>",
                    "",
                )
            )
        active_store.save_recap_artifact(f"debug/{stage_name}_failure.md", "\n".join(failure_lines).strip())
        raise RuntimeError(
            f"Recap stage '{stage_name}' failed after {RECAP_STAGE_MAX_ATTEMPTS} invalid responses. "
            f"See recap/debug/{stage_name}_failure.md for details."
        )

    def _render_turn_line(self, turn: dict[str, str]) -> str:
        speaker = str(turn.get("speaker") or "").strip()
        text = _normalize_line_item(str(turn.get("text") or ""), max_chars=520)
        if not text:
            return ""
        if _is_mechanics_only_text(text):
            return ""
        if speaker:
            return f"{speaker}: {text}"
        return text

    def _build_window_micro_blocks(self, window: dict[str, object]) -> list[dict[str, object]]:
        turns = _split_dialogue_turns(str(window.get("text") or ""))
        blocks: list[dict[str, object]] = []
        current_lines: list[str] = []
        current_tokens = 0
        start_turn_index = 1
        last_turn_index = 0
        for turn_index, turn in enumerate(turns, start=1):
            line = self._render_turn_line(turn)
            if not line:
                continue
            line_tokens = _estimate_text_tokens(line)
            if current_lines and current_tokens + line_tokens > RECAP_MICRO_BLOCK_TOKENS:
                block_text = "\n".join(current_lines).strip()
                blocks.append(
                    {
                        "block_index": len(blocks) + 1,
                        "turn_range": f"{start_turn_index}-{last_turn_index or turn_index - 1}",
                        "text": block_text,
                        "estimated_tokens": _estimate_text_tokens(block_text),
                    }
                )
                current_lines = []
                current_tokens = 0
                start_turn_index = turn_index
            current_lines.append(line)
            current_tokens += line_tokens
            last_turn_index = turn_index
        if current_lines:
            block_text = "\n".join(current_lines).strip()
            blocks.append(
                {
                    "block_index": len(blocks) + 1,
                    "turn_range": f"{start_turn_index}-{last_turn_index or start_turn_index}",
                    "text": block_text,
                    "estimated_tokens": _estimate_text_tokens(block_text),
                }
            )
        if blocks:
            return blocks
        clean_text = _normalize_model_output(str(window.get("text") or ""))
        if not clean_text:
            return []
        return [
            {
                "block_index": 1,
                "turn_range": "1-1",
                "text": clean_text,
                "estimated_tokens": _estimate_text_tokens(clean_text),
            }
        ]

    def _block_mode_system_prompt(self) -> str:
        return (
            "You are the Block Mode Classifier.\n"
            "Read only the supplied transcript block.\n"
            "Answer with exactly one lowercase word from this list and nothing else:\n"
            "setup investigation combat interrogation loot planning travel aftermath other\n"
            "Choose the dominant mode of the block.\n"
        )

    def _block_flags_system_prompt(self) -> str:
        return (
            "You are the Block Boundary Classifier.\n"
            "Read only the supplied transcript block.\n"
            "Return exactly two lines and nothing else in this exact order:\n"
            "IMPORTANCE: low|medium|high\n"
            "BOUNDARY: split|keep\n"
            "Use split only if the block ends at a natural scene boundary.\n"
        )

    def _block_summary_system_prompt(self) -> str:
        return (
            "You are the Block Summary Extractor.\n"
            "Read only the supplied transcript block.\n"
            "Return either exactly one line starting with 'SUMMARY: ' followed by one sentence, or the single word 'none'.\n"
            "Write one neutral narrator sentence about what materially changed in this block.\n"
            "Do not quote speakers. Do not copy tactical chatter. Ignore dice, confirmations, and filler.\n"
            "Do not infer attacks, wounds, motives, or consequences that are not explicitly stated.\n"
        )

    def _prefixed_extractor_system_prompt(self, label: str, description: str, max_items: int) -> str:
        return (
            f"You are the {label.title()} Extractor.\n"
            "Read only the supplied transcript block.\n"
            f"Return either the single word 'none' or up to {max_items} lines, each starting with '{label}: '.\n"
            f"Extract only {description}.\n"
            "Convert raw dialogue into concise factual statements.\n"
            "Ignore jokes, proposals that were not accepted, dice chatter, and repeated setup.\n"
            "Do not infer unseen attacks, wounds, motives, relationships, or future plans.\n"
            "Do not include any other text.\n"
        )

    def _scene_writer_system_prompt(self) -> str:
        return (
            "You are the Scene Weaver.\n"
            "Use only the supplied structured scene notes.\n"
            "Return exactly one line starting with 'SCENE: ' followed by 3 to 5 sentences of coherent prose.\n"
            "Write neutral recap prose with clear cause and effect.\n"
            "Prefer anchors, outcomes, unresolved threads, and how the scene ends.\n"
            "Do not quote transcript lines or repeat the same setup twice.\n"
        )

    def _build_block_prompt(
        self,
        window: dict[str, object],
        block: dict[str, object],
    ) -> str:
        return (
            f"Session: {self._session_name or 'Unnamed Session'}\n"
            f"Window: {int(window.get('window_index') or 1)}\n"
            f"Slice range: {window.get('slice_range')}\n"
            f"Block: {int(block.get('block_index') or 1)}\n"
            f"Turns: {block.get('turn_range')}\n\n"
            "Transcript block:\n"
            f"{str(block.get('text') or '').strip()}\n"
        )

    def _build_scene_writer_prompt(self, scene: dict[str, object]) -> str:
        sections = [
            f"Session: {self._session_name or 'Unnamed Session'}",
            f"Scene: {int(scene.get('scene_index') or 1)}",
            f"Mode: {scene.get('mode') or 'other'}",
            "",
            "Block Summaries:",
        ]
        for value in list(scene.get("summaries", []))[:6]:
            sections.append(f"- {value}")
        sections.extend(("", "Anchors:"))
        for value in list(scene.get("anchors", []))[:8]:
            sections.append(f"- {value}")
        sections.extend(("", "Outcomes:"))
        for value in list(scene.get("outcomes", []))[:6]:
            sections.append(f"- {value}")
        sections.extend(("", "Decisions:"))
        for value in list(scene.get("decisions", []))[:6]:
            sections.append(f"- {value}")
        sections.extend(("", "Entities:"))
        for value in list(scene.get("entities", []))[:8]:
            sections.append(f"- {value}")
        sections.extend(("", "Open Threads:"))
        for value in list(scene.get("open_threads", []))[:4]:
            sections.append(f"- {value}")
        return "\n".join(sections).strip()

    def _classify_block_mode(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        window: dict[str, object],
        block: dict[str, object],
    ) -> str:
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=f"window_{int(window.get('window_index') or 1):04d}_block_{int(block.get('block_index') or 1):02d}_mode",
            system_prompt=self._block_mode_system_prompt(),
            user_prompt=self._build_block_prompt(window, block),
            format_requirements="Return exactly one lowercase word from: setup investigation combat interrogation loot planning travel aftermath other",
            parser=lambda raw: _parse_choice_response(raw, RECAP_ALLOWED_BLOCK_MODES),
            num_predict=24,
        )

    def _classify_block_flags(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        window: dict[str, object],
        block: dict[str, object],
    ) -> dict[str, str]:
        required_keys = {
            "IMPORTANCE": ("low", "medium", "high"),
            "BOUNDARY": ("split", "keep"),
        }
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=f"window_{int(window.get('window_index') or 1):04d}_block_{int(block.get('block_index') or 1):02d}_flags",
            system_prompt=self._block_flags_system_prompt(),
            user_prompt=self._build_block_prompt(window, block),
            format_requirements=(
                "Return exactly two lines in this order:\n"
                "IMPORTANCE: low|medium|high\n"
                "BOUNDARY: split|keep"
            ),
            parser=lambda raw: _parse_flag_lines_response(raw, required_keys),
            num_predict=64,
        )

    def _extract_block_summary(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        window: dict[str, object],
        block: dict[str, object],
        *,
        mode: str,
        flags: dict[str, str],
    ) -> str:
        prompt = (
            f"{self._build_block_prompt(window, block)}\n\n"
            f"Mode: {mode}\n"
            f"Importance: {flags.get('IMPORTANCE', 'medium')}\n"
            "Focus on the most important net-new development in this block.\n"
        )
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=f"window_{int(window.get('window_index') or 1):04d}_block_{int(block.get('block_index') or 1):02d}_summary",
            system_prompt=self._block_summary_system_prompt(),
            user_prompt=prompt,
            format_requirements="Return either 'none' or exactly one line starting with 'SUMMARY: '.",
            parser=lambda raw: _parse_single_prefixed_line_response(raw, prefix="SUMMARY: ", allow_none=True),
            num_predict=120,
        )

    def _extract_block_prefixed_items(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        *,
        window: dict[str, object],
        block: dict[str, object],
        stage_suffix: str,
        label: str,
        description: str,
        max_items: int,
        num_predict: int,
    ) -> list[str]:
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=f"window_{int(window.get('window_index') or 1):04d}_block_{int(block.get('block_index') or 1):02d}_{stage_suffix}",
            system_prompt=self._prefixed_extractor_system_prompt(label, description, max_items),
            user_prompt=self._build_block_prompt(window, block),
            format_requirements=f"Return either 'none' or up to {max_items} lines, each starting with '{label}: '.",
            parser=lambda raw: _parse_prefixed_lines_response(raw, prefix=f"{label}: ", max_items=max_items, allow_none=True),
            num_predict=num_predict,
        )

    def _scene_mode_break(self, previous_mode: str, next_mode: str) -> bool:
        prev = str(previous_mode or "other").strip().lower() or "other"
        nxt = str(next_mode or "other").strip().lower() or "other"
        if prev == nxt:
            return False
        hard_breaks = {
            ("setup", "combat"),
            ("investigation", "combat"),
            ("combat", "loot"),
            ("combat", "planning"),
            ("combat", "aftermath"),
            ("interrogation", "planning"),
            ("travel", "setup"),
            ("loot", "planning"),
        }
        return (prev, nxt) in hard_breaks

    def _group_block_dossiers_into_scenes(self, block_dossiers: list[dict[str, object]]) -> list[dict[str, object]]:
        scenes: list[list[dict[str, object]]] = []
        current_scene: list[dict[str, object]] = []
        current_tokens = 0
        for dossier in block_dossiers:
            mode = str(dossier.get("mode") or "other")
            block_tokens = max(1, int(dossier.get("estimated_tokens") or 0))
            if current_scene:
                previous = current_scene[-1]
                previous_flags = dict(previous.get("flags") or {})
                previous_mode = str(previous.get("mode") or "other")
                needs_split = (
                    str(previous_flags.get("BOUNDARY") or "keep") == "split"
                    or self._scene_mode_break(previous_mode, mode)
                    or current_tokens + block_tokens > RECAP_SCENE_TARGET_TOKENS
                )
                if needs_split:
                    scenes.append(current_scene)
                    current_scene = []
                    current_tokens = 0
            current_scene.append(dossier)
            current_tokens += block_tokens
        if current_scene:
            scenes.append(current_scene)
        scene_payloads: list[dict[str, object]] = []
        for scene_index, blocks in enumerate(scenes, start=1):
            all_modes = [str(block.get("mode") or "other") for block in blocks]
            dominant_mode = max(set(all_modes), key=all_modes.count) if all_modes else "other"
            scene_payloads.append(
                {
                    "scene_index": scene_index,
                    "mode": dominant_mode,
                    "blocks": copy.deepcopy(blocks),
                    "summaries": _dedupe_preserve_order([str(block.get("summary") or "") for block in blocks if str(block.get("summary") or "").strip()]),
                    "anchors": _dedupe_preserve_order([item for block in blocks for item in list(block.get("anchors", []))]),
                    "outcomes": _dedupe_preserve_order([item for block in blocks for item in list(block.get("outcomes", []))]),
                    "decisions": _dedupe_preserve_order([item for block in blocks for item in list(block.get("decisions", []))]),
                    "entities": _dedupe_preserve_order([item for block in blocks for item in list(block.get("entities", []))]),
                    "open_threads": _dedupe_preserve_order([item for block in blocks for item in list(block.get("open_threads", []))]),
                }
            )
        return scene_payloads

    def _write_scene_paragraph(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        scene: dict[str, object],
    ) -> str:
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=f"scene_{int(scene.get('scene_index') or 1):02d}_writer",
            system_prompt=self._scene_writer_system_prompt(),
            user_prompt=self._build_scene_writer_prompt(scene),
            format_requirements="Return exactly one line starting with 'SCENE: ' followed by prose.",
            parser=lambda raw: _parse_single_prefixed_line_response(raw, prefix="SCENE: ", allow_none=False),
            num_predict=220,
        )

    def _window_model_chain_analysis(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        window: dict[str, object],
    ) -> dict[str, object]:
        block_dossiers: list[dict[str, object]] = []
        for block in self._build_window_micro_blocks(window):
            mode = self._classify_block_mode(active_store, host, model, window, block)
            flags = self._classify_block_flags(active_store, host, model, window, block)
            summary = self._extract_block_summary(active_store, host, model, window, block, mode=mode, flags=flags)
            anchors = self._extract_block_prefixed_items(
                active_store,
                host,
                model,
                window=window,
                block=block,
                stage_suffix="anchors",
                label="ANCHOR",
                description="must-keep facts, named people/items/places, end-state changes, or reveals that must survive the recap even if wording changes",
                max_items=4,
                num_predict=180,
            )
            outcomes = self._extract_block_prefixed_items(
                active_store,
                host,
                model,
                window=window,
                block=block,
                stage_suffix="outcomes",
                label="OUTCOME",
                description="concrete results, discoveries, state changes, recovered items, reveals, captures, escapes, or final consequences from this block",
                max_items=5,
                num_predict=180,
            )
            decisions = self._extract_block_prefixed_items(
                active_store,
                host,
                model,
                window=window,
                block=block,
                stage_suffix="decisions",
                label="DECISION",
                description="decisions that were actually made, agreed, or chosen by the end of this block",
                max_items=3,
                num_predict=160,
            )
            open_threads = self._extract_block_prefixed_items(
                active_store,
                host,
                model,
                window=window,
                block=block,
                stage_suffix="open_threads",
                label="OPEN",
                description="unresolved questions, missing information, escaped threats, or loose ends still open at the end of this block",
                max_items=3,
                num_predict=160,
            )
            entities = self._extract_block_prefixed_items(
                active_store,
                host,
                model,
                window=window,
                block=block,
                stage_suffix="entities",
                label="ENTITY",
                description="named people, places, factions, items, or terms that matter later in the recap",
                max_items=4,
                num_predict=180,
            )
            block_dossiers.append(
                {
                    "block_index": int(block.get("block_index") or len(block_dossiers) + 1),
                    "turn_range": str(block.get("turn_range") or ""),
                    "text": str(block.get("text") or ""),
                    "estimated_tokens": int(block.get("estimated_tokens") or 0),
                    "mode": mode,
                    "flags": flags,
                    "summary": summary,
                    "anchors": anchors,
                    "outcomes": outcomes,
                    "decisions": decisions,
                    "entities": entities,
                    "open_threads": open_threads,
                }
            )
        if not block_dossiers:
            raise RuntimeError(f"Window {int(window.get('window_index') or 1)} produced no recap blocks.")
        active_store.save_recap_json_artifact(
            f"investigations/window_{int(window.get('window_index') or 1):04d}_blocks.json",
            {"blocks": block_dossiers},
        )
        scenes = self._group_block_dossiers_into_scenes(block_dossiers)
        scene_paragraphs: list[str] = []
        for scene in scenes:
            scene_text = self._write_scene_paragraph(active_store, host, model, scene)
            scene["scene_text"] = scene_text
            scene_paragraphs.append(scene_text)
        active_store.save_recap_json_artifact(
            f"investigations/window_{int(window.get('window_index') or 1):04d}_scenes.json",
            {"scenes": scenes},
        )
        summary_candidates = scene_paragraphs + [str(block.get("summary") or "") for block in block_dossiers]
        return {
            "window_index": int(window.get("window_index") or 1),
            "slice_range": str(window.get("slice_range") or ""),
            "summary": _compose_summary_sentences(summary_candidates, max_sentences=4, max_chars=620),
            "key_beats": _dedupe_preserve_order(scene_paragraphs + [str(block.get("summary") or "") for block in block_dossiers if str(block.get("summary") or "").strip()])[:RECAP_MAX_CHRONOLOGY_ITEMS],
            "anchors": _dedupe_preserve_order([item for scene in scenes for item in list(scene.get("anchors", []))])[:RECAP_MAX_FACT_ITEMS],
            "important_facts": _dedupe_preserve_order(
                [item for scene in scenes for item in list(scene.get("anchors", []))]
                + [item for scene in scenes for item in list(scene.get("outcomes", []))]
                + [item for scene in scenes for item in list(scene.get("entities", []))]
            )[:RECAP_MAX_FACT_ITEMS],
            "evidence_gaps": _dedupe_preserve_order([item for scene in scenes for item in list(scene.get("open_threads", []))])[:RECAP_MAX_RULING_ITEMS],
            "decisions": _dedupe_preserve_order([item for scene in scenes for item in list(scene.get("decisions", []))])[:RECAP_MAX_DECISION_ITEMS],
            "tasks": [],
            "open_threads": _dedupe_preserve_order([item for scene in scenes for item in list(scene.get("open_threads", []))])[:RECAP_MAX_OPEN_THREAD_ITEMS],
            "rulings": [],
            "follow_ups": _dedupe_preserve_order([item for scene in scenes for item in list(scene.get("open_threads", []))])[:RECAP_MAX_FOLLOW_UP_ITEMS],
            "continuity_notes": _dedupe_preserve_order([item for scene in scenes for item in list(scene.get("outcomes", []))] + scene_paragraphs[-2:])[:RECAP_MAX_CONTINUITY_ITEMS],
            "scene_paragraphs": scene_paragraphs,
        }

    def _final_recap_system_prompt(self) -> str:
        return (
            "You are the Final Session Weaver.\n"
            "Use only the supplied scene notes and required facts.\n"
            "Return exactly 2 or 3 lines and nothing else in this format:\n"
            "P1: <paragraph>\n"
            "P2: <paragraph>\n"
            "Optional P3: <paragraph>\n"
            "Each line must be one prose paragraph.\n"
            "Write a coherent recap, not bullet points, not metadata, and not raw transcript quotes.\n"
            "Do not invent any fact, location, custody detail, motive, or consequence that is not explicitly supported by the supplied notes.\n"
            "Avoid repetition. Cover setup, major developments, resulting state, and unresolved hooks.\n"
        )

    def _session_keep_system_prompt(self) -> str:
        return (
            "You are the Session Keep Selector.\n"
            "Use only the supplied scene notes and extracted recap facts.\n"
            "Return either the single word 'none' or up to 8 lines, each starting with 'KEEP: '.\n"
            "Choose the facts that must survive into the final recap even if wording changes.\n"
            "Prefer named people, places, items, revealed connections, final decisions, and ending state.\n"
            "If later scenes contain named reveals or ending-state facts, prioritize those over early setup details.\n"
            "Ignore dice, micro-tactics, minor injuries, and incidental table chatter.\n"
        )

    def _final_recap_audit_system_prompt(self) -> str:
        return (
            "You are the Final Recap Auditor.\n"
            "Compare the supplied final recap against the supplied required facts and unresolved hooks.\n"
            "Return exactly one line 'STATUS: pass' if the recap covers them adequately.\n"
            "Otherwise return one line 'STATUS: fail' followed by up to 6 lines starting with 'MISSING: '.\n"
            "Each MISSING line must name one factual point or unresolved hook that should be added or clarified.\n"
            "Only fail for major omissions involving named reveals, final decisions, ending state, or unresolved hooks that still matter at session end.\n"
            "Ignore incidental tactics, minor injuries, and setup details that do not matter later.\n"
            "Do not rewrite the recap.\n"
        )

    def _ordered_session_points(self, values: list[str], *, limit: int) -> list[str]:
        return _dedupe_preserve_order([str(value or "") for value in values])[:limit]

    def _build_session_keep_prompt(
        self,
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> str:
        narrative_payload = dict(narrative_doc.get("payload") or {})
        coverage_payload = dict(coverage_doc.get("payload") or {})
        sections = [
            f"Session: {self._session_name or 'Unnamed Session'}",
            "",
            "Scene Notes:",
        ]
        for value in self._ordered_session_points(
            self._normalize_json_list(narrative_payload, "scene_paragraphs")
            or self._normalize_json_list(narrative_payload, "key_beats"),
            limit=8,
        ):
            sections.append(f"- {value}")
        sections.extend(("", "Anchors And Outcomes:"))
        for value in self._ordered_session_points(
            self._normalize_json_list(narrative_payload, "anchors")
            + self._normalize_json_list(narrative_payload, "important_facts")
            + self._normalize_json_list(narrative_payload, "continuity_notes"),
            limit=14,
        ):
            sections.append(f"- {value}")
        sections.extend(("", "Late Session Anchors:"))
        for value in self._ordered_session_points(self._normalize_json_list(narrative_payload, "anchors")[-6:], limit=6):
            sections.append(f"- {value}")
        sections.extend(("", "Decisions:"))
        for value in self._ordered_session_points(self._normalize_json_list(narrative_payload, "decisions"), limit=8):
            sections.append(f"- {value}")
        sections.extend(("", "Open Threads:"))
        for value in self._ordered_session_points(
            self._normalize_json_list(narrative_payload, "open_threads")
            + self._normalize_json_list(coverage_payload, "open_threads"),
            limit=8,
        ):
            sections.append(f"- {value}")
        return "\n".join(sections).strip()

    def _select_session_keep_points(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> list[str]:
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name="session_keep",
            system_prompt=self._session_keep_system_prompt(),
            user_prompt=self._build_session_keep_prompt(narrative_doc, coverage_doc),
            format_requirements="Return either 'none' or up to 8 lines, each starting with 'KEEP: '.",
            parser=lambda raw: _parse_prefixed_lines_response(raw, prefix="KEEP: ", max_items=8, allow_none=False),
            num_predict=220,
        )

    def _build_final_draft_prompt(
        self,
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
        keep_points: list[str],
        *,
        missing_points: Optional[list[str]] = None,
    ) -> str:
        narrative_payload = dict(narrative_doc.get("payload") or {})
        coverage_payload = dict(coverage_doc.get("payload") or {})
        anchors = self._normalize_json_list(narrative_payload, "anchors")
        if not anchors:
            anchors = self._normalize_json_list(narrative_payload, "important_facts")
        open_threads = self._ordered_session_points(
            self._normalize_json_list(narrative_payload, "open_threads")
            + self._normalize_json_list(coverage_payload, "open_threads"),
            limit=4,
        )
        continuity = self._ordered_session_points(
            self._normalize_json_list(narrative_payload, "continuity_notes")[-4:],
            limit=4,
        )
        late_anchors = self._ordered_session_points(self._normalize_json_list(narrative_payload, "anchors")[-6:], limit=6)
        required_facts = self._ordered_session_points(keep_points + late_anchors, limit=10)
        opening_facts = self._ordered_session_points(anchors[:4], limit=4)
        middle_facts = self._ordered_session_points(anchors[4:10] + self._normalize_json_list(narrative_payload, "important_facts")[:4], limit=6)
        ending_facts = self._ordered_session_points(
            late_anchors
            + self._normalize_json_list(narrative_payload, "decisions")[-4:]
            + continuity,
            limit=8,
        )
        sections = [
            f"Session: {self._session_name or 'Unnamed Session'}",
            "",
            "Opening Facts:",
        ]
        for value in opening_facts:
            sections.append(f"- {value}")
        sections.extend(("", "Confrontation And Discovery Facts:"))
        for value in middle_facts:
            sections.append(f"- {value}")
        sections.extend(("", "Ending Facts:"))
        for value in ending_facts:
            sections.append(f"- {value}")
        sections.extend(("", "Required Facts To Cover:"))
        for point in required_facts:
            sections.append(f"- {point}")
        sections.extend(("", "Remaining Hooks:"))
        for value in open_threads:
            sections.append(f"- {value}")
        sections.extend(
            (
                "",
                "Writing Plan:",
                "- P1 should cover the setup and initial approach.",
                "- P2 should cover the main confrontation and discoveries.",
                "- P3, if used, should cover the final decision, resulting state, and unresolved hooks.",
                "- Only mention unresolved hooks that are still open at the end of the session.",
                "- Do not quote raw dialogue or repeat the same setup twice.",
            )
        )
        if missing_points:
            sections.extend(("", "Repair Requirements:"))
            for value in self._ordered_session_points(list(missing_points), limit=6):
                sections.append(f"- {value}")
        return "\n".join(sections).strip()

    def _validate_final_recap_paragraphs(
        self,
        paragraphs: list[str],
    ) -> tuple[bool, str]:
        if len(set(paragraph.casefold() for paragraph in paragraphs)) != len(paragraphs):
            return False, "Paragraphs repeated the same content."
        first_sentences = [
            _strip_sentence_ending((_split_text_sentences(paragraph) or [paragraph])[0]).casefold()
            for paragraph in paragraphs
        ]
        if len(set(first_sentences)) != len(first_sentences):
            return False, "Multiple paragraphs opened with the same sentence."
        combined = " ".join(paragraphs).lower()
        forbidden_tokens = ("slice range", "coverage window", "prompt", "metadata")
        for token in forbidden_tokens:
            if token in combined:
                return False, f"Final recap contained forbidden metadata token {token!r}."
        if any(len(paragraph) < 90 for paragraph in paragraphs[:2]):
            return False, "Final recap paragraphs were too short to be useful."
        return True, ""

    def _normalize_json_list(self, payload: dict, key: str) -> list[str]:
        raw_values = payload.get(key, [])
        if not isinstance(raw_values, list):
            return []
        return _dedupe_preserve_order([str(value or "") for value in raw_values])

    def _collect_window_fragments(self, window_text: str) -> list[dict[str, object]]:
        fragments: list[dict[str, object]] = []
        turns = _split_dialogue_turns(window_text)
        for turn_index, turn in enumerate(turns):
            speaker = str(turn.get("speaker") or "").strip()
            turn_text = str(turn.get("text") or "").strip()
            for sentence_index, sentence in enumerate(_split_text_sentences(turn_text) or [turn_text]):
                clean_text = _ensure_sentence(sentence, max_chars=260)
                if not clean_text or _is_mechanics_only_text(clean_text):
                    continue
                lowered = clean_text.lower()
                fragments.append(
                    {
                        "speaker": speaker,
                        "text": clean_text,
                        "lower": lowered,
                        "order": len(fragments),
                        "turn_index": turn_index,
                        "sentence_index": sentence_index,
                    }
                )
        return fragments

    def _window_code_analysis(self, window: dict[str, object]) -> dict:
        fragments = self._collect_window_fragments(str(window.get("text") or ""))
        action_tokens = (
            "found",
            "followed",
            "heard",
            "saw",
            "slip",
            "grab",
            "kick",
            "burst",
            "rush",
            "grapple",
            "question",
            "inspect",
            "search",
            "disable",
            "open",
            "take",
            "bring",
            "leave",
            "recognize",
            "escaped",
            "tied",
        )
        reveal_tokens = (
            "there is",
            "there are",
            "inside",
            "looks like",
            "it is",
            "the ledger",
            "the signet",
            "you find",
            "you hear",
            "you see",
            "he says",
            "she says",
            "they says",
            "it sends",
            "same ",
            "entry",
            "wrapped in cloth",
            "someone at",
        )
        decision_tokens = (
            "i vote",
            "agreed",
            "let's",
            "we should",
            "we take",
            "we bring",
            "the call",
            "should not",
            "definitely not",
            "we do that",
            "we do it",
        )
        task_tokens = (
            "need to",
            "needs to",
            "we should",
            "i will",
            "we will",
            "let's",
            "bring",
            "search",
            "ask",
            "hand",
            "return",
            "report",
            "follow up",
            "update",
            "send",
        )
        open_tokens = (
            "don't know",
            "didn't know",
            "hard to say",
            "maybe",
            "unknown",
            "what is",
            "who is",
            "where is",
            "who's",
            "question",
            "escaped",
            "still",
            "too late",
        )
        plot_question_tokens = (
            "what is",
            "who is",
            "where is",
            "moon gate",
            "under the water",
            "buyers",
            "escaped",
            "compromised",
            "dock office",
            "magistrate",
            "signet",
            "ledger",
        )
        tactical_question_tokens = (
            "can i",
            "do we bring",
            "what do you do",
            "roll",
            "is he wearing",
            "can i drag",
            "can i listen",
        )
        ruling_tokens = (
            "with advantage",
            "with disadvantage",
            "can i",
            "you can",
            "you'll only",
            "roll ",
            "fails",
            "hits",
            "arcana",
            "stealth",
            "athletics",
            "intimidation",
        )
        outcome_tokens = (
            "you have",
            "we take",
            "we bring",
            "leave him",
            "tied",
            "captured",
            "disabled",
            "recognize",
            "lied",
            "stop",
        )

        chronology_candidates: list[str] = []
        facts: list[str] = []
        evidence_gaps: list[str] = []
        decisions: list[str] = []
        tasks: list[str] = []
        open_threads: list[str] = []
        rulings: list[str] = []
        follow_ups: list[str] = []

        total_fragments = max(1, len(fragments))
        for fragment in fragments:
            text = str(fragment.get("text") or "")
            lowered = str(fragment.get("lower") or "")
            speaker = str(fragment.get("speaker") or "").upper()
            is_dm = speaker in {"DM", "GM"}
            late_fragment = int(fragment.get("order") or 0) >= max(0, total_fragments - 4)
            looks_significant = (
                is_dm
                or _contains_any_token(lowered, action_tokens)
                or _contains_any_token(lowered, reveal_tokens)
                or _contains_any_token(lowered, decision_tokens)
                or _contains_any_token(lowered, outcome_tokens)
            )
            if looks_significant:
                chronology_candidates.append(text)
            if _contains_any_token(lowered, reveal_tokens) or (is_dm and len(text) >= 60):
                facts.append(text)
            is_plot_question = (
                "?" in text
                and _contains_any_token(lowered, plot_question_tokens)
                and not _contains_any_token(lowered, tactical_question_tokens)
            )
            if _contains_any_token(lowered, open_tokens) or is_plot_question:
                evidence_gaps.append(text)
                open_threads.append(text)
            if _contains_any_token(lowered, decision_tokens):
                decisions.append(text)
            if _contains_any_token(lowered, task_tokens):
                tasks.append(text)
            if _contains_any_token(lowered, ruling_tokens) and is_dm:
                rulings.append(text)
            if _contains_any_token(lowered, task_tokens) and (late_fragment or "before" in lowered or "after" in lowered):
                follow_ups.append(text)
            if late_fragment and (
                _contains_any_token(lowered, outcome_tokens)
                or _contains_any_token(lowered, open_tokens)
                or is_dm
            ):
                follow_ups.append(text)

        if not chronology_candidates:
            chronology_candidates = [str(fragment.get("text") or "") for fragment in fragments[:RECAP_MAX_CHRONOLOGY_ITEMS]]
        chronology = _dedupe_preserve_order(chronology_candidates)[:RECAP_MAX_CHRONOLOGY_ITEMS]
        important_facts = _dedupe_preserve_order(facts)[:RECAP_MAX_FACT_ITEMS]
        evidence_gaps = _dedupe_preserve_order(evidence_gaps)[:RECAP_MAX_RULING_ITEMS]
        decisions = _dedupe_preserve_order(decisions)[:RECAP_MAX_DECISION_ITEMS]
        tasks = _dedupe_preserve_order(tasks)[:RECAP_MAX_TASK_ITEMS]
        open_threads = _dedupe_preserve_order(open_threads)[:RECAP_MAX_OPEN_THREAD_ITEMS]
        rulings = _dedupe_preserve_order(rulings)[:RECAP_MAX_RULING_ITEMS]
        follow_ups = _dedupe_preserve_order(follow_ups)[:RECAP_MAX_FOLLOW_UP_ITEMS]

        tail_fragments = [str(fragment.get("text") or "") for fragment in fragments[max(0, len(fragments) - 5) :]]
        continuity_notes = _dedupe_preserve_order(
            [value for value in tail_fragments if value]
            + [value for value in open_threads[:2] if value]
        )[:RECAP_MAX_CONTINUITY_ITEMS]
        summary = _compose_summary_sentences(
            chronology[:3] + important_facts[:2] + decisions[:1] + continuity_notes[:1],
            max_sentences=4,
            max_chars=560,
        )
        return {
            "window_index": int(window.get("window_index") or 1),
            "slice_range": str(window.get("slice_range") or ""),
            "summary": summary,
            "key_beats": chronology,
            "important_facts": important_facts,
            "evidence_gaps": evidence_gaps,
            "decisions": decisions,
            "tasks": tasks,
            "open_threads": open_threads,
            "rulings": rulings,
            "follow_ups": follow_ups,
            "continuity_notes": continuity_notes,
        }

    def _build_window_dossier_payload(
        self,
        window_payload: dict,
    ) -> dict:
        return {
            "window_index": int(window_payload.get("window_index") or 1),
            "slice_range": str(window_payload.get("slice_range") or ""),
            "summary": _normalize_line_item(str(window_payload.get("summary") or ""), max_chars=480),
            "anchors": self._normalize_json_list(window_payload, "anchors")[:RECAP_MAX_FACT_ITEMS],
            "key_beats": self._normalize_json_list(window_payload, "key_beats")[:RECAP_MAX_CHRONOLOGY_ITEMS],
            "important_facts": self._normalize_json_list(window_payload, "important_facts")[:RECAP_MAX_FACT_ITEMS],
            "evidence_gaps": self._normalize_json_list(window_payload, "evidence_gaps")[:RECAP_MAX_RULING_ITEMS],
            "decisions": self._normalize_json_list(window_payload, "decisions")[:RECAP_MAX_DECISION_ITEMS],
            "tasks": self._normalize_json_list(window_payload, "tasks")[:RECAP_MAX_TASK_ITEMS],
            "open_threads": self._normalize_json_list(window_payload, "open_threads")[:RECAP_MAX_OPEN_THREAD_ITEMS],
            "rulings": self._normalize_json_list(window_payload, "rulings")[:RECAP_MAX_RULING_ITEMS],
            "follow_ups": self._normalize_json_list(window_payload, "follow_ups")[:RECAP_MAX_FOLLOW_UP_ITEMS],
            "continuity_notes": self._normalize_json_list(window_payload, "continuity_notes")[:RECAP_MAX_CONTINUITY_ITEMS],
            "scene_paragraphs": self._normalize_json_list(window_payload, "scene_paragraphs")[:8],
        }

    def _format_window_dossier_text(self, dossier: dict) -> str:
        sections = [
            f"### Window {int(dossier.get('window_index') or 1)}",
            f"Slice Range: {dossier.get('slice_range', '')}",
            "",
            "Summary:",
            str(dossier.get("summary") or "No concise summary produced."),
            "",
        ]
        section_map = (
            ("Scene Paragraphs", dossier.get("scene_paragraphs", [])),
            ("Anchors", dossier.get("anchors", [])),
            ("Key Beats", dossier.get("key_beats", [])),
            ("Important Facts", dossier.get("important_facts", [])),
            ("Decisions", dossier.get("decisions", [])),
            ("Tasks", dossier.get("tasks", [])),
            ("Open Threads", dossier.get("open_threads", [])),
            ("Rulings", dossier.get("rulings", [])),
            ("Follow Ups", dossier.get("follow_ups", [])),
            ("Continuity Notes", dossier.get("continuity_notes", [])),
            ("Evidence Gaps", dossier.get("evidence_gaps", [])),
        )
        for title, items in section_map:
            values = list(items or [])
            if not values:
                continue
            sections.append(f"{title}:")
            sections.extend(f"- {item}" for item in values)
            sections.append("")
        return "\n".join(sections).strip()

    def _build_coverage_card_payload(self, dossier: dict) -> dict:
        return {
            "window_index": int(dossier.get("window_index") or 1),
            "decisions": _dedupe_preserve_order(list(dossier.get("decisions", [])))[:14],
            "tasks": _dedupe_preserve_order(list(dossier.get("tasks", [])))[:14],
            "open_threads": _dedupe_preserve_order(list(dossier.get("open_threads", [])))[:14],
            "important_facts": _dedupe_preserve_order(
                list(dossier.get("important_facts", [])) + list(dossier.get("rulings", []))
            )[:18],
        }

    def _format_coverage_card_text(self, payload: dict) -> str:
        sections = [f"### Coverage Window {int(payload.get('window_index') or 1)}", ""]
        for title, key in (
            ("Decisions", "decisions"),
            ("Tasks", "tasks"),
            ("Open Threads", "open_threads"),
            ("Important Facts", "important_facts"),
        ):
            values = list(payload.get(key, []))
            if not values:
                continue
            sections.append(f"{title}:")
            sections.extend(f"- {item}" for item in values)
            sections.append("")
        return "\n".join(sections).strip()

    def _investigate_window(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        window: dict[str, object],
        *,
        total_windows: int,
    ) -> tuple[dict[str, object], dict[str, object]]:
        window_index = int(window.get("window_index") or 1)
        window_payload = self._window_model_chain_analysis(active_store, host, model, window)
        chronology_payload = {
            "summary": str(window_payload.get("summary") or ""),
            "key_beats": list(window_payload.get("key_beats", [])),
            "important_facts": list(window_payload.get("important_facts", [])),
            "evidence_gaps": list(window_payload.get("evidence_gaps", [])),
        }
        active_store.save_recap_json_artifact(
            f"investigations/window_{window_index:04d}_chronology.json",
            chronology_payload,
        )
        commitments_payload = {
            "decisions": list(window_payload.get("decisions", [])),
            "tasks": list(window_payload.get("tasks", [])),
            "open_threads": list(window_payload.get("open_threads", [])),
            "rulings": list(window_payload.get("rulings", [])),
            "follow_ups": list(window_payload.get("follow_ups", [])),
            "continuity_notes": list(window_payload.get("continuity_notes", [])),
        }
        active_store.save_recap_json_artifact(
            f"investigations/window_{window_index:04d}_commitments.json",
            commitments_payload,
        )
        dossier_payload = self._build_window_dossier_payload(window_payload)
        active_store.save_recap_json_artifact(f"dossiers/window_{window_index:04d}.json", dossier_payload)
        dossier_text = self._format_window_dossier_text(dossier_payload)
        active_store.save_recap_artifact(f"dossiers/window_{window_index:04d}.md", dossier_text)
        coverage_payload = self._build_coverage_card_payload(dossier_payload)
        active_store.save_recap_json_artifact(f"coverage/window_{window_index:04d}.json", coverage_payload)
        coverage_text = self._format_coverage_card_text(coverage_payload)
        active_store.save_recap_artifact(f"coverage/window_{window_index:04d}.md", coverage_text)
        return (
            {
                "title": f"Window {window_index}",
                "payload": dossier_payload,
                "text": dossier_text,
                "estimated_tokens": _estimate_text_tokens(dossier_text),
            },
            {
                "title": f"Coverage {window_index}",
                "payload": coverage_payload,
                "text": coverage_text,
                "estimated_tokens": _estimate_text_tokens(coverage_text),
            },
        )

    def _pack_documents_by_budget(
        self,
        documents: list[dict[str, object]],
        *,
        max_tokens: int,
    ) -> list[list[dict[str, object]]]:
        groups: list[list[dict[str, object]]] = []
        current_group: list[dict[str, object]] = []
        current_tokens = 0
        for document in documents:
            text = str(document.get("text") or "").strip()
            doc_tokens = max(1, int(document.get("estimated_tokens") or _estimate_text_tokens(text)))
            if current_group and current_tokens + doc_tokens > max_tokens:
                groups.append(current_group)
                current_group = []
                current_tokens = 0
            current_group.append(document)
            current_tokens += doc_tokens
        if current_group:
            groups.append(current_group)
        return groups

    def _build_narrative_brief_payload(self, payload: dict) -> dict:
        return {
            "summary": _normalize_line_item(str(payload.get("summary") or ""), max_chars=520),
            "scene_paragraphs": self._normalize_json_list(payload, "scene_paragraphs")[:10],
            "anchors": self._normalize_json_list(payload, "anchors")[:14],
            "key_beats": self._normalize_json_list(payload, "key_beats")[:16],
            "decisions": self._normalize_json_list(payload, "decisions")[:16],
            "tasks": self._normalize_json_list(payload, "tasks")[:16],
            "open_threads": self._normalize_json_list(payload, "open_threads")[:16],
            "continuity_notes": self._normalize_json_list(payload, "continuity_notes")[:12],
            "important_facts": self._normalize_json_list(payload, "important_facts")[:18],
        }

    def _format_narrative_brief_text(self, payload: dict, *, title: str) -> str:
        sections = [f"### {title}", "", "Summary:", str(payload.get("summary") or ""), ""]
        for section_title, key in (
            ("Scene Paragraphs", "scene_paragraphs"),
            ("Anchors", "anchors"),
            ("Key Beats", "key_beats"),
            ("Important Facts", "important_facts"),
            ("Decisions", "decisions"),
            ("Tasks", "tasks"),
            ("Open Threads", "open_threads"),
            ("Continuity Notes", "continuity_notes"),
        ):
            values = list(payload.get(key, []))
            if not values:
                continue
            sections.append(f"{section_title}:")
            sections.extend(f"- {item}" for item in values)
            sections.append("")
        return "\n".join(sections).strip()

    def _build_coverage_brief_payload(self, payload: dict) -> dict:
        return {
            "decisions": self._normalize_json_list(payload, "decisions")[:24],
            "tasks": self._normalize_json_list(payload, "tasks")[:24],
            "open_threads": self._normalize_json_list(payload, "open_threads")[:24],
            "important_facts": self._normalize_json_list(payload, "important_facts")[:28],
        }

    def _format_coverage_brief_text(self, payload: dict, *, title: str) -> str:
        sections = [f"### {title}", ""]
        for section_title, key in (
            ("Decisions", "decisions"),
            ("Tasks", "tasks"),
            ("Open Threads", "open_threads"),
            ("Important Facts", "important_facts"),
        ):
            values = list(payload.get(key, []))
            if not values:
                continue
            sections.append(f"{section_title}:")
            sections.extend(f"- {item}" for item in values)
            sections.append("")
        return "\n".join(sections).strip()

    def _merge_narrative_payloads(self, payloads: list[dict]) -> dict:
        merged = {
            "summary": "",
            "scene_paragraphs": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "scene_paragraphs")]
            )[:10],
            "anchors": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "anchors")]
            )[:14],
            "key_beats": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "key_beats")]
            )[:18],
            "important_facts": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "important_facts")]
            )[:20],
            "decisions": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "decisions")]
            )[:18],
            "tasks": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "tasks")]
            )[:18],
            "open_threads": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "open_threads")]
            )[:18],
            "continuity_notes": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "continuity_notes")]
            )[:14],
        }
        summary_candidates = [
            str(payload.get("summary") or "")
            for payload in payloads
            if str(payload.get("summary") or "").strip()
        ]
        merged["summary"] = _compose_summary_sentences(
            summary_candidates
            + merged["scene_paragraphs"][:2]
            + merged["anchors"][:2]
            + merged["key_beats"][:3]
            + merged["important_facts"][:2]
            + merged["decisions"][:1]
            + merged["continuity_notes"][:1],
            max_sentences=4,
            max_chars=620,
        )
        return self._build_narrative_brief_payload(merged)

    def _merge_coverage_payloads(self, payloads: list[dict]) -> dict:
        merged = {
            "decisions": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "decisions")]
            )[:28],
            "tasks": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "tasks")]
            )[:28],
            "open_threads": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "open_threads")]
            )[:28],
            "important_facts": _dedupe_preserve_order(
                [item for payload in payloads for item in self._normalize_json_list(payload, "important_facts")]
            )[:32],
        }
        return self._build_coverage_brief_payload(merged)

    def _reduce_narrative_documents(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        documents: list[dict[str, object]],
        *,
        generation: Optional[int],
    ) -> tuple[dict[str, object], int]:
        if not documents:
            raise RuntimeError("Narrative reduction received no documents.")
        round_index = 0
        current_documents = list(documents)
        while len(current_documents) > 1:
            self._ensure_recap_generation_active(active_store, generation)
            round_index += 1
            next_documents: list[dict[str, object]] = []
            for group_index, group in enumerate(
                self._pack_documents_by_budget(current_documents, max_tokens=RECAP_SEGMENT_BUNDLE_TOKENS),
                start=1,
            ):
                payload = self._merge_narrative_payloads([dict(item.get("payload") or {}) for item in group])
                active_store.save_recap_json_artifact(
                    f"merge_rounds/narrative_round_{round_index:02d}_group_{group_index:02d}.json",
                    payload,
                )
                text = self._format_narrative_brief_text(
                    payload,
                    title=f"Narrative Brief R{round_index}G{group_index}",
                )
                active_store.save_recap_artifact(
                    f"merge_rounds/narrative_round_{round_index:02d}_group_{group_index:02d}.md",
                    text,
                )
                next_documents.append(
                    {
                        "title": f"Narrative Brief R{round_index}G{group_index}",
                        "payload": payload,
                        "text": text,
                        "estimated_tokens": _estimate_text_tokens(text),
                    }
                )
            current_documents = next_documents
            active_store.update_recap_progress(merge_rounds=round_index)
        return current_documents[0], round_index

    def _reduce_coverage_documents(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        documents: list[dict[str, object]],
        *,
        generation: Optional[int],
    ) -> tuple[dict[str, object], int]:
        if not documents:
            raise RuntimeError("Coverage reduction received no documents.")
        round_index = 0
        current_documents = list(documents)
        while len(current_documents) > 1:
            self._ensure_recap_generation_active(active_store, generation)
            round_index += 1
            next_documents: list[dict[str, object]] = []
            for group_index, group in enumerate(
                self._pack_documents_by_budget(current_documents, max_tokens=RECAP_COVERAGE_BUNDLE_TOKENS),
                start=1,
            ):
                payload = self._merge_coverage_payloads([dict(item.get("payload") or {}) for item in group])
                active_store.save_recap_json_artifact(
                    f"merge_rounds/coverage_round_{round_index:02d}_group_{group_index:02d}.json",
                    payload,
                )
                text = self._format_coverage_brief_text(
                    payload,
                    title=f"Coverage Brief R{round_index}G{group_index}",
                )
                active_store.save_recap_artifact(
                    f"merge_rounds/coverage_round_{round_index:02d}_group_{group_index:02d}.md",
                    text,
                )
                next_documents.append(
                    {
                        "title": f"Coverage Brief R{round_index}G{group_index}",
                        "payload": payload,
                        "text": text,
                        "estimated_tokens": _estimate_text_tokens(text),
                    }
                )
            current_documents = next_documents
            active_store.update_recap_progress(merge_rounds=round_index)
        return current_documents[0], round_index

    def _sanitize_model_summary(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", str(text or "").strip()).strip()
        if _is_low_signal_recap_text(cleaned):
            return ""
        cleaned = re.sub(r"^#+\s*", "", cleaned).strip()
        cleaned = re.sub(r"^(summary|session recap)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
        if _is_low_signal_recap_text(cleaned):
            return ""
        return _normalize_line_item(cleaned, max_chars=780)

    def _deterministic_final_summary(self, narrative_doc: dict[str, object], coverage_doc: dict[str, object]) -> str:
        narrative_payload = dict(narrative_doc.get("payload") or {})
        coverage_payload = dict(coverage_doc.get("payload") or {})
        candidates = [
            *self._normalize_json_list(narrative_payload, "key_beats")[:3],
            *self._normalize_json_list(narrative_payload, "important_facts")[:2],
            *self._normalize_json_list(narrative_payload, "decisions")[:1],
            *self._normalize_json_list(coverage_payload, "open_threads")[:1],
            *self._normalize_json_list(narrative_payload, "continuity_notes")[:1],
        ]
        summary = _compose_summary_sentences(candidates, max_sentences=4, max_chars=760)
        return summary or "The session recap is available below."

    def _select_recap_sentences(
        self,
        values: list[str],
        *,
        max_count: int,
        allow_questions: bool = False,
    ) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()
        for value in values:
            sentence = _ensure_sentence(value, max_chars=320)
            if not sentence or _is_low_signal_recap_text(sentence):
                continue
            if not allow_questions and sentence.endswith("?"):
                continue
            normalized = _strip_sentence_ending(sentence).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            selected.append(sentence)
            if len(selected) >= max_count:
                break
        return selected

    def _compose_recap_body(self, narrative_doc: dict[str, object], coverage_doc: dict[str, object], summary: str) -> str:
        narrative_payload = dict(narrative_doc.get("payload") or {})
        coverage_payload = dict(coverage_doc.get("payload") or {})

        chronology = self._select_recap_sentences(
            self._normalize_json_list(narrative_payload, "key_beats")
            + self._normalize_json_list(narrative_payload, "important_facts"),
            max_count=5,
        )
        decisions = self._select_recap_sentences(
            self._normalize_json_list(narrative_payload, "decisions")
            + self._normalize_json_list(coverage_payload, "decisions"),
            max_count=3,
        )
        tasks = self._select_recap_sentences(
            self._normalize_json_list(narrative_payload, "tasks")
            + self._normalize_json_list(coverage_payload, "tasks"),
            max_count=3,
        )
        open_threads = self._select_recap_sentences(
            self._normalize_json_list(narrative_payload, "open_threads")
            + self._normalize_json_list(coverage_payload, "open_threads"),
            max_count=3,
            allow_questions=True,
        )
        continuity = self._select_recap_sentences(
            self._normalize_json_list(narrative_payload, "continuity_notes"),
            max_count=3,
        )

        paragraphs: list[str] = [summary]

        middle_candidates = chronology[1:4] + decisions[:2] + tasks[:1]
        middle = _compose_summary_sentences(middle_candidates, max_sentences=4, max_chars=760)
        if middle and middle.casefold() != summary.casefold():
            paragraphs.append(middle)

        closing_candidates = continuity[:2] + tasks[1:3] + open_threads[:2]
        closing = _compose_summary_sentences(closing_candidates, max_sentences=4, max_chars=760)
        if not closing and open_threads:
            closing = _compose_summary_sentences(open_threads, max_sentences=2, max_chars=420)
        if closing and all(closing.casefold() != paragraph.casefold() for paragraph in paragraphs):
            paragraphs.append(closing)

        return "\n\n".join(paragraph for paragraph in paragraphs if paragraph.strip()).strip()

    def _build_final_recap_draft(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> tuple[str, list[str]]:
        keep_points = self._select_session_keep_points(active_store, host, model, narrative_doc, coverage_doc)
        paragraphs = self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name="final_draft",
            system_prompt=self._final_recap_system_prompt(),
            user_prompt=self._build_final_draft_prompt(narrative_doc, coverage_doc, keep_points),
            format_requirements=(
                "Return exactly 2 or 3 lines in this format:\n"
                "P1: <paragraph>\n"
                "P2: <paragraph>\n"
                "Optional P3: <paragraph>\n"
                "Each paragraph must be prose and not bullets."
            ),
            parser=self._parse_and_validate_final_recap,
            num_predict=420,
        )
        return "\n\n".join(paragraphs).strip(), keep_points

    def _parse_and_validate_final_recap(
        self,
        raw: str,
    ) -> tuple[bool, list[str], str]:
        ok, paragraphs, error_message = _parse_paragraph_lines_response(raw)
        if not ok:
            return False, [], error_message
        valid, validation_error = self._validate_final_recap_paragraphs(paragraphs)
        if not valid:
            return False, [], validation_error
        return True, paragraphs, ""

    def _build_final_audit_prompt(
        self,
        final_draft: str,
        keep_points: list[str],
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> str:
        narrative_payload = dict(narrative_doc.get("payload") or {})
        coverage_payload = dict(coverage_doc.get("payload") or {})
        sections = [
            f"Session: {self._session_name or 'Unnamed Session'}",
            "",
            "Final Recap:",
            final_draft.strip(),
            "",
            "Required Facts:",
        ]
        for value in self._ordered_session_points(
            keep_points + self._normalize_json_list(narrative_payload, "anchors")[-6:],
            limit=10,
        ):
            sections.append(f"- {value}")
        sections.extend(("", "Unresolved Hooks:"))
        for value in self._ordered_session_points(
            (self._normalize_json_list(narrative_payload, "open_threads")
            + self._normalize_json_list(coverage_payload, "open_threads"))[-4:],
            limit=4,
        ):
            sections.append(f"- {value}")
        sections.extend(("", "Ending State:"))
        for value in self._ordered_session_points(
            self._normalize_json_list(narrative_payload, "continuity_notes")[-4:],
            limit=4,
        ):
            sections.append(f"- {value}")
        return "\n".join(sections).strip()

    def _audit_final_recap_stage(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        *,
        stage_name: str,
        final_draft: str,
        keep_points: list[str],
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> dict[str, object]:
        return self._run_validated_recap_stage(
            active_store,
            host,
            model,
            stage_name=stage_name,
            system_prompt=self._final_recap_audit_system_prompt(),
            user_prompt=self._build_final_audit_prompt(final_draft, keep_points, narrative_doc, coverage_doc),
            format_requirements=(
                "Return either exactly 'STATUS: pass' or 'STATUS: fail' followed by one or more 'MISSING: ' lines."
            ),
            parser=_parse_status_missing_response,
            num_predict=220,
        )

    def _audit_final_recap(
        self,
        active_store: SessionTranscriptStore,
        host: str,
        model: str,
        final_draft: str,
        keep_points: list[str],
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> str:
        active_text = str(final_draft or "").strip()
        for round_index in range(1, 3):
            audit = self._audit_final_recap_stage(
                active_store,
                host,
                model,
                stage_name=f"final_audit_round_{round_index:02d}",
                final_draft=active_text,
                keep_points=keep_points,
                narrative_doc=narrative_doc,
                coverage_doc=coverage_doc,
            )
            if str(audit.get("status") or "") == "pass":
                return self._compose_final_recap_markdown(active_text, narrative_doc, coverage_doc)
            missing = list(audit.get("missing") or [])
            active_text = "\n\n".join(
                self._run_validated_recap_stage(
                    active_store,
                    host,
                    model,
                    stage_name=f"final_repair_round_{round_index:02d}",
                    system_prompt=self._final_recap_system_prompt(),
                    user_prompt=self._build_final_draft_prompt(
                        narrative_doc,
                        coverage_doc,
                        keep_points,
                        missing_points=missing,
                    ),
                    format_requirements=(
                        "Return exactly 2 or 3 lines in this format:\n"
                        "P1: <paragraph>\n"
                        "P2: <paragraph>\n"
                        "Optional P3: <paragraph>"
                    ),
                    parser=self._parse_and_validate_final_recap,
                    num_predict=420,
                )
            ).strip()
        raise RuntimeError("Final recap audit still failed after 2 repair attempts.")

    def _compose_final_recap_markdown(
        self,
        final_draft: str,
        narrative_doc: dict[str, object],
        coverage_doc: dict[str, object],
    ) -> str:
        body = _normalize_model_output(final_draft)
        if not body:
            raise RuntimeError("Final recap draft was empty after validation.")
        return "\n\n".join(("## Session Recap", body)).strip()


class TranscriptSessionPanel(QWidget):
    def __init__(self, controller: TranscriptSessionController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._syncing_fields = False
        self._editor_loading = False
        self._editor_dirty = False
        self._bound_session_dir = ""
        self._mic_devices: list[AudioInputDescriptor] = []
        self._system_devices: list[AudioInputDescriptor] = []
        self._init_ui()
        self._controller.stateChanged.connect(self._refresh_from_controller)
        self._controller.transcriptChanged.connect(self._on_transcript_changed)
        self._refresh_runtime_fields()
        self._refresh_from_controller()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        config_group = QGroupBox("Transcript Capture")
        config_group.setObjectName("TransparentContainer")
        config_group_layout = QVBoxLayout(config_group)
        config_group_layout.setContentsMargins(8, 8, 8, 8)
        config_group_layout.setSpacing(8)

        config_header_row = QWidget(config_group)
        config_header_row.setObjectName("TransparentContainer")
        config_header_layout = QHBoxLayout(config_header_row)
        config_header_layout.setContentsMargins(0, 0, 0, 0)
        config_header_layout.setSpacing(0)
        config_header_layout.addStretch(1)

        config_form_host = QWidget(config_group)
        config_form_host.setObjectName("TransparentContainer")
        config_layout = QFormLayout(config_form_host)
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(8)
        config_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.source_mode_combo = QComboBox(config_group)
        self.source_mode_combo.addItem("Mic Only", "mic")
        self.source_mode_combo.addItem("System Audio Only", "system")
        self.source_mode_combo.addItem("Mic + System Audio", "mixed")
        self.source_mode_combo.setFixedHeight(FIELD_HEIGHT)
        self.source_mode_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.source_mode_combo.currentIndexChanged.connect(self._on_capture_preferences_changed)
        config_layout.addRow("Source Mode", self.source_mode_combo)

        self.import_source_combo = QComboBox(config_group)
        self.import_source_combo.addItem("Mic", "mic")
        self.import_source_combo.addItem("System", "system")
        self.import_source_combo.setFixedHeight(FIELD_HEIGHT)
        self.import_source_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        config_layout.addRow("Import As", self.import_source_combo)

        self.audio_note_label = _make_hint_label(
            "",
            config_group,
        )
        self.audio_note_label.setVisible(False)
        self.refresh_devices_btn = _make_icon_tool_button(
            config_group,
            "reset.svg",
            "Refresh devices",
            object_name="SecondaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.refresh_devices_btn.clicked.connect(self._refresh_audio_devices)
        config_header_layout.addWidget(self.refresh_devices_btn, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

        self.mic_device_combo = QComboBox(config_group)
        self.mic_device_combo.setFixedHeight(FIELD_HEIGHT)
        self.mic_device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.mic_device_combo.currentIndexChanged.connect(self._on_capture_preferences_changed)
        config_layout.addRow("Mic Input", self.mic_device_combo)

        self.system_device_combo = QComboBox(config_group)
        self.system_device_combo.setFixedHeight(FIELD_HEIGHT)
        self.system_device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.system_device_combo.currentIndexChanged.connect(self._on_capture_preferences_changed)
        config_layout.addRow("System Input", self.system_device_combo)
        config_layout.addRow("", self.audio_note_label)

        config_group_layout.addWidget(config_header_row)
        config_group_layout.addWidget(config_form_host)
        layout.addWidget(config_group)

        control_row = QWidget(self)
        control_row.setObjectName("TransparentContainer")
        control_row.setMinimumHeight(ACTION_ROW_HEIGHT)
        control_layout = QHBoxLayout(control_row)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)
        self.start_btn = _make_icon_tool_button(
            control_row,
            "ping.svg",
            "Start capture",
            object_name="PrimaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.start_btn.clicked.connect(self._toggle_capture)
        self.halt_btn = _make_icon_tool_button(control_row, "stop.svg", "Stop", object_name="DestructiveButton")
        self.halt_btn.clicked.connect(self._halt_processing)
        self.halt_btn.setVisible(False)
        self.import_btn = _make_icon_tool_button(
            control_row,
            "folder_open.svg",
            "Import audio",
            object_name="SecondaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.import_btn.clicked.connect(self._import_audio)
        self.run_pending_btn = _make_icon_tool_button(
            control_row,
            "play.svg",
            "Transcribe pending",
            object_name="SecondaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.run_pending_btn.clicked.connect(lambda: self._controller.request_processing(run_recap=False))
        self.retry_failed_btn = _make_icon_tool_button(
            control_row,
            "redo.svg",
            "Retry failed",
            object_name="SecondaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.retry_failed_btn.clicked.connect(self._controller.retry_failed_chunks)
        control_layout.addWidget(self.start_btn)
        control_layout.addWidget(self.import_btn)
        control_layout.addWidget(self.run_pending_btn)
        control_layout.addWidget(self.retry_failed_btn)
        control_layout.addStretch(1)
        self.editor_state_label = _make_hint_label("Edit transcript text here.", control_row)
        self.editor_state_label.setVisible(False)
        control_layout.addWidget(self.editor_state_label, 1, Qt.AlignmentFlag.AlignVCenter)
        self.save_editor_btn = _make_icon_tool_button(
            control_row,
            "save.svg",
            "Save transcript text",
            object_name="PrimaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.save_editor_btn.clicked.connect(self._save_editor_text)
        self.reload_editor_btn = _make_icon_tool_button(
            control_row,
            "undo.svg",
            "Discard editor changes",
            object_name="SecondaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.reload_editor_btn.clicked.connect(self._reload_editor_text)
        self.use_generated_btn = _make_icon_tool_button(
            control_row,
            "reset.svg",
            "Use generated transcript",
            object_name="SecondaryButton",
            button_size=ACTION_TEXT_BUTTON_HEIGHT,
        )
        self.use_generated_btn.clicked.connect(self._use_generated_transcript)
        control_layout.addWidget(self.save_editor_btn)
        control_layout.addWidget(self.reload_editor_btn)
        control_layout.addWidget(self.use_generated_btn)
        layout.addWidget(control_row)

        self.status_label = _make_hint_label("Create or select a session first.", self)
        layout.addWidget(self.status_label)

        self.event_label = _make_hint_label("", self)
        self.event_label.setVisible(False)
        layout.addWidget(self.event_label)

        self.transcript_editor = QPlainTextEdit(self)
        self.transcript_editor.setReadOnly(False)
        self.transcript_editor.setPlaceholderText("Paste or edit transcript text here.")
        self.transcript_editor.textChanged.connect(self._on_editor_text_changed)
        layout.addWidget(self.transcript_editor, 1)

        self._populate_device_combo(self.mic_device_combo, [], "Refresh audio devices")
        self._populate_device_combo(self.system_device_combo, [], "Refresh audio devices")

    def _save_runtime_settings(self) -> None:
        if self._syncing_fields:
            return
        self._controller.update_runtime_settings(
            "",
            "",
            self._controller.snapshot().get("runtime", {}).get("ollama_host", DEFAULT_OLLAMA_HOST),
            self._controller.snapshot().get("runtime", {}).get("ollama_model", DEFAULT_OLLAMA_MODEL),
        )

    def _refresh_runtime_fields(self) -> None:
        return

    def _refresh_audio_devices(self, *, show_error: bool = True) -> None:
        mic_devices, mic_error = self._controller.list_mic_inputs(force_refresh=True)
        system_devices, system_error = self._controller.list_system_audio_inputs(force_refresh=True)
        self._mic_devices = mic_devices
        self._system_devices = system_devices
        snapshot = self._controller.snapshot()
        capture_devices = snapshot.get("capture_devices", {})
        selected_mic_id = str(capture_devices.get("mic_id") or "")
        selected_system_id = str(capture_devices.get("system_id") or "") or self._controller.suggest_system_audio_device_id()
        self._populate_device_combo(
            self.mic_device_combo,
            mic_devices,
            "No microphone inputs detected",
            selected_id=selected_mic_id,
        )
        self._populate_device_combo(
            self.system_device_combo,
            system_devices,
            "No system audio inputs detected",
            selected_id=selected_system_id,
        )
        error_message = "\n".join(message for message in (mic_error, system_error) if message)
        if error_message and show_error:
            QMessageBox.warning(self, "Audio Devices", error_message)
        self._on_capture_preferences_changed()
        self._refresh_from_controller()

    def _populate_device_combo(
        self,
        combo: QComboBox,
        devices: list[AudioInputDescriptor],
        empty_label: str,
        *,
        selected_id: str = "",
    ) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(empty_label, "")
        target_id = str(selected_id or "").strip()
        target_index = 0
        for index, device in enumerate(devices, start=1):
            combo.addItem(device.name, device.device_id)
            if target_id and device.device_id == target_id:
                target_index = index
        combo.setCurrentIndex(target_index)
        combo.blockSignals(False)

    def _current_device_name(self, combo: QComboBox) -> str:
        current_index = combo.currentIndex()
        if current_index < 0:
            return ""
        return str(combo.currentText() or "").strip()

    def _on_capture_preferences_changed(self) -> None:
        snapshot = self._controller.snapshot()
        if not snapshot.get("has_session"):
            return
        self._controller.update_capture_preferences(
            str(self.source_mode_combo.currentData() or DEFAULT_SOURCE_MODE),
            mic_id=str(self.mic_device_combo.currentData() or ""),
            mic_name=self._current_device_name(self.mic_device_combo),
            system_id=str(self.system_device_combo.currentData() or ""),
            system_name=self._current_device_name(self.system_device_combo),
        )

    def _start_capture(self) -> None:
        self._save_runtime_settings()
        self._controller.start_capture(
            str(self.source_mode_combo.currentData() or DEFAULT_SOURCE_MODE),
            mic_id=str(self.mic_device_combo.currentData() or ""),
            mic_name=self._current_device_name(self.mic_device_combo),
            system_id=str(self.system_device_combo.currentData() or ""),
            system_name=self._current_device_name(self.system_device_combo),
        )

    def _toggle_capture(self) -> None:
        if bool(self._controller.snapshot().get("recording")):
            self._halt_processing()
            return
        self._start_capture()

    def _halt_processing(self) -> None:
        self._controller.halt()

    def _import_audio(self) -> None:
        snapshot = self._controller.snapshot()
        if not snapshot.get("has_session"):
            QMessageBox.information(self, "No Session Selected", "Create or select a session first.")
            return
        start_dir = str(Path.home())
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Import Audio Files",
            start_dir,
            "Audio Files (*.wav *.mp3 *.flac *.m4a *.ogg *.aac);;All Files (*)",
        )
        if not paths:
            return
        self._controller.import_audio_files(paths, str(self.import_source_combo.currentData() or "mic"))

    def _load_editor_text(self, text: str) -> None:
        self._editor_loading = True
        try:
            self.transcript_editor.setPlainText(str(text or ""))
        finally:
            self._editor_loading = False
        self._editor_dirty = False
        self._update_editor_action_state()

    def _on_editor_text_changed(self) -> None:
        if self._editor_loading:
            return
        self._editor_dirty = True
        self._update_editor_action_state()

    def _save_editor_text(self) -> None:
        snapshot = self._controller.snapshot()
        if not snapshot.get("has_session"):
            return
        self._controller.save_manual_transcript(self.transcript_editor.toPlainText())
        self._load_editor_text(self._controller.transcript_text())

    def _reload_editor_text(self) -> None:
        self._load_editor_text(self._controller.transcript_text())

    def _use_generated_transcript(self) -> None:
        self._controller.clear_manual_transcript()
        self._load_editor_text(self._controller.transcript_text())

    def _update_editor_action_state(self) -> None:
        snapshot = self._controller.snapshot()
        has_session = bool(snapshot.get("has_session"))
        manual_meta = snapshot.get("manual_transcript", {})
        generated_text = self._controller.generated_transcript_text() if has_session else ""
        self.save_editor_btn.setEnabled(has_session and self._editor_dirty)
        self.reload_editor_btn.setEnabled(has_session and self._editor_dirty)
        self.use_generated_btn.setEnabled(
            has_session and (bool(manual_meta.get("enabled")) or bool(generated_text.strip()))
        )
        if not has_session:
            self.editor_state_label.setText("")
            self.editor_state_label.setVisible(False)
            return
        if self._editor_dirty:
            self.editor_state_label.setText("Unsaved transcript edits")
            self.editor_state_label.setVisible(True)
        else:
            self.editor_state_label.setText("")
            self.editor_state_label.setVisible(False)

    def _on_transcript_changed(self, text: str) -> None:
        current_text = self.transcript_editor.toPlainText()
        if current_text == str(text or ""):
            return
        if self._editor_dirty:
            self._update_editor_action_state()
            return
        self._load_editor_text(str(text or ""))

    def _refresh_from_controller(self) -> None:
        snapshot = self._controller.snapshot()
        self._refresh_runtime_fields()
        has_session = bool(snapshot.get("has_session"))
        counts = snapshot.get("counts", {})
        state = str(snapshot.get("state") or "idle")
        manual_meta = snapshot.get("manual_transcript", {})
        recap = snapshot.get("recap", {})
        last_event = snapshot.get("last_event", {})
        capture_devices = snapshot.get("capture_devices", {})
        session_dir = str(snapshot.get("session_dir") or "")
        if has_session and not self._mic_devices and not self._system_devices:
            self._refresh_audio_devices(show_error=False)
            snapshot = self._controller.snapshot()
            capture_devices = snapshot.get("capture_devices", {})
            manual_meta = snapshot.get("manual_transcript", {})
            session_dir = str(snapshot.get("session_dir") or "")
        if session_dir != self._bound_session_dir:
            self._bound_session_dir = session_dir
            self._load_editor_text(self._controller.transcript_text())
        self._syncing_fields = True
        try:
            source_mode = str(snapshot.get("source_mode") or DEFAULT_SOURCE_MODE)
            index = self.source_mode_combo.findData(source_mode)
            if index >= 0:
                self.source_mode_combo.setCurrentIndex(index)
        finally:
            self._syncing_fields = False
        if self._mic_devices or self._system_devices:
            self._populate_device_combo(
                self.mic_device_combo,
                self._mic_devices,
                "No microphone inputs detected",
                selected_id=str(capture_devices.get("mic_id") or ""),
            )
            self._populate_device_combo(
                self.system_device_combo,
                self._system_devices,
                "No system audio inputs detected",
                selected_id=str(capture_devices.get("system_id") or ""),
            )
        controls_enabled = has_session
        for widget in (
            self.source_mode_combo,
            self.import_source_combo,
            self.refresh_devices_btn,
            self.mic_device_combo,
            self.system_device_combo,
            self.start_btn,
            self.halt_btn,
            self.import_btn,
            self.run_pending_btn,
            self.retry_failed_btn,
            self.save_editor_btn,
            self.reload_editor_btn,
            self.use_generated_btn,
            self.transcript_editor,
        ):
            widget.setEnabled(controls_enabled)
        selected_mode = str(self.source_mode_combo.currentData() or DEFAULT_SOURCE_MODE)
        needs_mic = selected_mode in {"mic", "mixed"}
        needs_system = selected_mode in {"system", "mixed"}
        has_mic_choice = bool(self.mic_device_combo.currentData())
        has_system_choice = bool(self.system_device_combo.currentData())
        self.start_btn.setEnabled(
            controls_enabled
            and (
                snapshot.get("recording")
                or ((not needs_mic or has_mic_choice) and (not needs_system or has_system_choice))
            )
        )
        self.halt_btn.setEnabled(
            controls_enabled
            and (
                snapshot.get("recording")
                or int(counts.get("pending", 0)) > 0
                or int(counts.get("running", 0)) > 0
                or str(recap.get("status") or "") == "running"
            )
        )
        self.retry_failed_btn.setEnabled(controls_enabled and int(counts.get("failed", 0)) > 0)
        self._update_editor_action_state()
        if not has_session:
            self._bound_session_dir = ""
            self._editor_dirty = False
            self.status_label.setText("Create or select a session first.")
            self.status_label.setVisible(True)
            self.event_label.setText("")
            self.event_label.setVisible(False)
            self._load_editor_text("")
            return
        recording = bool(snapshot.get("recording"))
        _set_icon_tool_button_state(
            self.start_btn,
            "stop.svg" if recording else "ping.svg",
            "Stop capture" if recording else "Start capture",
            object_name="DestructiveButton" if recording else "PrimaryButton",
        )
        status_text = ""
        if recording:
            status_text = "Recording"
        elif int(counts.get("pending", 0)) > 0:
            status_text = f"{int(counts.get('pending', 0))} pending"
        elif int(counts.get("failed", 0)) > 0:
            status_text = f"{int(counts.get('failed', 0))} failed"
        self.status_label.setText(status_text)
        self.status_label.setVisible(bool(status_text))
        event_message = str(last_event.get("message") or "").strip()
        event_level = str(last_event.get("level") or "info").lower()
        if event_level == "error" and event_message and "recap" not in event_message.lower():
            self.event_label.setText(event_message)
            self.event_label.setVisible(True)
        else:
            self.event_label.setText("")
            self.event_label.setVisible(False)
        audio_error = str(snapshot.get("audio_devices_error") or "").strip()
        if audio_error:
            self.audio_note_label.setText(audio_error)
            self.audio_note_label.setVisible(True)
        else:
            self.audio_note_label.setText("")
            self.audio_note_label.setVisible(False)


class RecapSessionPanel(QWidget):
    def __init__(self, controller: TranscriptSessionController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._syncing_fields = False
        self._recap_editor_loading = False
        self._recap_editor_dirty = False
        self._showing_stream_preview = False
        self._recap_save_timer = QTimer(self)
        self._recap_save_timer.setSingleShot(True)
        self._recap_save_timer.setInterval(400)
        self._recap_save_timer.timeout.connect(self._commit_recap_editor_text)
        self._init_ui()
        self._controller.stateChanged.connect(self._refresh_from_controller)
        self._controller.recapChanged.connect(self._on_recap_changed)
        self._controller.recapStreamChanged.connect(self._on_recap_stream_changed)
        self._refresh_runtime_fields()
        self._refresh_from_controller()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        runtime_group = QGroupBox("Local Recap")
        runtime_group.setObjectName("TransparentContainer")
        runtime_layout = QFormLayout(runtime_group)
        runtime_layout.setContentsMargins(8, 8, 8, 8)
        runtime_layout.setSpacing(8)
        runtime_layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.ollama_host_edit = QLineEdit(runtime_group)
        self.ollama_host_edit.setFixedHeight(FIELD_HEIGHT)
        self.ollama_host_edit.setMinimumWidth(0)
        self.ollama_host_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ollama_host_edit.editingFinished.connect(self._save_runtime_settings)
        runtime_layout.addRow("Ollama Host", self.ollama_host_edit)

        self.ollama_model_edit = QLineEdit(runtime_group)
        self.ollama_model_edit.setFixedHeight(FIELD_HEIGHT)
        self.ollama_model_edit.setMinimumWidth(0)
        self.ollama_model_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.ollama_model_edit.editingFinished.connect(self._save_runtime_settings)
        runtime_layout.addRow("Ollama Model", self.ollama_model_edit)

        layout.addWidget(runtime_group)

        buttons_row = QWidget(self)
        buttons_row.setObjectName("TransparentContainer")
        buttons_row.setMinimumHeight(ACTION_ROW_HEIGHT)
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(6)
        buttons_layout.addStretch(1)

        self.generate_btn = _make_action_button(
            buttons_row,
            "add_items.svg",
            "AutoRecap",
            "Generate recap",
            object_name="PrimaryButton",
            minimum_width=148,
        )
        self.generate_btn.clicked.connect(self._toggle_recap)

        buttons_layout.addWidget(self.generate_btn)
        layout.addWidget(buttons_row)

        self.recap_heading_label = _make_section_label("Recap", self)
        self.recap_heading_label.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(self.recap_heading_label)

        self.status_label = _make_hint_label("", self)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        self.recap_editor = QPlainTextEdit(self)
        self.recap_editor.setReadOnly(False)
        self.recap_editor.setPlaceholderText("Generate or write recap text here.")
        self.recap_editor.textChanged.connect(self._on_recap_editor_text_changed)
        layout.addWidget(self.recap_editor, 1)

    def _save_runtime_settings(self) -> None:
        if self._syncing_fields:
            return
        snapshot = self._controller.snapshot()
        runtime = snapshot.get("runtime", {})
        self._controller.update_runtime_settings(
            str(runtime.get("whisper_cli_path") or ""),
            str(runtime.get("whisper_model_path") or ""),
            self.ollama_host_edit.text(),
            self.ollama_model_edit.text(),
        )

    def _refresh_runtime_fields(self) -> None:
        snapshot = self._controller.snapshot()
        runtime = snapshot.get("runtime", {})
        self._syncing_fields = True
        try:
            if not self.ollama_host_edit.hasFocus():
                self.ollama_host_edit.setText(str(runtime.get("ollama_host") or DEFAULT_OLLAMA_HOST))
            if not self.ollama_model_edit.hasFocus():
                self.ollama_model_edit.setText(str(runtime.get("ollama_model") or DEFAULT_OLLAMA_MODEL))
        finally:
            self._syncing_fields = False

    def _on_recap_changed(self, text: str) -> None:
        if self._showing_stream_preview or self._recap_editor_dirty:
            return
        self._load_recap_text(str(text or ""))

    def _on_generate_clicked(self) -> None:
        if self._recap_save_timer.isActive():
            self._recap_save_timer.stop()
            self._commit_recap_editor_text()
        allowed, _, error_message = self._controller.recap_generation_preflight()
        if not allowed:
            QMessageBox.warning(self, "Cannot Auto Generate Recap", error_message)
            return
        self._controller.request_recap()

    def _toggle_recap(self) -> None:
        recap_status = str(self._controller.snapshot().get("recap", {}).get("status") or "idle")
        if recap_status == "running":
            self._controller.halt()
            return
        self._on_generate_clicked()

    def _load_recap_text(self, text: str) -> None:
        self._recap_editor_loading = True
        try:
            self.recap_editor.setPlainText(str(text or ""))
        finally:
            self._recap_editor_loading = False
        self._recap_editor_dirty = False

    @staticmethod
    def _display_recap_body(text: str) -> str:
        clean_text = str(text or "").strip()
        if clean_text.startswith("## "):
            parts = clean_text.split("\n", 2)
            if len(parts) >= 2 and not parts[1].strip():
                return parts[2] if len(parts) >= 3 else ""
        return clean_text

    def _on_recap_editor_text_changed(self) -> None:
        if self._recap_editor_loading or self._showing_stream_preview:
            return
        snapshot = self._controller.snapshot()
        if not bool(snapshot.get("has_session")):
            return
        if str(snapshot.get("recap", {}).get("status") or "idle") == "running":
            return
        self._recap_editor_dirty = True
        self._recap_save_timer.start()

    def _commit_recap_editor_text(self) -> None:
        if self._recap_editor_loading or self._showing_stream_preview:
            return
        snapshot = self._controller.snapshot()
        if not bool(snapshot.get("has_session")):
            return
        if str(snapshot.get("recap", {}).get("status") or "idle") == "running":
            return
        self._controller.save_recap_text(self.recap_editor.toPlainText())
        self._recap_editor_dirty = False

    @staticmethod
    def _extract_stage_section(log_text: str, stage_name: str) -> str:
        clean_log = str(log_text or "")
        clean_stage = str(stage_name or "").strip()
        if not clean_log or not clean_stage:
            return ""
        header = f"=== {clean_stage} ===\n"
        start = clean_log.rfind(header)
        if start < 0:
            return ""
        section = clean_log[start + len(header):]
        next_header = section.find("\n\n=== ")
        if next_header >= 0:
            section = section[:next_header]
        return section.strip()

    @staticmethod
    def _latest_stage_name_from_log(log_text: str) -> str:
        matches = re.findall(r"===\s*([^\n=]+?)\s*===", str(log_text or ""))
        return matches[-1].strip() if matches else ""

    @staticmethod
    def _stream_goal_and_heading(stage_name: str) -> tuple[str, str]:
        clean_stage = str(stage_name or "").strip().lower()
        if clean_stage.startswith("stage1_summary"):
            return "Write the first short recap draft from the transcript.", "Draft Recap"
        if clean_stage.startswith("stage2_refine"):
            return "Refine the draft into the final recap.", "Final Recap"
        return "Work on the current recap.", "Recap"

    @staticmethod
    def _collapse_preview(text: str, *, max_chars: int = 160) -> str:
        clean_text = " ".join(str(text or "").split())
        if len(clean_text) <= max_chars:
            return clean_text
        return clean_text[: max_chars - 1].rstrip() + "…"

    def _render_stream_preview(self, snapshot: dict[str, object]) -> None:
        stage_name = str(snapshot.get("stage_name") or "").strip()
        goal_text, output_heading = self._stream_goal_and_heading(stage_name)
        self.recap_heading_label.setText(output_heading)
        response_text = self._extract_stage_section(str(snapshot.get("response_log") or ""), stage_name)
        thinking_text = self._extract_stage_section(str(snapshot.get("thinking_log") or ""), stage_name)
        message = str(snapshot.get("message") or "").strip()
        stage_one_preview = ""
        if stage_name.startswith("stage2_"):
            draft_text = self._extract_stage_section(str(snapshot.get("response_log") or ""), "stage1_summary_attempt_01")
            if draft_text:
                stage_one_preview = f"Draft recap minimized\n{self._collapse_preview(draft_text)}\n\n"
        if response_text:
            preview_text = f"{stage_one_preview}{response_text}".strip()
        else:
            reasoning_text = thinking_text or message or "Waiting for model output."
            preview_text = (
                f"{stage_one_preview}Current goal\n\n"
                f"{goal_text}\n\n"
                "Reasoning\n\n"
                f"{reasoning_text}"
            ).strip()
        self._showing_stream_preview = True
        self._load_recap_text(preview_text)
        self._showing_stream_preview = True

    def _on_recap_stream_changed(self, payload: object) -> None:
        snapshot = dict(payload or {})
        running = bool(snapshot.get("running"))
        if running:
            self._showing_stream_preview = True
            self._render_stream_preview(snapshot)
            return
        if self._showing_stream_preview:
            self._showing_stream_preview = False
            if not self._recap_editor_dirty:
                recap_text = self._controller.recap_text()
                if recap_text.strip():
                    self.recap_heading_label.setText("Final Recap")
                    self._load_recap_text(self._display_recap_body(recap_text))
                else:
                    response_stage = self._latest_stage_name_from_log(str(snapshot.get("response_log") or ""))
                    if response_stage:
                        halted_snapshot = dict(snapshot)
                        halted_snapshot["stage_name"] = response_stage
                        self._render_stream_preview(halted_snapshot)
                        self._showing_stream_preview = False
                    else:
                        self.recap_heading_label.setText("Recap")
                        self._load_recap_text("")

    def _refresh_from_controller(self) -> None:
        snapshot = self._controller.snapshot()
        self._refresh_runtime_fields()
        has_session = bool(snapshot.get("has_session"))
        recap = snapshot.get("recap", {})
        last_event = snapshot.get("last_event", {})
        for widget in (
            self.ollama_host_edit,
            self.ollama_model_edit,
            self.generate_btn,
            self.recap_editor,
        ):
            widget.setEnabled(has_session)
        if not has_session:
            self.recap_heading_label.setText("Recap")
            self.status_label.setText("Create or select a session first.")
            self.status_label.setVisible(True)
            self._load_recap_text("")
            self.recap_editor.setReadOnly(True)
            return
        recap_status = str(recap.get("status") or "idle")
        last_error = str(recap.get("last_error") or "").strip()
        _set_action_button_state(
            self.generate_btn,
            "stop.svg" if recap_status == "running" else "add_items.svg",
            "Stop" if recap_status == "running" else "AutoRecap",
            "Stop recap" if recap_status == "running" else "Generate recap",
            object_name="DestructiveButton" if recap_status == "running" else "PrimaryButton",
        )
        self.recap_editor.setReadOnly(recap_status == "running")
        if recap_status == "running":
            self.status_label.setText("Generating recap")
            self.status_label.setVisible(True)
        elif last_error and "halted by user" not in last_error.lower():
            self.status_label.setText(last_error)
            self.status_label.setVisible(True)
        else:
            self.status_label.setText("")
            self.status_label.setVisible(False)
        if recap_status != "running" and not self._recap_editor_dirty and not self._showing_stream_preview:
            recap_text = self._controller.recap_text()
            self.recap_heading_label.setText("Final Recap" if recap_text.strip() else "Recap")
            self._load_recap_text(self._display_recap_body(recap_text))
