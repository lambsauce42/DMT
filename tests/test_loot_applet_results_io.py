import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DMT_TEST_MODE", "1")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

import loot_applet


class TestLootAppletResultsIO:
    @classmethod
    def setup_class(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _item(self, item_id: str, title: str, path: str) -> loot_applet.LootItem:
        return loot_applet.LootItem(
            item_id=item_id,
            title=title,
            rarity="rare",
            category_label="Equipment",
            categories={"equipment"},
            level=5,
            tags=set(),
            icon_path=None,
            path=path,
        )

    def test_save_generated_results_uses_dmtloot_and_persists_state(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        widget = loot_applet.LootAppletWidget()
        try:
            item = self._item("sword_1", "Longsword", str(tmp_path / "longsword.json"))
            widget._seed_spin.setValue(31415)
            widget._results = [
                loot_applet.LootResultItem(
                    result_id=1,
                    item=item,
                    locked=True,
                    guaranteed=False,
                )
            ]

            target_base = tmp_path / "saved_roll"
            monkeypatch.setattr(
                "loot_applet.QFileDialog.getSaveFileName",
                lambda *args, **kwargs: (str(target_base), "DMT Loot Results"),
            )
            info_messages: list[tuple] = []
            monkeypatch.setattr(
                "loot_applet.QMessageBox.information",
                lambda *args, **kwargs: info_messages.append(args),
            )

            widget._save_generated_results()

            saved_path = target_base.with_suffix(loot_applet.LOOT_RESULTS_EXTENSION)
            assert saved_path.exists()
            payload = json.loads(saved_path.read_text(encoding="utf-8"))
            assert payload["version"] == 1
            assert payload["seed"] == 31415
            assert len(payload["results"]) == 1
            row = payload["results"][0]
            assert row["item_id"] == "sword_1"
            assert row["locked"] is True
            assert row["guaranteed"] is False
            assert info_messages
        finally:
            widget.close()

    def test_load_generated_results_restores_seed_flags_and_skips_missing(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        widget = loot_applet.LootAppletWidget()
        try:
            known_path = str(tmp_path / "items" / "known.json")
            known_item = self._item("known_1", "Known Item", known_path)

            def _fake_load_item_library() -> None:
                widget._item_library = [known_item]
                widget._item_by_id = {known_item.item_id: known_item}

            widget._load_item_library = _fake_load_item_library

            source = tmp_path / f"input{loot_applet.LOOT_RESULTS_EXTENSION}"
            source.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "seed": 777,
                        "created_at": "2026-02-09T00:00:00+00:00",
                        "results": [
                            {
                                "item_id": "known_1",
                                "path": known_path,
                                "title": "Known Item",
                                "locked": True,
                                "guaranteed": True,
                            },
                            {
                                "item_id": "missing_1",
                                "path": str(tmp_path / "items" / "missing.json"),
                                "title": "Missing Item",
                                "locked": False,
                                "guaranteed": False,
                            },
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            monkeypatch.setattr(
                "loot_applet.QFileDialog.getOpenFileName",
                lambda *args, **kwargs: (str(source), "DMT Loot Results"),
            )
            warning_messages: list[tuple] = []
            info_messages: list[tuple] = []
            monkeypatch.setattr(
                "loot_applet.QMessageBox.warning",
                lambda *args, **kwargs: warning_messages.append(args),
            )
            monkeypatch.setattr(
                "loot_applet.QMessageBox.information",
                lambda *args, **kwargs: info_messages.append(args),
            )

            widget._load_generated_results()

            assert widget._seed_spin.value() == 777
            assert len(widget._results) == 1
            loaded = widget._results[0]
            assert loaded.item.item_id == "known_1"
            assert loaded.locked is True
            assert loaded.guaranteed is True
            assert widget._next_result_id >= 2
            assert warning_messages
            assert not info_messages
        finally:
            widget.close()
