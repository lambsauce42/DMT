from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QTimer, QSize
from PyQt6.QtGui import (
    QAction,
    QIcon,
    QColor,
    QPixmap,
    QDesktopServices,
    QKeySequence,
    QShortcut,
    QTextCharFormat,
    QTextBlockFormat,
    QTextListFormat,
    QFont,
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
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QGroupBox,
    QFileDialog,
    QMenu,
    QSpinBox,
)

from models import Session, SessionLogEntry
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
from ui.widgets import TerminalWidget
from ui.widgets.rich_text_editor import RichTextDescriptionEditor


# Attempt to import PDF Viewer
PDFIUM_VIEW_AVAILABLE = False
try:
    from ui.character_sheet_panel import CharacterSheetPanel
    PDFIUM_VIEW_AVAILABLE = True
except Exception:
    pass

SESSION_DIR_NAME = "sessions"
SESSION_JSON_NAME = "sessions.json"
SESSION_FILE_EXTENSION = ".dmtsession"
ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))


def session_storage_dir() -> Path:
    # MD specifies: ~/Documents/DMT/sessions/ 
    # save_paths.default_dnd_save_dir() returns ~/Documents/DMT (or equivalent)
    return Path(default_dnd_save_dir()) / SESSION_DIR_NAME

def session_storage_path() -> Path:
    return session_storage_dir() / SESSION_JSON_NAME

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


class SessionManager:
    def __init__(self) -> None:
        self.sessions: List[Session] = []
        self.last_error: str = ""
        self.load()

    def load(self) -> None:
        self.last_error = ""
        self.sessions = []
        storage_root = session_storage_path().parent
        legacy_path = session_storage_path()
        loaded_any = False

        if storage_root.exists():
            session_files = sorted(storage_root.glob(f"*{SESSION_FILE_EXTENSION}"))
            if session_files:
                loaded_any = True
            for file_path in session_files:
                try:
                    payload = json.loads(file_path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        self.sessions.append(self._dict_to_session(payload))
                except Exception as exc:
                    self.last_error = f"Unable to load session from '{file_path}': {exc}"

        if loaded_any:
            return

        if not legacy_path.exists():
            return
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                for item in data:
                    self.sessions.append(self._dict_to_session(item))
        except Exception as exc:
            self.last_error = f"Unable to load sessions from '{legacy_path}': {exc}"

    def save(self) -> None:
        storage_root = session_storage_path().parent
        storage_root.mkdir(parents=True, exist_ok=True)
        expected_files: set[Path] = set()

        for session in self.sessions:
            file_path = session_file_path(session.id, storage_root)
            expected_files.add(file_path.resolve())
            payload = self._session_to_dict(session)
            file_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
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

    def _dict_to_session(self, d: dict) -> Session:
        logs = [SessionLogEntry(**l) for l in d.get("logs", [])]
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

    def add_session(self, session: Session) -> None:
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
        self.save()


class SessionCreatorWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.manager = SessionManager()
        self._current_session: Optional[Session] = None
        self._current_session_dirty = False
        self._loading_plan_text = False
        
        self._world_data = WORLD_DATA
        
        self.sheets_manager = PlayerSheetsManager(entries=self._load_sheet_entries())

        # Auto-save timer
        self.auto_save_timer = QTimer()
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
            QTimer.singleShot(
                0,
                lambda msg=self.manager.last_error: QMessageBox.warning(
                    self,
                    "Session Load Failed",
                    msg,
                ),
            )

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
            # Backward compatibility: legacy group-only storage.
            return "", "", raw
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

        # Initialize Combo Boxes
        _populate_combo(self.world_combo, self._world_options())
        self._on_world_changed() # Trigger cascade

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

    def _load_session_to_ui(self, session: Session, *, apply_context: bool) -> None:
        self._set_current_session_dirty(False)
        self._set_plan_controls_enabled(True)
        self.scratchpad.blockSignals(True)
        self.scratchpad.setHtml(session.notes)
        self.scratchpad.blockSignals(False)
        self._load_plan_text_file(session.document_path, fallback_text=session.plan_text)

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
