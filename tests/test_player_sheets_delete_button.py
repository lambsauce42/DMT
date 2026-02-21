import json
import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from PyQt6.QtWidgets import QApplication

import player_sheets
from player_sheets import PlayerSheetsWidget


class PlayerSheetsDeleteButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_delete_button_moves_pdf_to_trash_and_removes_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trashed_payloads = []

            def _fake_move_to_trash(entry_type, payload, parent=None, path=None):
                trashed_payloads.append((entry_type, payload))
                return payload

            with patch("player_sheets.default_sheet_save_dir", return_value=temp_dir), patch(
                "player_sheets.move_to_trash", side_effect=_fake_move_to_trash
            ), patch("player_sheets.PDFIUM_VIEW_AVAILABLE", False):
                entry = player_sheets.PlayerSheetEntry(
                    name="Delete Me",
                    pdf_path="",
                    world=None,
                    campaign=None,
                    group=None,
                    tags=[],
                    inventory=[],
                )
                sheet_id = player_sheets.sheet_id_for_entry(entry)
                storage_path = player_sheets.character_sheet_pdf_path(sheet_id)
                trash_path = player_sheets.character_sheet_trash_path(sheet_id)
                storage_path.parent.mkdir(parents=True, exist_ok=True)
                storage_path.write_text("pdf")
                entry.pdf_path = str(storage_path)

                storage_json = player_sheets.player_sheets_storage_path()
                storage_json.parent.mkdir(parents=True, exist_ok=True)
                with open(storage_json, "w", encoding="utf-8") as handle:
                    json.dump([player_sheets.entry_to_dict(entry)], handle)

                widget = PlayerSheetsWidget()
                widget._sheet_list.setCurrentRow(0)
                QApplication.processEvents()
                widget._delete_button.click()
                QApplication.processEvents()
                widget.close()

                self.assertFalse(storage_path.exists())
                self.assertTrue(trash_path.exists())
                self.assertEqual(len(trashed_payloads), 1)
                self.assertEqual(trashed_payloads[0][0], "character_sheet")

                with open(storage_json, "r", encoding="utf-8") as handle:
                    remaining = json.load(handle)
                self.assertEqual(remaining, [])

    def test_character_list_name_line_uses_bold_delegate_font(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("player_sheets.default_sheet_save_dir", return_value=temp_dir), patch(
                "player_sheets.PDFIUM_VIEW_AVAILABLE", False
            ):
                widget = PlayerSheetsWidget()
                delegate = widget._sheet_list.itemDelegate()
                self.assertIsInstance(delegate, player_sheets.CharacterSheetListDelegate)
                base_font = widget._sheet_list.font()
                self.assertTrue(delegate._font_for_line(base_font, 0).bold())
                self.assertFalse(delegate._font_for_line(base_font, 1).bold())
                widget.close()

    def test_equipment_slot_placeholder_background_is_gray_and_faint(self) -> None:
        pixmap = player_sheets._equipment_slot_background_pixmap(72)
        self.assertFalse(pixmap.isNull())
        self.assertEqual(pixmap.width(), 72)
        self.assertEqual(pixmap.height(), 72)

        image = pixmap.toImage()
        sample = None
        grayscale_values = set()
        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                if color.alpha() > 0:
                    grayscale_values.add(color.red())
                    sample = color
                    if len(grayscale_values) > 8:
                        break
            if len(grayscale_values) > 8:
                break

        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertLess(abs(sample.red() - sample.green()), 6)
        self.assertLess(abs(sample.red() - sample.blue()), 6)
        self.assertLess(sample.alpha(), 180)
        self.assertGreater(len(grayscale_values), 1)

    def test_weapon_background_remains_weapon_themed(self) -> None:
        weapon_bg = player_sheets._equipment_slot_background_pixmap(96, slot_id="weapon_1")
        misc_bg = player_sheets._equipment_slot_background_pixmap(96, slot_id="misc_1")
        self.assertFalse(weapon_bg.isNull())
        self.assertFalse(misc_bg.isNull())
        self.assertEqual(weapon_bg.size(), misc_bg.size())

        weapon_image = weapon_bg.toImage()
        misc_image = misc_bg.toImage()
        self.assertEqual(weapon_image.size(), misc_image.size())
        different_pixel_found = False
        for y in range(weapon_image.height()):
            for x in range(weapon_image.width()):
                if weapon_image.pixelColor(x, y) != misc_image.pixelColor(x, y):
                    different_pixel_found = True
                    break
            if different_pixel_found:
                break
        self.assertTrue(different_pixel_found)

    def test_equipment_background_paths_use_shield_trinket_and_misc_hexagon_assets(self) -> None:
        shield_path = player_sheets._resolve_equipment_slot_background_path("weapon_4")
        weapon_path = player_sheets._resolve_equipment_slot_background_path("weapon_1")
        trinket_path = player_sheets._resolve_equipment_slot_background_path("misc_1")
        trinket_path_2 = player_sheets._resolve_equipment_slot_background_path("misc_2")
        misc_path = player_sheets._resolve_equipment_slot_background_path("misc_13")

        self.assertEqual(shield_path.name, "shield.png")
        self.assertEqual(weapon_path.name, "sword_short.png")
        self.assertEqual(trinket_path.name, "trinket.png")
        self.assertEqual(trinket_path_2.name, "trinket.png")
        self.assertEqual(misc_path.name, "misc_hexagon.svg")
        self.assertNotEqual(misc_path.name, "trinket.png")
        self.assertNotEqual(trinket_path.name, "miscellaneous_charm.png")

    def test_inventory_icon_composition_keeps_even_inner_gaps(self) -> None:
        if not player_sheets.RENDERER_AVAILABLE:
            self.skipTest("Renderer dependencies unavailable")

        with tempfile.TemporaryDirectory() as temp_dir:
            icon_path = os.path.join(temp_dir, "opaque_square.png")
            player_sheets.Image.new("RGBA", (101, 101), (255, 255, 255, 255)).save(icon_path)

            with_icon = player_sheets._inventory_icon_pixmap(
                player_sheets.LootItem(
                    item_id="with-icon",
                    title="With Icon",
                    rarity="rare",
                    category_label="Equipment",
                    categories={"equipment"},
                    level=1,
                    tags=set(),
                    icon_path=icon_path,
                    path=None,
                )
            )
            without_icon = player_sheets._inventory_icon_pixmap(
                player_sheets.LootItem(
                    item_id="without-icon",
                    title="Without Icon",
                    rarity="rare",
                    category_label="Equipment",
                    categories={"equipment"},
                    level=1,
                    tags=set(),
                    icon_path=None,
                    path=None,
                )
            )

            with_image = with_icon.toImage()
            without_image = without_icon.toImage()
            changed: list[tuple[int, int]] = []
            for y in range(with_image.height()):
                for x in range(with_image.width()):
                    if with_image.pixelColor(x, y) != without_image.pixelColor(x, y):
                        changed.append((x, y))

            self.assertTrue(changed)
            xs = [point[0] for point in changed]
            ys = [point[1] for point in changed]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)

            frame = player_sheets.INVENTORY_ICON_FRAME
            icon_box = player_sheets.INVENTORY_ICON_SIZE - (frame * 2)
            inner_right = frame + icon_box - 1
            inner_bottom = frame + icon_box - 1
            left_gap = x0 - frame
            right_gap = inner_right - x1
            top_gap = y0 - frame
            bottom_gap = inner_bottom - y1

            self.assertEqual(left_gap, right_gap)
            self.assertEqual(top_gap, bottom_gap)

    def test_dpr_fitted_pixel_size_preserves_logical_size(self) -> None:
        pixel_size, effective_dpr = player_sheets._dpr_fitted_pixel_size(57, 1.25)
        self.assertEqual(pixel_size, 57)
        self.assertEqual(effective_dpr, 1.0)
        self.assertAlmostEqual(pixel_size / effective_dpr, 57.0, places=6)

        pixel_size_int, effective_dpr_int = player_sheets._dpr_fitted_pixel_size(57, 2.0)
        self.assertEqual(pixel_size_int, 114)
        self.assertEqual(effective_dpr_int, 2.0)

    def test_equipment_background_fractional_dpr_matches_requested_logical_size(self) -> None:
        pixmap = player_sheets._equipment_slot_background_pixmap(
            57, dpr=1.25, slot_id="weapon_1"
        )
        self.assertFalse(pixmap.isNull())
        logical = pixmap.deviceIndependentSize()
        self.assertAlmostEqual(logical.width(), 57.0, places=6)
        self.assertAlmostEqual(logical.height(), 57.0, places=6)
        self.assertEqual(pixmap.devicePixelRatio(), 1.0)

    def test_trim_alpha_bbox_removes_transparent_padding(self) -> None:
        if not player_sheets.RENDERER_AVAILABLE:
            self.skipTest("Renderer dependencies unavailable")
        image = player_sheets.Image.new("RGBA", (12, 12), (0, 0, 0, 0))
        for y in range(3, 9):
            for x in range(4, 10):
                image.putpixel((x, y), (255, 255, 255, 255))
        trimmed = player_sheets._trim_alpha_bbox(image, threshold=8)
        self.assertEqual(trimmed.size, (6, 6))

    def test_equipment_item_icon_pixmap_is_centered_in_canvas(self) -> None:
        if not player_sheets.RENDERER_AVAILABLE:
            self.skipTest("Renderer dependencies unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            path = os.path.join(temp_dir, "offcenter.png")
            icon = player_sheets.Image.new("RGBA", (30, 30), (0, 0, 0, 0))
            for y in range(4, 24):
                for x in range(0, 12):
                    icon.putpixel((x, y), (255, 255, 255, 255))
            icon.save(path)
            loot_item = player_sheets.LootItem(
                item_id="offcenter-test",
                title="Offcenter",
                rarity="rare",
                category_label="Equipment",
                categories={"equipment"},
                level=1,
                tags=set(),
                icon_path=path,
                path=None,
            )
            pixmap = player_sheets._equipment_item_icon_pixmap(loot_item)
            image = pixmap.toImage()
            points: list[tuple[int, int]] = []
            for y in range(image.height()):
                for x in range(image.width()):
                    if image.pixelColor(x, y).alpha() > 0:
                        points.append((x, y))
            self.assertTrue(points)
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            left_gap = x0
            right_gap = (image.width() - 1) - x1
            top_gap = y0
            bottom_gap = (image.height() - 1) - y1
            self.assertLessEqual(abs(left_gap - right_gap), 1)
            self.assertLessEqual(abs(top_gap - bottom_gap), 1)

    def test_equipment_slot_canvas_pixmap_is_consistent_across_slots(self) -> None:
        if not player_sheets.RENDERER_AVAILABLE:
            self.skipTest("Renderer dependencies unavailable")
        with tempfile.TemporaryDirectory() as temp_dir:
            icon_path = os.path.join(temp_dir, "slot_consistency.png")
            icon = player_sheets.Image.new("RGBA", (40, 40), (0, 0, 0, 0))
            for y in range(6, 34):
                for x in range(0, 16):
                    icon.putpixel((x, y), (255, 255, 255, 255))
            icon.save(icon_path)
            loot_item = player_sheets.LootItem(
                item_id="slot-consistency-test",
                title="Slot Consistency",
                rarity="rare",
                category_label="Equipment",
                categories={"equipment"},
                level=1,
                tags=set(),
                icon_path=icon_path,
                path=None,
            )

            with patch("player_sheets._load_loot_item_library", return_value=([], {})), patch(
                "player_sheets.PDFIUM_VIEW_AVAILABLE", False
            ):
                widget = PlayerSheetsWidget()
                widget._inventory_item_by_id[loot_item.item_id] = loot_item
                widget._inventory_item_library.append(loot_item)
                entry = player_sheets.PlayerSheetEntry(name="Test", pdf_path="")
                for slot_id in player_sheets.EQUIPMENT_SLOT_IDS:
                    entry.equipment[slot_id] = loot_item.item_id
                widget.resize(1200, 860)
                widget.show()
                QApplication.processEvents()
                widget._set_inventory(entry)
                widget._set_inventory_view("equipment")
                QApplication.processEvents()

                hashes: set[str] = set()
                for slot_id in ("weapon_1", "weapon_2", "weapon_3", "head", "back", "misc_4"):
                    slot = widget._equipment_slot_widgets[slot_id]
                    pixmap = slot._slot_canvas.pixmap()
                    self.assertIsNotNone(pixmap)
                    assert pixmap is not None
                    logical = pixmap.deviceIndependentSize()
                    self.assertAlmostEqual(logical.width(), float(slot._slot_canvas.width()), places=6)
                    self.assertAlmostEqual(logical.height(), float(slot._slot_canvas.height()), places=6)

                    image = pixmap.toImage()
                    ptr = image.bits()
                    ptr.setsize(image.sizeInBytes())
                    hashes.add(hashlib.sha256(bytes(ptr)).hexdigest())

                self.assertEqual(len(hashes), 1)
                widget.close()

    def test_equipment_figure_preserves_source_aspect_ratio(self) -> None:
        with patch("player_sheets._load_loot_item_library", return_value=([], {})), patch(
            "player_sheets.PDFIUM_VIEW_AVAILABLE", False
        ):
            widget = PlayerSheetsWidget()
            widget.show()
            QApplication.processEvents()

            label = widget._equipment_figure_label
            self.assertIsNotNone(label)
            assert label is not None
            self.assertFalse(label.hasScaledContents())

            source = widget._equipment_figure_source_pixmap
            if source is None or source.isNull() or source.height() <= 0:
                widget.close()
                self.skipTest("Silhouette source unavailable")

            label.setFixedSize(220, 140)
            widget._update_equipment_figure_pixmap()
            QApplication.processEvents()

            rendered = label.pixmap()
            self.assertIsNotNone(rendered)
            assert rendered is not None
            logical = rendered.deviceIndependentSize()
            self.assertGreater(logical.width(), 0)
            self.assertGreater(logical.height(), 0)
            source_ratio = float(source.width()) / float(source.height())
            rendered_ratio = float(logical.width()) / float(logical.height())
            ratio_tolerance = max(1.0 / float(source.height()), 1.0 / float(logical.height()))
            self.assertLessEqual(abs(rendered_ratio - source_ratio), ratio_tolerance)
            self.assertLessEqual(logical.width(), float(label.width()))
            self.assertLessEqual(logical.height(), float(label.height()))
            widget.close()

if __name__ == "__main__":
    unittest.main()
