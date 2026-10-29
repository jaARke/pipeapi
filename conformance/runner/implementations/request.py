import base64
import json
import secrets

from reference_app.routers.items import Item
from reference_app.routers.requests import SET_COOKIES, BarrierOutcome, Seen
from runner.adapter_session import AdapterSession, Response
from runner.case_run import CaseRun
from runner.contract import PROTOCOL_VERSION, load_contract
from runner.registry import implements

RAW_PATH = "/seen/a%2Fb/c"
RAW_QUERY = "x=1&x=2&y=%20z"
TAGS = ("kitchen", "blue")
CONCURRENT_REQUESTS = 4


def header_names(seen: Seen) -> list[str]:
    """
    List the header names a request arrived with.

    Args:
        seen: What the app saw.

    Returns:
        Each name, lowercased, in the order it arrived.
    """
    return [name.lower() for name, _ in seen.headers]


def header_values(seen: Seen, name: str) -> list[str]:
    """
    List one header's values as a request arrived with them.

    Args:
        seen: What the app saw.
        name: The header's name, lowercased.

    Returns:
        Its values, in order.
    """
    return [value for each, value in seen.headers if each.lower() == name]


def check_whole(seen: Seen, what: str) -> bytes:
    """
    Check that a body went out whole, with its length and without chunks.

    Args:
        seen: What the app saw.
        what: The body, for the failure.

    Returns:
        The body.
    """
    body = base64.b64decode(seen.body)
    assert header_values(seen, "content-length") == [str(len(body))], what
    assert "transfer-encoding" not in header_names(seen), what
    return body


def connected(run: CaseRun) -> tuple[AdapterSession, int]:
    """
    Start the app and a client, and connect the client to it.

    Args:
        run: The permutation's context.

    Returns:
        The client, and its Backend.
    """
    app = run.app()
    client = run.client()
    return client, run.connect(client, app)


@implements("request.query-string")
def path_and_query_arrive_intact(run: CaseRun) -> None:
    """Check that a path and query arrive byte for byte."""
    client, backend = connected(run)
    target = f"{RAW_PATH}?{RAW_QUERY}"
    seen = client.request(backend, "GET", target, via=run.via).answer(Seen)
    assert (seen.raw_path, seen.query) == (RAW_PATH, RAW_QUERY)


@implements("request.whole-body")
def a_whole_body_goes_out_with_its_length(run: CaseRun) -> None:
    """Check that JSON and form bodies go out with their lengths and arrive whole."""
    client, backend = connected(run)
    document = json.dumps({"name": "cup", "tags": list(TAGS)})
    seen = client.request(
        backend,
        "POST",
        "/seen",
        via=run.via,
        headers=[("Content-Type", "application/json")],
        body={"text": document},
    ).answer(Seen)
    assert check_whole(seen, "JSON") == document.encode()
    fields = [["name", "cup"], *(["tags", tag] for tag in TAGS)]
    for form in ("form", "multipart"):
        seen = client.request(
            backend, "POST", "/seen", via=run.via, body={form: fields}
        ).answer(Seen)
        check_whole(seen, form)
        created = client.request(
            backend, "POST", "/items/form", via=run.via, body={form: fields}
        )
        assert created.status == 201, form
        item = created.answer(Item)
        assert (item.name, tuple(item.tags)) == ("cup", TAGS), form


@implements("request.streamed-body")
def a_streamed_body_goes_out_chunked(run: CaseRun) -> None:
    """Check that a body fed in chunks goes out chunked and arrives intact."""
    client, backend = connected(run)
    chunks = [b"first, ", b"\x00\xff second"]
    # The app's mirror shows how the body went out, and its echo what arrived.
    for target in ("/seen", "/echo"):
        request = client.send_request(
            backend,
            "POST",
            target,
            via=run.via,
            headers=[("Content-Type", "application/octet-stream")],
            body={"stream": True},
        )
        for chunk in chunks:
            encoded = base64.b64encode(chunk).decode()
            client.call("body_chunk", request=request, base64=encoded).result()
        client.call("body_end", request=request).result()
        response = client.finish(request)
        if target == "/echo":
            assert response.body == b"".join(chunks)
            continue
        seen = response.answer(Seen)
        assert header_values(seen, "transfer-encoding") == ["chunked"]
        assert "content-length" not in header_names(seen)
        assert base64.b64decode(seen.body) == b"".join(chunks)


@implements("request.multi-value-headers")
def repeated_response_headers_are_kept(run: CaseRun) -> None:
    """Check that both Set-Cookie values come back, in order."""
    client, backend = connected(run)
    response = client.request(backend, "GET", "/headers", via=run.via)
    assert response.values("set-cookie") == list(SET_COOKIES)


@implements("request.no-body")
def a_response_without_a_body_completes(run: CaseRun) -> None:
    """Check that 204, 205 and 304 complete with an empty body."""
    client, backend = connected(run)
    created = client.request(
        backend,
        "POST",
        "/items",
        via=run.via,
        headers=[("Content-Type", "application/json")],
        body={"text": json.dumps({"name": "cup"})},
    ).answer(Item)
    deleted = client.request(backend, "DELETE", f"/items/{created.id}", via=run.via)
    assert (deleted.status, deleted.body) == (204, b"")
    for status in (204, 205, 304):
        response = client.request(backend, "GET", f"/status/{status}", via=run.via)
        assert (response.status, response.body) == (status, b"")


@implements("request.head")
def head_completes_without_a_body(run: CaseRun) -> None:
    """Check that HEAD returns GET's headers and no body."""
    client, backend = connected(run)

    def compared(response: Response) -> list[tuple[str, str]]:
        # The date differs between any two responses.
        return [
            (name.lower(), value)
            for name, value in response.headers
            if name.lower() != "date"
        ]

    get = client.request(backend, "GET", "/items", via=run.via)
    head = client.request(backend, "HEAD", "/items", via=run.via)
    assert (head.status, head.body) == (200, b"")
    assert compared(head) == compared(get)


@implements("request.concurrent")
def requests_run_concurrently(run: CaseRun) -> None:
    """Check that requests sent at once are in flight together."""
    client, backend = connected(run)
    target = f"/barrier/{secrets.token_hex(8)}?parties={CONCURRENT_REQUESTS}"
    requests = [
        client.send_request(backend, "GET", target, via=run.via)
        for _ in range(CONCURRENT_REQUESTS)
    ]
    outcomes = [client.finish(each).answer(BarrierOutcome) for each in requests]
    assert all(outcome.filled for outcome in outcomes), outcomes


@implements("request.status-is-not-error")
def an_http_status_is_never_a_connector_error(run: CaseRun) -> None:
    """Check that 404 and 500 come back as responses."""
    client, backend = connected(run)
    assert client.request(backend, "GET", "/status/404", via=run.via).status == 404
    assert client.request(backend, "POST", "/status/500", via=run.via).status == 500


@implements("request.host-header")
def app_requests_carry_the_fixed_host(run: CaseRun) -> None:
    """Check that the app sees the fixed Host and no Origin."""
    client, backend = connected(run)
    seen = client.request(backend, "GET", "/seen", via=run.via).answer(Seen)
    host = load_contract(PROTOCOL_VERSION).constant("host")
    assert header_values(seen, "host") == [host]
    assert "origin" not in header_names(seen)


@implements("request.authorization-passes")
def authorization_reaches_the_app(run: CaseRun) -> None:
    """Check that an Authorization header reaches the app unchanged."""
    client, backend = connected(run)
    credentials = f"Bearer {secrets.token_urlsafe(16)}"
    seen = client.request(
        backend, "GET", "/seen", via=run.via, headers=[("Authorization", credentials)]
    ).answer(Seen)
    assert header_values(seen, "authorization") == [credentials]
