from __future__ import annotations

from pathlib import Path

import pytest

import conftest as tier_config

pytestmark = pytest.mark.tier0

ROOT = Path(__file__).resolve().parents[1]
_DEBUG_LOG = ROOT / "debug" / "test_tier_registry_integrity.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def test_known_test_file_registry_matches_filesystem() -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    tests_dir = Path(__file__).resolve().parent
    actual = {path.name for path in tests_dir.glob("test_*.py")}
    known = set(tier_config._KNOWN_TEST_FILES)
    missing_from_registry = sorted(actual - known)
    stale_in_registry = sorted(known - actual)
    _debug_log(
        "registry-diff "
        f"missing_from_registry={missing_from_registry} "
        f"stale_in_registry={stale_in_registry}"
    )
    assert not missing_from_registry, (
        "Files exist but are not listed in _KNOWN_TEST_FILES: "
        + ", ".join(missing_from_registry)
    )
    assert not stale_in_registry, (
        "Files listed in _KNOWN_TEST_FILES do not exist: "
        + ", ".join(stale_in_registry)
    )
