from __future__ import annotations

import pytest

import bundled_data

pytestmark = pytest.mark.tier0


def test_frozen_data_dir_extracts_bundled_files_into_save_path(tmp_path, monkeypatch):
    bundle_root = tmp_path / "bundle"
    save_root = tmp_path / "save"
    for relative in (
        "data/dnd_monsters_full.csv",
        "data/EncounterDifficulty.csv",
        "data/EncounterMultipliers.csv",
        "data/5e_CharacterSheet.pdf",
    ):
        target = bundle_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(relative, encoding="utf-8")

    monkeypatch.setattr(bundled_data.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bundled_data.sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(bundled_data, "dnd_saves_dir", lambda: save_root)

    extracted_dir = bundled_data.data_dir()

    assert extracted_dir == save_root / "cache" / "bundled_runtime_data" / f"pid_{bundled_data.os.getpid()}" / "data"
    assert (extracted_dir / "dnd_monsters_full.csv").read_text(encoding="utf-8") == "data/dnd_monsters_full.csv"
    assert (extracted_dir / "5e_CharacterSheet.pdf").read_text(encoding="utf-8") == "data/5e_CharacterSheet.pdf"


def test_cleanup_current_bundled_runtime_data_removes_pid_directory(tmp_path, monkeypatch):
    save_root = tmp_path / "save"
    monkeypatch.setattr(bundled_data.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bundled_data, "dnd_saves_dir", lambda: save_root)

    runtime_dir = bundled_data.data_dir()
    marker = runtime_dir / "marker.txt"
    marker.write_text("keep", encoding="utf-8")

    bundled_data.cleanup_current_bundled_runtime_data()

    assert not runtime_dir.parent.exists()
