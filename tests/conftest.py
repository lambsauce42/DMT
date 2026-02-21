"""Pytest configuration for DMT tests.

This ensures pytest-qt uses PyQt6 (matching the application code) instead of
auto-detecting PySide6 which causes QWidget type mismatches.

CRITICAL: QT_API must be set before any Qt bindings are imported.
"""
import os
os.environ["QT_API"] = "pyqt6"
os.environ["PYTEST_QT_API"] = "pyqt6"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DMT_TEST_MODE", "1")

import pytest
