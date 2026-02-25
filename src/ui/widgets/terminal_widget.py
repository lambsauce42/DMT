from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor, QKeyEvent
from PySide6.QtWidgets import QLabel, QTextEdit, QVBoxLayout, QWidget

from terminal_logic import TerminalSession


_DEBUG_LOG_PATH = Path(__file__).resolve().parents[3] / "debug" / "terminal_widget.log"


class TerminalWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._session = TerminalSession()
        self._input_start = 0
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
        self._terminal_output.setReadOnly(False)
        self._terminal_output.setAcceptRichText(False)
        self._terminal_output.setUndoRedoEnabled(False)
        self._terminal_output.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._terminal_output.setPlaceholderText(
            "Run shell commands, or /dmt test."
        )
        self._terminal_output.installEventFilter(self)
        layout.addWidget(self._terminal_output, 1)
        self._append_prompt_line()
        self._terminal_output.setFocus()

    def eventFilter(self, watched, event):
        if watched is self._terminal_output and event.type() == QEvent.Type.KeyPress:
            return self._handle_key_press(event)
        return super().eventFilter(watched, event)

    def _handle_key_press(self, event: QKeyEvent) -> bool:
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._run_terminal_command()
            return True

        cursor = self._terminal_output.textCursor()
        if key == Qt.Key.Key_Backspace and cursor.position() <= self._input_start:
            return True
        if key == Qt.Key.Key_Delete and cursor.position() < self._input_start:
            return True
        if key == Qt.Key.Key_Left and cursor.position() <= self._input_start:
            return True
        if key == Qt.Key.Key_Home:
            self._move_cursor_to_prompt()
            return True
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown):
            return True

        if self._terminal_output.textCursor().position() < self._input_start:
            self._move_cursor_to_end()
        return False

    def _run_terminal_command(self) -> None:
        command = self._current_command_text()
        self._move_cursor_to_end()
        self._insert_newline()
        responses = self._session.run_command(command, include_prompt_echo=False)
        for response in responses:
            self._append_terminal_line(response.text, response.is_error)
        self._append_prompt_line()
        self._terminal_output.setFocus()

    def _current_command_text(self) -> str:
        text = self._terminal_output.toPlainText()
        if self._input_start >= len(text):
            return ""
        return text[self._input_start :]

    def _append_prompt_line(self) -> None:
        cursor = self._terminal_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        prompt_format = QTextCharFormat()
        prompt_format.setForeground(QColor("#58a6ff"))
        cursor.setCharFormat(prompt_format)
        cursor.insertText(f"{self._session.prompt} ")
        input_format = QTextCharFormat()
        input_format.setForeground(QColor("#e6edf3"))
        cursor.setCharFormat(input_format)
        self._input_start = cursor.position()
        self._terminal_output.setTextCursor(cursor)
        self._terminal_output.ensureCursorVisible()
        self._debug_log(f"prompt-rendered cwd={self._session.cwd}")

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
        self._debug_log(f"line-rendered error={is_error} text={text!r}")

    def _insert_newline(self) -> None:
        cursor = self._terminal_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertBlock()
        self._terminal_output.setTextCursor(cursor)

    def _move_cursor_to_end(self) -> None:
        cursor = self._terminal_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._terminal_output.setTextCursor(cursor)

    def _move_cursor_to_prompt(self) -> None:
        cursor = self._terminal_output.textCursor()
        cursor.setPosition(self._input_start)
        self._terminal_output.setTextCursor(cursor)

    def _debug_log(self, message: str) -> None:
        try:
            _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"[{timestamp}] {message}\n")
        except Exception:
            # Debug logging should never break the terminal.
            pass
