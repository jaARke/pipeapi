import asyncio
import base64
import os
from collections.abc import AsyncIterator
from typing import Annotated, Any, Final

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from reference_app.routers.operations import require_operation_id

BARRIER_DEADLINE_SECONDS: Final = 30.0
"""
How long a barrier waits for its parties, which a run that sends them all never
reaches.
"""

SEEN_METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE")
"""The methods the seen route answers."""

SET_COOKIES: Final = ("first=1; Path=/", "second=2; Path=/")
"""The ``Set-Cookie`` values the headers route sends, each in a header of its own."""


class Seen(BaseModel):
    """What the app saw of a request, as its ASGI scope and body gave it."""

    pid: int
    """The PID of the process that served it."""
    method: str
    path: str
    """The path, percent-decoded."""
    raw_path: str | None
    """The path as it arrived, if the server gave it."""
    query: str
    """The query string as it arrived."""
    http_version: str
    scheme: str
    headers: list[tuple[str, str]]
    """Each header in the order it arrived, a repeated one repeated."""
    body: str
    """The body, base64-encoded."""
    client: tuple[str, int] | None
    """``request.client``, as an app reads it."""
    server: tuple[str, int | None] | None
    pipeapi: dict[str, Any] | None
    """What pipeapi's middleware put under the scope's ``pipeapi`` extension, if any."""


class SentHeaders(BaseModel):
    """The headers a response was sent with, beside it."""

    set_cookie: list[str]


class BarrierOutcome(BaseModel):
    """How a barrier ended for one of its parties."""

    filled: bool
    """Whether every party arrived before the deadline."""
    arrived: int
    """How many parties had arrived when it ended."""


def create_router() -> APIRouter:
    """
    Create the request routes, with barriers of their own.

    Returns:
        The router.
    """
    router = APIRouter(generate_unique_id_function=require_operation_id)
    barriers: dict[str, _Barrier] = {}

    async def seen(request: Request) -> Seen:
        """
        Report what the app saw of the request, under any path below `/seen`.

        Returns:
            What the app saw.
        """
        scope = request.scope
        raw_path: bytes | None = scope.get("raw_path")
        extensions: dict[str, Any] = scope.get("extensions") or {}
        client = request.client
        return Seen(
            pid=os.getpid(),
            method=request.method,
            path=request.url.path,
            raw_path=None if raw_path is None else raw_path.decode("latin-1"),
            query=scope["query_string"].decode("latin-1"),
            http_version=scope["http_version"],
            scheme=request.url.scheme,
            headers=[
                (name.decode("latin-1"), value.decode("latin-1"))
                for name, value in scope["headers"]
            ],
            body=base64.b64encode(await request.body()).decode("ascii"),
            client=None if client is None else (client.host, client.port),
            server=scope.get("server"),
            pipeapi=extensions.get("pipeapi"),
        )

    # One route per method, since a route that names several has one operation ID for
    # them all. Out of the schema: a generated client has no use for a mirror.
    for method in SEEN_METHODS:
        for path in ("/seen", "/seen/{rest:path}"):
            router.add_api_route(path, seen, methods=[method], include_in_schema=False)

    @router.post("/echo", operation_id="echo")
    async def echo(request: Request) -> StreamingResponse:
        """
        Send the request's body back, streamed in the chunks it arrived in.

        The body is read whole first, so the response's stream never competes with the
        request's for the connection.

        Returns:
            The body, with the request's content type.
        """
        chunks = [chunk async for chunk in request.stream() if chunk]

        async def replay() -> AsyncIterator[bytes]:
            for chunk in chunks:
                yield chunk

        return StreamingResponse(
            replay(),
            media_type=request.headers.get("content-type", "application/octet-stream"),
        )

    @router.get("/headers", operation_id="headers")
    async def headers(response: Response) -> SentHeaders:
        """
        Answer with two `Set-Cookie` headers, which a client must keep apart.

        Returns:
            The values sent.
        """
        for cookie in SET_COOKIES:
            response.headers.append("set-cookie", cookie)
        return SentHeaders(set_cookie=list(SET_COOKIES))

    async def status(code: Annotated[int, Path(ge=200, le=599)]) -> Response:
        """
        Answer with the status asked for, as the app itself would.

        A 401 carries a `WWW-Authenticate` challenge, as HTTP requires, and no pipeapi
        marker. 204, 205 and 304 have no body; any other status has a JSON one.

        Returns:
            The response.
        """
        headers = {"www-authenticate": "Bearer"} if code == 401 else None
        if code in _BODILESS_STATUSES:
            return Response(status_code=code, headers=headers)
        return JSONResponse({"status": code}, status_code=code, headers=headers)

    for method in ("GET", "POST"):
        router.add_api_route(
            "/status/{code}",
            status,
            methods=[method],
            operation_id=f"{method.lower()}_status",
        )

    @router.get("/barrier/{name}", operation_id="barrier")
    async def barrier(
        name: str, parties: Annotated[int, Query(ge=1)]
    ) -> BarrierOutcome:
        """
        Hold the request until `parties` requests wait at the barrier of this name.

        The first party's count holds for the barrier. Each party then answers at
        once, so requests that all answer `filled` were in flight together. A barrier
        that does not fill by its deadline answers each of its parties with `filled`
        false.

        Returns:
            How the barrier ended.
        """
        current = barriers.get(name)
        if current is None:
            current = barriers[name] = _Barrier(parties)
        current.arrived += 1
        if current.arrived == current.parties:
            del barriers[name]
            current.filled.set()
        try:
            await asyncio.wait_for(current.filled.wait(), BARRIER_DEADLINE_SECONDS)
        except asyncio.TimeoutError:
            arrived = current.arrived
            current.arrived -= 1
            if current.arrived == 0 and barriers.get(name) is current:
                del barriers[name]
            return BarrierOutcome(filled=False, arrived=arrived)
        return BarrierOutcome(filled=True, arrived=current.parties)

    return router


_BODILESS_STATUSES: Final = frozenset({204, 205, 304})


class _Barrier:
    def __init__(self, parties: int) -> None:
        self.parties = parties
        self.arrived = 0
        self.filled = asyncio.Event()
