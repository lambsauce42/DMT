from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.tier2

ROOT = Path(__file__).resolve().parents[1]
_DEBUG_LOG = ROOT / "debug" / "test_pytest_discovery_scope.log"


def _debug_log(line: str) -> None:
    _DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _DEBUG_LOG.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")


def test_root_pytest_collect_only_is_scoped_to_tests_dir() -> None:
    _DEBUG_LOG.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "--tier-max=1"]
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    _debug_log(f"cmd={' '.join(cmd)}")
    _debug_log(f"returncode={result.returncode}")
    _debug_log("stdout:")
    _debug_log(result.stdout)
    _debug_log("stderr:")
    _debug_log(result.stderr)

    output = (result.stdout + "\n" + result.stderr).replace("\\", "/")
    assert result.returncode == 0, output
    assert "debug/test_" not in output
