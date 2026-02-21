import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

from app import APPLET_DEFINITIONS, MainLauncherWindow


class HomeTabBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_single_click_opens_in_background_and_focuses_existing(self) -> None:
        window = MainLauncherWindow()
        applet = next(a for a in APPLET_DEFINITIONS if a["key"] == "dungeon_creator")

        window.open_applet(applet, focus_if_new=False)
        self.assertEqual(window.tabs.currentIndex(), 0)

        widget = window._tab_by_key["dungeon_creator"]
        tab_index = window.tabs.indexOf(widget)
        self.assertNotEqual(tab_index, -1)

        window.open_applet(applet, focus_if_new=False)
        self.assertEqual(window.tabs.currentIndex(), tab_index)
        window.close()

    def test_world_selector_opens_home_dropdown(self) -> None:
        window = MainLauncherWindow()
        applet = next(a for a in APPLET_DEFINITIONS if a["key"] == "world_selector")

        window.open_applet(applet, focus_if_new=False)
        self.assertEqual(window.tabs.currentIndex(), 0)
        self.assertNotIn("world_selector", window._tab_by_key)
        # Verify the navigation tree exists  
        self.assertTrue(hasattr(window._home, "_compact_nav_tree"))
        window.close()

    def test_applets_panel_expands_with_vertical_resize(self) -> None:
        window = MainLauncherWindow()
        window.resize(1400, 900)
        window.show()
        self._app.processEvents()

        home = window._home
        applets_panel = home._applets_panel
        main_content = applets_panel.parentWidget()

        self.assertIsNotNone(main_content)
        initial_panel_height = applets_panel.height()
        initial_content_height = main_content.height()
        self.assertGreaterEqual(initial_panel_height, initial_content_height - 2)

        window.resize(1400, 1400)
        self._app.processEvents()

        self.assertGreater(applets_panel.height(), initial_panel_height)
        self.assertGreater(main_content.height(), initial_content_height)
        self.assertGreaterEqual(applets_panel.height(), main_content.height() - 2)
        window.close()

    def test_applet_grid_resets_stale_row_stretch(self) -> None:
        window = MainLauncherWindow()
        window.show()
        self._app.processEvents()

        home = window._home
        home._layout_applets(1)
        home._layout_applets(2)

        for row in range(4, home._grid_layout.rowCount()):
            self.assertEqual(home._grid_layout.rowStretch(row), 0)
        window.close()

    def test_home_card_icon_and_frame_scale_with_resize(self) -> None:
        window = MainLauncherWindow()
        window.resize(1200, 850)
        window.show()
        self._app.processEvents()

        card = window._home._applet_cards[0]
        icon_label = card._icon_label
        initial_box = icon_label.width()
        initial_pixmap = icon_label.pixmap()
        self.assertIsNotNone(initial_pixmap)

        window.resize(1400, 1300)
        self._app.processEvents()

        grown_box = icon_label.width()
        grown_pixmap = icon_label.pixmap()
        self.assertIsNotNone(grown_pixmap)
        self.assertGreater(grown_box, initial_box)

        pixmap_width = int(round(grown_pixmap.deviceIndependentSize().width()))
        total_padding = grown_box - pixmap_width
        self.assertLessEqual(total_padding, max(14, int(grown_box * 0.2)))
        window.close()


if __name__ == "__main__":
    unittest.main()
