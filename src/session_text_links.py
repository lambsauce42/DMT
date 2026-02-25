from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from dmt_package import read_dmt_package_info
from save_paths import dnd_saves_dir

SUPPORTED_COMMANDS = {"npc", "map", "dungeon", "item", "character", "encounter"}
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((dmt://[^)\s]+)\)")


@dataclass(frozen=True)
class SlashTrigger:
    command: str
    query: str
    start: int
    end: int


@dataclass(frozen=True)
class ParsedSessionLink:
    start: int
    end: int
    label: str
    url: str
    kind: str
    target_id: str
    collection_path: Optional[str] = None


@dataclass(frozen=True)
class LinkSuggestion:
    kind: str
    target_id: str
    display_label: str
    markdown: str = ""
    href: str = ""
    link_text: str = ""
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    collection_path: Optional[str] = None


@dataclass(frozen=True)
class _StoredEntry:
    kind: str
    target_id: str
    name: str
    world: str = ""
    campaign: str = ""
    group: str = ""
    collection_path: str = ""
    collection_name: str = ""
    source_path: str = ""


def detect_slash_trigger(text: str, cursor_pos: int) -> Optional[SlashTrigger]:
    raw = str(text or "")
    if not raw:
        return None
    pos = max(0, min(int(cursor_pos), len(raw)))
    line_start = raw.rfind("\n", 0, pos) + 1
    segment = raw[line_start:pos]
    if "/" not in segment:
        return None
    rel_slash = segment.rfind("/")
    start = line_start + rel_slash

    if start > 0 and raw[start - 1] == "/":
        return None
    if start > 0 and not raw[start - 1].isspace():
        return None

    token = raw[start + 1 : pos]
    if not token.strip():
        return None

    parts = token.split(None, 1)
    command = parts[0].strip().lower()
    if command not in SUPPORTED_COMMANDS:
        return None
    query = parts[1].strip() if len(parts) > 1 else ""
    return SlashTrigger(command=command, query=query, start=start, end=pos)


def build_dmt_url(kind: str, target_id: str, collection_path: Optional[str] = None) -> str:
    clean_kind = str(kind or "").strip().lower()
    if clean_kind not in SUPPORTED_COMMANDS:
        raise ValueError(f"Unsupported link kind: {kind}")
    encoded_id = quote(str(target_id or "").strip(), safe="")
    if not encoded_id:
        raise ValueError("target_id is required")
    url = f"dmt://{clean_kind}/{encoded_id}"
    if clean_kind == "dungeon" and collection_path:
        query = urlencode(
            {"collection": str(collection_path)},
            doseq=False,
            quote_via=quote,
            safe="",
        )
        if query:
            url = f"{url}?{query}"
    return url


def build_markdown_link(
    *,
    kind: str,
    target_id: str,
    display_label: str,
    collection_path: Optional[str] = None,
) -> str:
    clean_label = str(display_label or "").strip()
    if not clean_label:
        raise ValueError("display_label is required")
    url = build_dmt_url(kind, target_id, collection_path=collection_path)
    return f"[{clean_label}]({url})"


def parse_dmt_url(url: str) -> Optional[tuple[str, str, Optional[str]]]:
    parsed = urlparse(str(url or ""))
    if parsed.scheme.lower() != "dmt":
        return None
    kind = str(parsed.netloc or "").strip().lower()
    if kind not in SUPPORTED_COMMANDS:
        return None
    target_id = unquote(str(parsed.path or "").lstrip("/")).strip()
    if not target_id:
        return None
    collection_path = None
    if kind == "dungeon":
        query = parse_qs(parsed.query, keep_blank_values=False)
        values = query.get("collection") or []
        if values:
            candidate = str(values[0] or "").strip()
            if candidate:
                collection_path = unquote(candidate)
    return kind, target_id, collection_path


def iter_markdown_links(text: str) -> list[ParsedSessionLink]:
    raw = str(text or "")
    output: list[ParsedSessionLink] = []
    for match in _MARKDOWN_LINK_RE.finditer(raw):
        label = match.group(1)
        url = match.group(2)
        parsed = parse_dmt_url(url)
        if parsed is None:
            continue
        kind, target_id, collection_path = parsed
        output.append(
            ParsedSessionLink(
                start=match.start(),
                end=match.end(),
                label=label,
                url=url,
                kind=kind,
                target_id=target_id,
                collection_path=collection_path,
            )
        )
    return output


def find_markdown_link_at_position(text: str, position: int) -> Optional[ParsedSessionLink]:
    pos = max(0, int(position))
    for link in iter_markdown_links(text):
        if link.start <= pos < link.end:
            return link
        if pos == link.end:
            return link
    return None


def _resolve_base_dir(base_dir: Optional[Path | str]) -> Path:
    if base_dir is not None:
        return Path(base_dir).expanduser().resolve()
    return dnd_saves_dir().expanduser().resolve()


def _tokens(query: str) -> list[str]:
    return [token for token in re.split(r"[\s,]+", str(query or "").strip().lower()) if token]


def _matches_query(query: str, *fields: str) -> bool:
    parts = _tokens(query)
    if not parts:
        return True
    haystack = " ".join(str(part or "").lower() for part in fields)
    return all(token in haystack for token in parts)


def _read_payload(path: Path, expected_format: str) -> Optional[tuple[dict, dict]]:
    try:
        info = read_dmt_package_info(path)
    except Exception as exc:
        print(f"[WARN] Unable to read link payload '{path}': {exc}", file=sys.stderr)
        return None
    if not isinstance(info, dict):
        return None
    if str(info.get("format") or "") != expected_format:
        return None
    payload = info.get("payload")
    if not isinstance(payload, dict):
        return None
    return info, payload


def _load_npc_entries(base_dir: Path) -> list[_StoredEntry]:
    output: list[_StoredEntry] = []
    npc_dir = base_dir / "npcs"
    for path in sorted(npc_dir.glob("*.dmtnpc")):
        parsed = _read_payload(path, expected_format="dmtnpc.v1")
        if parsed is None:
            continue
        info, payload = parsed
        name = str(payload.get("name") or "").strip()
        target_id = str(payload.get("id") or info.get("object_id") or "").strip()
        if not name or not target_id:
            continue
        output.append(
            _StoredEntry(
                kind="npc",
                target_id=target_id,
                name=name,
                world=str(payload.get("world") or "").strip(),
                campaign=str(payload.get("campaign") or "").strip(),
                group=str(payload.get("group") or "").strip(),
            )
        )
    return output


def _load_map_entries(base_dir: Path) -> list[_StoredEntry]:
    output: list[_StoredEntry] = []
    maps_dir = base_dir / "maps"
    for path in sorted(maps_dir.glob("*.dmtmap")):
        parsed = _read_payload(path, expected_format="dmtmap.v1")
        if parsed is None:
            continue
        info, payload = parsed
        name = str(payload.get("name") or "").strip()
        target_id = str(payload.get("id") or info.get("object_id") or "").strip()
        if not name or not target_id:
            continue
        output.append(
            _StoredEntry(
                kind="map",
                target_id=target_id,
                name=name,
                world=str(payload.get("world") or "").strip(),
                campaign=str(payload.get("campaign") or "").strip(),
                group=str(payload.get("group") or "").strip(),
            )
        )
    return output


def _load_dungeon_entries(base_dir: Path) -> list[_StoredEntry]:
    output: list[_StoredEntry] = []
    collections_dir = base_dir / "dungeon_collections"
    if not collections_dir.exists():
        return output
    for path in sorted(collections_dir.rglob("*.dmtcollection")):
        if not path.is_file():
            continue
        try:
            info = read_dmt_package_info(path)
        except Exception as exc:
            print(f"[WARN] Unable to read dungeon collection '{path}': {exc}", file=sys.stderr)
            continue
        if not isinstance(info, dict):
            continue
        if str(info.get("format") or "") != "dmtcollection.v1":
            continue
        payload = info
        collection_name = str(payload.get("collection_name") or path.stem).strip() or path.stem
        dungeons = payload.get("dungeons")
        if not isinstance(dungeons, list):
            continue
        for dungeon in dungeons:
            if not isinstance(dungeon, dict):
                continue
            target_id = str(dungeon.get("id") or "").strip()
            name = str(dungeon.get("name") or "").strip()
            if not target_id or not name:
                continue
            output.append(
                _StoredEntry(
                    kind="dungeon",
                    target_id=target_id,
                    name=name,
                    collection_path=str(path.resolve()),
                    collection_name=collection_name,
                )
            )
    return output


def _display_label(kind: str, name: str) -> str:
    return str(name or "").strip()


def _load_item_entries(base_dir: Path) -> list[_StoredEntry]:
    from item_file_format import list_item_file_paths, load_item_payload

    output: list[_StoredEntry] = []
    item_root = base_dir / "items"
    for path in list_item_file_paths(item_root):
        payload = load_item_payload(path)
        if not isinstance(payload, dict):
            continue
        target_id = str(path.stem or "").strip()
        name = str(payload.get("title") or path.stem).strip()
        if not target_id or not name:
            continue
        output.append(
            _StoredEntry(
                kind="item",
                target_id=target_id,
                name=name,
                source_path=str(path.resolve()),
            )
        )
    return output


def _load_character_entries(_base_dir: Path) -> list[_StoredEntry]:
    # Player sheets storage has richer migration logic; rely on its loader directly.
    from player_sheets import load_entries_from_storage, sheet_id_for_entry

    output: list[_StoredEntry] = []
    for entry in load_entries_from_storage():
        target_id = str(sheet_id_for_entry(entry) or "").strip()
        name = str(getattr(entry, "name", "") or "").strip()
        if not target_id or not name:
            continue
        output.append(
            _StoredEntry(
                kind="character",
                target_id=target_id,
                name=name,
                world=str(getattr(entry, "world", "") or "").strip(),
                campaign=str(getattr(entry, "campaign", "") or "").strip(),
                group=str(getattr(entry, "group", "") or "").strip(),
            )
        )
    return output


def _load_encounter_entries(base_dir: Path) -> list[_StoredEntry]:
    output: list[_StoredEntry] = []
    encounters_dir = base_dir / "encounters"
    if not encounters_dir.exists():
        return output
    for path in sorted(encounters_dir.rglob("*.dmtencounter")):
        if not path.is_file():
            continue
        try:
            info = read_dmt_package_info(path)
        except Exception as exc:
            print(f"[WARN] Unable to read encounter '{path}': {exc}", file=sys.stderr)
            continue
        if not isinstance(info, dict):
            continue
        if str(info.get("format") or "").strip() != "dmtencounter.v1":
            continue
        target_id = str(info.get("object_id") or info.get("id") or path.stem).strip()
        name = str(info.get("name") or path.stem).strip() or path.stem
        if not target_id:
            continue
        output.append(
            _StoredEntry(
                kind="encounter",
                target_id=target_id,
                name=name,
                source_path=str(path.resolve()),
            )
        )
    return output


def load_link_suggestions(
    command: str,
    query: str,
    *,
    world: str = "",
    campaign: str = "",
    group: str = "",
    base_dir: Optional[Path | str] = None,
    limit: int = 50,
) -> list[LinkSuggestion]:
    clean_command = str(command or "").strip().lower()
    if clean_command not in SUPPORTED_COMMANDS:
        return []
    target_limit = max(1, int(limit))
    root = _resolve_base_dir(base_dir)

    if clean_command == "npc":
        entries = _load_npc_entries(root)
    elif clean_command == "map":
        entries = _load_map_entries(root)
    elif clean_command == "dungeon":
        entries = _load_dungeon_entries(root)
    elif clean_command == "item":
        entries = _load_item_entries(root)
    elif clean_command == "encounter":
        entries = _load_encounter_entries(root)
    else:
        entries = _load_character_entries(root)

    filtered: list[LinkSuggestion] = []
    for entry in entries:
        if clean_command in {"npc", "map"}:
            if world and entry.world != world:
                continue
            if campaign and entry.campaign != campaign:
                continue
            if group and entry.group != group:
                continue
        if clean_command == "dungeon":
            if not _matches_query(query, entry.name, entry.collection_name, entry.collection_path):
                continue
        elif not _matches_query(query, entry.name, entry.world, entry.campaign, entry.group):
            continue

        label = _display_label(entry.kind, entry.name)
        href = build_dmt_url(
            kind=entry.kind,
            target_id=entry.target_id,
            collection_path=entry.collection_path or None,
        )
        markdown = build_markdown_link(
            kind=entry.kind,
            target_id=entry.target_id,
            display_label=label,
            collection_path=entry.collection_path or None,
        )
        filtered.append(
            LinkSuggestion(
                kind=entry.kind,
                target_id=entry.target_id,
                display_label=label,
                markdown=markdown,
                href=href,
                link_text=label,
                world=entry.world or None,
                campaign=entry.campaign or None,
                group=entry.group or None,
                collection_path=entry.collection_path or None,
            )
        )

    filtered.sort(key=lambda suggestion: suggestion.display_label.lower())
    return filtered[:target_limit]
