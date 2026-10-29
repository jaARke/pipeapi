import asyncio
import base64
import json
import logging
import os
import urllib.parse
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Final, cast

import httpx2
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from baseline_adapter.channel import Channel
from baseline_adapter.event_stream import EventStreamParser
from baseline_adapter.messages import (
    Body,
    BodyChunkCommand,
    BodyEndCommand,
    CallFailed,
    CancelCommand,
    CloseCommand,
    Command,
    ConnectCommand,
    Refusal,
    Refused,
    RequestCommand,
    SseCommand,
    WebSocketCloseCommand,
    WebSocketOpenCommand,
    WebSocketSendCommand,
    decode_bytes,
    encode_bytes,
    language_error,
)

ADAPTER_PROTOCOL: Final = 1

CONNECTOR_NAME: Final = "baseline"

# protocol/v1/registry.yaml's constants.host, which every request carries, as a
# connector's do.
HOST: Final = "pipeapi.localhost"

# The options the plain client takes: an endpoint, and a token it ignores, since it
# holds no lease.
TAKEN_OPTIONS: Final = frozenset({"endpoint", "token"})

LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "::1"})

# A loopback connection opens or is refused within seconds, even as Windows retries
# a refused one; a hang guard.
CONNECT_TIMEOUT_SECONDS: Final = 30.0

# The reference app answers a WebSocket's opening handshake at once; a hang guard.
WEBSOCKET_OPEN_TIMEOUT_SECONDS: Final = 30.0

FORM_CONTENT_TYPE: Final = "application/x-www-form-urlencoded"

# What the HTTP and WebSocket libraries raise in a call, which the reply gives as an
# error of the language's own.
LIBRARY_ERRORS: Final = (httpx2.HTTPError, WebSocketException, OSError)

NO_DIAL: Final = "the baseline adapter's plain client has no dial()"
NO_PIPED_STDIN: Final = (
    "the baseline adapter spawns no backend, so it has no piped stdin"
)
NO_SINKS: Final = "the baseline adapter spawns no backend, so it has no sinks"

UNSUPPORTED: Final[Mapping[str, str]] = {
    "shutdown": "the baseline adapter's plain client has no shutdown()",
    "read_backend": "the baseline adapter's plain client holds no lease or session",
    "typed_request": "the baseline adapter has no typed client",
    "dial": NO_DIAL,
    "connection_write": NO_DIAL,
    "connection_close": NO_DIAL,
    "stdin_write": NO_PIPED_STDIN,
    "stdin_close": NO_PIPED_STDIN,
    "sink_resume": NO_SINKS,
}
"""Why the baseline has nothing to call for each command of the protocol it refuses."""

type Result = dict[str, object]
"""What a call returned, as its reply's ``result``."""


def hello(version: str) -> dict[str, object]:
    """
    Make the hello, which names the plain client as the baseline connector.

    Args:
        version: The baseline's version, as the conformance project gives it.

    Returns:
        The hello.
    """
    return {
        "type": "hello",
        "adapterProtocol": ADAPTER_PROTOCOL,
        "connector": {"name": CONNECTOR_NAME, "version": version},
        "pid": os.getpid(),
        "transports": ["tcp"],
        "capabilities": [],
    }


class Adapter:
    """
    Carries out the runner's commands with a plain HTTP client and WebSocket client.

    It does at the HTTP level what a connector does, minus everything pipeapi adds:
    a Backend is an :class:`httpx2.AsyncClient` for a loopback address, with proxies
    off. Each command's call runs as a task of its own, so a call that waits never
    holds up the next command, and each command gets one reply, after every event of
    its call.
    """

    def __init__(self, channel: Channel) -> None:
        self._channel = channel
        self._handlers: dict[str, Callable[[Any], Coroutine[Any, Any, Result]]] = {
            "connect": self._connect,
            "close": self._close,
            "cancel": self._cancel,
            "request": self._request,
            "body_chunk": self._body_chunk,
            "body_end": self._body_end,
            "sse": self._sse,
            "websocket_open": self._websocket_open,
            "websocket_send": self._websocket_send,
            "websocket_close": self._websocket_close,
        }
        self._backends: dict[int, _Backend] = {}
        self._bodies: dict[int, asyncio.Queue[bytes | None]] = {}
        self._sockets: dict[int, ClientConnection] = {}
        self._calls: dict[int, _Call] = {}
        self._seen: set[int] = set()
        self._receivers: set[asyncio.Task[None]] = set()

    def _write_reply(
        self, command_id: int | None, name: str | None, outcome: Mapping[str, object]
    ) -> None:
        reply = {"type": "reply", "id": command_id, "command": name, **outcome}
        self._channel.write(reply)

    def _write_event(self, event: str, **fields: object) -> None:
        self._channel.write({"type": "event", "event": event, **fields})

    async def _carry_out(self, command: Command) -> None:
        command_id, name = command["id"], command["command"]
        task = asyncio.current_task()
        assert task is not None, "each command's call runs as a task of its own"
        call = _Call(task)
        self._seen.add(command_id)
        self._calls[command_id] = call
        outcome: dict[str, object]
        try:
            handler = self._handlers.get(name)
            if handler is None:
                message = UNSUPPORTED.get(name, f"the baseline adapter has no {name}")
                raise Refused("unknown_command", message)
            outcome = {"result": await handler(command)}
        except Refused as refused:
            outcome = {"refusal": refused.refusal}
        except CallFailed as failed:
            outcome = {"languageError": failed.language_error}
        except asyncio.CancelledError as error:
            if not call.cancelled:
                raise
            outcome = {"languageError": language_error("cancellation", error)}
        except LIBRARY_ERRORS as error:
            outcome = {"languageError": language_error("other", error)}
        except Exception as error:
            _logger.exception("The adapter failed outside the call a command made")
            message = f"{type(error).__name__}: {error}"
            outcome = {"refusal": Refusal(code="adapter_error", message=message)}
        finally:
            del self._calls[command_id]
        self._write_reply(command_id, name, outcome)

    async def _connect(self, command: ConnectCommand) -> Result:
        if "logging" in command:
            message = "the baseline adapter's plain client has no logging to turn on"
            raise Refused("invalid_command", message)
        if "sinks" in command:
            raise Refused("invalid_command", NO_SINKS)
        options = command["options"]
        others = sorted(set(options) - TAKEN_OPTIONS)
        if others:
            taken = ", ".join(others)
            message = f"the baseline adapter's plain client takes no {taken}"
            raise Refused("invalid_command", message)
        host, port = _loopback_address(options.get("endpoint"))
        self._write_event("started", id=command["id"])
        netloc = f"[{host}]" if ":" in host else host
        client = httpx2.AsyncClient(
            base_url=f"http://{netloc}:{port}",
            headers={"Host": HOST},
            # Reads unbounded, since a stream the app holds stays open until a case
            # ends it.
            timeout=httpx2.Timeout(None, connect=CONNECT_TIMEOUT_SECONDS),
            # No proxy from the environment, as a connector takes none.
            trust_env=False,
        )
        self._backends[command["id"]] = _Backend(client, host, port)
        return {"clientId": None}

    async def _close(self, command: CloseCommand) -> Result:
        backend = _named(self._backends, command["backend"], "Backend")
        del self._backends[command["backend"]]
        await backend.client.aclose()
        return {}

    async def _cancel(self, command: CancelCommand) -> Result:
        target = command["commandId"]
        call = self._calls.get(target)
        if call is not None:
            call.cancelled = True
            call.task.cancel()
        elif target not in self._seen:
            raise Refused("invalid_command", f"no command has the ID {target}")
        return {}

    async def _request(self, command: RequestCommand) -> Result:
        backend = _named(self._backends, command["backend"], "Backend")
        _refuse_request_options(command)
        if command.get("validate"):
            message = "the baseline adapter has no ValidationError to apply"
            raise Refused("invalid_command", message)
        headers = _headers(command)
        content: bytes | AsyncIterator[bytes] | None = None
        files: list[tuple[str, tuple[None, str]]] | None = None
        body: Body = command.get("body", {})
        if "form" in body:
            pairs = [(name, value) for name, value in body["form"]]
            content = urllib.parse.urlencode(pairs).encode()
            if not any(name.lower() == "content-type" for name, _ in headers):
                headers.append(("Content-Type", FORM_CONTENT_TYPE))
        elif "multipart" in body:
            # Fields without file names, since httpx2 encodes a multipart form only
            # when given files.
            files = [(name, (None, value)) for name, value in body["multipart"]]
        elif "stream" in body:
            chunks = asyncio.Queue[bytes | None]()
            self._bodies[command["id"]] = chunks
            content = _streamed(chunks)
        elif body:
            content = decode_bytes(body)
        read = partial(self._read_chunks, command["id"])
        try:
            await self._exchange(
                command,
                backend,
                command["method"],
                headers,
                read,
                content=content,
                files=files,
            )
        finally:
            self._bodies.pop(command["id"], None)
        return {}

    async def _sse(self, command: SseCommand) -> Result:
        backend = _named(self._backends, command["backend"], "Backend")
        _refuse_request_options(command)
        read = partial(self._read_events, command["id"])
        await self._exchange(command, backend, "GET", _headers(command), read)
        return {}

    async def _exchange(
        self,
        command: RequestCommand | SseCommand,
        backend: _Backend,
        method: str,
        headers: list[tuple[str, str]],
        read: Callable[[httpx2.Response], Coroutine[Any, Any, None]],
        *,
        content: bytes | AsyncIterator[bytes] | None = None,
        files: list[tuple[str, tuple[None, str]]] | None = None,
    ) -> None:
        request = command["id"]
        limit = asyncio.timeout(command.get("timeout"))
        # The target goes on the request line as it is, where httpx2's URL would
        # normalize it.
        extensions = {"target": command["target"].encode()}
        self._write_event("started", id=request)
        try:
            async with (
                limit,
                backend.client.stream(
                    method,
                    "/",
                    headers=headers,
                    content=content,
                    files=files,
                    extensions=extensions,
                ) as response,
            ):
                encoding = response.headers.encoding
                received = [
                    [name.decode(encoding), value.decode(encoding)]
                    for name, value in response.headers.raw
                ]
                status = response.status_code
                self._write_event(
                    "response", request=request, status=status, headers=received
                )
                await read(response)
        except TimeoutError as error:
            if limit.expired():
                raise CallFailed("timeout", error) from None
            raise

    async def _read_chunks(self, request: int, response: httpx2.Response) -> None:
        async for chunk in response.aiter_raw():
            self._write_event("response_chunk", request=request, **encode_bytes(chunk))

    async def _read_events(self, request: int, response: httpx2.Response) -> None:
        parser = EventStreamParser()
        async for chunk in response.aiter_bytes():
            for event in parser.feed(chunk):
                self._write_event(
                    "sse_event",
                    request=request,
                    eventType=event.event_type,
                    data=event.data,
                    eventId=event.event_id,
                )

    async def _body_chunk(self, command: BodyChunkCommand) -> Result:
        chunks = _named(self._bodies, command["request"], "streamed body")
        chunks.put_nowait(decode_bytes(command))
        return {}

    async def _body_end(self, command: BodyEndCommand) -> Result:
        chunks = _named(self._bodies, command["request"], "streamed body")
        chunks.put_nowait(None)
        del self._bodies[command["request"]]
        return {}

    async def _websocket_open(self, command: WebSocketOpenCommand) -> Result:
        backend = _named(self._backends, command["backend"], "Backend")
        self._write_event("started", id=command["id"])
        # The connection goes to the Backend's address, and the Host header is the
        # URI's.
        socket = await connect(
            f"ws://{HOST}{command['target']}",
            additional_headers=_headers(command),
            proxy=None,
            open_timeout=WEBSOCKET_OPEN_TIMEOUT_SECONDS,
            host=backend.host,
            port=backend.port,
        )
        self._sockets[command["id"]] = socket
        # Not started eagerly, so its first event follows this call's reply.
        receiver = asyncio.create_task(self._receive(command["id"], socket))
        self._receivers.add(receiver)
        receiver.add_done_callback(self._receivers.discard)
        return {}

    async def _receive(self, socket_id: int, socket: ClientConnection) -> None:
        while True:
            try:
                message = await socket.recv()
            except ConnectionClosed as closed:
                # Without a close frame, the library reports an error, not a close.
                if closed.rcvd is None:
                    error = language_error("other", closed)
                    self._write_event(
                        "websocket_closed", socket=socket_id, languageError=error
                    )
                else:
                    code, reason = closed.rcvd.code, closed.rcvd.reason
                    self._write_event(
                        "websocket_closed", socket=socket_id, code=code, reason=reason
                    )
                return
            if isinstance(message, str):
                self._write_event("websocket_message", socket=socket_id, text=message)
            else:
                binary = base64.b64encode(message).decode("ascii")
                self._write_event("websocket_message", socket=socket_id, binary=binary)

    async def _websocket_send(self, command: WebSocketSendCommand) -> Result:
        socket = _named(self._sockets, command["socket"], "WebSocket")
        text = command.get("text")
        if text is not None:
            await socket.send(text)
        else:
            await socket.send(base64.b64decode(command.get("binary", "")))
        return {}

    async def _websocket_close(self, command: WebSocketCloseCommand) -> Result:
        socket = _named(self._sockets, command["socket"], "WebSocket")
        code = command.get("code")
        if code is None:
            message = "the baseline adapter's WebSocket library always sends a code"
            raise Refused("invalid_command", message)
        await socket.close(code, command.get("reason", ""))
        return {}

    def dispatch(self, line: bytes) -> None:
        """
        Start carrying out the command a line holds, or refuse a line that holds none.

        The command's task starts at once, so it refuses the command, or registers
        what a later command names, such as a streamed body, before the next line is
        dispatched.

        Args:
            line: The line, as stdin gave it.
        """
        try:
            command = _read_command(line)
        except Refused as refused:
            self._write_reply(None, None, {"refusal": refused.refusal})
            return
        asyncio.create_task(self._carry_out(command), eager_start=True)


@dataclass(frozen=True)
class _Backend:
    client: httpx2.AsyncClient
    host: str
    port: int


@dataclass
class _Call:
    task: asyncio.Task[Any]
    cancelled: bool = False


_logger: Final = logging.getLogger(__name__)


def _read_command(line: bytes) -> Command:
    try:
        message: object = json.loads(line)
    except ValueError:
        raise Refused("invalid_command", "the line isn't JSON") from None
    if not isinstance(message, dict):
        raise Refused("invalid_command", "the line isn't a command")
    fields = cast("dict[str, object]", message)
    if (
        fields.get("type") != "command"
        or type(fields.get("id")) is not int
        or not isinstance(fields.get("command"), str)
    ):
        raise Refused("invalid_command", "the line isn't a command")
    return cast("Command", fields)


def _loopback_address(endpoint: object) -> tuple[str, int]:
    if not isinstance(endpoint, str):
        message = "the baseline adapter spawns no backend, so it needs an endpoint"
        raise Refused("invalid_command", message)
    parts = urllib.parse.urlsplit(endpoint)
    host = parts.hostname
    try:
        port = parts.port
    except ValueError:
        port = None
    if parts.scheme != "tcp" or host is None or host not in LOOPBACK_HOSTS or not port:
        message = (
            "the baseline adapter's plain client needs a loopback TCP endpoint with a "
            "port, such as tcp://127.0.0.1:8123"
        )
        raise Refused("invalid_command", message)
    return host, port


def _refuse_request_options(command: RequestCommand | SseCommand) -> None:
    if command.get("options"):
        message = "the baseline adapter's plain client takes no request options"
        raise Refused("invalid_command", message)


def _headers(
    command: RequestCommand | SseCommand | WebSocketOpenCommand,
) -> list[tuple[str, str]]:
    return [(name, value) for name, value in command.get("headers", [])]


def _named[T](handles: Mapping[int, T], handle: int, kind: str) -> T:
    found = handles.get(handle)
    if found is None:
        raise Refused("invalid_command", f"no {kind} is named {handle}")
    return found


async def _streamed(chunks: asyncio.Queue[bytes | None]) -> AsyncIterator[bytes]:
    while (chunk := await chunks.get()) is not None:
        yield chunk
