from collections.abc import Callable, Iterable, Mapping
from typing import Final, Literal

from runner.adapter_session import Message
from runner.case_run import CaseRun
from runner.plan import PlannedInvariant

type InvariantCheck = Callable[[CaseRun], None]
"""A check of one invariant, run on a permutation that passed, once its clients end."""

# The connector API's lifecycle event types the order names, which a test holds equal
# to its file's.
RECONNECTING: Final = "reconnecting"
LOST: Final = "lost"
OUTAGE_ENDS: Final = frozenset({"reconnected", "respawned", LOST})
"""The events that end an outage, exactly one of which follows each reconnecting."""


def checked_as_received(_run: CaseRun) -> None:
    """
    Leave an invariant to the adapter session or the raw client, which check each
    line as they receive it, so the case's end has nothing left to check.

    Args:
        _run: The permutation's context.
    """


def events_out_of_order(transcript: Iterable[Message]) -> list[str]:
    """
    Find each lifecycle event in an adapter's session that breaks the order the
    connector API gives a Backend's events.

    Each Backend's events are ordered apart. A ``reconnecting`` starts an outage,
    which exactly one ``reconnected``, ``respawned`` or ``lost`` ends, with no event
    between, and no event follows ``lost`` or ``close()``. ``close()`` counts from
    its reply, the first point at which it has surely come, and ends an outage too.
    An outage still open at the session's end breaks nothing, since an adapter exits
    at the end of its stdin without waiting for one to end.

    Args:
        transcript: The session, as
            :meth:`~runner.adapter_session.AdapterSession.transcript` gives it.

    Returns:
        A message for each event out of order, naming its Backend, in the order the
        adapter wrote them.
    """
    commands: dict[int, Message] = {}
    standings: dict[int, _Standing] = {}
    found: list[str] = []
    for message in transcript:
        if message["type"] == "command":
            commands[message["id"]] = message
        elif message["type"] == "reply" and "refusal" not in message:
            command = commands.get(message["id"])
            if command is not None and command["command"] == "close":
                standings[command["backend"]] = "closed"
        elif message["type"] == "event" and message["event"] == "lifecycle":
            backend: int = message["backend"]
            event: str = message["lifecycle"]["type"]
            standing, problem = _after(standings.get(backend, "serving"), event)
            standings[backend] = standing
            if problem is not None:
                found.append(f"Backend {backend}'s {event} came {problem}")
    return found


def event_order(run: CaseRun) -> None:
    """
    Check that each client's Backends emitted their lifecycle events in the order the
    connector API gives them, as :func:`events_out_of_order` finds them.

    Args:
        run: The permutation's context.
    """
    found = [
        f"{client.name}: {problem}"
        for client in run.clients
        for problem in events_out_of_order(client.transcript())
    ]
    assert found == [], f"lifecycle events out of order: {'; '.join(found)}"


def no_token_in_output(run: CaseRun) -> None:
    """
    Check that no file the case wrote holds its token.

    The files are the case's trace, which holds every line each adapter wrote, and
    each backend's output and observation log. The trace's records of the runner's
    own commands hide the token, so a file holds it only where something else wrote
    it.

    Args:
        run: The permutation's context.
    """
    token = run.token.encode()
    holding = [
        path.relative_to(run.directory).as_posix()
        for path in sorted(run.directory.rglob("*"))
        if path.is_file() and token in path.read_bytes()
    ]
    assert holding == [], f"the case's token appears in {', '.join(holding)}"


CHECKS: Final[Mapping[str, InvariantCheck]] = {
    "invariant.contract-schemas": checked_as_received,
    "invariant.adapter-shapes": checked_as_received,
    "invariant.event-order": event_order,
    "invariant.no-token-in-output": no_token_in_output,
}
"""
The runner's check of each invariant it checks, by the invariant's ID in the case
list, run at a case's end. An invariant with no check here isn't checked yet, which
fails the run once every component it needs is built.
"""


def check_invariants(run: CaseRun, invariants: Iterable[PlannedInvariant]) -> None:
    """
    End a permutation's clients, then check each invariant whose components are built
    by its check in :data:`CHECKS`.

    The clients end first, so a check sees everything they wrote.

    Args:
        run: The permutation's context, once its implementation passed.
        invariants: The run's invariants.

    Raises:
        AssertionError: An invariant doesn't hold, with a note that names it.
    """
    run.end_clients()
    for planned in invariants:
        check = CHECKS.get(planned.invariant.id)
        if check is None or planned.unbuilt:
            continue
        try:
            check(run)
        except AssertionError as violation:
            violation.add_note(f"{planned.invariant.id} doesn't hold")
            raise


# Where a Backend's lifecycle stands: serving, in an outage a reconnecting started,
# lost, or closed by close().
type _Standing = Literal["serving", "outage", "lost", "closed"]


def _after(standing: _Standing, event: str) -> tuple[_Standing, str | None]:
    # Where a Backend stands after an event, and how the event breaks the order.
    if standing == "lost":
        return standing, "after lost"
    if standing == "closed":
        return standing, "after close()"
    if standing == "outage":
        if event in OUTAGE_ENDS:
            return ("lost" if event == LOST else "serving"), None
        return standing, "during an outage, before reconnected, respawned or lost"
    if event == RECONNECTING:
        return "outage", None
    if event == LOST:
        return "lost", None
    if event in OUTAGE_ENDS:
        return standing, "with no reconnecting before it"
    return standing, None
