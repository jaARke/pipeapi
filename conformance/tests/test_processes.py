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

from reference_app.environment import LOG_VARIABLE
from runner import processes as processes_module
from runner.deadlines import Deadline
from runner.processes import (
    KILL_GUARD_SECONDS,
    ForeignProcess,
    Process,
    Processes,
    StdinStuck,
    StillRunning,
    end_learned,
)
from runner.trace import Trace
from runner.uvicorn_server import PROJECT, Server, ServerDidNotStart, run_server

# A program that starts a child, reports both PIDs, and waits.
PARENT = (
    "import os, subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
    "print(os.getpid(), child.pid, flush=True)\n"
    "time.sleep(600)\n"
)
# A program that never reads its stdin.
DEAF = "import time; time.sleep(600)"
# More than any pipe's buffer holds, so a write to a child that doesn't read blocks.
UNREAD_BYTES: Final = 4_000_000
# The bounds a test shortens, so a stuck write or a lingering wrapper shows at once.
SHORT_GUARD_SECONDS: Final = 0.5
# How long a close that kills a stuck child takes at most, its hang guards included.
CLOSE_BOUND_SECONDS: Final = 60.0


@pytest.fixture
def trace(tmp_path: Path) -> Iterator[Trace]:
    with Trace(tmp_path / "trace.log") as opened:
        yield opened


@pytest.fixture
def serving(tmp_path: Path) -> Iterator[Server]:
    with run_server(tmp_path) as server:
        server.wait_until_serving()
        yield server


def start_parent(processes: Processes) -> tuple[Process, int, int]:
    process = processes.start(
        "parent", [sys.executable, "-c", PARENT], cwd=PROJECT, stdout=subprocess.PIPE
    )
    assert process.popen.stdout is not None
    program, child = map(int, process.popen.stdout.readline().split())
    process.popen.stdout.close()
    return process, program, child


def end(pid: int) -> None:
    with suppress(psutil.NoSuchProcess):
        left = psutil.Process(pid)
        left.kill()
        left.wait(KILL_GUARD_SECONDS)


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


def test_killing_a_program_leaves_the_processes_it_started_running(
    trace: Trace,
) -> None:
    with Processes(trace) as processes:
        process, program, child = start_parent(processes)
        process.identify_program(program)
        try:
            process.kill()
            assert not psutil.pid_exists(program)
            assert psutil.pid_exists(child), "the program's child died with it"
        finally:
            end(child)


def test_a_pid_that_isnt_the_process_or_a_descendant_is_refused(
    trace: Trace,
) -> None:
    with Processes(trace) as processes:
        process = processes.start("deaf", [sys.executable, "-c", DEAF], cwd=PROJECT)
        with pytest.raises(ForeignProcess, match=f"PID {os.getpid()}"):
            process.identify_program(os.getpid())
        assert process.program_pid == process.pid


def test_a_process_whose_program_ended_first_is_killed_itself(trace: Trace) -> None:
    processes = Processes(trace)
    process, program, child = start_parent(processes)
    try:
        process.identify_program(child)
        end(child)
        processes.close()
        assert not process.running()
        assert process.killed
    finally:
        end(program)


def test_a_wrapper_that_outlives_its_killed_program_is_killed_too(
    trace: Trace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        processes_module, "LAUNCHER_EXIT_GUARD_SECONDS", SHORT_GUARD_SECONDS
    )
    with Processes(trace) as processes:
        process, program, child = start_parent(processes)
        try:
            process.identify_program(child)
            killed = psutil.Process(child)
            process.kill()
            killed.wait(KILL_GUARD_SECONDS)
            assert not process.running()
            assert process.killed
        finally:
            end(program)


def test_a_stuck_write_to_stdin_is_ended_by_killing_the_child(trace: Trace) -> None:
    with Processes(trace) as processes:
        process = processes.start(
            "deaf",
            [sys.executable, "-c", DEAF],
            cwd=PROJECT,
            stdin=subprocess.PIPE,
        )
        with pytest.raises(StdinStuck, match="deaf to take the bytes"):
            process.write(
                b"x" * UNREAD_BYTES,
                guard=SHORT_GUARD_SECONDS,
                deadline=Deadline.after(KILL_GUARD_SECONDS, "the test"),
                what="the bytes",
            )
        finishes(process.close_stdin, CLOSE_BOUND_SECONDS)
        assert process.killed
        assert not process.running()


@pytest.mark.skipif(sys.platform != "win32", reason="SIGTERM needs no process group")
def test_a_process_without_a_group_of_its_own_isnt_interrupted(trace: Trace) -> None:
    with Processes(trace) as processes:
        process = processes.start("deaf", [sys.executable, "-c", DEAF], cwd=PROJECT)
        with pytest.raises(RuntimeError, match="no process group of its own"):
            process.interrupt()
        assert process.running()


def test_a_backend_learned_of_by_its_log_is_ended(
    serving: Server, trace: Trace
) -> None:
    pid = serving.observations()[0]["pid"]
    end_learned(
        [pid],
        lambda environment: environment.get(LOG_VARIABLE) == str(serving.log),
        trace,
    )
    serving.wait_for_exit()
    assert not psutil.pid_exists(pid)


def test_a_process_whose_environment_isnt_the_works_is_left_running(
    serving: Server, trace: Trace
) -> None:
    pid = serving.observations()[0]["pid"]
    end_learned([pid], lambda _environment: False, trace)
    assert serving.process.running()
    assert psutil.Process(pid).is_running()


def test_a_process_whose_environment_cant_be_read_counts_as_still_running(
    serving: Server, trace: Trace, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = serving.observations()[0]["pid"]

    def denied(self: psutil.Process) -> dict[str, str]:
        raise psutil.AccessDenied(self.pid)

    monkeypatch.setattr(psutil.Process, "environ", denied)
    with pytest.raises(StillRunning, match=f"PID {pid}, which denies access"):
        end_learned([pid], lambda _environment: True, trace)
    assert f"PID {pid}, which a backend ran as, denies access" in trace.path.read_text(
        encoding="utf-8"
    )
    assert serving.process.running()


def test_a_backend_that_doesnt_serve_by_the_deadline_is_the_runners_fault(
    tmp_path: Path,
) -> None:
    with run_server(tmp_path) as server, pytest.raises(ServerDidNotStart):
        server.wait_until_serving(Deadline.after(0, "the test"))
