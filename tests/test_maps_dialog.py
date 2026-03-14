import os
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt
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


def _write_png(path: Path, *, width: int = 32, height: int = 32) -> None:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xFF336699)
    assert image.save(str(path), "PNG")


class _WheelDeltaStub:
    def __init__(self, y_value: int) -> None:
        self._y_value = y_value

    def y(self) -> int:
        return self._y_value


class _WheelEventStub:
    def __init__(self, *, delta: int, modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
        self._delta = delta
        self._modifiers = modifiers
        self.accepted = False

    def angleDelta(self) -> _WheelDeltaStub:
        return _WheelDeltaStub(self._delta)

    def modifiers(self) -> Qt.KeyboardModifier:
        return self._modifiers

    def accept(self) -> None:
        self.accepted = True


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
    assert abs(view._zoom - 1.0) < 0.01
    assert view.transform().m11() > 1.0


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


def test_map_view_panel_plain_wheel_zooms_when_ctrl_requirement_is_disabled(qtbot, tmp_path, monkeypatch):
    source = tmp_path / "wheel_zoom.png"
    _write_png(source)

    view = MapViewPanel()
    qtbot.addWidget(view)
    view.resize(600, 400)
    view.show()
    view.load_image(str(source))

    baseline_zoom = float(view._zoom)
    event = _WheelEventStub(delta=120)
    monkeypatch.setattr("maps_applet.is_ctrl_mouse_wheel_zoom_enabled", lambda: False)

    view.wheelEvent(event)

    assert event.accepted is True
    assert view._zoom > baseline_zoom


def test_maps_widget_restores_map_view_state_and_reset_view(qtbot, monkeypatch, tmp_path):
    maps_dir = tmp_path / "maps"
    images_dir = maps_dir / "images"
    thumbs_dir = images_dir / ".thumbs"
    images_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    first = images_dir / "first.png"
    second = images_dir / "second.png"
    _write_png(first, width=96, height=96)
    _write_png(second, width=420, height=180)

    monkeypatch.setattr("maps_applet.load_navigation_data", lambda: [])
    monkeypatch.setattr("maps_applet.maps_storage_dir", lambda: maps_dir)
    monkeypatch.setattr("maps_applet.maps_images_dir", lambda: images_dir)
    monkeypatch.setattr("maps_applet.maps_thumbs_dir", lambda: thumbs_dir)

    widget = MapsWidget()
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()

    first_entry = MapAsset(id="map-a", name="Alpha", image_path=str(first))
    second_entry = MapAsset(id="map-b", name="Beta", image_path=str(second))
    widget._manager.entries = [first_entry, second_entry]
    widget._apply_filters()
    widget._load_map_preview(first_entry)

    panel = widget._preview_panel
    assert abs(panel._zoom - 1.0) < 0.01
    assert widget._zoom_label.text() == "100%"
    saved_center = panel._pixmap_item.boundingRect().center() + QPointF(8.0, 6.0)
    panel.set_zoom(2.0)
    panel.centerOn(saved_center)
    first_effective_zoom = panel.transform().m11()

    widget._map_list.setCurrentRow(1)

    switched_center = panel.mapToScene(panel.viewport().rect().center())
    expected_second_center = panel._pixmap_item.boundingRect().center()
    assert abs(panel._zoom - 1.0) < 0.01
    assert widget._zoom_label.text() == "100%"
    assert abs(panel.transform().m11() - first_effective_zoom) > 0.5
    assert abs(switched_center.x() - expected_second_center.x()) < 1.25
    assert abs(switched_center.y() - expected_second_center.y()) < 1.25

    widget._map_list.setCurrentRow(0)

    restored_center = panel.mapToScene(panel.viewport().rect().center())
    assert abs(panel._zoom - 2.0) < 0.01
    assert abs(restored_center.x() - saved_center.x()) < 1.25
    assert abs(restored_center.y() - saved_center.y()) < 1.25

    qtbot.mouseClick(widget._reset_view_button, Qt.MouseButton.LeftButton)

    expected_center = panel._pixmap_item.boundingRect().center()
    reset_center = panel.mapToScene(panel.viewport().rect().center())
    assert abs(panel._zoom - 1.0) < 0.01
    assert abs(reset_center.x() - expected_center.x()) < 1.25
    assert abs(reset_center.y() - expected_center.y()) < 1.25


def test_maps_widget_preserves_fit_scale_for_untouched_maps_across_switches(
    qtbot, monkeypatch, tmp_path
):
    maps_dir = tmp_path / "maps"
    images_dir = maps_dir / "images"
    thumbs_dir = images_dir / ".thumbs"
    images_dir.mkdir(parents=True, exist_ok=True)
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    large = images_dir / "large.png"
    small = images_dir / "small.png"
    _write_png(large, width=640, height=320)
    _write_png(small, width=96, height=96)

    monkeypatch.setattr("maps_applet.load_navigation_data", lambda: [])
    monkeypatch.setattr("maps_applet.maps_storage_dir", lambda: maps_dir)
    monkeypatch.setattr("maps_applet.maps_images_dir", lambda: images_dir)
    monkeypatch.setattr("maps_applet.maps_thumbs_dir", lambda: thumbs_dir)

    widget = MapsWidget()
    qtbot.addWidget(widget)
    widget.resize(1200, 800)
    widget.show()

    large_entry = MapAsset(id="map-large", name="Large", image_path=str(large))
    small_entry = MapAsset(id="map-small", name="Small", image_path=str(small))
    widget._manager.entries = [large_entry, small_entry]
    widget._apply_filters()

    panel = widget._preview_panel
    initial_large_zoom = panel.transform().m11()
    initial_large_center = panel.mapToScene(panel.viewport().rect().center())

    widget._map_list.setCurrentRow(1)
    small_zoom = panel.transform().m11()

    widget._map_list.setCurrentRow(0)
    restored_large_zoom = panel.transform().m11()
    restored_large_center = panel.mapToScene(panel.viewport().rect().center())
    expected_large_center = panel._pixmap_item.boundingRect().center()

    debug_root = Path(ROOT) / "debug"
    debug_root.mkdir(parents=True, exist_ok=True)
    debug_log = debug_root / "map_view_untouched_restore.log"
    debug_log.write_text(
        "\n".join(
            [
                f"initial_large_zoom={initial_large_zoom:.6f}",
                f"small_zoom={small_zoom:.6f}",
                f"restored_large_zoom={restored_large_zoom:.6f}",
                (
                    "initial_large_center="
                    f"({float(initial_large_center.x()):.6f},{float(initial_large_center.y()):.6f})"
                ),
                (
                    "restored_large_center="
                    f"({float(restored_large_center.x()):.6f},{float(restored_large_center.y()):.6f})"
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    assert small_zoom > initial_large_zoom
    assert abs(restored_large_zoom - initial_large_zoom) < 0.01
    assert abs(restored_large_center.x() - expected_large_center.x()) < 1.25
    assert abs(restored_large_center.y() - expected_large_center.y()) < 1.25
