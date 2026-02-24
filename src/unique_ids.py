from __future__ import annotations

import hashlib
import os
import platform
import re
import uuid
from datetime import datetime, timezone


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


def generate_probabilistic_unique_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    machine_entropy = machine_entropy_string()
    random_entropy = f"{uuid.uuid4().hex}{uuid.uuid4().hex}"
    digest = hashlib.sha256(
        f"{prefix}|{timestamp}|{machine_entropy}|{random_entropy}".encode("utf-8")
    ).hexdigest()[:24]
    safe_prefix = re.sub(r"[^a-z0-9_]+", "", str(prefix or "id").strip().lower()) or "id"
    return f"{safe_prefix}_{timestamp}_{digest}_{random_entropy[:16]}"
