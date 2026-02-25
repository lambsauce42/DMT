import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLineEdit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ui.widgets.terminal_widget import TerminalWidget


def _terminal_lines(widget: TerminalWidget) -> list[str]:
    return widget._terminal_output.toPlainText().splitlines()


def test_terminal_uses_inline_prompt_without_separate_input_box(qtbot):
    widget = TerminalWidget()
    qtbot.addWidget(widget)

    assert widget.findChildren(QLineEdit) == []
    assert not widget._terminal_output.isReadOnly()
    assert _terminal_lines(widget)[-1] == f"{widget._session.prompt} "
    assert "#58a6ff" in widget._terminal_output.toHtml().lower()


def test_inline_enter_executes_command_and_keeps_prompt_on_last_line(qtbot):
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    output = widget._terminal_output

    output.setFocus()
    qtbot.keyClicks(output, "echo INLINE_PROMPT_TEST")
    qtbot.keyClick(output, Qt.Key_Return)

    lines = _terminal_lines(widget)
    assert any("INLINE_PROMPT_TEST" == line.strip() for line in lines)
    assert lines[-1] == f"{widget._session.prompt} "


def test_cd_changes_inline_prompt_directory(qtbot, tmp_path):
    widget = TerminalWidget()
    qtbot.addWidget(widget)
    output = widget._terminal_output
    target = str(tmp_path).replace("\\", "/")
    old_prompt = widget._session.prompt
    command_line = f'{old_prompt} cd "{target}"'

    output.setFocus()
    qtbot.keyClicks(output, f'cd "{target}"')
    qtbot.keyClick(output, Qt.Key_Return)

    lines = _terminal_lines(widget)
    assert sum(1 for line in lines if line == command_line) == 1
    assert lines[-1] == f"{target} > "
