import os
import sys

import pytest


sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from ui.encounter_panel import EncounterPanel


def test_party_size_slider_supports_ten_players(qtbot):
    panel = EncounterPanel()
    qtbot.addWidget(panel)

    assert panel._party_size_slider.maximum() == 10

    panel._party_size_slider.setValue(10)
    assert panel._party_size_slider.value() == 10
    assert len(panel._level_sliders) == 10
