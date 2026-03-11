from __future__ import annotations

import pytest

import asset_paths

pytestmark = pytest.mark.tier0


@pytest.fixture(autouse=True)
def _reset_asset_path_warnings() -> None:
    asset_paths._WARNED_MISSING_RESOURCES.clear()


def test_source_resource_path_uses_repo_assets(monkeypatch):
    monkeypatch.setattr(asset_paths.sys, "frozen", False, raising=False)
    monkeypatch.setattr(asset_paths.sys, "_MEIPASS", "", raising=False)

    close_icon = asset_paths.icon_path("close.svg")
    helper = asset_paths.resource_path("loading_indicator_process.py")

    assert close_icon.exists()
    assert close_icon.name == "close.svg"
    assert helper.exists()
    assert helper.name == "loading_indicator_process.py"


def test_frozen_resource_path_prefers_bundle_root(tmp_path, monkeypatch):
    bundle_root = tmp_path / "bundle"
    bundled_icon = bundle_root / "assets" / "icons" / "close.svg"
    bundled_helper = bundle_root / "loading_indicator_process.py"
    bundled_icon.parent.mkdir(parents=True, exist_ok=True)
    bundled_icon.write_text("bundled-close", encoding="utf-8")
    bundled_helper.write_text("bundled-helper", encoding="utf-8")

    monkeypatch.setattr(asset_paths.sys, "frozen", True, raising=False)
    monkeypatch.setattr(asset_paths.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(asset_paths.sys, "executable", str(tmp_path / "DMT.exe"), raising=False)

    assert asset_paths.icon_path("close.svg") == bundled_icon
    assert asset_paths.resource_path("loading_indicator_process.py") == bundled_helper
