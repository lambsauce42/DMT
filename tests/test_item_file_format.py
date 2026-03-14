from __future__ import annotations

import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from item_file_format import (
    ITEM_FILE_EXTENSION,
    ITEM_FILE_FORMAT,
    build_item_document,
    indexed_item_record_by_id,
    item_id_from_payload,
    list_item_file_paths,
    load_item_document,
    load_item_payload,
    resolved_item_document_payload,
    write_item_document,
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
    write_item_document(item_path, document)

    with zipfile.ZipFile(item_path, "r") as zf:
        names = set(zf.namelist())
        assert "info.json" in names
        assert "assets/icon.png" in names
        info = json.loads(zf.read("info.json").decode("utf-8"))
        assert info["format"] == ITEM_FILE_FORMAT
        assert info["payload"]["title"] == "Blade"
        assert info["payload"]["item_id"]
        assert info["icon_asset_name"] == "assets/icon.png"

    loaded = load_item_payload(item_path)
    assert isinstance(loaded, dict)
    assert loaded["title"] == "Blade"
    assert loaded["rarity"] == "common"
    assert item_id_from_payload(loaded)
    embedded_icon_path = Path(str(loaded.get("icon_path") or ""))
    assert embedded_icon_path.exists()
    assert embedded_icon_path.suffix == ".png"


def test_resolved_item_document_payload_uses_embedded_icon_after_source_is_deleted(
    tmp_path: Path,
) -> None:
    icon_source = tmp_path / "icon.png"
    icon_source.write_bytes(_PNG_1X1_BYTES)

    document = build_item_document(
        {
            "title": "Blade",
            "rarity": "common",
            "level": 1,
            "icon_path": str(icon_source),
        },
        str(icon_source),
    )
    icon_source.unlink()

    resolved = resolved_item_document_payload(document)

    assert isinstance(resolved, dict)
    assert resolved["title"] == "Blade"
    assert str(resolved.get("icon_path") or "").strip() != str(icon_source)
    assert Path(str(resolved.get("icon_path") or "")).exists()


def test_build_item_document_preserves_existing_item_id() -> None:
    payload = {
        "item_id": "remote-item-fixed",
        "title": "Remote Item",
        "rarity": "common",
        "level": 1,
    }
    document = build_item_document(payload, None)

    assert isinstance(document, dict)
    assert isinstance(document.get("payload"), dict)
    assert document["payload"]["item_id"] == "remote-item-fixed"


def test_load_item_document_rejects_legacy_raw_json_payload(tmp_path: Path) -> None:
    legacy_document = {
        "format": "dmtitem.v1",
        "payload": {"title": "Legacy Blade", "rarity": "common", "level": 1},
    }
    legacy_path = tmp_path / f"legacy{ITEM_FILE_EXTENSION}"
    legacy_path.write_text(json.dumps(legacy_document), encoding="utf-8")

    document = load_item_document(legacy_path)
    assert document is None


def test_list_item_file_paths_includes_only_dmtitem(tmp_path: Path) -> None:
    root = tmp_path / "items"
    root.mkdir(parents=True, exist_ok=True)
    dmtitem_path = root / "a_item.dmtitem"
    (root / "b_item.json").write_text("{}", encoding="utf-8")
    dmtitem_path.write_text("{}", encoding="utf-8")

    files = list_item_file_paths(root)
    names = [path.name for path in files]
    assert names == ["a_item.dmtitem"]


def test_load_item_payload_rejects_non_dmtitem_format(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.json"
    legacy_path.write_text(
        json.dumps({"title": "Legacy Item", "rarity": "rare", "level": 2}),
        encoding="utf-8",
    )

    loaded = load_item_payload(legacy_path)
    assert loaded is None


def test_indexed_item_record_by_id_sees_new_file_after_cache_was_built(tmp_path: Path) -> None:
    root = tmp_path / "items"
    root.mkdir(parents=True, exist_ok=True)

    first_path = root / "first.dmtitem"
    write_item_document(
        first_path,
        build_item_document(
            {"item_id": "item-first", "title": "First", "rarity": "common", "level": 1},
            None,
        ),
    )

    first_record = indexed_item_record_by_id(root, "item-first")
    assert first_record is not None
    assert first_record.path == first_path

    second_path = root / "second.dmtitem"
    write_item_document(
        second_path,
        build_item_document(
            {"item_id": "item-second", "title": "Second", "rarity": "common", "level": 1},
            None,
        ),
    )

    second_record = indexed_item_record_by_id(root, "item-second")
    assert second_record is not None
    assert second_record.path == second_path
