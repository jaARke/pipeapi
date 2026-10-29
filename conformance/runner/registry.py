import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from typing import Final

from runner.case_run import CaseRun

IMPLEMENTATIONS_PACKAGE: Final = "runner.implementations"

type Implementation = Callable[[CaseRun], None]
"""A case's implementation, which sets up the case and checks its expectation."""


@dataclass(frozen=True)
class Registration:
    """One function that names the case it implements."""

    case: str
    function: Implementation

    @property
    def where(self) -> str:
        """The function's module and name."""
        return f"{self.function.__module__}.{self.function.__qualname__}"


REGISTRATIONS: Final[list[Registration]] = []
"""Every registration, in the order the modules made them, duplicates included."""


def implements(case: str) -> Callable[[Implementation], Implementation]:
    """
    Name the case a function implements, by its ID.

    A case is implemented at most once, and every implementation names a case the
    case list defines, which the conformance project's checks hold.

    Args:
        case: The case's ID.

    Returns:
        A decorator that registers the function and returns it as it is.
    """

    def register(function: Implementation) -> Implementation:
        REGISTRATIONS.append(Registration(case, function))
        return function

    return register


@cache
def load_implementations() -> list[Registration]:
    """
    Import every module of the implementations package, once, so each registers.

    Returns:
        Every registration.
    """
    package = importlib.import_module(IMPLEMENTATIONS_PACKAGE)
    for module in pkgutil.iter_modules(package.__path__, f"{IMPLEMENTATIONS_PACKAGE}."):
        importlib.import_module(module.name)
    return list(REGISTRATIONS)


def implementation_of(case: str) -> Implementation | None:
    """
    Find a case's implementation.

    Args:
        case: The case's ID.

    Returns:
        The first function that names it, or None for a case not yet implemented.
    """
    for registration in load_implementations():
        if registration.case == case:
            return registration.function
    return None
