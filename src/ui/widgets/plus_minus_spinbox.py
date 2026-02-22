import os
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLineEdit, QSizePolicy
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QLocale, QSize
from PyQt6.QtGui import QIntValidator, QDoubleValidator, QIcon


ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "assets", "icons"))

class PlusMinusSpinBox(QWidget):
    # Emit object to support both int and float
    valueChanged = pyqtSignal(object) 
    editingFinished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("PlusMinusSpinBox")

        # Internal state
        self._value = 0
        self._decimals = 0
        self._minimum = 0
        self._maximum = 100
        self._single_step = 1

        self._init_ui()
        self._update_display()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Line Edit (Left, Expands)
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName("SpinBoxInput")
        self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.line_edit.setFixedHeight(32)
        self.line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._update_validator()
        self.line_edit.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.line_edit)

        # Minus Button
        self.minus_btn = QPushButton()
        self.minus_btn.setIcon(QIcon(os.path.join(ICON_DIR, "minus.svg")))
        self.minus_btn.setIconSize(QSize(14, 14))
        self.minus_btn.setObjectName("SpinBoxButton")
        self.minus_btn.setFixedSize(32, 32)
        self.minus_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.minus_btn.setAutoRepeat(True)
        self.minus_btn.setAutoRepeatDelay(500)
        self.minus_btn.setAutoRepeatInterval(50)
        self.minus_btn.clicked.connect(self.step_down)
        layout.addWidget(self.minus_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        # Plus Button
        self.plus_btn = QPushButton()
        self.plus_btn.setIcon(QIcon(os.path.join(ICON_DIR, "plus.svg")))
        self.plus_btn.setIconSize(QSize(14, 14))
        self.plus_btn.setObjectName("SpinBoxButton")
        self.plus_btn.setFixedSize(32, 32)
        self.plus_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.plus_btn.setAutoRepeat(True)
        self.plus_btn.setAutoRepeatDelay(500)
        self.plus_btn.setAutoRepeatInterval(50)
        self.plus_btn.clicked.connect(self.step_up)
        layout.addWidget(self.plus_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def value(self):
        if self._decimals == 0:
            return int(self._value)
        return float(self._value)

    def setValue(self, val):
        old = self._value
        
        # Clamp value
        val = max(self._minimum, min(self._maximum, val))
        
        if self._decimals == 0:
            self._value = int(val)
        else:
            self._value = float(val)

        # Update display if needed
        # We assume standard formatting. If user types "05", it becomes "5".
        current_text = self.line_edit.text()
        formatted = self._format_value(self._value)
        
        # Avoid resetting text if it parses to the same value (e.g. "1.50" vs "1.5")
        # unless it's strictly different.
        try:
            if self._decimals == 0:
                text_val = int(current_text)
            else:
                text_val = float(current_text)
        except ValueError:
            text_val = None
            
        if text_val != self._value:
             self.line_edit.setText(formatted)
             
        if self._value != old:
            self.valueChanged.emit(self.value())

    def _format_value(self, val):
        if self._decimals == 0:
            return str(int(val))
        return f"{val:.{self._decimals}f}"

    def setRange(self, min_val, max_val):
        self._minimum = min_val
        self._maximum = max_val
        self._update_validator()
        self.setValue(self._value)

    def setMinimum(self, val):
        self.setRange(val, self._maximum)

    def setMaximum(self, val):
        self.setRange(self._minimum, val)

    def setSingleStep(self, step):
        self._single_step = step

    def setDecimals(self, decimals: int):
        self._decimals = decimals
        self._update_validator()
        self.setValue(self._value)

    def _update_validator(self):
        if self._decimals == 0:
            self.line_edit.setValidator(QIntValidator(int(self._minimum), int(self._maximum)))
        else:
            val = QDoubleValidator(float(self._minimum), float(self._maximum), self._decimals)
            val.setNotation(QDoubleValidator.Notation.StandardNotation)
            self.line_edit.setValidator(val)

    def step_up(self):
        self.setValue(self._value + self._single_step)

    def step_down(self):
        self.setValue(self._value - self._single_step)

    def _update_display(self):
        self.line_edit.setText(self._format_value(self._value))

    def _on_editing_finished(self):
        text = self.line_edit.text()
        try:
            if self._decimals == 0:
                val = int(float(text)) # float parse handles "1.0" as 1
            else:
                val = float(text)
            self.setValue(val)
        except ValueError:
            self._update_display()
        self.editingFinished.emit()
    
    # Compatibility
    def setPrefix(self, prefix: str):
        pass 

    def setSuffix(self, suffix: str):
        pass 
        
    def setAlignment(self, alignment: Qt.AlignmentFlag):
        self.line_edit.setAlignment(alignment)

    def lineEdit(self) -> QLineEdit:
        return self.line_edit

    def setKeyboardTracking(self, enabled: bool):
        pass