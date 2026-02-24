import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from session_creator import SessionCreatorWidget


def test_session_creator_close_stops_autosave_timer(qtbot):
    widget = SessionCreatorWidget()
    qtbot.addWidget(widget)

    widget.auto_save_timer.start()
    assert widget.auto_save_timer.isActive()

    widget.close()

    assert not widget.auto_save_timer.isActive()
