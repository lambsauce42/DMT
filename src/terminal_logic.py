from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class TerminalLine:
    text: str
    is_error: bool = False


def build_terminal_response(command: str) -> List[TerminalLine]:
    trimmed = command.strip()
    if not trimmed:
        return []
    lines = [TerminalLine(f"> {trimmed}")]
    if trimmed == "/test":
        lines.append(TerminalLine("Test successful."))
    else:
        lines.append(TerminalLine("Unknown command", is_error=True))
    return lines
