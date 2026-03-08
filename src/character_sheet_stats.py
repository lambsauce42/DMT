from __future__ import annotations

from pathlib import Path
import re


def extract_character_stats_from_pdf(pdf_path: str) -> dict:
    field_map = {
        "name": ["CharacterName", "Character Name", "Character_Name", "Name"],
        "strength": ["STR", "Strength", "Strength Score", "STR Score"],
        "dexterity": ["DEX", "Dexterity", "Dexterity Score", "DEX Score"],
        "constitution": ["CON", "Constitution", "Constitution Score", "CON Score"],
        "intelligence": ["INT", "Intelligence", "Intelligence Score", "INT Score"],
        "wisdom": ["WIS", "Wisdom", "Wisdom Score", "WIS Score"],
        "charisma": ["CHA", "Charisma", "Charisma Score", "CHA Score"],
        "ac": ["AC", "ArmorClass", "Armor Class", "Armour Class"],
        "hp_max": ["HPMax", "HP Max", "HitPoints", "Hit Points", "MaxHP", "HPmax"],
        "hp_current": ["HPCurrent", "CurrentHP", "Current Hit Points", "HP"],
    }

    def _parse_int(value: object) -> int | None:
        text = str(value or "").strip()
        if not text:
            return None
        match = re.search(r"-?\d+", text)
        if not match:
            return None
        try:
            return int(match.group(0))
        except (TypeError, ValueError):
            return None

    def _normalize_field_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _extract_candidates(values: dict[str, str], candidates: list[str]) -> str | None:
        for candidate in candidates:
            candidate_key = _normalize_field_key(candidate)
            if not candidate_key:
                continue
            direct = values.get(candidate_key)
            if direct:
                return direct
            for key, value in values.items():
                if key.startswith(candidate_key):
                    suffix = key[len(candidate_key) :]
                    if not suffix or suffix.isdigit():
                        return value
        return None

    def _extract_pdf_literal(value: bytes) -> str:
        decoded = value.decode("latin-1", errors="ignore")
        decoded = re.sub(
            r"\\([0-7]{1,3})",
            lambda match: chr(int(match.group(1), 8)),
            decoded,
        )
        decoded = decoded.replace("\\n", "\n")
        decoded = decoded.replace("\\r", "\r")
        decoded = decoded.replace("\\t", "\t")
        decoded = decoded.replace("\\b", "\b")
        decoded = decoded.replace("\\f", "\f")
        decoded = decoded.replace("\\(", "(")
        decoded = decoded.replace("\\)", ")")
        decoded = decoded.replace("\\\\", "\\")
        return decoded.strip()

    output = {
        "name": None,
        "strength": None,
        "dexterity": None,
        "constitution": None,
        "intelligence": None,
        "wisdom": None,
        "charisma": None,
        "ac": None,
        "hp_max": None,
        "hp_current": None,
        "hp": None,
    }

    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        PdfReader = None  # type: ignore

    if PdfReader is not None:
        try:
            reader = PdfReader(pdf_path)
            fields = reader.get_fields() or {}
            field_values: dict[str, str] = {}
            for field_name, raw_field in fields.items():
                if not isinstance(field_name, str):
                    continue
                raw_val = None
                if isinstance(raw_field, dict):
                    raw_val = raw_field.get("/V")
                if raw_val is None:
                    continue
                clean = str(raw_val).strip()
                if not clean:
                    continue
                field_values[_normalize_field_key(field_name)] = clean

            for key, candidates in field_map.items():
                clean = _extract_candidates(field_values, candidates)
                if not clean:
                    continue
                output[key] = clean if key == "name" else _parse_int(clean)
        except Exception:
            pass

    missing = [key for key, value in output.items() if value is None and key != "hp"]
    if missing:
        try:
            token_values: dict[str, str] = {}
            raw_bytes = Path(pdf_path).read_bytes()
            pattern = re.compile(
                rb"/T\(((?:\\.|[^\\)])*)\)(?:(?!endobj).){0,1200}?/V\(((?:\\.|[^\\)])*)\)",
                re.DOTALL,
            )
            for match in pattern.finditer(raw_bytes):
                name = _extract_pdf_literal(match.group(1))
                value = _extract_pdf_literal(match.group(2))
                if not name or not value:
                    continue
                token_values[_normalize_field_key(name)] = value
            for key in missing:
                candidates = field_map.get(key)
                if not candidates:
                    continue
                clean = _extract_candidates(token_values, candidates)
                if not clean:
                    continue
                output[key] = clean if key == "name" else _parse_int(clean)
        except Exception:
            pass

    missing = [key for key, value in output.items() if value is None]
    if not [key for key in missing if key != "hp"]:
        if output.get("hp") is None:
            if isinstance(output.get("hp_max"), int):
                output["hp"] = output.get("hp_max")
            elif isinstance(output.get("hp_current"), int):
                output["hp"] = output.get("hp_current")
        return output

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(pdf_path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:
        return output

    def _find(pattern: str) -> str | None:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    text_values = {
        "name": _find(r"Character\s*Name\s*[:\s]+([^\n\r]+)"),
        "strength": _find(r"\bSTR(?:ength)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "dexterity": _find(r"\bDEX(?:terity)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "constitution": _find(r"\bCON(?:stitution)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "intelligence": _find(r"\bINT(?:elligence)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "wisdom": _find(r"\bWIS(?:dom)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "charisma": _find(r"\bCHA(?:risma)?(?:\s*Score)?\b\D{0,10}(\d{1,3})"),
        "ac": _find(r"\bAC\b\D{0,10}(\d{1,3})"),
        "hp_max": _find(r"\bHP(?:\s*Max(?:imum)?)?\b\D{0,10}(\d{1,3})"),
        "hp_current": _find(r"\bCurrent\s*Hit\s*Points?\b\D{0,10}(\d{1,3})"),
    }
    for key in missing:
        candidate = text_values.get(key)
        if candidate is None:
            continue
        if key == "name":
            output[key] = candidate
        else:
            output[key] = _parse_int(candidate)
    if output.get("hp") is None:
        if isinstance(output.get("hp_max"), int):
            output["hp"] = output.get("hp_max")
        elif isinstance(output.get("hp_current"), int):
            output["hp"] = output.get("hp_current")
    return output
