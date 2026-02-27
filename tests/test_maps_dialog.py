import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QImage

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from maps_applet import (
    MapAsset,
    MapDialog,
    MapViewPanel,
    MapsWidget,
    map_image_trash_path,
    map_thumb_trash_path,
)
from dmt_package import write_dmt_package


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


def test_maps_widget_ignores_invalid_map_packages(qtbot, monkeypatch, tmp_path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    (maps_dir / "broken.dmtmap").write_text("not a package", encoding="utf-8")
    monkeypatch.setattr("maps_applet.maps_storage_dir", lambda: maps_dir)
    monkeypatch.setattr("maps_applet.maps_images_dir", lambda: maps_dir / "images")
    monkeypatch.setattr("maps_applet.maps_thumbs_dir", lambda: maps_dir / "images" / ".thumbs")

    widget = MapsWidget()
    qtbot.addWidget(widget)

    assert widget._manager.entries == []
    assert widget._load_entries_error == ""


def test_maps_widget_save_preserves_unknown_format_packages(qtbot, monkeypatch, tmp_path):
    maps_dir = tmp_path / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    unknown_file = maps_dir / "future_format.dmtmap"
    write_dmt_package(
        unknown_file,
        info={
            "format": "dmtmap.v999",
            "object_type": "map",
            "object_id": "future",
            "payload": {"id": "future", "name": "Future Map", "image_path": "missing.png"},
        },
    )
    monkeypatch.setattr("maps_applet.maps_storage_dir", lambda: maps_dir)
    monkeypatch.setattr("maps_applet.maps_images_dir", lambda: maps_dir / "images")
    monkeypatch.setattr("maps_applet.maps_thumbs_dir", lambda: maps_dir / "images" / ".thumbs")

    widget = MapsWidget()
    qtbot.addWidget(widget)
    widget._save_entries()

    assert unknown_file.exists()


def test_map_trash_paths_use_stable_id_not_name():
    first = MapAsset(id="map-001", name="Shared Name", image_path="first.png")
    second = MapAsset(id="map-002", name="Shared Name", image_path="second.png")

    assert map_image_trash_path(first, first.image_path) != map_image_trash_path(second, second.image_path)
    assert map_thumb_trash_path(first) != map_thumb_trash_path(second)


def test_map_view_panel_uses_infinite_padding_and_no_scrollbars(qtbot, tmp_path):
    source = tmp_path / "pad.png"
    _write_png(source)

    view = MapViewPanel()
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    view.load_image(str(source))

    assert view.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert view.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    rect = view.sceneRect()
    pixmap_rect = view._pixmap_item.boundingRect()
    assert int(rect.width()) == int(pixmap_rect.width()) + 100000
    assert int(rect.height()) == int(pixmap_rect.height()) + 100000


def test_map_view_panel_pan_is_stable_without_vertical_jitter(qtbot, tmp_path):
    source = tmp_path / "pan_stable.png"
    _write_png(source)

    view = MapViewPanel()
    qtbot.addWidget(view)
    view.resize(800, 600)
    view.show()
    view.load_image(str(source))
    view.set_zoom(3.0)

    viewport = view.viewport()
    start = viewport.rect().center()
    samples: list[tuple[int, float, float]] = []

    QTest.mousePress(
        viewport,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        start,
    )
    for dx in range(0, 101, 5):
        pos = start + QPoint(dx, 0)
        QTest.mouseMove(viewport, pos)
        center = view.mapToScene(viewport.rect().center())
        samples.append((dx, float(center.x()), float(center.y())))
    QTest.mouseRelease(
        viewport,
        Qt.MouseButton.MiddleButton,
        Qt.KeyboardModifier.NoModifier,
        start + QPoint(100, 0),
    )

    debug_root = Path(ROOT) / "debug"
    debug_root.mkdir(parents=True, exist_ok=True)
    debug_log = debug_root / "map_view_pan_stability.log"
    lines = [f"dx={dx} center=({cx:.6f},{cy:.6f})" for dx, cx, cy in samples]
    debug_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    y_values = [entry[2] for entry in samples]
    y_jitter = max(y_values) - min(y_values)
    assert y_jitter < 0.05
