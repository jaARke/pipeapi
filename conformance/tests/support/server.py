import signal
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx2
import pytest

from reference_app.environment import (
    FAIL_STARTUP_VARIABLE,
    FAKE_READY_VARIABLE,
    LOG_VARIABLE,
)
from tests.support.observations import Observation, read_observations

# The conformance project, from which uvicorn imports the app.
PROJECT: Final = Path(__file__).resolve().parents[2]

HOST: Final = "127.0.0.1"

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

# How often a wait looks again at the log or the port.
POLL_INTERVAL_SECONDS: Final = 0.02


class ServerExited(Exception):
    """The server exited while a test waited on it."""


class PortTaken(Exception):
    """Another process answers on the port chosen for the server."""


@dataclass(frozen=True)
class Server:
    """A reference app's uvicorn process, and the files it writes."""

    process: subprocess.Popen[bytes]
    port: int
    log: Path
    stdout: Path
    stderr: Path

    @property
    def base_url(self) -> str:
        return f"http://{HOST}:{self.port}"

    def _ending(self, how: str) -> str:
        tail = self.stderr.read_text(errors="replace").strip().splitlines()[-20:]
        return f"uvicorn {how}; its stderr ends:\n" + "\n".join(tail)

    def client(self) -> httpx2.Client:
        """A client of the app, which a proxy in the environment never redirects."""
        return httpx2.Client(
            base_url=self.base_url, timeout=REQUEST_TIMEOUT_SECONDS, trust_env=False
        )

    def observations(self) -> list[Observation]:
        return read_observations(self.log)

    def wait_for(
        self,
        matches: Callable[[Observation], bool],
        *,
        after: int = 0,
        within: float = OBSERVATION_DEADLINE_SECONDS,
    ) -> Observation:
        """
        Wait for the first observation past the `after`th that matches, and return it.

        Raises ServerExited if the server exits first, and TimeoutError past `within`.
        """
        deadline = time.monotonic() + within
        while True:
            exited = self.process.poll() is not None
            for observation in self.observations()[after:]:
                if matches(observation):
                    return observation
            if exited:
                raise ServerExited(self._ending("exited"))
            if time.monotonic() > deadline:
                raise TimeoutError(self._ending("logged no such observation"))
            time.sleep(POLL_INTERVAL_SECONDS)

    def wait_until_serving(self) -> None:
        """
        Wait for the app's lifespan startup, then for uvicorn to serve the app.

        The startup observation comes first, since uvicorn binds its socket only after
        the lifespan startup, and connecting to a port before it listens takes seconds
        on Windows. The app's PID then confirms the port is this server's, which another
        process may have taken between its release and uvicorn's bind.

        Raises ServerExited if the server exits first, PortTaken if another process
        answers on the port, and TimeoutError past the startup bound.
        """
        deadline = time.monotonic() + STARTUP_DEADLINE_SECONDS
        startup = self.wait_for(
            lambda observation: observation["event"] == "startup",
            within=STARTUP_DEADLINE_SECONDS,
        )
        while True:
            try:
                address = (HOST, self.port)
                with socket.create_connection(address, CONNECT_TIMEOUT_SECONDS):
                    break
            except OSError:
                if self.process.poll() is not None:
                    raise ServerExited(self._ending("exited")) from None
                if time.monotonic() > deadline:
                    raise TimeoutError(self._ending("never listened")) from None
                time.sleep(POLL_INTERVAL_SECONDS)
        pid: object = None
        try:
            with self.client() as client:
                pid = client.get("/seen").json().get("pid")
        except httpx2.HTTPError, ValueError, AttributeError:
            pass
        if pid != startup["pid"]:
            raise PortTaken(self._ending(f"lost port {self.port} to another process"))

    def wait_for_exit(self) -> int:
        """Wait for the process to exit, and return its status."""
        return self.process.wait(timeout=STOP_DEADLINE_SECONDS)

    def stop(self) -> int:
        """Ask uvicorn to stop, as an interrupt does, and wait for the process."""
        if sys.platform == "win32":
            # uvicorn handles SIGBREAK, which Ctrl+Break sends to the process group.
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            self.process.send_signal(signal.SIGTERM)
        return self.wait_for_exit()

    def kill(self) -> int:
        """Kill the process, so it runs nothing more, and wait for it to exit."""
        self.process.kill()
        return self.wait_for_exit()


@contextmanager
def run_server(
    directory: Path,
    *,
    fake_ready: str | None = None,
    fail_startup: str | None = None,
    environment: Mapping[str, str] | None = None,
    stdin: int = subprocess.DEVNULL,
) -> Generator[Server]:
    """
    Start the reference app under uvicorn on a free loopback port, writing its log and
    output in `directory`, and kill it on the way out if it still runs.

    The app's settings come from the arguments, never from the test's environment;
    `environment` adds variables of the test's own.
    """
    port = _free_port()
    log = directory / "observations.jsonl"
    with ExitStack() as stack:
        stdout_path, stderr_path = directory / "stdout.txt", directory / "stderr.txt"
        stdout = stack.enter_context(stdout_path.open("wb"))
        stderr = stack.enter_context(stderr_path.open("wb"))
        # The child inherits the environment as it is when it starts, after which the
        # test's own is restored.
        with pytest.MonkeyPatch.context() as patch:
            patch.setenv(LOG_VARIABLE, str(log))
            for name, value in (
                (FAKE_READY_VARIABLE, fake_ready),
                (FAIL_STARTUP_VARIABLE, fail_startup),
            ):
                if value is None:
                    patch.delenv(name, raising=False)
                else:
                    patch.setenv(name, value)
            for name, value in (environment or {}).items():
                patch.setenv(name, value)
            process = subprocess.Popen(
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
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                # A group of its own, which Ctrl+Break can reach alone.
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if sys.platform == "win32"
                else 0,
            )
        try:
            yield Server(process, port, log, stdout_path, stderr_path)
        finally:
            if process.poll() is None:
                process.kill()
            try:
                process.wait(timeout=STOP_DEADLINE_SECONDS)
            finally:
                if process.stdin is not None:
                    process.stdin.close()


def _free_port() -> int:
    # Bound and released, for uvicorn to bind next. Another process can take it between
    # the two: uvicorn then fails to bind, or the other process answers in its place,
    # which Server.wait_until_serving tells apart by the app's PID.
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        port: int = probe.getsockname()[1]
        return port
