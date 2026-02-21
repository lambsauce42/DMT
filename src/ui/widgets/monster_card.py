from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.widgets.plus_minus_spinbox import PlusMinusSpinBox
from encounter_engine import Monster


class MonsterCard(QFrame):
    def __init__(
        self,
        monster: Monster,
        on_add: Callable[[Monster, int], None],
        on_modify: Callable[[Monster, int], None],
        on_expand_request: Callable[["MonsterCard", bool], None],
    ) -> None:
        super().__init__()
        self.monster = monster
        self._on_add = on_add
        self._on_modify = on_modify
        self._on_expand_request = on_expand_request
        self._expanded = False

        self.setObjectName("SubPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(5)

        header = QHBoxLayout()
        header.setSpacing(6)

        avatar = QLabel(monster.name[:1].upper())
        avatar.setFixedSize(22, 22)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setObjectName("CardIcon")
        self._toggle = QToolButton(self)
        self._toggle.setText("Details")
        self._toggle.setCheckable(True)
        self._toggle.setChecked(False)
        self._toggle.clicked.connect(self._toggle_expanded)
        self._toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        name_label = QLabel(monster.name)
        name_label.setObjectName("PanelTitle")
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        name_label.setMinimumWidth(0)
        name_label.setWordWrap(True)

        hp_ac_label = QLabel(f"HP {monster.hp} • AC {monster.ac}")
        hp_ac_label.setMinimumWidth(0)
        stats_text = (
            f"STR {monster.strength} DEX {monster.dexterity} CON {monster.constitution} "
            f"INT {monster.intelligence} WIS {monster.wisdom} CHA {monster.charisma}"
        )
        self._stats_text_full = stats_text
        self._stats_text_compact = (
            f"S{monster.strength} D{monster.dexterity} Co{monster.constitution} "
            f"I{monster.intelligence} W{monster.wisdom} Ch{monster.charisma}"
        )
        self._stats_label = QLabel(stats_text)
        self._stats_label.setToolTip(stats_text)
        self._stats_label.setWordWrap(False)
        self._stats_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._stats_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._stats_label.setMinimumWidth(0)
        self._stats_label.setContentsMargins(6, 0, 6, 0)

        xp_label = QLabel(f"{monster.xp} XP")
        xp_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        xp_label.setMinimumWidth(0)

        header.addWidget(avatar)
        header.addWidget(name_label, 1)
        header.addWidget(hp_ac_label)
        header.addWidget(self._stats_label, 2)
        header.addStretch(1)
        header.addWidget(xp_label)
        header.addWidget(self._toggle)
        outer.addLayout(header)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)
        count_label = QLabel("Count")
        self._count_spin = PlusMinusSpinBox()
        self._count_spin.setRange(1, 99)
        self._count_spin.setValue(1)
        self._count_spin.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        add_button = QPushButton("Add")
        add_button.setObjectName("PrimaryButton")
        add_button.setProperty("compact", True)
        add_button.clicked.connect(self._handle_add)
        add_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        modify_button = QPushButton("Modify & Add")
        modify_button.setObjectName("SecondaryButton")
        modify_button.setProperty("compact", True)
        modify_button.clicked.connect(self._handle_modify)
        modify_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        actions_row.addWidget(count_label)
        actions_row.addWidget(self._count_spin)
        actions_row.addStretch(1)
        actions_row.addWidget(add_button)
        actions_row.addWidget(modify_button)
        outer.addLayout(actions_row)

        self._details = QWidget(self)
        details_layout = QVBoxLayout(self._details)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(4)

        stats = QLabel(f"HP {monster.hp} • AC {monster.ac}")
        tags_text = ", ".join(monster.tags) if monster.tags else "No tags"
        tags = QLabel(f"Tags: {tags_text}")
        source = QLabel(f"Source: {monster.source}")
        description_text = (monster.description or "").strip()
        description = QLabel(description_text)
        description.setWordWrap(True)
        actions = QLabel(monster.actions or "No actions listed.")
        actions.setWordWrap(True)

        details_layout.addWidget(stats)
        details_layout.addWidget(tags)
        details_layout.addWidget(source)
        if description_text:
            details_layout.addWidget(description)
        details_layout.addWidget(actions)

        self._details.setVisible(False)
        outer.addWidget(self._details)
        self._update_stats_label()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_stats_label()

    def _update_stats_label(self) -> None:
        if not hasattr(self, "_stats_label"):
            return
        metrics = self._stats_label.fontMetrics()
        available = max(0, self._stats_label.width())
        if metrics.horizontalAdvance(self._stats_text_full) <= available:
            text = self._stats_text_full
        elif metrics.horizontalAdvance(self._stats_text_compact) <= available:
            text = self._stats_text_compact
        else:
            text = metrics.elidedText(
                self._stats_text_compact,
                Qt.TextElideMode.ElideRight,
                available,
            )
        if self._stats_label.text() != text:
            self._stats_label.setText(text)

    def _toggle_expanded(self) -> None:
        self._expanded = self._toggle.isChecked()
        self._on_expand_request(self, self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._toggle.blockSignals(True)
        self._toggle.setChecked(expanded)
        self._toggle.blockSignals(False)
        self._details.setVisible(expanded)

    def is_expanded(self) -> bool:
        return self._expanded

    def _handle_add(self) -> None:
        self._on_add(self.monster, self._count_spin.value())

    def _handle_modify(self) -> None:
        self._on_modify(self.monster, self._count_spin.value())
