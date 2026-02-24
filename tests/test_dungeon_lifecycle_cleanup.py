import os
import sys

from PyQt6.QtWidgets import QApplication


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from dungeon_applet import DungeonAppletWidget, ONLINE_MODE_DM_HOST


def test_dungeon_close_stops_online_timers(qtbot):
    widget = DungeonAppletWidget()
    qtbot.addWidget(widget)
    widget._set_online_mode(ONLINE_MODE_DM_HOST)

    assert widget._host_scene_watchdog_timer.isActive()
    assert widget._loot_claim_reservation_timer.isActive()

    widget.close()
    QApplication.processEvents()

    assert not widget._host_scene_sync_timer.isActive()
    assert not widget._host_scene_watchdog_timer.isActive()
    assert not widget._loot_claim_reservation_timer.isActive()
