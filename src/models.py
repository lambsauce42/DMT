from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class World:
    id: str
    name: str
    description: str = ""
    campaign_ids: List[str] = field(default_factory=list)
    map_ids: List[str] = field(default_factory=list)
    dungeon_ids: List[str] = field(default_factory=list)
    npc_ids: List[str] = field(default_factory=list)


@dataclass
class Campaign:
    id: str
    world_id: str
    name: str
    summary: str = ""
    group_ids: List[str] = field(default_factory=list)


@dataclass
class Group:
    id: str
    campaign_id: str
    name: str
    notes: str = ""


@dataclass
class MapAsset:
    id: str
    name: str
    image_path: str
    campaign_id: Optional[str] = None
    world: Optional[str] = None
    campaign: Optional[str] = None
    group: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    notes: str = ""
    thumbnail_path: Optional[str] = None
    created_at: str = ""
    last_modified: str = ""


@dataclass
class SessionLogEntry:
    timestamp: str
    event_type: str
    description: str


@dataclass
class Session:
    id: str
    name: str
    session_date: str
    # New fields
    in_game_date: str = ""
    real_world_duration: str = ""
    notes: str = ""
    logs: List[SessionLogEntry] = field(default_factory=list)
    # Existing fields
    document_path: Optional[str] = None
    plan_text: str = ""
    group_ids: List[str] = field(default_factory=list)


@dataclass
class Dungeon:
    id: str
    name: str
    world_id: str
    json_path: Optional[str] = None
    image_path: Optional[str] = None


@dataclass
class Item:
    id: str
    name: str
    required_level: int = 1
    json_path: Optional[str] = None
    pdf_path: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class NPC:
    id: str
    name: str
    world_id: str
    location: str = ""
    description: str = ""
    tags: List[str] = field(default_factory=list)
