from runner.adapter_session import AdapterSession, Message
from runner.case_run import CaseRun
from runner.fake_server import FakeScript, FakeServer, HelloScript, LeaseScript, Line
from runner.proofs import HELLO_MISTAKES, HelloMistake
from runner.registry import implements

# The connector's most verbose level, so every record it logs reaches the case.
LOGGING = "debug"

# What a server of a later protocol version might add, which a client ignores.
UNKNOWN_FEATURE = "future_feature"
UNKNOWN_PROPERTY = "future_property"
UNKNOWN_HEADER = ("X-PipeAPI-Future", "1")
UNKNOWN_EVENT = "future_event"
# A proof v1 can't read, which a client never reads in a hello of a version it lacks.
NO_V1_PROOF = {"proof": None}
# The end reason the fake ends the lease with last, after which a client reconnects.
FINAL_END_REASON = "restart"


def connect_to(client: AdapterSession, fake: FakeServer) -> Message:
    """
    Call ``connect()`` on the fake's endpoint, with logging on, and wait for it.

    Args:
        client: The client.
        fake: The fake server.

    Returns:
        The reply.
    """
    options = {"endpoint": fake.endpoint, "token": fake.token}
    return client.call("connect", options=options, logging=LOGGING).message


def error_code(reply: Message) -> str | None:
    """
    Read the connector error a reply carries.

    Args:
        reply: The reply.

    Returns:
        Its code, or None when the call didn't fail with one.
    """
    error: Message | None = reply.get("error")
    return None if error is None else error["code"]


def token_for(run: CaseRun, mistake: HelloMistake) -> str:
    """
    Choose a token whose proof the mistake changes.

    Trimming changes only a token with spaces around it, and the case's token, a
    generated one, has none.

    Args:
        run: The permutation's context.
        mistake: The mistake.

    Returns:
        The token.
    """
    return f"  {run.token}  " if mistake == "TrimmedTokenKey" else run.token


def is_verification_failure(event: Message) -> bool:
    """
    Tell whether an event is the connector's record of a hello that failed to verify.

    Args:
        event: The event.

    Returns:
        Whether it is.
    """
    return event["event"] == "log" and event["record"]["event"] == "verification_failed"


def is_reconnecting_at_the_end(event: Message) -> bool:
    """
    Tell whether an event is the connector's ``reconnecting`` after the lease's
    scripted end.

    Args:
        event: The event.

    Returns:
        Whether it is.
    """
    return (
        event["event"] == "lifecycle"
        and event["lifecycle"]["type"] == "reconnecting"
        and event["lifecycle"]["endReason"] == FINAL_END_REASON
    )


def is_warning_or_error(event: Message) -> bool:
    """
    Tell whether an event is a record the connector logged as a warning or an error,
    other than its record of reconnecting, which may come before the event itself.

    Args:
        event: The event.

    Returns:
        Whether it is.
    """
    return (
        event["event"] == "log"
        and event["record"]["level"] in {"warning", "error"}
        and event["record"]["event"] != "reconnecting"
    )


@implements("hello.wrong-proof")
def a_wrong_proof_stops_the_client_before_it_enrolls(run: CaseRun) -> None:
    """Check that each mistake the hello-proof vectors name fails verification."""
    client = run.client()
    for mistake in sorted(HELLO_MISTAKES):
        script = FakeScript(hello=HelloScript(mistake=mistake))
        fake = run.fake(script, token_for(run, mistake))
        recorded = len(client.events(is_verification_failure))
        reply = connect_to(client, fake)
        assert error_code(reply) == "verification_failed", (mistake, reply)
        client.wait_for_event(
            lambda _event, before=recorded: (
                len(client.events(is_verification_failure)) > before
            ),
            f"the verification_failed record of {mistake}",
        )
        assert fake.requests("lease") == (), mistake


@implements("hello.no-common-protocol")
def no_common_version_fails_naming_both_sides(run: CaseRun) -> None:
    """Check that a server of only another version fails naming both sides."""
    client = run.client()
    for properties in ({}, NO_V1_PROOF):
        hello = HelloScript(protocols=(2,), properties=properties)
        fake = run.fake(FakeScript(hello=hello))
        reply = connect_to(client, fake)
        error: Message = reply.get("error") or {}
        assert error.get("code") == "no_common_protocol", (properties, reply)
        assert (error["clientProtocols"], error["serverProtocols"]) == ([1], [2])
        assert fake.requests("lease") == (), properties


@implements("hello.client-ignores-unknown")
def a_client_ignores_what_it_doesnt_know(run: CaseRun) -> None:
    """Check that unknown properties, features, headers and events change nothing."""
    client = run.client()
    hello = HelloScript(
        features=(UNKNOWN_FEATURE,),
        properties={UNKNOWN_PROPERTY: 1},
        headers=(UNKNOWN_HEADER,),
    )
    # The end comes last, so the reconnecting it causes follows whatever the unknown
    # lines made the connector do.
    lease = LeaseScript(
        session_properties={UNKNOWN_PROPERTY: 1},
        lines=(
            Line.heartbeat(),
            Line.event({"type": UNKNOWN_EVENT, UNKNOWN_PROPERTY: 1}),
            Line.event({"type": "heartbeat", UNKNOWN_PROPERTY: 1}),
            Line.end(FINAL_END_REASON),
        ),
        headers=(UNKNOWN_HEADER,),
    )
    fake = run.fake(FakeScript(hello=hello, lease=lease))
    reply = connect_to(client, fake)
    assert "result" in reply, reply
    control = client.wait_for_event(
        is_reconnecting_at_the_end, f"the reconnecting after the {FINAL_END_REASON}"
    )
    lifecycle = client.events(lambda each: each["event"] == "lifecycle", before=control)
    assert lifecycle == []
    assert client.events(is_warning_or_error, before=control) == []
