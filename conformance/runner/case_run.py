import shutil
import tempfile
from collections.abc import Mapping
from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import Final

from reference_app.environment import LOG_VARIABLE
from runner.adapter_session import AdapterSession, Hello, start_adapter
from runner.adapters import AdapterManifest
from runner.cases import Case, Run, Transport, Via
from runner.deadlines import Deadline
from runner.fake_server import (
    FakeScript,
    FakeServer,
    Listener,
    TcpListener,
    UnixListener,
)
from runner.observations import read_observations
from runner.plan import Planned
from runner.processes import Changes, Process, Processes, end_learned
from runner.proofs import random_b64u_32
from runner.trace import Trace
from runner.uvicorn_server import LOG_FILE_NAME, Server, run_server

# Every case ends well within this, unless it waits out one of the protocol's fixed
# durations on purpose; a hang guard.
CASE_DEADLINE_SECONDS: Final = 60.0
# A slow case waits out a fixed duration of up to two minutes, then checks.
SLOW_CASE_DEADLINE_SECONDS: Final = 300.0


class RunnerFault(Exception):
    """
    An assertion or a wait of the runner's own failed as it set up or ended a case.

    It is never the connector's behavior, so no expected failure covers it.
    """


class CaseRun:
    """
    Everything one permutation of a case works with, closed when it ends.

    An implementation asks it for the app and for clients, and it starts each as
    the run has it: in the baseline run, the reference app under plain uvicorn on
    loopback and the baseline adapter. Everything it starts belongs to the case's
    processes and trace, and closes on every path out of the case.
    """

    def __init__(
        self,
        planned: Planned,
        transport: Transport,
        *,
        directory: Path,
        stack: ExitStack,
        every: list[Process],
        manifest: AdapterManifest | None,
        hello: Hello | None,
    ) -> None:
        self.case: Case = planned.case
        self.run: Run = planned.run
        self.transport = transport
        """The transport the permutation runs on."""
        self.via: Via = planned.via or "untyped"
        """
        What the permutation's requests go through: its own, for a case that varies
        by it, and otherwise the untyped request.
        """
        self.directory = directory
        """The case's directory in the run's trace, which holds its files."""
        self.hello = hello
        """The hello of the run's adapter, read once for the run."""
        seconds = (
            SLOW_CASE_DEADLINE_SECONDS if self.case.slow else CASE_DEADLINE_SECONDS
        )
        self.deadline = Deadline.after(seconds, f"the case {planned.id}")
        self.token = random_b64u_32()
        """The token the case's backends and clients share, as a connector makes one."""
        self.trace = stack.enter_context(Trace(directory / "trace.log"))
        what = f"{planned.id} in the {self.run} run on {transport}"
        self.trace.record("runner", f"{what}, within {seconds:g} seconds")
        self.processes = stack.enter_context(Processes(self.trace, every))
        # Before the processes close, and after the clients and backends the case
        # started, which a stack closes last to first.
        stack.callback(self._end_logged_backends)
        self._stack = stack
        self._manifest = manifest
        self._clients: list[AdapterSession] = []
        self._apps = 0
        self._adapters = 0

    @property
    def clients(self) -> tuple[AdapterSession, ...]:
        """Each client the case started, in the order it started them."""
        return tuple(self._clients)

    def _end_logged_backends(self) -> None:
        # Every backend that served the case logged to a file in its directory, the
        # backends a connector spawned included, which the runner didn't start.
        for log in self.directory.rglob(LOG_FILE_NAME):
            pids = sorted(
                {observation["pid"] for observation in read_observations(log)}
            )
            end_learned(pids, partial(_logs_to, str(log)), self.trace)

    def app(self) -> Server:
        """
        Start a backend serving the reference app, and wait until it serves.

        Returns:
            The backend.

        Raises:
            RuntimeError: The run reaches the app through pipeapi's server, which no
                run starts yet, since no case that needs it runs.
        """
        if self.run != "baseline":
            message = f"the {self.run} run reaches the app through pipeapi's server"
            raise RuntimeError(message)
        self._apps += 1
        directory = self.directory / f"backend-{self._apps}"
        directory.mkdir(parents=True)
        server = self._stack.enter_context(run_server(directory, self.processes))
        server.wait_until_serving(self.deadline)
        return server

    def fake(
        self, script: FakeScript | None = None, token: str | None = None
    ) -> FakeServer:
        """
        Start the fake server on the permutation's transport.

        Args:
            script: What it answers, or None for answers as a server's.
            token: The token it proves it holds, or None for the case's.

        Returns:
            The fake, listening.

        Raises:
            RuntimeError: The fake has no listener on the transport yet.
        """
        if self.transport == "tcp":
            listener: Listener = TcpListener()
        elif self.transport == "unix":
            # Not the case's directory, whose path a socket's limit of about 100
            # bytes may not hold.
            directory = Path(tempfile.mkdtemp(prefix="pipeapi-fake-"))
            self._stack.callback(shutil.rmtree, directory, ignore_errors=True)
            listener = UnixListener(directory / "s.sock")
        else:
            raise RuntimeError(f"the fake server has no {self.transport} listener")
        token = self.token if token is None else token
        server = FakeServer(token, script, listener, deadline=self.deadline)
        return self._stack.enter_context(server)

    def client(self, changes: Changes | None = None) -> AdapterSession:
        """
        Start a client: an adapter of the run's connector.

        Args:
            changes: The changes the case makes to its environment, such as proxies.

        Returns:
            The adapter's session, once its hello has come.

        Raises:
            RuntimeError: The run has no adapter, as a server case's doesn't.
        """
        if self._manifest is None:
            raise RuntimeError(f"the {self.run} run has no adapter")
        self._adapters += 1
        session = start_adapter(
            f"adapter {self._adapters}",
            self._manifest,
            self.processes,
            self.trace,
            self.deadline,
            changes,
            secrets=(self.token,),
        )
        self._clients.append(session)
        self._stack.callback(session.close)
        return session

    def connect(self, client: AdapterSession, app: Server) -> int:
        """
        Connect a client to a running backend, by its endpoint and token.

        Args:
            client: The client.
            app: The backend.

        Returns:
            The Backend's name in the client's adapter.
        """
        return client.connect({"endpoint": app.endpoint, "token": self.token})

    def end_clients(self) -> None:
        """
        End each client the case started, as the case's end does: its stdin, then its
        exit with status 0 and the end of its stdout, so everything it wrote is in.

        Raises:
            AdapterFault: A client didn't exit at once with status 0, or wrote a line
                that broke the protocol, which no wait raised.
        """
        for client in self._clients:
            client.close()


def _logs_to(log: str, environment: Mapping[str, str]) -> bool:
    return environment.get(LOG_VARIABLE) == log
