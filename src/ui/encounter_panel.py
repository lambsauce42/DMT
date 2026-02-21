from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QEvent, Qt, QTimer, QSize
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from encounter_engine import (
    EncounterDataError,
    EncounterEntry,
    Monster,
    SuggestFilters,
    compute_adjusted_xp,
    load_difficulty_table,
    load_monsters,
    load_multiplier_table,
    parse_cr_value,
    parse_tags_text,
    sort_monsters_by_xp,
    suggest_monsters,
)
from save_paths import dnd_saves_dir
from ui.encounter_edit_dialog import ModifyMonsterDialog
from ui.widgets.encounter_progress import EncounterProgressBar
from ui.widgets.monster_card import MonsterCard
from ui.widgets import PlusMinusSpinBox

ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "icons"))


class SuggestDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Suggest Monsters")
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._method = QComboBox()
        self._method.addItems(["Greedy"])
        self._max_monsters = PlusMinusSpinBox()
        self._max_monsters.setRange(1, 50)
        self._max_monsters.setValue(10)
        self._auto_add = QCheckBox("Auto-add suggestions to encounter")
        self._auto_add.setChecked(True)

        form.addRow("Method", self._method)
        form.addRow("Max monsters", self._max_monsters)
        form.addRow("", self._auto_add)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def method(self) -> str:
        return self._method.currentText().lower()

    def max_monsters(self) -> int:
        return self._max_monsters.value()

    def auto_add(self) -> bool:
        return self._auto_add.isChecked()


class EncounterPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._monsters: list[Monster] = []
        self._filtered_monsters: list[Monster] = []
        self._encounter_entries: list[EncounterEntry] = []
        self._difficulty_table: dict[int, dict[str, int]] = {}
        self._difficulty_keys: list[str] = []
        self._expanded_monster_id: Optional[str] = None
        self._sort_mode = "none"
        self._settings = self._load_settings()
        self._sort_mode = self._settings.get("xp_sort", "none")
        self._target_factor = float(self._settings.get("target_factor", 1.0))

        self._load_tables()
        self._load_monster_db()
        self._build_ui()
        self._apply_filters()
        self._recompute_totals()

    def _load_tables(self) -> None:
        try:
            self._difficulty_table = load_difficulty_table()
            load_multiplier_table()
        except EncounterDataError as exc:
            QMessageBox.warning(self, "Encounter Data", str(exc))
            self._difficulty_table = {}
        keys = set()
        for level_data in self._difficulty_table.values():
            keys.update(level_data.keys())
        default_order = ["easy", "medium", "hard", "deadly"]
        self._difficulty_keys = [key for key in default_order if key in keys]
        if not self._difficulty_keys:
            self._difficulty_keys = sorted(keys)

    def _load_monster_db(self) -> None:
        try:
            self._monsters = load_monsters()
        except EncounterDataError as exc:
            QMessageBox.warning(self, "Monster DB", str(exc))
            self._monsters = []

    def _apply_splitter_sizes(self) -> None:
        splitter = getattr(self, "_splitter", None)
        if splitter is None:
            return
        total = splitter.size().width()
        if total <= 0:
            return
        ratios = [8, 10, 10]
        ratio_total = sum(ratios)
        sizes = [max(1, int(total * r / ratio_total)) for r in ratios]
        sizes[-1] = max(1, total - sum(sizes[:-1]))
        splitter.setSizes(sizes)
        QTimer.singleShot(0, self._sync_chip_widths)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_splitter_sizes()
        self._sync_chip_widths()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        left_panel = self._build_party_panel()
        center_panel = self._build_browser_panel()
        right_panel = self._build_encounter_panel()

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 8)
        splitter.setStretchFactor(1, 10)
        splitter.setStretchFactor(2, 10)
        self._splitter = splitter
        splitter.splitterMoved.connect(
            lambda *_: QTimer.singleShot(0, self._sync_chip_widths)
        )
        layout.addWidget(splitter, 1)
        QTimer.singleShot(0, self._apply_splitter_sizes)

    # ── shared geometry for party-panel rows (mirrors C# encounter layout) ──
    _PARTY_LABEL_W = 124
    _PARTY_LABEL_H = 32
    _PARTY_GAP_LS = 8      # label → slider
    _PARTY_GAP_SV = 4      # slider → value
    _PARTY_VALUE_W = 54
    _PARTY_VALUE_H = 32
    _PARTY_ROW_H = 32
    _PARTY_STEP_SIZE = 32   # +/- buttons

    @staticmethod
    def _make_party_label_box(text: str) -> QFrame:
        box = QFrame()
        box.setFixedSize(EncounterPanel._PARTY_LABEL_W, EncounterPanel._PARTY_LABEL_H)
        box.setStyleSheet(
            "QFrame { background-color: #0d1117; border: 1px solid #2e3a4c;"
            " border-radius: 4px; }"
        )
        lbl = QLabel(text, box)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "QLabel { border: none; color: #c9d1d9; font-size: 12px; }"
        )
        lo = QHBoxLayout(box)
        lo.setContentsMargins(8, 0, 8, 0)
        lo.addWidget(lbl)
        return box

    @staticmethod
    def _make_party_value_label(text: str = "") -> QLabel:
        lbl = QLabel(text)
        lbl.setFixedSize(EncounterPanel._PARTY_VALUE_W, EncounterPanel._PARTY_VALUE_H)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "QLabel { background-color: #0d1117; border: 1px solid #2e3a4c;"
            " border-radius: 4px; color: #c9d1d9; }"
        )
        return lbl

    @staticmethod
    def _make_step_button(icon_name: str) -> QPushButton:
        """Create a +/- step button with SVG icon, matching the value box height."""
        btn = QPushButton()
        icon_path = os.path.join(ICON_DIR, f"{icon_name}.svg")
        btn.setIcon(QIcon(icon_path))
        btn.setIconSize(QSize(14, 14))
        btn.setFixedSize(EncounterPanel._PARTY_STEP_SIZE, EncounterPanel._PARTY_VALUE_H)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background-color: #1b2432; border: 1px solid #3b424b;"
            " border-radius: 4px; color: #c9d1d9; font-weight: 600; padding: 0px;"
            " min-width: 0px; min-height: 0px; }"
            "QPushButton:hover { border-color: #58a6ff; color: #e6edf3; }"
        )
        return btn

    def _build_party_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Party")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        # ── Party size row ────────────────────────────────────────────
        ps_row = QHBoxLayout()
        ps_row.setSpacing(0)
        ps_row.addWidget(self._make_party_label_box("Party size"))
        ps_row.addSpacing(self._PARTY_GAP_LS)

        self._party_size_slider = QSlider(Qt.Orientation.Horizontal)
        self._party_size_slider.setRange(1, 8)
        self._party_size_slider.setValue(4)
        self._party_size_slider.setTickInterval(1)
        self._party_size_slider.setSingleStep(1)
        self._party_size_slider.setMinimumHeight(self._PARTY_ROW_H)
        ps_row.addWidget(self._party_size_slider, 1)
        ps_row.addSpacing(self._PARTY_GAP_SV)

        self._party_size_value = self._make_party_value_label("4")
        ps_row.addWidget(self._party_size_value)

        def _on_party_size_changed(val: int) -> None:
            self._party_size_value.setText(str(val))
            self._rebuild_levels(val)

        self._party_size_slider.valueChanged.connect(_on_party_size_changed)
        layout.addLayout(ps_row)

        # ── Difficulty row ────────────────────────────────────────────
        diff_row = QHBoxLayout()
        diff_row.setSpacing(0)
        diff_row.addWidget(self._make_party_label_box("Difficulty"))
        diff_row.addSpacing(self._PARTY_GAP_LS)

        self._difficulty_combo = QComboBox()
        self._difficulty_combo.addItems(
            [key.title() for key in self._difficulty_keys] or ["Medium"]
        )
        self._difficulty_combo.setMinimumHeight(self._PARTY_ROW_H)
        self._difficulty_combo.currentTextChanged.connect(self._recompute_totals)
        diff_row.addWidget(self._difficulty_combo, 1)
        layout.addLayout(diff_row)

        # ── Custom factor row ─────────────────────────────────────────
        cf_row = QHBoxLayout()
        cf_row.setSpacing(0)
        cf_row.addWidget(self._make_party_label_box("Custom factor"))
        cf_row.addSpacing(self._PARTY_GAP_LS)

        self._target_factor_slider = QSlider(Qt.Orientation.Horizontal)
        self._target_factor_slider.setRange(10, 1000)
        self._target_factor_slider.setSingleStep(5)
        self._target_factor_slider.setValue(int(round(self._target_factor * 100)))
        self._target_factor_slider.setMinimumHeight(self._PARTY_ROW_H)
        self._target_factor_slider.valueChanged.connect(
            self._on_target_factor_slider
        )
        cf_row.addWidget(self._target_factor_slider, 1)
        cf_row.addSpacing(self._PARTY_GAP_SV)

        self._target_factor_value = self._make_party_value_label(
            f"{self._target_factor:.2f}"
        )
        cf_row.addWidget(self._target_factor_value)
        layout.addLayout(cf_row)

        # ── Player levels header ──────────────────────────────────────
        levels_hdr = QLabel("Player Levels")
        levels_hdr.setObjectName("PanelTitle")
        levels_hdr.setStyleSheet(
            "font-weight: 600; font-size: 13px; margin-top: 4px;"
        )
        layout.addWidget(levels_hdr)

        # container for dynamically built level rows
        self._levels_container = QWidget()
        self._levels_container.setObjectName("TransparentContainer")
        self._levels_layout = QVBoxLayout(self._levels_container)
        self._levels_layout.setContentsMargins(0, 0, 0, 0)
        self._levels_layout.setSpacing(4)
        layout.addWidget(self._levels_container)

        # target XP label
        self._target_label = QLabel("Target XP: 0")
        self._target_label.setObjectName("ColumnHeader")
        self._target_label.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._target_label.customContextMenuRequested.connect(self._show_target_menu)
        layout.addWidget(self._target_label)
        layout.addStretch(1)

        # init level tracking
        self._level_sliders: list[QSlider] = []
        self._level_value_labels: list[QLabel] = []
        self._rebuild_levels(self._party_size_slider.value())
        return panel

    def _show_target_menu(self, pos) -> None:
        menu = QMenu(self)
        action = QAction("Copy target XP", self)
        action.triggered.connect(self._copy_target_xp)
        menu.addAction(action)
        menu.exec(self._target_label.mapToGlobal(pos))

    def _copy_target_xp(self) -> None:
        QApplication.clipboard().setText(self._target_label.text())

    def _build_browser_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Monster Browser")
        title.setObjectName("PanelTitle")
        header_row = QHBoxLayout()
        header_row.addWidget(title)
        header_row.addStretch(1)

        self._sort_combo = QComboBox()
        self._sort_combo.addItems(["XP: None", "XP: Low → High", "XP: High → Low"])
        self._sort_combo.setCurrentIndex(self._sort_index_from_mode(self._sort_mode))
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        header_row.addWidget(self._sort_combo)
        layout.addLayout(header_row)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search name")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._apply_filters)
        self._search.textChanged.connect(self._debounce_filters)

        filters_row = QHBoxLayout()
        self._xp_min = PlusMinusSpinBox()
        self._xp_min.setRange(0, 500000)
        self._xp_min.setPrefix("Min XP ")
        self._xp_min.valueChanged.connect(self._apply_filters)
        self._xp_max = PlusMinusSpinBox()
        self._xp_max.setRange(0, 500000)
        self._xp_max.setPrefix("Max XP ")
        self._xp_max.valueChanged.connect(self._apply_filters)
        self._cr_combo = QComboBox()
        self._cr_combo.addItem("Any CR")
        for cr in self._sorted_cr_values():
            self._cr_combo.addItem(cr)
        self._cr_combo.currentTextChanged.connect(self._apply_filters)

        filters_row.addWidget(self._xp_min)
        filters_row.addWidget(self._xp_max)
        filters_row.addWidget(self._cr_combo)

        layout.addWidget(self._search)
        layout.addLayout(filters_row)

        tags_group = QGroupBox("Tags")
        tags_group.setObjectName("TransparentContainer")
        tags_layout = QVBoxLayout(tags_group)
        self._tags_input = QLineEdit()
        self._tags_input.setPlaceholderText("Tags: undead, boss")
        self._tags_input.textChanged.connect(self._apply_filters)
        self._match_all_tags = QCheckBox("Match all tags")
        self._match_all_tags.stateChanged.connect(self._apply_filters)
        tags_layout.addWidget(self._tags_input)
        tags_layout.addWidget(self._match_all_tags)
        layout.addWidget(tags_group)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setObjectName("SubPanel")
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._scroll.setWidget(self._cards_container)

        layout.addWidget(self._scroll, 1)
        return panel

    def _build_encounter_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Current Encounter")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self._encounter_headers = ["Count", "Name", "XP each", "Total XP", "Remove"]
        self._encounter_tree = QTableWidget(0, 5)
        self._encounter_tree.verticalHeader().setVisible(False)
        self._encounter_tree.horizontalHeader().setVisible(False)
        self._encounter_tree.setShowGrid(False)
        self._encounter_tree.setAlternatingRowColors(False)
        self._encounter_tree.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._encounter_tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._encounter_tree.setFrameStyle(QFrame.Shape.NoFrame)
        self._encounter_tree.setStyleSheet("""
            QTableWidget { 
                background-color: transparent; 
                border: none;
                padding: 0px;
            }
            QTableWidget::item { 
                padding: 0px;
                border: none;
            }
            QWidget#EncounterHeaderCell {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 4px;
            }
            QLabel#EncounterHeaderLabel {
                color: #9aa4b2;
                font-weight: 600;
            }
            QWidget#EncounterCell {
                background-color: transparent;
            }
            QLabel#EncounterCellLabel {
                color: #c9d1d9;
            }
        """)
        
        self._encounter_header_height = 32
        self._encounter_row_height = 42
        self._encounter_cell_padding = 8
        self._count_cell_margin = 6
        self._count_spin_width = 110
        self._remove_cell_margin = 6
        self._xp_each_col_width = 75
        self._total_xp_col_width = 85

        header = self._encounter_tree.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._encounter_tree.setColumnWidth(
            0, self._count_spin_width + (self._count_cell_margin * 2)
        )
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._encounter_tree.setColumnWidth(2, self._xp_each_col_width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._encounter_tree.setColumnWidth(3, self._total_xp_col_width)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        remove_probe = QPushButton("Remove", self._encounter_tree)
        remove_probe.setObjectName("InlineResetButton")
        remove_probe.ensurePolished()
        remove_width = remove_probe.sizeHint().width() + (self._remove_cell_margin * 2)
        remove_probe.deleteLater()
        self._encounter_tree.setColumnWidth(4, max(80, remove_width))
        header.sectionResized.connect(lambda *_: self._sync_encounter_cell_sizes())
        self._encounter_tree.installEventFilter(self)
        self._encounter_tree.viewport().installEventFilter(self)

        layout.addWidget(self._encounter_tree, 1)

        totals_group = QGroupBox("Totals")
        totals_group.setStyleSheet("background-color: transparent;")
        totals_layout = QVBoxLayout(totals_group)
        self._raw_label = QLabel("Raw XP: 0")
        self._mult_label = QLabel("Multiplier: 1.0")
        self._adj_label = QLabel("Adjusted XP: 0")
        totals_layout.addWidget(self._raw_label)
        totals_layout.addWidget(self._mult_label)
        totals_layout.addWidget(self._adj_label)
        layout.addWidget(totals_group)

        progress_container = QWidget(self)
        progress_layout = QVBoxLayout(progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(4)

        progress_container.setStyleSheet("""
            QFrame#EncounterInfoChip {
                background-color: #161b22;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
            QLabel#EncounterInfoChipLabel {
                color: #9aa4b2;
                font-size: 11px;
                font-weight: 600;
            }
            QFrame#EncounterDeltaChip[delta="positive"] {
                background-color: #1f6f3d;
                border-color: #3fb950;
                border-radius: 12px;
            }
            QFrame#EncounterDeltaChip[delta="negative"] {
                background-color: #7a1f1f;
                border-color: #f85149;
                border-radius: 12px;
            }
            QFrame#EncounterDeltaChip[delta="neutral"] {
                background-color: #161b22;
                border-color: #30363d;
                border-radius: 12px;
            }
            QFrame#EncounterDifficultyChip {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 12px;
            }
            QFrame#EncounterDifficultyChip[difficulty="none"] {
                background-color: #21262d;
                border-color: #30363d;
            }
            QFrame#EncounterDifficultyChip[difficulty="trivial"] {
                background-color: #243041;
                border-color: #4b5563;
            }
            QFrame#EncounterDifficultyChip[difficulty="easy"] {
                background-color: #1f6f3d;
                border-color: #3fb950;
            }
            QFrame#EncounterDifficultyChip[difficulty="medium"] {
                background-color: #6e4a0a;
                border-color: #d29922;
            }
            QFrame#EncounterDifficultyChip[difficulty="hard"] {
                background-color: #7a1f1f;
                border-color: #f85149;
            }
            QFrame#EncounterDifficultyChip[difficulty="deadly"] {
                background-color: #8b0000;
                border-color: #ff7b72;
            }
            QLabel#EncounterDifficultyLabel {
                color: #ffffff;
                font-size: 11px;
                font-weight: 700;
            }
        """)

        self._chip_height = 26
        self._chip_spacing = 6
        self._chip_min_width = 80
        self._chip_padding_x = 10
        chips_row = QWidget(progress_container)
        self._chips_row = chips_row
        chips_layout = QHBoxLayout(chips_row)
        chips_layout.setContentsMargins(0, 0, 0, 0)
        chips_layout.setSpacing(self._chip_spacing)

        self._adjusted_chip, self._adjusted_chip_label = self._build_info_chip(
            "XP: 0",
            "EncounterInfoChip",
            "EncounterInfoChipLabel",
            Qt.AlignmentFlag.AlignLeft,
        )
        self._target_chip, self._target_chip_label = self._build_info_chip(
            "Target XP: 0",
            "EncounterInfoChip",
            "EncounterInfoChipLabel",
            Qt.AlignmentFlag.AlignLeft,
        )
        self._delta_chip, self._delta_chip_label = self._build_info_chip(
            "Δ 0 XP",
            "EncounterDeltaChip",
            "EncounterInfoChipLabel",
            Qt.AlignmentFlag.AlignLeft,
        )
        self._delta_chip.setProperty("delta", "neutral")
        self._difficulty_chip, self._difficulty_chip_label = self._build_info_chip(
            "No encounter",
            "EncounterDifficultyChip",
            "EncounterDifficultyLabel",
            Qt.AlignmentFlag.AlignCenter,
        )
        self._difficulty_chip.setProperty("difficulty", "none")

        chips_layout.addWidget(self._adjusted_chip)
        chips_layout.addWidget(self._target_chip)
        chips_layout.addWidget(self._delta_chip)
        chips_layout.addWidget(self._difficulty_chip)
        self._chips = [
            self._adjusted_chip,
            self._target_chip,
            self._delta_chip,
            self._difficulty_chip,
        ]
        bar_marker_container = QWidget(progress_container)
        bar_marker_layout = QVBoxLayout(bar_marker_container)
        bar_marker_layout.setContentsMargins(0, 0, 0, 0)
        bar_marker_layout.setSpacing(0)

        self._progress_bar = EncounterProgressBar(bar_marker_container)
        self._progress_bar.setFixedHeight(18)
        self._progress_bar.setSizePolicy(
            self._progress_bar.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Fixed,
        )
        self._progress_bar.installEventFilter(self)
        self._chips_row.installEventFilter(self)

        bar_marker_layout.addWidget(self._progress_bar)
        progress_layout.addWidget(chips_row)
        progress_layout.addWidget(bar_marker_container)
        layout.addWidget(progress_container)
        QTimer.singleShot(0, self._sync_chip_widths)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)

        _wide_btn_style = (
            "QToolButton { background-color: #1b2432; border: 1px solid #3b424b;"
            " border-radius: 6px; color: #c9d1d9; }"
            "QToolButton:hover { border-color: #58a6ff; color: #e6edf3; }"
        )
        _danger_btn_style = (
            "QToolButton { background-color: #8b1a1a; border: 1px solid #f85149;"
            " border-radius: 6px; color: #ffe9e8; }"
            "QToolButton:hover { background-color: #a42525;"
            " border-color: #ff7b72; color: #ffffff; }"
        )

        suggest_btn = QToolButton()
        suggest_btn.setIcon(QIcon(os.path.join(ICON_DIR, "lightbulb.svg")))
        suggest_btn.setToolTip("Suggest Monsters")
        suggest_btn.clicked.connect(self._suggest)

        save_btn = QToolButton()
        save_btn.setIcon(QIcon(os.path.join(ICON_DIR, "save.svg")))
        save_btn.setToolTip("Save Encounter")
        save_btn.clicked.connect(self.save_encounter)

        export_btn = QToolButton()
        export_btn.setIcon(QIcon(os.path.join(ICON_DIR, "export.svg")))
        export_btn.setToolTip("Export Encounter PDF")
        export_btn.clicked.connect(self._export_dialog)

        clear_btn = QToolButton()
        clear_btn.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
        clear_btn.setToolTip("Clear Encounter")
        clear_btn.clicked.connect(self.new_encounter)

        for btn in (suggest_btn, save_btn, export_btn):
            btn.setFixedHeight(56)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setIconSize(QSize(22, 22))
            btn.setStyleSheet(_wide_btn_style)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            actions_row.addWidget(btn)

        clear_btn.setFixedHeight(56)
        clear_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        clear_btn.setIconSize(QSize(22, 22))
        clear_btn.setStyleSheet(_danger_btn_style)
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        actions_row.addWidget(clear_btn)

        layout.addLayout(actions_row)
        return panel

    def _debounce_filters(self) -> None:
        self._search_timer.stop()
        self._search_timer.start()

    def _sorted_cr_values(self) -> list[str]:
        cr_map = {}
        for monster in self._monsters:
            cr_map[monster.cr] = monster.cr_value
        return [cr for cr, _ in sorted(cr_map.items(), key=lambda item: item[1])]

    def _rebuild_levels(self, size: int) -> None:
        previous = [s.value() for s in self._level_sliders]
        # tear down old rows
        for s in self._level_sliders:
            s.deleteLater()
        for lbl in self._level_value_labels:
            lbl.deleteLater()
        self._level_sliders.clear()
        self._level_value_labels.clear()
        # remove remaining row widgets from layout
        while self._levels_layout.count():
            item = self._levels_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                sub = item.layout()
                while sub.count():
                    child = sub.takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()

        for idx in range(size):
            value = previous[idx] if idx < len(previous) else 1
            row_widget = QWidget()
            row_widget.setObjectName("TransparentContainer")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)

            label_box = self._make_party_label_box(f"Player {idx + 1}")
            row_layout.addWidget(label_box)
            row_layout.addSpacing(self._PARTY_GAP_LS)

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(1, 20)
            slider.setValue(value)
            slider.setTickInterval(1)
            slider.setSingleStep(1)
            slider.setMinimumHeight(self._PARTY_ROW_H)
            row_layout.addWidget(slider, 1)
            row_layout.addSpacing(self._PARTY_GAP_SV)

            val_lbl = self._make_party_value_label(str(value))
            row_layout.addWidget(val_lbl)
            row_layout.addSpacing(4)

            minus_btn = self._make_step_button("minus")
            plus_btn = self._make_step_button("plus")
            row_layout.addWidget(minus_btn)
            row_layout.addSpacing(4)
            row_layout.addWidget(plus_btn)

            # wire slider ↔ label
            def _sync(v: int, lbl=val_lbl) -> None:
                lbl.setText(str(v))
                self._recompute_totals()

            slider.valueChanged.connect(_sync)
            minus_btn.clicked.connect(
                lambda _=False, s=slider: s.setValue(max(1, s.value() - 1))
            )
            plus_btn.clicked.connect(
                lambda _=False, s=slider: s.setValue(min(20, s.value() + 1))
            )

            self._levels_layout.addWidget(row_widget)
            self._level_sliders.append(slider)
            self._level_value_labels.append(val_lbl)

        if hasattr(self, "_raw_label"):
            self._recompute_totals()

    def _current_target_factor(self) -> float:
        if hasattr(self, "_target_factor_spin"):
            return float(self._target_factor_spin.value())
        return float(self._settings.get("target_factor", 1.0))

    def _on_target_factor_slider(self, value: int) -> None:
        factor = value / 100.0
        if hasattr(self, "_target_factor_value"):
            self._target_factor_value.setText(f"{factor:.2f}")
        self._update_target_factor(factor)

    def _on_target_factor_spin(self, value: float) -> None:
        # kept for API compat; slider drives value now
        slider_value = int(round(value * 100))
        self._target_factor_slider.blockSignals(True)
        self._target_factor_slider.setValue(slider_value)
        self._target_factor_slider.blockSignals(False)
        self._update_target_factor(value)

    def _update_target_factor(self, factor: float) -> None:
        self._target_factor = float(factor)
        self._settings["target_factor"] = self._target_factor
        self._save_settings()
        self._recompute_totals()

    def _current_levels(self) -> list[int]:
        return [s.value() for s in self._level_sliders]

    def _difficulty_key(self) -> str:
        return self._difficulty_combo.currentText().strip().lower()

    def _compute_target_xp(self, levels: list[int], difficulty: str) -> int:
        total = 0
        for level in levels:
            thresholds = self._difficulty_table.get(level)
            if thresholds is None:
                continue
            total += thresholds.get(difficulty, 0)
        factor = self._current_target_factor()
        return int(total * factor + 0.5)

    def _breakdown_tooltip(self, levels: list[int], difficulty: str) -> str:
        factor = self._current_target_factor()
        lines = []
        if abs(factor - 1.0) > 0.001:
            lines.append(f"Custom factor: x{factor:.2f}")
        for index, level in enumerate(levels, start=1):
            base_value = self._difficulty_table.get(level, {}).get(difficulty, 0)
            value = int(base_value * factor + 0.5)
            lines.append(f"P{index} (lvl {level}): {value} XP")
        return "\n".join(lines)

    def _apply_filters(self) -> None:
        search = self._search.text().strip().lower()
        min_xp = self._xp_min.value() or None
        max_xp = self._xp_max.value() or None
        cr_value = self._cr_combo.currentText()
        cr_values = None if cr_value == "Any CR" else {cr_value}
        selected_tags = set(parse_tags_text(self._tags_input.text()))
        match_all = self._match_all_tags.isChecked()

        filtered = []
        for monster in self._monsters:
            if search and search not in monster.name.lower():
                continue
            if min_xp is not None and monster.xp < min_xp:
                continue
            if max_xp is not None and monster.xp > max_xp:
                continue
            if cr_values and monster.cr not in cr_values:
                continue
            if selected_tags:
                if match_all:
                    if not selected_tags.issubset(set(monster.tags)):
                        continue
                else:
                    if not set(monster.tags) & selected_tags:
                        continue
            filtered.append(monster)

        self._filtered_monsters = sort_monsters_by_xp(filtered, self._sort_mode)
        self._render_results()

    def _render_results(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for monster in self._filtered_monsters:
            card = MonsterCard(
                monster,
                on_add=self._add_monster,
                on_modify=self._modify_monster,
                on_expand_request=self._handle_expand,
            )
            expanded = self._expanded_monster_id == monster.id
            card.set_expanded(expanded)
            self._cards_layout.addWidget(card)

        self._cards_layout.addStretch(1)

    def _handle_expand(self, card: MonsterCard, expanded: bool) -> None:
        if expanded:
            self._expanded_monster_id = card.monster.id
            for index in range(self._cards_layout.count()):
                widget = self._cards_layout.itemAt(index).widget()
                if isinstance(widget, MonsterCard) and widget is not card:
                    widget.set_expanded(False)
        else:
            if self._expanded_monster_id == card.monster.id:
                self._expanded_monster_id = None
        card.set_expanded(expanded)

    def _add_monster(self, monster: Monster, count: int) -> None:
        if count <= 0:
            return
        for entry in self._encounter_entries:
            if entry.monster.id == monster.id:
                entry.count += count
                self._refresh_encounter()
                return
        self._encounter_entries.append(EncounterEntry(monster=monster, count=count))
        self._refresh_encounter()

    def _modify_monster(self, monster: Monster, count: int) -> None:
        dialog = ModifyMonsterDialog(monster, count, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        new_monster = dialog.result_monster()
        if not new_monster:
            return
        self._add_monster(new_monster, dialog.result_count())

    def _refresh_encounter(self) -> None:
        self._render_encounter_tree()
        self._recompute_totals()

    def _render_encounter_tree(self) -> None:
        self._encounter_tree.clearContents()
        total_rows = len(self._encounter_entries) + 1
        self._encounter_tree.setRowCount(total_rows)

        def make_header_cell(text: str, alignment: Qt.AlignmentFlag) -> QWidget:
            cell = QFrame(self._encounter_tree)
            cell.setObjectName("EncounterHeaderCell")
            cell.setFixedHeight(self._encounter_header_height)
            layout = QHBoxLayout(cell)
            layout.setContentsMargins(self._encounter_cell_padding, 0, self._encounter_cell_padding, 0)
            layout.setAlignment(alignment)
            label = QLabel(text, cell)
            label.setObjectName("EncounterHeaderLabel")
            label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
            layout.addWidget(label)
            return cell

        def make_text_cell(text: str, alignment: Qt.AlignmentFlag, tooltip: str | None = None) -> QWidget:
            cell = QFrame(self._encounter_tree)
            cell.setObjectName("EncounterCell")
            cell.setFixedHeight(self._encounter_row_height)
            layout = QHBoxLayout(cell)
            layout.setContentsMargins(self._encounter_cell_padding, 0, self._encounter_cell_padding, 0)
            layout.setAlignment(alignment)
            label = QLabel(text, cell)
            label.setObjectName("EncounterCellLabel")
            label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            if tooltip is not None:
                label.setToolTip(tooltip)
            layout.addWidget(label)
            return cell

        self._encounter_tree.setRowHeight(0, self._encounter_header_height)
        header_alignments = [
            Qt.AlignmentFlag.AlignCenter,
            Qt.AlignmentFlag.AlignLeft,
            Qt.AlignmentFlag.AlignRight,
            Qt.AlignmentFlag.AlignRight,
            Qt.AlignmentFlag.AlignCenter,
        ]
        for col, text in enumerate(self._encounter_headers):
            self._encounter_tree.setCellWidget(0, col, make_header_cell(text, header_alignments[col]))

        for row, entry in enumerate(self._encounter_entries, start=1):
            self._encounter_tree.setRowHeight(row, self._encounter_row_height)
            
            # Count widget (Col 0) - Center alignment
            count_container = QFrame(self._encounter_tree)
            count_container.setObjectName("EncounterCell")
            count_container.setFixedHeight(self._encounter_row_height)
            count_layout = QHBoxLayout(count_container)
            count_layout.setContentsMargins(
                self._count_cell_margin, 0, self._count_cell_margin, 0
            )
            count_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            count_spin = PlusMinusSpinBox()
            count_spin.setRange(1, 99)
            count_spin.setValue(entry.count)
            count_spin.setFixedWidth(self._count_spin_width)
            count_spin.valueChanged.connect(
                lambda value, e=entry: self._update_count(e, value)
            )
            count_layout.addWidget(count_spin)
            self._encounter_tree.setCellWidget(row, 0, count_container)

            # Name (Col 1) - Left aligned with icon controls
            name = entry.monster.name
            if entry.monster.transient:
                name += " (modified)"
            name_cell = QFrame(self._encounter_tree)
            name_cell.setObjectName("EncounterCell")
            name_cell.setFixedHeight(self._encounter_row_height)
            name_layout = QHBoxLayout(name_cell)
            name_layout.setContentsMargins(self._encounter_cell_padding, 0, self._encounter_cell_padding, 0)
            name_layout.setSpacing(6)
            name_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            name_label = QLabel(name, name_cell)
            name_label.setObjectName("EncounterCellLabel")
            name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            name_label.setToolTip(name)
            name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            name_layout.addWidget(name_label, 1)
            set_icon_btn = QPushButton(
                "Edit" if getattr(entry.monster, "icon_path", "") else "Set",
                name_cell,
            )
            set_icon_btn.setObjectName("InlineResetButton")
            set_icon_btn.setFixedHeight(24)
            set_icon_btn.setFixedWidth(42)
            set_icon_btn.clicked.connect(
                lambda checked=False, e=entry: self._set_entry_icon(e)
            )
            clear_icon_btn = QPushButton("X", name_cell)
            clear_icon_btn.setObjectName("InlineResetButton")
            clear_icon_btn.setFixedHeight(24)
            clear_icon_btn.setFixedWidth(28)
            clear_icon_btn.setEnabled(bool(getattr(entry.monster, "icon_path", "")))
            clear_icon_btn.clicked.connect(
                lambda checked=False, e=entry: self._clear_entry_icon(e)
            )
            name_layout.addWidget(set_icon_btn)
            name_layout.addWidget(clear_icon_btn)
            self._encounter_tree.setCellWidget(row, 1, name_cell)
            
            # XP each (Col 2) - Right aligned
            xp_each = make_text_cell(
                str(entry.monster.xp), Qt.AlignmentFlag.AlignRight
            )
            self._encounter_tree.setCellWidget(row, 2, xp_each)
            
            # Total XP (Col 3) - Right aligned
            total_xp = make_text_cell(
                str(entry.monster.xp * entry.count), Qt.AlignmentFlag.AlignRight
            )
            self._encounter_tree.setCellWidget(row, 3, total_xp)

            # Remove (Col 4) - Center aligned
            remove_container = QFrame(self._encounter_tree)
            remove_container.setObjectName("EncounterCell")
            remove_container.setFixedHeight(self._encounter_row_height)
            remove_layout = QHBoxLayout(remove_container)
            remove_layout.setContentsMargins(
                self._remove_cell_margin, 0, self._remove_cell_margin, 0
            )
            remove_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            remove_btn = QPushButton("Remove")
            remove_btn.setObjectName("InlineResetButton")
            remove_btn.clicked.connect(lambda checked=False, e=entry: self._remove_entry(e))
            remove_layout.addWidget(remove_btn)
            self._encounter_tree.setCellWidget(row, 4, remove_container)

        self._sync_encounter_cell_sizes()

    def _update_count(self, entry: EncounterEntry, value: int) -> None:
        entry.count = max(1, value)
        self._refresh_encounter()

    def _remove_entry(self, entry: EncounterEntry) -> None:
        self._encounter_entries = [e for e in self._encounter_entries if e is not entry]
        self._refresh_encounter()

    def _set_entry_icon(self, entry: EncounterEntry) -> None:
        start_dir = str(dnd_saves_dir())
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Select Encounter Icon",
            start_dir,
            "Images (*.png *.jpg *.jpeg *.bmp *.webp *.svg)",
        )
        if not filename:
            return
        entry.monster = replace(entry.monster, icon_path=filename, transient=True)
        self._refresh_encounter()

    def _clear_entry_icon(self, entry: EncounterEntry) -> None:
        if not getattr(entry.monster, "icon_path", ""):
            return
        entry.monster = replace(entry.monster, icon_path="", transient=True)
        self._refresh_encounter()

    def _sync_encounter_cell_sizes(self) -> None:
        if not self._encounter_tree:
            return
        for row in range(self._encounter_tree.rowCount()):
            row_height = self._encounter_tree.rowHeight(row)
            for col in range(self._encounter_tree.columnCount()):
                widget = self._encounter_tree.cellWidget(row, col)
                if widget is None:
                    continue
                widget.setFixedWidth(self._encounter_tree.columnWidth(col))
                widget.setFixedHeight(row_height)

    def eventFilter(self, obj, event) -> bool:
        if obj in (self._encounter_tree, self._encounter_tree.viewport()):
            if event.type() == QEvent.Type.Resize:
                QTimer.singleShot(0, self._sync_encounter_cell_sizes)
        if obj in (getattr(self, "_progress_bar", None), getattr(self, "_chips_row", None)):
            if event.type() == QEvent.Type.Resize:
                QTimer.singleShot(0, self._sync_chip_widths)
        return super().eventFilter(obj, event)

    def _recompute_totals(self) -> None:
        levels = self._current_levels()
        difficulty = self._difficulty_key()
        target_xp = self._compute_target_xp(levels, difficulty)
        self._target_label.setText(f"Target XP: {target_xp}")
        self._target_label.setToolTip(self._breakdown_tooltip(levels, difficulty))

        raw_xp, multiplier, adjusted_xp = compute_adjusted_xp(
            self._encounter_entries, self._party_size_slider.value()
        )
        self._raw_label.setText(f"Raw XP: {raw_xp}")
        self._mult_label.setText(f"Multiplier: {multiplier:.2f}")
        self._adj_label.setText(f"Adjusted XP: {adjusted_xp}")

        if target_xp > 0:
            progress = (adjusted_xp / target_xp) * 100
        else:
            progress = 0.0
        self._progress_bar.set_value(progress)
        self._progress_bar.set_target_values(adjusted_xp, target_xp)
        self._update_encounter_chips(adjusted_xp, target_xp, levels)
        self._sync_chip_widths()

    def _sync_chip_widths(self) -> None:
        if not hasattr(self, "_chips"):
            return
        available = self._progress_bar.width()
        if available <= 0 and hasattr(self, "_chips_row"):
            available = self._chips_row.width()
        if available <= 0:
            return
        spacing_total = self._chip_spacing * 3
        width_each = max(
            self._chip_min_width,
            int((available - spacing_total) / 4),
        )
        for chip in self._chips:
            chip.setFixedWidth(width_each)

    def _build_info_chip(
        self,
        text: str,
        frame_name: str,
        label_name: str,
        alignment: Qt.AlignmentFlag,
    ) -> tuple[QFrame, QLabel]:
        chip = QFrame(self)
        chip.setObjectName(frame_name)
        chip.setFixedHeight(self._chip_height)
        chip.setMinimumWidth(0)
        chip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(chip)
        layout.setContentsMargins(self._chip_padding_x, 0, self._chip_padding_x, 0)
        layout.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        label = QLabel(text, chip)
        label.setObjectName(label_name)
        label.setAlignment(alignment | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label)
        return chip, label

    def _update_encounter_chips(
        self, adjusted_xp: int, target_xp: int, levels: list[int]
    ) -> None:
        self._adjusted_chip_label.setText(f"XP: {adjusted_xp}")
        self._target_chip_label.setText(f"Target XP: {target_xp}")
        if target_xp <= 0:
            delta_text = "Δ 0 XP"
            delta_state = "neutral"
        else:
            delta_value = adjusted_xp - target_xp
            sign = "+" if delta_value > 0 else ""
            delta_text = f"Δ {sign}{delta_value} XP"
            if delta_value > 0:
                delta_state = "positive"
            elif delta_value < 0:
                delta_state = "negative"
            else:
                delta_state = "neutral"
        self._delta_chip_label.setText(delta_text)
        if self._delta_chip.property("delta") != delta_state:
            self._delta_chip.setProperty("delta", delta_state)
            self._delta_chip.style().unpolish(self._delta_chip)
            self._delta_chip.style().polish(self._delta_chip)

        difficulty = self._status_text(adjusted_xp, levels)
        difficulty_key = difficulty.lower().replace(" ", "")
        if adjusted_xp <= 0:
            difficulty_key = "none"
            difficulty = "No encounter"
        self._difficulty_chip_label.setText(difficulty)
        if self._difficulty_chip.property("difficulty") != difficulty_key:
            self._difficulty_chip.setProperty("difficulty", difficulty_key)
            self._difficulty_chip.style().unpolish(self._difficulty_chip)
            self._difficulty_chip.style().polish(self._difficulty_chip)

    def _status_text(self, adjusted_xp: int, levels: list[int]) -> str:
        if adjusted_xp <= 0:
            return "No encounter"
        thresholds = {
            key: self._compute_target_xp(levels, key)
            for key in ["easy", "medium", "hard", "deadly"]
            if key in self._difficulty_keys
        }
        easy = thresholds.get("easy", 0)
        medium = thresholds.get("medium", easy)
        hard = thresholds.get("hard", medium)
        deadly = thresholds.get("deadly", hard)
        if adjusted_xp < easy:
            return "Trivial"
        if adjusted_xp < medium:
            return "Easy"
        if adjusted_xp < hard:
            return "Medium"
        if adjusted_xp < deadly:
            return "Hard"
        return "Deadly"

    def _suggest(self) -> None:
        dialog = SuggestDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        levels = self._current_levels()
        target = self._compute_target_xp(levels, self._difficulty_key())
        filters = self._suggest_filters()
        entries = suggest_monsters(
            target, self._monsters, dialog.max_monsters(), dialog.method(), filters
        )
        if dialog.auto_add():
            for entry in entries:
                self._add_monster(entry.monster, entry.count)
        else:
            QMessageBox.information(
                self, "Suggestions", "Suggestion list ready. Enable auto-add to insert."
            )

    def _suggest_filters(self) -> SuggestFilters:
        search = self._search.text().strip() or None
        min_xp = self._xp_min.value() or None
        max_xp = self._xp_max.value() or None
        cr_value = self._cr_combo.currentText()
        cr_values = None if cr_value == "Any CR" else {cr_value}
        selected_tags = set(parse_tags_text(self._tags_input.text()))
        return SuggestFilters(
            search=search,
            min_xp=min_xp,
            max_xp=max_xp,
            cr_values=cr_values,
            tags=selected_tags or None,
        )

    def new_encounter(self) -> None:
        self._encounter_entries = []
        self._refresh_encounter()

    def _encounters_dir(self) -> Path:
        return dnd_saves_dir() / "encounters"

    def save_encounter(self, name: Optional[str] = None) -> None:
        if not name:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save Encounter",
                str(self._encounters_dir()),
                "Encounter (*.json)",
            )
            if not filename:
                return
            path = Path(filename)
        else:
            path = self._encounters_dir() / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._serialize_encounter(path.stem)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        QMessageBox.information(self, "Encounter", f"Saved {path.name}.")

    def load_encounter(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "Encounter", "Encounter file not found.")
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self._encounter_entries = []
        levels = data.get("party_levels") or []
        self._party_size_slider.setValue(max(1, len(levels)))
        self._rebuild_levels(self._party_size_slider.value())
        for index, level in enumerate(levels):
            if index >= len(self._level_sliders):
                break
            self._level_sliders[index].setValue(int(level))
        difficulty = (data.get("difficulty") or "Medium").lower()
        if difficulty in self._difficulty_keys:
            self._difficulty_combo.setCurrentText(difficulty.title())

        for entry_data in data.get("monsters", []):
            cr = entry_data.get("cr", "")
            monster = Monster(
                id=entry_data.get("id", ""),
                name=entry_data.get("name", ""),
                cr=cr,
                cr_value=parse_cr_value(cr) if cr else 0.0,
                xp=int(entry_data.get("xp", 0)),
                hp=int(entry_data.get("hp", 0)),
                ac=int(entry_data.get("ac", 0)),
                strength=int(entry_data.get("str", 10)),
                dexterity=int(entry_data.get("dex", 10)),
                constitution=int(entry_data.get("con", 10)),
                intelligence=int(entry_data.get("int", 10)),
                wisdom=int(entry_data.get("wis", 10)),
                charisma=int(entry_data.get("cha", 10)),
                actions=entry_data.get("actions", ""),
                description=entry_data.get("description", ""),
                tags=tuple(entry_data.get("tags", [])),
                source=entry_data.get("source", ""),
                icon_path=entry_data.get("icon_path", ""),
                transient=bool(entry_data.get("transient", False)),
            )
            count = int(entry_data.get("count", 1))
            self._encounter_entries.append(EncounterEntry(monster=monster, count=count))
        self._refresh_encounter()

    def export_encounter(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self._serialize_encounter(path.stem)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def _export_dialog(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Encounter",
            str(self._encounters_dir()),
            "Encounter (*.json)",
        )
        if not filename:
            return
        self.export_encounter(Path(filename))

    def _serialize_encounter(self, name: str) -> dict:
        levels = self._current_levels()
        raw_xp, multiplier, adjusted_xp = compute_adjusted_xp(
            self._encounter_entries, self._party_size_slider.value()
        )
        return {
            "schema_version": 1,
            "name": name,
            "party_levels": levels,
            "difficulty": self._difficulty_combo.currentText(),
            "monsters": [
                {
                    "id": entry.monster.id,
                    "name": entry.monster.name,
                    "cr": entry.monster.cr,
                    "xp": entry.monster.xp,
                    "hp": entry.monster.hp,
                    "ac": entry.monster.ac,
                    "str": entry.monster.strength,
                    "dex": entry.monster.dexterity,
                    "con": entry.monster.constitution,
                    "int": entry.monster.intelligence,
                    "wis": entry.monster.wisdom,
                    "cha": entry.monster.charisma,
                    "actions": entry.monster.actions,
                    "description": entry.monster.description,
                    "tags": list(entry.monster.tags),
                    "source": entry.monster.source,
                    "icon_path": entry.monster.icon_path,
                    "count": entry.count,
                    "transient": entry.monster.transient,
                }
                for entry in self._encounter_entries
            ],
            "raw_xp": raw_xp,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "created_at": datetime.now().isoformat(),
        }

    def _settings_path(self) -> Path:
        return dnd_saves_dir() / "settings" / "encounter_settings.json"

    def _load_settings(self) -> dict:
        path = self._settings_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self) -> None:
        path = self._settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._settings, indent=2), encoding="utf-8")

    def _sort_index_from_mode(self, mode: str) -> int:
        if mode == "asc":
            return 1
        if mode == "desc":
            return 2
        return 0

    def _on_sort_changed(self, index: int) -> None:
        self._sort_mode = {0: "none", 1: "asc", 2: "desc"}.get(index, "none")
        self._settings["xp_sort"] = self._sort_mode
        self._save_settings()
        self._apply_filters()
