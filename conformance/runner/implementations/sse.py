from runner.adapter_session import Message
from runner.case_run import CaseRun
from runner.observations import Observation
from runner.registry import implements


def is_disconnect(observation: Observation) -> bool:
    """
    Tell whether an observation records a client leaving the event stream.

    Args:
        observation: The observation.

    Returns:
        Whether it does.
    """
    return observation["event"] == "disconnect" and observation["route"] == "events"


def check_events(events: list[Message], count: int) -> None:
    """
    Check that a stream's events are the reference app's first ones, in order.

    Args:
        events: The events the SSE helper gave.
        count: How many there must be.
    """
    shown = [(each["eventType"], each["data"], each["eventId"]) for each in events]
    expected = [("message", f"event {i}", str(i)) for i in range(1, count + 1)]
    assert shown == expected


@implements("sse.first-event-before-end")
def events_arrive_while_the_stream_is_open(run: CaseRun) -> None:
    """Check that events reach the client before the stream ends."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    before = len(app.observations())
    stream = client.sse(backend, "/events?count=3", via=run.via)
    check_events(client.sse_events(stream, 3), 3)
    assert not any(map(is_disconnect, app.observations()[before:]))
    client.call("cancel", commandId=stream).result()
    client.reply(stream)


@implements("sse.abort")
def aborting_a_stream(run: CaseRun) -> None:
    """Check that an aborted stream ends with the abort error and the app sees it."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    before = len(app.observations())
    stream = client.sse(backend, "/events?count=1", via=run.via)
    check_events(client.sse_events(stream, 1), 1)
    client.call("cancel", commandId=stream).result()
    ended = client.reply(stream).message
    assert ended.get("languageError", {}).get("kind") == "cancellation", ended
    disconnect = app.wait_for(is_disconnect, after=before, deadline=run.deadline)
    assert disconnect["last_event_id"] == 1


@implements("sse.server-ends")
def a_stream_the_server_ends_ends_the_iteration(run: CaseRun) -> None:
    """Check that a stream the server ends ends the iteration without an error."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    stream = client.sse(backend, "/events?count=2&end=true", via=run.via)
    client.reply(stream).result()
    check_events(client.sse_events(stream, 2), 2)


@implements("sse.client-killed")
def a_dead_clients_connection_closes(run: CaseRun) -> None:
    """Check that the app sees a client killed hard leave its stream."""
    app = run.app()
    client = run.client()
    backend = run.connect(client, app)
    before = len(app.observations())
    stream = client.sse(backend, "/events?count=1", via=run.via)
    client.sse_events(stream, 1)
    client.kill()
    app.wait_for(is_disconnect, after=before, deadline=run.deadline)
