import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from session_creator import SessionCreatorWidget


def _create_named_session(widget: SessionCreatorWidget, name: str) -> None:
    widget._create_session()
    item = widget.session_list.currentItem()
    assert item is not None
    item.setText(name)
    widget._on_session_name_changed(item)


def _find_session_item(widget: SessionCreatorWidget, name: str):
    for index in range(widget.session_list.count()):
        item = widget.session_list.item(index)
        if item is not None and item.text() == name:
            return item
    return None


def test_session_creator_close_stops_autosave_timer(qtbot):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)

    widget.auto_save_timer.start()
    assert widget.auto_save_timer.isActive()

    widget.close()

    assert not widget.auto_save_timer.isActive()


def test_session_creator_close_persists_pending_edits(qtbot):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    _create_named_session(widget, "Close Persist")

    widget.scratchpad.setPlainText("typed before close")
    assert widget._current_session_dirty is True

    widget.close()

    reloaded = SessionCreatorWidget()
    qtbot.addWidget(reloaded)
    saved = next(session for session in reloaded.manager.sessions if session.name == "Close Persist")
    assert "typed before close" in saved.notes


def test_session_creator_switch_persists_pending_edits(qtbot):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)
    _create_named_session(widget, "Session A")
    _create_named_session(widget, "Session B")

    item_a = _find_session_item(widget, "Session A")
    item_b = _find_session_item(widget, "Session B")
    assert item_a is not None
    assert item_b is not None

    widget.session_list.setCurrentItem(item_a)
    widget.scratchpad.setPlainText("pending switch save")
    assert widget._current_session_dirty is True

    widget.session_list.setCurrentItem(item_b)

    reloaded = SessionCreatorWidget()
    qtbot.addWidget(reloaded)
    saved = next(session for session in reloaded.manager.sessions if session.name == "Session A")
    assert "pending switch save" in saved.notes
