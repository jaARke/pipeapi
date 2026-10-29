import base64
import codecs
import json
import subprocess
import threading
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import IO, Any, Final, cast

from jsonschema.protocols import Validator
from pydantic import BaseModel

from runner.adapters import ADAPTER_PROTOCOL, SCRIPTS, AdapterManifest
from runner.cases import Via
from runner.deadlines import Deadline, DeadlinePassed, wait_until
from runner.processes import (
    Changes,
    ForeignProcess,
    Prepended,
    Process,
    Processes,
    StdinStuck,
)
from runner.schemas import parse_json, validator
from runner.trace import Trace

SCHEMA_FILE_NAME: Final = "adapter-protocol.schema.json"

# An adapter loads its connector and writes its hello in a few seconds, even a
# runtime that starts slowly on a cold CI runner.
HELLO_GUARD_SECONDS: Final = 60.0

# A command's call returns in well under this unless the case waits on purpose, in
# which case it passes a guard of its own.
REPLY_GUARD_SECONDS: Final = 30.0

# An adapter exits at once at the end of its stdin.
EXIT_GUARD_SECONDS: Final = 10.0

# Once an adapter has ended, its stdout ends and the reader takes what the pipe still
# holds at once, unless a process the adapter started holds the pipe open.
STDOUT_END_GUARD_SECONDS: Final = 10.0

# An adapter reads each command as it arrives, so the pipe takes a line at once.
WRITE_GUARD_SECONDS: Final = 30.0

# How many of the adapter's last stderr lines a fault quotes.
STDERR_TAIL_LINES: Final = 20

# What the trace's record of a command shows in place of a secret it carries, so the
# trace holds a secret only where something else wrote it.
REDACTED: Final = "[secret]"

type Message = dict[str, Any]
"""One message of the adapter protocol, as JSON."""


type Headers = tuple[tuple[str, str], ...]
"""Headers in order, a name repeated for each of its values."""


class AdapterFault(Exception):
    """
    A fault of the runner or an adapter, never the connector's behavior.

    An adapter that breaks the protocol, refuses a command, takes no command or
    writes no hello in time, or exits early raises it, and so does a command the
    runner writes that the protocol's schema refuses. It isn't an assertion, so no
    expected failure covers it.
    """


@dataclass(frozen=True)
class Hello:
    """What an adapter's hello says."""

    protocol: int
    """The adapter protocol version it speaks."""
    connector: str
    version: str
    pid: int
    """The PID of the client process, the adapter itself."""
    transports: frozenset[str]
    """The connector's transports on this platform, as the connector API names them."""
    capabilities: frozenset[str]


@dataclass(frozen=True)
class Reply:
    """An adapter's reply to a command whose call returned or failed."""

    id: int
    command: str
    message: Message

    def result(self) -> Message:
        """
        Take what the call returned.

        Returns:
            The reply's result.

        Raises:
            AssertionError: The call failed instead, with the error it gave.
        """
        if "result" in self.message:
            result: Message = self.message["result"]
            return result
        outcome = self.message.get("error") or self.message.get("languageError")
        raise AssertionError(f"command {self.id} ({self.command}) failed: {outcome}")


@dataclass(frozen=True)
class Response:
    """A response as an adapter reported it."""

    status: int
    headers: Headers
    """Its headers, as the adapter's client gave them."""
    body: bytes

    def values(self, name: str) -> list[str]:
        """
        Find a header's values.

        Args:
            name: The header's name, in any case.

        Returns:
            Its values, in order.
        """
        return [value for each, value in self.headers if each.lower() == name.lower()]

    def answer[ModelT: BaseModel](self, model: type[ModelT]) -> ModelT:
        """
        Read the body as a route's JSON answer, through the app's own model of it.

        Args:
            model: The model the route answers with, from the reference app.

        Returns:
            The answer.
        """
        return model.model_validate_json(self.body)


def bytes_of(message: Mapping[str, Any]) -> bytes:
    """
    Read the bytes a message carries as text or in base64.

    Args:
        message: The message.

    Returns:
        The bytes.
    """
    if "text" in message:
        text: str = message["text"]
        return text.encode()
    encoded: str = message["base64"]
    return base64.b64decode(encoded)


def versions() -> dict[int, Path]:
    """
    Find each adapter protocol version the runner speaks, by its directory.

    Returns:
        Each version with its schema's file.
    """
    found: dict[int, Path] = {}
    for schema in ADAPTER_PROTOCOL.glob(f"v*/{SCHEMA_FILE_NAME}"):
        number = schema.parent.name.removeprefix("v")
        if number.isdecimal():
            found[int(number)] = schema
    return found


class AdapterSession:
    """
    One running adapter, driven over the adapter protocol.

    It reads the adapter's stdout and stderr on threads of their own, checks every
    line both ways against the schema of the version the hello names, and writes
    each line to the trace. Commands go out from one thread, the caller's.
    """

    def __init__(
        self,
        name: str,
        process: Process,
        trace: Trace,
        deadline: Deadline,
        secrets: Collection[str] = (),
    ) -> None:
        self.name = name
        """What the adapter is to the case, such as ``adapter 1``."""
        self.process = process
        self._trace = trace
        self._deadline = deadline
        self._secrets = tuple(secrets)
        self._condition = threading.Condition()
        self._transcript: list[Message] = []
        self._sent: dict[int, str] = {}
        self._replies: dict[int, Reply] = {}
        self._fault: str | None = None
        self._fault_raised = False
        self._fault_cut = False
        self._ended = False
        self._closed = False
        self._stderr: list[str] = []
        self._next_id = 1
        self._version: int | None = None
        self._readers = [
            self._read(self._stdout_lines, "stdout"),
            self._read(self._stderr_lines, "stderr"),
        ]
        self.hello = self._wait_for_hello()
        try:
            process.identify_program(self.hello.pid)
        except ForeignProcess as foreign:
            raise AdapterFault(f"{self.name}'s hello is wrong: {foreign}") from foreign

    def _wait_for_hello(self) -> Hello:
        def found() -> Message | None:
            with self._condition:
                self._raise_fault()
                if self._transcript:
                    return self._transcript[0]
                if self._ended:
                    message = f"{self.name} ended before its hello"
                    raise AdapterFault(message + self._stderr_tail())
            return None

        try:
            hello = wait_until(
                found,
                guard=HELLO_GUARD_SECONDS,
                deadline=self._deadline,
                waiting_for=f"the hello of {self.name}",
            )
        except DeadlinePassed as passed:
            message = f"{self.name} wrote no hello: {passed}"
            raise AdapterFault(message + self._stderr_tail()) from passed
        return Hello(
            protocol=hello["adapterProtocol"],
            connector=hello["connector"]["name"],
            version=hello["connector"]["version"],
            pid=hello["pid"],
            transports=frozenset(hello["transports"]),
            capabilities=frozenset(hello["capabilities"]),
        )

    def _wait[T](self, found: Callable[[], T | None], guard: float, what: str) -> T:
        try:
            return wait_until(
                found, guard=guard, deadline=self._deadline, waiting_for=what
            )
        except DeadlinePassed as passed:
            passed.add_note(f"{self.name}'s stderr ends:{self._stderr_tail()}")
            raise

    def _check(self, message: Message, what: str) -> None:
        version = self._version
        if version is None:
            return
        error = _schema_error(version, message)
        if error is not None:
            raise AdapterFault(f"{what} breaks the schema at {error}")

    def _read(
        self, lines: Callable[[], Iterable[bytes]], stream: str
    ) -> threading.Thread:
        def read() -> None:
            for line in lines():
                self._take(stream, line)
            with self._condition:
                if stream == "stdout":
                    self._ended = True
                self._condition.notify_all()

        thread = threading.Thread(
            target=read, name=f"{self.name} {stream}", daemon=True
        )
        thread.start()
        return thread

    def _stdout_lines(self) -> Iterable[bytes]:
        return self._lines_of(self.process.popen.stdout)

    def _stderr_lines(self) -> Iterable[bytes]:
        return self._lines_of(self.process.popen.stderr)

    def _lines_of(self, stream: IO[bytes] | None) -> Iterable[bytes]:
        if stream is None:
            return
        with stream:
            yield from iter(stream.readline, b"")

    def _take(self, stream: str, raw: bytes) -> None:
        text = raw.decode(errors="replace")
        if stream == "stderr":
            line = text.rstrip("\r\n")
            self._trace.record(f"{self.name} stderr", line)
            with self._condition:
                self._stderr.append(line)
            return
        self._trace.record(f"{self.name} stdout", text.rstrip("\n"))
        with self._condition:
            parsed = self._parse(raw)
            if isinstance(parsed, str):
                fault = f"{self.name} wrote {parsed}: {text!r}"
            else:
                fault = self._file(parsed)
            if fault is not None and self._fault is None:
                self._fault = fault
                # Only the last line can lack its LF, and a kill can cut it short.
                self._fault_cut = not raw.endswith(b"\n")
            self._condition.notify_all()

    def _parse(self, raw: bytes) -> Message | str:
        # The message a line holds, or how the line breaks the protocol.
        if not raw.endswith(b"\n") or raw.endswith(b"\r\n"):
            return "a line that doesn't end in LF alone"
        if raw.startswith(codecs.BOM_UTF8):
            return "a line that starts with a byte order mark"
        try:
            decoded: Any = parse_json(raw)
        except ValueError as error:
            return f"a line that isn't JSON ({error})"
        if not isinstance(decoded, dict):
            return "a line that isn't an object"
        message = cast("Message", decoded)
        if self._version is None:
            version = message.get("adapterProtocol")
            speaks = versions()
            if message.get("type") != "hello":
                return "a line before its hello"
            if not isinstance(version, int) or version not in speaks:
                known = ", ".join(str(each) for each in sorted(speaks))
                return f"a hello naming adapter protocol {version}, not {known}"
            self._version = version
        elif message.get("type") not in {"reply", "event"}:
            return "a line that is neither a reply nor an event"
        error = _schema_error(self._version, message)
        if error is not None:
            return f"a line that breaks the schema at {error}"
        return message

    def _file(self, message: Message) -> str | None:
        # Files a message, or says how it breaks the protocol.
        self._transcript.append(message)
        if message["type"] != "reply":
            return None
        reply_id = message["id"]
        if not isinstance(reply_id, int):
            refusal = message.get("refusal", {})
            return f"{self.name} couldn't read a command: {refusal}"
        sent = self._sent.get(reply_id)
        if sent is None:
            return f"{self.name} replied to command {reply_id}, which was never sent"
        if message["command"] != sent:
            named = message["command"]
            return f"{self.name} replied to command {reply_id}, a {sent}, as a {named}"
        if reply_id in self._replies:
            return f"{self.name} replied twice to command {reply_id}"
        self._replies[reply_id] = Reply(reply_id, sent, message)
        # A refusal is the runner's or the adapter's fault, so it fails the session
        # whether or not anything waits for this reply.
        refusal = message.get("refusal")
        if refusal is not None:
            code, text = refusal["code"], refusal["message"]
            return f"{self.name} refused command {reply_id} ({sent}): {code}: {text}"
        return None

    def _raise_fault(self) -> None:
        if self._fault is not None:
            self._fault_raised = True
            raise AdapterFault(self._fault + self._stderr_tail())

    def _unraised_fault(self) -> str | None:
        # The fault a line showed that no wait has raised, which closing raises.
        with self._condition:
            if self._fault is None or self._fault_raised:
                return None
            if self._fault_cut and self.process.killed:
                return None
            self._fault_raised = True
            return self._fault

    def _read_to_the_end(self) -> None:
        def ended() -> bool | None:
            with self._condition:
                return True if self._ended else None

        try:
            wait_until(
                ended,
                guard=STDOUT_END_GUARD_SECONDS,
                deadline=None,
                waiting_for=f"the stdout of {self.name} to end",
            )
        except DeadlinePassed as passed:
            held = "a process it started may hold it open"
            self._trace.record(self.name, f"{passed}, which {held}")

    def _stderr_tail(self) -> str:
        with self._condition:
            tail = self._stderr[-STDERR_TAIL_LINES:]
        return "".join(f"\n    {line}" for line in tail)

    def _write(self, data: bytes, what: str) -> None:
        try:
            self.process.write(
                data, guard=WRITE_GUARD_SECONDS, deadline=self._deadline, what=what
            )
        except (StdinStuck, OSError) as error:
            message = f"{self.name} took no {what}: {error}"
            raise AdapterFault(message + self._stderr_tail()) from error

    def _redacted(self, line: str) -> str:
        for secret in self._secrets:
            line = line.replace(secret, REDACTED)
        return line

    def send(self, command: str, **fields: object) -> int:
        """
        Write a command, checked against the schema first.

        Args:
            command: The command's name.
            **fields: Its fields, as the schema names them.

        Returns:
            The command's ID.

        Raises:
            AdapterFault: The schema refuses the command, or the adapter takes none.
        """
        command_id = self._next_id
        self._next_id += 1
        message: Message = {
            "type": "command",
            "id": command_id,
            "command": command,
            **fields,
        }
        self._check(message, "the runner's command")
        line = json.dumps(message, separators=(",", ":"))
        with self._condition:
            self._sent[command_id] = command
            self._transcript.append(message)
        self._trace.record(f"{self.name} stdin", self._redacted(line))
        self._write(line.encode() + b"\n", f"command {command_id}")
        return command_id

    def reply(self, command_id: int, guard: float = REPLY_GUARD_SECONDS) -> Reply:
        """
        Wait for a command's reply.

        Args:
            command_id: The command's ID.
            guard: The wait's hang guard, in seconds.

        Returns:
            The reply.

        Raises:
            AdapterFault: The adapter refused the command, broke the protocol or
                exited first.
        """

        def found() -> Reply | None:
            with self._condition:
                self._raise_fault()
                reply = self._replies.get(command_id)
                if reply is None and self._ended:
                    message = f"{self.name} ended before replying to {command_id}"
                    raise AdapterFault(message + self._stderr_tail())
            return reply

        return self._wait(found, guard, f"the reply to command {command_id}")

    def call(self, command: str, **fields: object) -> Reply:
        """
        Write a command and wait for its reply.

        Args:
            command: The command's name.
            **fields: Its fields.

        Returns:
            The reply.
        """
        return self.reply(self.send(command, **fields))

    def transcript(self) -> list[Message]:
        """
        Take the session so far, as the adapter protocol's examples write one.

        Returns:
            The hello, then each command the runner wrote and each reply and event the
            adapter wrote, in the order the runner wrote or read them.
        """
        with self._condition:
            return list(self._transcript)

    def events(
        self,
        matches: Callable[[Message], bool] | None = None,
        *,
        before: Message | None = None,
    ) -> list[Message]:
        """
        Take the events the adapter has written so far, or those before one of them.

        Args:
            matches: Which events to take, or None for all.
            before: An event the adapter wrote, before which to take them, or None.

        Returns:
            The events, in the order the adapter wrote them.

        Raises:
            ValueError: The adapter wrote no such event as ``before``.
        """
        with self._condition:
            every = [each for each in self._transcript if each["type"] == "event"]
        if before is not None:
            index = next((i for i, each in enumerate(every) if each is before), None)
            if index is None:
                raise ValueError(f"{self.name} wrote no such event: {before}")
            every = every[:index]
        return [each for each in every if matches is None or matches(each)]

    def wait_for_event(
        self,
        matches: Callable[[Message], bool],
        waiting_for: str,
        guard: float = REPLY_GUARD_SECONDS,
    ) -> Message:
        """
        Wait for the first event that matches.

        Args:
            matches: Whether an event is the one awaited.
            waiting_for: What the event is, which a failure names.
            guard: The wait's hang guard, in seconds.

        Returns:
            The event.

        Raises:
            AdapterFault: The adapter broke the protocol or exited first.
        """

        def found() -> Message | None:
            with self._condition:
                self._raise_fault()
                for message in self._transcript:
                    if message["type"] == "event" and matches(message):
                        return message
                if self._ended:
                    message_text = f"{self.name} ended before {waiting_for}"
                    raise AdapterFault(message_text + self._stderr_tail())
            return None

        return self._wait(found, guard, waiting_for)

    def connect(self, options: Mapping[str, object]) -> int:
        """
        Call ``connect()`` and wait for it to return.

        Args:
            options: The options, as the connector API spells them.

        Returns:
            The Backend's name, the connect command's ID.
        """
        reply = self.call("connect", options=dict(options))
        reply.result()
        return reply.id

    def send_request(
        self,
        backend: int,
        method: str,
        target: str,
        *,
        via: Via = "untyped",
        headers: Iterable[tuple[str, str]] = (),
        body: Mapping[str, object] | None = None,
    ) -> int:
        """
        Send a request without waiting for it, such as one with a streamed body.

        Args:
            backend: The Backend.
            method: The method.
            target: The path and query, as they go out.
            via: What the request goes through.
            headers: Headers beside those the connector adds.
            body: The body, as the adapter protocol writes one.

        Returns:
            The request's name, its command's ID.
        """
        fields: dict[str, object] = {
            "backend": backend,
            "via": via,
            "method": method,
            "target": target,
            "headers": [list(header) for header in headers],
        }
        if body is not None:
            fields["body"] = dict(body)
        return self.send("request", **fields)

    def request(
        self,
        backend: int,
        method: str,
        target: str,
        *,
        via: Via = "untyped",
        headers: Iterable[tuple[str, str]] = (),
        body: Mapping[str, object] | None = None,
    ) -> Response:
        """
        Send a request and wait for its whole response.

        Args:
            backend: The Backend.
            method: The method.
            target: The path and query, as they go out.
            via: What the request goes through.
            headers: Headers beside those the connector adds.
            body: The body, as the adapter protocol writes one.

        Returns:
            The response.
        """
        request = self.send_request(
            backend, method, target, via=via, headers=headers, body=body
        )
        return self.finish(request)

    def finish(self, request: int) -> Response:
        """
        Wait for a request sent earlier to complete, and gather its response.

        Args:
            request: The request's name, its command's ID.

        Returns:
            The response.

        Raises:
            AssertionError: The request failed, with the error it gave.
        """
        self.reply(request).result()
        return self.response(request)

    def sse(self, backend: int, target: str, *, via: Via = "untyped") -> int:
        """
        Start iterating a GET request's response with the SSE helper.

        Args:
            backend: The Backend.
            target: The path and query, as they go out.
            via: What the request goes through.

        Returns:
            The request's name, its command's ID.
        """
        return self.send("sse", backend=backend, via=via, target=target)

    def sse_events(self, request: int, count: int) -> list[Message]:
        """
        Wait until the SSE helper has given a stream's first events.

        Args:
            request: The stream's request.
            count: How many events to wait for.

        Returns:
            Its events so far, at least ``count`` of them, in order.
        """

        def matches(each: Message) -> bool:
            return each["event"] == "sse_event" and each["request"] == request

        self.wait_for_event(
            lambda _event: len(self.events(matches)) >= count,
            f"{count} events of stream {request}",
        )
        return self.events(matches)

    def response(self, request: int) -> Response:
        """
        Gather the response of a request whose call returned, from its events.

        Args:
            request: The request's name, its command's ID.

        Returns:
            The response.

        Raises:
            AdapterFault: The adapter wrote no response for it, which it writes
                before the reply that says the call returned.
        """
        events = self.events(lambda each: each.get("request") == request)
        heads = [each for each in events if each["event"] == "response"]
        if not heads:
            message = f"{self.name} wrote no response for request {request}"
            raise AdapterFault(message + self._stderr_tail())
        head = heads[0]
        body = b"".join(
            bytes_of(each) for each in events if each["event"] == "response_chunk"
        )
        headers = tuple((name, value) for name, value in head["headers"])
        return Response(head["status"], headers, body)

    def kill(self) -> int:
        """
        Kill the client process hard, by the PID its hello gave, and only it.

        Returns:
            The exit status of the process the runner started.
        """
        return self.process.kill()

    def close(self) -> None:
        """
        End the adapter's stdin, wait for it to exit with status 0, then read its
        stdout to the end, so the session holds every line it wrote.

        Closing again does nothing. A client the runner killed isn't waited for,
        such as one whose stdin a write was stuck on, which ends it first. Once the
        client has ended, a line that broke the protocol and that no wait raised,
        such as one after the case's last wait, is raised, except a last line the
        runner's kill cut short. A stdout that a process the client started holds
        open is read only within a hang guard, which the trace records.

        Raises:
            AdapterFault: A line broke the protocol and no wait raised it, or the
                client exited with another status, or didn't exit at once, in which
                case it is killed.
            StillRunning: It outlived its kill.
        """
        if self._closed:
            return
        self._closed = True
        self.process.close_stdin()
        problems: list[str] = []
        cause: DeadlinePassed | None = None
        if not self.process.killed:
            try:
                status = self.process.wait(EXIT_GUARD_SECONDS)
            except DeadlinePassed as passed:
                self.process.kill()
                cause = passed
                problems.append(f"{self.name} didn't exit at the end of its stdin")
            else:
                if status != 0:
                    problems.append(
                        f"{self.name} exited with status {status} at the end of its "
                        "stdin"
                    )
        self._read_to_the_end()
        fault = self._unraised_fault()
        if fault is not None:
            problems.insert(0, fault)
        if problems:
            raise AdapterFault("; ".join(problems) + self._stderr_tail()) from cause


def start_adapter(
    name: str,
    manifest: AdapterManifest,
    processes: Processes,
    trace: Trace,
    deadline: Deadline,
    changes: Changes | None = None,
    secrets: Collection[str] = (),
) -> AdapterSession:
    """
    Start a connector's adapter, as its manifest says, and read its hello.

    The adapter's PATH starts with the runner's own environment's scripts, as
    :data:`~runner.adapters.SCRIPTS` says.

    Args:
        name: What the adapter is to the case, which the trace names.
        manifest: The adapter's manifest.
        processes: The work's processes, which the adapter joins.
        trace: The trace.
        deadline: The deadline of the work the adapter belongs to.
        changes: The changes the case makes to the adapter's environment.
        secrets: What the commands carry that the trace's records of them hide.

    Returns:
        The session, once the hello has come.

    Raises:
        AdapterFault: The hello names another connector.
    """
    process = processes.start(
        name,
        manifest.resolved_command(),
        cwd=manifest.directory,
        changes={"PATH": Prepended(SCRIPTS), **(changes or {})},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    session = AdapterSession(name, process, trace, deadline, secrets)
    if session.hello.connector != manifest.connector:
        message = (
            f"{name}'s hello names the connector {session.hello.connector}, "
            f"where its manifest names {manifest.connector}"
        )
        raise AdapterFault(message)
    return session


@cache
def _message_validator(version: int) -> Validator:
    return validator(versions()[version])


def _schema_error(version: int, message: Message) -> str | None:
    error = next(iter(_message_validator(version).iter_errors(message)), None)
    if error is None:
        return None
    # A union's error says only that no member matched, so take the deepest of its
    # members' errors, which is in the member the message meant to be.
    while error.context:
        error = max(error.context, key=lambda each: len(each.absolute_path))
    return f"{error.json_path}: {error.message}"
