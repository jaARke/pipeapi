import asyncio
from collections.abc import AsyncIterator
from typing import Annotated, Final

from fastapi import APIRouter, Header, HTTPException, Query, Request, WebSocket, status
from fastapi.responses import StreamingResponse

from reference_app.observations import ObservationLog

HOLD_DEADLINE_SECONDS: Final = 600.0
"""
How long a stream waits on its client before the server ends it, which a run that
closes its streams never reaches.
"""


def sse_event(event_id: int) -> str:
    r"""
    Frame one event of the stream as server-sent events frame it.

    Args:
        event_id: The event's ID, which its data repeats.

    Returns:
        The event, ending in the blank line that dispatches it.

    Examples:
        >>> sse_event(3)
        'id: 3\ndata: event 3\n\n'
    """
    return f"id: {event_id}\ndata: event {event_id}\n\n"


def create_router(log: ObservationLog) -> APIRouter:
    """
    Create the stream routes, which record a client that leaves early in the log.

    Args:
        log: The observation log.

    Returns:
        The router.
    """
    router = APIRouter()

    @router.get("/events")
    async def events(
        request: Request,
        *,
        count: Annotated[int, Query(ge=0)] = 3,
        end: Annotated[bool, Query()] = False,
        last_event_id: Annotated[str | None, Header()] = None,
    ) -> StreamingResponse:
        """
        Stream events 1 to `count`, or those after `Last-Event-ID`, then hold it open.

        A held stream stays open until its client disconnects, which is recorded with
        the last event sent, or until the server's hold deadline. With `end`, the
        stream ends after its last event instead. IDs are integers, so a resumed stream
        continues after the one it was given.

        Returns:
            The stream, as `text/event-stream`.

        Raises:
            HTTPException: 400, for a `Last-Event-ID` the stream never sent.
        """
        if last_event_id is None:
            last_sent = 0
        elif last_event_id.isdecimal():
            last_sent = int(last_event_id)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown Last-Event-ID")

        async def stream() -> AsyncIterator[str]:
            sent = last_sent
            finished = False
            try:
                for event_id in range(last_sent + 1, count + 1):
                    yield sse_event(event_id)
                    sent = event_id
                finished = end
                if not end:
                    await asyncio.wait_for(
                        _disconnected(request), HOLD_DEADLINE_SECONDS
                    )
            except asyncio.TimeoutError:
                finished = True
            finally:
                if not finished:
                    log.record("disconnect", route="events", last_event_id=sent)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache"},
        )

    @router.websocket("/ws")
    async def echo_socket(
        websocket: WebSocket,
        *,
        close_after: Annotated[int | None, Query(ge=0)] = None,
        close_code: Annotated[int, Query(ge=4000, le=4999)] = 4000,
    ) -> None:
        """
        Echo each text and binary message, closing after `close_after` of them.

        The server's close carries `close_code` and the reason "closed by the server",
        or "idle" once no message arrives by the server's hold deadline. A client that
        disconnects first is recorded with its close code and the number of messages
        echoed.
        """
        await websocket.accept()
        echoed = 0
        reason = "closed by the server"
        while close_after is None or echoed < close_after:
            try:
                message = await asyncio.wait_for(
                    websocket.receive(), HOLD_DEADLINE_SECONDS
                )
            except asyncio.TimeoutError:
                reason = "idle"
                break
            if message["type"] == "websocket.disconnect":
                log.record(
                    "disconnect", route="ws", code=message.get("code"), echoed=echoed
                )
                return
            text: str | None = message.get("text")
            if text is not None:
                await websocket.send_text(text)
            else:
                await websocket.send_bytes(message.get("bytes") or b"")
            echoed += 1
        await websocket.close(code=close_code, reason=reason)

    return router


async def _disconnected(request: Request) -> None:
    # Wait on the connection itself, so the hold ends on a server that cancels nothing
    # when its client leaves, as ASGI 2.4 servers may.
    while (await request.receive())["type"] != "http.disconnect":
        pass
