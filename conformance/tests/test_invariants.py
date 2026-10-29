from typing import Any, Final

import pytest

from runner.adapter_session import Message, versions
from runner.invariants import LOST, OUTAGE_ENDS, RECONNECTING, events_out_of_order
from runner.repository import REPOSITORY
from runner.schemas import read_document, validator

CONNECTOR_API: Final = (
    REPOSITORY / "protocol" / "connector-api" / "connector-api.schema.json"
)
# The fields each lifecycle event requires beside its type, as an adapter writes them.
LIFECYCLE_FIELDS: Final[dict[str, dict[str, Any]]] = {
    "reconnecting": {"endReason": None},
    "reconnected": {"oldClientId": "c1", "newClientId": "c2"},
    "respawned": {"oldClientId": "c1", "newClientId": "c2"},
    "lost": {
        "reason": "unavailable",
        "error": "connect_timeout",
        "exitCode": None,
        "signal": None,
        "stderrTail": None,
    },
}
CLOSE_ID: Final = 7


def session(*messages: Message) -> list[Message]:
    """A session's transcript, each message checked against the adapter protocol."""
    check = validator(versions()[1])
    for message in messages:
        check.validate(message)
    return list(messages)


def lifecycle(event: str, backend: int = 1) -> Message:
    """A lifecycle event a Backend emitted, as an adapter reports it."""
    fields = {"type": event, **LIFECYCLE_FIELDS[event]}
    return {
        "type": "event",
        "event": "lifecycle",
        "backend": backend,
        "lifecycle": fields,
    }


def close(backend: int = 1) -> Message:
    """The runner's command to close a Backend."""
    return {"type": "command", "id": CLOSE_ID, "command": "close", "backend": backend}


def closed() -> Message:
    """The adapter's reply once close() returned."""
    return {"type": "reply", "id": CLOSE_ID, "command": "close", "result": {}}


@pytest.mark.parametrize("end", sorted(OUTAGE_ENDS))
def test_an_outage_that_ends_in_one_event_keeps_the_order(end: str) -> None:
    transcript = session(lifecycle("reconnecting"), lifecycle(end))
    assert events_out_of_order(transcript) == []


def test_a_backend_lost_without_an_outage_keeps_the_order() -> None:
    assert events_out_of_order(session(lifecycle("lost"))) == []


def test_a_session_without_lifecycle_events_keeps_the_order() -> None:
    transcript = session(
        {"type": "event", "event": "started", "id": 1},
        {"type": "reply", "id": 1, "command": "connect", "result": {"clientId": None}},
    )
    assert events_out_of_order(transcript) == []


@pytest.mark.parametrize("end", ["reconnected", "respawned"])
def test_an_outage_that_ends_without_starting_is_out_of_order(end: str) -> None:
    assert events_out_of_order(session(lifecycle(end))) == [
        f"Backend 1's {end} came with no reconnecting before it"
    ]


def test_a_second_reconnecting_before_the_outage_ends_is_out_of_order() -> None:
    transcript = session(lifecycle("reconnecting"), lifecycle("reconnecting"))
    assert events_out_of_order(transcript) == [
        "Backend 1's reconnecting came during an outage, "
        "before reconnected, respawned or lost"
    ]


def test_an_outage_that_ends_twice_is_out_of_order() -> None:
    transcript = session(
        lifecycle("reconnecting"), lifecycle("reconnected"), lifecycle("respawned")
    )
    assert events_out_of_order(transcript) == [
        "Backend 1's respawned came with no reconnecting before it"
    ]


def test_no_event_follows_lost() -> None:
    transcript = session(lifecycle("lost"), lifecycle("reconnecting"))
    assert events_out_of_order(transcript) == [
        "Backend 1's reconnecting came after lost"
    ]


def test_no_event_follows_close() -> None:
    transcript = session(close(), closed(), lifecycle("lost"))
    assert events_out_of_order(transcript) == ["Backend 1's lost came after close()"]


def test_close_ends_an_outage() -> None:
    transcript = session(lifecycle("reconnecting"), close(), closed())
    assert events_out_of_order(transcript) == []


def test_an_event_before_the_reply_to_close_may_have_come_before_it() -> None:
    transcript = session(close(), lifecycle("reconnecting"), closed())
    assert events_out_of_order(transcript) == []


def test_a_refused_close_closes_nothing() -> None:
    refusal = {"code": "invalid_command", "message": "no Backend is named 1"}
    transcript = session(
        close(),
        {"type": "reply", "id": CLOSE_ID, "command": "close", "refusal": refusal},
        lifecycle("lost"),
    )
    assert events_out_of_order(transcript) == []


def test_an_outage_open_at_the_sessions_end_breaks_nothing() -> None:
    assert events_out_of_order(session(lifecycle("reconnecting"))) == []


def test_each_backends_events_are_ordered_apart() -> None:
    transcript = session(
        lifecycle("reconnecting", backend=1),
        lifecycle("reconnecting", backend=2),
        lifecycle("reconnected", backend=1),
        close(backend=2),
        closed(),
        lifecycle("lost", backend=1),
        lifecycle("reconnecting", backend=2),
    )
    assert events_out_of_order(transcript) == [
        "Backend 2's reconnecting came after close()"
    ]


def test_the_order_names_each_lifecycle_event_type_the_connector_api_defines() -> None:
    members = read_document(CONNECTOR_API)["$defs"]["event"]["oneOf"]
    defined = {member["properties"]["type"]["const"] for member in members}
    assert {RECONNECTING, LOST, *OUTAGE_ENDS} == defined
