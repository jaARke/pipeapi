from pathlib import Path
from typing import Final

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from reference_app.routers import streams
from reference_app.routers.streams import sse_event
from tests.support.observations import read_observations
from tests.support.server import Server
from tests.support.targets import Target

# A WebSocket handshake or message answers in well under this.
WEBSOCKET_TIMEOUT_SECONDS: Final = 30.0


def test_an_ended_stream_sends_its_events_with_ids(target: Target) -> None:
    response = target.client.get("/events", params={"count": 3, "end": True})
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "".join(sse_event(event_id) for event_id in (1, 2, 3))


def test_a_stream_resumes_after_the_last_event_id(target: Target) -> None:
    response = target.client.get(
        "/events", params={"count": 3, "end": True}, headers={"last-event-id": "1"}
    )
    assert response.text == sse_event(2) + sse_event(3)


@pytest.mark.parametrize("last_event_id", ["one", "-1", ""])
def test_a_last_event_id_the_stream_never_sent_is_refused(
    target: Target, last_event_id: str
) -> None:
    response = target.client.get(
        "/events", params={"end": True}, headers={"last-event-id": last_event_id}
    )
    assert response.status_code == 400


def test_a_held_streams_first_event_arrives_and_the_app_sees_its_client_leave(
    under_uvicorn: Target, server: Server
) -> None:
    before = len(server.observations())
    with under_uvicorn.client.stream("GET", "/events", params={"count": 1}) as response:
        lines = response.iter_lines()
        # The stream holds after this event, so it arrived before the stream ended.
        assert [next(lines), next(lines)] == ["id: 1", "data: event 1"]
    disconnect = server.wait_for(
        lambda observation: observation["event"] == "disconnect", after=before
    )
    assert (disconnect["route"], disconnect["last_event_id"]) == ("events", 1)


def test_the_websocket_echoes_text_and_bytes_until_the_server_closes_it(
    test_client: TestClient,
) -> None:
    with test_client.websocket_connect("/ws?close_after=2&close_code=4001") as socket:
        socket.send_text("text")
        assert socket.receive_text() == "text"
        socket.send_bytes(b"bytes")
        assert socket.receive_bytes() == b"bytes"
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_text()
    assert (closed.value.code, closed.value.reason) == (4001, "closed by the server")


def test_the_app_sees_a_websocket_client_leave(
    test_client: TestClient, log: Path
) -> None:
    with test_client.websocket_connect("/ws") as socket:
        socket.send_text("once")
        assert socket.receive_text() == "once"
    disconnect = read_observations(log)[-1]
    assert (disconnect["event"], disconnect["route"], disconnect["echoed"]) == (
        "disconnect",
        "ws",
        1,
    )


def test_the_websocket_echoes_and_closes_under_uvicorn(server: Server) -> None:
    url = f"ws://{server.base_url.removeprefix('http://')}/ws?close_after=1&close_code=4002"
    with connect(url, open_timeout=WEBSOCKET_TIMEOUT_SECONDS, proxy=None) as socket:
        socket.send("over loopback")
        assert socket.recv(timeout=WEBSOCKET_TIMEOUT_SECONDS) == "over loopback"
        with pytest.raises(ConnectionClosed) as closed:
            socket.recv(timeout=WEBSOCKET_TIMEOUT_SECONDS)
    assert closed.value.rcvd is not None
    assert (closed.value.rcvd.code, closed.value.rcvd.reason) == (
        4002,
        "closed by the server",
    )


def test_the_app_sees_a_websocket_client_leave_under_uvicorn(server: Server) -> None:
    before = len(server.observations())
    url = f"ws://{server.base_url.removeprefix('http://')}/ws"
    with connect(url, open_timeout=WEBSOCKET_TIMEOUT_SECONDS, proxy=None) as socket:
        socket.send(b"\x00binary")
        assert socket.recv(timeout=WEBSOCKET_TIMEOUT_SECONDS) == b"\x00binary"
    disconnect = server.wait_for(
        lambda observation: observation["event"] == "disconnect", after=before
    )
    assert (disconnect["route"], disconnect["code"], disconnect["echoed"]) == (
        "ws",
        1000,
        1,
    )


def test_a_held_stream_ends_at_the_servers_hold_deadline(
    in_process: Target, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(streams, "HOLD_DEADLINE_SECONDS", 0)
    response = in_process.client.get("/events", params={"count": 1})
    assert response.text == sse_event(1)
    assert "disconnect" not in [o["event"] for o in in_process.observations()]


def test_an_idle_websocket_is_closed_at_the_servers_hold_deadline(
    test_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(streams, "HOLD_DEADLINE_SECONDS", 0)
    with test_client.websocket_connect("/ws?close_code=4003") as socket:
        with pytest.raises(WebSocketDisconnect) as closed:
            socket.receive_text()
    assert (closed.value.code, closed.value.reason) == (4003, "idle")
