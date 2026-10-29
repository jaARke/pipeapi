import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Self

# How often a wait looks again at what it waits for. Short, so an interrupt lands
# between two looks, since a blocking wait on Windows takes no Ctrl+C until it ends.
POLL_INTERVAL_SECONDS: Final = 0.02


class DeadlinePassed(Exception):
    """A wait outlasted its bound, naming what it waited for and the bound."""


@dataclass(frozen=True)
class Deadline:
    """
    A point in time after which work stops waiting, such as the end of a case.

    Every wait on another process takes the earlier of its own hang guard and the
    deadline of the work it belongs to, through :meth:`bound` or :func:`wait_until`,
    so no case outlives its deadline whichever wait it is in.
    """

    at: float
    """The point in time, on the monotonic clock."""
    what: str
    """What ends there, which a failure names, such as a case's ID."""

    @classmethod
    def after(cls, seconds: float, what: str) -> Self:
        """
        Make a deadline some time from now.

        Args:
            seconds: How long from now.
            what: What ends there.

        Returns:
            The deadline.
        """
        return cls(time.monotonic() + seconds, what)

    def remaining(self) -> float:
        """
        Measure the time left.

        Returns:
            The seconds left, or 0 once it has passed.
        """
        return max(0.0, self.at - time.monotonic())

    def bound(self, guard: float, waiting_for: str) -> float:
        """
        Bound one wait by its hang guard and by the deadline, whichever ends first.

        Args:
            guard: The wait's own hang guard, in seconds.
            waiting_for: What the wait is for, which the failure names.

        Returns:
            The seconds the wait may take.

        Raises:
            DeadlinePassed: The deadline has already passed.
        """
        remaining = self.remaining()
        if remaining <= 0:
            raise DeadlinePassed(f"{self.what} ended while waiting for {waiting_for}")
        return min(guard, remaining)


def wait_until[T](
    found: Callable[[], T | None],
    *,
    guard: float,
    deadline: Deadline | None,
    waiting_for: str,
) -> T:
    """
    Look for something again and again until it is there, within the bounds.

    Args:
        found: What to look for, returning None while it isn't there.
        guard: The wait's own hang guard, in seconds.
        deadline: The deadline of the work the wait belongs to, if any.
        waiting_for: What the wait is for, which the failure names.

    Returns:
        What ``found`` returned once it wasn't None.

    Raises:
        DeadlinePassed: The guard or the deadline passed first, naming which.
    """
    ends = time.monotonic() + guard
    while True:
        result = found()
        if result is not None:
            return result
        now = time.monotonic()
        if deadline is not None and now >= deadline.at:
            message = f"{deadline.what} ended while waiting for {waiting_for}"
            raise DeadlinePassed(message)
        if now >= ends:
            raise DeadlinePassed(f"waited {guard:g} seconds for {waiting_for}")
        time.sleep(POLL_INTERVAL_SECONDS)
