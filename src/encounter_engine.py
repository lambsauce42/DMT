from __future__ import annotations

import csv
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from save_paths import dnd_saves_dir


class EncounterDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class Monster:
    id: str
    name: str
    cr: str
    cr_value: float
    xp: int
    hp: int
    ac: int
    actions: str
    description: str
    tags: tuple[str, ...]
    source: str
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10
    icon_path: str = ""
    transient: bool = False


@dataclass
class EncounterEntry:
    monster: Monster
    count: int


@dataclass(frozen=True)
class SuggestFilters:
    search: Optional[str] = None
    min_xp: Optional[int] = None
    max_xp: Optional[int] = None
    cr_values: Optional[set[str]] = None
    tags: Optional[set[str]] = None


DifficultyTable = dict[int, dict[str, int]]
MultiplierEntry = tuple[int, Optional[int], float, float, float]
MultiplierTable = list[MultiplierEntry]


REQUIRED_MONSTER_COLUMNS = {
    "id",
    "name",
    "cr",
    "xp",
    "hp",
    "ac",
    "actions",
    "description",
    "tags",
    "source",
}

OPTIONAL_STAT_COLUMNS = {
    "str",
    "dex",
    "con",
    "int",
    "wis",
    "cha",
}


def parse_tags_text(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    tokens = [token.strip().lower() for token in text.replace(";", ",").split(",")]
    return tuple(token for token in tokens if token)


def _data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data"


def resolve_monster_db_path() -> Path:
    override = dnd_saves_dir() / "imports" / "dnd_monsters_full.csv"
    if override.exists():
        return override
    return _data_dir() / "dnd_monsters_full.csv"


def parse_cr_value(cr: str) -> float:
    token = cr.strip()
    if not token:
        raise EncounterDataError("CR value is empty.")
    if "/" in token:
        numerator, denominator = token.split("/", 1)
        try:
            return float(numerator) / float(denominator)
        except ValueError as exc:
            raise EncounterDataError(f"Invalid CR fraction '{cr}'.") from exc
    try:
        return float(token)
    except ValueError as exc:
        raise EncounterDataError(f"Invalid CR value '{cr}'.") from exc


def _parse_int(value: str, field_name: str) -> int:
    try:
        return int(float(value))
    except ValueError as exc:
        raise EncounterDataError(f"Invalid {field_name} value '{value}'.") from exc


def load_monsters(path: Path | None = None) -> list[Monster]:
    resolved_path = path or resolve_monster_db_path()
    if not resolved_path.exists():
        raise EncounterDataError(
            f"Monster DB missing: {resolved_path}. Place a CSV at this location."
        )
    with resolved_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise EncounterDataError("Monster DB has no headers.")
        missing = REQUIRED_MONSTER_COLUMNS - set(reader.fieldnames)
        if missing:
            raise EncounterDataError(
                f"Monster DB is missing required columns: {', '.join(sorted(missing))}."
            )
        monsters: list[Monster] = []
        for row_number, row in enumerate(reader, start=2):
            try:
                tags = parse_tags_text(row.get("tags") or "")
                actions = (row.get("actions") or "").replace("\\n", "\n")
                description = (row.get("description") or "").replace("\\n", "\n")
                cr_token = (row.get("cr") or "").strip()
                strength = _parse_int(row.get("str") or "10", "str")
                dexterity = _parse_int(row.get("dex") or "10", "dex")
                constitution = _parse_int(row.get("con") or "10", "con")
                intelligence = _parse_int(row.get("int") or "10", "int")
                wisdom = _parse_int(row.get("wis") or "10", "wis")
                charisma = _parse_int(row.get("cha") or "10", "cha")
                monster = Monster(
                    id=(row.get("id") or "").strip(),
                    name=(row.get("name") or "").strip(),
                    cr=cr_token,
                    cr_value=parse_cr_value(cr_token),
                    xp=_parse_int(row.get("xp") or "0", "xp"),
                    hp=_parse_int(row.get("hp") or "0", "hp"),
                    ac=_parse_int(row.get("ac") or "0", "ac"),
                    actions=actions,
                    description=description,
                    tags=tags,
                    source=(row.get("source") or "").strip(),
                    strength=strength,
                    dexterity=dexterity,
                    constitution=constitution,
                    intelligence=intelligence,
                    wisdom=wisdom,
                    charisma=charisma,
                    icon_path=(row.get("icon_path") or "").strip(),
                    transient=False,
                )
            except EncounterDataError as exc:
                raise EncounterDataError(
                    f"Monster DB row {row_number} invalid: {exc}"
                ) from exc
            if not monster.id or not monster.name:
                raise EncounterDataError(
                    f"Monster DB row {row_number} missing id or name."
                )
            monsters.append(monster)
    return monsters


def load_difficulty_table(path: Path | None = None) -> DifficultyTable:
    resolved_path = path or (_data_dir() / "EncounterDifficulty.csv")
    if not resolved_path.exists():
        raise EncounterDataError(
            f"Difficulty table missing: {resolved_path}. Place the CSV there."
        )
    with resolved_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise EncounterDataError("Difficulty table has no headers.")
        difficulty_columns = [
            name for name in reader.fieldnames if name not in {"players", "level"}
        ]
        if not difficulty_columns:
            raise EncounterDataError("Difficulty table has no difficulty columns.")
        table: DifficultyTable = {}
        for row_number, row in enumerate(reader, start=2):
            players = _parse_int(row.get("players") or "0", "players")
            if players != 1:
                continue
            level = _parse_int(row.get("level") or "0", "level")
            table[level] = {
                name.replace("_xp", "").lower(): _parse_int(row.get(name) or "0", name)
                for name in difficulty_columns
            }
        if not table:
            raise EncounterDataError("Difficulty table has no rows for players=1.")
    return table


def compute_target_xp(player_levels: list[int], difficulty: str) -> int:
    table = load_difficulty_table()
    difficulty_key = difficulty.strip().lower()
    total = 0
    for level in player_levels:
        if level not in table:
            raise EncounterDataError(f"Unsupported level {level}.")
        thresholds = table[level]
        if difficulty_key not in thresholds:
            raise EncounterDataError(f"Unknown difficulty '{difficulty}'.")
        total += thresholds[difficulty_key]
    return total


def load_multiplier_table(path: Path | None = None) -> MultiplierTable:
    resolved_path = path or (_data_dir() / "EncounterMultipliers.csv")
    if not resolved_path.exists():
        raise EncounterDataError(
            f"Multiplier table missing: {resolved_path}. Place the CSV there."
        )
    with resolved_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise EncounterDataError("Multiplier table has no headers.")
        required = {
            "entities",
            "multiplier_players_1_2",
            "multiplier_players_3_5",
            "multiplier_players_gt5",
        }
        missing = required - set(reader.fieldnames)
        if missing:
            raise EncounterDataError(
                f"Multiplier table missing columns: {', '.join(sorted(missing))}."
            )
        table: MultiplierTable = []
        for row_number, row in enumerate(reader, start=2):
            token = (row.get("entities") or "").strip()
            if not token:
                raise EncounterDataError(f"Row {row_number} missing entity range.")
            min_value: int
            max_value: Optional[int]
            if "-" in token:
                start, end = token.split("-", 1)
                min_value = _parse_int(start, "entities")
                max_value = _parse_int(end, "entities")
            elif token.startswith(">"):
                min_value = _parse_int(token[1:], "entities") + 1
                max_value = None
            else:
                min_value = _parse_int(token, "entities")
                max_value = min_value
            try:
                mult_1_2 = float(row.get("multiplier_players_1_2") or 1)
                mult_3_5 = float(row.get("multiplier_players_3_5") or 1)
                mult_6 = float(row.get("multiplier_players_gt5") or 1)
            except ValueError as exc:
                raise EncounterDataError(
                    f"Invalid multiplier values on row {row_number}."
                ) from exc
            table.append((min_value, max_value, mult_1_2, mult_3_5, mult_6))
    return table


def lookup_multiplier(total_entities: int, party_size: int) -> float:
    table = load_multiplier_table()
    if party_size <= 2:
        column_index = 2
    elif party_size <= 5:
        column_index = 3
    else:
        column_index = 4

    for min_value, max_value, mult_1_2, mult_3_5, mult_6 in table:
        if max_value is None:
            matches = total_entities >= min_value
        else:
            matches = min_value <= total_entities <= max_value
        if matches:
            return [mult_1_2, mult_3_5, mult_6][column_index - 2]
    return 1.0


def compute_adjusted_xp(
    entries: Iterable[EncounterEntry], party_size: int
) -> tuple[int, float, int]:
    raw_xp = sum(entry.monster.xp * entry.count for entry in entries)
    total_entities = sum(entry.count for entry in entries)
    if total_entities <= 0:
        return 0, 1.0, 0
    multiplier = lookup_multiplier(total_entities, party_size)
    adjusted = int(raw_xp * multiplier + 0.5)
    return raw_xp, multiplier, adjusted


def _passes_filters(monster: Monster, filters: Optional[SuggestFilters]) -> bool:
    if filters is None:
        return True
    if filters.search:
        if filters.search.lower() not in monster.name.lower():
            return False
    if filters.min_xp is not None and monster.xp < filters.min_xp:
        return False
    if filters.max_xp is not None and monster.xp > filters.max_xp:
        return False
    if filters.cr_values and monster.cr not in filters.cr_values:
        return False
    if filters.tags:
        if not set(monster.tags) & filters.tags:
            return False
    return True


def suggest_monsters(
    target_xp: int,
    monsters: list[Monster],
    max_monsters: int = 10,
    method: str = "greedy",
    filters: SuggestFilters | None = None,
) -> list[EncounterEntry]:
    if target_xp <= 0:
        return []
    candidates = [m for m in monsters if _passes_filters(m, filters)]
    if not candidates:
        return []
    if method != "greedy":
        method = "greedy"
    tolerance = target_xp * 0.1
    remaining = target_xp
    entries: dict[str, EncounterEntry] = {}
    total_added = 0

    while total_added < max_monsters and remaining > 0:
        sorted_candidates = sorted(
            candidates,
            key=lambda monster: (
                abs(remaining - monster.xp),
                -monster.xp,
                monster.name.lower(),
            ),
        )
        chosen = sorted_candidates[0]
        entry = entries.get(chosen.id)
        if entry:
            entry.count += 1
        else:
            entries[chosen.id] = EncounterEntry(monster=chosen, count=1)
        total_added += 1
        remaining -= chosen.xp
        if remaining <= tolerance:
            break
    return list(entries.values())


def sort_monsters_by_xp(monsters: list[Monster], mode: str) -> list[Monster]:
    if mode == "asc":
        return sorted(monsters, key=lambda m: (m.xp, m.name.lower()))
    if mode == "desc":
        return sorted(monsters, key=lambda m: (-m.xp, m.name.lower()))
    return monsters


def make_transient_monster(
    base: Monster,
    *,
    name: str,
    cr: str,
    xp: int,
    hp: int,
    ac: int,
    actions: str,
    description: str,
    tags: tuple[str, ...],
    source: str,
    strength: int,
    dexterity: int,
    constitution: int,
    intelligence: int,
    wisdom: int,
    charisma: int,
) -> Monster:
    return Monster(
        id=f"transient:{uuid.uuid4()}",
        name=name,
        cr=cr,
        cr_value=parse_cr_value(cr),
        xp=xp,
        hp=hp,
        ac=ac,
        actions=actions,
        description=description,
        tags=tags,
        source=source,
        strength=strength,
        dexterity=dexterity,
        constitution=constitution,
        intelligence=intelligence,
        wisdom=wisdom,
        charisma=charisma,
        transient=True,
    )
