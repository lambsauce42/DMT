from __future__ import annotations

import ctypes
from collections import OrderedDict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from PySide6.QtCore import Qt, QSize, QTimer, QPointF, QRectF, Signal
from PySide6.QtGui import QCursor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c


_MAX_RENDER_CACHE = 6
_PAGE_SPACING = 16


@dataclass
class _PageHandle:
    page: pdfium.PdfPage
    index: int


class PdfiumViewerWidget(QWidget):
    """Render and edit AcroForm PDFs using PDFium FormFill APIs.

    The FormFill environment must be initialized per document to enable
    interactive editing (caret, focus, widget updates). Mouse/keyboard
    events are routed into PDFium so the form engine can update fields
    and request repaints via callbacks.
    """

    pageChanged = Signal(int, int)
    zoomChanged = Signal(float)
    unsavedChanged = Signal(bool)
    statusMessage = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        # Keep the viewer from pushing parent splitter sizes around when zoom modes
        # recalculate content dimensions; the scroll area should own panel sizing.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(0, 0)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._doc: Optional[pdfium.PdfDocument] = None
        self._doc_path: Optional[str] = None
        self._form_handle = None
        self._form_info = None
        self._callbacks: Dict[str, object] = {}
        self._page_handles: Dict[int, _PageHandle] = {}
        self._page_handle_by_ptr: Dict[int, int] = {}
        self._current_page_index = 0
        self._page_count = 0
        self._zoom = 1.0
        self._fit_width_enabled = False
        self._fit_page_enabled = False
        self._page_sizes_pt: list[Tuple[float, float]] = []
        self._page_rects: list[QRectF] = []
        self._min_viewport_width = 0.0
        self._render_cache: "OrderedDict[Tuple[int, float, int], QImage]" = OrderedDict()
        self._dirty_pages: set[int] = set()
        self._current_image: Optional[QImage] = None
        self._modified = False
        self._loading = False  # Guard to prevent modified flag during load
        self._timers: Dict[int, QTimer] = {}
        self._next_timer_id = 1
        self._pending_render = False
        self._last_mouse_down: Optional[Tuple[int, float, float]] = None
        self._last_mouse_down_field_type: Optional[int] = None

    @property
    def document_path(self) -> Optional[str]:
        return self._doc_path

    @property
    def modified(self) -> bool:
        return self._modified

    def page_count(self) -> int:
        return self._page_count

    def current_page_index(self) -> int:
        return self._current_page_index

    def zoom_factor(self) -> float:
        return self._zoom

    def page_offset_y(self, index: int) -> Optional[float]:
        if index < 0 or index >= len(self._page_rects):
            return None
        return self._page_rects[index].top()

    def set_viewport_width(self, width: int) -> None:
        width = max(0, width)
        if abs(width - self._min_viewport_width) < 1.0:
            return
        self._min_viewport_width = float(width)
        if self._doc is not None:
            self._rebuild_layout()

    def load_document(self, path: str) -> bool:
        self.close_document()
        if not path:
            return False
        self._loading = True  # Set loading guard before opening
        try:
            self._doc = pdfium.PdfDocument(path)
        except Exception as exc:  # pragma: no cover - depends on pdfium internals
            self._loading = False
            self.statusMessage.emit(f"Unable to load PDF: {exc}")
            return False

        self._doc_path = path
        self._page_count = len(self._doc)
        if self._page_count == 0:
            self.statusMessage.emit("PDF contains no pages.")
            self._doc = None
            self._doc_path = None
            return False

        self._init_form_environment()
        self._current_page_index = 0
        self._page_sizes_pt = []
        self._page_rects = []
        self._render_cache.clear()
        self._dirty_pages.clear()
        self._load_page(self._current_page_index)
        self._ensure_page_sizes()
        self._rebuild_layout()
        self._render_visible_pages(force=True)
        self._loading = False  # Clear loading guard after everything is loaded
        self._set_modified(False)
        self.pageChanged.emit(self._current_page_index + 1, self._page_count)
        return True

    def close_document(self) -> None:
        self._cancel_pending_render()
        self._clear_timers()
        self._close_all_pages()
        if self._form_handle is not None:
            try:
                pdfium_c.FORM_ForceToKillFocus(self._form_handle)
            except Exception:
                pass
            pdfium_c.FPDFDOC_ExitFormFillEnvironment(self._form_handle)
        self._form_handle = None
        self._form_info = None
        self._callbacks.clear()
        if self._doc is not None:
            close = getattr(self._doc, "close", None)
            if callable(close):
                close()
        self._doc = None
        self._doc_path = None
        self._page_count = 0
        self._current_page_index = 0
        self._page_sizes_pt = []
        self._page_rects = []
        self._render_cache.clear()
        self._dirty_pages.clear()
        self._current_image = None
        self._last_mouse_down = None
        self._last_mouse_down_field_type = None
        self.update()

    def save_document(self, path: str) -> bool:
        if self._doc is None:
            return False
        try:
            self._commit_form_changes()
            # Use FPDF_SaveAsCopy with incremental flag to preserve form data
            raw_doc = self._doc.raw if hasattr(self._doc, "raw") else self._doc
            # Try incremental save first (preserves more structure)
            if hasattr(pdfium_c, "FPDF_SaveAsCopy"):
                import io
                buffer = io.BytesIO()
                
                # Define the file write callback
                @ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(pdfium_c.FPDF_FILEWRITE), ctypes.c_void_p, ctypes.c_ulong)
                def write_block(file_write, data, size):
                    buffer.write(ctypes.string_at(data, size))
                    return 1
                
                file_write = pdfium_c.FPDF_FILEWRITE()
                file_write.version = 1
                file_write.WriteBlock = write_block
                
                # FPDF_INCREMENTAL = 1, preserves form field appearance streams
                save_flags = 1  # FPDF_INCREMENTAL
                result = pdfium_c.FPDF_SaveAsCopy(raw_doc, ctypes.byref(file_write), save_flags)
                
                if result:
                    with open(path, "wb") as f:
                        f.write(buffer.getvalue())
                else:
                    # Fallback to pypdfium2 save
                    self._doc.save(path)
            else:
                self._doc.save(path)
        except Exception as exc:  # pragma: no cover - depends on pdfium internals
            self.statusMessage.emit(f"Unable to save PDF: {exc}")
            return False
        self._set_modified(False)
        self._doc_path = path
        return True

    def reload(self) -> bool:
        if not self._doc_path:
            return False
        return self.load_document(self._doc_path)

    def set_zoom_factor(self, factor: float) -> None:
        factor = max(0.25, min(4.0, factor))
        self._fit_width_enabled = False
        self._fit_page_enabled = False
        if abs(factor - self._zoom) < 0.0001:
            return
        self._zoom = factor
        self._render_cache.clear()
        self._dirty_pages.clear()
        self._rebuild_layout()
        self._render_visible_pages(force=True)
        self.zoomChanged.emit(self._zoom)

    def set_fit_width(self, viewport_width: int) -> None:
        if viewport_width <= 0 or not self._doc:
            return
        self._fit_width_enabled = True
        self._fit_page_enabled = False
        self._ensure_page_sizes()
        if not self._page_sizes_pt:
            return
        page_width_pt = max(size[0] for size in self._page_sizes_pt)
        if page_width_pt <= 0:
            return
        self._zoom = max(0.25, min(4.0, viewport_width / page_width_pt))
        self._render_cache.clear()
        self._dirty_pages.clear()
        self._rebuild_layout()
        self._render_visible_pages(force=True)
        self.zoomChanged.emit(self._zoom)

    def update_fit_width(self, viewport_width: int) -> None:
        if self._fit_width_enabled:
            self.set_fit_width(viewport_width)

    def set_fit_page(self, viewport_width: int, viewport_height: int) -> None:
        if viewport_width <= 0 or viewport_height <= 0 or not self._doc:
            return
        self._fit_page_enabled = True
        self._fit_width_enabled = False
        self._ensure_page_sizes()
        if not self._page_sizes_pt:
            return
        index = max(0, min(self._current_page_index, self._page_count - 1))
        page_width_pt, page_height_pt = self._page_sizes_pt[index]
        if page_width_pt <= 0 or page_height_pt <= 0:
            return
        scale_x = viewport_width / page_width_pt
        scale_y = viewport_height / page_height_pt
        self._zoom = max(0.25, min(4.0, min(scale_x, scale_y)))
        self._render_cache.clear()
        self._dirty_pages.clear()
        self._rebuild_layout()
        self._render_visible_pages(force=True)
        self.zoomChanged.emit(self._zoom)

    def update_fit_page(self, viewport_width: int, viewport_height: int) -> None:
        if self._fit_page_enabled:
            self.set_fit_page(viewport_width, viewport_height)

    def next_page(self) -> None:
        if self._page_count == 0:
            return
        self.set_page_index(self._current_page_index + 1)

    def prev_page(self) -> None:
        if self._page_count == 0:
            return
        self.set_page_index(self._current_page_index - 1)

    def set_page_index(self, index: int) -> None:
        if self._doc is None:
            return
        index = max(0, min(index, self._page_count - 1))
        if index == self._current_page_index:
            return
        self._current_page_index = index
        self._load_page(index)
        self._render_visible_pages(force=True)
        self.pageChanged.emit(self._current_page_index + 1, self._page_count)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        if not self._page_rects:
            if self._doc is not None:
                self._rebuild_layout()
            if not self._page_rects:
                return
        visible_region = self.visibleRegion().boundingRect()
        if visible_region.isEmpty():
            visible_region = event.rect()
        zoom_key = round(self._zoom, 3)
        dpr_key = int(round(self._effective_device_pixel_ratio() * 100.0))
        for index, rect in enumerate(self._page_rects):
            if not rect.intersects(QRectF(visible_region)):
                continue
            image = self._render_page(index, zoom_key, dpr_key)
            if image is not None:
                painter.drawImage(rect.topLeft(), image)
        self._update_current_page_from_visible(visible_region)

    def sizeHint(self) -> QSize:  # type: ignore[override]
        if not self._page_rects:
            return QSize(640, 480)
        max_width = max(rect.width() for rect in self._page_rects)
        total_height = self._page_rects[-1].bottom()
        return QSize(int(max_width), int(total_height))

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if not self._form_handle or not self._doc:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        hit = self._page_hit_test(event.position())
        if hit is None:
            return
        page_index, page_x, page_y = hit
        page = self._get_page(page_index)
        if page is None:
            return
        # Use raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        self._last_mouse_down = (page_index, page_x, page_y)
        field_type = self._form_field_type_at_point(raw_page, page_x, page_y)
        self._last_mouse_down_field_type = field_type
        self._set_current_page_index(page_index)
        modifier = self._event_modifier_flags(event)
        pdfium_c.FORM_OnFocus(self._form_handle, raw_page, modifier, page_x, page_y)
        handled = pdfium_c.FORM_OnLButtonDown(
            self._form_handle, raw_page, modifier, page_x, page_y
        )
        # Always mark dirty and re-render so click-driven widget visuals update.
        self._mark_page_dirty(page_index)
        if handled and self._should_mark_modified_for_mouse_field(field_type):
            self._mark_modified()
        self._schedule_render()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not self._form_handle or not self._doc:
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self._page_hit_test(event.position())
        if hit is None:
            hit = self._last_mouse_down
        if hit is None:
            return
        page_index, page_x, page_y = hit
        page = self._get_page(page_index)
        if page is None:
            return
        # Use raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        self._last_mouse_down = None
        field_type = self._form_field_type_at_point(raw_page, page_x, page_y)
        if field_type is None:
            field_type = self._last_mouse_down_field_type
        self._last_mouse_down_field_type = None
        self._set_current_page_index(page_index)
        modifier = self._event_modifier_flags(event, include_button=True)
        handled = pdfium_c.FORM_OnLButtonUp(
            self._form_handle, raw_page, modifier, page_x, page_y
        )
        # Always mark dirty and re-render so click-driven widget visuals update.
        self._mark_page_dirty(page_index)
        if handled and self._should_mark_modified_for_mouse_field(field_type):
            self._mark_modified()
        self._schedule_render()
        event.accept()

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if not self._form_handle or not self._doc:
            return
        hit = self._page_hit_test(event.position())
        if hit is None:
            return
        page_index, page_x, page_y = hit
        page = self._get_page(page_index)
        if page is None:
            return
        # Use raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        modifier = self._event_modifier_flags(event)
        handled = pdfium_c.FORM_OnMouseMove(
            self._form_handle, raw_page, modifier, page_x, page_y
        )
        if handled:
            self._mark_page_dirty(page_index)
            self._schedule_render()
            event.accept()

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                delta = event.pixelDelta().y()
            if delta != 0:
                steps = delta / 120.0
                factor = 1.1 ** steps
                self.set_zoom_factor(self._zoom * factor)
                event.accept()
                return
        event.ignore()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if not self._form_handle or not self._doc:
            return
        page = self._get_page(self._current_page_index)
        if page is None:
            return
        # Use raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        modifier = self._key_modifier_flags(event)
        key = event.key()
        handled = False
        fwl_key = _qt_key_to_fwl(key)
        if fwl_key is not None:
            handled = bool(
                pdfium_c.FORM_OnKeyDown(self._form_handle, raw_page, fwl_key, modifier)
            )
        text = event.text() or ""
        if text and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier)):
            for char in text:
                if char == "\x00":
                    continue
                handled = bool(
                    pdfium_c.FORM_OnChar(
                        self._form_handle, raw_page, ord(char), modifier
                    )
                ) or handled
        if handled:
            self._mark_page_dirty(self._current_page_index)
            self._mark_modified()
            self._schedule_render()
            event.accept()

    def keyReleaseEvent(self, event) -> None:  # type: ignore[override]
        if not self._form_handle or not self._doc:
            return
        page = self._get_page(self._current_page_index)
        if page is None:
            return
        # Use raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        modifier = self._key_modifier_flags(event)
        fwl_key = _qt_key_to_fwl(event.key())
        if fwl_key is None:
            return
        handled = pdfium_c.FORM_OnKeyUp(self._form_handle, raw_page, fwl_key, modifier)
        if handled:
            self._mark_page_dirty(self._current_page_index)
            self._schedule_render()
            event.accept()

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        super().focusOutEvent(event)
        if self._form_handle is None:
            return
        try:
            pdfium_c.FORM_ForceToKillFocus(self._form_handle)
        except Exception:
            return

    def _init_form_environment(self) -> None:
        if self._doc is None:
            return
        raw_doc = self._doc.raw if hasattr(self._doc, "raw") else self._doc
        form_type = pdfium_c.FPDF_GetFormType(raw_doc)
        if form_type == pdfium_c.FORMTYPE_XFA_FULL or form_type == pdfium_c.FORMTYPE_XFA_FOREGROUND:
            self.statusMessage.emit("XFA forms are not supported; rendering only.")

        form_info = pdfium_c.FPDF_FORMFILLINFO()
        form_info.version = 1

        self._callbacks = {
            "Release": _callback(None, (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO),), self._ffi_release),
            "FFI_Invalidate": _callback(
                None,
                (
                    ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO),
                    pdfium_c.FPDF_PAGE,
                    ctypes.c_double,
                    ctypes.c_double,
                    ctypes.c_double,
                    ctypes.c_double,
                ),
                self._ffi_invalidate,
            ),
            "FFI_SetCursor": _callback(
                None,
                (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO), ctypes.c_int),
                self._ffi_set_cursor,
            ),
            "FFI_SetTimer": _callback(
                ctypes.c_int,
                (
                    ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO),
                    ctypes.c_int,
                    pdfium_c.TimerCallback,
                ),
                self._ffi_set_timer,
            ),
            "FFI_KillTimer": _callback(
                None,
                (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO), ctypes.c_int),
                self._ffi_kill_timer,
            ),
            "FFI_GetPage": _callback(
                ctypes.c_void_p,
                (
                    ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO),
                    pdfium_c.FPDF_DOCUMENT,
                    ctypes.c_int,
                ),
                self._ffi_get_page,
            ),
            "FFI_GetCurrentPage": _callback(
                ctypes.c_void_p,
                (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO), pdfium_c.FPDF_DOCUMENT),
                self._ffi_get_current_page,
            ),
            "FFI_GetRotation": _callback(
                ctypes.c_int,
                (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO), pdfium_c.FPDF_PAGE),
                self._ffi_get_rotation,
            ),
            "FFI_ExecuteNamedAction": _callback(
                None,
                (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO), pdfium_c.FPDF_BYTESTRING),
                self._ffi_execute_named_action,
            ),
            "FFI_OnChange": _callback(
                None,
                (ctypes.POINTER(pdfium_c.FPDF_FORMFILLINFO),),
                self._ffi_on_change,
            ),
        }
        for name, cb in self._callbacks.items():
            if hasattr(form_info, name):
                setattr(form_info, name, cb)

        self._form_info = form_info
        self._form_handle = pdfium_c.FPDFDOC_InitFormFillEnvironment(
            raw_doc, ctypes.byref(form_info)
        )
        if not self._form_handle:
            self.statusMessage.emit("PDFium form environment failed to initialize.")
            return
        pdfium_c.FPDF_SetFormFieldHighlightColor(
            self._form_handle, pdfium_c.FPDF_FORMFIELD_UNKNOWN, 0x2D6CDF
        )
        pdfium_c.FPDF_SetFormFieldHighlightAlpha(self._form_handle, 0)
        # Skip JS actions - they can reset form field values on some PDFs
        # pdfium_c.FORM_DoDocumentJSAction(self._form_handle)
        # pdfium_c.FORM_DoDocumentOpenAction(self._form_handle)

    def _load_page(self, index: int) -> Optional[pdfium.PdfPage]:
        return self._get_page(index)

    def _get_page(self, index: int) -> Optional[pdfium.PdfPage]:
        if self._doc is None:
            return None
        if index in self._page_handles:
            return self._page_handles[index].page
        try:
            page = self._doc[index]
        except Exception:
            return None
        self._page_handles[index] = _PageHandle(page=page, index=index)
        # Get raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        try:
            pdfium_c.FORM_OnAfterLoadPage(raw_page, self._form_handle)
        except Exception:
            pass
        # Skip page-level JS actions - can interfere with form field state
        # Store raw pointer for lookup
        raw_ptr = int(ctypes.cast(raw_page, ctypes.c_void_p).value or 0)
        self._page_handle_by_ptr[raw_ptr] = index
        return page

    def _close_all_pages(self) -> None:
        for handle in list(self._page_handles.values()):
            try:
                raw_page = handle.page.raw if hasattr(handle.page, 'raw') else handle.page
                pdfium_c.FORM_OnBeforeClosePage(raw_page, self._form_handle)
            except Exception:
                pass
            close = getattr(handle.page, "close", None)
            if callable(close):
                close()
        self._page_handles.clear()
        self._page_handle_by_ptr.clear()

    def _ensure_page_sizes(self) -> None:
        if self._doc is None or self._page_sizes_pt:
            return
        raw_doc = self._doc.raw if hasattr(self._doc, "raw") else self._doc
        sizes: list[Tuple[float, float]] = []
        for index in range(self._page_count):
            width = 0.0
            height = 0.0
            # Prefer document-level size if available (does not require loading page)
            if hasattr(pdfium_c, "FPDF_GetPageSizeByIndexF"):
                try:
                    size = pdfium_c.FS_SIZEF()
                    ok = pdfium_c.FPDF_GetPageSizeByIndexF(
                        raw_doc, index, ctypes.byref(size)
                    )
                    if ok:
                        width = float(size.width)
                        height = float(size.height)
                except Exception:
                    pass
            # Load the page and ask for size via pypdfium2
            if width <= 0 or height <= 0:
                page = self._get_page(index)
                if page is not None:
                    try:
                        sz = page.get_size()
                        width = float(sz[0])
                        height = float(sz[1])
                    except Exception:
                        try:
                            raw_page = page.raw if hasattr(page, "raw") else page
                            width = float(pdfium_c.FPDF_GetPageWidthF(raw_page))
                            height = float(pdfium_c.FPDF_GetPageHeightF(raw_page))
                        except Exception:
                            pass
            sizes.append((width, height))
        self._page_sizes_pt = sizes

    def _rebuild_layout(self) -> None:
        if self._doc is None:
            self._page_rects = []
            return
        self._ensure_page_sizes()
        rects: list[QRectF] = []
        y_offset = 0.0
        max_width = 0.0
        widths_px: list[float] = []
        heights_px: list[float] = []
        for width_pt, height_pt in self._page_sizes_pt:
            width_px = max(1.0, width_pt * self._zoom)
            height_px = max(1.0, height_pt * self._zoom)
            widths_px.append(width_px)
            heights_px.append(height_px)
            y_offset += height_px + _PAGE_SPACING
            max_width = max(max_width, width_px)
        canvas_width = max(max_width, self._min_viewport_width)
        y_offset = 0.0
        for width_px, height_px in zip(widths_px, heights_px):
            x_offset = max(0.0, (canvas_width - width_px) / 2.0)
            rects.append(QRectF(x_offset, y_offset, width_px, height_px))
            y_offset += height_px + _PAGE_SPACING
        if rects:
            y_offset -= _PAGE_SPACING
        self._page_rects = rects
        self.resize(int(canvas_width), int(max(y_offset, 1.0)))

    def _render_visible_pages(self, force: bool = False) -> None:
        if self._doc is None:
            return
        if force:
            self._render_cache.clear()
        self.update()

    def _render_page(self, index: int, zoom_key: float, dpr_key: int) -> Optional[QImage]:
        if self._doc is None or index < 0 or index >= self._page_count:
            return None
        cache_key = (index, zoom_key, dpr_key)
        if cache_key in self._render_cache and index not in self._dirty_pages:
            return self._render_cache[cache_key]
        page = self._get_page(index)
        if page is None:
            page = self._load_page(index)
        if page is None:
            return None
        # Use raw page handle for PDFium calls
        raw_page = page.raw if hasattr(page, 'raw') else page
        if not self._page_sizes_pt:
            self._page_sizes_pt = [(0.0, 0.0)] * self._page_count
        width_pt, height_pt = self._page_sizes_pt[index]
        size_was_missing = width_pt <= 0 or height_pt <= 0
        if width_pt <= 0 or height_pt <= 0:
            # Try document-level size first if available
            if hasattr(pdfium_c, "FPDF_GetPageSizeByIndexF"):
                try:
                    raw_doc = self._doc.raw if hasattr(self._doc, "raw") else self._doc
                    size = pdfium_c.FS_SIZEF()
                    ok = pdfium_c.FPDF_GetPageSizeByIndexF(
                        raw_doc, index, ctypes.byref(size)
                    )
                    if ok:
                        width_pt, height_pt = float(size.width), float(size.height)
                except Exception:
                    pass
        if width_pt <= 0 or height_pt <= 0:
            try:
                size = page.get_size()
                width_pt, height_pt = float(size[0]), float(size[1])
            except Exception:
                try:
                    width_pt = float(pdfium_c.FPDF_GetPageWidthF(raw_page))
                    height_pt = float(pdfium_c.FPDF_GetPageHeightF(raw_page))
                except Exception:
                    pass
            self._page_sizes_pt[index] = (width_pt, height_pt)
        if size_was_missing and width_pt > 0 and height_pt > 0:
            self._rebuild_layout()
        if width_pt <= 0 or height_pt <= 0:
            return None
        dpr = max(1.0, float(dpr_key) / 100.0)
        width_px = max(1, int(round(width_pt * self._zoom * dpr)))
        height_px = max(1, int(round(height_pt * self._zoom * dpr)))
        bitmap = pdfium_c.FPDFBitmap_Create(width_px, height_px, 1)
        if not bitmap:
            return None
        pdfium_c.FPDFBitmap_FillRect(bitmap, 0, 0, width_px, height_px, 0xFFFFFFFF)
        render_flags = pdfium_c.FPDF_ANNOT | pdfium_c.FPDF_LCD_TEXT
        render_flags |= getattr(pdfium_c, "FPDF_RENDER_FORCEHALFTONE", 0)
        pdfium_c.FPDF_RenderPageBitmap(
            bitmap, raw_page, 0, 0, width_px, height_px, 0, render_flags
        )
        if self._form_handle is not None:
            pdfium_c.FPDF_FFLDraw(
                self._form_handle,
                bitmap,
                raw_page,
                0,
                0,
                width_px,
                height_px,
                0,
                render_flags,
            )
        buffer_ptr = pdfium_c.FPDFBitmap_GetBuffer(bitmap)
        stride = pdfium_c.FPDFBitmap_GetStride(bitmap)
        image: Optional[QImage] = None
        if buffer_ptr:
            image = QImage(
                buffer_ptr,
                width_px,
                height_px,
                stride,
                QImage.Format.Format_ARGB32,
            ).copy()
            image.setDevicePixelRatio(dpr)
            self._cache_image(cache_key, image)
        pdfium_c.FPDFBitmap_Destroy(bitmap)
        self._dirty_pages.discard(index)
        return image

    def _cache_image(self, key: Tuple[int, float, int], image: QImage) -> None:
        self._render_cache[key] = image
        self._render_cache.move_to_end(key)
        while len(self._render_cache) > _MAX_RENDER_CACHE:
            self._render_cache.popitem(last=False)

    def _effective_device_pixel_ratio(self) -> float:
        dpr = float(self.devicePixelRatioF())
        if dpr <= 0:
            return 1.0
        return dpr

    def _page_hit_test(self, pos: QPointF) -> Optional[Tuple[int, float, float]]:
        if not self._page_rects:
            return None
        for index, rect in enumerate(self._page_rects):
            if rect.contains(pos):
                page_x = (pos.x() - rect.left()) / self._zoom
                page_height_px = rect.height()
                page_y = (page_height_px - (pos.y() - rect.top())) / self._zoom
                return index, page_x, page_y
        return None

    def _event_modifier_flags(self, event, include_button: bool = True) -> int:
        flags = self._key_modifier_flags(event)
        buttons = event.buttons() if hasattr(event, "buttons") else Qt.MouseButton.NoButton
        if include_button and hasattr(event, "button") and event.button() == Qt.MouseButton.LeftButton:
            flags |= pdfium_c.FWL_EVENTFLAG_LeftButtonDown
        if buttons & Qt.MouseButton.LeftButton:
            flags |= pdfium_c.FWL_EVENTFLAG_LeftButtonDown
        if buttons & Qt.MouseButton.MiddleButton:
            flags |= pdfium_c.FWL_EVENTFLAG_MiddleButtonDown
        if buttons & Qt.MouseButton.RightButton:
            flags |= pdfium_c.FWL_EVENTFLAG_RightButtonDown
        return flags

    def _key_modifier_flags(self, event) -> int:
        flags = 0
        mods = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        if mods & Qt.KeyboardModifier.ShiftModifier:
            flags |= pdfium_c.FWL_EVENTFLAG_ShiftKey
        if mods & Qt.KeyboardModifier.ControlModifier:
            flags |= pdfium_c.FWL_EVENTFLAG_ControlKey
        if mods & Qt.KeyboardModifier.AltModifier:
            flags |= pdfium_c.FWL_EVENTFLAG_AltKey
        if mods & Qt.KeyboardModifier.MetaModifier:
            flags |= pdfium_c.FWL_EVENTFLAG_MetaKey
        return flags

    def _mark_page_dirty(self, index: int) -> None:
        self._dirty_pages.add(index)

    def _form_field_type_at_point(
        self, raw_page, page_x: float, page_y: float
    ) -> Optional[int]:
        if self._form_handle is None or not hasattr(pdfium_c, "FPDFPage_HasFormFieldAtPoint"):
            return None
        try:
            field_type = pdfium_c.FPDFPage_HasFormFieldAtPoint(
                self._form_handle, raw_page, page_x, page_y
            )
        except Exception:
            return None
        try:
            return int(field_type)
        except Exception:
            return None

    def _should_mark_modified_for_mouse_field(self, field_type: Optional[int]) -> bool:
        if field_type is None:
            return False
        return field_type in (
            pdfium_c.FPDF_FORMFIELD_CHECKBOX,
            pdfium_c.FPDF_FORMFIELD_RADIOBUTTON,
        )

    def _schedule_render(self) -> None:
        if self._pending_render:
            return
        self._pending_render = True
        QTimer.singleShot(0, self._flush_pending_render)

    def _flush_pending_render(self) -> None:
        self._pending_render = False
        self._render_visible_pages(force=True)

    def _cancel_pending_render(self) -> None:
        self._pending_render = False

    def _mark_modified(self) -> None:
        if self._loading:
            return  # Don't mark modified during document load
        if not self._modified:
            self._set_modified(True)

    def _set_modified(self, modified: bool) -> None:
        self._modified = modified
        self.unsavedChanged.emit(modified)

    def _commit_form_changes(self) -> None:
        if self._form_handle is None:
            return
        try:
            pdfium_c.FORM_ForceToKillFocus(self._form_handle)
        except Exception:
            pass
        # Note: Do NOT call _regenerate_form_appearances() - it corrupts checkboxes
        # pypdfium2's save() should handle form data correctly on its own

    def _regenerate_form_appearances(self) -> None:
        """Placeholder - appearance regeneration removed as it corrupted checkboxes."""
        pass

    def _ffi_release(self, _info) -> None:
        return

    def _ffi_invalidate(self, _info, page_ptr, _left, _top, _right, _bottom) -> None:
        # Find the page index from the raw pointer
        ptr_val = int(ctypes.cast(page_ptr, ctypes.c_void_p).value or 0) if page_ptr else 0
        page_index = self._page_handle_by_ptr.get(ptr_val, self._current_page_index)
        self._mark_page_dirty(page_index)
        self._schedule_render()

    def _ffi_set_cursor(self, _info, cursor_type: int) -> None:
        mapping = {
            pdfium_c.FXCT_ARROW: Qt.CursorShape.ArrowCursor,
            pdfium_c.FXCT_VBEAM: Qt.CursorShape.IBeamCursor,
            pdfium_c.FXCT_HAND: Qt.CursorShape.PointingHandCursor,
            pdfium_c.FXCT_HBEAM: Qt.CursorShape.SizeHorCursor,
            pdfium_c.FXCT_NESW: Qt.CursorShape.SizeBDiagCursor,
            pdfium_c.FXCT_NWSE: Qt.CursorShape.SizeFDiagCursor,
        }
        shape = mapping.get(cursor_type, Qt.CursorShape.ArrowCursor)
        self.setCursor(QCursor(shape))

    def _ffi_set_timer(self, _info, interval_ms: int, timer_cb) -> int:
        if interval_ms <= 0:
            return 0
        timer_id = self._next_timer_id
        self._next_timer_id += 1
        qt_timer = QTimer(self)
        qt_timer.setInterval(interval_ms)
        qt_timer.timeout.connect(lambda tid=timer_id: timer_cb(tid))
        qt_timer.start()
        self._timers[timer_id] = qt_timer
        return timer_id

    def _ffi_kill_timer(self, _info, timer_id: int) -> None:
        timer = self._timers.pop(timer_id, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def _ffi_get_page(self, _info, _doc, index: int):
        page = self._get_page(index)
        if page is None:
            return None
        return page.raw if hasattr(page, "raw") else page

    def _ffi_get_current_page(self, _info, _doc):
        page = self._get_page(self._current_page_index)
        if page is None:
            return None
        return page.raw if hasattr(page, "raw") else page

    def _ffi_get_rotation(self, _info, _page) -> int:
        return 0

    def _ffi_execute_named_action(self, _info, _action) -> None:
        return

    def _ffi_on_change(self, _info) -> None:
        self._mark_modified()

    def _clear_timers(self) -> None:
        for timer in self._timers.values():
            timer.stop()
            timer.deleteLater()
        self._timers.clear()

    def _set_current_page_index(self, index: int) -> None:
        if index != self._current_page_index:
            self._current_page_index = index
            self.pageChanged.emit(self._current_page_index + 1, self._page_count)

    def _update_current_page_from_visible(self, visible_rect) -> None:
        if not self._page_rects:
            return
        visible_top = visible_rect.top()
        for index, rect in enumerate(self._page_rects):
            if rect.bottom() >= visible_top:
                self._set_current_page_index(index)
                return


def _callback(restype, argtypes, func):
    cb = ctypes.CFUNCTYPE(restype, *argtypes)(func)
    return cb


def _qt_key_to_fwl(key: Qt.Key) -> Optional[int]:
    mapping = {
        Qt.Key.Key_Backspace: pdfium_c.FWL_VKEY_Back,
        Qt.Key.Key_Delete: pdfium_c.FWL_VKEY_Delete,
        Qt.Key.Key_Left: pdfium_c.FWL_VKEY_Left,
        Qt.Key.Key_Right: pdfium_c.FWL_VKEY_Right,
        Qt.Key.Key_Up: pdfium_c.FWL_VKEY_Up,
        Qt.Key.Key_Down: pdfium_c.FWL_VKEY_Down,
        Qt.Key.Key_Home: pdfium_c.FWL_VKEY_Home,
        Qt.Key.Key_End: pdfium_c.FWL_VKEY_End,
        Qt.Key.Key_PageUp: pdfium_c.FWL_VKEY_Prior,
        Qt.Key.Key_PageDown: pdfium_c.FWL_VKEY_Next,
        Qt.Key.Key_Tab: pdfium_c.FWL_VKEY_Tab,
        Qt.Key.Key_Return: pdfium_c.FWL_VKEY_Return,
        Qt.Key.Key_Enter: pdfium_c.FWL_VKEY_Return,
        Qt.Key.Key_Escape: pdfium_c.FWL_VKEY_Escape,
    }
    if key in mapping:
        return mapping[key]
    if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
        return pdfium_c.FWL_VKEY_0 + (key - Qt.Key.Key_0)
    if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
        return pdfium_c.FWL_VKEY_A + (key - Qt.Key.Key_A)
    return None
