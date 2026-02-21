from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTextEdit, QLineEdit, QSizePolicy
from PyQt6.QtGui import QTextCursor, QTextCharFormat, QColor
from PyQt6.QtCore import Qt
from terminal_logic import build_terminal_response

class TerminalWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        title = QLabel("Terminal", self)
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self._terminal_output = QTextEdit(self)
        self._terminal_output.setObjectName("TerminalOutput")
        self._terminal_output.setReadOnly(True)
        self._terminal_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._terminal_output.setPlaceholderText(
            "Enter /test to verify the terminal."
        )
        layout.addWidget(self._terminal_output, 1)

        self._terminal_input = QLineEdit(self)
        self._terminal_input.setObjectName("TerminalInput")
        self._terminal_input.setPlaceholderText("Type a command and press Enter")
        self._terminal_input.returnPressed.connect(self._run_terminal_command)
        layout.addWidget(self._terminal_input)

    def _run_terminal_command(self) -> None:
        command = self._terminal_input.text()
        responses = build_terminal_response(command)
        if not responses:
            self._terminal_input.clear()
            return
        for response in responses:
            self._append_terminal_line(response.text, response.is_error)
        self._terminal_input.clear()

    def _append_terminal_line(self, text: str, is_error: bool = False) -> None:
        cursor = self._terminal_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if is_error:
            fmt.setForeground(QColor("#f26d6d"))
        else:
            fmt.setForeground(QColor("#e3e3e3"))
        cursor.setCharFormat(fmt)
        cursor.insertText(text)
        cursor.insertBlock()
        self._terminal_output.setTextCursor(cursor)
        self._terminal_output.ensureCursorVisible()
