from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QEvent, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QKeySequence, QShortcut, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QAbstractSpinBox,
    QVBoxLayout,
    QWidget,
    QSplitter,
)

from ui.widgets import PlusMinusSpinBox
from viewer.pdfium_viewer_widget import PdfiumViewerWidget


ICON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "icons"))


class PageSpinBox(QSpinBox):
    """QSpinBox that swaps up/down logic for document navigation."""

    def stepEnabled(self) -> QAbstractSpinBox.StepEnabled:
        # We want to swap the enabling logic too.
        # Up button (StepUp) should be enabled if we can DECREASE (go to prev page).
        # Down button (StepDown) should be enabled if we can INCREASE (go to next page).
        flags = QAbstractSpinBox.StepEnabledFlag.StepNone
        
        val = self.value()
        if val > self.minimum():
            flags |= QAbstractSpinBox.StepEnabledFlag.StepUpEnabled
        if val < self.maximum():
            flags |= QAbstractSpinBox.StepEnabledFlag.StepDownEnabled
        return flags

    def stepBy(self, steps: int) -> None:
        # Up button click gives positive steps, Down button gives negative steps.
        # We want Up to decrease, Down to increase.
        super().stepBy(-steps)
        # Deselect and clear focus to hide the cursor/edit mode when using buttons
        self.lineEdit().deselect()
        self.clearFocus()


class CharacterSheetPanel(QWidget):
    """Toolbar + scrollable PDF viewer for character sheets."""

    unsavedChanged = Signal(bool)
    statusMessage = Signal(str)
    pdfPathSelected = Signal(str)
    expandToggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._current_path: Optional[str] = None
        self._autosave_path: Optional[str] = None
        self._autosave_enabled = False
        self._autosave_timer: Optional[QTimer] = None
        self._fit_width_enabled = False
        self._fit_page_enabled = False
        self._updating_page_input = False
        self._expanded = False
        self._center_title_text = ""
        self._center_unsaved = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QFrame(self)
        toolbar.setObjectName("SubPanel")
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(8, 6, 8, 6)
        toolbar_layout.setSpacing(6)

        self._open_button = QPushButton("Open")
        self._reload_button = QPushButton("Reload")
        self._save_as_button = QPushButton("Save As")

        self._page_input = PageSpinBox()
        self._page_input.setMinimum(1)
        self._page_input.setMaximum(1)
        self._page_input.setFixedWidth(64)
        self._page_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._page_input.setPrefix("")
        self._page_input.setKeyboardTracking(False)
        self._page_input.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        line_edit = self._page_input.lineEdit()
        if line_edit is not None:
            line_edit.setReadOnly(False)
        self._page_label = QLabel("/ 0")
        self._page_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._center_title = QLabel("")
        self._center_title.setObjectName("PanelTitle")
        self._center_title.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter
        )
        self._center_title.setMinimumWidth(0)
        self._center_title.setVisible(False)

        self._zoom_out_button = QPushButton()
        self._zoom_out_button.setIcon(QIcon(os.path.join(ICON_DIR, "zoom_out.svg")))
        self._zoom_out_button.setIconSize(QSize(16, 16))
        self._zoom_out_button.setToolTip("Zoom Out")
        self._zoom_in_button = QPushButton()
        self._zoom_in_button.setIcon(QIcon(os.path.join(ICON_DIR, "zoom_in.svg")))
        self._zoom_in_button.setIconSize(QSize(16, 16))
        self._zoom_in_button.setToolTip("Zoom In")
        self._fit_button = QPushButton("Fit Width")
        self._fit_page_button = QPushButton("Fit Page")
        self._zoom_label = QLabel("100%")
        self._expand_button = QPushButton("Expand")
        self._expand_button.setToolTip("Expand character sheet view")

        for btn in (
            self._open_button,
            self._reload_button,
            self._save_as_button,
            self._zoom_out_button,
            self._zoom_in_button,
            self._fit_button,
            self._fit_page_button,
            self._expand_button,
        ):
            btn.setProperty("compact", True)

        toolbar_layout.addWidget(self._save_as_button)
        toolbar_layout.addWidget(self._page_input)
        toolbar_layout.addWidget(self._page_label)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self._center_title, 1, Qt.AlignmentFlag.AlignCenter)
        toolbar_layout.addStretch(1)
        toolbar_layout.addWidget(self._zoom_label)
        toolbar_layout.addWidget(self._zoom_out_button)
        toolbar_layout.addWidget(self._zoom_in_button)
        toolbar_layout.addWidget(self._fit_button)
        toolbar_layout.addWidget(self._fit_page_button)
        toolbar_layout.addWidget(self._expand_button)

        layout.addWidget(toolbar)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(False)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setAutoFillBackground(False)
        self._scroll_area.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self._scroll_area.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        viewport = self._scroll_area.viewport()
        viewport.setAutoFillBackground(False)
        viewport.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        viewport.setObjectName("TransparentContainer")
        viewport.installEventFilter(self)

        self._viewer = PdfiumViewerWidget(self)
        self._viewer.statusMessage.connect(self._on_status_message)
        self._viewer.pageChanged.connect(self._on_page_changed)
        self._viewer.zoomChanged.connect(self._on_zoom_changed)
        self._viewer.unsavedChanged.connect(self._on_unsaved_changed)

        self._scroll_area.setWidget(self._viewer)
        layout.addWidget(self._scroll_area, 1)

        self._open_button.clicked.connect(self._open_pdf_dialog)
        self._save_as_button.clicked.connect(self.save_as)
        self._zoom_out_button.clicked.connect(self._zoom_out)
        self._zoom_in_button.clicked.connect(self._zoom_in)
        self._fit_button.clicked.connect(self._fit_width)
        self._fit_page_button.clicked.connect(self._fit_page)
        self._page_input.editingFinished.connect(self._on_page_input_changed)
        self._page_input.valueChanged.connect(self._on_page_input_changed)
        self._expand_button.clicked.connect(self._on_expand_clicked)

        # Note: Ctrl+S shortcut is handled by the parent sheets widget

    @property
    def current_path(self) -> Optional[str]:
        return self._current_path

    def set_autosave_path(self, path: Optional[str]) -> None:
        self._autosave_path = path

    def set_autosave_enabled(self, enabled: bool) -> None:
        self._autosave_enabled = enabled

    def set_center_title(self, text: str) -> None:
        self._center_title_text = text.strip()
        self._update_center_title()

    def set_center_unsaved(self, unsaved: bool) -> None:
        self._center_unsaved = unsaved
        self._update_center_title()

    def is_modified(self) -> bool:
        return self._viewer.modified

    def load_pdf(self, path: Optional[str]) -> None:
        if not path:
            self.clear()
            return
        self._current_path = path
        ok = self._viewer.load_document(path)
        if ok:
            self._fit_width_enabled = False
            self._fit_page_enabled = False
            self._on_page_changed(
                self._viewer.current_page_index() + 1, self._viewer.page_count()
            )
            self._viewer.set_viewport_width(self._scroll_area.viewport().width())
            self._scroll_area.verticalScrollBar().setValue(0)
        else:
            self._page_label.setText("Page 0 / 0")

    def clear(self) -> None:
        self._current_path = None
        self._viewer.close_document()
        self._page_label.setText("/ 0")
        self._page_input.setValue(1)
        self._page_input.setMaximum(1)
        self._zoom_label.setText("100%")

    def reload(self) -> None:
        if not self._current_path:
            return
        self._viewer.reload()

    def save_current(self) -> None:
        if not self._current_path and not self._autosave_path:
            self.save_as()
            return
        target = self._current_path or self._autosave_path
        if not target:
            return
        self._viewer.save_document(target)

    def save_as(self) -> None:
        base_dir = os.path.dirname(self._current_path) if self._current_path else ""
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Character Sheet",
            base_dir,
            "PDF Files (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        ok = self._viewer.save_document(path)
        if ok:
            self._current_path = path

    def set_expanded(self, expanded: bool) -> None:
        if self._expanded == expanded:
            return
        self._expanded = expanded
        if expanded:
            self._expand_button.setText("Collapse")
            self._expand_button.setToolTip("Collapse character sheet view")
        else:
            self._expand_button.setText("Expand")
            self._expand_button.setToolTip("Expand character sheet view")
        self._update_center_title()

    def _update_center_title(self) -> None:
        if not self._center_title_text:
            self._center_title.setText("")
            self._center_title.setVisible(False)
            return
        label_text = self._center_title_text
        if self._center_unsaved:
            label_text = f"{label_text} *"
        self._center_title.setText(label_text)
        self._center_title.setVisible(self._expanded)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_viewer_to_viewport()

    def eventFilter(self, watched, event):  # type: ignore[override]
        if watched is self._scroll_area.viewport() and event.type() == QEvent.Type.Resize:
            self._sync_viewer_to_viewport()
        return super().eventFilter(watched, event)

    def _open_pdf_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Character Sheet",
            "",
            "PDF Files (*.pdf)",
        )
        if not path:
            return
        self.pdfPathSelected.emit(path)

    def _on_status_message(self, message: str) -> None:
        if message:
            self.statusMessage.emit(message)

    def _on_page_changed(self, current: int, total: int) -> None:
        self._page_label.setText(f"/ {total}")
        self._update_page_input_limits(total)
        self._set_page_input_value(current)

    def _on_zoom_changed(self, zoom: float) -> None:
        self._zoom_label.setText(f"{int(zoom * 100)}%")

    def _on_unsaved_changed(self, modified: bool) -> None:
        self.unsavedChanged.emit(modified)
        if modified and self._autosave_enabled and self._autosave_path:
            self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if self._autosave_timer is None:
            self._autosave_timer = QTimer(self)
            self._autosave_timer.setSingleShot(True)
            self._autosave_timer.timeout.connect(self._run_autosave)
        self._autosave_timer.start(750)

    def _run_autosave(self) -> None:
        if not self._autosave_path:
            return
        self._viewer.save_document(self._autosave_path)
        if self._current_path is None:
            self._current_path = self._autosave_path

    def _zoom_in(self) -> None:
        self._fit_width_enabled = False
        self._fit_page_enabled = False
        self._viewer.set_zoom_factor(self._viewer.zoom_factor() * 1.15)

    def _zoom_out(self) -> None:
        self._fit_width_enabled = False
        self._fit_page_enabled = False
        self._viewer.set_zoom_factor(self._viewer.zoom_factor() / 1.15)

    def _fit_width(self) -> None:
        splitter_sizes = self._capture_ancestor_splitter_sizes()
        self._fit_width_enabled = True
        self._fit_page_enabled = False
        width = self._scroll_area.viewport().width()
        if width <= 0:
            return
        self._viewer.set_fit_width(width)
        self._schedule_splitter_size_restore(splitter_sizes)

    def _fit_page(self) -> None:
        splitter_sizes = self._capture_ancestor_splitter_sizes()
        self._fit_page_enabled = True
        self._fit_width_enabled = False
        width = self._scroll_area.viewport().width()
        height = self._scroll_area.viewport().height()
        if width <= 0 or height <= 0:
            return
        self._viewer.set_fit_page(width, height)
        self._schedule_splitter_size_restore(splitter_sizes)

    def _on_expand_clicked(self) -> None:
        self.expandToggled.emit(not self._expanded)

    def _on_page_input_changed(self) -> None:
        if self._updating_page_input:
            return
        page_value = int(self._page_input.value())
        index = max(0, min(page_value - 1, self._viewer.page_count() - 1))
        self._viewer.set_page_index(index)
        self._scroll_to_page(index)

    def _scroll_to_page(self, index: int) -> None:
        y_offset = self._viewer.page_offset_y(index)
        if y_offset is None:
            return
        self._scroll_area.verticalScrollBar().setValue(int(y_offset))

    def _update_page_input_limits(self, total: int) -> None:
        total = max(1, total)
        self._page_input.setMaximum(total)

    def _set_page_input_value(self, current: int) -> None:
        self._updating_page_input = True
        try:
            self._page_input.setValue(max(1, current))
        finally:
            self._updating_page_input = False

    def _capture_ancestor_splitter_sizes(self) -> list[tuple[QSplitter, list[int]]]:
        snapshots: list[tuple[QSplitter, list[int]]] = []
        seen: set[int] = set()
        parent = self.parentWidget()
        while parent is not None:
            if isinstance(parent, QSplitter):
                splitter_id = id(parent)
                if splitter_id not in seen:
                    seen.add(splitter_id)
                    snapshots.append((parent, parent.sizes()))
            parent = parent.parentWidget()
        return snapshots

    def _schedule_splitter_size_restore(
        self, snapshots: list[tuple[QSplitter, list[int]]]
    ) -> None:
        if not snapshots:
            return
        # Restore on the current and next layout ticks to absorb deferred relayout.
        QTimer.singleShot(0, lambda: self._restore_splitter_sizes(snapshots))
        QTimer.singleShot(16, lambda: self._restore_splitter_sizes(snapshots))

    def _restore_splitter_sizes(self, snapshots: list[tuple[QSplitter, list[int]]]) -> None:
        for splitter, sizes in snapshots:
            if splitter is None:
                continue
            if splitter.count() != len(sizes):
                continue
            splitter.setSizes(sizes)

    def _sync_viewer_to_viewport(self) -> None:
        viewport = self._scroll_area.viewport()
        viewport_width = viewport.width()
        viewport_height = viewport.height()
        self._viewer.set_viewport_width(viewport_width)
        if self._fit_width_enabled:
            self._viewer.update_fit_width(viewport_width)
        if self._fit_page_enabled:
            self._viewer.update_fit_page(viewport_width, viewport_height)
