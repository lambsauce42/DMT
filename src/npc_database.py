from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import (
    QIcon,
    QTextCursor,
    QTextListFormat,
    QTextCharFormat,
    QTextBlockFormat,
    QFont,
    QCursor,
    QTextDocument,
)
from PyQt6.QtWidgets import (
    QApplication,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QScrollArea,
    QPlainTextEdit,
    QTextEdit,
    QSpinBox,
)

from dmt_package import read_dmt_package_info, write_dmt_package
from navigate_widget import load_navigation_data
from ui.widgets.rich_text_editor import RichTextDescriptionEditor
from unique_ids import generate_probabilistic_unique_id

ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
RESET_ICON = os.path.join(ICON_DIR, "reset.svg")
from player_sheets import (
    _combo_optional_value,
    _populate_combo,
    default_sheet_save_dir,
    list_campaigns,
    list_groups,
    list_worlds,
    normalize_tags,
    parse_tag_query,
    resolve_selection,
    sanitize_filename,
)

NPCS_DIR_NAME = "npcs"
NPCS_FILE_EXTENSION = ".dmtnpc"
NPCS_FILE_FORMAT = "dmtnpc.v1"
NPCS_TRASH_NAME = "npc_trash.json"

NPC_SORT_OPTIONS = [
    "Name",
    "Location",
    "Recently Edited",
    "World/Campaign",
]


def _now_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


def npc_storage_dir() -> Path:
    return Path(default_sheet_save_dir()) / NPCS_DIR_NAME


def npc_storage_path() -> Path:
    return npc_storage_dir() / "npcs.dmtindex"


def npc_file_path(npc_id: str) -> Path:
    safe_name = sanitize_filename(str(npc_id or "").strip()) or "npc"
    return npc_storage_dir() / f"{safe_name}{NPCS_FILE_EXTENSION}"


def npc_trash_path() -> Path:
    return npc_storage_dir() / "trash" / NPCS_TRASH_NAME


def _split_search(text: str) -> List[str]:
    if not text:
        return []
    tokens = re.split(r"[,\s]+", text.strip().lower())
    return [token for token in tokens if token]


def _description_as_plain_text(value: str) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    lowered = raw.lstrip().lower()
    likely_html = "<" in raw and (
        "</" in raw or "<p" in lowered or "<html" in lowered or "<span" in lowered
    )
    if not likely_html:
        return raw
    doc = QTextDocument()
    doc.setHtml(raw)
    return doc.toPlainText()


@dataclass
class NPCEntry:
    id: str
    name: str
    role: str = ""
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    location: str = ""
    tags: List[str] = field(default_factory=list)
    description: str = ""
    sessions: List[str] = field(default_factory=list)
    encounters: List[str] = field(default_factory=list)
    loot: List[str] = field(default_factory=list)
    created_at: str = ""
    last_modified: str = ""
    archived: bool = False

    def __post_init__(self) -> None:
        self.tags = normalize_tags(self.tags)


def entry_to_dict(entry: NPCEntry) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "role": entry.role,
        "world": entry.world,
        "campaign": entry.campaign,
        "group": entry.group,
        "location": entry.location,
        "tags": list(entry.tags),
        "description": entry.description,
        "sessions": list(entry.sessions),
        "encounters": list(entry.encounters),
        "loot": list(entry.loot),
        "created_at": entry.created_at,
        "last_modified": entry.last_modified,
        "archived": entry.archived,
    }


def entry_from_dict(payload: dict) -> Optional[NPCEntry]:
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "")).strip()
    if not name:
        return None
    tags = payload.get("tags") or []
    sessions = payload.get("sessions") or []
    encounters = payload.get("encounters") or []
    loot = payload.get("loot") or []
    if not isinstance(tags, list):
        tags = []
    if not isinstance(sessions, list):
        sessions = []
    if not isinstance(encounters, list):
        encounters = []
    if not isinstance(loot, list):
        loot = []
    return NPCEntry(
        id=str(payload.get("id") or sanitize_filename(name)),
        name=name,
        role=str(payload.get("role") or "").strip(),
        world=payload.get("world") or None,
        campaign=payload.get("campaign") or None,
        group=payload.get("group") or None,
        location=str(payload.get("location") or "").strip(),
        tags=normalize_tags([str(tag) for tag in tags if str(tag).strip()]),
        description=str(payload.get("description") or "").strip(),
        sessions=[str(value) for value in sessions if str(value).strip()],
        encounters=[str(value) for value in encounters if str(value).strip()],
        loot=[str(value) for value in loot if str(value).strip()],
        created_at=str(payload.get("created_at") or "").strip(),
        last_modified=str(payload.get("last_modified") or "").strip(),
        archived=bool(payload.get("archived", False)),
    )


def save_trash(entries: list[dict], path: Optional[Path] = None) -> None:
    target = path or npc_trash_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def load_trash(path: Optional[Path] = None) -> list[dict]:
    target = path or npc_trash_path()
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def move_to_trash(entry: NPCEntry) -> None:
    trash = load_trash()
    trash.append(
        {
            "type": "npc",
            "name": entry.name,
            "payload": entry_to_dict(entry),
            "deleted_at": _now_timestamp(),
        }
    )
    save_trash(trash)


def matches_filters(
    entry: NPCEntry,
    world: Optional[str],
    campaign: Optional[str],
    group: Optional[str],
    tag_query: str,
    search_query: str,
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

    search_tokens = _split_search(search_query)
    if search_tokens:
        haystack = " ".join(
            [
                entry.name,
                entry.role,
                entry.location,
                entry.description,
                " ".join(entry.tags),
                entry.world or "",
                entry.campaign or "",
                entry.group or "",
            ]
        ).lower()
        if not all(token in haystack for token in search_tokens):
            return False

    return True


def filter_entries(
    entries: Iterable[NPCEntry],
    world: Optional[str] = None,
    campaign: Optional[str] = None,
    group: Optional[str] = None,
    tag_query: str = "",
    search_query: str = "",
) -> List[NPCEntry]:
    return [
        entry
        for entry in entries
        if matches_filters(entry, world, campaign, group, tag_query, search_query)
    ]


def _sort_timestamp(entry: NPCEntry) -> str:
    return entry.last_modified or entry.created_at or ""


def sort_entries(entries: Iterable[NPCEntry], sort_key: str) -> List[NPCEntry]:
    if sort_key == "Location":
        return sorted(entries, key=lambda entry: entry.location.lower())
    if sort_key == "Recently Edited":
        return sorted(entries, key=_sort_timestamp, reverse=True)
    if sort_key == "World/Campaign":
        return sorted(
            entries,
            key=lambda entry: (
                (entry.world or "").lower(),
                (entry.campaign or "").lower(),
                (entry.group or "").lower(),
                entry.name.lower(),
            ),
        )
    return sorted(entries, key=lambda entry: entry.name.lower())


@dataclass
class NPCFilters:
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    tag_query: str = ""
    search_query: str = ""
    sort_key: str = NPC_SORT_OPTIONS[0]


class NPCManager:
    def __init__(self, entries: Optional[List[NPCEntry]] = None) -> None:
        self.entries = list(entries or [])
        self.filters = NPCFilters()

    def set_filters(
        self,
        world: Optional[str],
        campaign: Optional[str],
        group: Optional[str],
        tag_query: str,
        search_query: str,
        sort_key: str,
    ) -> None:
        self.filters = NPCFilters(
            world=world,
            campaign=campaign,
            group=group,
            tag_query=tag_query,
            search_query=search_query,
            sort_key=sort_key or NPC_SORT_OPTIONS[0],
        )

    def add_entry(self, entry: NPCEntry) -> None:
        self.entries.append(entry)

    def update_entry(self, entry: NPCEntry) -> None:
        for index, existing in enumerate(self.entries):
            if existing.id == entry.id:
                self.entries[index] = entry
                return
        self.entries.append(entry)

    def delete_entry(self, entry_id: str) -> None:
        self.entries = [entry for entry in self.entries if entry.id != entry_id]

    def filtered_entries(self) -> List[NPCEntry]:
        filtered = filter_entries(
            self.entries,
            world=self.filters.world,
            campaign=self.filters.campaign,
            group=self.filters.group,
            tag_query=self.filters.tag_query,
            search_query=self.filters.search_query,
        )
        return sort_entries(filtered, self.filters.sort_key)


class NPCDialog(QDialog):
    def __init__(
        self,
        world_data: list[dict],
        parent: Optional[QWidget] = None,
        entry: Optional[NPCEntry] = None,
    ) -> None:
        super().__init__(parent)
        self._world_data = world_data
        self._entry: Optional[NPCEntry] = None
        self._original_entry = entry

        self.setWindowTitle("Edit NPC" if entry else "New NPC")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self._name_input = QLineEdit()
        form.addRow("Name", self._name_input)

        self._role_input = QLineEdit()
        form.addRow("Role/Title", self._role_input)

        self._location_input = QLineEdit()
        form.addRow("Location", self._location_input)

        self._world_combo = QComboBox()
        self._campaign_combo = QComboBox()
        self._group_combo = QComboBox()
        form.addRow("World", self._world_combo)
        form.addRow("Campaign", self._campaign_combo)
        form.addRow("Group", self._group_combo)

        self._tags_input = QLineEdit()
        self._tags_input.setPlaceholderText("comma, separated, tags")
        form.addRow("Tags", self._tags_input)

        self._description_input = QPlainTextEdit()
        self._description_input.setPlaceholderText(
            "Description, notes, and notable traits"
        )
        self._description_input.setMinimumHeight(120)
        form.addRow("Description", self._description_input)

        layout.addLayout(form)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self._buttons.accepted.connect(self._on_accept)
        self._buttons.rejected.connect(self.reject)
        layout.addWidget(self._buttons)

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

        if entry:
            self._name_input.setText(entry.name)
            self._role_input.setText(entry.role)
            self._location_input.setText(entry.location)
            if entry.tags:
                self._tags_input.setText(", ".join(entry.tags))
            if entry.description:
                self._description_input.setPlainText(
                    _description_as_plain_text(entry.description)
                )

    def entry(self) -> Optional[NPCEntry]:
        return self._entry

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

    def _on_accept(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Please enter an NPC name.")
            return
        now = _now_timestamp()
        entry_id = (
            self._original_entry.id
            if self._original_entry
            else sanitize_filename(name)
        )
        created_at = self._original_entry.created_at if self._original_entry else now
        self._entry = NPCEntry(
            id=entry_id,
            name=name,
            role=self._role_input.text().strip(),
            world=_combo_optional_value(self._world_combo),
            campaign=_combo_optional_value(self._campaign_combo),
            group=_combo_optional_value(self._group_combo),
            location=self._location_input.text().strip(),
            tags=parse_tag_query(self._tags_input.text()),
            description=self._description_input.toPlainText().strip(),
            sessions=list(self._original_entry.sessions) if self._original_entry else [],
            encounters=list(self._original_entry.encounters)
            if self._original_entry
            else [],
            loot=list(self._original_entry.loot) if self._original_entry else [],
            created_at=created_at,
            last_modified=now,
            archived=self._original_entry.archived if self._original_entry else False,
        )
        self.accept()






class NPCDatabaseWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._world_data = load_navigation_data()
        self._storage_path = npc_storage_path()
        self._manager = NPCManager(entries=self._load_entries())
        self._current_entry: Optional[NPCEntry] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        filter_bar = QFrame(self)
        filter_bar.setObjectName("Panel")
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(10)

        self._world_combo = QComboBox()
        self._campaign_combo = QComboBox()
        self._group_combo = QComboBox()
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Tags: merchant, guard")

        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search names, descriptions...")
        
        self._sort_combo = QComboBox()
        # NPC_SORT_OPTIONS is likely defined globally
        self._sort_combo.addItems(NPC_SORT_OPTIONS)
        self._sort_combo.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._reset_world_button = self._make_reset_button("Reset World")
        self._reset_world_button.clicked.connect(self._reset_world_filter)

        self._reset_campaign_button = self._make_reset_button("Reset Campaign")
        self._reset_campaign_button.clicked.connect(self._reset_campaign_filter)

        self._reset_group_button = self._make_reset_button("Reset Group")
        self._reset_group_button.clicked.connect(self._reset_group_filter)

        self._reset_tags_button = self._make_reset_button("Reset Tags")
        self._reset_tags_button.clicked.connect(self._reset_tags_filter)

        self._reset_search_button = self._make_reset_button("Reset Search")
        self._reset_search_button.clicked.connect(self._reset_search_filter)

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
        filter_layout.addWidget(
            self._build_filter_field("Search", self._search_input, self._reset_search_button),
            1,
        )
        filter_layout.addWidget(self._build_filter_field("Sort", self._sort_combo), 1)

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
        self._new_button.clicked.connect(self._open_new_npc_dialog)
        filter_layout.addWidget(self._new_button, 0, Qt.AlignmentFlag.AlignTop)

        layout.addWidget(filter_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        list_panel = QFrame(self)
        list_panel.setObjectName("Panel")
        list_panel.setMinimumWidth(320)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(10, 10, 10, 10)
        list_layout.setSpacing(8)

        list_title = QLabel("NPCs")
        list_title.setObjectName("PanelTitle")
        list_layout.addWidget(list_title)

        self._npc_list = QListWidget()
        self._npc_list.setObjectName("NavList")
        self._npc_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._npc_list.currentItemChanged.connect(self._on_npc_selected)
        list_layout.addWidget(self._npc_list, 1)

        splitter.addWidget(list_panel)

        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        header_panel = QFrame(self)
        header_panel.setObjectName("Panel")
        header_layout = QHBoxLayout(header_panel)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._header_name = QLabel("NPC: None")
        self._header_name.setObjectName("PanelTitle")
        header_layout.addWidget(self._header_name, 1)

        self._duplicate_button = QToolButton()
        self._duplicate_button.setObjectName("PrimaryButton")
        self._duplicate_button.setIcon(QIcon(os.path.join(ICON_DIR, "copy.svg")))
        self._duplicate_button.setToolTip("Duplicate NPC")
        self._duplicate_button.clicked.connect(self._duplicate_current_npc)

        self._edit_button = QToolButton()
        self._edit_button.setObjectName("SecondaryButton")
        self._edit_button.setIcon(QIcon(os.path.join(ICON_DIR, "edit.svg")))
        self._edit_button.setToolTip("Edit NPC Settings")
        self._edit_button.clicked.connect(self._open_edit_npc_dialog)

        self._save_button = QToolButton()
        self._save_button.setObjectName("SecondaryButton")
        self._save_button.setIcon(QIcon(os.path.join(ICON_DIR, "save.svg")))
        self._save_button.setToolTip("Save")
        self._save_button.clicked.connect(self._save_current_npc)

        self._delete_button = QToolButton()
        self._delete_button.setObjectName("DestructiveButton")
        self._delete_button.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
        self._delete_button.setToolTip("Delete to Trash")
        self._delete_button.clicked.connect(self._delete_current_npc)

        self._disintegrate_button = QToolButton()
        self._disintegrate_button.setObjectName("DestructiveButton")
        self._disintegrate_button.setIcon(QIcon(os.path.join(ICON_DIR, "disintegrate.svg")))
        self._disintegrate_button.setToolTip("Permanently Delete")
        self._disintegrate_button.clicked.connect(self._disintegrate_current_npc)

        for btn in (
            # self._add_button, Removed
            self._duplicate_button,
            self._edit_button,
            self._save_button,
            self._delete_button,
            self._disintegrate_button,
        ):
            btn.setFixedSize(36, 36)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet("""
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
            btn.setIconSize(QSize(20, 20))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            header_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

        right_layout.addWidget(header_panel)

        details_panel = QFrame(self)
        details_panel.setObjectName("Panel")
        details_layout = QVBoxLayout(details_panel)
        details_layout.setContentsMargins(10, 10, 10, 10)
        details_layout.setSpacing(8)

        details_title = QLabel("Details")
        details_title.setObjectName("PanelTitle")
        details_layout.addWidget(details_title)

        details_scroll = QScrollArea(details_panel)
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.Shape.NoFrame)

        details_body = QWidget(details_scroll)
        details_body_layout = QVBoxLayout(details_body)
        details_body_layout.setContentsMargins(0, 0, 0, 0)
        details_body_layout.setSpacing(8)

        summary_section = self._build_section("Summary")
        summary_layout = QFormLayout()
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(6)
        summary_section.layout().addLayout(summary_layout)

        self._detail_name = QLabel("-")
        self._detail_role = QLabel("-")
        self._detail_world = QLabel("-")
        self._detail_campaign = QLabel("-")
        self._detail_group = QLabel("-")
        self._detail_location = QLabel("-")
        self._detail_tags = QLabel("-")
        self._detail_updated = QLabel("-")
        for label in (
            self._detail_name,
            self._detail_role,
            self._detail_world,
            self._detail_campaign,
            self._detail_group,
            self._detail_location,
            self._detail_tags,
            self._detail_updated,
        ):
            label.setWordWrap(True)

        summary_layout.addRow(self._make_field_label("Name"), self._detail_name)
        summary_layout.addRow(self._make_field_label("Role"), self._detail_role)
        summary_layout.addRow(self._make_field_label("World"), self._detail_world)
        summary_layout.addRow(self._make_field_label("Campaign"), self._detail_campaign)
        summary_layout.addRow(self._make_field_label("Group"), self._detail_group)
        summary_layout.addRow(self._make_field_label("Location"), self._detail_location)
        summary_layout.addRow(self._make_field_label("Tags"), self._detail_tags)
        summary_layout.addRow(self._make_field_label("Last Updated"), self._detail_updated)

        details_body_layout.addWidget(summary_section)

        description_section = self._build_section("Description")
        description_layout = description_section.layout()
        self._description_text = RichTextDescriptionEditor()
        self._description_text.setReadOnly(False)
        self._description_text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._description_text.textChanged.connect(self._on_description_changed)
        description_layout.addWidget(self._description_text)
        details_body_layout.addWidget(description_section, 1)





        # Quick Actions removed per user request

        # details_body_layout.addStretch(1) # Removed stretch to let description expand
        details_scroll.setWidget(details_body)

        details_layout.addWidget(details_scroll, 1)

        right_layout.addWidget(details_panel, 1)

        splitter.addWidget(right_container)
        splitter.setSizes([320, 880])

        layout.addWidget(splitter, 1)

        _populate_combo(self._world_combo, list_worlds(self._world_data))
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)

        self._world_combo.currentIndexChanged.connect(self._on_world_changed)
        self._campaign_combo.currentIndexChanged.connect(self._on_campaign_changed)
        self._group_combo.currentIndexChanged.connect(self._apply_filters)
        self._tag_input.textChanged.connect(self._apply_filters)
        self._search_input.textChanged.connect(self._apply_filters)
        self._sort_combo.currentIndexChanged.connect(self._apply_filters)

        self._apply_filters()

    # def _add_current_npc_to_encounter(self) -> None:
    #     # Placeholder for future integration
    #     QMessageBox.information(self, "Add NPC", "This feature is coming soon!")

    def _make_reset_button(self, tooltip: str) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("InlineResetButton")
        btn.setIcon(QIcon(RESET_ICON))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

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

    def _build_section(self, title: str) -> QFrame:
        section = QFrame(self)
        section.setObjectName("SubPanel")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        label = QLabel(title)
        label.setObjectName("ColumnHeader")
        layout.addWidget(label)
        return section

    def _make_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("Subheader")
        return label

    def _load_entries(self) -> List[NPCEntry]:
        entries: List[NPCEntry] = []
        for path in sorted(npc_storage_dir().glob(f"*{NPCS_FILE_EXTENSION}")):
            info = read_dmt_package_info(path)
            if not isinstance(info, dict):
                continue
            if str(info.get("format") or "") != NPCS_FILE_FORMAT:
                continue
            payload = info.get("payload")
            if not isinstance(payload, dict):
                continue
            if not str(payload.get("id") or "").strip():
                payload = dict(payload)
                payload["id"] = str(info.get("object_id") or "").strip()
            entry = entry_from_dict(payload)
            if entry:
                entries.append(entry)
        return entries

    def _save_entries(self) -> None:
        root = npc_storage_dir()
        root.mkdir(parents=True, exist_ok=True)
        expected: set[Path] = set()
        for entry in self._manager.entries:
            if not str(entry.id or "").strip():
                entry.id = generate_probabilistic_unique_id("npc")
            path = npc_file_path(entry.id)
            expected.add(path.resolve())
            write_dmt_package(
                path,
                info={
                    "format": NPCS_FILE_FORMAT,
                    "object_type": "npc",
                    "object_id": str(entry.id),
                    "name": str(entry.name),
                    "updated_at": _now_timestamp(),
                    "payload": entry_to_dict(entry),
                },
            )
        for existing in root.glob(f"*{NPCS_FILE_EXTENSION}"):
            try:
                resolved = existing.resolve()
            except Exception:
                resolved = existing
            if resolved in expected:
                continue
            try:
                existing.unlink()
            except Exception:
                continue

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

    def _reset_search_filter(self) -> None:
        self._search_input.setText("")

    def _apply_filters(self) -> None:
        self._manager.set_filters(
            world=_combo_optional_value(self._world_combo),
            campaign=_combo_optional_value(self._campaign_combo),
            group=_combo_optional_value(self._group_combo),
            tag_query=self._tag_input.text().strip(),
            search_query=self._search_input.text().strip(),
            sort_key=self._sort_combo.currentText(),
        )
        entries = self._manager.filtered_entries()
        self._refresh_list(entries)

    def _refresh_list(self, entries: List[NPCEntry]) -> None:
        previous_id = self._current_entry.id if self._current_entry else None
        self._npc_list.blockSignals(True)
        self._npc_list.clear()
        selection_index = -1
        for index, entry in enumerate(entries):
            context_parts = [
                part for part in [entry.world, entry.campaign, entry.group] if part
            ]
            context_line = " / ".join(context_parts) if context_parts else "Unassigned"
            role_line = entry.role if entry.role else "No role"
            location_line = entry.location if entry.location else "Unknown location"
            tags_line = ", ".join(entry.tags) if entry.tags else "No tags"
            item_text = "\n".join(
                [
                    f"{entry.name} - {role_line}",
                    context_line,
                    f"Location: {location_line}",
                    f"Tags: {tags_line}",
                ]
            )
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._npc_list.addItem(item)
            if previous_id and entry.id == previous_id:
                selection_index = index
        self._npc_list.blockSignals(False)

        if entries:
            if selection_index == -1:
                selection_index = 0
            self._npc_list.setCurrentRow(selection_index)
        else:
            self._set_details(None)

    def _on_npc_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        entry = None
        if current is not None:
            entry = current.data(Qt.ItemDataRole.UserRole)
        self._set_details(entry)

    def _set_details(self, entry: Optional[NPCEntry]) -> None:
        self._current_entry = entry
        if not entry:
            self._header_name.setText("NPC: None")
            self._edit_button.setEnabled(False)
            self._duplicate_button.setEnabled(False)
            self._delete_button.setEnabled(False)
            self._description_text.setPlainText("")
            self._description_text.setPlaceholderText("Select an NPC to see details.")
            self._detail_name.setText("-")
            self._detail_role.setText("-")
            self._detail_world.setText("-")
            self._detail_campaign.setText("-")
            self._detail_group.setText("-")
            self._detail_location.setText("-")
            self._detail_tags.setText("-")
            self._detail_updated.setText("-")
            self._detail_updated.setText("-")

            return

        self._header_name.setText(f"NPC: {entry.name}")
        self._edit_button.setEnabled(True)
        self._duplicate_button.setEnabled(True)
        self._delete_button.setEnabled(True)
        self._detail_name.setText(entry.name or "-")
        self._detail_role.setText(entry.role or "None")
        self._detail_world.setText(entry.world or "Unassigned")
        self._detail_campaign.setText(entry.campaign or "Unassigned")
        self._detail_group.setText(entry.group or "Unassigned")
        self._detail_location.setText(entry.location or "Unknown")
        self._detail_tags.setText(", ".join(entry.tags) if entry.tags else "None")
        updated = entry.last_modified or entry.created_at or "Unknown"
        self._detail_updated.setText(updated)
        self._detail_updated.setText(updated)
        self._description_text.blockSignals(True)
        self._description_text.setHtml(entry.description or "")
        self._description_text.blockSignals(False)



    def _open_new_npc_dialog(self) -> None:
        dialog = NPCDialog(self._world_data, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        entry = dialog.entry()
        if not entry:
            return
        entry.id = self._make_unique_id(entry.id)
        self._manager.add_entry(entry)
        self._save_entries()
        self._apply_filters()
        self._select_entry_by_id(entry.id)

    def _open_edit_npc_dialog(self) -> None:
        if not self._current_entry:
            return
        dialog = NPCDialog(self._world_data, self, entry=self._current_entry)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        entry = dialog.entry()
        if not entry:
            return
        entry.id = self._current_entry.id
        self._manager.update_entry(entry)
        self._save_entries()
        self._apply_filters()
        self._select_entry_by_id(entry.id)

    def _duplicate_current_npc(self) -> None:
        if not self._current_entry:
            return
        name, ok = QInputDialog.getText(
            self,
            "Duplicate NPC",
            "New name for the duplicate:",
            text=f"{self._current_entry.name} Copy",
        )
        if not ok:
            return
        new_name = name.strip()
        if not new_name:
            QMessageBox.warning(self, "Missing Name", "Please enter a name.")
            return
        now = _now_timestamp()
        entry = NPCEntry(
            id=self._make_unique_id(sanitize_filename(new_name)),
            name=new_name,
            role=self._current_entry.role,
            world=self._current_entry.world,
            campaign=self._current_entry.campaign,
            group=self._current_entry.group,
            location=self._current_entry.location,
            tags=list(self._current_entry.tags),
            description=self._current_entry.description,
            sessions=list(self._current_entry.sessions),
            encounters=list(self._current_entry.encounters),
            loot=list(self._current_entry.loot),
            created_at=now,
            last_modified=now,
            archived=self._current_entry.archived,
        )
        self._manager.add_entry(entry)
        self._save_entries()
        self._apply_filters()
        self._select_entry_by_id(entry.id)

    def _delete_current_npc(self) -> None:
        if not self._current_entry:
            return
        response = QMessageBox.question(
            self,
            "Delete NPC",
            f"Move {self._current_entry.name} to trash?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        move_to_trash(self._current_entry)
        entry_id = self._current_entry.id
        self._manager.delete_entry(entry_id)
        self._save_entries()
        self._apply_filters()

    def _select_entry_by_id(self, entry_id: str) -> None:
        for index in range(self._npc_list.count()):
            item = self._npc_list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and entry.id == entry_id:
                self._npc_list.setCurrentRow(index)
                return

    def _make_unique_id(self, base_id: str) -> str:
        base = sanitize_filename(base_id or "npc")
        existing = {entry.id for entry in self._manager.entries}
        if base and base not in existing:
            return base
        while True:
            candidate = generate_probabilistic_unique_id(base or "npc")
            if candidate not in existing:
                return candidate

    def _show_placeholder(self, title: str) -> None:
        QMessageBox.information(self, "Placeholder", f"{title} is not implemented yet.")

    def _save_current_npc(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select an NPC to save.")
            return
        self._current_entry.last_modified = _now_timestamp()
        self._save_entries()
        self._apply_filters()

    def _on_description_changed(self) -> None:
        if not self._current_entry:
            return
        self._current_entry.description = self._description_text.toHtml()
        self._current_entry.last_modified = _now_timestamp()
        self._save_entries()


    def _disintegrate_current_npc(self) -> None:
        if not self._current_entry:
            return
        response = QMessageBox.question(
            self,
            "Disintegrate NPC",
            f"Permanently delete {self._current_entry.name}? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if response != QMessageBox.StandardButton.Yes:
            return
        entry_id = self._current_entry.id
        self._manager.delete_entry(entry_id)
        self._save_entries()
        self._apply_filters()
