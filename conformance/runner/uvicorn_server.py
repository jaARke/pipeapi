import socket
import subprocess
import sys
from collections.abc import Callable, Generator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx2

from reference_app.environment import (
    FAIL_STARTUP_VARIABLE,
    FAKE_READY_VARIABLE,
    LOG_VARIABLE,
)
from runner.deadlines import Deadline, DeadlinePassed, wait_until
from runner.observations import Observation, read_observations
from runner.processes import Process, Processes
from runner.trace import Trace

# The conformance project, from which uvicorn imports the app.
PROJECT: Final = Path(__file__).resolve().parents[1]

HOST: Final = "127.0.0.1"

# The observation log's name, in a backend's directory.
LOG_FILE_NAME: Final = "observations.jsonl"

# uvicorn imports the app and starts in a few seconds, even on a cold CI runner.
STARTUP_DEADLINE_SECONDS: Final = 60.0

# uvicorn stops in well under this once signalled, and a killed process at once.
STOP_DEADLINE_SECONDS: Final = 30.0

# A request to the app answers in well under this, a held stream's first event included.
REQUEST_TIMEOUT_SECONDS: Final = 30.0

# How long an observation the test caused may take to reach the log, a hang guard.
OBSERVATION_DEADLINE_SECONDS: Final = 30.0

# One attempt to connect; a refused one is retried for about two seconds on Windows.
CONNECT_TIMEOUT_SECONDS: Final = 5.0


class ServerExited(Exception):
    """The server exited while the runner waited on it."""


class PortTaken(Exception):
    """Another process answers on the port chosen for the server."""


class ServerDidNotStart(Exception):
    """The server didn't serve within its startup's hang guard or the deadline."""


@dataclass(frozen=True)
class Server:
    """A uvicorn process serving the reference app, and the files it writes."""

    process: Process
    port: int
    log: Path
    stdout: Path
    stderr: Path

    @property
    def base_url(self) -> str:
        """The app's URL over loopback."""
        return f"http://{HOST}:{self.port}"

    @property
    def endpoint(self) -> str:
        """The app's address as the protocol writes an endpoint."""
        return f"tcp://{HOST}:{self.port}"

    def _ending(self, how: str) -> str:
        tail = self.stderr.read_text(errors="replace").strip().splitlines()[-20:]
        return f"uvicorn {how}; its stderr ends:\n" + "\n".join(tail)

    def client(self) -> httpx2.Client:
        """
        Make a client of the app, which a proxy in the environment never redirects.

        Returns:
            The client.
        """
        return httpx2.Client(
            base_url=self.base_url, timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False
        )

    def observations(self) -> list[Observation]:
        """
        Read the app's observation log.

        Returns:
            Every complete observation, in order.
        """
        return read_observations(self.log)

    def wait_for(
        self,
        matches: Callable[[Observation], bool],
        *,
        after: int = 0,
        within: float = OBSERVATION_DEADLINE_SECONDS,
        deadline: Deadline | None = None,
    ) -> Observation:
        """
        Wait for the first observation past the ``after``-th that matches.

        Args:
            matches: Whether an observation is the one awaited.
            after: How many observations to pass over first.
            within: The wait's hang guard, in seconds.
            deadline: The deadline of the work the wait belongs to.

        Returns:
            The observation.

        Raises:
            ServerExited: The server exited first, with its stderr's last lines.
            DeadlinePassed: The guard or the deadline passed first.
        """

        def found() -> Observation | None:
            exited = not self.process.running()
            for observation in self.observations()[after:]:
                if matches(observation):
                    return observation
            if exited:
                raise ServerExited(self._ending("exited"))
            return None

        try:
            return wait_until(
                found, guard=within, deadline=deadline, waiting_for="the observation"
            )
        except DeadlinePassed as passed:
            passed.add_note(self._ending("logged no such observation"))
            raise

    def wait_until_serving(self, deadline: Deadline | None = None) -> None:
        """
        Wait for the app's lifespan startup, then for uvicorn to serve the app.

        The startup observation comes first, since uvicorn binds its socket only after
        the lifespan startup, and connecting to a port before it listens takes seconds
        on Windows. The app's PID then confirms the port is this server's, which another
        process may have taken between its release and uvicorn's bind.

        Args:
            deadline: The deadline of the work the wait belongs to.

        Raises:
            ServerExited: The server exited first.
            PortTaken: Another process answers on the port.
            ServerDidNotStart: The guard or the deadline passed first, a fault of the
                runner's own work rather than of what a case tests.
        """

        def listening() -> bool | None:
            try:
                address = (HOST, self.port)
                with socket.create_connection(address, CONNECT_TIMEOUT_SECONDS):
                    return True
            except OSError:
                if not self.process.running():
                    raise ServerExited(self._ending("exited")) from None
                return None

        try:
            startup = self.wait_for(
                lambda observation: observation["event"] == "startup",
                within=STARTUP_DEADLINE_SECONDS,
                deadline=deadline,
            )
            wait_until(
                listening,
                guard=STARTUP_DEADLINE_SECONDS,
                deadline=deadline,
                waiting_for=f"uvicorn to listen on port {self.port}",
            )
        except DeadlinePassed as passed:
            raise ServerDidNotStart(self._ending(f"didn't serve: {passed}")) from None
        pid: object = None
        try:
            with self.client() as client:
                pid = client.get("/seen").json().get("pid")
        except httpx2.HTTPError, ValueError, AttributeError:
            pass
        if pid != startup["pid"]:
            raise PortTaken(self._ending(f"lost port {self.port} to another process"))

    def wait_for_exit(self) -> int:
        """
        Wait for the process to exit.

        Returns:
            Its exit status.
        """
        return self.process.wait(STOP_DEADLINE_SECONDS)

    def stop(self) -> int:
        """
        Ask uvicorn to stop, as an interrupt does, and wait for the process.

        uvicorn raises the signal again once it has shut down, so the status reports
        the signal; the log's ``shutdown`` record tells a graceful stop.

        Returns:
            Its exit status.
        """
        self.process.interrupt()
        return self.wait_for_exit()

    def kill(self) -> int:
        """
        Kill the process, so it runs nothing more, and wait for it to exit.

        Returns:
            Its exit status.

        Raises:
            StillRunning: It outlived its kill.
        """
        return self.process.kill()


@contextmanager
def run_server(
    directory: Path,
    processes: Processes | None = None,
    *,
    fake_ready: str | None = None,
    fail_startup: str | None = None,
    environment: Mapping[str, str] | None = None,
    stdin: int = subprocess.DEVNULL,
) -> Generator[Server]:
    """
    Start the reference app under uvicorn on a free loopback port.

    The app's settings come from the arguments, never from the runner's environment,
    and ``environment`` adds variables of the caller's own.

    Args:
        directory: Where the server writes its observation log and its output.
        processes: The work's processes, which the server joins, or None for a set
            of its own whose trace is in ``directory``.
        fake_ready: The app's fake ready line.
        fail_startup: The message the app's startup fails with.
        environment: Further variables for the server.
        stdin: The server's stdin.

    Yields:
        The server, which is killed on the way out if it still runs.
    """
    port = _free_port()
    log = directory / LOG_FILE_NAME
    changes: dict[str, str | None] = {
        LOG_VARIABLE: str(log),
        FAKE_READY_VARIABLE: fake_ready,
        FAIL_STARTUP_VARIABLE: fail_startup,
        **(environment or {}),
    }
    with ExitStack() as stack:
        if processes is None:
            trace = stack.enter_context(Trace(directory / "trace.log"))
            processes = stack.enter_context(Processes(trace))
        stdout_path, stderr_path = directory / "stdout.txt", directory / "stderr.txt"
        stdout = stack.enter_context(stdout_path.open("wb"))
        stderr = stack.enter_context(stderr_path.open("wb"))
        process = processes.start(
            "backend",
            [
                sys.executable,
                "-m",
                "uvicorn",
                "reference_app.main:app",
                "--host",
                HOST,
                "--port",
                str(port),
                "--lifespan",
                "on",
            ],
            cwd=PROJECT,
            changes=changes,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            new_group=True,
        )
        try:
            yield Server(process, port, log, stdout_path, stderr_path)
        finally:
            try:
                process.kill()
            finally:
                process.close_stdin()


def _free_port() -> int:
    # Bound and released, for uvicorn to bind next. Another process can take it between
    # the two: uvicorn then fails to bind, or the other process answers in its place,
    # which Server.wait_until_serving tells apart by the app's PID.
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        port: int = probe.getsockname()[1]
        return port
