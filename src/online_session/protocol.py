from __future__ import annotations

import base64
import hashlib
import json
import struct
import uuid
import zlib
from typing import Any, Dict, List


# Large linked-character archives can legitimately exceed the old 16 MiB
# transport limit once they include embedded item definitions and archives.
_MAX_FRAME_SIZE = 256 * 1024 * 1024
_MAX_DECODED_PAYLOAD_SIZE = 256 * 1024 * 1024
_MAX_CHUNKED_MESSAGE_BYTES = 1024 * 1024 * 1024
_INLINE_MESSAGE_JSON_LIMIT_BYTES = 8 * 1024 * 1024
_CHUNKED_MESSAGE_SLICE_BYTES = 1024 * 1024
CHUNKED_MESSAGE_TYPE = "chunked_message_part"


def encode_message(message: Dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_DECODED_PAYLOAD_SIZE:
        raise ValueError("message payload too large")
    compressed = zlib.compress(payload)
    if len(compressed) > _MAX_FRAME_SIZE:
        raise ValueError("message too large")
    return struct.pack(">I", len(compressed)) + compressed


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
            try:
                decoded_payload = zlib.decompress(payload)
            except zlib.error as exc:
                raise ValueError(f"invalid compressed payload: {exc}") from exc
            if len(decoded_payload) > _MAX_DECODED_PAYLOAD_SIZE:
                raise ValueError("decoded payload too large")
            decoded = json.loads(decoded_payload.decode("utf-8"))
            if isinstance(decoded, dict):
                frames.append(decoded)
        return frames


def serialize_application_message(message: Dict[str, Any]) -> bytes:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > _MAX_CHUNKED_MESSAGE_BYTES:
        raise ValueError("message payload too large for chunked transport")
    return payload


def prepare_outbound_transport_messages(message: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = serialize_application_message(message)
    if len(payload) <= _INLINE_MESSAGE_JSON_LIMIT_BYTES:
        return [message]
    packed_payload = zlib.compress(payload)
    packed_hash = hashlib.sha256(packed_payload).hexdigest()
    chunk_id = uuid.uuid4().hex
    parts: List[Dict[str, Any]] = []
    total_chunks = max(1, (len(packed_payload) + _CHUNKED_MESSAGE_SLICE_BYTES - 1) // _CHUNKED_MESSAGE_SLICE_BYTES)
    for chunk_index, start in enumerate(range(0, len(packed_payload), _CHUNKED_MESSAGE_SLICE_BYTES)):
        chunk_bytes = packed_payload[start : start + _CHUNKED_MESSAGE_SLICE_BYTES]
        parts.append(
            {
                "type": CHUNKED_MESSAGE_TYPE,
                "chunk_id": chunk_id,
                "original_type": str(message.get("type") or ""),
                "chunk_index": int(chunk_index),
                "chunk_count": int(total_chunks),
                "packed_size": int(len(packed_payload)),
                "packed_sha256": packed_hash,
                "payload_b64": base64.b64encode(chunk_bytes).decode("ascii"),
            }
        )
    return parts


def decode_chunked_payload_bytes(
    *,
    payload_b64: str,
) -> bytes:
    try:
        return base64.b64decode(str(payload_b64 or "").encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError(f"invalid chunk payload: {exc}") from exc


def restore_chunked_transport_message(
    *,
    packed_payload: bytes,
    packed_sha256: str,
    packed_size: int,
) -> Dict[str, Any]:
    if len(packed_payload) != int(packed_size):
        raise ValueError("chunked payload size mismatch")
    actual_hash = hashlib.sha256(packed_payload).hexdigest()
    if actual_hash != str(packed_sha256 or "").strip():
        raise ValueError("chunked payload checksum mismatch")
    try:
        decoded_payload = zlib.decompress(packed_payload)
    except zlib.error as exc:
        raise ValueError(f"invalid chunked payload compression: {exc}") from exc
    if len(decoded_payload) > _MAX_CHUNKED_MESSAGE_BYTES:
        raise ValueError("chunked payload too large")
    try:
        restored = json.loads(decoded_payload.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid chunked message payload: {exc}") from exc
    if not isinstance(restored, dict):
        raise ValueError("chunked message payload must decode to an object")
    return restored
