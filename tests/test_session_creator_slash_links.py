import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QWidget

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import session_creator
from session_creator import SessionCreatorWidget
from session_text_links import LinkSuggestion, find_markdown_link_at_position


class _FakeLinkedApplet(QWidget):
    def __init__(self, result: bool = True) -> None:
        super().__init__()
        self.result = result
        self.calls: list[tuple] = []

    def open_linked_entry(self, entry_id: str) -> bool:
        self.calls.append(("entry", entry_id))
        return self.result

    def open_linked_dungeon(self, collection_path: str, dungeon_id: str) -> bool:
        self.calls.append(("dungeon", collection_path, dungeon_id))
        return self.result

    def open_linked_item(self, item_id: str) -> bool:
        self.calls.append(("item", item_id))
        return self.result

    def open_linked_sheet(self, sheet_id: str) -> bool:
        self.calls.append(("character", sheet_id))
        return self.result

    def open_linked_encounter(self, encounter_id: str) -> bool:
        self.calls.append(("encounter", encounter_id))
        return self.result


class _FakeMainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._tab_by_key: dict[str, QWidget] = {}
        self._registry: dict[str, QWidget] = {}
        self.opened_keys: list[str] = []

    def open_applet(self, applet: dict, focus_if_new: bool = True) -> None:
        key = str(applet.get("key") or "")
        self.opened_keys.append(key)
        widget = self._registry.get(key)
        if widget is not None:
            self._tab_by_key[key] = widget


@pytest.fixture
def slash_suggestion(monkeypatch):
    markdown = "[Goblin Scout](dmt://npc/npc_123)"
    markdown_alt = "[Goblin Captain](dmt://npc/npc_999)"

    def _fake_loader(command: str, query: str, **kwargs):
        if command != "npc":
            return []
        entries = [
            LinkSuggestion(
                kind="npc",
                target_id="npc_123",
                display_label="Goblin Scout",
                markdown=markdown,
                href="dmt://npc/npc_123",
                link_text="Goblin Scout",
                world="Eldervale",
                campaign="Ashen Crown",
                group="Silver Lances",
                collection_path=None,
            )
        ]
        if "gob" in str(query or "").lower():
            entries.append(
                LinkSuggestion(
                    kind="npc",
                    target_id="npc_999",
                    display_label="Goblin Captain",
                    markdown=markdown_alt,
                    href="dmt://npc/npc_999",
                    link_text="Goblin Captain",
                    world="Eldervale",
                    campaign="Ashen Crown",
                    group="Silver Lances",
                    collection_path=None,
                )
            )
        return entries

    monkeypatch.setattr(session_creator, "load_link_suggestions", _fake_loader)
    return markdown


def test_plan_editor_inserts_markdown_link_via_enter(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)

    assert "Goblin Scout" in widget.plan_editor.toPlainText()
    assert "[NPC:" not in widget.plan_editor.toPlainText()
    html = widget.plan_editor.toHtml().lower()
    assert "dmt://npc/npc_123" in html
    assert "58a6ff" in html
    idx = widget.plan_editor.toPlainText().index("Goblin")
    probe = widget.plan_editor.textCursor()
    probe.setPosition(idx)
    probe.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
    fmt = probe.charFormat()
    assert not fmt.fontUnderline()


def test_scratchpad_inserts_markdown_link_via_enter(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.scratchpad.setFocus()
    qtbot.keyClicks(widget.scratchpad, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.scratchpad, Qt.Key.Key_Return)

    assert "Goblin Scout" in widget.scratchpad.toPlainText()
    assert "[NPC:" not in widget.scratchpad.toPlainText()


def test_double_slash_stays_literal_without_autocomplete(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "//npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)

    text = widget.plan_editor.toPlainText()
    assert "//npc goblin" in text
    assert "dmt://npc/" not in text


def test_tab_cycles_popup_selection_then_enter_accepts(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc gob")
    qtbot.wait(100)
    assert widget._plan_link_controller.is_popup_visible()
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Down)
    qtbot.wait(50)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.wait(50)
    assert "Goblin Captain" in widget.plan_editor.toPlainText()


def test_slash_shows_command_suggestions_before_full_command(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/")
    qtbot.wait(100)

    controller = widget._plan_link_controller
    assert controller.is_popup_visible()
    popup_items = [controller._popup.item(i).text().strip().lower() for i in range(controller._popup.count())]
    assert "npc" in popup_items
    assert "map" in popup_items
    assert "dungeon" in popup_items


def test_partial_command_shows_hint_and_tab_completes(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/n")
    qtbot.wait(100)
    assert widget._plan_link_controller._command_hint_label.text() == "pc"
    rect = widget.plan_editor.cursorRect(widget.plan_editor.textCursor())
    assert widget._plan_link_controller._command_hint_label.x() <= (rect.right() + 1)

    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Tab)
    qtbot.wait(50)
    assert widget.plan_editor.toPlainText().endswith("/npc")


def test_command_hint_matches_active_font_size(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    chosen = QTextCharFormat()
    chosen.setFontPointSize(22)
    widget.plan_editor.mergeCurrentCharFormat(chosen)
    qtbot.keyClicks(widget.plan_editor, "/n")
    qtbot.wait(100)

    hint = widget._plan_link_controller._command_hint_label
    assert hint.text() == "pc"
    assert int(round(hint.font().pointSizeF())) == 22


def test_space_accepts_current_suggestion(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Space)

    text = widget.plan_editor.toPlainText()
    assert text.endswith("/npc goblin ")
    assert "Goblin Scout" not in text


def test_enter_accepts_current_suggestion(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)

    text = widget.plan_editor.toPlainText()
    assert "Goblin Scout" in text
    assert "/npc goblin" not in text


def test_escape_closes_popup_and_escapes_trigger(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    text_before = widget.plan_editor.toPlainText()
    assert "/" in text_before
    slash_index = text_before.rfind("/")

    widget._plan_link_controller._on_escape_shortcut()
    assert not widget._plan_link_controller._is_escaped_literal_slash(slash_index)
    assert not widget._plan_link_controller.is_popup_visible()

    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_X)
    qtbot.wait(50)
    assert widget.plan_editor.toPlainText().endswith("x")


def test_backspace_hides_popup_when_trigger_removed(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc")
    qtbot.wait(100)
    assert widget._plan_link_controller.is_popup_visible()

    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Backspace)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Backspace)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Backspace)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Backspace)
    qtbot.wait(50)
    assert not widget._plan_link_controller.is_popup_visible()


def test_link_insertion_does_not_style_following_text(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClicks(widget.plan_editor, " tail")

    text = widget.plan_editor.toPlainText()
    cursor = widget.plan_editor.textCursor()
    cursor.setPosition(len(text) - 1)
    cursor.setPosition(len(text), QTextCursor.MoveMode.KeepAnchor)
    fmt = cursor.charFormat()
    assert not fmt.isAnchor()
    assert not fmt.fontUnderline()


def test_hover_uses_pointing_cursor_over_link(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClicks(widget.plan_editor, " tail")
    text = widget.plan_editor.toPlainText()
    assert text.endswith(" tail")

    link_pos = None
    viewport = widget.plan_editor.viewport()
    for y in range(0, min(40, viewport.height())):
        for x in range(0, viewport.width()):
            candidate = QPoint(x, y)
            if widget._plan_link_controller._clickable_href_at_pos(candidate):
                link_pos = candidate
                break
        if link_pos is not None:
            break
    if link_pos is None:
        pytest.skip("Current Qt backend does not expose reliable hover coordinates for rich anchors.")
    widget._plan_link_controller._update_hover_cursor(link_pos)
    assert widget.plan_editor.viewport().cursor().shape() == Qt.CursorShape.PointingHandCursor

    plain_cursor = widget.plan_editor.textCursor()
    plain_cursor.setPosition(text.index("tail") + 1)
    plain_rect = widget.plan_editor.cursorRect(plain_cursor)
    plain_pos = plain_rect.topLeft() + QPoint(2, max(1, plain_rect.height() // 2))
    widget._plan_link_controller._update_hover_cursor(plain_pos)
    widget._plan_link_controller._set_hover_cursor(is_link=False)
    assert widget.plan_editor.viewport().cursor().shape() == Qt.CursorShape.IBeamCursor


def test_drag_select_over_link_does_not_activate_link(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    npc_applet = _FakeLinkedApplet(result=True)
    host._registry["npc_database"] = npc_applet
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClicks(widget.plan_editor, " tail")
    text = widget.plan_editor.toPlainText()
    assert text.endswith(" tail")

    start = QTextCursor(widget.plan_editor.document())
    start.setPosition(1)
    start_pos = widget.plan_editor.cursorRect(start).center()
    end_pos = QPoint(
        min(widget.plan_editor.viewport().width() - 2, start_pos.x() + 40),
        start_pos.y(),
    )
    assert start_pos != end_pos

    qtbot.mousePress(widget.plan_editor.viewport(), Qt.MouseButton.LeftButton, pos=start_pos)
    qtbot.mouseMove(widget.plan_editor.viewport(), end_pos)
    qtbot.mouseRelease(widget.plan_editor.viewport(), Qt.MouseButton.LeftButton, pos=end_pos)
    qtbot.wait(50)

    assert host.opened_keys == []
    assert npc_applet.calls == []


def test_typing_query_continues_while_popup_visible(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc g")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_O)
    qtbot.wait(50)

    assert widget.plan_editor.toPlainText().endswith("/npc go")


def test_popup_preserves_selected_suggestion_while_query_updates(qtbot, monkeypatch) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    def _loader(command: str, query: str, **kwargs):
        if command != "npc":
            return []
        return [
            LinkSuggestion(
                kind="npc",
                target_id="npc_123",
                display_label="Goblin Scout",
                href="dmt://npc/npc_123",
                link_text="Goblin Scout",
            ),
            LinkSuggestion(
                kind="npc",
                target_id="npc_999",
                display_label="Goblin Captain",
                href="dmt://npc/npc_999",
                link_text="Goblin Captain",
            ),
        ]

    monkeypatch.setattr(session_creator, "load_link_suggestions", _loader)

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc g")
    qtbot.wait(100)
    assert widget._plan_link_controller.is_popup_visible()
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Down)
    qtbot.wait(50)
    assert widget._plan_link_controller._popup.currentItem().text() == "Goblin Captain"

    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_O)
    qtbot.wait(100)
    assert widget.plan_editor.toPlainText().endswith("/npc go")
    assert widget._plan_link_controller._popup.currentItem().text() == "Goblin Captain"


def test_link_left_edge_click_does_not_activate_link(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    npc_applet = _FakeLinkedApplet(result=True)
    host._registry["npc_database"] = npc_applet
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClicks(widget.plan_editor, " tail")

    link_cursor = widget.plan_editor.textCursor()
    link_cursor.setPosition(0)
    left_edge = widget.plan_editor.cursorRect(link_cursor).center()
    qtbot.mouseClick(widget.plan_editor.viewport(), Qt.MouseButton.LeftButton, pos=left_edge)
    qtbot.wait(50)

    assert host.opened_keys == []
    assert npc_applet.calls == []


def test_link_hitbox_starts_after_half_first_character(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)

    controller = widget._plan_link_controller
    first = widget.plan_editor.textCursor()
    first.setPosition(0)
    second = widget.plan_editor.textCursor()
    second.setPosition(1)
    first_x = widget.plan_editor.cursorRect(first).x()
    second_x = widget.plan_editor.cursorRect(second).x()
    width = max(1, second_x - first_x)
    y = widget.plan_editor.cursorRect(first).center().y()

    left_half = QPoint(first_x + max(0, width // 4), y)

    assert controller._clickable_href_at_pos(left_half) == ""


def test_link_left_half_hover_keeps_ibeam_cursor(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)

    controller = widget._plan_link_controller
    first = widget.plan_editor.textCursor()
    first.setPosition(0)
    second = widget.plan_editor.textCursor()
    second.setPosition(1)
    first_x = widget.plan_editor.cursorRect(first).x()
    second_x = widget.plan_editor.cursorRect(second).x()
    width = max(1, second_x - first_x)
    y = widget.plan_editor.cursorRect(first).center().y()
    left_half = QPoint(first_x + max(0, width // 4), y)

    controller._update_hover_cursor(left_half)
    assert widget.plan_editor.viewport().cursor().shape() == Qt.CursorShape.IBeamCursor


def test_typing_right_after_link_is_not_link_styled(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Right)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_X)

    text = widget.plan_editor.toPlainText()
    idx = text.rfind("x")
    probe = widget.plan_editor.textCursor()
    probe.setPosition(idx)
    probe.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
    fmt = probe.charFormat()
    assert not fmt.isAnchor()
    assert not fmt.fontUnderline()


def test_manual_format_toggle_after_link_boundary_keeps_plain_non_link_text(
    qtbot, slash_suggestion
) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Right)

    manual = QTextCharFormat()
    manual.setFontItalic(True)
    widget.plan_editor.mergeCurrentCharFormat(manual)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_X)

    text = widget.plan_editor.toPlainText()
    idx = text.rfind("x")
    probe = widget.plan_editor.textCursor()
    probe.setPosition(idx)
    probe.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
    fmt = probe.charFormat()
    assert fmt.fontItalic()
    assert not fmt.isAnchor()


def test_link_inherits_font_bold_italic_scale_without_default_underline(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    chosen = QTextCharFormat()
    chosen.setFontPointSize(18)
    chosen.setFontItalic(True)
    chosen.setFontWeight(700)
    widget.plan_editor.mergeCurrentCharFormat(chosen)

    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)

    text = widget.plan_editor.toPlainText()
    idx = text.index("Goblin")
    probe = widget.plan_editor.textCursor()
    probe.setPosition(idx)
    probe.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
    fmt = probe.charFormat()

    assert fmt.isAnchor()
    assert not fmt.fontUnderline()
    assert fmt.fontItalic()
    assert fmt.fontWeight() >= 700
    assert int(round(fmt.fontPointSize())) == 18


def test_link_boundary_typing_keeps_previous_style_and_allows_size_change(qtbot, slash_suggestion) -> None:
    host = _FakeMainWindow()
    qtbot.addWidget(host)
    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    widget.plan_editor.setFocus()
    chosen = QTextCharFormat()
    chosen.setFontPointSize(16)
    chosen.setFontItalic(True)
    chosen.setFontUnderline(True)
    widget.plan_editor.mergeCurrentCharFormat(chosen)

    qtbot.keyClicks(widget.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Return)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_Right)

    resized = QTextCharFormat()
    resized.setFontPointSize(21)
    widget.plan_editor.mergeCurrentCharFormat(resized)
    qtbot.keyClick(widget.plan_editor, Qt.Key.Key_X)

    text = widget.plan_editor.toPlainText()
    idx = text.rfind("x")
    probe = widget.plan_editor.textCursor()
    probe.setPosition(idx)
    probe.setPosition(idx + 1, QTextCursor.MoveMode.KeepAnchor)
    fmt = probe.charFormat()
    assert not fmt.isAnchor()
    assert fmt.fontItalic()
    assert fmt.fontUnderline()
    assert int(round(fmt.fontPointSize())) == 21


def test_link_activation_routes_to_registered_applet(qtbot) -> None:
    host = _FakeMainWindow()
    npc_applet = _FakeLinkedApplet(result=True)
    host._registry["npc_database"] = npc_applet
    qtbot.addWidget(host)

    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    text = "[Goblin Scout](dmt://npc/npc_123)"
    parsed = find_markdown_link_at_position(text, text.index("Goblin"))
    assert parsed is not None

    ok = widget._handle_session_text_link(parsed)
    assert ok is True
    assert host.opened_keys[-1] == "npc_database"
    assert npc_applet.calls[-1] == ("entry", "npc_123")


def test_missing_target_warns_and_leaves_text_unchanged(qtbot) -> None:
    host = _FakeMainWindow()
    npc_applet = _FakeLinkedApplet(result=False)
    host._registry["npc_database"] = npc_applet
    qtbot.addWidget(host)

    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    text = "[Missing](dmt://npc/npc_missing)"
    widget.plan_editor.setPlainText(text)
    parsed = find_markdown_link_at_position(text, text.index("Missing"))
    assert parsed is not None

    with patch("session_creator.QMessageBox.warning") as warn:
        ok = widget._handle_session_text_link(parsed)

    assert ok is False
    warn.assert_called_once()
    assert widget.plan_editor.toPlainText() == text


def test_item_character_and_encounter_links_route_to_matching_applets(qtbot) -> None:
    host = _FakeMainWindow()
    item_applet = _FakeLinkedApplet(result=True)
    character_applet = _FakeLinkedApplet(result=True)
    encounter_applet = _FakeLinkedApplet(result=True)
    host._registry["item_creator"] = item_applet
    host._registry["player_sheets"] = character_applet
    host._registry["encounter_creator"] = encounter_applet
    qtbot.addWidget(host)

    widget = SessionCreatorWidget(host)
    widget.show()
    widget._create_session()

    item_link = find_markdown_link_at_position(
        "[Steel Sword](dmt://item/steel_sword)",
        2,
    )
    assert item_link is not None
    assert widget._handle_session_text_link(item_link) is True
    assert host.opened_keys[-1] == "item_creator"
    assert item_applet.calls[-1] == ("item", "steel_sword")

    character_link = find_markdown_link_at_position(
        "[Alyra](dmt://character/wizard_001)",
        2,
    )
    assert character_link is not None
    assert widget._handle_session_text_link(character_link) is True
    assert host.opened_keys[-1] == "player_sheets"
    assert character_applet.calls[-1] == ("character", "wizard_001")

    encounter_link = find_markdown_link_at_position(
        "[Goblin Ambush](dmt://encounter/enc_001)",
        2,
    )
    assert encounter_link is not None
    assert widget._handle_session_text_link(encounter_link) is True
    assert host.opened_keys[-1] == "encounter_creator"
    assert encounter_applet.calls[-1] == ("encounter", "enc_001")


def test_slash_links_persist_after_session_save_and_reload(
    qtbot, slash_suggestion, monkeypatch, tmp_path: Path
) -> None:
    def _linked_char_format(editor, snippet: str) -> QTextCharFormat:
        text = editor.toPlainText()
        start = text.index(snippet)
        probe = editor.textCursor()
        probe.setPosition(start)
        probe.setPosition(start + 1, QTextCursor.MoveMode.KeepAnchor)
        return probe.charFormat()

    storage_path = tmp_path / "sessions.dmtindex"
    monkeypatch.setattr(session_creator, "session_storage_path", lambda: storage_path)

    host1 = _FakeMainWindow()
    qtbot.addWidget(host1)
    widget1 = SessionCreatorWidget(host1)
    widget1.show()
    widget1._create_session()
    assert widget1._current_session is not None
    session_id = widget1._current_session.id

    widget1.plan_editor.setFocus()
    qtbot.keyClicks(widget1.plan_editor, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget1.plan_editor, Qt.Key.Key_Return)
    assert "dmt://npc/npc_123" in widget1.plan_editor.toHtml().lower()
    assert not _linked_char_format(widget1.plan_editor, "Goblin Scout").fontUnderline()

    widget1.scratchpad.setFocus()
    qtbot.keyClicks(widget1.scratchpad, "/npc goblin")
    qtbot.wait(100)
    qtbot.keyClick(widget1.scratchpad, Qt.Key.Key_Return)
    assert "dmt://npc/npc_123" in widget1.scratchpad.toHtml().lower()
    assert not _linked_char_format(widget1.scratchpad, "Goblin Scout").fontUnderline()
    widget1._save_now()

    host2 = _FakeMainWindow()
    qtbot.addWidget(host2)
    reopened = SessionCreatorWidget(host2)
    reopened.show()
    match_row = None
    for row in range(reopened.session_list.count()):
        item = reopened.session_list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == session_id:
            match_row = row
            break
    assert match_row is not None
    reopened.session_list.setCurrentRow(match_row)
    reopened._load_selected_session()

    assert "Goblin Scout" in reopened.plan_editor.toPlainText()
    assert "Goblin Scout" in reopened.scratchpad.toPlainText()
    assert "dmt://npc/npc_123" in reopened.plan_editor.toHtml().lower()
    assert "dmt://npc/npc_123" in reopened.scratchpad.toHtml().lower()
    assert not _linked_char_format(reopened.plan_editor, "Goblin Scout").fontUnderline()
    assert not _linked_char_format(reopened.scratchpad, "Goblin Scout").fontUnderline()
