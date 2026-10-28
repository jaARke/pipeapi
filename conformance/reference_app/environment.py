import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

LOG_VARIABLE: Final = "REFERENCE_APP_LOG"
"""
The file the app appends its observations to, as an absolute path.

Unset or empty, the app records nothing.
"""

FAKE_READY_VARIABLE: Final = "REFERENCE_APP_FAKE_READY"
"""
A line the app writes on stdout as its lifespan startup begins.

It stands in for a readiness signal on stdio, which the protocol has none of, so a
connector that waits for one is caught. Unset or empty, the app writes none.
"""

FAIL_STARTUP_VARIABLE: Final = "REFERENCE_APP_FAIL_STARTUP"
"""
A message the app's lifespan startup fails with, so the server exits before it serves.

Unset or empty, the startup succeeds.
"""


@dataclass(frozen=True)
class Settings:
    """What the environment tells the app, read once as its entry point creates it."""

    log: Path | None = None
    """The observation log, if the app keeps one."""
    fake_ready: str | None = None
    """The fake ready line, if the app writes one."""
    fail_startup: str | None = None
    """The startup failure's message, if the startup fails."""


@dataclass(frozen=True)
class EnvironmentReport:
    """What the app's environment holds, as far as the probe was asked."""

    variables: dict[str, str | None]
    """Each name asked for, with its value, or None where it is unset."""
    containing: dict[str, list[str]]
    """Each text asked for, with the names of the variables whose values contain it."""


def read_settings() -> Settings:
    """
    Read the settings from the environment.

    Returns:
        The settings.

    Raises:
        ValueError: The log's path is not absolute, since the server's directory
            may not be the runner's.
    """
    log = _value(LOG_VARIABLE)
    if log is not None and not Path(log).is_absolute():
        raise ValueError(f"{LOG_VARIABLE} must be an absolute path")
    return Settings(
        log=None if log is None else Path(log),
        fake_ready=_value(FAKE_READY_VARIABLE),
        fail_startup=_value(FAIL_STARTUP_VARIABLE),
    )


def probe(names: Iterable[str], containing: Iterable[str]) -> EnvironmentReport:
    """
    Report what the environment holds, read as each request arrives.

    Only the variables asked for are reported, so the environment's other values,
    which may be a developer's secrets, never leave the process.

    Args:
        names: The variables whose values to report.
        containing: Texts to look for in every variable's value, such as a token
            that must not be there under any name.

    Returns:
        The report.
    """
    return EnvironmentReport(
        variables={name: os.environ.get(name) for name in names},
        containing={
            text: sorted(name for name, value in os.environ.items() if text in value)
            for text in containing
        },
    )


def _value(name: str) -> str | None:
    return os.environ.get(name) or None
