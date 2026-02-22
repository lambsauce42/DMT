
import pytest
import sys
import os
from PyQt6.QtWidgets import QLabel, QBoxLayout, QHBoxLayout, QApplication

# Adjust import path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from ui.encounter_panel import EncounterPanel

def test_encounter_panel_layout_changes(qtbot):
    panel = EncounterPanel()
    qtbot.addWidget(panel)

    # 1. Check Splitter Ratios/Stretch Factors
    splitter = panel._splitter
    
    panel.resize(1400, 600)
    panel.show()
    QApplication.processEvents()
    panel._apply_splitter_sizes()
    QApplication.processEvents()
    
    sizes = splitter.sizes()
    
    total = sum(sizes)
    assert total > 0
    
    # Expected Ratios: 16 : 27 : 27. Total 70.
    # p0 ~ 16/70 = 0.2285
    # p1 ~ 27/70 = 0.3857
    # p2 ~ 27/70 = 0.3857
    
    p0 = sizes[0] / total
    p1 = sizes[1] / total
    p2 = sizes[2] / total
    
    assert abs(p0 - 0.2285) < 0.02
    assert abs(p1 - 0.3857) < 0.02
    assert abs(p2 - 0.3857) < 0.02

    # 2. Check "XP/CR:" Label
    # It should be in the browser panel layout.
    # We can find all QLabels and check if one has text "XP/CR:"
    labels = panel.findChildren(QLabel)
    xp_cr_label = next((l for l in labels if l.text() == "XP/CR:"), None)
    assert xp_cr_label is not None
    assert xp_cr_label.isVisible()

    # 3. Check Sort Combo location
    # It should be in the same row (layout) as Match all tags
    sort_combo = panel._sort_combo
    match_all_tags = panel._match_all_tags
    
    # They should share the same parent widget (the GroupBox)
    assert sort_combo.parent() == match_all_tags.parent()
    
    # We can inspect the layout to see if they are in the same QHBoxLayout
    # match_all_tags.parent() is the QGroupBox "Tags"
    group_box = match_all_tags.parent()
    main_layout = group_box.layout()
    
    # The last item in the main_layout (QVBox) should be the QHBox containing them
    last_item = main_layout.itemAt(main_layout.count() - 1)
    assert isinstance(last_item, QBoxLayout) # QHBoxLayout inherits QBoxLayout
    # Actually itemAt returns QLayoutItem. If it is a layout, .layout() returns the layout.
    
    sort_row_layout = last_item.layout()
    assert isinstance(sort_row_layout, QHBoxLayout)
    
    # Check items in this horizontal layout
    # We expect: Checkbox, Stretch, Label "Sort:", Combo
    
    # We can't easily iterate layout items by index and get widgets reliably if there are spacers.
    # But we can check if both widgets are in this layout.
    
    widgets_in_row = []
    for i in range(sort_row_layout.count()):
        item = sort_row_layout.itemAt(i)
        if item.widget():
            widgets_in_row.append(item.widget())
    
    assert match_all_tags in widgets_in_row
    assert sort_combo in widgets_in_row
    
    # Check for "Sort:" label
    sort_label = next((w for w in widgets_in_row if isinstance(w, QLabel) and w.text() == "Sort:"), None)
    assert sort_label is not None
    
    # Verify order: Checkbox -> ... -> Label -> Combo
    checkbox_idx = widgets_in_row.index(match_all_tags)
    label_idx = widgets_in_row.index(sort_label)
    combo_idx = widgets_in_row.index(sort_combo)
    
    # 4. Check "from" and "to" labels
    labels = panel.findChildren(QLabel)
    from_label = next((l for l in labels if l.text() == "from"), None)
    to_label = next((l for l in labels if l.text() == "to"), None)
    assert from_label is not None
    assert to_label is not None
    assert from_label.isVisible()
    assert to_label.isVisible()

    # 6. Check Modify column
    assert panel._encounter_headers[4] == "Modify"

