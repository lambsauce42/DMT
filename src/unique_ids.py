from __future__ import annotations

import hashlib
import os
import platform
import re
import uuid
from datetime import datetime, timezone

MAX_NAMED_OBJECT_ID_LENGTH = 128
MAX_ID_TYPE_LENGTH = 24
MAX_ID_NAME_LENGTH = 48


def machine_entropy_string() -> str:
    parts = [
        os.environ.get("COMPUTERNAME", ""),
        os.environ.get("HOSTNAME", ""),
        os.environ.get("USERNAME", ""),
        os.environ.get("USER", ""),
        platform.node(),
        platform.system(),
        platform.release(),
        platform.machine(),
    ]
    return "|".join(str(value or "").strip() for value in parts if str(value or "").strip())


def sanitize_id_component(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    cleaned = cleaned.strip("._-")
    fallback_clean = re.sub(r"[^A-Za-z0-9._-]+", "_", str(fallback or "").strip())
    fallback_clean = fallback_clean.strip("._-")
    return cleaned or fallback_clean or "id"


def _trim_sanitized_component(value: str, fallback: str, max_length: int) -> str:
    cleaned = sanitize_id_component(value, fallback)
    max_len = max(1, int(max_length))
    if len(cleaned) <= max_len:
        return cleaned
    trimmed = cleaned[:max_len].strip("._-")
    return trimmed or sanitize_id_component(fallback, "id")


def generate_probabilistic_unique_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    machine_entropy = machine_entropy_string()
    random_entropy = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
    digest = hashlib.sha256(
        f"{prefix}|{timestamp}|{machine_entropy}|{random_entropy}".encode("utf-8")
    ).hexdigest()[:24]
    safe_prefix = re.sub(r"[^a-z0-9_]+", "", str(prefix or "id").strip().lower()) or "id"
    return f"{safe_prefix}_{timestamp}_{digest}_{random_entropy[:16]}"


def generate_named_object_id(name: str, object_type: str) -> str:
    safe_type = _trim_sanitized_component(object_type, "object", MAX_ID_TYPE_LENGTH)
    safe_name = _trim_sanitized_component(name, safe_type, MAX_ID_NAME_LENGTH)
    readable_prefix = sanitize_id_component(
        f"{safe_name}_{datetime.now().isoformat(timespec='seconds')}",
        safe_name,
    )
    probabilistic_suffix = generate_probabilistic_unique_id(safe_type)
    identifier = sanitize_id_component(f"{readable_prefix}_{probabilistic_suffix}", safe_type)
    if len(identifier) <= MAX_NAMED_OBJECT_ID_LENGTH:
        return identifier
    max_prefix_len = max(
        1,
        MAX_NAMED_OBJECT_ID_LENGTH - len(probabilistic_suffix) - 1,
    )
    trimmed_prefix = _trim_sanitized_component(readable_prefix, safe_name, max_prefix_len)
    return sanitize_id_component(f"{trimmed_prefix}_{probabilistic_suffix}", safe_type)
