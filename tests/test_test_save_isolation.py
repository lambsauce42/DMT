from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from save_paths import default_dnd_save_dir

pytestmark = pytest.mark.tier0

_POLLUTION_MARKER = "__session_pollution_guard__.dmtsession"


def _marker_path() -> Path:
    return Path(default_dnd_save_dir()) / "sessions" / _POLLUTION_MARKER


def test_test_save_artifact_can_be_written() -> None:
    marker = _marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("pollution", encoding="utf-8")
    assert marker.exists()


def test_test_save_artifact_does_not_leak_between_tests() -> None:
    marker = _marker_path()
    assert not marker.exists()
