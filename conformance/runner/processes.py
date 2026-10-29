import os
import signal
import subprocess
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import IO, Final, Self

import psutil
import pytest

from runner.deadlines import Deadline, DeadlinePassed, wait_until
from runner.trace import Trace

# A process killed hard exits at once, even on a loaded CI runner; a hang guard.
KILL_GUARD_SECONDS: Final = 30.0

# A launcher, such as a virtual environment's python.exe on Windows, exits at once once
# its program does; a hang guard, past which the launcher is killed too.
LAUNCHER_EXIT_GUARD_SECONDS: Final = 10.0

# A write to a killed child's stdin fails at once, since nothing then reads the pipe; a
# hang guard.
WRITE_RELEASE_GUARD_SECONDS: Final = 10.0


@dataclass(frozen=True)
class Prepended:
    """A directory put first in a variable's list of paths, such as PATH."""

    directory: Path


type Changes = Mapping[str, str | Prepended | None]
"""
Changes to a child's environment: each variable with its value, a directory put first
in its list of paths, or None to unset it.
"""

type Stream = int | IO[bytes]
"""A child's stream: ``subprocess.PIPE``, ``subprocess.DEVNULL`` or an open file."""


class StillRunning(Exception):
    """Processes the runner started outlived its attempts to end them."""


class ForeignProcess(Exception):
    """
    A PID a program reported as its own is neither the process the runner started nor
    a descendant of it.
    """


class StdinStuck(Exception):
    """A write to a child's stdin outlived its bounds, and is still under way."""


class Process:
    """
    A child process the runner started, whose end the trace records.

    On Windows the PID of a virtual environment's ``python.exe`` is a launcher's, which
    runs the interpreter as a child of its own inside a job object that ends with the
    launcher, so the PID of the program itself, such as an adapter's client process,
    comes from the program, through :meth:`identify_program`.
    """

    def __init__(
        self,
        name: str,
        popen: subprocess.Popen[bytes],
        trace: Trace,
        *,
        new_group: bool,
    ) -> None:
        self.name = name
        """What the process is to the case, such as ``backend`` or ``adapter 1``."""
        self.popen = popen
        self.new_group = new_group
        """Whether it has a process group of its own, which :meth:`interrupt` needs."""
        self.exit_code: int | None = None
        """Its exit status once the runner has seen it exit."""
        self.killed = False
        """Whether the runner killed it, or the program it runs."""
        self._trace = trace
        self._program: psutil.Process | None = None
        self._writer: threading.Thread | None = None

    @property
    def pid(self) -> int:
        """The PID the OS gave the process the runner started."""
        return self.popen.pid

    @property
    def program_pid(self) -> int:
        """The PID of the program: the one it reported as its own, or else the PID."""
        return self.pid if self._program is None else self._program.pid

    def _poll(self) -> int | None:
        code = self.popen.poll()
        if code is not None and self.exit_code is None:
            self.exit_code = code
            how = "killed by the runner, " if self.killed else ""
            if code < 0:
                self._trace.record(self.name, f"{how}ended by signal {-code}")
            else:
                self._trace.record(self.name, f"{how}exited with status {code}")
        return code

    def _kill_started(self) -> None:
        self.popen.kill()
        self.killed = True
        self._trace.record(self.name, "killed by the runner")

    def _kill_program(self, program: psutil.Process) -> None:
        try:
            program.kill()
        except psutil.NoSuchProcess:
            self._trace.record(self.name, f"its program, PID {program.pid}, had ended")
        else:
            self.killed = True
            self._trace.record(self.name, f"PID {program.pid} killed by the runner")
        try:
            self.wait(LAUNCHER_EXIT_GUARD_SECONDS)
        except DeadlinePassed:
            self._trace.record(self.name, "still ran once its program had ended")
            self._kill_started()

    def running(self) -> bool:
        """
        Tell whether the process still runs.

        Returns:
            Whether it does.
        """
        return self._poll() is None

    def wait(self, guard: float, deadline: Deadline | None = None) -> int:
        """
        Wait for the process to exit.

        Args:
            guard: The wait's hang guard, in seconds.
            deadline: The deadline of the work the wait belongs to.

        Returns:
            Its exit status.

        Raises:
            DeadlinePassed: It still ran at the guard or the deadline.
        """
        return wait_until(
            self._poll,
            guard=guard,
            deadline=deadline,
            waiting_for=f"{self.name} (PID {self.pid}) to exit",
        )

    def identify_program(self, pid: int) -> None:
        """
        Take the PID the program reports as its own, such as in an adapter's hello, as
        the one :meth:`kill` kills.

        psutil must show that the PID is this process or a descendant of it, and the
        handle it gives is kept, which guards the kill against the PID's reuse.

        Args:
            pid: The PID.

        Raises:
            ForeignProcess: The PID is neither this process nor a descendant of it.
        """
        if pid == self.pid:
            return
        try:
            descendants = psutil.Process(self.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        program = next((each for each in descendants if each.pid == pid), None)
        if program is None:
            message = (
                f"{self.name} reported PID {pid} as its own, which is neither PID "
                f"{self.pid}, the process the runner started, nor a descendant of it"
            )
            raise ForeignProcess(message)
        self._program = program
        self._trace.record(self.name, f"its program runs as PID {pid}")

    def write(
        self, data: bytes, *, guard: float, deadline: Deadline | None, what: str
    ) -> None:
        """
        Write to the process's stdin and flush it, on a thread of its own.

        A pipe the child stopped reading blocks a write once it's full, and a wait on
        the thread can be bounded where the write can't. A write that outlives its
        bounds stays under way, holding the stream, until :meth:`close_stdin` kills
        the process, which ends the write.

        Args:
            data: The bytes.
            guard: The write's hang guard, in seconds.
            deadline: The deadline of the work the write belongs to.
            what: What the bytes are, which a failure names.

        Raises:
            StdinStuck: The write didn't finish within the guard or the deadline, or
                an earlier one is still under way.
            OSError: The write failed, such as on a pipe nothing reads any more.
            RuntimeError: The process's stdin is no open pipe.
        """
        stdin = self.popen.stdin
        if stdin is None or stdin.closed:
            raise RuntimeError(f"{self.name}'s stdin is no open pipe")
        if self._writer is not None and self._writer.is_alive():
            message = f"an earlier write to the stdin of {self.name} is under way"
            raise StdinStuck(message)
        failures: list[OSError] = []

        def write() -> None:
            try:
                stdin.write(data)
                stdin.flush()
            except OSError as error:
                failures.append(error)

        writer = threading.Thread(target=write, name=f"{self.name} stdin", daemon=True)
        self._writer = writer
        writer.start()
        try:
            wait_until(
                lambda: None if writer.is_alive() else True,
                guard=guard,
                deadline=deadline,
                waiting_for=f"{self.name} to take {what}",
            )
        except DeadlinePassed as passed:
            raise StdinStuck(str(passed)) from passed
        if failures:
            raise failures[0]

    def close_stdin(self) -> None:
        """
        Close the writing end of the process's stdin, so the child reads its end.

        A write still under way holds the stream until it fails, so the process is
        killed first, which ends the write. Only the writing end closes: a reader
        thread closes what it reads at its end, which a process the child started may
        hold open after it.

        Raises:
            StillRunning: The process outlived its kill, or the write outlived it.
        """
        stdin = self.popen.stdin
        if stdin is None or stdin.closed:
            return
        writer = self._writer
        if writer is not None and writer.is_alive():
            self._trace.record(self.name, "a write to its stdin is stuck, so it dies")
            self.kill()
            writer.join(WRITE_RELEASE_GUARD_SECONDS)
            if writer.is_alive():
                message = (
                    f"a write to the stdin of {self.name} (PID {self.pid}) outlived "
                    "its kill"
                )
                raise StillRunning(message)
        # Once the child has exited, nothing reads the pipe, so the flush may fail.
        with suppress(OSError):
            stdin.close()

    def kill(self) -> int:
        """
        Kill the program hard, so it runs nothing more, and wait for the process.

        Only the program dies: never a process group or a job object, so whatever it
        started keeps running, as a killed client's backends must. A program that
        reported its own PID is killed through the handle :meth:`identify_program`
        kept, and a launcher the runner started for it then exits on its own; killing
        the launcher first would end its job object and every process in it. A
        process that still runs past a hang guard once its program has ended, such as
        a wrapper that outlives what it runs, is killed too.

        Returns:
            The exit status of the process the runner started.

        Raises:
            StillRunning: The process outlived its kill.
        """
        if self._program is not None and not has_ended(self._program):
            self._kill_program(self._program)
        elif self.running():
            self._kill_started()
        try:
            return self.wait(KILL_GUARD_SECONDS)
        except DeadlinePassed as passed:
            message = f"{self.name} (PID {self.pid}) outlived its kill"
            raise StillRunning(message) from passed

    def interrupt(self) -> None:
        """
        Ask the process to stop, as an interrupt does.

        Raises:
            RuntimeError: On Windows, the process has no process group of its own,
                which Ctrl+Break must reach alone.
        """
        if not self.running():
            return
        if sys.platform == "win32":
            if not self.new_group:
                message = f"{self.name} has no process group of its own to interrupt"
                raise RuntimeError(message)
            self._trace.record(self.name, "interrupted by the runner")
            self.popen.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            self._trace.record(self.name, "interrupted by the runner")
            self.popen.send_signal(signal.SIGTERM)


def has_ended(process: psutil.Process) -> bool:
    """
    Tell whether a process psutil names has ended: it's gone, or it's a zombie.

    A zombie has exited, and only its parent can reap it, which a parent that never
    waits for its children doesn't do, so psutil's own wait would outlast its guard.

    Args:
        process: The process.

    Returns:
        Whether it has ended.
    """
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def end_learned(
    pids: Iterable[int], belongs: Callable[[Mapping[str, str]], bool], trace: Trace
) -> None:
    """
    End processes the work learned of but didn't start, by PID, such as a backend a
    connector spawned, which the case's observation log names.

    A process is killed only while it runs and while ``belongs`` says its environment
    is the work's, so a PID the OS has given another process since is left alone. A
    process whose environment can't be read may be the work's, so it counts among
    those that outlived their kill.

    Args:
        pids: The PIDs.
        belongs: Whether a process's environment shows it is the work's.
        trace: The trace, which records each kill.

    Raises:
        StillRunning: A process outlived its kill, or couldn't be read, naming each.
    """
    failed: list[str] = []
    for pid in pids:
        try:
            process = psutil.Process(pid)
            if not belongs(process.environ()):
                continue
            trace.record("runner", f"PID {pid}, which a backend ran as, killed")
            process.kill()
            _wait_until_ended(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            trace.record("runner", f"PID {pid}, which a backend ran as, denies access")
            failed.append(f"PID {pid}, which denies access")
        except DeadlinePassed:
            failed.append(f"PID {pid}")
    if failed:
        raise StillRunning(", ".join(failed))


class Processes:
    """
    Every process one piece of work starts, so that each ends with it.

    Each start goes through :meth:`start`, which counts it and records it in the
    trace, and closing kills whatever still runs, on every path out of the work.
    """

    def __init__(self, trace: Trace, every: list[Process] | None = None) -> None:
        self.started: list[Process] = []
        """Each process started, in order."""
        self._trace = trace
        self._every = every

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def start(
        self,
        name: str,
        command: Sequence[str],
        *,
        cwd: Path,
        changes: Changes | None = None,
        stdin: Stream = subprocess.DEVNULL,
        stdout: Stream = subprocess.DEVNULL,
        stderr: Stream = subprocess.DEVNULL,
        new_group: bool = False,
    ) -> Process:
        """
        Start a process with the runner's environment and the changes given.

        Args:
            name: What the process is to the work, which the trace names.
            command: The program and its arguments.
            cwd: The working directory.
            changes: The changes to the environment it inherits.
            stdin: Its stdin.
            stdout: Its stdout.
            stderr: Its stderr.
            new_group: Whether it gets a process group of its own, which on Windows
                :meth:`Process.interrupt` needs.

        Returns:
            The process.
        """
        # The child inherits the environment as it is at the start, after which the
        # runner's own is restored, so no variable is read here.
        with pytest.MonkeyPatch.context() as patch:
            for variable, value in (changes or {}).items():
                match value:
                    case None:
                        patch.delenv(variable, raising=False)
                    case Prepended(directory=directory):
                        patch.setenv(variable, str(directory), prepend=os.pathsep)
                    case str():
                        patch.setenv(variable, value)
            popen = subprocess.Popen(
                list(command),
                cwd=cwd,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if new_group and sys.platform == "win32"
                else 0,
            )
        process = Process(name, popen, self._trace, new_group=new_group)
        self.started.append(process)
        if self._every is not None:
            self._every.append(process)
        shown = " ".join(command)
        self._trace.record(name, f"started as PID {popen.pid} in {cwd}: {shown}")
        return process

    def close(self) -> None:
        """
        Kill every process still running, wait for each to exit and close its stdin,
        carrying on past one that fails to end.

        Raises:
            StillRunning: A process outlived its kill, or ending it failed, naming
                each.
        """
        failed: list[str] = []
        for process in reversed(self.started):
            for end in (process.kill, process.close_stdin):
                try:
                    end()
                except (StillRunning, psutil.Error, OSError) as error:
                    failed.append(f"{process.name} (PID {process.pid}): {error}")
        if failed:
            raise StillRunning("; ".join(failed))


def _wait_until_ended(process: psutil.Process) -> None:
    wait_until(
        lambda: True if has_ended(process) else None,
        guard=KILL_GUARD_SECONDS,
        deadline=None,
        waiting_for=f"PID {process.pid} to end",
    )
