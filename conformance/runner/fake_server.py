import asyncio
import json
import os
import sys
import threading
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field, replace
from http import HTTPStatus
from pathlib import Path
from types import TracebackType
from typing import Any, Final, Self

import h11

from runner.contract import (
    CONTENT_TYPE_HEADER,
    JSON_LINES,
    PROTOCOL_VERSION,
    REJECTED_HEADER,
    HeaderLines,
    field_value,
    load_contract,
)
from runner.deadlines import Deadline, DeadlinePassed, wait_until
from runner.proofs import (
    PID_LIMIT,
    HelloMistake,
    decode_b64u_32,
    hello_proof,
    random_b64u_32,
)

LOOPBACK: Final = "127.0.0.1"
# The fake listens within moments of its thread starting; a hang guard.
START_GUARD_SECONDS: Final = 10.0
# The fake closes its listener, its connections and its thread at once; a hang guard.
STOP_GUARD_SECONDS: Final = 10.0
# A request a test caused reaches the fake well within this; a hang guard.
ARRIVAL_GUARD_SECONDS: Final = 30.0
READ_SIZE: Final = 65536
JSON: Final = "application/json"
CONTENT_LENGTH_HEADER: Final = "Content-Length"
CONNECTION_HEADER: Final = "Connection"
WWW_AUTHENTICATE_HEADER: Final = "WWW-Authenticate"


class FakeServerFailed(Exception):
    """
    The fake server's own code failed, it didn't listen in time, or its thread
    outlived its hang guard.
    """


class UnsupportedListener(Exception):
    """A listener the fake can't open on this OS."""


@dataclass(frozen=True)
class CannedResponse:
    """A response written as given, with a ``Content-Length`` unless it gives one."""

    status: int
    headers: HeaderLines = ()
    body: bytes = b""

    def encode(self, *, close: bool) -> bytes:
        """
        Encode the response as HTTP/1.1.

        Args:
            close: Whether the connection closes after it, which it then says.

        Returns:
            The response's bytes.
        """
        headers = list(self.headers)
        if field_value(headers, CONTENT_LENGTH_HEADER) is None:
            headers.append((CONTENT_LENGTH_HEADER, str(len(self.body))))
        if close:
            headers.append((CONNECTION_HEADER, "close"))
        return _head(self.status, headers) + self.body


@dataclass(frozen=True)
class Rejection:
    """
    A refusal as pipeapi answers one: the status, the marker, and on a 401 the
    challenge that names pipeapi's scheme.
    """

    code: str
    """The rejection's code, one the registry holds or an unknown one."""
    status: int | None = None
    """The status, or None for the one the registry gives the code."""
    headers: HeaderLines = ()
    """Further headers."""

    def __post_init__(self) -> None:
        self._status()

    def _status(self) -> int:
        contract = load_contract(PROTOCOL_VERSION)
        status = (
            contract.rejection_status(self.code) if self.status is None else self.status
        )
        if status is None:
            message = f"{self.code} is no rejection the registry holds; give a status"
            raise ValueError(message)
        return status

    def response(self) -> CannedResponse:
        """
        Make the refusal's response.

        Returns:
            The response, with an empty body.
        """
        status = self._status()
        headers = [(REJECTED_HEADER, self.code)]
        if status == HTTPStatus.UNAUTHORIZED:
            scheme = load_contract(PROTOCOL_VERSION).constant("auth_scheme")
            headers.append((WWW_AUTHENTICATE_HEADER, f'{scheme} error="{self.code}"'))
        return CannedResponse(status, (*headers, *self.headers))


@dataclass(frozen=True)
class HelloScript:
    """The server's hello, answered 200, correct unless the script says otherwise."""

    protocols: tuple[int, ...] = (PROTOCOL_VERSION,)
    features: tuple[str, ...] = ()
    pid: int | None = None
    """The PID the hello names, or None for the fake's own process."""
    mistake: HelloMistake | None = None
    """The mistake the proof is computed with, or None for a correct proof."""
    other_pid: int | None = None
    """The PID a ``RelayedProof`` covers, or None for the one after ``pid``."""
    properties: Mapping[str, Any] = field(default_factory=dict[str, Any])
    """Properties merged over the hello's own: unknown ones, or known ones replaced."""
    headers: HeaderLines = ()
    """Further response headers."""


@dataclass(frozen=True)
class Line:
    """One write of a lease stream, as one chunk, and the cue it waits for."""

    data: bytes
    """Exactly what is written, its LF included."""
    cue: str | None = None
    """The cue it waits for once the line before it is written, or None for none."""

    @classmethod
    def event(cls, event: Mapping[str, Any], *, cue: str | None = None) -> Self:
        """
        Make the line of an event.

        Args:
            event: The event.
            cue: The cue it waits for, or None.

        Returns:
            The line: the event in compact JSON, then LF.
        """
        return cls(_json_bytes(event) + b"\n", cue)

    @classmethod
    def heartbeat(cls, *, cue: str | None = None) -> Self:
        """
        Make a heartbeat's line.

        Args:
            cue: The cue it waits for, or None.

        Returns:
            The line.
        """
        return cls.event({"type": "heartbeat"}, cue=cue)

    @classmethod
    def end(cls, reason: str, *, cue: str | None = None) -> Self:
        """
        Make the line of an ``end`` event.

        Args:
            reason: Why the lease ends.
            cue: The cue it waits for, or None.

        Returns:
            The line.
        """
        return cls.event({"type": "end", "reason": reason}, cue=cue)

    def __post_init__(self) -> None:
        # An empty chunk would end the chunked body.
        if not self.data:
            raise ValueError("a line writes at least one byte")


@dataclass(frozen=True)
class LeaseScript:
    """
    A lease stream: a session event, then the lines in order, then held open until
    the client leaves or the fake stops.
    """

    lease_ttl: int | None = None
    """The session event's ``lease_ttl``."""
    session_properties: Mapping[str, Any] = field(default_factory=dict[str, Any])
    """Properties merged over the session event's own."""
    lines: tuple[Line, ...] = ()
    """The lines after the session event, each written once its cue is given."""
    headers: HeaderLines = ()
    """Further response headers."""


type HelloAnswer = HelloScript | Rejection | CannedResponse
"""What the fake answers a hello with."""

type LeaseAnswer = LeaseScript | Rejection | CannedResponse
"""What the fake answers a lease request with."""


@dataclass(frozen=True)
class FakeScript:
    """What the fake answers each request with, by default as a server would."""

    hello: HelloAnswer = field(default_factory=HelloScript)
    lease: LeaseAnswer = field(default_factory=LeaseScript)


@dataclass(frozen=True)
class TcpListener:
    """A TCP listener, on loopback by default, on a port the OS picks by default."""

    host: str = LOOPBACK
    port: int = 0


@dataclass(frozen=True)
class UnixListener:
    """A Unix domain socket's listener, on POSIX."""

    path: Path


type Listener = TcpListener | UnixListener
"""Where the fake listens."""


@dataclass(frozen=True)
class ReceivedRequest:
    """A request the fake received."""

    connection: int
    """The number of the connection it came on, from 1, in the order they opened."""
    operation: str | None
    """The ``operationId`` of the reserved route it is for, or None for none."""
    method: str
    target: str
    http_version: str
    headers: tuple[tuple[str, str], ...]
    """Its header lines, in order, repeats included, with names as the client sent."""
    body: bytes

    @property
    def path(self) -> str:
        """The target's path, without its query."""
        return self.target.split("?", 1)[0]

    def header(self, name: str) -> str | None:
        """
        Read a header's value.

        Args:
            name: The header's name, in any case.

        Returns:
            Its value, repeats joined by commas, or None when the request lacks it.
        """
        return field_value(self.headers, name)


@dataclass(frozen=True)
class LeaseRecord:
    """One lease stream the fake held, as it stood when read."""

    request: ReceivedRequest
    client_id: str
    secret: str
    lines_sent: tuple[bytes, ...]
    """The lines written so far, the session event's first."""
    lines_scripted: int
    """How many lines the stream writes in all, the session event's included."""
    open: bool
    """Whether the stream is still open."""

    @property
    def enrollment(self) -> str | None:
        """The enrollment the lease request carried, which the fake doesn't check."""
        name = load_contract(PROTOCOL_VERSION).header_name("enrollment")
        return self.request.header(name)

    @property
    def all_sent(self) -> bool:
        """Whether every scripted line has been written."""
        return len(self.lines_sent) == self.lines_scripted


@dataclass(frozen=True)
class MalformedRequest:
    """A request the fake couldn't parse as HTTP/1.1, which it answered and closed."""

    connection: int
    error: str


class FakeServer:
    """
    The runner's scriptable fake server, which stands in for a pipeapi backend.

    It runs in the runner's process, on an asyncio loop in a thread of its own, and
    listens on loopback TCP, or on a Unix domain socket on POSIX. It answers each
    hello and lease request as its script says, by default as a server would. Any
    other request under the reserved prefix, a renewal or a shutdown included, is
    refused with ``unknown_route``, and any other path is answered 404. It records
    every request and each lease stream, which tests read and wait on from their own
    thread.

    As a context manager it starts listening on the way in, and on the way out
    closes its listener, its connections and its thread, whatever the way out.
    """

    def __init__(
        self,
        token: str,
        script: FakeScript | None = None,
        listener: Listener | None = None,
        *,
        deadline: Deadline | None = None,
    ) -> None:
        self.token = token
        self.script = FakeScript() if script is None else script
        self.listener = TcpListener() if listener is None else listener
        self._deadline = deadline
        contract = load_contract(PROTOCOL_VERSION)
        self._routes = {
            (operation.method, operation.path): operation.id
            for operation in contract.operations
        }
        self._reserved_prefix = contract.constant("reserved_prefix")
        self._nonce_header = contract.header_name("nonce")
        if isinstance(self.script.hello, HelloScript):
            # A scripted mistake that needs an input the script lacks fails here.
            self._hello_proof(self.script.hello, random_b64u_32(), os.getpid())
        self._lock = threading.Lock()
        self._requests: list[ReceivedRequest] = []
        self._leases: list[LeaseRecord] = []
        self._malformed: list[MalformedRequest] = []
        self._failures: list[str] = []
        self._endpoint: str | None = None
        self._start_error: OSError | UnsupportedListener | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping: asyncio.Event | None = None
        self._stop_requested = threading.Event()
        # Only the loop's thread touches these.
        self._cues: dict[str, asyncio.Event] = {}
        self._handlers: set[asyncio.Task[Any]] = set()
        self._connections = 0
        self._clients = 0
        self._thread = threading.Thread(
            target=self._run, name="fake server", daemon=True
        )

    def __enter__(self) -> Self:
        self._thread.start()
        try:
            wait_until(
                self._listening,
                guard=START_GUARD_SECONDS,
                deadline=self._deadline,
                waiting_for="the fake server to listen",
            )
        except DeadlinePassed as passed:
            self.stop()
            raise FakeServerFailed(f"the fake server didn't listen: {passed}") from None
        except BaseException:
            self.stop()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()
        with self._lock:
            failures = list(self._failures)
        if failures:
            raise FakeServerFailed("the fake server failed:\n" + "\n".join(failures))

    @property
    def endpoint(self) -> str:
        """
        The endpoint's URL, such as ``tcp://127.0.0.1:50123``.

        Raises:
            RuntimeError: The fake hasn't listened yet.
        """
        with self._lock:
            endpoint = self._endpoint
        if endpoint is None:
            raise RuntimeError("the fake server hasn't listened yet")
        return endpoint

    def _run(self) -> None:
        asyncio.run(self._serve())

    async def _serve(self) -> None:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(self._record_failure)
        stopping = asyncio.Event()
        try:
            server, endpoint = await self._listen()
        except (OSError, UnsupportedListener) as error:
            with self._lock:
                self._start_error = error
            return
        with self._lock:
            self._loop, self._stopping, self._endpoint = loop, stopping, endpoint
        # A stop asked for before the loop was published finds no loop to signal.
        if self._stop_requested.is_set():
            stopping.set()
        async with server:
            await stopping.wait()
            server.close()
            handlers = list(self._handlers)
            for handler in handlers:
                handler.cancel()
            await asyncio.gather(*handlers, return_exceptions=True)

    async def _listen(self) -> tuple[asyncio.Server, str]:
        match self.listener:
            case TcpListener(host=host, port=port):
                server = await asyncio.start_server(self._connection, host, port)
                bound: int = server.sockets[0].getsockname()[1]
                address = f"[{host}]" if ":" in host else host
                return server, f"tcp://{address}:{bound}"
            case UnixListener(path=path):
                if sys.platform == "win32":
                    message = "a Unix domain socket needs AF_UNIX, which Python on "
                    raise UnsupportedListener(message + "Windows lacks")
                server = await asyncio.start_unix_server(self._connection, path)
                return server, f"unix://{path.as_posix()}"

    def _record_failure(
        self, loop: asyncio.AbstractEventLoop, context: dict[str, Any]
    ) -> None:
        error = context.get("exception")
        # A client that resets its connection is the client's doing, not the fake's.
        if not isinstance(error, ConnectionError):
            with self._lock:
                self._failures.append(f"{context['message']}: {error!r}")
        loop.default_exception_handler(context)

    def _listening(self) -> bool | None:
        with self._lock:
            if self._start_error is not None:
                raise self._start_error
            if self._endpoint is not None:
                return True
        if not self._thread.is_alive():
            raise FakeServerFailed("the fake server's thread ended before it listened")
        return None

    async def _connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        self._connections += 1
        number = self._connections
        parser = h11.Connection(h11.SERVER)
        try:
            # A client that leaves ends its connection's work.
            with suppress(ConnectionError):
                while True:
                    request = await self._receive(parser, reader, writer, number)
                    if request is None or not await self._answer(
                        request, reader, writer
                    ):
                        return
                    parser = _next_cycle(parser)
        finally:
            if task is not None:
                self._handlers.discard(task)
            writer.close()

    async def _receive(
        self,
        parser: h11.Connection,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        connection: int,
    ) -> ReceivedRequest | None:
        head: h11.Request | None = None
        body = bytearray()
        while True:
            try:
                event = parser.next_event()
            except h11.RemoteProtocolError as error:
                with self._lock:
                    self._malformed.append(MalformedRequest(connection, str(error)))
                status = error.error_status_hint
                writer.write(CannedResponse(status).encode(close=True))
                await writer.drain()
                return None
            if event is h11.NEED_DATA:
                parser.receive_data(await reader.read(READ_SIZE))
            elif isinstance(event, h11.Request):
                head = event
            elif isinstance(event, h11.Data):
                body += event.data
            elif isinstance(event, h11.EndOfMessage) and head is not None:
                return self._record(connection, head, bytes(body))
            elif isinstance(event, h11.ConnectionClosed):
                return None
            else:
                raise RuntimeError(f"h11 gave {event!r} before the request ended")

    def _record(
        self, connection: int, head: h11.Request, body: bytes
    ) -> ReceivedRequest:
        method = head.method.decode("ascii")
        target = head.target.decode("latin-1")
        headers = tuple(
            (name.decode("latin-1"), value.decode("latin-1"))
            for name, value in head.headers.raw_items()
        )
        request = ReceivedRequest(
            connection,
            self._routes.get((method, target.split("?", 1)[0])),
            method,
            target,
            head.http_version.decode("ascii"),
            headers,
            body,
        )
        with self._lock:
            self._requests.append(request)
        return request

    async def _answer(
        self,
        request: ReceivedRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> bool:
        # Whether the connection stays open for another request.
        answer: HelloAnswer | LeaseAnswer
        match request.operation:
            case "hello":
                answer = self.script.hello
            case "lease":
                answer = self.script.lease
            case _ if request.path.startswith(self._reserved_prefix):
                answer = Rejection("unknown_route")
            case _:
                answer = CannedResponse(HTTPStatus.NOT_FOUND)
        match answer:
            case LeaseScript():
                await self._hold_lease(answer, request, reader, writer)
                return False
            case HelloScript():
                response = self._hello(answer, request)
            case Rejection():
                response = answer.response()
            case CannedResponse():
                response = answer
        close = not _keeps_alive(request)
        writer.write(response.encode(close=close))
        await writer.drain()
        return not close

    def _hello_proof(self, script: HelloScript, nonce: str, pid: int) -> str:
        other_pid = (
            (pid + 1) % PID_LIMIT if script.other_pid is None else script.other_pid
        )
        return hello_proof(self.token, nonce, pid, script.mistake, other_pid=other_pid)

    def _hello(self, script: HelloScript, request: ReceivedRequest) -> CannedResponse:
        nonce = request.header(self._nonce_header)
        if nonce is None or not _is_b64u_32(nonce):
            return Rejection("invalid_nonce").response()
        pid = os.getpid() if script.pid is None else script.pid
        hello = {
            "protocols": list(script.protocols),
            "features": list(script.features),
            "pid": pid,
            "proof": self._hello_proof(script, nonce, pid),
            "challenge": random_b64u_32(),
            **script.properties,
        }
        headers = ((CONTENT_TYPE_HEADER, JSON), *script.headers)
        return CannedResponse(HTTPStatus.OK, headers, _json_bytes(hello))

    async def _hold_lease(
        self,
        script: LeaseScript,
        request: ReceivedRequest,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._clients += 1
        client_id = f"c{self._clients}"
        secret = random_b64u_32()
        session = {
            "type": "session",
            "client_id": client_id,
            "secret": secret,
            "lease_ttl": script.lease_ttl,
            **script.session_properties,
        }
        lines = (Line.event(session), *script.lines)
        record = LeaseRecord(request, client_id, secret, (), len(lines), open=True)
        with self._lock:
            index = len(self._leases)
            self._leases.append(record)
        try:
            headers = [
                (CONTENT_TYPE_HEADER, JSON_LINES),
                ("Transfer-Encoding", "chunked"),
                *script.headers,
            ]
            writer.write(_head(HTTPStatus.OK, headers))
            await writer.drain()
            writing = asyncio.create_task(self._write_lines(lines, writer, index))
            try:
                # Held until the client leaves; what it sends meanwhile is dropped.
                while await reader.read(READ_SIZE):
                    pass
            finally:
                writing.cancel()
                with suppress(asyncio.CancelledError, ConnectionError):
                    await writing
        finally:
            with self._lock:
                self._leases[index] = replace(self._leases[index], open=False)

    async def _write_lines(
        self, lines: tuple[Line, ...], writer: asyncio.StreamWriter, index: int
    ) -> None:
        for line in lines:
            if line.cue is not None:
                await self._cue_event(line.cue).wait()
            writer.write(b"%x\r\n%b\r\n" % (len(line.data), line.data))
            await writer.drain()
            with self._lock:
                lease = self._leases[index]
                sent = (*lease.lines_sent, line.data)
                self._leases[index] = replace(lease, lines_sent=sent)

    def _cue_event(self, name: str) -> asyncio.Event:
        if name not in self._cues:
            self._cues[name] = asyncio.Event()
        return self._cues[name]

    def _release(self, name: str) -> None:
        self._cue_event(name).set()

    def requests(self, operation: str | None = None) -> tuple[ReceivedRequest, ...]:
        """
        Read the requests received so far.

        Args:
            operation: Only those for this reserved route, by its ``operationId``,
                or None for every request.

        Returns:
            The requests, in the order they arrived.
        """
        with self._lock:
            requests = tuple(self._requests)
        if operation is None:
            return requests
        return tuple(request for request in requests if request.operation == operation)

    def leases(self) -> tuple[LeaseRecord, ...]:
        """
        Read the lease streams held so far, as each stands now.

        Returns:
            The streams, in the order their requests arrived.
        """
        with self._lock:
            return tuple(self._leases)

    def malformed_requests(self) -> tuple[MalformedRequest, ...]:
        """
        Read the requests the fake couldn't parse.

        Returns:
            Them, in the order they arrived.
        """
        with self._lock:
            return tuple(self._malformed)

    def wait_for_request(
        self, operation: str, *, count: int = 1, deadline: Deadline | None = None
    ) -> ReceivedRequest:
        """
        Wait until a number of requests for a reserved route have arrived.

        Args:
            operation: The route, by its ``operationId``.
            count: How many requests to wait for.
            deadline: The deadline of the work the wait belongs to, if any.

        Returns:
            The request that made the count.

        Raises:
            DeadlinePassed: They didn't arrive within the hang guard or the deadline.
        """

        def arrived() -> ReceivedRequest | None:
            requests = self.requests(operation)
            return requests[count - 1] if len(requests) >= count else None

        return wait_until(
            arrived,
            guard=ARRIVAL_GUARD_SECONDS,
            deadline=deadline,
            waiting_for=f"{operation} request {count} at the fake server",
        )

    def wait_for_lease(
        self,
        matches: Callable[[LeaseRecord], bool],
        waiting_for: str,
        *,
        deadline: Deadline | None = None,
    ) -> LeaseRecord:
        """
        Wait until a lease stream stands as a test needs, such as all its lines sent.

        Args:
            matches: Whether a stream stands as needed.
            waiting_for: What the wait is for, which the failure names.
            deadline: The deadline of the work the wait belongs to, if any.

        Returns:
            The first stream that matches.

        Raises:
            DeadlinePassed: None matched within the hang guard or the deadline.
        """

        def found() -> LeaseRecord | None:
            return next((lease for lease in self.leases() if matches(lease)), None)

        return wait_until(
            found,
            guard=ARRIVAL_GUARD_SECONDS,
            deadline=deadline,
            waiting_for=waiting_for,
        )

    def cue(self, name: str) -> None:
        """
        Give a cue, so every lease line that waits for it is written, now or once
        the lines before it are. A cue given stays given.

        Args:
            name: The cue.

        Raises:
            RuntimeError: The fake isn't listening.
        """
        with self._lock:
            loop = self._loop
        if loop is None:
            raise RuntimeError("the fake server isn't listening")
        loop.call_soon_threadsafe(self._release, name)

    def stop(self) -> None:
        """
        Stop: close the listener and every connection, and end the thread.

        A held lease stream breaks off, as a backend's does when it goes away.
        Stopping again does nothing.

        Raises:
            FakeServerFailed: The thread didn't end within its hang guard.
        """
        self._stop_requested.set()
        with self._lock:
            loop, stopping = self._loop, self._stopping
        if loop is not None and stopping is not None:
            # The loop has closed once the fake has stopped.
            with suppress(RuntimeError):
                loop.call_soon_threadsafe(stopping.set)
        if self._thread.ident is not None:
            self._thread.join(STOP_GUARD_SECONDS)
            if self._thread.is_alive():
                raise FakeServerFailed("the fake server's thread didn't stop")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, separators=(",", ":")).encode()


def _head(status: int, headers: HeaderLines) -> bytes:
    # By hand, not through h11, which refuses what a script may break on purpose.
    try:
        reason = HTTPStatus(status).phrase
    except ValueError:
        reason = ""
    lines = [
        f"HTTP/1.1 {status} {reason}",
        *(f"{name}: {value}" for name, value in headers),
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def _is_b64u_32(text: str) -> bool:
    try:
        decode_b64u_32(text)
    except ValueError:
        return False
    return True


def _keeps_alive(request: ReceivedRequest) -> bool:
    value = request.header(CONNECTION_HEADER) or ""
    options = {option.strip().lower() for option in value.split(",")}
    if request.http_version == "1.0":
        return "keep-alive" in options
    return "close" not in options


def _next_cycle(parser: h11.Connection) -> h11.Connection:
    # Each request gets a parser of its own, given what the last one read past its
    # request, since the fake writes its responses itself rather than through h11.
    data, closed = parser.trailing_data
    following = h11.Connection(h11.SERVER)
    # h11 reads empty data as the end of input, so it gets only what there is.
    if data:
        following.receive_data(data)
    if closed:
        following.receive_data(b"")
    return following
