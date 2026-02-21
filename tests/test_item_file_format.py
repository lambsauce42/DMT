from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from item_file_format import (
    ITEM_FILE_EXTENSION,
    build_item_document,
    list_item_file_paths,
    load_item_payload,
)

_PNG_1X1_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc``\xf8\xff\xff?\x00\x05\xfe\x02\xfe"
    b"\xa7\xd6\x9f\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_build_document_with_embedded_icon_round_trip(tmp_path: Path) -> None:
    icon_source = tmp_path / "icon.png"
    icon_source.write_bytes(_PNG_1X1_BYTES)

    payload = {
        "title": "Blade",
        "rarity": "common",
        "level": 1,
        "effects": ["+1 attack"],
    }
    document = build_item_document(payload, str(icon_source))
    item_path = tmp_path / f"blade{ITEM_FILE_EXTENSION}"
    item_path.write_text(json.dumps(document), encoding="utf-8")

    loaded = load_item_payload(item_path)
    assert isinstance(loaded, dict)
    assert loaded["title"] == "Blade"
    assert loaded["rarity"] == "common"
    embedded_icon_path = Path(str(loaded.get("icon_path") or ""))
    assert embedded_icon_path.exists()
    assert embedded_icon_path.suffix == ".png"


def test_list_item_file_paths_includes_dmtitem_and_json(tmp_path: Path) -> None:
    root = tmp_path / "items"
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "b_item.json"
    dmtitem_path = root / "a_item.dmtitem"
    json_path.write_text("{}", encoding="utf-8")
    dmtitem_path.write_text("{}", encoding="utf-8")

    files = list_item_file_paths(root)
    names = [path.name for path in files]
    assert names == ["a_item.dmtitem", "b_item.json"]


def test_load_item_payload_supports_legacy_json(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(
        json.dumps({"title": "Legacy Item", "rarity": "rare", "level": 2}),
        encoding="utf-8",
    )

    loaded = load_item_payload(legacy_path)
    assert isinstance(loaded, dict)
    assert loaded["title"] == "Legacy Item"
    assert loaded["rarity"] == "rare"
