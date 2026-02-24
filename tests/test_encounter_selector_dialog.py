import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dmt_package import write_dmt_package
from ui.encounter_selector_dialog import EncounterSelectorDialog

ENCOUNTER_EXT = ".dmtencounter"
ENCOUNTER_FORMAT = "dmtencounter.v1"


def test_selector_skips_non_dict_payload_files(qtbot, monkeypatch, tmp_path):
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    valid_path = encounters_dir / f"valid{ENCOUNTER_EXT}"
    invalid_path = encounters_dir / f"invalid{ENCOUNTER_EXT}"
    write_dmt_package(
        valid_path,
        info={"format": ENCOUNTER_FORMAT, "name": "Goblin Ambush", "monsters": []},
    )
    invalid_path.write_text("not a dmt package", encoding="utf-8")

    monkeypatch.setattr(EncounterSelectorDialog, "_encounters_dir", lambda self: encounters_dir)

    dialog = EncounterSelectorDialog()
    qtbot.addWidget(dialog)

    loaded = {card.path().name for card in dialog._cards}
    assert f"valid{ENCOUNTER_EXT}" in loaded
    assert f"invalid{ENCOUNTER_EXT}" not in loaded


def test_selected_data_returns_none_for_non_dict_payload(qtbot, monkeypatch, tmp_path):
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    invalid_path = encounters_dir / f"invalid{ENCOUNTER_EXT}"
    invalid_path.write_text("not a dmt package", encoding="utf-8")

    monkeypatch.setattr(EncounterSelectorDialog, "_encounters_dir", lambda self: encounters_dir)

    dialog = EncounterSelectorDialog()
    qtbot.addWidget(dialog)
    dialog._selected_path = invalid_path

    assert dialog.selected_data() is None


def test_selected_data_returns_dict_payload(qtbot, monkeypatch, tmp_path):
    encounters_dir = tmp_path / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    valid_path = encounters_dir / f"valid{ENCOUNTER_EXT}"
    payload = {
        "format": ENCOUNTER_FORMAT,
        "name": "Skeleton Patrol",
        "monsters": [{"name": "Skeleton", "count": 2}],
    }
    write_dmt_package(valid_path, info=payload)

    monkeypatch.setattr(EncounterSelectorDialog, "_encounters_dir", lambda self: encounters_dir)

    dialog = EncounterSelectorDialog()
    qtbot.addWidget(dialog)
    dialog._selected_path = valid_path

    assert dialog.selected_data() == payload
