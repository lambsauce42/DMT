from __future__ import annotations

import json
import mimetypes
import os
import hashlib
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QEasingCurve, QPointF, Qt, QTimer, QSize, QVariantAnimation
from PyQt6.QtGui import (
    QAction,
    QIcon,
    QColor,
    QDesktopServices,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextBlockFormat,
    QTextListFormat,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QAbstractSpinBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QToolButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QPlainTextEdit,
    QTextEdit,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QGroupBox,
    QFileDialog,
    QMenu,
    QPushButton,
    QSpinBox,
)

from dmt_package import read_dmt_package_asset, read_dmt_package_info, write_dmt_package
from models import Session, SessionAttachment, SessionLogEntry
from save_paths import default_dnd_save_dir
from navigate_widget import WORLD_DATA
from player_sheets import (
    PlayerSheetsManager,
    PlayerSheetEntry,
    entry_from_dict as sheet_entry_from_dict,
    player_sheets_storage_path,
    list_worlds,
    list_campaigns,
    list_groups,
    resolve_selection,
    _combo_optional_value,
    _populate_combo,
)
from maps_applet import MapViewPanel
from ui.widgets import TerminalWidget
from ui.widgets.rich_text_editor import RichTextDescriptionEditor
from unique_ids import generate_probabilistic_unique_id


# Attempt to import PDF Viewer
PDFIUM_VIEW_AVAILABLE = False
try:
    from ui.character_sheet_panel import CharacterSheetPanel
    PDFIUM_VIEW_AVAILABLE = True
except Exception:
    pass

SESSION_DIR_NAME = "sessions"
SESSION_STORAGE_MARKER_NAME = "sessions.dmtindex"
SESSION_FILE_EXTENSION = ".dmtsession"
SESSION_FILE_FORMAT = "dmtsession.v2"
MAX_ATTACHMENT_FILE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_ATTACHMENT_BYTES = 150 * 1024 * 1024
FILES_COLLAPSED_STRIP_WIDTH = 0
ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
TEXT_FILE_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".yaml",
    ".yml",
    ".csv",
    ".log",
    ".ini",
    ".py",
    ".js",
    ".ts",
}
IMAGE_FILE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
PDF_FILE_EXTENSIONS = {".pdf"}


def session_storage_dir() -> Path:
    # MD specifies: ~/Documents/DMT/sessions/ 
    # save_paths.default_dnd_save_dir() returns ~/Documents/DMT (or equivalent)
    return Path(default_dnd_save_dir()) / SESSION_DIR_NAME

def session_storage_path() -> Path:
    return session_storage_dir() / SESSION_STORAGE_MARKER_NAME

def session_file_path(session_id: str, base_dir: Optional[Path] = None) -> Path:
    target_dir = base_dir if base_dir is not None else session_storage_path().parent
    safe_name = sanitize_filename(session_id)
    return target_dir / f"{safe_name}{SESSION_FILE_EXTENSION}"

def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")

def sanitize_filename(name: str) -> str:
    import re
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "session"


def _is_test_env() -> bool:
    if os.environ.get("DMT_TEST_MODE") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return "pytest" in sys.modules


def _detect_mime(name: str) -> str:
    mime, _ = mimetypes.guess_type(str(name or ""))
    return str(mime or "application/octet-stream")


def _is_text_extension(name: str, mime: str = "") -> bool:
    suffix = Path(str(name or "")).suffix.lower()
    normalized_mime = str(mime or "").strip().lower()
    if suffix in TEXT_FILE_EXTENSIONS:
        return True
    if normalized_mime.startswith("text/"):
        return True
    return normalized_mime in {
        "application/json",
        "application/xml",
        "application/javascript",
        "application/x-yaml",
        "application/yaml",
    }


def _safe_attachment_filename(name: str) -> str:
    base_name = Path(str(name or "")).name or "file"
    stem = sanitize_filename(Path(base_name).stem) or "file"
    suffix = "".join(
        ch for ch in Path(base_name).suffix.lower() if ch.isalnum() or ch == "."
    )
    if suffix and not suffix.startswith("."):
        suffix = f".{suffix}"
    return f"{stem}{suffix}"


def _attachment_asset_name(attachment_id: str, name: str) -> str:
    safe_attachment_id = sanitize_filename(attachment_id) or "attachment"
    safe_name = _safe_attachment_filename(name)
    return f"assets/files/{safe_attachment_id}/{safe_name}"


def _hash_bytes(raw: bytes) -> str:
    return hashlib.sha256(bytes(raw)).hexdigest()


def _format_size(size_bytes: int) -> str:
    size = max(0, int(size_bytes))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{size} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class SessionManager:
    def __init__(self) -> None:
        self.sessions: List[Session] = []
        self.last_error: str = ""
        self._attachment_assets: dict[str, dict[str, bytes]] = {}
        self.load()

    def load(self) -> None:
        self.last_error = ""
        self.sessions = []
        self._attachment_assets = {}
        storage_root = session_storage_path().parent

        if storage_root.exists():
            session_files = sorted(storage_root.glob(f"*{SESSION_FILE_EXTENSION}"))
            for file_path in session_files:
                try:
                    info = read_dmt_package_info(file_path)
                    if not isinstance(info, dict):
                        raise ValueError("Missing or invalid package info.")
                    if str(info.get("format") or "") != SESSION_FILE_FORMAT:
                        raise ValueError(
                            f"Unsupported session format '{info.get('format')}'."
                        )
                    payload = info.get("payload")
                    if not isinstance(payload, dict):
                        raise ValueError("Missing session payload.")
                    session = self._dict_to_session(payload)
                    attachments = self._attachments_from_payload(info.get("attachments"))
                    session_assets: dict[str, bytes] = {}
                    for attachment in attachments:
                        asset_bytes = read_dmt_package_asset(file_path, attachment.asset_path)
                        if asset_bytes is None:
                            continue
                        attachment.size_bytes = len(asset_bytes)
                        attachment.sha256 = _hash_bytes(asset_bytes)
                        session_assets[attachment.id] = bytes(asset_bytes)
                    session.attachments = [
                        attachment for attachment in attachments if attachment.id in session_assets
                    ]
                    self._attachment_assets[session.id] = session_assets
                    self.sessions.append(session)
                except Exception as exc:
                    self.last_error = f"Unable to load session from '{file_path}': {exc}"

    def save(self) -> None:
        storage_root = session_storage_path().parent
        storage_root.mkdir(parents=True, exist_ok=True)
        expected_files: set[Path] = set()

        for session in self.sessions:
            file_path = session_file_path(session.id, storage_root)
            expected_files.add(file_path.resolve())
            payload = self._session_to_dict(session)
            attachment_assets = self._attachment_assets.setdefault(session.id, {})
            serialized_attachments: list[dict] = []
            package_assets: dict[str, bytes] = {}
            for attachment in session.attachments:
                attachment_bytes = attachment_assets.get(attachment.id)
                if attachment_bytes is None:
                    continue
                attachment.asset_path = (
                    str(attachment.asset_path).strip()
                    or _attachment_asset_name(attachment.id, attachment.name)
                )
                attachment.mime = str(attachment.mime or _detect_mime(attachment.name))
                attachment.is_text = bool(
                    attachment.is_text
                    or _is_text_extension(attachment.name, attachment.mime)
                )
                attachment.size_bytes = len(attachment_bytes)
                attachment.sha256 = _hash_bytes(attachment_bytes)
                package_assets[attachment.asset_path] = bytes(attachment_bytes)
                serialized_attachments.append(asdict(attachment))
            write_dmt_package(
                file_path,
                info={
                    "format": SESSION_FILE_FORMAT,
                    "object_type": "session",
                    "object_id": str(session.id),
                    "updated_at": _now_timestamp(),
                    "payload": payload,
                    "attachments": serialized_attachments,
                },
                assets=package_assets,
            )

        for existing in storage_root.glob(f"*{SESSION_FILE_EXTENSION}"):
            try:
                existing_resolved = existing.resolve()
            except Exception:
                existing_resolved = existing
            if existing_resolved not in expected_files:
                try:
                    existing.unlink()
                except Exception:
                    continue

    def _attachments_from_payload(self, raw_payload) -> list[SessionAttachment]:
        if not isinstance(raw_payload, list):
            return []
        attachments: list[SessionAttachment] = []
        for index, payload in enumerate(raw_payload):
            if not isinstance(payload, dict):
                continue
            attachment_id = str(payload.get("id") or "").strip()
            attachment_name = str(payload.get("name") or "").strip()
            attachment_asset_path = str(payload.get("asset_path") or "").strip()
            if not attachment_id:
                attachment_id = generate_probabilistic_unique_id("att")
            if not attachment_name or not attachment_asset_path:
                continue
            attachment_mime = str(payload.get("mime") or _detect_mime(attachment_name))
            is_text = bool(
                payload.get("is_text", _is_text_extension(attachment_name, attachment_mime))
            )
            attachments.append(
                SessionAttachment(
                    id=attachment_id,
                    name=attachment_name,
                    asset_path=attachment_asset_path,
                    mime=attachment_mime,
                    size_bytes=max(0, int(payload.get("size_bytes") or 0)),
                    sha256=str(payload.get("sha256") or ""),
                    source_name=str(payload.get("source_name") or attachment_name),
                    source_path=str(payload.get("source_path") or ""),
                    added_at=str(payload.get("added_at") or ""),
                    updated_at=str(payload.get("updated_at") or ""),
                    is_text=is_text,
                )
            )
        return attachments

    def _dict_to_session(self, d: dict) -> Session:
        logs = [SessionLogEntry(**l) for l in d.get("logs", []) if isinstance(l, dict)]
        return Session(
            id=d.get("id", sanitize_filename(d["name"])),
            name=d["name"],
            session_date=d["session_date"],
            in_game_date=d.get("in_game_date", ""),
            real_world_duration=d.get("real_world_duration", ""),
            notes=d.get("notes", ""),
            logs=logs,
            document_path=d.get("document_path"),
            plan_text=d.get("plan_text", ""),
            group_ids=d.get("group_ids", []),
            attachments=[],
        )

    def _session_to_dict(self, s: Session) -> dict:
        return {
            "id": s.id,
            "name": s.name,
            "session_date": s.session_date,
            "in_game_date": s.in_game_date,
            "real_world_duration": s.real_world_duration,
            "notes": s.notes,
            "logs": [asdict(l) for l in s.logs],
            "document_path": s.document_path,
            "plan_text": s.plan_text,
            "group_ids": s.group_ids,
        }

    def get_attachment_bytes(self, session_id: str, attachment_id: str) -> Optional[bytes]:
        session_assets = self._attachment_assets.get(str(session_id), {})
        payload = session_assets.get(str(attachment_id))
        if payload is None:
            return None
        return bytes(payload)

    def set_attachment_bytes(self, session_id: str, attachment_id: str, payload: bytes) -> None:
        session_key = str(session_id)
        attachment_key = str(attachment_id)
        if not session_key or not attachment_key:
            return
        session_assets = self._attachment_assets.setdefault(session_key, {})
        session_assets[attachment_key] = bytes(payload)

    def remove_attachment_bytes(self, session_id: str, attachment_id: str) -> None:
        session_assets = self._attachment_assets.get(str(session_id), {})
        session_assets.pop(str(attachment_id), None)

    def add_session(self, session: Session) -> None:
        self._attachment_assets.setdefault(session.id, {})
        self.sessions.append(session)
        self.save()

    def update_session(self, session: Session) -> None:
        for i, s in enumerate(self.sessions):
            if s.id == session.id:
                self.sessions[i] = session
                break
        self.save()

    def delete_session(self, session_id: str) -> None:
        self.sessions = [s for s in self.sessions if s.id != session_id]
        self._attachment_assets.pop(str(session_id), None)
        self.save()


class FilePoolEdgeToggleButton(QPushButton):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._collapsed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("SecondaryButton")
        self.setProperty("compact", True)
        self.setFixedSize(32, 64)
        self.set_collapsed(False)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = bool(collapsed)
        self.setText(">" if self._collapsed else "<")
        self.setToolTip("Expand file list" if self._collapsed else "Collapse file list")

    def is_collapsed(self) -> bool:
        return self._collapsed

    def paintEvent(self, event) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ""
        option.icon = QIcon()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)

        rect = self.rect().adjusted(0, 0, -1, -1)
        center_x = float(rect.center().x()) + 0.5
        center_y = float(rect.center().y()) + 0.5

        vertical_half = min(20.0, rect.height() * 0.36)
        horizontal_half = min(8.2, rect.width() * 0.26)
        if self._collapsed:
            top = QPointF(center_x - horizontal_half, center_y - vertical_half)
            mid = QPointF(center_x + horizontal_half, center_y)
            bottom = QPointF(center_x - horizontal_half, center_y + vertical_half)
        else:
            top = QPointF(center_x + horizontal_half, center_y - vertical_half)
            mid = QPointF(center_x - horizontal_half, center_y)
            bottom = QPointF(center_x + horizontal_half, center_y + vertical_half)

        caret_color = QColor(236, 241, 247, 248 if self.underMouse() else 230)
        caret_pen = QPen(caret_color, 2.6)
        caret_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        caret_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(caret_pen)

        caret_path = QPainterPath()
        caret_path.moveTo(top)
        caret_path.lineTo(mid)
        caret_path.lineTo(bottom)
        painter.drawPath(caret_path)


class SessionCreatorWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.manager = SessionManager()
        self._current_session: Optional[Session] = None
        self._current_session_dirty = False
        self._loading_plan_text = False
        self._loading_attachment_text = False
        self._active_text_attachment_id: Optional[str] = None
        self._files_list_collapsed = False
        self._files_last_expanded_width = 320
        
        self._world_data = WORLD_DATA
        
        self.sheets_manager = PlayerSheetsManager(entries=self._load_sheet_entries())

        # Auto-save timer
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.setInterval(2000) # 2 seconds
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self._save_current_session)
        self.save_shortcut = QShortcut(QKeySequence.StandardKey.Save, self)
        self.save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.save_shortcut.activated.connect(self._save_now)
        self._plan_shortcuts: List[QShortcut] = []

        self._init_ui()
        self._refresh_session_list()
        if self.manager.last_error:
            if _is_test_env():
                print(f"Session Load Failed: {self.manager.last_error}")
            else:
                QTimer.singleShot(
                    0,
                    lambda msg=self.manager.last_error: QMessageBox.warning(
                        self,
                        "Session Load Failed",
                        msg,
                    ),
                )

    def closeEvent(self, event) -> None:
        self.auto_save_timer.stop()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._position_files_edge_toggle()

    def _current_context_restrictions(self) -> tuple[str, str, str]:
        world = _combo_optional_value(self.world_combo) if hasattr(self, "world_combo") else ""
        campaign = _combo_optional_value(self.campaign_combo) if hasattr(self, "campaign_combo") else ""
        group = _combo_optional_value(self.group_combo) if hasattr(self, "group_combo") else ""
        return world, campaign, group

    def _context_token(self, world: str, campaign: str, group: str) -> Optional[str]:
        if not (world or campaign or group):
            return None
        return f"{world}::{campaign}::{group}"

    def _session_context(self, session: Session) -> tuple[str, str, str]:
        if not session.group_ids:
            return "", "", ""
        raw = str(session.group_ids[0])
        if "::" not in raw:
            return "", "", ""
        parts = raw.split("::", 2)
        while len(parts) < 3:
            parts.append("")
        return str(parts[0]), str(parts[1]), str(parts[2])

    def _session_matches_context(
        self, session: Session, world: str, campaign: str, group: str
    ) -> bool:
        s_world, s_campaign, s_group = self._session_context(session)
        if world and s_world != world:
            return False
        if campaign and s_campaign != campaign:
            return False
        if group and s_group != group:
            return False
        return True

    def _world_options(self) -> List[str]:
        options = list(list_worlds(self._world_data))
        for session in self.manager.sessions:
            world, _, _ = self._session_context(session)
            if world and world not in options:
                options.append(world)
        return options

    def _campaign_options(self, world: Optional[str] = None) -> List[str]:
        options = list(list_campaigns(self._world_data, world))
        for session in self.manager.sessions:
            s_world, campaign, _ = self._session_context(session)
            if not campaign:
                continue
            if world and s_world != world:
                continue
            if campaign not in options:
                options.append(campaign)
        return options

    def _group_options(self, world: Optional[str] = None, campaign: Optional[str] = None) -> List[str]:
        options = list(list_groups(self._world_data, world, campaign))
        for session in self.manager.sessions:
            s_world, s_campaign, group = self._session_context(session)
            if not group:
                continue
            if world and s_world != world:
                continue
            if campaign and s_campaign != campaign:
                continue
            if group not in options:
                options.append(group)
        return options

    def _load_sheet_entries(self) -> List[PlayerSheetEntry]:
        path = player_sheets_storage_path()
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, list):
                return [e for e in (sheet_entry_from_dict(p) for p in raw) if e]
        except Exception:
            pass
        return []

    def _init_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.main_splitter.setHandleWidth(10)

        # --- Left Pane: Dashboard (Scratchpad Only) ---
        self.dashboard_pane = QFrame()
        self.dashboard_pane.setObjectName("Panel")
        dash_layout = QVBoxLayout(self.dashboard_pane)
        dash_layout.setContentsMargins(12, 12, 12, 12)
        dash_layout.setSpacing(8)
        
        self.session_title_label = QLabel("No Session Selected")
        self.session_title_label.setObjectName("SelectionTitle")
        dash_layout.addWidget(self.session_title_label)
        
        scratch_header = QWidget()
        scratch_header.setObjectName("TransparentContainer")
        scratch_header_layout = QHBoxLayout(scratch_header)
        scratch_header_layout.setContentsMargins(0, 0, 0, 0)
        scratch_label = QLabel("Scratchpad")
        scratch_label.setObjectName("Subheader")
        scratch_header_layout.addWidget(scratch_label)
        dash_layout.addWidget(scratch_header)

        self.scratchpad = RichTextDescriptionEditor()
        self.scratchpad.setPlaceholderText("Session notes...")
        self.scratchpad.textChanged.connect(self._trigger_auto_save)
        dash_layout.addWidget(self.scratchpad, 1)

        # Terminal
        self.terminal = TerminalWidget()
        dash_layout.addWidget(self.terminal, 1)

        self.main_splitter.addWidget(self.dashboard_pane)

        # --- Center Pane: Reference ---
        self.reference_pane = QFrame()
        self.reference_pane.setObjectName("Panel")
        ref_layout = QVBoxLayout(self.reference_pane)
        ref_layout.setContentsMargins(0, 0, 0, 0)
        
        self.ref_tabs = QTabWidget()
        
        # Plan Tab (scratchpad-like rich text editor + plain-text import)
        plan_tab = QWidget()
        plan_layout = QVBoxLayout(plan_tab)

        plan_controls = QHBoxLayout()
        plan_controls.setContentsMargins(0, 0, 0, 0)
        plan_controls.setSpacing(8)
        self.plan_path_label = QLabel("No text file loaded")
        self.plan_path_label.setStyleSheet("color: #8b949e; font-style: italic;")
        plan_controls.addWidget(self.plan_path_label, 1)

        self.load_plan_btn = QToolButton()
        self.load_plan_btn.setObjectName("PrimaryButton")
        self.load_plan_btn.setToolTip("Load Text File")
        self.load_plan_btn.setIcon(QIcon(os.path.join(ICON_DIR, "folder_open.svg")))
        self.load_plan_btn.setIconSize(QSize(18, 18))
        self.load_plan_btn.setStyleSheet("padding: 4px; border-radius: 6px;")
        self.load_plan_btn.clicked.connect(self._browse_plan_text_file)

        self.plan_editor = QTextEdit()
        self.plan_editor.setAcceptRichText(True)
        self.plan_editor.setPlaceholderText("Load a text file to import a session plan or start typing...")
        self.plan_editor.textChanged.connect(self._on_plan_text_changed)
        self.plan_editor.cursorPositionChanged.connect(self._update_plan_toolbar_state)
        self.plan_editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.plan_editor.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)

        self.plan_toolbar = QWidget()
        self.plan_toolbar.setObjectName("TransparentContainer")
        self.plan_toolbar_container = QFrame(self.plan_toolbar)
        self.plan_toolbar_container.setObjectName("ToolPanelContainer")
        self.plan_toolbar_container.setStyleSheet(
            """
            #ToolPanelContainer {
                background-color: rgba(9, 9, 11, 180);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 20);
            }
            QToolButton {
                background-color: transparent;
                border: none;
                border-radius: 6px;
                padding: 6px;
                margin: 2px;
                text-align: center;
                min-width: 32px;
                max-width: 32px;
                min-height: 32px;
                max-height: 32px;
            }
            QToolButton:hover {
                background-color: rgba(255, 255, 255, 30);
            }
            QToolButton:checked {
                background-color: rgba(255, 255, 255, 50);
                border: 1px solid rgba(255, 255, 255, 80);
            }
            QSpinBox {
                background-color: rgba(0, 0, 0, 100);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 4px;
                padding: 2px 6px;
            }
            """
        )
        plan_toolbar_outer = QVBoxLayout(self.plan_toolbar)
        plan_toolbar_outer.setContentsMargins(0, 0, 0, 0)
        plan_toolbar_outer.addWidget(self.plan_toolbar_container)

        plan_tools_layout = QHBoxLayout(self.plan_toolbar_container)
        plan_tools_layout.setContentsMargins(4, 4, 4, 4)
        plan_tools_layout.setSpacing(4)

        self.plan_bold_btn = self._make_plan_tool_button("Bold (Ctrl+B)", "bold.svg")
        self.plan_bold_btn.setCheckable(True)
        self.plan_bold_btn.clicked.connect(self._toggle_plan_bold)
        plan_tools_layout.addWidget(self.plan_bold_btn)

        self.plan_italic_btn = self._make_plan_tool_button("Italic (Ctrl+I)", "italic.svg")
        self.plan_italic_btn.setCheckable(True)
        self.plan_italic_btn.clicked.connect(self._toggle_plan_italic)
        plan_tools_layout.addWidget(self.plan_italic_btn)

        self.plan_underline_btn = self._make_plan_tool_button("Underline (Ctrl+U)", "underline.svg")
        self.plan_underline_btn.setCheckable(True)
        self.plan_underline_btn.clicked.connect(self._toggle_plan_underline)
        plan_tools_layout.addWidget(self.plan_underline_btn)

        sep_2 = QFrame()
        sep_2.setFrameShape(QFrame.Shape.VLine)
        sep_2.setFrameShadow(QFrame.Shadow.Plain)
        sep_2.setStyleSheet("color: #30363d;")
        plan_tools_layout.addWidget(sep_2)

        self.plan_bullet_btn = self._make_plan_tool_button("Bullet List (Ctrl+Shift+])", "list.svg")
        self.plan_bullet_btn.setCheckable(True)
        self.plan_bullet_btn.clicked.connect(self._toggle_plan_bullet_list)
        plan_tools_layout.addWidget(self.plan_bullet_btn)

        self.plan_indent_btn = self._make_plan_tool_button("Indent (Ctrl+])", "indent.svg")
        self.plan_indent_btn.clicked.connect(self._indent_plan_text)
        plan_tools_layout.addWidget(self.plan_indent_btn)

        self.plan_outdent_btn = self._make_plan_tool_button("Outdent (Ctrl+[)", "outdent.svg")
        self.plan_outdent_btn.clicked.connect(self._outdent_plan_text)
        plan_tools_layout.addWidget(self.plan_outdent_btn)

        sep_3 = QFrame()
        sep_3.setFrameShape(QFrame.Shape.VLine)
        sep_3.setFrameShadow(QFrame.Shadow.Plain)
        sep_3.setStyleSheet("color: #30363d;")
        plan_tools_layout.addWidget(sep_3)

        self.plan_font_spin = QSpinBox()
        self.plan_font_spin.setRange(8, 72)
        self.plan_font_spin.setValue(12)
        self.plan_font_spin.setSuffix("pt")
        self.plan_font_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.plan_font_spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plan_font_spin.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.plan_font_spin.setFixedWidth(64)
        self.plan_font_spin.valueChanged.connect(self._set_plan_font_size)
        self.plan_font_spin.wheelEvent = lambda event: event.ignore()
        plan_tools_layout.addWidget(self.plan_font_spin)

        self.plan_font_up_btn = self._make_plan_tool_button("Increase Font Size", "caret_up_white.svg")
        self.plan_font_up_btn.clicked.connect(self.plan_font_spin.stepUp)
        plan_tools_layout.addWidget(self.plan_font_up_btn)

        self.plan_font_down_btn = self._make_plan_tool_button("Decrease Font Size", "caret_down_white.svg")
        self.plan_font_down_btn.clicked.connect(self.plan_font_spin.stepDown)
        plan_tools_layout.addWidget(self.plan_font_down_btn)

        self._plan_format_controls = [
            self.plan_bold_btn,
            self.plan_italic_btn,
            self.plan_underline_btn,
            self.plan_bullet_btn,
            self.plan_indent_btn,
            self.plan_outdent_btn,
            self.plan_font_spin,
            self.plan_font_up_btn,
            self.plan_font_down_btn,
        ]
        self._init_plan_shortcuts()
        plan_row_height = self.plan_toolbar.sizeHint().height()
        self.plan_toolbar.setFixedHeight(plan_row_height)
        plan_tool_button_size = self.plan_bold_btn.width()
        self.load_plan_btn.setFixedSize(plan_tool_button_size, plan_tool_button_size)

        plan_controls.addWidget(self.plan_toolbar, 0, Qt.AlignmentFlag.AlignVCenter)
        plan_controls.addWidget(self.load_plan_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        plan_layout.addLayout(plan_controls)
        plan_layout.addWidget(self.plan_editor, 1)

        self.ref_tabs.addTab(plan_tab, "Plan")
        self.ref_tabs.addTab(self._build_files_tab(), "Files")
        self.ref_tabs.currentChanged.connect(self._on_reference_tab_changed)
        
        ref_layout.addWidget(self.ref_tabs)
        self.main_splitter.addWidget(self.reference_pane)

        # --- Right Pane: Navigation ---
        self.nav_pane = QFrame()
        self.nav_pane.setObjectName("Panel")
        self.nav_pane.setFixedWidth(300)
        nav_layout = QVBoxLayout(self.nav_pane)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(12)
        
        # Sophisticated Context Picker
        context_group = QGroupBox("Linked Context")
        context_group.setObjectName("TransparentContainer")
        context_layout = QVBoxLayout(context_group)
        context_layout.setSpacing(8)
        
        self.world_combo = QComboBox()
        self.campaign_combo = QComboBox()
        self.group_combo = QComboBox()
        self._context_reset_buttons: List[QToolButton] = []
        for combo in (self.world_combo, self.campaign_combo, self.group_combo):
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            combo.setFixedHeight(32)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(1)
        context_control_size = 32
        
        # Helper for rows
        def make_context_row(label_text, widget, reset_callback):
            row = QWidget()
            row.setObjectName("TransparentContainer")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(6)
            
            label = QLabel(label_text)
            label.setFixedWidth(70) # Fixed width for alignment
            label.setObjectName("Subheader")
            
            reset_btn = QToolButton()
            reset_btn.setObjectName("InlineResetButton")
            reset_btn.setIcon(QIcon(os.path.join(ICON_DIR, "reset.svg")))
            reset_btn.setIconSize(QSize(14, 14))
            reset_btn.setFixedSize(context_control_size, context_control_size)
            reset_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            reset_btn.clicked.connect(reset_callback)
            self._context_reset_buttons.append(reset_btn)
            
            row_layout.addWidget(label)
            row_layout.addWidget(widget, 1)
            row_layout.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignVCenter)
            return row

        context_layout.addWidget(make_context_row("World:", self.world_combo, lambda: self.world_combo.setCurrentIndex(0)))
        context_layout.addWidget(make_context_row("Campaign:", self.campaign_combo, lambda: self.campaign_combo.setCurrentIndex(0)))
        context_layout.addWidget(make_context_row("Group:", self.group_combo, lambda: self.group_combo.setCurrentIndex(0)))
        
        nav_layout.addWidget(context_group)
        
        # Connect Context Signals
        self.world_combo.currentIndexChanged.connect(self._on_world_changed)
        self.campaign_combo.currentIndexChanged.connect(self._on_campaign_changed)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        
        sessions_header = QWidget()
        sessions_header.setObjectName("TransparentContainer")
        sessions_header_layout = QHBoxLayout(sessions_header)
        sessions_header_layout.setContentsMargins(0, 0, 0, 0)
        sessions_label = QLabel("Sessions")
        sessions_label.setObjectName("Subheader")
        sessions_header_layout.addWidget(sessions_label)
        nav_layout.addWidget(sessions_header)

        self.session_list = QListWidget()
        self.session_list.setObjectName("NavList")
        self.session_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.session_list.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._on_session_context_menu)
        self.session_list.currentItemChanged.connect(self._on_session_list_changed)
        self.session_list.itemChanged.connect(self._on_session_name_changed)
        nav_layout.addWidget(self.session_list, 1)
        
        btn_row_widget = QWidget()
        btn_row_widget.setObjectName("TransparentContainer")
        btn_row = QHBoxLayout(btn_row_widget)
        btn_row.setContentsMargins(0, 0, 0, 6)
        btn_row.setSpacing(5)
        
        new_btn = QToolButton()
        new_btn.setObjectName("PrimaryButton")
        new_btn.setIcon(QIcon(os.path.join(ICON_DIR, "plus.svg")))
        new_btn.setToolTip("New Session")
        new_btn.clicked.connect(self._create_session)

        load_btn = QToolButton()
        load_btn.setObjectName("PrimaryButton")
        load_btn.setIcon(QIcon(os.path.join(ICON_DIR, "folder_open.svg")))
        load_btn.setToolTip("Load Selected Session")
        load_btn.clicked.connect(self._load_selected_session)

        save_btn = QToolButton()
        save_btn.setObjectName("PrimaryButton")
        save_btn.setIcon(QIcon(os.path.join(ICON_DIR, "save.svg")))
        save_btn.setToolTip("Save Current Session (Ctrl+S)")
        save_btn.clicked.connect(self._save_now)
        
        del_btn = QToolButton()
        del_btn.setObjectName("DestructiveButton")
        del_btn.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
        del_btn.setToolTip("Delete Session")
        del_btn.clicked.connect(self._delete_session)
        
        for btn in (new_btn, load_btn, save_btn, del_btn):
            btn.setFixedHeight(36)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setIconSize(QSize(20, 20))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_row.addWidget(btn)
            
        nav_layout.addWidget(btn_row_widget)
        
        self.main_splitter.addWidget(self.nav_pane)
        
        # Set initial splitter sizes
        self.main_splitter.setSizes([350, int(600 * 0.7), 300])
        
        layout.addWidget(self.main_splitter)

        self._set_plan_controls_enabled(False)
        self._set_file_controls_enabled(False)

        # Initialize Combo Boxes
        _populate_combo(self.world_combo, self._world_options())
        self._on_world_changed() # Trigger cascade

    def _build_files_tab(self) -> QWidget:
        files_tab = QWidget(self)
        files_layout = QVBoxLayout(files_tab)
        files_layout.setContentsMargins(8, 8, 8, 8)
        files_layout.setSpacing(8)

        files_splitter = QSplitter(Qt.Orientation.Horizontal, files_tab)
        files_splitter.setHandleWidth(10)
        self.files_splitter = files_splitter

        list_panel = QFrame(files_tab)
        list_panel.setObjectName("PanelTransparent")
        self.files_list_panel = list_panel
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.setSpacing(8)
        self.files_list_content = QWidget(list_panel)
        self.files_list_content.setObjectName("TransparentContainer")
        list_content_layout = QVBoxLayout(self.files_list_content)
        list_content_layout.setContentsMargins(0, 0, 0, 0)
        list_content_layout.setSpacing(8)

        self.files_table = QTableWidget(0, 4, self.files_list_content)
        self.files_table.setHorizontalHeaderLabels(["Name", "Type", "Size", "Updated"])
        self.files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.files_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.files_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.files_table.setAlternatingRowColors(True)
        self.files_table.setShowGrid(False)
        self.files_table.setFrameShape(QFrame.Shape.NoFrame)
        self.files_table.setViewportMargins(0, 0, 0, 0)
        self.files_table.setContentsMargins(0, 0, 0, 0)
        self.files_table.horizontalHeader().setSectionsMovable(False)
        self.files_table.horizontalHeader().setStretchLastSection(False)
        self.files_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.files_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.files_table.verticalHeader().setVisible(False)
        self.files_table.setStyleSheet(
            """
            QTableWidget {
                padding: 0px;
                margin: 0px;
                border: 0px;
                background-clip: border;
            }
            QTableView::item {
                margin: 0px;
                padding: 4px 6px;
                border: 0px;
            }
            QHeaderView {
                margin: 0px;
                padding: 0px;
            }
            QHeaderView::section {
                margin: 0px;
                padding: 4px 6px;
            }
            """
        )
        self.files_table.itemSelectionChanged.connect(self._on_selected_file_changed)
        list_content_layout.addWidget(self.files_table, 1)

        controls = QWidget(self.files_list_content)
        controls.setObjectName("TransparentContainer")
        controls.setMinimumHeight(58)
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 6, 0, 6)
        controls_layout.setSpacing(6)

        self.add_file_btn = QPushButton("Add", controls)
        self.add_file_btn.setObjectName("PrimaryButton")
        self.add_file_btn.clicked.connect(self._attach_files_to_session)

        self.remove_file_btn = QPushButton("Remove", controls)
        self.remove_file_btn.setObjectName("DestructiveButton")
        self.remove_file_btn.clicked.connect(self._remove_selected_file)

        self.open_file_external_btn = QPushButton("Open", controls)
        self.open_file_external_btn.setObjectName("PrimaryButton")
        self.open_file_external_btn.clicked.connect(self._open_selected_file_externally)

        for button in (self.add_file_btn, self.remove_file_btn, self.open_file_external_btn):
            button.setProperty("compact", True)
            button.setMinimumHeight(46)
            button.setMaximumHeight(46)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            controls_layout.addWidget(button)
        list_content_layout.addWidget(controls)
        list_layout.addWidget(self.files_list_content, 1)

        preview_panel = QFrame(files_tab)
        preview_panel.setObjectName("PanelTransparent")
        self.files_preview_panel = preview_panel
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(8)

        preview_header = QWidget(preview_panel)
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_layout.setSpacing(6)

        self.files_preview_title = QLabel("Select an attached file")
        self.files_preview_title.setObjectName("Subheader")
        preview_header_layout.addWidget(self.files_preview_title, 1)

        self.files_zoom_label = QLabel("100%")
        self.files_zoom_label.setObjectName("Subheader")
        preview_header_layout.addWidget(self.files_zoom_label, 0, Qt.AlignmentFlag.AlignVCenter)

        self.files_zoom_out_button = QToolButton(preview_header)
        self.files_zoom_out_button.setObjectName("SecondaryButton")
        self.files_zoom_out_button.setIcon(QIcon(os.path.join(ICON_DIR, "minus.svg")))
        self.files_zoom_out_button.setToolTip("Zoom Out")
        self.files_zoom_out_button.setProperty("compact", True)
        self.files_zoom_out_button.setFixedSize(36, 36)
        self.files_zoom_out_button.setIconSize(QSize(20, 20))
        self.files_zoom_out_button.setStyleSheet(
            "padding: 0px; border-radius: 6px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px;"
        )
        self.files_zoom_out_button.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_header_layout.addWidget(self.files_zoom_out_button)

        self.files_zoom_in_button = QToolButton(preview_header)
        self.files_zoom_in_button.setObjectName("SecondaryButton")
        self.files_zoom_in_button.setIcon(QIcon(os.path.join(ICON_DIR, "plus.svg")))
        self.files_zoom_in_button.setToolTip("Zoom In")
        self.files_zoom_in_button.setProperty("compact", True)
        self.files_zoom_in_button.setFixedSize(36, 36)
        self.files_zoom_in_button.setIconSize(QSize(20, 20))
        self.files_zoom_in_button.setStyleSheet(
            "padding: 0px; border-radius: 6px; min-width: 36px; max-width: 36px; min-height: 36px; max-height: 36px;"
        )
        self.files_zoom_in_button.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_header_layout.addWidget(self.files_zoom_in_button)

        preview_layout.addWidget(preview_header)

        self.files_preview_stack = QStackedWidget(preview_panel)
        preview_layout.addWidget(self.files_preview_stack, 1)

        self.files_empty_page = QLabel("No file selected.")
        self.files_empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.files_empty_page.setObjectName("Subheader")
        self.files_preview_stack.addWidget(self.files_empty_page)

        image_page = QWidget(preview_panel)
        image_layout = QVBoxLayout(image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(6)
        self.files_image_view = MapViewPanel(image_page, placeholder="No image selected.")
        image_layout.addWidget(self.files_image_view, 1)
        self.files_preview_stack.addWidget(image_page)
        self.files_image_page = image_page
        self.files_zoom_out_button.clicked.connect(self.files_image_view.zoom_out)
        self.files_zoom_in_button.clicked.connect(self.files_image_view.zoom_in)
        self.files_image_view.zoomChanged.connect(
            lambda value: self.files_zoom_label.setText(f"{int(value)}%")
        )

        text_page = QWidget(preview_panel)
        text_layout = QVBoxLayout(text_page)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        self.files_text_status = QLabel("Text attachment")
        self.files_text_status.setStyleSheet("color: #8b949e;")
        text_layout.addWidget(self.files_text_status)
        self.files_text_editor = QPlainTextEdit(text_page)
        self.files_text_editor.setPlaceholderText("Select a text-based attachment to edit.")
        self.files_text_editor.textChanged.connect(self._on_file_text_changed)
        text_layout.addWidget(self.files_text_editor, 1)
        self.files_preview_stack.addWidget(text_page)
        self.files_text_page = text_page

        self.files_pdf_page = QWidget(preview_panel)
        pdf_layout = QVBoxLayout(self.files_pdf_page)
        pdf_layout.setContentsMargins(0, 0, 0, 0)
        pdf_layout.setSpacing(0)
        if PDFIUM_VIEW_AVAILABLE:
            self.files_pdf_viewer = CharacterSheetPanel(self.files_pdf_page)
            self.files_pdf_viewer.set_autosave_enabled(False)
            pdf_layout.addWidget(self.files_pdf_viewer, 1)
            self.files_pdf_unavailable = None
        else:
            self.files_pdf_viewer = None
            self.files_pdf_unavailable = QLabel(
                "PDF preview requires pypdfium2. Use Open to view externally.",
                self.files_pdf_page,
            )
            self.files_pdf_unavailable.setWordWrap(True)
            self.files_pdf_unavailable.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pdf_layout.addWidget(self.files_pdf_unavailable, 1)
        self.files_preview_stack.addWidget(self.files_pdf_page)

        self.files_unsupported_page = QLabel(
            "Preview unavailable for this file type. Use Open to launch externally.",
            preview_panel,
        )
        self.files_unsupported_page.setWordWrap(True)
        self.files_unsupported_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.files_preview_stack.addWidget(self.files_unsupported_page)

        files_splitter.addWidget(list_panel)
        files_splitter.addWidget(preview_panel)
        files_splitter.setSizes([320, 520])
        files_layout.addWidget(files_splitter, 1)

        self.files_edge_toggle_btn = FilePoolEdgeToggleButton(preview_panel)
        self.files_edge_toggle_btn.clicked.connect(self._toggle_files_list_panel)

        self._files_splitter_animation = QVariantAnimation(self)
        self._files_splitter_animation.setDuration(220)
        self._files_splitter_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._files_splitter_animation.valueChanged.connect(self._on_files_splitter_anim_step)
        self._files_splitter_animation.finished.connect(self._on_files_splitter_anim_finished)
        self.files_splitter.splitterMoved.connect(self._on_files_splitter_moved)
        QTimer.singleShot(0, self._position_files_edge_toggle)
        return files_tab

    def _trigger_auto_save(self) -> None:
        if self._current_session:
            self._set_current_session_dirty(True)
        self.auto_save_timer.start()

    def _report_io_failure(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    def _set_current_session_dirty(self, is_dirty: bool) -> None:
        self._current_session_dirty = bool(is_dirty and self._current_session)
        self._update_session_title()

    def _update_session_title(self) -> None:
        if not self._current_session:
            self.session_title_label.setText("No Session Selected")
            return
        dirty_suffix = " *" if self._current_session_dirty else ""
        self.session_title_label.setText(f"Session: {self._current_session.name}{dirty_suffix}")

    def _save_current_session(self) -> None:
        if not self._current_session:
            return
        
        # Only saving scratchpad and context now, as date/duration/log removed from UI
        self._current_session.notes = self.scratchpad.toHtml()
        self._current_session.plan_text = self.plan_editor.toPlainText()
        
        # Save linked context
        w, c, g = self._current_context_restrictions()
        token = self._context_token(w, c, g)
        self._current_session.group_ids = [token] if token else []

        if self._current_session.document_path:
            plan_path = Path(self._current_session.document_path)
            try:
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(self._current_session.plan_text, encoding="utf-8")
            except Exception as exc:
                self._report_io_failure(
                    "Save Failed",
                    f"Unable to save plan text:\n{plan_path}\n\n{exc}",
                )
        
        self.manager.save()
        self._set_current_session_dirty(False)

    def _save_now(self) -> None:
        self.auto_save_timer.stop()
        self._save_current_session()

    def _refresh_session_list(
        self, *, load_selection: bool = True, preserve_current_session: bool = False
    ) -> None:
        current_id = self._current_session.id if self._current_session else None
        world, campaign, group = self._current_context_restrictions()
        self.session_list.blockSignals(True)
        self.session_list.clear()

        target_row = None
        visible_row_index = -1
        for session in sorted(self.manager.sessions, key=lambda s: s.session_date, reverse=True):
            if not self._session_matches_context(session, world, campaign, group):
                continue
            visible_row_index += 1
            item = QListWidgetItem(session.name)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(Qt.ItemDataRole.UserRole, session.id)
            self.session_list.addItem(item)
            if current_id and session.id == current_id:
                target_row = visible_row_index

        if target_row is None and self.session_list.count() > 0 and not preserve_current_session:
            target_row = 0

        selected_item = None
        if target_row is not None:
            self.session_list.setCurrentRow(target_row)
            selected_item = self.session_list.item(target_row)
        self.session_list.blockSignals(False)
        if load_selection:
            if preserve_current_session and current_id and target_row is None:
                return
            if selected_item is None and current_id and self._current_session and self._current_session.id == current_id:
                return
            self._on_session_list_changed(selected_item, None)

    def _create_session(self) -> None:
        default_name = "Untitled Session"
        session = Session(
            id=sanitize_filename(f"{default_name}_{_now_timestamp()}"),
            name=default_name,
            session_date=datetime.now().strftime("%Y-%m-%d"),
        )
        # Pre-fill linked context if selected.
        w, c, g = self._current_context_restrictions()
        token = self._context_token(w, c, g)
        session.group_ids = [token] if token else []

        self.manager.add_session(session)
        self._current_session = session
        self._refresh_session_list()

        # Select and immediately begin inline rename.
        item = self.session_list.currentItem()
        if item and item.data(Qt.ItemDataRole.UserRole) == session.id:
            self.session_list.editItem(item)

    def _delete_session(self) -> None:
        item = self.session_list.currentItem()
        if not item:
            return
        session_id = item.data(Qt.ItemDataRole.UserRole)
        res = QMessageBox.question(self, "Delete Session", f"Are you sure you want to delete '{item.text()}'?",
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if res == QMessageBox.StandardButton.Yes:
            self.manager.delete_session(session_id)
            if self._current_session and self._current_session.id == session_id:
                self._current_session = None
                self._clear_dashboard()
            self._refresh_session_list()

    def _on_session_context_menu(self, pos) -> None:
        item = self.session_list.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete Session")
        delete_action.triggered.connect(self._delete_session)
        menu.exec(self.session_list.mapToGlobal(pos))

    def _on_session_name_changed(self, item: QListWidgetItem) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        session = next((s for s in self.manager.sessions if s.id == session_id), None)
        if not session:
            return

        new_name = item.text().strip() or "Untitled Session"
        if new_name != item.text():
            self.session_list.blockSignals(True)
            item.setText(new_name)
            self.session_list.blockSignals(False)

        if session.name == new_name:
            self._update_session_title()
            return

        session.name = new_name
        if self._current_session and self._current_session.id == session.id:
            self._current_session = session
            self._update_session_title()
        self.manager.save()

    def _on_session_list_changed(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if not current:
            self._current_session = None
            self._clear_dashboard()
            return
        self._set_current_session_from_item(current, apply_context=False)

    def _clear_dashboard(self) -> None:
        self._set_current_session_dirty(False)
        self.scratchpad.clear()
        self._load_plan_text_file(None)
        self._set_plan_controls_enabled(False)
        self._set_file_controls_enabled(False)
        self._refresh_file_table()
        self._show_empty_file_preview("No file selected.")

    def _load_session_to_ui(self, session: Session, *, apply_context: bool) -> None:
        self._set_current_session_dirty(False)
        self._set_plan_controls_enabled(True)
        self._set_file_controls_enabled(True)
        self.scratchpad.blockSignals(True)
        self.scratchpad.setHtml(session.notes)
        self.scratchpad.blockSignals(False)
        self._load_plan_text_file(session.document_path, fallback_text=session.plan_text)
        self._refresh_file_table()

        if apply_context:
            # Loading a session should apply its linked context as active restrictions.
            w, c, g = self._session_context(session)
            self._set_context(w, c, g)
            self._refresh_session_list(load_selection=False)

    def _load_selected_session(self) -> None:
        item = self.session_list.currentItem()
        if item:
            self._set_current_session_from_item(item, apply_context=True)

    def _set_current_session_from_item(self, item: QListWidgetItem, *, apply_context: bool) -> None:
        session_id = item.data(Qt.ItemDataRole.UserRole)
        self._current_session = next((s for s in self.manager.sessions if s.id == session_id), None)
        if self._current_session:
            self._load_session_to_ui(self._current_session, apply_context=apply_context)

    def _set_context(self, world: str, campaign: str, group: str) -> None:
        _populate_combo(self.world_combo, self._world_options(), world or None)
        _populate_combo(self.campaign_combo, self._campaign_options(world or None), campaign or None)
        _populate_combo(self.group_combo, self._group_options(world or None, campaign or None), group or None)
        self._sync_reference_tabs()

    def _on_world_changed(self) -> None:
        w = _combo_optional_value(self.world_combo)
        campaigns = self._campaign_options(w)
        _populate_combo(self.campaign_combo, campaigns)
        self._on_campaign_changed()

    def _on_campaign_changed(self) -> None:
        w = _combo_optional_value(self.world_combo)
        c = _combo_optional_value(self.campaign_combo)
        groups = self._group_options(w, c)
        _populate_combo(self.group_combo, groups)
        self._on_group_changed()

    def _on_group_changed(self) -> None:
        self._sync_reference_tabs()
        self._refresh_session_list(preserve_current_session=True)

    def _sync_reference_tabs(self) -> None:
        # Reference tabs currently do not require context-specific sync.
        return

    def _make_plan_tool_button(self, tooltip: str, icon_name: Optional[str], text: Optional[str] = None) -> QToolButton:
        btn = QToolButton()
        btn.setToolTip(tooltip)
        btn.setFixedSize(32, 32)
        btn.setIconSize(QSize(18, 18))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if icon_name:
            icon_path = os.path.join(ICON_DIR, icon_name)
            if os.path.exists(icon_path):
                btn.setIcon(QIcon(icon_path))
            elif text:
                btn.setText(text)
        elif text:
            btn.setText(text)
        return btn

    def _init_plan_shortcuts(self) -> None:
        self._register_plan_shortcut(QKeySequence.StandardKey.Bold, self._toggle_plan_bold)
        self._register_plan_shortcut(QKeySequence.StandardKey.Italic, self._toggle_plan_italic)
        self._register_plan_shortcut("Ctrl+U", self._toggle_plan_underline)
        self._register_plan_shortcut("Ctrl+Shift+]", self._toggle_plan_bullet_list)
        self._register_plan_shortcut("Ctrl+]", self._indent_plan_text)
        self._register_plan_shortcut("Ctrl+[", self._outdent_plan_text)

    def _register_plan_shortcut(self, key: QKeySequence | str, callback) -> None:
        sequence = key if isinstance(key, QKeySequence) else QKeySequence(key)
        shortcut = QShortcut(sequence, self.plan_editor)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(callback)
        self._plan_shortcuts.append(shortcut)

    def _toggle_plan_bold(self) -> None:
        cursor = self.plan_editor.textCursor()
        fmt = QTextCharFormat()
        current_weight = cursor.charFormat().fontWeight()
        target = QFont.Weight.Normal if current_weight == QFont.Weight.Bold else QFont.Weight.Bold
        fmt.setFontWeight(target)
        cursor.mergeCharFormat(fmt)
        self.plan_editor.mergeCurrentCharFormat(fmt)
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        self._trigger_auto_save()

    def _toggle_plan_italic(self) -> None:
        cursor = self.plan_editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontItalic(not cursor.charFormat().fontItalic())
        cursor.mergeCharFormat(fmt)
        self.plan_editor.mergeCurrentCharFormat(fmt)
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        self._trigger_auto_save()

    def _toggle_plan_underline(self) -> None:
        cursor = self.plan_editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontUnderline(not cursor.charFormat().fontUnderline())
        cursor.mergeCharFormat(fmt)
        self.plan_editor.mergeCurrentCharFormat(fmt)
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        self._trigger_auto_save()

    def _toggle_plan_bullet_list(self) -> None:
        cursor = self.plan_editor.textCursor()
        cursor.beginEditBlock()
        current_list = cursor.currentList()
        if current_list and current_list.format().style() == QTextListFormat.Style.ListDisc:
            block_fmt = cursor.blockFormat()
            block_fmt.setObjectIndex(-1)
            block_fmt.setIndent(0)
            cursor.setBlockFormat(block_fmt)
        else:
            list_fmt = current_list.format() if current_list else QTextListFormat()
            list_fmt.setStyle(QTextListFormat.Style.ListDisc)
            if list_fmt.indent() <= 0:
                list_fmt.setIndent(1)
            cursor.createList(list_fmt)
        cursor.endEditBlock()
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        self._trigger_auto_save()

    def _indent_plan_text(self) -> None:
        cursor = self.plan_editor.textCursor()
        cursor.beginEditBlock()
        current_list = cursor.currentList()
        if current_list:
            list_fmt = current_list.format()
            list_fmt.setIndent(list_fmt.indent() + 1)
            cursor.createList(list_fmt)
        else:
            block_fmt = cursor.blockFormat()
            block_fmt.setIndent(block_fmt.indent() + 1)
            cursor.setBlockFormat(block_fmt)
        cursor.endEditBlock()
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        self._trigger_auto_save()

    def _outdent_plan_text(self) -> None:
        cursor = self.plan_editor.textCursor()
        cursor.beginEditBlock()
        current_list = cursor.currentList()
        if current_list:
            list_fmt = current_list.format()
            if list_fmt.indent() > 1:
                list_fmt.setIndent(list_fmt.indent() - 1)
                cursor.createList(list_fmt)
            else:
                block_fmt = QTextBlockFormat()
                block_fmt.setIndent(0)
                cursor.setBlockFormat(block_fmt)
        else:
            block_fmt = cursor.blockFormat()
            if block_fmt.indent() > 0:
                block_fmt.setIndent(block_fmt.indent() - 1)
                cursor.setBlockFormat(block_fmt)
        cursor.endEditBlock()
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        self._trigger_auto_save()

    def _set_plan_font_size(self, size: int) -> None:
        cursor = self.plan_editor.textCursor()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(size))
        cursor.mergeCharFormat(fmt)
        if cursor.currentList():
            cursor.mergeBlockCharFormat(fmt)
        self.plan_editor.mergeCurrentCharFormat(fmt)
        self.plan_editor.setFocus()
        self._update_plan_toolbar_state()
        QTimer.singleShot(0, lambda: self.plan_font_spin.lineEdit().deselect())
        self._trigger_auto_save()

    def _update_plan_toolbar_state(self) -> None:
        if not hasattr(self, "plan_editor"):
            return
        enabled = self.plan_editor.isEnabled()
        for control in getattr(self, "_plan_format_controls", []):
            control.setEnabled(enabled)
        if not enabled:
            return

        cursor = self.plan_editor.textCursor()
        fmt = cursor.charFormat()
        self.plan_bold_btn.setChecked(fmt.fontWeight() == QFont.Weight.Bold)
        self.plan_italic_btn.setChecked(fmt.fontItalic())
        self.plan_underline_btn.setChecked(fmt.fontUnderline())

        current_list = cursor.currentList()
        list_style = current_list.format().style() if current_list else None
        self.plan_bullet_btn.setChecked(list_style == QTextListFormat.Style.ListDisc)

        size = fmt.fontPointSize()
        if size > 0:
            self.plan_font_spin.blockSignals(True)
            self.plan_font_spin.setValue(int(size))
            self.plan_font_spin.blockSignals(False)

    def _set_plan_controls_enabled(self, enabled: bool) -> None:
        # Keep the loader clickable so users can get feedback if no session is active.
        self.load_plan_btn.setEnabled(True)
        self.plan_editor.setEnabled(enabled)
        self._update_plan_toolbar_state()

    def _browse_plan_text_file(self) -> None:
        if not self._current_session:
            # Attempt to load currently selected row first.
            self._load_selected_session()
        if not self._current_session:
            QMessageBox.information(self, "No Session Selected", "Create or select a session first.")
            return
        start_dir = os.path.expanduser("~")
        if self._current_session.document_path:
            start_dir = str(Path(self._current_session.document_path).parent)
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Plan Text File",
            start_dir,
            "Text Files (*.txt *.md *.markdown *.rst *.log);;All Files (*)",
        )
        if not filename:
            return
        self._current_session.document_path = filename
        self._load_plan_text_file(filename)
        self._trigger_auto_save()

    def _load_plan_text_file(self, path: Optional[str], fallback_text: str = "") -> None:
        self._loading_plan_text = True
        self.plan_editor.blockSignals(True)
        if not path:
            self.plan_editor.setPlainText(fallback_text or "")
            self.plan_path_label.setText("No text file loaded")
            self.plan_editor.blockSignals(False)
            self._loading_plan_text = False
            self._update_plan_toolbar_state()
            return

        text_path = Path(path)
        text = fallback_text or ""
        if text_path.exists():
            try:
                text = text_path.read_text(encoding="utf-8")
            except Exception as exc:
                self._report_io_failure(
                    "Load Failed",
                    f"Unable to load plan text:\n{text_path}\n\n{exc}",
                )
        self.plan_editor.setPlainText(text)
        self.plan_path_label.setText(text_path.name if text_path.name else str(text_path))
        self.plan_editor.blockSignals(False)
        self._loading_plan_text = False
        self._update_plan_toolbar_state()

    def _on_plan_text_changed(self) -> None:
        if self._loading_plan_text:
            return
        self._trigger_auto_save()

    def _set_file_controls_enabled(self, enabled: bool) -> None:
        self.files_table.setEnabled(enabled)
        self.add_file_btn.setEnabled(enabled)
        self.files_text_editor.setReadOnly(not enabled)
        self.files_zoom_in_button.setEnabled(enabled)
        self.files_zoom_out_button.setEnabled(enabled)
        self.files_edge_toggle_btn.setEnabled(enabled)
        self._update_file_action_states()

    def _update_file_action_states(self) -> None:
        enabled = bool(self._current_session and self.files_table.isEnabled())
        has_selection = self._current_attachment() is not None
        self.remove_file_btn.setEnabled(enabled and has_selection)
        self.open_file_external_btn.setEnabled(enabled and has_selection)
        is_image_preview = self.files_preview_stack.currentWidget() is self.files_image_page
        self.files_zoom_label.setVisible(is_image_preview)
        self.files_zoom_in_button.setVisible(is_image_preview)
        self.files_zoom_out_button.setVisible(is_image_preview)
        self.files_zoom_in_button.setEnabled(enabled and is_image_preview)
        self.files_zoom_out_button.setEnabled(enabled and is_image_preview)

    def _toggle_files_list_panel(self) -> None:
        if not hasattr(self, "files_splitter"):
            return
        current_left = self.files_splitter.sizes()[0] if self.files_splitter.sizes() else 0
        if self._files_splitter_animation.state() == QVariantAnimation.State.Running:
            self._files_splitter_animation.stop()
        target_collapsed = not self._files_list_collapsed
        self.files_edge_toggle_btn.set_collapsed(target_collapsed)
        if self._files_list_collapsed:
            self.files_splitter.setHandleWidth(10)
            self.files_list_panel.setVisible(True)
            self.files_list_content.setVisible(True)
            target_left = max(220, int(self._files_last_expanded_width))
        else:
            self._files_last_expanded_width = max(220, int(current_left))
            self.files_list_content.setVisible(False)
            target_left = max(FILES_COLLAPSED_STRIP_WIDTH, 0)
        self._files_splitter_animation.setStartValue(int(current_left))
        self._files_splitter_animation.setEndValue(int(target_left))
        self._files_splitter_animation.start()

    def _on_files_splitter_anim_step(self, value) -> None:
        if not hasattr(self, "files_splitter"):
            return
        try:
            left_width = int(value)
        except Exception:
            left_width = 0
        self._set_files_splitter_left_width(left_width)

    def _set_files_splitter_left_width(self, left_width: int) -> None:
        total = sum(self.files_splitter.sizes())
        if total <= 0:
            total = max(1, self.files_splitter.width())
        clamped_left = max(0, min(total, int(left_width)))
        right_width = max(0, total - clamped_left)
        self.files_splitter.setSizes([clamped_left, right_width])
        self._position_files_edge_toggle()

    def _on_files_splitter_anim_finished(self) -> None:
        left_width = self.files_splitter.sizes()[0] if self.files_splitter.sizes() else 0
        self._files_list_collapsed = left_width <= (FILES_COLLAPSED_STRIP_WIDTH + 2)
        if not self._files_list_collapsed:
            self._files_last_expanded_width = max(220, int(left_width))
            self.files_splitter.setHandleWidth(10)
        else:
            self.files_splitter.setHandleWidth(0)
        self.files_list_panel.setVisible(True)
        self.files_list_content.setVisible(not self._files_list_collapsed)
        self.files_edge_toggle_btn.set_collapsed(self._files_list_collapsed)
        self._position_files_edge_toggle()

    def _on_files_splitter_moved(self, pos: int, index: int) -> None:
        if self._files_splitter_animation.state() == QVariantAnimation.State.Running:
            return
        left_width = self.files_splitter.sizes()[0] if self.files_splitter.sizes() else 0
        self._files_list_collapsed = left_width <= (FILES_COLLAPSED_STRIP_WIDTH + 2)
        if not self._files_list_collapsed:
            self._files_last_expanded_width = max(220, int(left_width))
            self.files_splitter.setHandleWidth(10)
        else:
            self.files_splitter.setHandleWidth(0)
        self.files_list_panel.setVisible(True)
        self.files_list_content.setVisible(not self._files_list_collapsed)
        self.files_edge_toggle_btn.set_collapsed(self._files_list_collapsed)
        self._position_files_edge_toggle()

    def _position_files_edge_toggle(self) -> None:
        if (
            not hasattr(self, "files_splitter")
            or not hasattr(self, "files_edge_toggle_btn")
            or not hasattr(self, "files_preview_panel")
        ):
            return
        preview_panel = self.files_preview_panel
        if preview_panel.width() <= 0 or preview_panel.height() <= 0:
            return
        btn = self.files_edge_toggle_btn
        x = 4
        y = max(0, (preview_panel.height() - btn.height()) // 2)
        btn.move(x, y)
        btn.raise_()
        btn.show()

    def _on_reference_tab_changed(self, index: int) -> None:
        if not hasattr(self, "ref_tabs") or not hasattr(self, "files_edge_toggle_btn"):
            return
        is_files_tab = self.ref_tabs.tabText(index) == "Files"
        if is_files_tab:
            self._position_files_edge_toggle()
            self.files_edge_toggle_btn.show()

    def _refresh_file_table(self, *, selected_attachment_id: Optional[str] = None) -> None:
        session = self._current_session
        self.files_table.blockSignals(True)
        self.files_table.setRowCount(0)
        if not session:
            self.files_table.blockSignals(False)
            self._show_empty_file_preview("No file selected.")
            self._update_file_action_states()
            return
        target_row: Optional[int] = None
        for row, attachment in enumerate(session.attachments):
            self.files_table.insertRow(row)
            name_item = QTableWidgetItem(attachment.name)
            name_item.setData(Qt.ItemDataRole.UserRole, attachment.id)
            type_item = QTableWidgetItem(attachment.mime or _detect_mime(attachment.name))
            size_item = QTableWidgetItem(_format_size(attachment.size_bytes))
            updated_item = QTableWidgetItem(attachment.updated_at or attachment.added_at or "")
            self.files_table.setItem(row, 0, name_item)
            self.files_table.setItem(row, 1, type_item)
            self.files_table.setItem(row, 2, size_item)
            self.files_table.setItem(row, 3, updated_item)
            if selected_attachment_id and attachment.id == selected_attachment_id:
                target_row = row
        if target_row is None and self.files_table.rowCount() > 0:
            target_row = 0
        if target_row is not None:
            self.files_table.selectRow(target_row)
        self.files_table.blockSignals(False)
        self._on_selected_file_changed()
        self._update_file_action_states()

    def _refresh_file_row(self, attachment_id: str) -> None:
        session = self._current_session
        if not session:
            return
        attachment = next((a for a in session.attachments if a.id == attachment_id), None)
        if attachment is None:
            return
        for row in range(self.files_table.rowCount()):
            row_item = self.files_table.item(row, 0)
            if row_item is None:
                continue
            if row_item.data(Qt.ItemDataRole.UserRole) != attachment_id:
                continue
            mime = attachment.mime or _detect_mime(attachment.name)
            self.files_table.setItem(row, 1, QTableWidgetItem(mime))
            self.files_table.setItem(row, 2, QTableWidgetItem(_format_size(attachment.size_bytes)))
            self.files_table.setItem(
                row,
                3,
                QTableWidgetItem(attachment.updated_at or attachment.added_at or ""),
            )
            break

    def _current_attachment(self) -> Optional[SessionAttachment]:
        session = self._current_session
        if not session:
            return None
        row = self.files_table.currentRow()
        if row < 0:
            return None
        name_item = self.files_table.item(row, 0)
        if name_item is None:
            return None
        attachment_id = str(name_item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not attachment_id:
            return None
        return next((a for a in session.attachments if a.id == attachment_id), None)

    def _show_empty_file_preview(self, message: str) -> None:
        self._active_text_attachment_id = None
        self.files_preview_title.setText("Select an attached file")
        self.files_empty_page.setText(message)
        self.files_text_editor.blockSignals(True)
        self.files_text_editor.setPlainText("")
        self.files_text_editor.blockSignals(False)
        self.files_image_view.load_image(None)
        self.files_zoom_label.setText("100%")
        self.files_preview_stack.setCurrentWidget(self.files_empty_page)
        self._update_file_action_states()

    def _on_selected_file_changed(self) -> None:
        session = self._current_session
        attachment = self._current_attachment()
        if not session or attachment is None:
            self._show_empty_file_preview("No file selected.")
            return

        self.files_preview_title.setText(attachment.name)
        raw = self.manager.get_attachment_bytes(session.id, attachment.id)
        if raw is None:
            self._active_text_attachment_id = None
            self.files_unsupported_page.setText(
                f"Attachment asset missing for '{attachment.name}'."
            )
            self.files_preview_stack.setCurrentWidget(self.files_unsupported_page)
            self._update_file_action_states()
            return

        suffix = Path(attachment.name).suffix.lower()
        mime = attachment.mime or _detect_mime(attachment.name)
        attachment.mime = mime

        if suffix in IMAGE_FILE_EXTENSIONS or mime.startswith("image/"):
            runtime_path = self._materialize_attachment_runtime_path(attachment, raw)
            self.files_image_view.load_image(str(runtime_path))
            if self.files_image_view._pixmap_item.pixmap().isNull():
                self._active_text_attachment_id = None
                self.files_unsupported_page.setText(
                    f"Unable to decode preview for '{attachment.name}'."
                )
                self.files_preview_stack.setCurrentWidget(self.files_unsupported_page)
            else:
                self._active_text_attachment_id = None
                self.files_preview_stack.setCurrentWidget(self.files_image_page)
                self.files_zoom_label.setText("100%")
            self._update_file_action_states()
            return

        if attachment.is_text or _is_text_extension(attachment.name, mime):
            decoded = raw.decode("utf-8", errors="replace")
            self._loading_attachment_text = True
            self.files_text_editor.blockSignals(True)
            self.files_text_editor.setPlainText(decoded)
            self.files_text_editor.blockSignals(False)
            self._loading_attachment_text = False
            self._active_text_attachment_id = attachment.id
            self.files_text_status.setText(
                "Editing attached copy (source file is never modified)."
            )
            self.files_preview_stack.setCurrentWidget(self.files_text_page)
            self._update_file_action_states()
            return

        if suffix in PDF_FILE_EXTENSIONS or mime == "application/pdf":
            self._active_text_attachment_id = None
            if self.files_pdf_viewer is not None:
                runtime_path = self._materialize_attachment_runtime_path(attachment, raw)
                self.files_pdf_viewer.load_pdf(str(runtime_path))
            self.files_preview_stack.setCurrentWidget(self.files_pdf_page)
            self._update_file_action_states()
            return

        self._active_text_attachment_id = None
        self.files_unsupported_page.setText(
            f"Preview unavailable for '{attachment.name}' ({mime}). Use Open to view externally."
        )
        self.files_preview_stack.setCurrentWidget(self.files_unsupported_page)
        self._update_file_action_states()

    def _attachment_runtime_dir(self) -> Path:
        session = self._current_session
        session_id = sanitize_filename(session.id) if session else "session"
        return Path(default_dnd_save_dir()) / "cache" / "session_attachments" / session_id

    def _materialize_attachment_runtime_path(
        self, attachment: SessionAttachment, payload: bytes
    ) -> Path:
        runtime_dir = self._attachment_runtime_dir()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        file_name = _safe_attachment_filename(attachment.name)
        runtime_path = runtime_dir / f"{sanitize_filename(attachment.id)}_{file_name}"
        try:
            if not runtime_path.exists() or runtime_path.read_bytes() != payload:
                runtime_path.write_bytes(payload)
        except Exception:
            runtime_path.write_bytes(payload)
        return runtime_path

    def _session_attachment_total_size(self, session: Session) -> int:
        total = 0
        for attachment in session.attachments:
            payload = self.manager.get_attachment_bytes(session.id, attachment.id)
            if payload is not None:
                total += len(payload)
            else:
                total += max(0, int(attachment.size_bytes))
        return total

    def _attach_files_to_session(self) -> None:
        if not self._current_session:
            QMessageBox.information(self, "No Session Selected", "Create or select a session first.")
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach Files",
            os.path.expanduser("~"),
            "All Files (*)",
        )
        if not files:
            return
        session = self._current_session
        total_size = self._session_attachment_total_size(session)
        added_ids: list[str] = []
        for file_name in files:
            source_path = Path(file_name)
            try:
                payload = source_path.read_bytes()
            except Exception as exc:
                self._report_io_failure(
                    "Attach Failed",
                    f"Unable to read file:\n{source_path}\n\n{exc}",
                )
                continue

            payload_size = len(payload)
            if payload_size > MAX_ATTACHMENT_FILE_BYTES:
                QMessageBox.warning(
                    self,
                    "File Too Large",
                    f"'{source_path.name}' exceeds the 25 MB per-file limit.",
                )
                continue
            if total_size + payload_size > MAX_TOTAL_ATTACHMENT_BYTES:
                QMessageBox.warning(
                    self,
                    "Session Limit Reached",
                    "Adding this file would exceed the 150 MB session attachment limit.",
                )
                continue

            attachment_id = generate_probabilistic_unique_id("att")
            mime = _detect_mime(source_path.name)
            now = _now_timestamp()
            attachment = SessionAttachment(
                id=attachment_id,
                name=source_path.name,
                asset_path=_attachment_asset_name(attachment_id, source_path.name),
                mime=mime,
                size_bytes=payload_size,
                sha256=_hash_bytes(payload),
                source_name=source_path.name,
                source_path=str(source_path),
                added_at=now,
                updated_at=now,
                is_text=_is_text_extension(source_path.name, mime),
            )
            session.attachments.append(attachment)
            self.manager.set_attachment_bytes(session.id, attachment_id, payload)
            total_size += payload_size
            added_ids.append(attachment_id)

        if not added_ids:
            return
        self._refresh_file_table(selected_attachment_id=added_ids[-1])
        self._trigger_auto_save()

    def _remove_selected_file(self) -> None:
        session = self._current_session
        attachment = self._current_attachment()
        if not session or attachment is None:
            return
        session.attachments = [a for a in session.attachments if a.id != attachment.id]
        self.manager.remove_attachment_bytes(session.id, attachment.id)
        if self._active_text_attachment_id == attachment.id:
            self._active_text_attachment_id = None
        self._refresh_file_table()
        self._trigger_auto_save()

    def _open_selected_file_externally(self) -> None:
        session = self._current_session
        attachment = self._current_attachment()
        if not session or attachment is None:
            return
        payload = self.manager.get_attachment_bytes(session.id, attachment.id)
        if payload is None:
            QMessageBox.warning(self, "Missing File", "Attachment data is not available.")
            return
        runtime_path = self._materialize_attachment_runtime_path(attachment, payload)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(runtime_path))):
            QMessageBox.warning(self, "Open Failed", "Unable to open attachment externally.")

    def _on_file_text_changed(self) -> None:
        if self._loading_attachment_text:
            return
        session = self._current_session
        attachment_id = self._active_text_attachment_id
        if not session or not attachment_id:
            return
        attachment = next((a for a in session.attachments if a.id == attachment_id), None)
        if attachment is None:
            return
        payload = self.files_text_editor.toPlainText().encode("utf-8")
        self.manager.set_attachment_bytes(session.id, attachment_id, payload)
        attachment.size_bytes = len(payload)
        attachment.sha256 = _hash_bytes(payload)
        attachment.updated_at = _now_timestamp()
        attachment.mime = attachment.mime or _detect_mime(attachment.name)
        attachment.is_text = True
        self._refresh_file_row(attachment_id)
        self._trigger_auto_save()
