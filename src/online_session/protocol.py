from __future__ import annotations

import json
import struct
from typing import Any, Dict, List


_MAX_FRAME_SIZE = 16 * 1024 * 1024


def encode_message(message: Dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_FRAME_SIZE:
        raise ValueError("message too large")
    return struct.pack(">I", len(payload)) + payload


class FrameDecoder:
    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[Dict[str, Any]]:
        if data:
            self._buffer.extend(data)
        frames: List[Dict[str, Any]] = []
        while True:
            if len(self._buffer) < 4:
                break
            (size,) = struct.unpack(">I", self._buffer[:4])
            if size <= 0 or size > _MAX_FRAME_SIZE:
                raise ValueError("invalid frame size")
            if len(self._buffer) < 4 + size:
                break
            payload = bytes(self._buffer[4 : 4 + size])
            del self._buffer[: 4 + size]
            decoded = json.loads(payload.decode("utf-8"))
            if isinstance(decoded, dict):
                frames.append(decoded)
        return frames
