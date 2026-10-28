import asyncio
import sys
import threading
from typing import Annotated, Final, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator

from reference_app import environment

INPUT_DEADLINE_SECONDS: Final = 5.0
"""
How long the input route waits on ``input()``, which a backend whose stdin is the null
device never reaches.
"""

MAX_OUTPUT_CHARACTERS: Final = 64 * 1024 * 1024
"""The most the output route writes for one request."""


class EnvironmentQuery(BaseModel):
    """What to ask of the environment."""

    names: list[str] = Field(default_factory=list)
    """The variables whose values to report."""
    containing: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    """Texts to look for in every variable's value."""


class InputOutcome(BaseModel):
    """What ``input()`` gave."""

    outcome: Literal["eof", "line", "failed", "blocked"]
    """
    ``eof`` at the end of stdin, ``line`` for a line read, ``failed`` when stdin could
    not be read, and ``blocked`` when ``input()`` was still waiting at the route's
    deadline.
    """
    line: str | None = None
    """The line read, without its newline."""
    error: str | None = None
    """Why stdin could not be read."""


class OutputRequest(BaseModel):
    """What to write, as lines of a known shape a sink can check one by one."""

    stream: Literal["stdout", "stderr"]
    lines: int = Field(ge=0)
    width: int = Field(default=100, ge=1, le=1024 * 1024)
    """Each line's length, without its newline, which its tag and index must fit in."""
    tag: str = Field(default="output", pattern=r"^[A-Za-z0-9_-]{1,16}$")
    """What each line starts with, so the lines of one request are told apart."""

    @model_validator(mode="after")
    def check_shape(self) -> "OutputRequest":
        """
        Check that each line fits its tag and index, and that the request asks for no
        more than :data:`MAX_OUTPUT_CHARACTERS`.

        Returns:
            The request.

        Raises:
            ValueError: A line is narrower than its prefix, or the request asks for
                more.
        """
        # The size bound keeps every index below 10**8, so index 0's prefix is every
        # line's.
        prefix = len(output_line(self.tag, 0, 0))
        if self.width < prefix:
            raise ValueError(f"width is narrower than the {prefix}-character prefix")
        if self.lines * self.width > MAX_OUTPUT_CHARACTERS:
            raise ValueError(f"lines times width exceeds {MAX_OUTPUT_CHARACTERS}")
        return self


class OutputWritten(BaseModel):
    """What the output route wrote."""

    lines: int


def output_line(tag: str, index: int, width: int) -> str:
    """
    Write one line of the output route's output, without its newline.

    Args:
        tag: What the line starts with.
        index: The line's index, from 0.
        width: The line's length, padded with dots.

    Returns:
        The line.

    Examples:
        >>> output_line("sink", 7, 24)
        'sink 00000007 ..........'
    """
    return f"{tag} {index:08d} ".ljust(width, ".")


def create_router() -> APIRouter:
    """
    Create the process routes.

    Returns:
        The router.
    """
    router = APIRouter()

    @router.post("/environment")
    async def probe_environment(
        query: EnvironmentQuery,
    ) -> environment.EnvironmentReport:
        """
        Report what the environment holds, read as the request arrives.

        Returns:
            The values of the variables named, and the names of those that contain
            each text, never any other value.
        """
        return environment.probe(query.names, query.containing)

    @router.post("/input")
    async def read_input() -> InputOutcome:
        """
        Call `input()` and report what it gave, waiting on it no longer than a deadline.

        It reads on a daemon thread, so an `input()` that never returns neither blocks
        other requests nor keeps the process from exiting.

        Returns:
            What `input()` gave.
        """
        loop = asyncio.get_running_loop()
        outcome: asyncio.Future[InputOutcome] = loop.create_future()

        def settle(result: InputOutcome) -> None:
            if not outcome.done():
                outcome.set_result(result)

        def read() -> None:
            try:
                result = InputOutcome(outcome="line", line=input())
            except EOFError:
                result = InputOutcome(outcome="eof")
            except (OSError, RuntimeError, ValueError) as error:
                result = InputOutcome(outcome="failed", error=str(error))
            try:
                loop.call_soon_threadsafe(settle, result)
            except RuntimeError:
                # The loop closed while input() waited, so no request waits on it.
                return

        threading.Thread(target=read, name="reference-app-input", daemon=True).start()
        try:
            return await asyncio.wait_for(outcome, INPUT_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            return InputOutcome(outcome="blocked")

    @router.post("/output")
    def write_output(request: OutputRequest) -> OutputWritten:
        """
        Write `lines` numbered lines of `width` characters to stdout or stderr.

        It runs on a worker thread, so a sink that stops reading blocks this request,
        not the others.

        Returns:
            How many lines were written.
        """
        # Looked up for each request, so a server's wrapper around the stream is used.
        stream = sys.stdout if request.stream == "stdout" else sys.stderr
        for index in range(request.lines):
            stream.write(output_line(request.tag, index, request.width) + "\n")
        stream.flush()
        return OutputWritten(lines=request.lines)

    return router
