"""
Custom encounter selection dialog that replaces the Windows file picker
with a fancy, themed selection window.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont, QIcon, QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QWidget,
    QFrame,
    QPushButton,
    QLineEdit,
    QSizePolicy,
    QGraphicsDropShadowEffect,
)

from asset_paths import icons_dir
from dmt_package import read_dmt_package_info
from save_paths import dnd_saves_dir


ICON_DIR = str(icons_dir())
ENCOUNTER_FILE_EXTENSION = ".dmtencounter"
ENCOUNTER_FILE_FORMAT = "dmtencounter.v1"


class EncounterCard(QFrame):
    """A single encounter card showing encounter preview info."""
    
    clicked = Signal(Path)
    double_clicked = Signal(Path)
    
    def __init__(self, path: Path, data: dict, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._path = path
        self._data = data if isinstance(data, dict) else {}
        self._selected = False
        
        self.setObjectName("EncounterCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(80)
        self.setMaximumHeight(100)
        
        self._setup_ui()
        self._update_style()
        
    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(16)
        
        # Left side: Icon
        icon_container = QFrame(self)
        icon_container.setFixedSize(56, 56)
        icon_container.setObjectName("EncounterIconContainer")
        icon_layout = QVBoxLayout(icon_container)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        icon_label = QLabel(icon_container)
        icon_path = os.path.join(ICON_DIR, "encounter.svg")
        if os.path.exists(icon_path):
            icon_label.setPixmap(QIcon(icon_path).pixmap(QSize(28, 28)))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(icon_label)
        
        layout.addWidget(icon_container)
        
        # Middle: Encounter info
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(4)
        
        # Name
        name = self._data.get("name", self._path.stem)
        self._name_label = QLabel(name, self)
        self._name_label.setObjectName("EncounterCardTitle")
        name_font = self._name_label.font()
        name_font.setPointSize(13)
        name_font.setBold(True)
        self._name_label.setFont(name_font)
        info_layout.addWidget(self._name_label)
        
        # Subtitle line 1: Monster count and total XP
        monsters = self._data.get("monsters", [])
        total_monsters = sum(int(m.get("count", 1)) for m in monsters)
        unique_monsters = len(monsters)
        total_xp = sum(int(m.get("xp", 0)) * int(m.get("count", 1)) for m in monsters)
        
        subtitle = f"{total_monsters} monster{'s' if total_monsters != 1 else ''}"
        if unique_monsters != total_monsters:
            subtitle += f" ({unique_monsters} unique)"
        subtitle += f" • {total_xp:,} XP"
        
        subtitle_label = QLabel(subtitle, self)
        subtitle_label.setObjectName("EncounterCardSubtitle")
        subtitle_font = subtitle_label.font()
        subtitle_font.setPointSize(10)
        subtitle_label.setFont(subtitle_font)
        info_layout.addWidget(subtitle_label)
        
        # Subtitle line 2: Difficulty and party info
        difficulty = self._data.get("difficulty", "Unknown")
        party_levels = self._data.get("party_levels", [])
        party_size = len(party_levels)
        
        if party_size > 0:
            avg_level = sum(party_levels) / party_size
            detail_text = f"{difficulty.title()} • Party of {party_size} (avg lvl {avg_level:.0f})"
        else:
            detail_text = f"{difficulty.title()}"
        
        detail_label = QLabel(detail_text, self)
        detail_label.setObjectName("EncounterCardDetail")
        detail_font = detail_label.font()
        detail_font.setPointSize(9)
        detail_label.setFont(detail_font)
        info_layout.addWidget(detail_label)
        
        info_layout.addStretch(1)
        layout.addLayout(info_layout, 1)
        
        # Right side: Difficulty indicator
        difficulty_chip = self._create_difficulty_chip(difficulty.lower())
        layout.addWidget(difficulty_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        
    def _create_difficulty_chip(self, difficulty: str) -> QFrame:
        chip = QFrame(self)
        chip.setFixedSize(70, 24)
        chip.setObjectName("DifficultyChip")
        
        chip_layout = QHBoxLayout(chip)
        chip_layout.setContentsMargins(8, 0, 8, 0)
        chip_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        label = QLabel(difficulty.title(), chip)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip_font = label.font()
        chip_font.setPointSize(9)
        chip_font.setBold(True)
        label.setFont(chip_font)
        
        # Apply difficulty-specific colors
        colors = {
            "easy": ("#1f6f3d", "#3fb950"),
            "medium": ("#6e4a0a", "#d29922"),
            "hard": ("#7a1f1f", "#f85149"),
            "deadly": ("#8b0000", "#ff7b72"),
        }
        bg_color, border_color = colors.get(difficulty, ("#21262d", "#30363d"))
        chip.setStyleSheet(f"""
            QFrame#DifficultyChip {{
                background-color: {bg_color};
                border: 1px solid {border_color};
                border-radius: 12px;
            }}
            QLabel {{
                color: #ffffff;
                background-color: transparent;
            }}
        """)
        
        chip_layout.addWidget(label)
        return chip
        
    def _update_style(self) -> None:
        if self._selected:
            self.setStyleSheet("""
                QFrame#EncounterCard {
                    background-color: #1e2a3a;
                    border: 2px solid #60a5fa;
                    border-radius: 12px;
                }
                QFrame#EncounterIconContainer {
                    background-color: #304050;
                    border-radius: 12px;
                }
                QLabel#EncounterCardTitle {
                    color: #60a5fa;
                }
                QLabel#EncounterCardSubtitle {
                    color: #9aa4b2;
                }
                QLabel#EncounterCardDetail {
                    color: #6b7280;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#EncounterCard {
                    background-color: #161b22;
                    border: 1px solid #30363d;
                    border-radius: 12px;
                }
                QFrame#EncounterCard:hover {
                    background-color: #1c2128;
                    border-color: #3d4450;
                }
                QFrame#EncounterIconContainer {
                    background-color: #21262d;
                    border-radius: 12px;
                }
                QLabel#EncounterCardTitle {
                    color: #e5e7eb;
                }
                QLabel#EncounterCardSubtitle {
                    color: #9aa4b2;
                }
                QLabel#EncounterCardDetail {
                    color: #6b7280;
                }
            """)
    
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._update_style()
        
    def is_selected(self) -> bool:
        return self._selected
        
    def path(self) -> Path:
        return self._path
        
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._path)
        super().mousePressEvent(event)
        
    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._path)
        super().mouseDoubleClickEvent(event)


class EncounterSelectorDialog(QDialog):
    """A fancy encounter selection dialog that browses the default encounters directory."""
    
    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._selected_path: Optional[Path] = None
        self._cards: list[EncounterCard] = []
        
        self.setWindowTitle("Select Encounter")
        self.setMinimumSize(550, 500)
        self.resize(600, 600)
        self.setModal(True)
        
        self._setup_ui()
        self._load_encounters()
        
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        
        # Header
        header_layout = QVBoxLayout()
        header_layout.setSpacing(4)
        
        title_label = QLabel("Select Encounter to Spawn", self)
        title_font = title_label.font()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #e5e7eb;")
        header_layout.addWidget(title_label)
        
        subtitle_label = QLabel("Choose an encounter from your saved encounters", self)
        subtitle_font = subtitle_label.font()
        subtitle_font.setPointSize(11)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet("color: #9aa4b2;")
        header_layout.addWidget(subtitle_label)
        
        layout.addLayout(header_layout)
        
        # Search bar
        search_container = QFrame(self)
        search_container.setObjectName("TransparentContainer")
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Search encounters...")
        self._search.setMinimumHeight(40)
        self._search.setStyleSheet("""
            QLineEdit {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 8px 12px;
                color: #e5e7eb;
                font-size: 13px;
            }
            QLineEdit:focus {
                border-color: #60a5fa;
            }
            QLineEdit::placeholder {
                color: #6b7280;
            }
        """)
        self._search.textChanged.connect(self._filter_encounters)
        search_layout.addWidget(self._search)
        
        layout.addWidget(search_container)
        
        # Scroll area for encounter cards
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
            }
            QScrollBar:vertical {
                background-color: #0d1117;
                width: 10px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #30363d;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #3d4450;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        self._cards_container = QWidget(scroll)
        self._cards_container.setObjectName("TransparentContainer")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 8, 0)
        self._cards_layout.setSpacing(8)
        scroll.setWidget(self._cards_container)
        
        layout.addWidget(scroll, 1)
        
        # Empty state label (initially hidden)
        self._empty_label = QLabel("No encounters found.\nCreate encounters in the Encounter Panel first.", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_font = self._empty_label.font()
        empty_font.setPointSize(12)
        self._empty_label.setFont(empty_font)
        self._empty_label.setStyleSheet("color: #6b7280; padding: 40px;")
        self._empty_label.hide()
        layout.addWidget(self._empty_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.setFixedHeight(40)
        cancel_btn.setMinimumWidth(100)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #21262d;
                border: 1px solid #30363d;
                border-radius: 8px;
                color: #e5e7eb;
                font-size: 13px;
                font-weight: 600;
                padding: 8px 24px;
            }
            QPushButton:hover {
                background-color: #30363d;
            }
            QPushButton:pressed {
                background-color: #1c2128;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        
        self._select_btn = QPushButton("Select Encounter", self)
        self._select_btn.setFixedHeight(40)
        self._select_btn.setMinimumWidth(140)
        self._select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_btn.setEnabled(False)
        self._select_btn.setStyleSheet("""
            QPushButton {
                background-color: #238636;
                border: 1px solid #2ea043;
                border-radius: 8px;
                color: #ffffff;
                font-size: 13px;
                font-weight: 600;
                padding: 8px 24px;
            }
            QPushButton:hover {
                background-color: #2ea043;
            }
            QPushButton:pressed {
                background-color: #1f7a32;
            }
            QPushButton:disabled {
                background-color: #21262d;
                border-color: #30363d;
                color: #6b7280;
            }
        """)
        self._select_btn.clicked.connect(self.accept)
        
        button_layout.addStretch(1)
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(self._select_btn)
        
        layout.addLayout(button_layout)
        
        # Dialog styling
        self.setStyleSheet("""
            QDialog {
                background-color: #0d1117;
            }
        """)
        
    def _encounters_dir(self) -> Path:
        return dnd_saves_dir() / "encounters"
        
    def _load_encounters(self) -> None:
        # Clear existing cards
        for card in self._cards:
            card.deleteLater()
        self._cards.clear()
        
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        
        encounters_dir = self._encounters_dir()
        if not encounters_dir.exists():
            encounters_dir.mkdir(parents=True, exist_ok=True)
            
        encounter_files = sorted(
            encounters_dir.glob(f"*{ENCOUNTER_FILE_EXTENSION}"),
            key=lambda p: p.stem.lower(),
        )
        
        if not encounter_files:
            self._empty_label.show()
            return
            
        self._empty_label.hide()
        
        for path in encounter_files:
            try:
                data = read_dmt_package_info(path)
                if not isinstance(data, dict):
                    continue
                if str(data.get("format") or "") != ENCOUNTER_FILE_FORMAT:
                    continue
                card = EncounterCard(path, data, self._cards_container)
                card.clicked.connect(self._on_card_clicked)
                card.double_clicked.connect(self._on_card_double_clicked)
                self._cards.append(card)
                self._cards_layout.addWidget(card)
            except (OSError, TypeError, ValueError, AttributeError):
                # Skip malformed or unreadable files
                continue
                
        self._cards_layout.addStretch(1)
        
    def _filter_encounters(self, text: str) -> None:
        search_lower = text.strip().lower()
        for card in self._cards:
            name = card._data.get("name", card._path.stem)
            visible = not search_lower or search_lower in name.lower()
            card.setVisible(visible)
            
    def _on_card_clicked(self, path: Path) -> None:
        # Deselect all other cards
        for card in self._cards:
            card.set_selected(card.path() == path)
            
        self._selected_path = path
        self._select_btn.setEnabled(True)
        
    def _on_card_double_clicked(self, path: Path) -> None:
        self._selected_path = path
        self.accept()
        
    def selected_path(self) -> Optional[Path]:
        return self._selected_path
        
    def selected_data(self) -> Optional[dict]:
        if self._selected_path is None or not self._selected_path.exists():
            return None
        try:
            payload = read_dmt_package_info(self._selected_path)
            return payload if isinstance(payload, dict) else None
        except OSError:
            return None
