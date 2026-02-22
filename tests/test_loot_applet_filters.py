import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DMT_TEST_MODE", "1")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

import loot_applet


class LootAppletFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def _build_item(self, item_id: str, title: str, categories) -> loot_applet.LootItem:
        return loot_applet.LootItem(
            item_id=item_id,
            title=title,
            rarity="common",
            category_label=None,
            categories=set(categories),
            level=5,
            tags=set(),
            icon_path=None,
            path=None,
        )

    def test_category_filter_requires_all_selected_categories(self) -> None:
        widget = loot_applet.LootAppletWidget()
        try:
            items = [
                self._build_item("a", "All", {"equipment", "magic"}),
                self._build_item("b", "Equip", {"equipment"}),
                self._build_item("c", "Magic", {"magic"}),
                self._build_item("d", "Other", {"valuables"}),
            ]
            widget._item_library = items
            widget._category_labels = {
                "equipment": "Equipment",
                "magic": "Magic",
                "valuables": "Valuables",
            }
            widget._rebuild_category_filters({"equipment", "magic"})
            widget._group_level_spin.setValue(5)

            filtered = widget._apply_filters()

            self.assertEqual({item.item_id for item in filtered}, {"a"})
        finally:
            widget.close()


if __name__ == "__main__":
    unittest.main()
