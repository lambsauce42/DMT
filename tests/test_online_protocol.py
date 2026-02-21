import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from online_session.protocol import FrameDecoder, encode_message


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
