from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QPoint, Qt, QEvent, QTimer
from PySide6.QtGui import QColor, QFontMetricsF, QKeyEvent, QKeySequence, QShortcut, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import QApplication, QLabel, QListWidget, QListWidgetItem, QTextEdit

from session_text_links import (
    LinkSuggestion,
    ParsedSessionLink,
    SUPPORTED_COMMANDS,
    SlashTrigger,
    detect_slash_trigger,
    find_markdown_link_at_position,
    iter_markdown_links,
    parse_dmt_url,
)


class SessionTextLinkController(QObject):
    _ESCAPED_SLASH_PROP = int(QTextFormat.Property.UserProperty) + 791

    def __init__(
        self,
        editor: QTextEdit,
        suggestion_provider: Callable[[str, str], list[LinkSuggestion]],
        link_activated: Callable[[ParsedSessionLink], bool],
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent or editor)
        self._editor: Optional[QTextEdit] = editor
        self._suggestion_provider = suggestion_provider
        self._link_activated = link_activated
        self._current_trigger: Optional[SlashTrigger] = None
        self._suggestions: list[LinkSuggestion] = []
        self._is_applying = False
        self._format_normalizing = False
        self._prefer_plain_after_link = False
        self._force_plain_next_text_input = False
        self._navigation_format_change_guard = False
        self._last_seen_underline: Optional[bool] = None
        self._recent_text_input = False
        self._mouse_press_pos: Optional[QPoint] = None
        self._mouse_press_anchor: str = ""
        self._mouse_dragged = False

        self._popup = QListWidget(editor)
        self._popup.setWindowFlags(
            Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint
        )
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popup.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._popup.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._popup.setObjectName("SessionTextLinkPopup")
        self._popup.setStyleSheet(
            """
            QListWidget#SessionTextLinkPopup {
                background-color: #0d1117;
                border: 1px solid #3b424b;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget#SessionTextLinkPopup::item {
                padding: 6px 8px;
                border-radius: 4px;
            }
            QListWidget#SessionTextLinkPopup::item:selected {
                background-color: #2d6cdf;
                color: #ffffff;
            }
            """
        )
        self._popup.itemClicked.connect(self._on_popup_item_clicked)

        self._command_hint_label = QLabel(editor.viewport())
        self._command_hint_label.setObjectName("SessionTextLinkCommandHint")
        self._command_hint_label.setStyleSheet(
            "QLabel#SessionTextLinkCommandHint { color: #8b949e; background: transparent; }"
        )
        self._command_hint_label.hide()

        editor.installEventFilter(self)
        editor.viewport().installEventFilter(self)
        editor.viewport().setMouseTracking(True)
        editor.textChanged.connect(self._refresh_popup)
        editor.cursorPositionChanged.connect(self._refresh_popup)
        editor.cursorPositionChanged.connect(self._normalize_typing_format_near_link)
        editor.currentCharFormatChanged.connect(self._on_current_char_format_changed)
        editor.destroyed.connect(self._on_editor_destroyed)
        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), editor)
        self._escape_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._escape_shortcut.activated.connect(self._on_escape_shortcut)

    def _on_editor_destroyed(self, _obj=None) -> None:
        self._editor = None
        self._recent_text_input = False
        self._mouse_press_pos = None
        self._mouse_press_anchor = ""
        self._mouse_dragged = False
        self._hide_popup()

    def _on_escape_shortcut(self) -> None:
        self._escape_current_trigger()
        self._hide_popup()

    def is_popup_visible(self) -> bool:
        return self._popup.isVisible()

    def activate_link_at_cursor(self) -> bool:
        if self._editor is None:
            return False
        cursor = self._editor.textCursor()
        try:
            href = str(cursor.charFormat().anchorHref() or "").strip()
        except Exception:
            href = ""
        if href:
            link = self._parse_href_link(href)
            if link is not None:
                return bool(self._link_activated(link))
        text = self._editor.toPlainText()
        link = find_markdown_link_at_position(text, cursor.position())
        if link is None:
            return False
        return bool(self._link_activated(link))

    def eventFilter(self, watched, event):  # type: ignore[override]
        editor = self._editor
        if editor is None:
            return False
        if watched is editor and event.type() == QEvent.Type.KeyPress:
            if self._handle_editor_keypress(event):
                return True
        try:
            viewport = editor.viewport()
        except RuntimeError:
            return False
        if watched is viewport and event.type() == QEvent.Type.KeyPress:
            if self._handle_editor_keypress(event):
                return True
        if watched is viewport and event.type() == QEvent.Type.MouseButtonPress:
            self._handle_editor_mouse_press(event)
            return False
        if watched is viewport and event.type() == QEvent.Type.MouseMove:
            self._handle_editor_mouse_move(event)
            return False
        if watched is viewport and event.type() == QEvent.Type.Leave:
            self._set_hover_cursor(is_link=False)
            return False
        if watched is viewport and event.type() == QEvent.Type.MouseButtonRelease:
            if self._handle_editor_mouse_release(event):
                return True
        return super().eventFilter(watched, event)

    def _handle_editor_keypress(self, event: QKeyEvent) -> bool:
        typed_text = str(event.text() or "")
        if typed_text:
            if self._editor is not None and self._force_plain_next_text_input:
                plain = QTextCharFormat(self._editor.currentCharFormat())
                plain.setAnchor(False)
                plain.setAnchorHref("")
                plain.setFontUnderline(False)
                plain.setForeground(self._editor.palette().text().color())
                self._set_editor_current_char_format(plain)
                self._force_plain_next_text_input = False
            if self._insert_text_safely_near_link(typed_text, event.modifiers()):
                return True
            if self._editor is not None and self._prefer_plain_after_link:
                fmt = QTextCharFormat(self._editor.currentCharFormat())
                fmt.setAnchor(False)
                fmt.setAnchorHref("")
                fmt.setFontUnderline(False)
                fmt.setForeground(self._editor.palette().text().color())
                self._set_editor_current_char_format(fmt)
                self._prefer_plain_after_link = False
            self._recent_text_input = True
        key = event.key()
        if key == Qt.Key.Key_Tab:
            if self._apply_command_completion():
                return True
            if self._popup.isVisible():
                row = self._popup.currentRow()
                if row < 0:
                    row = 0
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    row = (row - 1) % max(1, self._popup.count())
                else:
                    row = (row + 1) % max(1, self._popup.count())
                self._popup.setCurrentRow(row)
                return True
            return False
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if not self._popup.isVisible():
                self._refresh_popup()
            if self._popup.isVisible():
                return self._accept_popup_selection(self._popup.currentRow())
            return False
        if key == Qt.Key.Key_Space:
            if not self._popup.isVisible():
                self._refresh_popup()
            trigger = self._current_trigger
            if trigger is None:
                return False
            if not str(trigger.query or "").strip():
                return False
            if self._popup.isVisible():
                return self._accept_popup_selection(self._popup.currentRow())
            return False
        if key == Qt.Key.Key_Escape:
            self._escape_current_trigger()
            self._hide_popup()
            return True
        if key == Qt.Key.Key_Backspace and self._popup.isVisible():
            if self._current_trigger is not None and self._editor is not None:
                if self._editor.textCursor().position() <= (self._current_trigger.start + 1):
                    self._hide_popup()
            return False
        if key in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Home, Qt.Key.Key_End):
            self._navigation_format_change_guard = True
            QTimer.singleShot(0, self._normalize_typing_format_near_link)
        if not self._popup.isVisible():
            return False
        if key == Qt.Key.Key_Down:
            row = max(0, self._popup.currentRow()) + 1
            self._popup.setCurrentRow(min(self._popup.count() - 1, row))
            return True
        if key == Qt.Key.Key_Up:
            row = max(0, self._popup.currentRow()) - 1
            self._popup.setCurrentRow(max(0, row))
            return True
        return False

    def _insert_text_safely_near_link(self, text: str, modifiers: Qt.KeyboardModifiers) -> bool:
        if self._editor is None:
            return False
        if not text:
            return False
        blocked = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if bool(modifiers & blocked):
            return False
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            return False
        pos = cursor.position()
        left_anchor = self._is_anchor_char_index(pos - 1)
        right_anchor = self._is_anchor_char_index(pos)
        current = QTextCharFormat(self._editor.currentCharFormat())
        if not current.isAnchor() and left_anchor == right_anchor:
            return False
        cleaned = QTextCharFormat(current)
        cleaned.setAnchor(False)
        cleaned.setAnchorHref("")
        if self._force_plain_next_text_input or self._prefer_plain_after_link:
            cleaned.setForeground(self._editor.palette().text().color())
            cleaned.setFontUnderline(False)
            self._prefer_plain_after_link = False
            self._force_plain_next_text_input = False
        cursor.insertText(text, cleaned)
        self._editor.setTextCursor(cursor)
        self._set_editor_current_char_format(cleaned)
        self._recent_text_input = True
        return True

    def _mark_slash_as_escaped(self, position: int, *, restore_cursor_pos: Optional[int] = None) -> bool:
        if self._editor is None:
            return False
        text = self._editor.toPlainText()
        if position < 0 or position >= len(text):
            return False
        if text[position] != "/":
            return False
        cursor = self._editor.textCursor()
        mark = QTextCharFormat()
        mark.setProperty(self._ESCAPED_SLASH_PROP, True)
        cursor.setPosition(position)
        cursor.setPosition(position + 1, cursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(mark)
        cursor.clearSelection()
        target_pos = position + 1 if restore_cursor_pos is None else int(restore_cursor_pos)
        target_pos = max(0, min(target_pos, len(text)))
        cursor.setPosition(target_pos)
        self._editor.setTextCursor(cursor)
        return True

    def _escape_current_trigger(self) -> None:
        trigger = self._current_trigger
        cursor_pos = None
        if self._editor is not None:
            cursor_pos = self._editor.textCursor().position()
        if trigger is None and self._editor is not None:
            text = self._editor.toPlainText()
            cursor_pos = self._editor.textCursor().position()
            trigger = detect_slash_trigger(text, cursor_pos)
        if trigger is not None:
            self._mark_slash_as_escaped(trigger.start, restore_cursor_pos=cursor_pos)
            return
        if self._editor is None:
            return
        text = self._editor.toPlainText()
        cursor_pos = max(0, min(self._editor.textCursor().position(), len(text)))
        line_start = text.rfind("\n", 0, cursor_pos) + 1
        slash_index = text.rfind("/", line_start, cursor_pos)
        if slash_index < 0:
            return
        self._mark_slash_as_escaped(slash_index, restore_cursor_pos=cursor_pos)

    def _is_escaped_literal_slash(self, position: int) -> bool:
        if self._editor is None:
            return False
        text = self._editor.toPlainText()
        if position < 0 or position >= len(text):
            return False
        if text[position] != "/":
            return False
        cursor = self._editor.textCursor()
        cursor.setPosition(position)
        cursor.setPosition(position + 1, cursor.MoveMode.KeepAnchor)
        try:
            value = cursor.charFormat().property(self._ESCAPED_SLASH_PROP)
        except Exception:
            return False
        return bool(value)

    def _parse_href_link(
        self,
        href: str,
        *,
        label: str = "",
        start: int = 0,
        end: int = 0,
    ) -> Optional[ParsedSessionLink]:
        parsed = parse_dmt_url(href)
        if parsed is None:
            return None
        kind, target_id, collection_path = parsed
        return ParsedSessionLink(
            start=start,
            end=end,
            label=str(label or ""),
            url=href,
            kind=kind,
            target_id=target_id,
            collection_path=collection_path,
        )

    def _event_pos(self, event) -> QPoint:
        try:
            return event.position().toPoint()
        except Exception:
            return event.pos()

    def _drag_distance_threshold(self) -> int:
        app = QApplication.instance()
        if app is None:
            return 2
        try:
            return max(2, int(app.styleHints().startDragDistance()))
        except Exception:
            return 2

    def _set_hover_cursor(self, *, is_link: bool) -> None:
        if self._editor is None:
            return
        viewport = self._editor.viewport()
        shape = Qt.CursorShape.PointingHandCursor if is_link else Qt.CursorShape.IBeamCursor
        if viewport.cursor().shape() == shape:
            return
        viewport.setCursor(shape)

    def _is_anchor_char_index(self, index: int) -> bool:
        if self._editor is None:
            return False
        text = self._editor.toPlainText()
        if index < 0 or index >= len(text):
            return False
        probe = self._editor.textCursor()
        probe.setPosition(index)
        probe.setPosition(index + 1, probe.MoveMode.KeepAnchor)
        try:
            return bool(probe.charFormat().isAnchor())
        except Exception:
            return False

    def _normalize_typing_format_near_link(self) -> None:
        if self._editor is None:
            return
        if self._is_applying:
            return
        if self._recent_text_input:
            self._recent_text_input = False
            return
        cursor = self._editor.textCursor()
        if cursor.hasSelection():
            return
        text = self._editor.toPlainText()
        pos = max(0, min(cursor.position(), len(text)))
        left_anchor = self._is_anchor_char_index(pos - 1)
        right_anchor = self._is_anchor_char_index(pos)
        # Only strip link style at link boundaries (before/after link),
        # while preserving actual in-link editing behavior.
        if left_anchor == right_anchor:
            return
        self._prefer_plain_after_link = True
        fmt = QTextCharFormat(self._editor.currentCharFormat())
        fmt.setAnchor(False)
        fmt.setAnchorHref("")
        fmt.setFontUnderline(False)
        fmt.setForeground(self._editor.palette().text().color())
        self._set_editor_current_char_format(fmt)

    def _set_editor_current_char_format(self, fmt: QTextCharFormat) -> None:
        if self._editor is None:
            return
        if self._format_normalizing:
            return
        self._format_normalizing = True
        try:
            self._editor.setCurrentCharFormat(fmt)
        finally:
            self._format_normalizing = False

    def _on_current_char_format_changed(self, fmt: QTextCharFormat) -> None:
        if self._editor is None:
            return
        if self._is_applying or self._format_normalizing:
            return
        current_underline = bool(fmt.fontUnderline())
        if self._navigation_format_change_guard:
            self._navigation_format_change_guard = False
            return
        if self._force_plain_next_text_input and not self._recent_text_input:
            self._force_plain_next_text_input = False
        self._last_seen_underline = current_underline
        if not fmt.isAnchor():
            if self._prefer_plain_after_link:
                cleaned_plain = QTextCharFormat(fmt)
                cleaned_plain.setFontUnderline(False)
                cleaned_plain.setForeground(self._editor.palette().text().color())
                self._prefer_plain_after_link = False
                if (
                    cleaned_plain.fontUnderline() != fmt.fontUnderline()
                    or cleaned_plain.foreground().color() != fmt.foreground().color()
                ):
                    self._set_editor_current_char_format(cleaned_plain)
            return
        cleaned = QTextCharFormat(fmt)
        cleaned.setAnchor(False)
        cleaned.setAnchorHref("")
        if self._prefer_plain_after_link:
            cleaned.setFontUnderline(False)
            cleaned.setForeground(self._editor.palette().text().color())
            self._prefer_plain_after_link = False
        self._set_editor_current_char_format(cleaned)

    def _command_completion(self) -> Optional[tuple[int, int, str, str]]:
        if self._editor is None:
            return None
        text = self._editor.toPlainText()
        pos = self._editor.textCursor().position()
        line_start = text.rfind("\n", 0, pos) + 1
        segment = text[line_start:pos]
        if "/" not in segment:
            return None
        rel_slash = segment.rfind("/")
        start = line_start + rel_slash
        if start > 0 and not text[start - 1].isspace():
            return None
        if start > 0 and text[start - 1] == "/":
            return None
        token = text[start + 1 : pos]
        if not token or any(ch.isspace() for ch in token):
            return None
        partial = token.strip().lower()
        matches = [cmd for cmd in sorted(SUPPORTED_COMMANDS) if cmd.startswith(partial)]
        if not matches:
            return None
        best = sorted(matches, key=lambda cmd: (len(cmd), cmd))[0]
        if best == partial:
            return None
        suffix = best[len(partial) :]
        if not suffix:
            return None
        return start, pos, best, suffix

    def _position_command_hint(self) -> None:
        if self._editor is None:
            return
        rect = self._editor.cursorRect(self._editor.textCursor())
        x = rect.right() + 1
        y = rect.top()
        self._command_hint_label.move(x, y)

    def _refresh_command_hint(self) -> None:
        completion = self._command_completion()
        if completion is None:
            self._command_hint_label.hide()
            return
        _, _, _, suffix = completion
        self._command_hint_label.setText(suffix)
        self._command_hint_label.adjustSize()
        self._position_command_hint()
        self._command_hint_label.show()

    def _apply_command_completion(self) -> bool:
        if self._editor is None:
            return False
        completion = self._command_completion()
        if completion is None:
            return False
        start, end, command, _suffix = completion
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
        cursor.insertText(f"/{command}")
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)
        self._command_hint_label.hide()
        self._refresh_popup()
        return True

    def _href_at_pos(self, pos: QPoint) -> str:
        if self._editor is None:
            return ""
        href = ""
        try:
            href = str(self._editor.anchorAt(pos) or "").strip()
        except Exception:
            href = ""
        if href:
            return href
        try:
            cursor = self._editor.cursorForPosition(pos)
            text = self._editor.toPlainText()
            index = cursor.position()
            if 0 <= index < len(text):
                probe = self._editor.textCursor()
                probe.setPosition(index)
                probe.setPosition(index + 1, probe.MoveMode.KeepAnchor)
                fmt = probe.charFormat()
                if fmt.isAnchor():
                    href = str(fmt.anchorHref() or "").strip()
                else:
                    href = ""
            else:
                href = ""
        except Exception:
            href = ""
        return href

    def _href_for_index(self, index: int) -> str:
        if self._editor is None:
            return ""
        text = self._editor.toPlainText()
        if index < 0 or index >= len(text):
            return ""
        probe = self._editor.textCursor()
        probe.setPosition(index)
        probe.setPosition(index + 1, probe.MoveMode.KeepAnchor)
        fmt = probe.charFormat()
        if not fmt.isAnchor():
            return ""
        return str(fmt.anchorHref() or "").strip()

    def _anchor_index_at_pos(self, pos: QPoint, href: str) -> Optional[int]:
        if self._editor is None:
            return None
        cursor = self._editor.cursorForPosition(pos)
        index = cursor.position()
        for candidate in (index, index - 1):
            if self._href_for_index(candidate) == href:
                return candidate
        return None

    def _anchor_segment_bounds(self, index: int, href: str) -> Optional[tuple[int, int]]:
        if self._editor is None:
            return None
        text = self._editor.toPlainText()
        if index < 0 or index >= len(text):
            return None
        if self._href_for_index(index) != href:
            return None
        start = index
        end = index
        while start - 1 >= 0 and self._href_for_index(start - 1) == href:
            start -= 1
        while end + 1 < len(text) and self._href_for_index(end + 1) == href:
            end += 1
        return start, end

    def _half_char_width(self, index: int) -> float:
        if self._editor is None:
            return 0.5
        text = self._editor.toPlainText()
        if index < 0 or index >= len(text):
            return 0.5
        probe = self._editor.textCursor()
        probe.setPosition(index)
        probe.setPosition(index + 1, probe.MoveMode.KeepAnchor)
        fmt = probe.charFormat()
        font = fmt.font() if fmt.font().family() else self._editor.font()
        metrics = QFontMetricsF(font)
        glyph = text[index]
        width = float(metrics.horizontalAdvance(glyph))
        if width <= 0.0:
            width = 1.0
        return width / 2.0

    def _clickable_href_at_pos(self, pos: QPoint) -> str:
        href = self._href_at_pos(pos)
        if not href:
            return ""
        if self._editor is None:
            return href
        anchor_index = self._anchor_index_at_pos(pos, href)
        if anchor_index is None:
            return ""
        bounds = self._anchor_segment_bounds(anchor_index, href)
        if bounds is None:
            return ""
        start, end = bounds
        start_cursor = self._editor.textCursor()
        start_cursor.setPosition(start)
        end_cursor = self._editor.textCursor()
        end_cursor.setPosition(end)
        start_left = float(self._editor.cursorRect(start_cursor).x())
        end_left = float(self._editor.cursorRect(end_cursor).x())
        left_bound = start_left + self._half_char_width(start)
        right_bound = end_left + self._half_char_width(end)
        if right_bound < left_bound:
            return ""
        x = float(pos.x())
        if x < left_bound or x > right_bound:
            return ""
        return href

    def _update_hover_cursor(self, pos: QPoint) -> None:
        href = self._clickable_href_at_pos(pos)
        self._set_hover_cursor(is_link=bool(href))

    def _handle_editor_mouse_press(self, event) -> None:
        if self._editor is None:
            return
        pos = self._event_pos(event)
        self._update_hover_cursor(pos)
        if event.button() != Qt.MouseButton.LeftButton:
            self._mouse_press_pos = None
            self._mouse_press_anchor = ""
            self._mouse_dragged = False
            return
        self._mouse_press_pos = pos
        self._mouse_press_anchor = self._clickable_href_at_pos(pos)
        self._mouse_dragged = False

    def _handle_editor_mouse_move(self, event) -> None:
        pos = self._event_pos(event)
        self._update_hover_cursor(pos)
        if self._mouse_press_pos is None:
            return
        if (pos - self._mouse_press_pos).manhattanLength() >= self._drag_distance_threshold():
            self._mouse_dragged = True

    def _handle_editor_mouse_release(self, event) -> bool:
        if self._editor is None:
            return False
        pos = self._event_pos(event)
        self._update_hover_cursor(pos)
        if event.button() != Qt.MouseButton.LeftButton:
            self._mouse_press_pos = None
            self._mouse_press_anchor = ""
            self._mouse_dragged = False
            return False
        had_selection = self._editor.textCursor().hasSelection()
        had_press = self._mouse_press_pos is not None
        dragged = self._mouse_dragged
        if self._mouse_press_pos is not None:
            distance = (pos - self._mouse_press_pos).manhattanLength()
            dragged = dragged or distance >= self._drag_distance_threshold()
        press_anchor = self._mouse_press_anchor
        self._mouse_press_pos = None
        self._mouse_press_anchor = ""
        self._mouse_dragged = False
        if had_selection or dragged or not had_press:
            return False
        href = self._clickable_href_at_pos(pos)
        if href:
            if not press_anchor or press_anchor != href:
                return False
            link = self._parse_href_link(href)
            if link is not None:
                return bool(self._link_activated(link))
        if press_anchor or self._href_at_pos(pos):
            return False
        cursor = self._editor.cursorForPosition(pos)
        if self._editor.textCursor().hasSelection():
            return False
        link = find_markdown_link_at_position(self._editor.toPlainText(), cursor.position())
        if link is None:
            return False
        position = cursor.position()
        if position <= link.start or position >= (link.end - 1):
            return False
        return bool(self._link_activated(link))

    def _on_popup_item_clicked(self, item: QListWidgetItem) -> None:
        row = self._popup.row(item)
        self._accept_popup_selection(row)

    def _accept_popup_selection(self, row: int) -> bool:
        if self._editor is None:
            return False
        if row < 0 and self._suggestions:
            row = 0
        if row < 0 or row >= len(self._suggestions):
            return False
        if self._current_trigger is None:
            return False
        suggestion = self._suggestions[row]
        trigger = self._current_trigger
        cursor = self._editor.textCursor()
        base_fmt = QTextCharFormat(self._editor.currentCharFormat())
        self._is_applying = True
        try:
            cursor.beginEditBlock()
            cursor.setPosition(trigger.start)
            cursor.setPosition(trigger.end, cursor.MoveMode.KeepAnchor)
            link_text = str(suggestion.link_text or suggestion.display_label or "").strip()
            href = str(suggestion.href or "").strip()
            if (not href or not link_text) and suggestion.markdown:
                parsed = iter_markdown_links(suggestion.markdown)
                if parsed:
                    href = href or parsed[0].url
                    if not link_text:
                        link_text = parsed[0].label or suggestion.display_label
            if link_text and href:
                fmt = QTextCharFormat(base_fmt)
                fmt.setAnchor(True)
                fmt.setAnchorHref(href)
                fmt.setFontUnderline(True)
                fmt.setForeground(QColor("#58a6ff"))
                cursor.insertText(link_text, fmt)
                reset_fmt = QTextCharFormat(base_fmt)
                reset_fmt.setAnchor(False)
                reset_fmt.setAnchorHref("")
                reset_fmt.setForeground(self._editor.palette().text().color())
                if not base_fmt.fontUnderline():
                    reset_fmt.setFontUnderline(False)
                cursor.setCharFormat(reset_fmt)
                cursor.mergeCharFormat(reset_fmt)
                self._editor.setCurrentCharFormat(reset_fmt)
                self._editor.mergeCurrentCharFormat(reset_fmt)
            elif suggestion.markdown:
                cursor.insertText(suggestion.markdown)
            elif link_text:
                cursor.insertText(link_text)
            cursor.endEditBlock()
            self._editor.setTextCursor(cursor)
        finally:
            self._is_applying = False
        self._force_plain_next_text_input = True
        self._last_seen_underline = False
        self._normalize_typing_format_near_link()
        self._hide_popup()
        return True

    def _refresh_popup(self) -> None:
        if self._editor is None:
            return
        if self._is_applying:
            return
        text = self._editor.toPlainText()
        cursor_pos = self._editor.textCursor().position()
        trigger = detect_slash_trigger(text, cursor_pos)
        self._current_trigger = trigger
        self._refresh_command_hint()
        if trigger is None:
            self._hide_popup()
            return
        if self._is_escaped_literal_slash(trigger.start):
            self._hide_popup()
            return

        suggestions = self._suggestion_provider(trigger.command, trigger.query)
        self._suggestions = suggestions
        if not suggestions:
            self._hide_popup()
            return

        self._popup.blockSignals(True)
        self._popup.clear()
        for suggestion in suggestions:
            item = QListWidgetItem(suggestion.display_label)
            self._popup.addItem(item)
        self._popup.setCurrentRow(0)
        self._popup.blockSignals(False)
        self._position_popup()
        self._popup.show()
        self._popup.raise_()

    def _position_popup(self) -> None:
        if self._editor is None:
            return
        rect = self._editor.cursorRect(self._editor.textCursor())
        origin = self._editor.viewport().mapToGlobal(rect.bottomLeft())
        x = origin.x()
        y = origin.y() + 4
        width = max(260, min(420, int(self._editor.width() * 0.6)))
        row_height = self._popup.sizeHintForRow(0) if self._popup.count() else 24
        visible_rows = min(8, max(1, self._popup.count()))
        height = (row_height * visible_rows) + 10
        self._popup.setGeometry(x, y, width, height)

    def _hide_popup(self) -> None:
        self._popup.hide()
        self._popup.clear()
        self._suggestions = []
        self._current_trigger = None
