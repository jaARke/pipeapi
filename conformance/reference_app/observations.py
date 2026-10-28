import json
import os
from pathlib import Path
from typing import Literal, TypeAlias

from starlette.types import ASGIApp, Receive, Scope, Send

Event: TypeAlias = Literal[
    "startup", "startup_failure", "shutdown", "request", "disconnect"
]
"""
What an observation reports.

- ``startup``: the lifespan startup ran, so the app is about to serve.
- ``startup_failure``: the lifespan startup failed, as its settings asked, with its
  ``message``.
- ``shutdown``: the lifespan shutdown ran.
- ``request``: a request reached the app, with its ``type`` (``http`` or
  ``websocket``), ``method`` (None for a WebSocket), ``path`` and ``query``.
- ``disconnect``: a client went away before its stream ended, with the ``route`` and
  what the route had sent or received by then.
"""

ObservationValue: TypeAlias = str | int | None
"""A value an observation carries beside its event and the app's PID."""


class ObservationLog:
    """
    Appends each observation to a file, as one JSON object on a line of its own.

    Every object holds its ``event`` and the ``pid`` of the process that saw it, so a
    runner tells apart the backends that share a log, one after another. Each line is
    written before the code that saw the event goes on, so it survives the process
    being killed. Backends that may run at the same time need logs of their own, since
    appends from several processes are not atomic on Windows.

    A log without a path records nothing.
    """

    def __init__(self, path: Path | None) -> None:
        self._path = path

    def record(self, event: Event, **fields: ObservationValue) -> None:
        """
        Append an observation.

        Args:
            event: What happened.
            **fields: What the event carries.
        """
        if self._path is None:
            return
        line = json.dumps({"event": event, "pid": os.getpid(), **fields}) + "\n"
        # Opened for each line, so no handle outlives a write, whatever ends the
        # process; binary, so lines end in LF on every platform.
        with self._path.open("ab") as file:
            file.write(line.encode())


class RecordRequests:
    """ASGI middleware that records a ``request`` observation as each one arrives."""

    def __init__(self, app: ASGIApp, log: ObservationLog) -> None:
        self._app = app
        self._log = log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Record an HTTP or WebSocket request, then pass every scope to the app."""
        if scope["type"] in ("http", "websocket"):
            self._log.record(
                "request",
                type=scope["type"],
                method=scope.get("method"),
                path=scope["path"],
                query=scope["query_string"].decode("latin-1"),
            )
        await self._app(scope, receive, send)
