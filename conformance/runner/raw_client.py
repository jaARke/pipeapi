import queue
import socket
import threading
from collections.abc import Generator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Final, Self, TypedDict, cast
from urllib.parse import urlsplit

import httpx2

from runner.cases import PLATFORM, Platform, Transport
from runner.contract import (
    LINE_END,
    PROTOCOL_VERSION,
    REJECTED_HEADER,
    Contract,
    HeaderLines,
    ResponseShape,
    field_value,
    load_contract,
)
from runner.deadlines import Deadline, wait_until
from runner.proofs import enrollment_header, hello_proof_verifies, random_b64u_32

# A reserved route answers, and a connection opens, in well under this; a hang guard.
REQUEST_GUARD_SECONDS: Final = 30.0
# A server writes a heartbeat every heartbeat_interval (15 s), so a correct lease
# stream's next line comes well within this; a hang guard.
LEASE_LINE_GUARD_SECONDS: Final = 60.0
# A lease's reader thread ends at once once its socket is shut down; a hang guard.
READER_STOP_GUARD_SECONDS: Final = 10.0

TRANSPORTS_ON: Final[Mapping[Platform, frozenset[Transport]]] = {
    "posix": frozenset({"unix", "tcp"}),
    # Python on Windows has no AF_UNIX, and httpx2 opens no named pipe.
    "windows": frozenset({"tcp"}),
}
"""The transports the raw client reaches on each platform, named as their schemes."""
TRANSPORTS: Final = TRANSPORTS_ON[PLATFORM]
"""The transports the raw client reaches on this platform."""

type LeaseEvent = Mapping[str, Any]
"""One event of a lease stream, checked against the item schema."""


class UnsupportedEndpoint(Exception):
    """An endpoint the raw client can't reach: an unknown scheme, or not on this OS."""


class UnexpectedStatus(AssertionError):
    """A response whose status a call can't go on from, such as a refused lease's."""


class ReaderStuck(Exception):
    """A lease stream's reader thread didn't stop within its hang guard."""


@dataclass(frozen=True)
class ReceivedResponse:
    """A response of a reserved route, checked against the protocol's document."""

    status: int
    headers: tuple[tuple[str, str], ...]
    """Its header lines, in order, repeats included, with names as the server sent."""
    body: bytes
    """Its body, empty for a stream, whose lines are read one at a time."""
    value: Any
    """The body parsed: a JSON value, or None for a stream or a response without
    content."""

    def header(self, name: str) -> str | None:
        """
        Read a header's value.

        Args:
            name: The header's name, in any case.

        Returns:
            Its value, repeats joined by commas, or None when the response lacks it.
        """
        return field_value(self.headers, name)


class HelloBody(TypedDict):
    """The server's hello, once checked against the hello schema."""

    protocols: list[int]
    features: list[str]
    pid: int
    proof: str
    challenge: str


@dataclass(frozen=True)
class HelloResponse:
    """The answer to a hello, and the nonce the hello carried."""

    nonce: str
    response: ReceivedResponse
    body: HelloBody | None
    """The hello a 200 carries; None for any other status, which carries none."""

    def proof_verifies(self, token: str) -> bool:
        """
        Check the hello's proof for a token, the nonce and the PID the hello names.

        Args:
            token: The token.

        Returns:
            Whether the proof is the one the rules give.

        Raises:
            UnexpectedStatus: The hello was refused, so it carries no proof.
        """
        if self.body is None:
            message = f"the hello was answered {self.response.status}, with no proof"
            raise UnexpectedStatus(message)
        return hello_proof_verifies(
            self.body["proof"], token=token, nonce=self.nonce, pid=self.body["pid"]
        )


@dataclass(frozen=True)
class LeaseEnd:
    """How a lease stream ended."""

    complete: bool
    """Whether the server finished the response, rather than it breaking off."""
    error: str | None
    """Why it broke off, or None when it is complete."""


class LeaseStream:
    """
    The answer to a lease request, whose events it reads one line at a time.

    A thread reads the stream's lines as they come, and :meth:`read_event` checks
    each against the item schema as it takes it. Closing it shuts the connection
    down, which ends the thread at once.
    """

    def __init__(
        self,
        contract: Contract,
        shape: ResponseShape,
        response: httpx2.Response,
        received: ReceivedResponse,
    ) -> None:
        self.response = received
        """The response, whose body is empty for a stream."""
        self._contract = contract
        self._shape = shape
        self._http = response
        self._events: list[LeaseEvent] = []
        self._end: LeaseEnd | None = None
        self._lines: queue.SimpleQueue[bytes | LeaseEnd] = queue.SimpleQueue()
        self._reader: threading.Thread | None = None
        if shape.streamed:
            self._reader = threading.Thread(
                target=self._read, name="lease reader", daemon=True
            )
            self._reader.start()

    @property
    def status(self) -> int:
        """The response's status."""
        return self.response.status

    @property
    def events(self) -> tuple[LeaseEvent, ...]:
        """The events read so far, in order."""
        return tuple(self._events)

    @property
    def end(self) -> LeaseEnd | None:
        """How the stream ended, once a read found its end, or None before."""
        return self._end

    def _read(self) -> None:
        end = LeaseEnd(complete=False, error="the reader thread failed")
        pending = b""
        try:
            for chunk in self._http.iter_bytes():
                *lines, pending = (pending + chunk).split(LINE_END)
                for line in lines:
                    self._lines.put(line + LINE_END)
            # The line the stream ended within, without its LF, which the contract
            # refuses.
            if pending:
                self._lines.put(pending)
            end = LeaseEnd(complete=True, error=None)
        except httpx2.HTTPError as error:
            end = LeaseEnd(complete=False, error=f"{type(error).__name__}: {error}")
        finally:
            self._lines.put(end)

    def _take(self) -> bytes | LeaseEnd | None:
        try:
            return self._lines.get_nowait()
        except queue.Empty:
            return None

    def read_event(self, deadline: Deadline | None = None) -> LeaseEvent | None:
        """
        Read the stream's next event, checked against the item schema.

        Args:
            deadline: The deadline of the work the read belongs to, if any.

        Returns:
            The event, or None once the stream has ended, as :attr:`end` then says.

        Raises:
            UnexpectedStatus: The lease was refused, so it has no stream.
            ContractViolation: The line doesn't end in LF alone, isn't JSON or
                doesn't meet the item schema.
            DeadlinePassed: No line came within the hang guard or the deadline.
        """
        if not self._shape.streamed:
            marker = self.response.header(REJECTED_HEADER)
            refusal = "" if marker is None else f" with {REJECTED_HEADER} {marker}"
            message = f"the lease was answered {self.status}{refusal}, with no stream"
            raise UnexpectedStatus(message)
        if self._end is not None:
            return None
        item = wait_until(
            self._take,
            guard=LEASE_LINE_GUARD_SECONDS,
            deadline=deadline,
            waiting_for="the lease stream's next line",
        )
        if isinstance(item, LeaseEnd):
            self._end = item
            return None
        number = len(self._events) + 1
        event = cast(
            "LeaseEvent", self._contract.check_stream_line(self._shape, item, number)
        )
        self._events.append(event)
        return event

    def close(self) -> None:
        """
        Close the stream, ending its reader thread.

        Raises:
            ReaderStuck: The reader thread didn't end within its hang guard.
        """
        reader = self._reader
        if reader is not None and reader.is_alive():
            # A blocked read ends once its socket is shut down; closing it from another
            # thread doesn't wake the read on every OS.
            stream = self._http.extensions.get("network_stream")
            if stream is not None:
                connection = cast("socket.socket", stream.get_extra_info("socket"))
                with suppress(OSError):
                    connection.shutdown(socket.SHUT_RDWR)
            reader.join(READER_STOP_GUARD_SECONDS)
            if reader.is_alive():
                raise ReaderStuck("the lease stream's reader thread didn't end")
        self._http.close()


class RawClient:
    """
    The runner's raw client of one pipeapi endpoint, which checks all it receives.

    It sends what the protocol asks: the ``Host`` the registry names on every
    request, no ``Origin``, no proxy from the environment, and each call's waits
    bounded. A case adds or replaces headers through each call's ``headers``. Every
    response of a reserved route and every line of a lease stream is checked
    against the protocol's OpenAPI document by :class:`~runner.contract.Contract`,
    so a server that drifts from the document fails the case by name.

    It reaches the transports :data:`TRANSPORTS` names: ``tcp://127.0.0.1:<port>``
    and ``tcp://[::1]:<port>`` on every OS, and ``unix://<path>`` on POSIX.
    """

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self._contract = load_contract(PROTOCOL_VERSION)
        host = self._contract.constant("host")
        base_url, transport = _connection(endpoint, host)
        self._http = httpx2.Client(
            base_url=base_url,
            transport=transport,
            headers={"Host": host},
            timeout=REQUEST_GUARD_SECONDS,
            trust_env=False,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the client and its connections."""
        self._http.close()

    def request(
        self,
        operation_id: str,
        *,
        headers: HeaderLines = (),
        content: bytes | None = None,
        deadline: Deadline | None = None,
    ) -> ReceivedResponse:
        """
        Send a reserved route's request, by its operation, and check its response.

        It suits an operation that answers with a whole body; :meth:`lease` reads a
        stream.

        Args:
            operation_id: The operation, by its ``operationId``, such as ``renew``.
            headers: The request's headers, beside ``Host``.
            content: The request's body, if any.
            deadline: The deadline of the work the request belongs to, if any.

        Returns:
            The response, checked.

        Raises:
            ContractViolation: The response doesn't meet the protocol's document.
            DeadlinePassed: The deadline has already passed.
            httpx2.HTTPError: The request failed or outlasted its bounds.
        """
        operation = self._contract.operation(operation_id)
        seconds = _bounded(REQUEST_GUARD_SECONDS, deadline, f"{operation_id} answer")
        response = self._http.request(
            operation.method,
            operation.path,
            headers=list(headers),
            content=content,
            timeout=seconds,
        )
        lines = _header_lines(response)
        shape = self._contract.check_head(operation_id, response.status_code, lines)
        value = self._contract.check_body(shape, response.content)
        return ReceivedResponse(response.status_code, lines, response.content, value)

    def hello(
        self,
        *,
        nonce: str | None = None,
        headers: HeaderLines = (),
        deadline: Deadline | None = None,
    ) -> HelloResponse:
        """
        Send a hello, and check its answer.

        Args:
            nonce: The nonce to send, or None for a fresh one.
            headers: Headers to add, or to replace the nonce's.
            deadline: The deadline of the work the hello belongs to, if any.

        Returns:
            The answer, with the nonce the hello carried.

        Raises:
            ContractViolation: The answer doesn't meet the protocol's document.
            DeadlinePassed: The deadline has already passed.
            httpx2.HTTPError: The request failed or outlasted its bounds.
        """
        sent = random_b64u_32() if nonce is None else nonce
        nonce_header = self._contract.header_name("nonce")
        received = self.request(
            "hello",
            headers=_merged([(nonce_header, sent)], headers),
            deadline=deadline,
        )
        body = None if received.value is None else cast("HelloBody", received.value)
        return HelloResponse(sent, received, body)

    @contextmanager
    def lease(
        self,
        hello: HelloResponse,
        token: str,
        *,
        headers: HeaderLines = (),
        deadline: Deadline | None = None,
    ) -> Generator[LeaseStream]:
        """
        Open a lease, enrolling with the hello's challenge, as a stream.

        The request carries the protocol version and the enrollment its token and
        the hello's challenge give, unless ``headers`` replaces them.

        Args:
            hello: The hello whose challenge the enrollment answers.
            token: The token.
            headers: Headers to add, or to replace the protocol's or the enrollment's.
            deadline: The deadline of the work the lease belongs to, if any.

        Yields:
            The stream, which closes on the way out, whatever the way.

        Raises:
            UnexpectedStatus: The hello was refused, so it has no challenge.
            ContractViolation: The answer doesn't meet the protocol's document.
            DeadlinePassed: The deadline has already passed.
            httpx2.HTTPError: The request failed or outlasted its bounds.
        """
        if hello.body is None:
            message = f"the hello was answered {hello.response.status}, no challenge"
            raise UnexpectedStatus(message)
        operation = self._contract.operation("lease")
        defaults = [
            (self._contract.header_name("protocol"), str(PROTOCOL_VERSION)),
            (
                self._contract.header_name("enrollment"),
                enrollment_header(token, hello.body["challenge"]),
            ),
        ]
        # Each read of the stream waits up to the read bound; reads wait for lines.
        timeout = httpx2.Timeout(
            _bounded(REQUEST_GUARD_SECONDS, deadline, "the lease's answer"),
            read=_bounded(LEASE_LINE_GUARD_SECONDS, deadline, "the lease's answer"),
        )
        request = self._http.build_request(
            operation.method,
            operation.path,
            headers=_merged(defaults, headers),
            timeout=timeout,
        )
        response = self._http.send(request, stream=True)
        try:
            lines = _header_lines(response)
            shape = self._contract.check_head(operation.id, response.status_code, lines)
            body = b"" if shape.streamed else response.read()
            value = None if shape.streamed else self._contract.check_body(shape, body)
            received = ReceivedResponse(response.status_code, lines, body, value)
            stream = LeaseStream(self._contract, shape, response, received)
            try:
                yield stream
            finally:
                stream.close()
        finally:
            response.close()


def _header_lines(response: httpx2.Response) -> tuple[tuple[str, str], ...]:
    return tuple(
        (name.decode("latin-1"), value.decode("latin-1"))
        for name, value in response.headers.raw
    )


def _merged(defaults: HeaderLines, headers: HeaderLines) -> list[tuple[str, str]]:
    # A header the case gives replaces the default of its name.
    given = {name.lower() for name, _ in headers}
    kept = [(name, value) for name, value in defaults if name.lower() not in given]
    return [*kept, *headers]


def _bounded(guard: float, deadline: Deadline | None, waiting_for: str) -> float:
    return guard if deadline is None else deadline.bound(guard, waiting_for)


def _connection(endpoint: str, host: str) -> tuple[str, httpx2.HTTPTransport]:
    # The base URL the client sends to, and the transport that reaches the endpoint.
    parts = urlsplit(endpoint)
    if parts.scheme not in TRANSPORTS:
        reached = ", ".join(sorted(TRANSPORTS))
        message = (
            f"the raw client reaches no {parts.scheme}:// endpoint here: {reached}"
        )
        raise UnsupportedEndpoint(message)
    if parts.scheme == "unix":
        return f"http://{host}", httpx2.HTTPTransport(uds=parts.path, trust_env=False)
    if parts.hostname is None or parts.port is None:
        raise UnsupportedEndpoint(f"{endpoint} names no host and port")
    address = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
    return f"http://{address}:{parts.port}", httpx2.HTTPTransport(trust_env=False)
