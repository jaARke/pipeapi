import os
import subprocess
import sys
import threading
from collections.abc import Callable, Iterator
from contextlib import suppress
from pathlib import Path
from typing import Final

import psutil
import pytest

from runner import adapter_session
from runner.adapter_session import AdapterFault, AdapterSession
from runner.deadlines import Deadline, wait_until
from runner.processes import KILL_GUARD_SECONDS, Processes
from runner.trace import Trace
from runner.uvicorn_server import PROJECT

# An adapter that behaves as its first argument says, writing its hello with the PID
# its second argument gives, or its own.
SCRIPTED = """
import json, os, subprocess, sys, time
mode = sys.argv[1]
pid = int(sys.argv[2]) if len(sys.argv) > 2 else os.getpid()
hello = {
    "type": "hello", "adapterProtocol": 1,
    "connector": {"name": "baseline", "version": "0"},
    "pid": pid, "transports": ["tcp"], "capabilities": [],
}

def write(message, prefix=b"", suffix=b""):
    sys.stdout.buffer.write(prefix + json.dumps(message).encode() + b"\\n" + suffix)
    sys.stdout.buffer.flush()

def reply(command_id, command, suffix=b""):
    message = {"type": "reply", "id": command_id, "command": command, "result": {}}
    write(message, suffix=suffix)

def spawn(code):
    # A process the adapter starts that holds its stdout, as an inherited one would.
    command = [sys.executable, "-c", code]
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=sys.stdout)

if mode == "holder":
    spawn("import time; time.sleep(600)")
if mode == "silent":
    sys.stdin.buffer.read()
    sys.exit(0)
write(hello, b"\\xef\\xbb\\xbf" if mode == "bom" else b"")
if mode == "deaf":
    time.sleep(600)
if mode == "unsent":
    reply(7, "close")
for line in sys.stdin.buffer:
    command = json.loads(line)
    if mode == "refusing":
        refusal = {"code": "unknown_command", "message": "no such command"}
        write({"type": "reply", "id": command["id"], "command": command["command"],
               "refusal": refusal})
        continue
    if mode == "stray":
        reply(7, "close")
        time.sleep(600)
    if mode == "cut":
        # The start of a line, in the reply's write, so it's there once the reply is.
        reply(command["id"], command["command"], b'{"type":"event"')
        time.sleep(600)
    reply(command["id"], "close" if mode == "misnamed" else command["command"])
if mode == "late":
    write({"type": "event", "event": "nothing"})
if mode == "afterword":
    spawn("import sys, time; time.sleep(0.5); sys.stdout.buffer.write(b'{}\\\\n')")
"""
# More than any pipe's buffer holds, so a command the adapter doesn't read blocks.
UNREAD_CHARACTERS: Final = 4_000_000
# The bounds a test shortens, so a missing hello or a stuck write shows at once.
SHORT_GUARD_SECONDS: Final = 0.5
# How long closing a session takes at most, its hang guards included.
CLOSE_BOUND_SECONDS: Final = 60.0


@pytest.fixture
def trace(tmp_path: Path) -> Iterator[Trace]:
    with Trace(tmp_path / "trace.log") as opened:
        yield opened


@pytest.fixture
def processes(trace: Trace) -> Iterator[Processes]:
    with Processes(trace) as started:
        yield started


def session_of(
    processes: Processes, trace: Trace, mode: str, *arguments: str
) -> AdapterSession:
    process = processes.start(
        "adapter",
        [sys.executable, "-c", SCRIPTED, mode, *arguments],
        cwd=PROJECT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return AdapterSession("adapter", process, trace, Deadline.after(60, "the test"))


def finishes(call: Callable[[], object], seconds: float) -> None:
    failures: list[BaseException] = []

    def run() -> None:
        try:
            call()
        except BaseException as error:  # noqa: BLE001
            failures.append(error)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"still running after {seconds} seconds"
    if failures:
        raise failures[0]


def test_an_adapter_that_writes_no_hello_is_an_adapter_fault(
    processes: Processes, trace: Trace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter_session, "HELLO_GUARD_SECONDS", SHORT_GUARD_SECONDS)
    with pytest.raises(AdapterFault, match="adapter wrote no hello"):
        session_of(processes, trace, "silent")


def test_a_hello_that_starts_with_a_byte_order_mark_is_refused(
    processes: Processes, trace: Trace
) -> None:
    with pytest.raises(AdapterFault, match="starts with a byte order mark"):
        session_of(processes, trace, "bom")


def test_a_hello_naming_a_pid_outside_the_adapters_processes_is_refused(
    processes: Processes, trace: Trace
) -> None:
    with pytest.raises(AdapterFault, match=f"reported PID {os.getpid()} as its own"):
        session_of(processes, trace, "replies", str(os.getpid()))


def test_a_reply_to_a_command_never_sent_is_an_adapter_fault(
    processes: Processes, trace: Trace
) -> None:
    # The stray reply comes right after the hello, so the hello's own wait may see it.
    with pytest.raises(AdapterFault, match="command 7, which was never sent"):
        session_of(processes, trace, "unsent").wait_for_event(
            lambda _event: False, "the fault"
        )


def test_a_reply_that_names_another_command_is_an_adapter_fault(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "misnamed")
    with pytest.raises(AdapterFault, match="command 1, a cancel, as a close"):
        session.call("cancel", commandId=1)


def test_a_request_that_returns_without_a_response_is_an_adapter_fault(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "replies")
    with pytest.raises(AdapterFault, match="wrote no response for request 1"):
        session.request(1, "GET", "/")
    session.close()


def test_a_line_that_breaks_the_schema_after_the_last_wait_fails_the_close(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "late")
    with pytest.raises(AdapterFault, match="a line that breaks the schema"):
        session.close()
    assert not session.process.running()
    session.close()


def test_a_fault_no_wait_raised_fails_the_close_of_a_client_the_case_killed(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "stray")
    session.send("cancel", commandId=1)
    wait_until(
        lambda: True if session.transcript()[-1]["type"] == "reply" else None,
        guard=adapter_session.REPLY_GUARD_SECONDS,
        deadline=None,
        waiting_for="the stray reply",
    )
    session.kill()
    with pytest.raises(AdapterFault, match="command 7, which was never sent"):
        session.close()


def test_a_refusal_fails_the_next_wait_though_nothing_awaits_its_reply(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "refusing")
    session.send("cancel", commandId=1)
    with pytest.raises(AdapterFault, match=r"refused command 1 \(cancel\)"):
        session.wait_for_event(lambda _event: False, "the refusal")
    session.close()


def test_a_refusal_no_wait_saw_fails_the_close(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "refusing")
    session.send("cancel", commandId=1)
    wait_until(
        lambda: True if session.transcript()[-1]["type"] == "reply" else None,
        guard=adapter_session.REPLY_GUARD_SECONDS,
        deadline=None,
        waiting_for="the refusal",
    )
    with pytest.raises(AdapterFault, match="unknown_command: no such command"):
        session.close()


def test_closing_doesnt_raise_again_a_fault_a_wait_raised(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "misnamed")
    with pytest.raises(AdapterFault, match="as a close"):
        session.call("cancel", commandId=1)
    session.close()


def test_closing_reads_the_stdout_to_its_end(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "afterword")
    with pytest.raises(
        AdapterFault, match="a line that is neither a reply nor an event"
    ):
        session.close()


def test_closing_a_client_whose_stdout_another_process_holds_ends_in_time(
    processes: Processes, trace: Trace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        adapter_session, "STDOUT_END_GUARD_SECONDS", SHORT_GUARD_SECONDS
    )
    session = session_of(processes, trace, "holder")
    holders = psutil.Process(session.process.program_pid).children(recursive=True)
    assert holders, "the adapter started the process that holds its stdout"
    try:
        finishes(session.close, CLOSE_BOUND_SECONDS)
    finally:
        for holder in holders:
            with suppress(psutil.NoSuchProcess):
                holder.kill()
        psutil.wait_procs(holders, timeout=KILL_GUARD_SECONDS)
    assert "may hold it open" in trace.path.read_text(encoding="utf-8")


def test_a_last_line_the_runners_kill_cut_short_is_no_fault(
    processes: Processes, trace: Trace
) -> None:
    session = session_of(processes, trace, "cut")
    session.call("cancel", commandId=1)
    session.kill()
    session.close()
    assert '{"type":"event"' in trace.path.read_text(encoding="utf-8")


def test_a_session_whose_stdin_is_stuck_takes_no_command_and_still_closes(
    processes: Processes, trace: Trace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(adapter_session, "WRITE_GUARD_SECONDS", SHORT_GUARD_SECONDS)
    session = session_of(processes, trace, "deaf")
    with pytest.raises(AdapterFault, match="adapter took no command 1"):
        session.send("body_chunk", request=1, text="x" * UNREAD_CHARACTERS)
    finishes(session.close, CLOSE_BOUND_SECONDS)
    assert session.process.killed
    assert not session.process.running()
