from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from encounter_engine import (
    EncounterDataError,
    Monster,
    make_transient_monster,
    parse_cr_value,
    parse_tags_text,
)


class ModifyMonsterDialog(QDialog):
    def __init__(self, monster: Monster, count: int, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Modify Monster")
        self._result_monster: Optional[Monster] = None
        self._result_count: int = count

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._name = QLineEdit(monster.name)
        self._cr = QLineEdit(monster.cr)
        self._xp = QSpinBox()
        self._xp.setRange(0, 500000)
        self._xp.setValue(monster.xp)
        self._hp = QSpinBox()
        self._hp.setRange(0, 5000)
        self._hp.setValue(monster.hp)
        self._ac = QSpinBox()
        self._ac.setRange(0, 40)
        self._ac.setValue(monster.ac)
        self._tags = QLineEdit(", ".join(monster.tags))
        self._source = QLineEdit(monster.source)
        self._count = QSpinBox()
        self._count.setRange(1, 99)
        self._count.setValue(max(1, count))
        self._str = QSpinBox()
        self._str.setRange(1, 30)
        self._str.setValue(monster.strength)
        self._dex = QSpinBox()
        self._dex.setRange(1, 30)
        self._dex.setValue(monster.dexterity)
        self._con = QSpinBox()
        self._con.setRange(1, 30)
        self._con.setValue(monster.constitution)
        self._int = QSpinBox()
        self._int.setRange(1, 30)
        self._int.setValue(monster.intelligence)
        self._wis = QSpinBox()
        self._wis.setRange(1, 30)
        self._wis.setValue(monster.wisdom)
        self._cha = QSpinBox()
        self._cha.setRange(1, 30)
        self._cha.setValue(monster.charisma)
        self._description = QPlainTextEdit(monster.description)
        self._description.setMinimumHeight(80)
        self._actions = QPlainTextEdit(monster.actions)
        self._actions.setMinimumHeight(120)

        form.addRow("Name", self._name)
        form.addRow("CR", self._cr)
        form.addRow("XP", self._xp)
        form.addRow("HP", self._hp)
        form.addRow("AC", self._ac)
        form.addRow("Tags (comma-separated)", self._tags)
        form.addRow("Source", self._source)
        form.addRow("Count", self._count)
        form.addRow("STR", self._str)
        form.addRow("DEX", self._dex)
        form.addRow("CON", self._con)
        form.addRow("INT", self._int)
        form.addRow("WIS", self._wis)
        form.addRow("CHA", self._cha)
        form.addRow(QLabel("Description"))
        form.addRow(self._description)
        form.addRow(QLabel("Actions"))
        form.addRow(self._actions)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._base = monster

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self.accept()
                return
        super().keyPressEvent(event)

    def accept(self) -> None:
        name = self._name.text().strip() or self._base.name
        cr = self._cr.text().strip() or self._base.cr
        try:
            parse_cr_value(cr)
        except EncounterDataError as exc:
            QMessageBox.warning(self, "Invalid CR", str(exc))
            return
        tags = parse_tags_text(self._tags.text())
        self._result_monster = make_transient_monster(
            self._base,
            name=name,
            cr=cr,
            xp=self._xp.value(),
            hp=self._hp.value(),
            ac=self._ac.value(),
            actions=self._actions.toPlainText().strip(),
            description=self._description.toPlainText().strip(),
            tags=tags,
            source=self._source.text().strip(),
            strength=self._str.value(),
            dexterity=self._dex.value(),
            constitution=self._con.value(),
            intelligence=self._int.value(),
            wisdom=self._wis.value(),
            charisma=self._cha.value(),
        )
        self._result_count = self._count.value()
        super().accept()

    def result_monster(self) -> Optional[Monster]:
        return self._result_monster

    def result_count(self) -> int:
        return self._result_count
