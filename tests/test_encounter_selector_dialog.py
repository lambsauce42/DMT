import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ui.encounter_selector_dialog import EncounterSelectorDialog


def test_selector_skips_non_dict_payload_files(qtbot, monkeypatch, tmp_path):
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    valid_path = encounters_dir / "valid.json"
    invalid_path = encounters_dir / "invalid.json"
    valid_path.write_text(json.dumps({"name": "Goblin Ambush", "monsters": []}), encoding="utf-8")
    invalid_path.write_text(json.dumps([{"name": "Not a dict root"}]), encoding="utf-8")

    monkeypatch.setattr(EncounterSelectorDialog, "_encounters_dir", lambda self: encounters_dir)

    dialog = EncounterSelectorDialog()
    qtbot.addWidget(dialog)

    loaded = {card.path().name for card in dialog._cards}
    assert "valid.json" in loaded
    assert "invalid.json" not in loaded


def test_selected_data_returns_none_for_non_dict_payload(qtbot, monkeypatch, tmp_path):
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    invalid_path = encounters_dir / "invalid.json"
    invalid_path.write_text(json.dumps([{"name": "Wrong root type"}]), encoding="utf-8")

    monkeypatch.setattr(EncounterSelectorDialog, "_encounters_dir", lambda self: encounters_dir)

    dialog = EncounterSelectorDialog()
    qtbot.addWidget(dialog)
    dialog._selected_path = invalid_path

    assert dialog.selected_data() is None


def test_selected_data_returns_dict_payload(qtbot, monkeypatch, tmp_path):
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    valid_path = encounters_dir / "valid.json"
    payload = {"name": "Skeleton Patrol", "monsters": [{"name": "Skeleton", "count": 2}]}
    valid_path.write_text(json.dumps(payload), encoding="utf-8")

    monkeypatch.setattr(EncounterSelectorDialog, "_encounters_dir", lambda self: encounters_dir)

    dialog = EncounterSelectorDialog()
    qtbot.addWidget(dialog)
    dialog._selected_path = valid_path

    assert dialog.selected_data() == payload
