import base64
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from reference_app.routers import requests
from tests.support.targets import Target


def test_the_path_and_query_arrive_intact(target: Target) -> None:
    seen = target.client.get("/seen/a%2Fb/c%20d?x=1&x=2&y=%20z").json()
    assert (seen["method"], seen["path"], seen["raw_path"], seen["query"]) == (
        "GET",
        "/seen/a/b/c d",
        "/seen/a%2Fb/c%20d",
        "x=1&x=2&y=%20z",
    )


def test_the_seen_route_answers_every_method_it_names(target: Target) -> None:
    for method in requests.SEEN_METHODS:
        assert target.client.request(method, "/seen").json()["method"] == method


def test_repeated_request_headers_arrive_in_order(target: Target) -> None:
    seen = target.client.get(
        "/seen", headers=[("x-repeated", "one"), ("x-repeated", "two")]
    ).json()
    repeated = [value for name, value in seen["headers"] if name == "x-repeated"]
    assert repeated == ["one", "two"]


def test_a_whole_body_arrives_with_its_length(target: Target) -> None:
    seen = target.client.post("/seen", json={"whole": True}).json()
    body = base64.b64decode(seen["body"])
    assert body == b'{"whole":true}'
    assert ["content-length", str(len(body))] in seen["headers"]


def test_a_streamed_body_arrives_chunked_and_intact(target: Target) -> None:
    def chunks() -> Iterator[bytes]:
        yield from (b"one ", b"two ", b"three")

    seen = target.client.post("/seen", content=chunks()).json()
    assert base64.b64decode(seen["body"]) == b"one two three"
    assert ["transfer-encoding", "chunked"] in seen["headers"]


def test_the_app_reports_the_process_and_the_client_it_saw(target: Target) -> None:
    seen = target.client.get("/seen").json()
    if target.server is None:
        assert seen["pid"] == os.getpid()
        assert seen["client"] == ["testclient", 50000]
    else:
        assert seen["pid"] != os.getpid()
        assert seen["client"][0] == "127.0.0.1"
    assert seen["pipeapi"] is None


def test_the_echo_streams_back_a_streamed_body(target: Target) -> None:
    def chunks() -> Iterator[bytes]:
        yield from (b"alpha ", b"beta ", b"gamma")

    response = target.client.post(
        "/echo", content=chunks(), headers={"content-type": "text/plain"}
    )
    assert response.content == b"alpha beta gamma"
    assert response.headers["content-type"].startswith("text/plain")
    if target.server is not None:
        assert response.headers["transfer-encoding"] == "chunked"


def test_repeated_set_cookie_headers_are_each_kept(target: Target) -> None:
    response = target.client.get("/headers")
    assert response.headers.get_list("set-cookie") == response.json()["set_cookie"]
    assert len(response.json()["set_cookie"]) == 2


def test_an_app_401_carries_its_challenge(target: Target) -> None:
    response = target.client.get("/status/401")
    assert (response.status_code, response.json()) == (401, {"status": 401})
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("code", [204, 304])
def test_a_bodiless_status_has_no_body(target: Target, code: int) -> None:
    response = target.client.get(f"/status/{code}")
    assert (response.status_code, response.content) == (code, b"")


def test_a_post_gets_the_status_asked_for(target: Target) -> None:
    assert target.client.post("/status/503").status_code == 503


def test_a_status_outside_the_final_range_is_refused(target: Target) -> None:
    assert target.client.get("/status/101").status_code == 422


def test_a_barrier_answers_once_its_parties_are_in_flight_together(
    target: Target,
) -> None:
    assert (
        _arrive_together(target, "together", 2) == [{"filled": True, "arrived": 2}] * 2
    )


def test_a_barrier_that_does_not_fill_by_its_deadline_says_so(
    in_process: Target, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(requests, "BARRIER_DEADLINE_SECONDS", 0)
    outcome = in_process.client.get("/barrier/alone", params={"parties": 2}).json()
    assert outcome == {"filled": False, "arrived": 1}
    monkeypatch.undo()
    # The party that timed out left, so the barrier of that name starts over.
    assert (
        _arrive_together(in_process, "alone", 2) == [{"filled": True, "arrived": 2}] * 2
    )


def test_every_request_that_reaches_the_app_is_recorded(target: Target) -> None:
    before = len(target.observations())
    seen = target.client.get("/seen/recorded", params={"probe": "requests"}).json()
    assert target.observations()[before:] == [
        {
            "event": "request",
            "pid": seen["pid"],
            "type": "http",
            "method": "GET",
            "path": "/seen/recorded",
            "query": "probe=requests",
        }
    ]


def _arrive_together(target: Target, name: str, parties: int) -> list[object]:
    def arrive() -> object:
        path = f"/barrier/{name}"
        return target.client.get(path, params={"parties": parties}).json()

    with ThreadPoolExecutor(max_workers=parties) as pool:
        arrivals = [pool.submit(arrive) for _party in range(parties)]
        return [arrival.result() for arrival in arrivals]
