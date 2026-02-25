from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shlex
import shutil
import subprocess
from datetime import datetime
from typing import List


@dataclass(frozen=True)
class TerminalLine:
    text: str
    is_error: bool = False


_DEBUG_LOG_PATH = Path(__file__).resolve().parents[1] / "debug" / "terminal_session.log"


class TerminalSession:
    def __init__(self, cwd: str | None = None, shell_executable: str | None = None) -> None:
        base_dir = cwd if cwd else os.getcwd()
        expanded = os.path.expandvars(os.path.expanduser(base_dir))
        self._cwd = os.path.abspath(expanded)
        self._shell_kind, self._shell_executable = self._resolve_shell(shell_executable)
        self._debug_log(f"session-start cwd={self._cwd} shell_kind={self._shell_kind} shell={self._shell_executable}")

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def prompt(self) -> str:
        return f"{self._cwd} >"

    def run_command(self, command: str, include_prompt_echo: bool = True) -> List[TerminalLine]:
        trimmed = command.strip()
        if not trimmed:
            return []

        lines: List[TerminalLine] = []
        if include_prompt_echo:
            lines.append(TerminalLine(f"{self.prompt} {trimmed}"))
        self._debug_log(f"run command={trimmed!r} cwd={self._cwd}")
        if trimmed.startswith("/dmt"):
            lines.extend(self._run_native_command(trimmed))
            return lines

        cd_result = self._try_change_directory(trimmed)
        if cd_result is not None:
            lines.extend(cd_result)
            return lines

        lines.extend(self._run_shell_command(trimmed))
        return lines

    def _run_native_command(self, command: str) -> List[TerminalLine]:
        if command == "/dmt test":
            return [TerminalLine("DMT test successful.")]
        return [TerminalLine(f"Unknown /dmt command: {command}", is_error=True)]

    def _try_change_directory(self, command: str) -> List[TerminalLine] | None:
        if command != "cd" and not command.startswith("cd "):
            return None
        parse_as_posix = self._shell_kind != "cmd"
        try:
            tokens = shlex.split(command, posix=parse_as_posix)
        except ValueError as exc:
            return [TerminalLine(f"Invalid cd command: {exc}", is_error=True)]

        if not tokens or tokens[0] != "cd":
            return None
        if len(tokens) > 2:
            return [TerminalLine("cd accepts at most one path argument", is_error=True)]

        target = tokens[1] if len(tokens) == 2 else "~"
        expanded = os.path.expandvars(os.path.expanduser(target))
        resolved = expanded if os.path.isabs(expanded) else os.path.join(self._cwd, expanded)
        new_dir = os.path.abspath(resolved)
        if not os.path.isdir(new_dir):
            return [TerminalLine(f"cd: no such directory: {target}", is_error=True)]

        self._cwd = new_dir
        self._debug_log(f"cd updated cwd={self._cwd}")
        return []

    def _run_shell_command(self, command: str) -> List[TerminalLine]:
        args = self._build_shell_args(command)
        kwargs = {
            "args": args,
            "shell": False,
            "capture_output": True,
            "text": True,
            "cwd": self._cwd,
        }

        try:
            completed = subprocess.run(**kwargs)
        except Exception as exc:
            return [TerminalLine(f"Failed to run command: {exc}", is_error=True)]
        self._debug_log(f"shell-exec args={args!r} returncode={completed.returncode} cwd={self._cwd}")

        lines: List[TerminalLine] = []
        for text_line in self._split_output(completed.stdout):
            lines.append(TerminalLine(text_line))
        for text_line in self._split_output(completed.stderr):
            lines.append(TerminalLine(text_line, is_error=True))

        if completed.returncode != 0 and not lines:
            lines.append(TerminalLine(f"Command failed with exit code {completed.returncode}", is_error=True))
        return lines

    @staticmethod
    def _split_output(output: str) -> List[str]:
        if not output:
            return []
        normalized = output.replace("\r\n", "\n").replace("\r", "\n")
        return [line for line in normalized.split("\n") if line != ""]

    def _resolve_shell(self, preferred_shell: str | None) -> tuple[str, str | None]:
        if preferred_shell:
            shell = os.path.expandvars(os.path.expanduser(preferred_shell))
            return self._kind_for_shell(shell), shell

        env_shell = os.environ.get("SHELL")
        if env_shell:
            shell = os.path.expandvars(os.path.expanduser(env_shell))
            return self._kind_for_shell(shell), shell

        for candidate in ("bash", "sh"):
            path = shutil.which(candidate)
            if path:
                return "posix", path

        if os.name == "nt":
            for candidate in ("pwsh", "powershell"):
                path = shutil.which(candidate)
                if path:
                    return "powershell", path
            comspec = os.environ.get("COMSPEC") or shutil.which("cmd.exe")
            if comspec:
                return "cmd", comspec

        return "system", None

    @staticmethod
    def _kind_for_shell(shell: str) -> str:
        name = Path(shell).name.lower()
        if name in {"bash", "sh", "zsh", "fish", "ksh"} or name.endswith(".sh"):
            return "posix"
        if "powershell" in name or name == "pwsh":
            return "powershell"
        if name in {"cmd", "cmd.exe"}:
            return "cmd"
        return "posix"

    def _build_shell_args(self, command: str):
        if self._shell_executable and self._shell_kind == "posix":
            return [self._shell_executable, "-lc", command]
        if self._shell_executable and self._shell_kind == "powershell":
            return [self._shell_executable, "-NoProfile", "-Command", command]
        if self._shell_executable and self._shell_kind == "cmd":
            return [self._shell_executable, "/C", command]
        return command

    def _debug_log(self, message: str) -> None:
        try:
            _DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().isoformat(timespec="seconds")
            with _DEBUG_LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(f"[{timestamp}] {message}\n")
        except Exception:
            # Debug logging must never break terminal behavior.
            pass
