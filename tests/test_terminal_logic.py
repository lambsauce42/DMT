import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from terminal_logic import TerminalSession


def _line_texts(lines):
    return [line.text for line in lines]


def test_shell_command_runs_in_terminal_session():
    session = TerminalSession()

    lines = session.run_command("echo DMT_REAL_TERMINAL")
    texts = _line_texts(lines)

    assert texts[0] == f"{session.cwd} > echo DMT_REAL_TERMINAL"
    assert any("DMT_REAL_TERMINAL" in text for text in texts[1:])
    assert not any(line.is_error for line in lines[1:])


def test_command_echo_shows_current_directory(tmp_path):
    session = TerminalSession(cwd=str(tmp_path))

    lines = session.run_command("echo prompt")
    texts = _line_texts(lines)

    assert texts[0] == f"{str(tmp_path)} > echo prompt"


def test_dmt_test_is_supported_native_command():
    session = TerminalSession()

    lines = session.run_command("/dmt test")
    texts = _line_texts(lines)

    assert texts == [f"{session.cwd} > /dmt test", "DMT test successful."]
    assert all(not line.is_error for line in lines)


def test_cd_updates_working_directory_for_next_command(tmp_path):
    session = TerminalSession(cwd=str(tmp_path.parent))
    target = str(tmp_path).replace("\\", "/")

    cd_lines = session.run_command(f'cd "{target}"')
    cd_texts = _line_texts(cd_lines)
    assert cd_texts[0] == f'{str(tmp_path.parent)} > cd "{target}"'
    assert all(not line.is_error for line in cd_lines)

    pwd_lines = session.run_command("pwd")
    pwd_texts = _line_texts(pwd_lines)

    assert pwd_texts[0] == f"{target} > pwd"
    assert any(target == text.strip() for text in pwd_texts[1:])


def test_explicit_shell_executable_is_invoked_directly(monkeypatch, tmp_path):
    captured = {}

    def _fake_run(*args, **kwargs):
        captured["args"] = kwargs.get("args")
        return subprocess.CompletedProcess(kwargs.get("args"), 0, stdout="", stderr="")

    monkeypatch.setattr("terminal_logic.subprocess.run", _fake_run)

    session = TerminalSession(cwd=str(tmp_path), shell_executable="/bin/bash")
    lines = session.run_command("ls")

    assert captured["args"] == ["/bin/bash", "-lc", "ls"]
    assert all(not line.is_error for line in lines)
