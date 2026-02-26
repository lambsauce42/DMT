import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import navigate_widget
from navigate_widget import NavigateContentWidget


def _write_nav(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _mount_widget(qtbot, monkeypatch, tmp_path, payload):
    nav_path = tmp_path / "nav.json"
    trash_path = tmp_path / "trash.json"
    _write_nav(nav_path, payload)
    monkeypatch.setattr(navigate_widget, "NAVIGATION_PATH", str(nav_path))
    monkeypatch.setattr(navigate_widget, "TRASH_PATH", str(trash_path))
    widget = NavigateContentWidget(show_worlds_header=False)
    qtbot.addWidget(widget)
    return widget


def test_remove_world_with_duplicate_name_deletes_only_one(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {"name": "Dup", "campaigns": []},
            {"name": "Dup", "campaigns": []},
        ],
    )
    print(f"[debug] worlds before remove: {len(widget._data)}")

    widget.remove_world(name="Dup")
    print(f"[debug] worlds after remove: {len(widget._data)}")

    assert len(widget._data) == 1
    assert len(widget._trash) == 1


def test_remove_world_by_index_zero_removes_first_row_only(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {"name": "First", "campaigns": []},
            {"name": "Second", "campaigns": []},
        ],
    )

    widget.remove_world(name=0)

    assert [world.get("name") for world in widget._data] == ["Second"]
    assert len(widget._trash) == 1
    assert widget._trash[0].get("name") == "First"


def test_disintegrate_world_with_duplicate_name_deletes_only_one(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {"name": "Dup", "campaigns": []},
            {"name": "Dup", "campaigns": []},
        ],
    )
    widget._confirm_disintegrate = lambda *_args, **_kwargs: True
    print(f"[debug] worlds before disintegrate: {len(widget._data)}")

    widget.disintegrate_world(name="Dup")
    print(f"[debug] worlds after disintegrate: {len(widget._data)}")

    assert len(widget._data) == 1


def test_remove_campaign_with_duplicate_name_deletes_only_one(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {
                "name": "World",
                "campaigns": [
                    {"name": "Dup", "groups": []},
                    {"name": "Dup", "groups": []},
                ],
            }
        ],
    )
    print(f"[debug] campaigns before remove: {len(widget._data[0]['campaigns'])}")

    widget._remove_campaign(0, name="Dup")
    print(f"[debug] campaigns after remove: {len(widget._data[0]['campaigns'])}")

    assert len(widget._data[0]["campaigns"]) == 1
    assert len(widget._trash) == 1


def test_disintegrate_campaign_with_duplicate_name_deletes_only_one(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {
                "name": "World",
                "campaigns": [
                    {"name": "Dup", "groups": []},
                    {"name": "Dup", "groups": []},
                ],
            }
        ],
    )
    widget._confirm_disintegrate = lambda *_args, **_kwargs: True
    print(f"[debug] campaigns before disintegrate: {len(widget._data[0]['campaigns'])}")

    widget._disintegrate_campaign(0, name="Dup")
    print(f"[debug] campaigns after disintegrate: {len(widget._data[0]['campaigns'])}")

    assert len(widget._data[0]["campaigns"]) == 1


def test_remove_group_with_duplicate_name_deletes_only_one(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {
                "name": "World",
                "campaigns": [
                    {
                        "name": "Campaign",
                        "groups": [{"name": "Dup"}, {"name": "Dup"}],
                    }
                ],
            }
        ],
    )
    print(f"[debug] groups before remove: {len(widget._data[0]['campaigns'][0]['groups'])}")

    widget._remove_group(0, 0, name="Dup")
    print(f"[debug] groups after remove: {len(widget._data[0]['campaigns'][0]['groups'])}")

    assert len(widget._data[0]["campaigns"][0]["groups"]) == 1
    assert len(widget._trash) == 1


def test_disintegrate_group_with_duplicate_name_deletes_only_one(qtbot, monkeypatch, tmp_path):
    widget = _mount_widget(
        qtbot,
        monkeypatch,
        tmp_path,
        [
            {
                "name": "World",
                "campaigns": [
                    {
                        "name": "Campaign",
                        "groups": [{"name": "Dup"}, {"name": "Dup"}],
                    }
                ],
            }
        ],
    )
    widget._confirm_disintegrate = lambda *_args, **_kwargs: True
    print(f"[debug] groups before disintegrate: {len(widget._data[0]['campaigns'][0]['groups'])}")

    widget._disintegrate_group(0, 0, name="Dup")
    print(f"[debug] groups after disintegrate: {len(widget._data[0]['campaigns'][0]['groups'])}")

    assert len(widget._data[0]["campaigns"][0]["groups"]) == 1
