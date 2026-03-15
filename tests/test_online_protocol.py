import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import online_session.protocol as protocol_module
from online_session.protocol import (
    CHUNKED_MESSAGE_TYPE,
    FrameDecoder,
    encode_message,
    prepare_outbound_transport_messages,
    validate_chunked_message_metadata,
)


def test_frame_round_trip_single_message():
    message = {"type": "hello", "name": "Alice"}
    encoded = encode_message(message)
    decoder = FrameDecoder()
    decoded = decoder.feed(encoded)
    assert decoded == [message]


def test_frame_round_trip_multiple_messages():
    first = {"type": "a", "value": 1}
    second = {"type": "b", "value": 2}
    encoded = encode_message(first) + encode_message(second)
    decoder = FrameDecoder()
    decoded = decoder.feed(encoded)
    assert decoded == [first, second]


def test_frame_decoder_handles_split_frames():
    message = {"type": "chat", "text": "hello"}
    encoded = encode_message(message)
    decoder = FrameDecoder()
    part_a = encoded[:5]
    part_b = encoded[5:]
    assert decoder.feed(part_a) == []
    assert decoder.feed(part_b) == [message]


def test_frame_supports_large_character_payloads_under_updated_cap():
    message = {"type": "command", "action": "sync_character_inventory", "archive_b64": "x" * (9 * 1024 * 1024)}
    encoded = encode_message(message)
    decoder = FrameDecoder()
    assert decoder.feed(encoded) == [message]


def test_frame_compresses_large_repetitive_character_payloads_below_wire_cap():
    message = {
        "type": "command",
        "action": "sync_character_inventory",
        "archive_b64": "A" * (18 * 1024 * 1024),
    }
    encoded = encode_message(message)
    decoder = FrameDecoder()
    assert decoder.feed(encoded) == [message]


def test_prepare_outbound_transport_messages_chunks_large_payloads_when_inline_limit_is_low(monkeypatch):
    monkeypatch.setattr(protocol_module, "_INLINE_MESSAGE_JSON_LIMIT_BYTES", 32)
    monkeypatch.setattr(protocol_module, "_CHUNKED_MESSAGE_SLICE_BYTES", 64)
    message = {
        "type": "command",
        "action": "sync_character_inventory",
        "payload": {"archive_b64": "A" * 512},
    }

    transport_messages = prepare_outbound_transport_messages(message)

    assert len(transport_messages) > 1
    assert all(part["type"] == CHUNKED_MESSAGE_TYPE for part in transport_messages)
    decoder = FrameDecoder()
    decoded_parts = decoder.feed(b"".join(encode_message(part) for part in transport_messages))
    assert decoded_parts == transport_messages


def test_chunked_message_metadata_rejects_oversized_claims():
    with pytest.raises(ValueError, match="too large"):
        validate_chunked_message_metadata(
            packed_size=(65 * 1024 * 1024),
            chunk_count=1,
        )


def test_chunked_message_metadata_rejects_impossible_chunk_count():
    with pytest.raises(ValueError, match="chunk count"):
        validate_chunked_message_metadata(
            packed_size=1024,
            chunk_count=4,
        )
