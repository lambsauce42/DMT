from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(slots=True)
class JournalEntry:
    undo_action: str
    undo_payload: Dict[str, Any]
    redo_action: str
    redo_payload: Dict[str, Any]


class PlayerUndoJournal:
    def __init__(self) -> None:
        self._undo: Dict[str, List[JournalEntry]] = {}
        self._redo: Dict[str, List[JournalEntry]] = {}

    def record(self, player_id: str, entry: JournalEntry) -> None:
        self._undo.setdefault(player_id, []).append(entry)
        self._redo[player_id] = []

    def pop_undo(self, player_id: str) -> Optional[JournalEntry]:
        stack = self._undo.get(player_id)
        if not stack:
            return None
        entry = stack.pop()
        self._redo.setdefault(player_id, []).append(entry)
        return entry

    def pop_redo(self, player_id: str) -> Optional[JournalEntry]:
        stack = self._redo.get(player_id)
        if not stack:
            return None
        entry = stack.pop()
        self._undo.setdefault(player_id, []).append(entry)
        return entry

    def clear_redo(self) -> None:
        for player_id in list(self._redo.keys()):
            self._redo[player_id] = []
