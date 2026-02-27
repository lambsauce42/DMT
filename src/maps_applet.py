from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
import sys
from pathlib import Path
import shutil
from typing import Iterable, List, Optional

from PySide6.QtCore import Qt, QUrl, QSize, QPoint, QPointF, QRectF, Signal, QTimer
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QToolButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
    QSizePolicy,
    QInputDialog,
)

from dmt_package import list_dmt_package_assets, read_dmt_package_asset, read_dmt_package_info, write_dmt_package
from navigate_widget import load_navigation_data, move_to_trash

ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets", "icons"))
RESET_ICON = os.path.join(ICON_DIR, "reset.svg")
from models import MapAsset
from player_sheets import (
    _combo_optional_value,
    _populate_combo,
    default_sheet_save_dir,
    list_campaigns,
    list_groups,
    list_worlds,
    normalize_tags,
    parse_tag_query,
    resolve_selection,
    sanitize_filename,
)
from unique_ids import generate_probabilistic_unique_id

MAPS_DIR_NAME = "maps"
MAPS_IMAGES_DIR_NAME = "images"
MAPS_THUMBS_DIR_NAME = ".thumbs"
MAP_FILE_EXTENSION = ".dmtmap"
MAP_FILE_FORMAT = "dmtmap.v1"
MAP_THUMB_SIZE = QSize(160, 100)
MAP_THUMB_STORAGE_SCALE = 2
MAP_VIEW_INFINITE_PADDING = 50000


def maps_storage_dir() -> Path:
    return Path(default_sheet_save_dir()) / MAPS_DIR_NAME


def maps_images_dir() -> Path:
    return maps_storage_dir() / MAPS_IMAGES_DIR_NAME


def maps_thumbs_dir() -> Path:
    return maps_images_dir() / MAPS_THUMBS_DIR_NAME


def maps_storage_path() -> Path:
    return maps_storage_dir() / "maps.dmtindex"


def map_file_path(map_id: str) -> Path:
    safe = sanitize_filename(str(map_id or "").strip()) or "map"
    return maps_storage_dir() / f"{safe}{MAP_FILE_EXTENSION}"


def maps_trash_dir() -> Path:
    return Path(default_sheet_save_dir()) / "trash" / MAPS_DIR_NAME


def maps_trash_images_dir() -> Path:
    return maps_trash_dir() / MAPS_IMAGES_DIR_NAME


def maps_trash_thumbs_dir() -> Path:
    return maps_trash_images_dir() / MAPS_THUMBS_DIR_NAME


def map_image_trash_path(entry: MapAsset, image_path: Optional[str] = None) -> Path:
    map_id = map_id_for_entry(entry)
    suffix = Path(image_path).suffix if image_path else ""
    if not suffix:
        suffix = ".png"
    return maps_trash_images_dir() / f"{map_id}{suffix}"


def map_thumb_trash_path(entry: MapAsset) -> Path:
    map_id = map_id_for_entry(entry)
    return maps_trash_thumbs_dir() / f"{map_id}.png"


def map_file_trash_path(entry: MapAsset) -> Path:
    map_id = map_id_for_entry(entry)
    return maps_trash_dir() / f"{map_id}{MAP_FILE_EXTENSION}"


def _move_path_to_trash(
    path_value: Optional[str],
    trash_path: Path,
    trash_root: Path,
) -> Optional[str]:
    if not path_value:
        return None
    current_path = Path(path_value)
    if not current_path.exists():
        return None
    if trash_root in current_path.parents:
        return str(current_path)
    trash_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if trash_path.exists():
            trash_path.unlink()
        shutil.move(str(current_path), str(trash_path))
    except OSError:
        return None
    return str(trash_path)


def move_entry_files_to_trash(entry: MapAsset) -> tuple[Optional[str], Optional[str]]:
    _move_path_to_trash(
        str(map_file_path(map_id_for_entry(entry))),
        map_file_trash_path(entry),
        maps_trash_dir(),
    )
    trashed_image = _move_path_to_trash(
        entry.image_path,
        map_image_trash_path(entry, entry.image_path),
        maps_trash_images_dir(),
    )
    thumb_source = entry.thumbnail_path
    if not thumb_source:
        fallback_thumb = maps_thumbs_dir() / f"{map_id_for_entry(entry)}.png"
        if fallback_thumb.exists():
            thumb_source = str(fallback_thumb)
    trashed_thumb = _move_path_to_trash(
        thumb_source,
        map_thumb_trash_path(entry),
        maps_trash_thumbs_dir(),
    )
    return trashed_image, trashed_thumb


def disintegrate_entry_files(entry: MapAsset) -> None:
    map_id = map_id_for_entry(entry)
    candidates: set[Path] = set()
    candidates.add(map_file_path(map_id))
    candidates.add(map_file_trash_path(entry))
    if entry.image_path:
        candidates.add(Path(entry.image_path))
    if entry.thumbnail_path:
        candidates.add(Path(entry.thumbnail_path))
    candidates.add(maps_thumbs_dir() / f"{map_id}.png")
    candidates.add(map_image_trash_path(entry, entry.image_path))
    candidates.add(map_thumb_trash_path(entry))
    suffix = Path(entry.image_path).suffix if entry.image_path else ""
    if not suffix:
        suffix = ".png"
    candidates.add(maps_images_dir() / f"{map_id}{suffix}")
    for target in candidates:
        try:
            if not target.exists():
                continue
            target.unlink()
        except OSError:
            continue


def map_id_for_entry(entry: MapAsset) -> str:
    raw_id = str(getattr(entry, "id", "") or "").strip()
    if raw_id:
        return sanitize_filename(raw_id)
    return sanitize_filename(entry.name)


def entry_to_dict(entry: MapAsset) -> dict:
    return {
        "id": entry.id,
        "name": entry.name,
        "image_path": entry.image_path,
        "thumbnail_path": entry.thumbnail_path,
        "campaign_id": entry.campaign_id,
        "world": entry.world,
        "campaign": entry.campaign,
        "group": entry.group,
        "tags": list(entry.tags),
        "notes": entry.notes,
        "created_at": entry.created_at,
        "last_modified": entry.last_modified,
    }


def entry_from_dict(payload: dict) -> Optional[MapAsset]:
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "")).strip()
    image_path = str(payload.get("image_path", "")).strip()
    if not name or not image_path:
        return None
    tags = payload.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    return MapAsset(
        id=str(payload.get("id") or sanitize_filename(name)),
        name=name,
        image_path=image_path,
        thumbnail_path=payload.get("thumbnail_path") or None,
        campaign_id=payload.get("campaign_id") or None,
        world=payload.get("world") or None,
        campaign=payload.get("campaign") or None,
        group=payload.get("group") or None,
        tags=normalize_tags([str(tag) for tag in tags if str(tag).strip()]),
        notes=str(payload.get("notes") or "").strip(),
        created_at=str(payload.get("created_at") or "").strip(),
        last_modified=str(payload.get("last_modified") or "").strip(),
    )


@dataclass
class MapFilters:
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    tag_query: str = ""


class MapsManager:
    def __init__(self, entries: Optional[List[MapAsset]] = None) -> None:
        self.entries = list(entries or [])
        self.filters = MapFilters()

    def set_filters(
        self,
        world: Optional[str],
        campaign: Optional[str],
        group: Optional[str],
        tag_query: str,
    ) -> None:
        self.filters = MapFilters(
            world=world,
            campaign=campaign,
            group=group,
            tag_query=tag_query,
        )

    def add_map(self, entry: MapAsset) -> None:
        self.entries.append(entry)

    def filtered_entries(self) -> List[MapAsset]:
        return filter_entries(
            self.entries,
            world=self.filters.world,
            campaign=self.filters.campaign,
            group=self.filters.group,
            tag_query=self.filters.tag_query,
        )


def matches_filters(
    entry: MapAsset,
    world: Optional[str],
    campaign: Optional[str],
    group: Optional[str],
    tag_query: str,
) -> bool:
    if world and entry.world != world:
        return False
    if campaign and entry.campaign != campaign:
        return False
    if group and entry.group != group:
        return False

    required_tags = parse_tag_query(tag_query)
    if required_tags:
        entry_tags = set(entry.tags)
        if not all(tag in entry_tags for tag in required_tags):
            return False

    return True


def filter_entries(
    entries: Iterable[MapAsset],
    world: Optional[str] = None,
    campaign: Optional[str] = None,
    group: Optional[str] = None,
    tag_query: str = "",
) -> List[MapAsset]:
    return [
        entry
        for entry in entries
        if matches_filters(entry, world, campaign, group, tag_query)
    ]


def _unique_image_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 2
    while True:
        candidate = parent / f"{stem}_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _ensure_thumbnail(source_path: str, thumb_path: Path) -> Optional[str]:
    if not source_path or not os.path.exists(source_path):
        return None
    target_size = QSize(
        max(1, MAP_THUMB_SIZE.width() * MAP_THUMB_STORAGE_SCALE),
        max(1, MAP_THUMB_SIZE.height() * MAP_THUMB_STORAGE_SCALE),
    )
    if thumb_path.exists():
        thumb_ok = False
        thumb = QPixmap(str(thumb_path))
        if not thumb.isNull():
            thumb_ok = (
                thumb.width() >= target_size.width()
                and thumb.height() >= target_size.height()
            )
        source_mtime = None
        thumb_mtime = None
        try:
            source_mtime = os.path.getmtime(source_path)
        except OSError:
            source_mtime = None
        try:
            thumb_mtime = os.path.getmtime(thumb_path)
        except OSError:
            thumb_mtime = None
        up_to_date = (
            source_mtime is None
            or (thumb_mtime is not None and thumb_mtime >= source_mtime)
        )
        if thumb_ok and up_to_date:
            return str(thumb_path)
    pixmap = QPixmap(source_path)
    if pixmap.isNull():
        return None
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    scaled = pixmap.scaled(
        target_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    scaled.save(str(thumb_path))
    return str(thumb_path)


class MapDialog(QDialog):
    def __init__(
        self,
        world_data: Optional[list] = None,
        parent: Optional[QWidget] = None,
        entry: Optional[MapAsset] = None,
    ) -> None:
        super().__init__(parent)
        self._world_data = (
            world_data if isinstance(world_data, list) else load_navigation_data()
        )
        self._entry: Optional[MapAsset] = None
        self._original_entry = entry
        self._source_image_path: Optional[str] = None

        self.setWindowTitle("Edit Map" if entry else "New Map")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(8)

        self._name_input = QLineEdit()
        form.addRow("Name", self._name_input)

        source_row = QWidget(self)
        source_layout = QHBoxLayout(source_row)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(6)
        self._source_label = QLabel("No image selected")
        self._source_label.setWordWrap(True)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._choose_image)
        source_layout.addWidget(self._source_label, 1)
        source_layout.addWidget(browse_button)
        form.addRow("PNG Source", source_row)

        self._world_combo = QComboBox()
        self._campaign_combo = QComboBox()
        self._group_combo = QComboBox()

        form.addRow("World", self._world_combo)
        form.addRow("Campaign", self._campaign_combo)
        form.addRow("Group", self._group_combo)

        self._tags_input = QLineEdit()
        self._tags_input.setPlaceholderText("comma, separated, tags")
        form.addRow("Tags", self._tags_input)

        self._notes_input = QLineEdit()
        self._notes_input.setPlaceholderText("Optional notes")
        form.addRow("Notes", self._notes_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        _populate_combo(self._world_combo, list_worlds(self._world_data))
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)
        self._world_combo.currentIndexChanged.connect(self._on_world_changed)
        self._campaign_combo.currentIndexChanged.connect(self._on_campaign_changed)

        if entry:
            self._set_entry(entry)

    def entry(self) -> Optional[MapAsset]:
        return self._entry

    def _set_entry(self, entry: MapAsset) -> None:
        self._name_input.setText(entry.name)
        if entry.image_path:
            self._source_label.setText(entry.image_path)
        if entry.world:
            index = self._world_combo.findText(entry.world)
            if index != -1:
                self._world_combo.setCurrentIndex(index)
        selected_campaign = self._refresh_campaigns(entry.campaign)
        self._refresh_groups(entry.group, campaign=selected_campaign)
        self._tags_input.setText(", ".join(entry.tags))
        self._notes_input.setText(entry.notes)

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Map Image",
            os.path.expanduser("~"),
            "Images (*.png *.jpg *.jpeg *.webp)",
        )
        if not path:
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            QMessageBox.warning(self, "Invalid Image", "Unable to load the image.")
            return
        self._source_image_path = path
        self._source_label.setText(path)

    def _on_world_changed(self) -> None:
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)

    def _on_campaign_changed(self) -> None:
        self._refresh_groups()

    def _refresh_campaigns(self, current_value: Optional[str] = None) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        campaigns = list_campaigns(self._world_data, world)
        if current_value is None:
            current_value = _combo_optional_value(self._campaign_combo)
        selection = resolve_selection(campaigns, current_value)
        _populate_combo(self._campaign_combo, campaigns, selection)
        return selection

    def _refresh_groups(
        self, current_value: Optional[str] = None, campaign: Optional[str] = None
    ) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        if campaign is None:
            campaign = _combo_optional_value(self._campaign_combo)
        groups = list_groups(self._world_data, world, campaign)
        if current_value is None:
            current_value = _combo_optional_value(self._group_combo)
        selection = resolve_selection(groups, current_value)
        _populate_combo(self._group_combo, groups, selection)
        return selection

    def _on_accept(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name", "Enter a map name.")
            return

        source_path = self._source_image_path
        if not source_path and self._original_entry:
            source_path = self._original_entry.image_path

        if not source_path:
            QMessageBox.warning(self, "Missing Image", "Select a PNG for this map.")
            return

        map_id = (
            str(getattr(self._original_entry, "id", "") or "").strip()
            if self._original_entry
            else ""
        )
        if not map_id:
            map_id = generate_probabilistic_unique_id("map")
        map_stem = sanitize_filename(name) or sanitize_filename(map_id)
        image_dir = maps_images_dir()
        image_dir.mkdir(parents=True, exist_ok=True)
        source_suffix = os.path.splitext(source_path)[1] or ".png"
        desired_path = image_dir / f"{map_stem}{source_suffix}"

        final_path = desired_path
        if self._source_image_path:
            final_path = _unique_image_path(desired_path)
            try:
                shutil.copy2(source_path, final_path)
            except OSError:
                QMessageBox.warning(self, "Copy Failed", "Unable to copy the map image.")
                return
        elif self._original_entry:
            existing_path = Path(self._original_entry.image_path)
            if existing_path.exists() and image_dir in existing_path.parents:
                if desired_path != existing_path:
                    final_path = _unique_image_path(desired_path)
                    try:
                        existing_path.rename(final_path)
                    except OSError:
                        final_path = existing_path
            else:
                final_path = existing_path

        thumb_path = maps_thumbs_dir() / f"{sanitize_filename(map_id)}.png"
        resolved_thumb = _ensure_thumbnail(str(final_path), thumb_path)

        now = datetime.now().isoformat(timespec="seconds")
        created_at = self._original_entry.created_at if self._original_entry else now
        self._entry = MapAsset(
            id=map_id,
            name=name,
            image_path=str(final_path),
            thumbnail_path=resolved_thumb,
            campaign_id=None,
            world=_combo_optional_value(self._world_combo),
            campaign=_combo_optional_value(self._campaign_combo),
            group=_combo_optional_value(self._group_combo),
            tags=parse_tag_query(self._tags_input.text()),
            notes=self._notes_input.text().strip(),
            created_at=created_at,
            last_modified=now,
        )
        self.accept()


class MapViewPanel(QGraphicsView):
    zoomChanged = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None, placeholder: str = "No map selected.") -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._placeholder_text = placeholder
        self._placeholder_item = QGraphicsTextItem(self._placeholder_text)
        self._scene.addItem(self._placeholder_item)

        self._zoom = 1.0
        self._panning = False
        self._pan_last_pos: Optional[QPoint] = None
        self._pan_center_scene: Optional[QPointF] = None
        self._auto_fit_active = False

        self._update_placeholder()

    def set_placeholder_text(self, text: str) -> None:
        self._placeholder_text = text
        self._placeholder_item.setPlainText(text)
        self._update_placeholder()

    def load_image(self, path: Optional[str]) -> None:
        if not path or not os.path.exists(path):
            self._pixmap_item.setPixmap(QPixmap())
            self._placeholder_item.setPlainText(self._placeholder_text)
            self._placeholder_item.setVisible(True)
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self._zoom = 1.0
            self.resetTransform()
            self.zoomChanged.emit(100)
            self._update_scene_rect()
            self._center_view()
            return
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self._pixmap_item.setPixmap(QPixmap())
            self._placeholder_item.setPlainText("Unable to load map preview.")
            self._placeholder_item.setVisible(True)
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            self._zoom = 1.0
            self.resetTransform()
            self.zoomChanged.emit(100)
            self._update_scene_rect()
            self._center_view()
            return
        self._pixmap_item.setPixmap(pixmap)
        self._placeholder_item.setVisible(False)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        
        # Enable auto-fit mode for this image
        self._auto_fit_active = True
        self.fit_to_view()
        self._center_view()

    def fit_to_view(self) -> None:
        pixmap = self._pixmap_item.pixmap()
        if pixmap.isNull() or pixmap.width() == 0:
            return
        
        viewport_size = self.viewport().size()
        if viewport_size.width() <= 10:
            viewport_size = self.size()

        if viewport_size.width() <= 10 or viewport_size.height() <= 10:
            return
            
        # Calculate fit factors for both dimensions
        zoom_w = viewport_size.width() / pixmap.width()
        zoom_h = viewport_size.height() / pixmap.height()
        
        # Use the smaller factor to ensure the whole image fits, but don't over-zoom small images
        fit_zoom = min(zoom_w, zoom_h)
        self.set_zoom(min(1.0, fit_zoom))
        self._center_view()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._auto_fit_active:
            self.fit_to_view()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        
        if self._auto_fit_active:
            self.fit_to_view()
            
        self._update_scene_rect()
        if not self._panning:
            self._center_view()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta == 0:
            return super().wheelEvent(event)
        
        # Manual zoom deactivates auto-fit
        self._auto_fit_active = False
        
        factor = 1.15 if delta > 0 else (1 / 1.15)
        self.set_zoom(self._zoom * factor, anchor="mouse")
        event.accept()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_last_pos = QPoint(event.pos())
            self._pan_center_scene = self.mapToScene(self.viewport().rect().center())
            self.centerOn(self._pan_center_scene)
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            
            # Manual pan deactivates auto-fit
            self._auto_fit_active = False
            
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._panning and self._pan_last_pos is not None and self._pan_center_scene is not None:
            current_pos = QPoint(event.pos())
            delta_px = current_pos - self._pan_last_pos
            if delta_px.isNull():
                event.accept()
                return
            inv_zoom = 1.0 / max(self._zoom, 1e-6)
            self._pan_center_scene = QPointF(
                self._pan_center_scene.x() - (float(delta_px.x()) * inv_zoom),
                self._pan_center_scene.y() - (float(delta_px.y()) * inv_zoom),
            )
            self.centerOn(self._pan_center_scene)
            self._pan_last_pos = current_pos
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.MiddleButton and self._panning:
            self._panning = False
            self._pan_last_pos = None
            self._pan_center_scene = None
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def zoom_in(self) -> None:
        self._auto_fit_active = False
        self.set_zoom(self._zoom * 1.15)

    def zoom_out(self) -> None:
        self._auto_fit_active = False
        self.set_zoom(self._zoom / 1.15)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    def set_zoom(self, zoom: float, *, anchor: str = "center") -> None:
        zoom = float(max(0.1, min(6.0, zoom)))
        if abs(zoom - self._zoom) < 1e-9:
            self._update_scene_rect()
            return
        if anchor == "mouse":
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        else:
            self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._zoom = zoom
        self.resetTransform()
        self.scale(self._zoom, self._zoom)
        self.zoomChanged.emit(int(round(self._zoom * 100)))
        self._update_scene_rect()

    def _center_view(self) -> None:
        if not self._pixmap_item.pixmap().isNull():
            self.centerOn(self._pixmap_item)
        else:
            self.centerOn(self._scene.sceneRect().center())

    def _update_scene_rect(self) -> None:
        pixmap = self._pixmap_item.pixmap()
        viewport = self.viewport().size()
        if pixmap.isNull():
            rect = QRectF(
                -max(1, viewport.width()) / 2.0,
                -max(1, viewport.height()) / 2.0,
                max(1, viewport.width()),
                max(1, viewport.height()),
            )
            self._scene.setSceneRect(rect)
            self._update_placeholder()
            return
        rect = self._pixmap_item.boundingRect()
        pad = float(MAP_VIEW_INFINITE_PADDING)
        padded = rect.adjusted(-pad, -pad, pad, pad)
        self._scene.setSceneRect(padded)

    def _update_placeholder(self) -> None:
        if not hasattr(self, "_placeholder_item") or not self._placeholder_item.isVisible():
            return
        rect = self._scene.sceneRect()
        text_rect = self._placeholder_item.boundingRect()
        self._placeholder_item.setPos(
            rect.center().x() - text_rect.width() / 2,
            rect.center().y() - text_rect.height() / 2,
        )


class MapsWidget(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._world_data = load_navigation_data()
        self._storage_path = maps_storage_path()
        self._load_entries_error = ""
        self._manager = MapsManager(entries=self._load_entries())
        self._current_entry: Optional[MapAsset] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        filter_bar = QFrame(self)
        filter_bar.setObjectName("Panel")
        filter_layout = QHBoxLayout(filter_bar)
        filter_layout.setContentsMargins(10, 8, 10, 8)
        filter_layout.setSpacing(10)

        self._world_combo = QComboBox()
        self._campaign_combo = QComboBox()
        self._group_combo = QComboBox()
        self._tag_input = QLineEdit()
        self._tag_input.setPlaceholderText("Tags: dungeon, town")

        self._reset_world_button = self._make_reset_button("Reset World")
        self._reset_world_button.clicked.connect(self._reset_world_filter)

        self._reset_campaign_button = self._make_reset_button("Reset Campaign")
        self._reset_campaign_button.clicked.connect(self._reset_campaign_filter)

        self._reset_group_button = self._make_reset_button("Reset Group")
        self._reset_group_button.clicked.connect(self._reset_group_filter)

        self._reset_tags_button = self._make_reset_button("Reset Tags")
        self._reset_tags_button.clicked.connect(self._reset_tags_filter)

        filter_layout.addWidget(
            self._build_filter_field("World", self._world_combo, self._reset_world_button),
            1,
        )
        filter_layout.addWidget(
            self._build_filter_field(
                "Campaign", self._campaign_combo, self._reset_campaign_button
            ),
            1,
        )
        filter_layout.addWidget(
            self._build_filter_field("Group", self._group_combo, self._reset_group_button),
            1,
        )
        filter_layout.addWidget(
            self._build_filter_field("Tags", self._tag_input, self._reset_tags_button),
            1,
        )

        self._new_button = QPushButton("New")
        self._new_button.setObjectName("PrimaryButton")
        self._new_button.setProperty("compact", True)
        self._new_button.setFixedSize(48, 48)
        self._new_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._new_button.setStyleSheet(
            "QPushButton#PrimaryButton {"
            "padding: 6px;"
            "min-width: 48px;"
            "max-width: 48px;"
            "min-height: 48px;"
            "max-height: 48px;"
            "border-radius: 8px;"
            "}"
        )
        self._new_button.clicked.connect(self._open_new_map_dialog)
        filter_layout.addWidget(self._new_button, 0, Qt.AlignmentFlag.AlignTop)

        layout.addWidget(filter_bar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(10)

        list_panel = QFrame(self)
        list_panel.setObjectName("Panel")
        list_panel.setMinimumWidth(320)
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(10, 10, 10, 10)
        list_layout.setSpacing(8)

        list_title = QLabel("Maps")
        list_title.setObjectName("PanelTitle")
        list_layout.addWidget(list_title)

        self._map_list = QListWidget()
        self._map_list.setObjectName("NavList")
        self._map_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._map_list.setIconSize(MAP_THUMB_SIZE)
        self._map_list.currentItemChanged.connect(self._on_map_selected)
        list_layout.addWidget(self._map_list, 1)

        splitter.addWidget(list_panel)

        right_container = QWidget(self)
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        header_panel = QFrame(self)
        header_panel.setObjectName("Panel")
        header_layout = QHBoxLayout(header_panel)
        header_layout.setContentsMargins(10, 6, 10, 6)
        header_layout.setSpacing(8)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._header_name = QLabel("Map: None")
        self._header_name.setObjectName("PanelTitle")
        header_layout.addWidget(self._header_name, 1)

        self._open_button = QToolButton()
        self._open_button.setObjectName("PrimaryButton")
        self._open_button.setIcon(QIcon(os.path.join(ICON_DIR, "external_link.svg")))
        self._open_button.setToolTip("Open Image externally")
        self._open_button.clicked.connect(self._open_map_image)

        self._edit_button = QToolButton()
        self._edit_button.setObjectName("SecondaryButton")
        self._edit_button.setIcon(QIcon(os.path.join(ICON_DIR, "edit.svg")))
        self._edit_button.setToolTip("Edit Map Settings")
        self._edit_button.clicked.connect(self._open_edit_map_dialog)

        self._save_button = QToolButton()
        self._save_button.setObjectName("SecondaryButton")
        self._save_button.setIcon(QIcon(os.path.join(ICON_DIR, "save.svg")))
        self._save_button.setToolTip("Save")
        self._save_button.clicked.connect(self._save_current_map)

        self._delete_button = QToolButton()
        self._delete_button.setObjectName("DestructiveButton")
        self._delete_button.setIcon(QIcon(os.path.join(ICON_DIR, "trash.svg")))
        self._delete_button.setToolTip("Delete to Trash")
        self._delete_button.clicked.connect(self._delete_current_map)

        self._disintegrate_button = QToolButton()
        self._disintegrate_button.setObjectName("DestructiveButton")
        self._disintegrate_button.setIcon(QIcon(os.path.join(ICON_DIR, "disintegrate.svg")))
        self._disintegrate_button.setToolTip("Permanently Delete")
        self._disintegrate_button.clicked.connect(self._disintegrate_current_map)

        for btn in (
            self._open_button,
            self._edit_button,
            self._save_button,
            self._delete_button,
            self._disintegrate_button,
        ):
            btn.setFixedSize(36, 36)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setStyleSheet("""
                QToolButton {
                    padding: 4px; 
                    border-radius: 6px; 
                    margin: 0px; 
                    min-width: 26px; 
                    max-width: 26px; 
                    min-height: 26px; 
                    max-height: 26px;
                }
            """)
            btn.setIconSize(QSize(20, 20))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            header_layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignVCenter)

        right_layout.addWidget(header_panel)

        preview_panel = QFrame(self)
        preview_panel.setObjectName("Panel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)

        preview_header = QWidget(self)
        preview_header_layout = QHBoxLayout(preview_header)
        preview_header_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_layout.setSpacing(6)

        self._preview_title = QLabel("Map View")
        self._preview_title.setObjectName("PanelTitle")
        preview_header_layout.addWidget(self._preview_title, 1)

        self._zoom_out_button = QToolButton(preview_header)
        self._zoom_out_button.setObjectName("SecondaryButton")
        self._zoom_out_button.setIcon(QIcon(os.path.join(ICON_DIR, "minus.svg")))
        self._zoom_out_button.setToolTip("Zoom Out")
        self._zoom_in_button = QToolButton(preview_header)
        self._zoom_in_button.setObjectName("SecondaryButton")
        self._zoom_in_button.setIcon(QIcon(os.path.join(ICON_DIR, "plus.svg")))
        self._zoom_in_button.setToolTip("Zoom In")
        self._zoom_label = QLabel("100%")
        self._zoom_label.setObjectName("Subheader")

        for button in (self._zoom_out_button, self._zoom_in_button):
            button.setProperty("compact", True)
            button.setFixedSize(36, 36)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setIconSize(QSize(20, 20))
            button.setStyleSheet(
                "QToolButton#SecondaryButton {"
                "padding: 0px;"
                "min-width: 36px;"
                "max-width: 36px;"
                "min-height: 36px;"
                "max-height: 36px;"
                "border-radius: 6px;"
                "}"
            )
            button.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_header_layout.addWidget(self._zoom_label)
        preview_header_layout.addWidget(self._zoom_out_button)
        preview_header_layout.addWidget(self._zoom_in_button)

        preview_layout.addWidget(preview_header)

        self._preview_panel = MapViewPanel(self)
        preview_layout.addWidget(self._preview_panel, 1)

        right_layout.addWidget(preview_panel, 1)

        splitter.addWidget(right_container)
        splitter.setSizes([340, 860])

        layout.addWidget(splitter, 1)

        _populate_combo(self._world_combo, list_worlds(self._world_data))
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)

        self._world_combo.currentIndexChanged.connect(self._on_world_changed)
        self._campaign_combo.currentIndexChanged.connect(self._on_campaign_changed)
        self._group_combo.currentIndexChanged.connect(self._apply_filters)
        self._tag_input.textChanged.connect(self._apply_filters)

        self._apply_filters()

        self._zoom_out_button.clicked.connect(self._preview_panel.zoom_out)
        self._zoom_in_button.clicked.connect(self._preview_panel.zoom_in)
        self._preview_panel.zoomChanged.connect(self._on_zoom_changed)
        if self._load_entries_error and not self._is_test_env():
            QTimer.singleShot(
                0,
                lambda msg=self._load_entries_error: QMessageBox.warning(
                    self,
                    "Maps Load Failed",
                    msg,
                ),
            )

    def _is_test_env(self) -> bool:
        if os.environ.get("DMT_TEST_MODE") == "1":
            return True
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return True
        return "pytest" in sys.modules

    def _make_reset_button(self, tooltip: str) -> QToolButton:
        btn = QToolButton(self)
        btn.setObjectName("InlineResetButton")
        btn.setIcon(QIcon(RESET_ICON))
        btn.setIconSize(QSize(14, 14))
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        return btn

    def _build_filter_field(
        self,
        label_text: str,
        widget: QWidget,
        reset_button: Optional[QToolButton] = None,
    ) -> QWidget:
        container = QWidget(self)
        container.setObjectName("FilterFieldContainer")
        container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)
        label = QLabel(label_text)
        label.setObjectName("Subheader")
        layout.addWidget(label)
        row = QWidget(container)
        row.setObjectName("TransparentContainer")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, widget.sizePolicy().verticalPolicy())
        row_layout.addWidget(widget, 1)
        if reset_button is not None:
            row_layout.addWidget(reset_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(row)
        return container

    def _load_entries(self) -> List[MapAsset]:
        entries: List[MapAsset] = []
        maps_images_dir().mkdir(parents=True, exist_ok=True)
        maps_thumbs_dir().mkdir(parents=True, exist_ok=True)
        for path in sorted(maps_storage_dir().glob(f"*{MAP_FILE_EXTENSION}")):
            info = read_dmt_package_info(path)
            if not isinstance(info, dict):
                continue
            if str(info.get("format") or "") != MAP_FILE_FORMAT:
                continue
            payload = info.get("payload")
            if not isinstance(payload, dict):
                continue
            payload = dict(payload)
            object_id = str(info.get("object_id") or payload.get("id") or "").strip()
            if not object_id:
                continue
            payload["id"] = object_id
            image_asset = str(info.get("image_asset") or "").strip()
            thumb_asset = str(info.get("thumbnail_asset") or "").strip()
            if image_asset:
                raw = read_dmt_package_asset(path, image_asset)
                if raw:
                    image_suffix = Path(image_asset).suffix.lower() or ".png"
                    image_target = maps_images_dir() / f"{sanitize_filename(object_id)}{image_suffix}"
                    try:
                        image_target.write_bytes(raw)
                        payload["image_path"] = str(image_target)
                    except OSError:
                        continue
            if thumb_asset:
                raw_thumb = read_dmt_package_asset(path, thumb_asset)
                if raw_thumb:
                    thumb_target = maps_thumbs_dir() / f"{sanitize_filename(object_id)}.png"
                    try:
                        thumb_target.write_bytes(raw_thumb)
                        payload["thumbnail_path"] = str(thumb_target)
                    except OSError:
                        pass
            entry = entry_from_dict(payload)
            if entry:
                entries.append(entry)
        return entries

    def _save_entries(self) -> None:
        root = maps_storage_dir()
        root.mkdir(parents=True, exist_ok=True)
        expected_files: set[Path] = set()
        for entry in self._manager.entries:
            if not str(entry.id or "").strip():
                entry.id = generate_probabilistic_unique_id("map")
            resolved_image = self._resolve_map_image_path(entry)
            if not resolved_image:
                continue
            image_path = Path(resolved_image)
            image_suffix = image_path.suffix.lower() or ".png"
            thumb_path = maps_thumbs_dir() / f"{sanitize_filename(entry.id)}.png"
            thumb_str = _ensure_thumbnail(str(image_path), thumb_path)
            if thumb_str:
                entry.thumbnail_path = thumb_str
            assets: dict[str, bytes] = {}
            image_asset_name = f"assets/map{image_suffix}"
            thumb_asset_name = "assets/thumb.png"
            try:
                assets[image_asset_name] = image_path.read_bytes()
            except Exception:
                continue
            if entry.thumbnail_path:
                try:
                    assets[thumb_asset_name] = Path(entry.thumbnail_path).read_bytes()
                except Exception:
                    pass
            file_path = map_file_path(entry.id)
            expected_files.add(file_path.resolve())
            write_dmt_package(
                file_path,
                info={
                    "format": MAP_FILE_FORMAT,
                    "object_type": "map",
                    "object_id": str(entry.id),
                    "name": str(entry.name),
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "image_asset": image_asset_name,
                    "thumbnail_asset": thumb_asset_name if thumb_asset_name in assets else "",
                    "payload": entry_to_dict(entry),
                },
                assets=assets,
            )
        for existing in root.glob(f"*{MAP_FILE_EXTENSION}"):
            try:
                resolved_existing = existing.resolve()
            except Exception:
                resolved_existing = existing
            if resolved_existing in expected_files:
                continue
            info = read_dmt_package_info(existing)
            if not isinstance(info, dict):
                continue
            if str(info.get("format") or "") != MAP_FILE_FORMAT:
                continue
            try:
                existing.unlink()
            except Exception:
                continue

    def _on_world_changed(self) -> None:
        selected_campaign = self._refresh_campaigns()
        self._refresh_groups(campaign=selected_campaign)
        self._apply_filters()

    def _on_campaign_changed(self) -> None:
        self._refresh_groups()
        self._apply_filters()

    def _refresh_campaigns(self, current_value: Optional[str] = None) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        campaigns = list_campaigns(self._world_data, world)
        if current_value is None:
            current_value = _combo_optional_value(self._campaign_combo)
        selection = resolve_selection(campaigns, current_value)
        _populate_combo(self._campaign_combo, campaigns, selection)
        return selection

    def _refresh_groups(
        self, current_value: Optional[str] = None, campaign: Optional[str] = None
    ) -> Optional[str]:
        world = _combo_optional_value(self._world_combo)
        if campaign is None:
            campaign = _combo_optional_value(self._campaign_combo)
        groups = list_groups(self._world_data, world, campaign)
        if current_value is None:
            current_value = _combo_optional_value(self._group_combo)
        selection = resolve_selection(groups, current_value)
        _populate_combo(self._group_combo, groups, selection)
        return selection

    def _reset_world_filter(self) -> None:
        self._world_combo.setCurrentIndex(0)

    def _reset_campaign_filter(self) -> None:
        self._campaign_combo.setCurrentIndex(0)

    def _reset_group_filter(self) -> None:
        self._group_combo.setCurrentIndex(0)

    def _reset_tags_filter(self) -> None:
        self._tag_input.setText("")

    def _apply_filters(self) -> None:
        self._manager.set_filters(
            world=_combo_optional_value(self._world_combo),
            campaign=_combo_optional_value(self._campaign_combo),
            group=_combo_optional_value(self._group_combo),
            tag_query=self._tag_input.text().strip(),
        )
        entries = self._manager.filtered_entries()
        self._refresh_list(entries)

    def _thumbnail_for_entry(self, entry: MapAsset) -> Optional[QPixmap]:
        path = entry.thumbnail_path or entry.image_path
        if entry.image_path and os.path.exists(entry.image_path):
            regenerated = _ensure_thumbnail(
                entry.image_path,
                maps_thumbs_dir() / f"{map_id_for_entry(entry)}.png",
            )
            if regenerated:
                path = regenerated
        if not path or not os.path.exists(path):
            return None
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return None
        dpr = max(1.0, float(self.devicePixelRatioF()))
        target = QSize(
            max(1, int(round(MAP_THUMB_SIZE.width() * dpr))),
            max(1, int(round(MAP_THUMB_SIZE.height() * dpr))),
        )
        scaled = pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(dpr)
        return scaled

    def _refresh_list(self, entries: List[MapAsset]) -> None:
        previous_entry = self._current_entry
        self._map_list.blockSignals(True)
        self._map_list.clear()
        selection_index = -1
        for index, entry in enumerate(entries):
            context_parts = [part for part in [entry.world, entry.campaign, entry.group] if part]
            context_line = " · ".join(context_parts) if context_parts else "Unassigned"
            tags_line = ", ".join(entry.tags) if entry.tags else "No tags"
            item_text = f"{entry.name}\n{context_line}\n{tags_line}"
            item = QListWidgetItem(item_text)
            thumbnail = self._thumbnail_for_entry(entry)
            if thumbnail:
                item.setIcon(QIcon(thumbnail))
            item.setData(Qt.ItemDataRole.UserRole, entry)
            item.setSizeHint(QSize(0, MAP_THUMB_SIZE.height() + 48))
            self._map_list.addItem(item)
            if entry is previous_entry:
                selection_index = index
        self._map_list.blockSignals(False)

        if entries:
            if selection_index == -1:
                selection_index = 0
            self._map_list.setCurrentRow(selection_index)
        else:
            self._set_details(None)

    def _set_details(self, entry: Optional[MapAsset]) -> None:
        self._current_entry = entry
        if not entry:
            self._header_name.setText("Map: None")
            self._open_button.setEnabled(False)
            self._edit_button.setEnabled(False)
            self._delete_button.setEnabled(False)
            self._disintegrate_button.setEnabled(False)
            self._preview_panel.load_image(None)
            return

        self._header_name.setText(f"Map: {entry.name}")
        self._open_button.setEnabled(bool(entry.image_path))
        self._edit_button.setEnabled(True)
        self._delete_button.setEnabled(True)
        self._disintegrate_button.setEnabled(True)
        self._load_map_preview(entry)

    def _on_map_selected(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        if current is None:
            self._set_details(None)
            return
        entry = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._set_details(entry)

    def _select_entry_by_id(self, entry_id: str) -> None:
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            return
        for index in range(self._map_list.count()):
            item = self._map_list.item(index)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if entry and str(getattr(entry, "id", "")).strip() == clean_id:
                self._map_list.setCurrentRow(index)
                return

    def open_linked_entry(self, entry_id: str) -> bool:
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            return False
        self._world_combo.blockSignals(True)
        self._campaign_combo.blockSignals(True)
        self._group_combo.blockSignals(True)
        self._world_combo.setCurrentIndex(0)
        self._campaign_combo.setCurrentIndex(0)
        self._group_combo.setCurrentIndex(0)
        self._world_combo.blockSignals(False)
        self._campaign_combo.blockSignals(False)
        self._group_combo.blockSignals(False)
        self._tag_input.setText("")
        self._apply_filters()
        self._select_entry_by_id(clean_id)
        return bool(self._current_entry and self._current_entry.id == clean_id)

    def _load_map_preview(self, entry: Optional[MapAsset]) -> None:
        if not entry:
            self._preview_panel.load_image(None)
            return
        path = self._resolve_map_image_path(entry)
        if not path:
            self._preview_panel.load_image(None)
            return
        self._preview_panel.load_image(path)

    def _resolve_map_image_path(
        self, entry: MapAsset, source_path: Optional[str] = None
    ) -> Optional[str]:
        map_id = map_id_for_entry(entry)
        source = source_path or entry.image_path
        if not source:
            return None
        source_path_obj = Path(source)
        if source_path_obj.exists() and maps_images_dir() in source_path_obj.parents:
            entry.image_path = str(source_path_obj)
            return str(source_path_obj)
        if source and os.path.exists(source):
            maps_images_dir().mkdir(parents=True, exist_ok=True)
            suffix = os.path.splitext(source)[1] or ".png"
            target = _unique_image_path(maps_images_dir() / f"{map_id}{suffix}")
            try:
                shutil.copy2(source, target)
            except OSError:
                return source
            entry.image_path = str(target)
            thumb = _ensure_thumbnail(str(target), maps_thumbs_dir() / f"{map_id}.png")
            if thumb:
                entry.thumbnail_path = thumb
            self._save_entries()
            return str(target)
        return None

    def _open_map_image(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a map to open.")
            return
        path = self._resolve_map_image_path(self._current_entry)
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Missing File", "The map image does not exist.")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
            QMessageBox.warning(self, "Open Failed", "Unable to open the map image.")

    def _remove_entry(self, entry: MapAsset) -> None:
        self._manager.entries = [item for item in self._manager.entries if item is not entry]
        self._save_entries()
        self._apply_filters()
        if self._current_entry is entry:
            self._set_details(None)

    def _trash_payload_for_entry(self, entry: MapAsset) -> dict:
        payload = entry_to_dict(entry)
        payload["map_id"] = map_id_for_entry(entry)
        return payload

    def _delete_current_map(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a map to delete.")
            return
        trashed_image, trashed_thumb = move_entry_files_to_trash(self._current_entry)
        payload = self._trash_payload_for_entry(self._current_entry)
        if trashed_image:
            payload["image_path"] = trashed_image
        if trashed_thumb:
            payload["thumbnail_path"] = trashed_thumb
        move_to_trash("map", payload)
        self._remove_entry(self._current_entry)

    def _disintegrate_current_map(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a map to disintegrate.")
            return
        typed, ok = QInputDialog.getText(
            self,
            "Disintegrate Map",
            "Type DISINTEGRATE to permanently delete this map.",
        )
        if not ok:
            return
        if typed.strip().upper() != "DISINTEGRATE":
            QMessageBox.warning(
                self,
                "Confirmation Required",
                "Disintegration cancelled. The confirmation text did not match.",
            )
            return
        disintegrate_entry_files(self._current_entry)
        self._remove_entry(self._current_entry)

    def _delete_entry_files(self, entry: MapAsset) -> None:
        disintegrate_entry_files(entry)

    def _open_new_map_dialog(self) -> None:
        dialog = MapDialog(self._world_data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.entry()
            if not entry:
                return
            self._manager.add_map(entry)
            self._save_entries()
            self._apply_filters()

    def _open_edit_map_dialog(self) -> None:
        if not self._current_entry:
            QMessageBox.information(self, "No Selection", "Select a map to edit.")
            return
        dialog = MapDialog(self._world_data, self, entry=self._current_entry)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.entry()
        if not updated:
            return
        self._current_entry.name = updated.name
        self._current_entry.image_path = updated.image_path
        self._current_entry.thumbnail_path = updated.thumbnail_path
        self._current_entry.world = updated.world
        self._current_entry.campaign = updated.campaign
        self._current_entry.group = updated.group
        self._current_entry.tags = updated.tags
        self._current_entry.notes = updated.notes
        self._current_entry.last_modified = updated.last_modified
        self._save_entries()
        self._apply_filters()

    def _on_zoom_changed(self, percent: int) -> None:
        self._zoom_label.setText(f"{percent}%")

    def _save_current_map(self) -> None:
        self._save_entries()
        QMessageBox.information(self, "Save", "Map settings saved successfully.")

