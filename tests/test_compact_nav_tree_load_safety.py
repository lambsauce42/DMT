import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import compact_nav_tree
from compact_nav_tree import CompactNavTree


def _write_nav(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def test_compact_nav_tree_skips_non_dict_world_entries(qtbot, monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    _write_nav(
        nav_path,
        [
            "broken-world",
            {"name": "Valid World", "campaigns": []},
        ],
    )

    monkeypatch.setattr(compact_nav_tree, "NAVIGATION_PATH", str(nav_path))
    print(f"[debug] loading compact nav from malformed world payload at {nav_path}")

    widget = CompactNavTree()
    qtbot.addWidget(widget)

    print(f"[debug] loaded world names: {[world.get('name') for world in widget._data]}")
    assert [world.get("name") for world in widget._data] == ["Valid World"]


def test_compact_nav_tree_skips_non_dict_campaign_entries(qtbot, monkeypatch, tmp_path):
    nav_path = tmp_path / "nav.json"
    _write_nav(
        nav_path,
        [
            {
                "name": "World A",
                "campaigns": [
                    "broken-campaign",
                    {"name": "Campaign A", "groups": []},
                ],
            }
        ],
    )

    monkeypatch.setattr(compact_nav_tree, "NAVIGATION_PATH", str(nav_path))
    print(f"[debug] loading compact nav from malformed campaign payload at {nav_path}")

    widget = CompactNavTree()
    qtbot.addWidget(widget)

    campaigns = widget._data[0]["campaigns"] if widget._data else []
    print(f"[debug] loaded campaign names: {[campaign.get('name') for campaign in campaigns]}")
    assert [campaign.get("name") for campaign in campaigns] == ["Campaign A"]
