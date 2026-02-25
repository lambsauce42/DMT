import os
from PySide6.QtWidgets import QWidget, QHBoxLayout, QSlider, QLineEdit, QSizePolicy, QVBoxLayout
from PySide6.QtCore import Qt, Signal, QLocale, QSize
from PySide6.QtGui import QIntValidator, QDoubleValidator


class SliderSpinBox(QWidget):
    valueChanged = Signal(object) 
    editingFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("SliderSpinBox")

        # Internal state
        self._value = 0
        self._decimals = 0
        self._minimum = 0
        self._maximum = 100
        self._single_step = 1

        self._init_ui()
        self._update_display()

    def _init_ui(self):
        # We want the slider and the input. 
        # User said: "remove +- buttons on from to xp fields and add a slider instead (of larger than the space for +- buttons.)"
        # I'll put them in a vertical layout or horizontal? 
        # If I want the slider to be larger, maybe horizontal but with a good stretch.
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Line Edit (Left)
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName("SpinBoxInput")
        self.line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.line_edit.setFixedHeight(32)
        self.line_edit.setFixedWidth(60) 
        self._update_validator()
        self.line_edit.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.line_edit)

        # Slider (Right, Expands)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setFixedHeight(32)
        self.slider.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.slider.sliderReleased.connect(self._on_slider_released)
        layout.addWidget(self.slider)

    def _on_slider_moved(self, val):
        # Update text for feedback, but don't emit valueChanged yet
        real_val = val * (10 ** -self._decimals)
        self.line_edit.setText(self._format_value(real_val))

    def _on_slider_released(self):
        # Finalize value and emit
        val = self.slider.value()
        real_val = val * (10 ** -self._decimals)
        self.setValue(real_val)

    def _on_slider_changed(self, val):
        # Kept for direct setValue calls or programmatic changes if needed
        # but disconnected from signals in __init__
        real_val = val * (10 ** -self._decimals)
        self.setValue(real_val)

    def value(self):
        if self._decimals == 0:
            return int(self._value)
        return float(self._value)

    def setValue(self, val):
        # Clamp value
        val = max(self._minimum, min(self._maximum, val))
        old = self._value
        
        if self._decimals == 0:
            self._value = int(val)
        else:
            self._value = float(val)

        # Sync Slider (block signals to avoid recursion)
        self.slider.blockSignals(True)
        self.slider.setRange(int(self._minimum * (10**self._decimals)), int(self._maximum * (10**self._decimals)))
        self.slider.setValue(int(self._value * (10**self._decimals)))
        self.slider.blockSignals(False)

        # Sync LineEdit
        if not self.line_edit.hasFocus():
            self.line_edit.setText(self._format_value(self._value))
             
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
        self.slider.setRange(int(self._minimum * (10**self._decimals)), int(self._maximum * (10**self._decimals)))
        self.setValue(self._value)

    def setMinimum(self, val):
        self.setRange(val, self._maximum)

    def setMaximum(self, val):
        self.setRange(self._minimum, val)

    def setDecimals(self, decimals: int):
        self._decimals = decimals
        self._update_validator()
        self.slider.setRange(int(self._minimum * (10**self._decimals)), int(self._maximum * (10**self._decimals)))
        self.setValue(self._value)

    def _update_validator(self):
        if self._decimals == 0:
            self.line_edit.setValidator(QIntValidator(int(self._minimum), int(self._maximum)))
        else:
            val = QDoubleValidator(float(self._minimum), float(self._maximum), self._decimals)
            val.setNotation(QDoubleValidator.Notation.StandardNotation)
            self.line_edit.setValidator(val)

    def _update_display(self):
        self.line_edit.setText(self._format_value(self._value))

    def _on_editing_finished(self):
        text = self.line_edit.text()
        try:
            if self._decimals == 0:
                val = int(float(text))
            else:
                val = float(text)
            self.setValue(val)
        except ValueError:
            self._update_display()
        self.editingFinished.emit()

    def setAlignment(self, alignment: Qt.AlignmentFlag):
        self.line_edit.setAlignment(alignment)

    def lineEdit(self) -> QLineEdit:
        return self.line_edit
