import base64
from collections.abc import Callable

from runner.adapter_session import AdapterSession, Message
from runner.case_run import CaseRun
from runner.registry import implements

BINARY = bytes([0, 1, 2, 253, 254, 255])


def of_socket(socket: int, event: str) -> Callable[[Message], bool]:
    """
    Match a WebSocket's events of one kind.

    Args:
        socket: The WebSocket, by its opening command's ID.
        event: The event's name.

    Returns:
        Whether an event is one of them.
    """

    def matches(message: Message) -> bool:
        return message["event"] == event and message.get("socket") == socket

    return matches


def wait_for_message(client: AdapterSession, socket: int, count: int) -> list[Message]:
    """
    Wait until a WebSocket has received some messages.

    Args:
        client: The client.
        socket: The WebSocket.
        count: How many messages to wait for.

    Returns:
        Its messages so far, in order.
    """
    matches = of_socket(socket, "websocket_message")
    client.wait_for_event(
        lambda _event: len(client.events(matches)) >= count,
        f"{count} messages on WebSocket {socket}",
    )
    return client.events(matches)


def open_socket(client: AdapterSession, backend: int, target: str) -> int:
    """
    Open a WebSocket through the connector's documented path.

    Args:
        client: The client.
        backend: The Backend.
        target: The path and query.

    Returns:
        The WebSocket, by its opening command's ID.
    """
    opened = client.call("websocket_open", backend=backend, target=target)
    opened.result()
    return opened.id


@implements("websocket.echo")
def an_echo_round_trip(run: CaseRun) -> None:
    """Check that text and binary messages echo, and that the close reaches the app."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    before = len(app.observations())
    socket = open_socket(client, backend, "/ws")
    client.call("websocket_send", socket=socket, text="hello").result()
    encoded = base64.b64encode(BINARY).decode()
    client.call("websocket_send", socket=socket, binary=encoded).result()
    received = wait_for_message(client, socket, 2)
    assert [each.get("text") or each.get("binary") for each in received] == [
        "hello",
        encoded,
    ]
    opened = [
        each
        for each in app.observations()[before:]
        if each["event"] == "request" and each["type"] == "websocket"
    ]
    assert [each["path"] for each in opened] == ["/ws"]
    client.call("websocket_close", socket=socket, code=4000, reason="done").result()
    disconnect = app.wait_for(
        lambda each: each["event"] == "disconnect" and each["route"] == "ws",
        after=before,
        deadline=run.deadline,
    )
    assert (disconnect["code"], disconnect["echoed"]) == (4000, 2)


@implements("websocket.server-close")
def a_close_from_the_server_reaches_the_client(run: CaseRun) -> None:
    """Check that the client sees the server's close code and reason."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    target = "/ws?close_after=2&close_code=4001"
    socket = open_socket(client, backend, target)
    for text in ("one", "two"):
        client.call("websocket_send", socket=socket, text=text).result()
    closed = client.wait_for_event(
        of_socket(socket, "websocket_closed"), f"WebSocket {socket} to close"
    )
    assert (closed.get("code"), closed.get("reason")) == (4001, "closed by the server")
