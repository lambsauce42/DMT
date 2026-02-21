import os
import sys
from pathlib import Path

from PyQt6.QtGui import QImage

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from maps_applet import (
    MapAsset,
    MapDialog,
    MapsWidget,
    map_image_trash_path,
    map_thumb_trash_path,
)


def _write_png(path: Path) -> None:
    image = QImage(32, 32, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(path), "PNG")


def test_map_dialog_new_entry_accepts_and_persists_copy(qtbot, monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    _write_png(source)

    images_dir = tmp_path / "images"
    thumbs_dir = images_dir / ".thumbs"
    monkeypatch.setattr("maps_applet.maps_images_dir", lambda: images_dir)
    monkeypatch.setattr("maps_applet.maps_thumbs_dir", lambda: thumbs_dir)

    dialog = MapDialog(world_data=[])
    qtbot.addWidget(dialog)
    dialog._name_input.setText("Forest Entrance")
    dialog._source_image_path = str(source)
    dialog._source_label.setText(str(source))

    dialog._on_accept()

    created = dialog.entry()
    assert created is not None
    assert created.name == "Forest Entrance"
    assert Path(created.image_path).exists()
    assert created.image_path != str(source)
    assert created.thumbnail_path is not None
    assert Path(created.thumbnail_path).exists()


def test_map_dialog_edit_entry_keeps_id_and_updates_name(qtbot, monkeypatch, tmp_path):
    existing_image = tmp_path / "existing.png"
    _write_png(existing_image)

    images_dir = tmp_path / "images"
    thumbs_dir = images_dir / ".thumbs"
    monkeypatch.setattr("maps_applet.maps_images_dir", lambda: images_dir)
    monkeypatch.setattr("maps_applet.maps_thumbs_dir", lambda: thumbs_dir)

    entry = MapAsset(
        id="map-existing-id",
        name="Old Name",
        image_path=str(existing_image),
        thumbnail_path=None,
    )
    dialog = MapDialog(world_data=[], entry=entry)
    qtbot.addWidget(dialog)
    dialog._name_input.setText("Edited Name")

    dialog._on_accept()

    updated = dialog.entry()
    assert updated is not None
    assert updated.id == "map-existing-id"
    assert updated.name == "Edited Name"
    assert Path(updated.image_path).exists()


def test_maps_widget_reports_storage_read_errors(qtbot, monkeypatch, tmp_path):
    broken_storage = tmp_path / "maps.json"
    broken_storage.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("maps_applet.maps_storage_path", lambda: broken_storage)

    widget = MapsWidget()
    qtbot.addWidget(widget)

    assert widget._manager.entries == []
    assert "Unable to read maps storage" in widget._load_entries_error


def test_map_trash_paths_use_stable_id_not_name():
    first = MapAsset(id="map-001", name="Shared Name", image_path="first.png")
    second = MapAsset(id="map-002", name="Shared Name", image_path="second.png")

    assert map_image_trash_path(first, first.image_path) != map_image_trash_path(second, second.image_path)
    assert map_thumb_trash_path(first) != map_thumb_trash_path(second)
