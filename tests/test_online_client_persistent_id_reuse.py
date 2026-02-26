import os
import socket
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from online_session.client import OnlineSessionClient
from online_session.server import OnlineSessionServer


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_client_connect_without_persistent_id_does_not_reuse_previous_value(qtbot):
    port = _free_tcp_port()
    server = OnlineSessionServer()
    ok, err = server.start(port)
    assert ok, err

    client = OnlineSessionClient()
    logs = []
    client.log_line.connect(logs.append)

    try:
        client.connect_to_host("127.0.0.1", port, "Alice", persistent_player_id="persist-player-1")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)
        first_player_id = str(client.player_id)
        print(f"[debug] first join player_id={first_player_id!r}")
        assert first_player_id == "persist-player-1"

        client.disconnect()
        qtbot.wait(150)

        print("[debug] reconnecting without persistent_player_id")
        client.connect_to_host("127.0.0.1", port, "Bob")
        qtbot.waitUntil(lambda: client.player_id is not None, timeout=4000)

        print(f"[debug] second join player_id={client.player_id!r}; recent_logs={logs[-6:]}")
        assert client.is_connected()
        assert str(client.player_id) != first_player_id
    finally:
        client.disconnect()
        server.stop()
