import json
import os
from typing import Final

import pytest

from runner.contract import ContractViolation
from runner.fake_server import (
    CannedResponse,
    FakeScript,
    FakeServer,
    HelloAnswer,
    HelloScript,
    LeaseScript,
    Line,
    Rejection,
)
from runner.proofs import HELLO_MISTAKES, HelloMistake, random_b64u_32
from runner.raw_client import (
    TRANSPORTS,
    RawClient,
    UnexpectedStatus,
    UnsupportedEndpoint,
)

DOCUMENT: Final = "protocol/v1/openapi.yaml"
HELLO_SCHEMA: Final = "#/components/schemas/hello"
LEASE_EVENT_SCHEMA: Final = "#/components/schemas/lease_event"
JSON_TYPE: Final = ("Content-Type", "application/json")
JSON_LINES_TYPE: Final = ("Content-Type", "application/jsonl")
# An endpoint on each of the connector API's transports, which constructing a client
# doesn't connect to.
ENDPOINTS: Final = {
    "tcp": "tcp://127.0.0.1:9",
    "unix": "unix:///tmp/pipeapi-none.sock",
    "npipe": "npipe:////./pipe/pipeapi-none",
}


def hello_body_without(name: str) -> bytes:
    hello = {
        "protocols": [1],
        "features": [],
        "pid": 1,
        "proof": random_b64u_32(),
        "challenge": random_b64u_32(),
    }
    del hello[name]
    return json.dumps(hello).encode()


def test_the_raw_client_accepts_the_fakes_default_hello_and_its_proof_verifies() -> (
    None
):
    token = random_b64u_32()
    with FakeServer(token) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello()
    assert hello.response.status == 200
    assert hello.body is not None
    assert hello.body["protocols"] == [1]
    assert hello.body["features"] == []
    assert hello.body["pid"] == os.getpid()
    assert hello.proof_verifies(token)
    assert not hello.proof_verifies(random_b64u_32())


@pytest.mark.parametrize("mistake", sorted(HELLO_MISTAKES))
def test_a_proof_computed_with_a_mistake_the_vectors_name_fails_verification(
    mistake: HelloMistake,
) -> None:
    # Trimming changes only a token with spaces around it, and decoding needs a token
    # in b64u(32), as a generated one is.
    token = (
        f" {random_b64u_32()} " if mistake == "TrimmedTokenKey" else random_b64u_32()
    )
    script = FakeScript(hello=HelloScript(pid=4242, mistake=mistake))
    with FakeServer(token, script) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello()
    assert hello.body is not None
    assert hello.body["pid"] == 4242
    assert not hello.proof_verifies(token)


def test_a_hello_with_another_version_and_unknown_fields_still_meets_the_schema() -> (
    None
):
    token = random_b64u_32()
    script = FakeScript(
        hello=HelloScript(
            protocols=(2,),
            features=("future_flag",),
            properties={"future": {"nested": [1]}},
            headers=(("X-PipeAPI-Future", "1"),),
        )
    )
    with FakeServer(token, script) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello()
    assert hello.body is not None
    assert hello.body["protocols"] == [2]
    assert hello.body["features"] == ["future_flag"]
    assert hello.response.value["future"] == {"nested": [1]}
    assert hello.response.header("x-pipeapi-future") == "1"
    assert hello.proof_verifies(token)


def test_a_hello_without_a_proof_fails_the_contract_naming_the_hello_schema() -> None:
    answer = CannedResponse(200, (JSON_TYPE,), hello_body_without("proof"))
    with (
        FakeServer(random_b64u_32(), FakeScript(hello=answer)) as fake,
        RawClient(fake.endpoint) as client,
        pytest.raises(ContractViolation) as raised,
    ):
        client.hello()
    message = str(raised.value)
    assert f"the hello operation's 200 response doesn't meet {DOCUMENT}" in message
    assert f"its body, against {HELLO_SCHEMA}" in message
    assert "$: 'proof' is a required property" in message


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param(
            CannedResponse(200, (JSON_TYPE,), b"{not json"),
            "its body isn't JSON",
            id="not-json",
        ),
        pytest.param(
            CannedResponse(200, (JSON_TYPE,), hello_body_without("challenge")),
            "$: 'challenge' is a required property",
            id="no-challenge",
        ),
        pytest.param(
            HelloScript(properties={"proof": "short"}),
            "$.proof: 'short' does not match",
            id="proof-not-b64u",
        ),
        pytest.param(
            HelloScript(properties={"pid": 2**32}),
            "$.pid: 4294967296 is greater than the maximum of 4294967295",
            id="pid-out-of-range",
        ),
        pytest.param(
            CannedResponse(200, (("Content-Type", "text/plain"),), b"{}"),
            "its Content-Type text/plain isn't in",
            id="not-json-media-type",
        ),
        pytest.param(
            CannedResponse(200, (JSON_TYPE,), b'{"pid": 1, "pid": 2}'),
            "holds the name 'pid' twice",
            id="duplicate-name",
        ),
    ],
)
def test_a_malformed_hello_fails_the_contract(
    answer: HelloAnswer, expected: str
) -> None:
    with (
        FakeServer(random_b64u_32(), FakeScript(hello=answer)) as fake,
        RawClient(fake.endpoint) as client,
        pytest.raises(ContractViolation) as raised,
    ):
        client.hello()
    assert expected in str(raised.value)


@pytest.mark.parametrize(
    ("rejection", "status"),
    [
        (Rejection("invalid_host"), 400),
        (Rejection("origin_forbidden"), 403),
        (Rejection("invalid_nonce"), 400),
        (Rejection("draining"), 503),
        (Rejection("future_refusal", status=400), 400),
    ],
    ids=lambda value: value.code if isinstance(value, Rejection) else str(value),
)
def test_a_rejected_hello_with_its_marker_meets_the_contract_for_its_status(
    rejection: Rejection, status: int
) -> None:
    token = random_b64u_32()
    with (
        FakeServer(token, FakeScript(hello=rejection)) as fake,
        RawClient(fake.endpoint) as client,
    ):
        hello = client.hello()
    assert hello.response.status == status
    assert hello.response.header("X-PipeAPI-Rejected") == rejection.code
    assert hello.response.body == b""
    assert hello.body is None
    with pytest.raises(UnexpectedStatus):
        hello.proof_verifies(token)


@pytest.mark.parametrize("status", [404, 500])
def test_a_hello_another_http_server_answers_fails_the_contract(status: int) -> None:
    answer = CannedResponse(status, (("Content-Type", "text/plain"),), b"Not here")
    with (
        FakeServer(random_b64u_32(), FakeScript(hello=answer)) as fake,
        RawClient(fake.endpoint) as client,
        pytest.raises(ContractViolation) as raised,
    ):
        client.hello()
    assert f"lists no {status} response" in str(raised.value)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param(
            CannedResponse(503),
            "the header X-PipeAPI-Rejected is missing",
            id="no-marker",
        ),
        pytest.param(
            CannedResponse(503, (("X-PipeAPI-Rejected", "Draining"),)),
            "the header X-PipeAPI-Rejected, against "
            "#/components/headers/X-PipeAPI-Rejected/schema",
            id="malformed-marker",
        ),
        pytest.param(
            CannedResponse(503, (("X-PipeAPI-Rejected", "draining"),), b"busy"),
            "its body holds 4 bytes",
            id="a-body",
        ),
    ],
)
def test_a_refusal_that_isnt_pipeapis_form_fails_the_contract(
    answer: CannedResponse, expected: str
) -> None:
    with (
        FakeServer(random_b64u_32(), FakeScript(hello=answer)) as fake,
        RawClient(fake.endpoint) as client,
        pytest.raises(ContractViolation) as raised,
    ):
        client.hello()
    assert expected in str(raised.value)


def test_each_lease_event_meets_the_item_schema_as_it_is_read() -> None:
    token = random_b64u_32()
    lines = (
        Line.heartbeat(),
        Line.event({"type": "future_event", "detail": 1}),
        Line.heartbeat(),
        Line.end("future_reason"),
    )
    lease = LeaseScript(session_properties={"future": True}, lines=lines)
    with (
        FakeServer(token, FakeScript(lease=lease)) as fake,
        RawClient(fake.endpoint) as client,
    ):
        hello = client.hello()
        with client.lease(hello, token) as stream:
            events = [stream.read_event() for _ in range(5)]
    assert stream.status == 200
    session = events[0]
    assert session is not None
    assert session["type"] == "session"
    assert session["client_id"]
    assert session["lease_ttl"] is None
    assert session["future"] is True
    assert events[1:] == [
        {"type": "heartbeat"},
        {"type": "future_event", "detail": 1},
        {"type": "heartbeat"},
        {"type": "end", "reason": "future_reason"},
    ]


@pytest.mark.parametrize(
    ("lease", "line", "expected"),
    [
        pytest.param(
            LeaseScript(lines=(Line.event({"type": "end"}),)),
            2,
            "$: 'reason' is a required property",
            id="end-without-reason",
        ),
        pytest.param(
            LeaseScript(lines=(Line.event({"heartbeat": True}),)),
            2,
            "$: 'type' is a required property",
            id="no-type",
        ),
        pytest.param(
            LeaseScript(lines=(Line(b"{not json\n"),)),
            2,
            "it isn't JSON",
            id="not-json",
        ),
        pytest.param(
            LeaseScript(lease_ttl=5),
            1,
            "$.lease_ttl: 5 is less than the minimum of 30",
            id="session-ttl-too-short",
        ),
    ],
)
def test_a_lease_line_that_breaks_the_item_schema_fails_the_contract(
    lease: LeaseScript, line: int, expected: str
) -> None:
    token = random_b64u_32()
    with (
        FakeServer(token, FakeScript(lease=lease)) as fake,
        RawClient(fake.endpoint) as client,
    ):
        hello = client.hello()
        with client.lease(hello, token) as stream:
            for _ in range(line - 1):
                stream.read_event()
            with pytest.raises(ContractViolation) as raised:
                stream.read_event()
    message = str(raised.value)
    assert (
        f"the lease operation's 200 stream's line {line} doesn't meet {DOCUMENT}"
        in message
    )
    assert expected in message
    if "isn't JSON" not in expected:
        assert f"it, against {LEASE_EVENT_SCHEMA}" in message


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        pytest.param(
            LeaseScript(lines=(Line(b'{"type":"heartbeat"}\r\n'),)),
            "it ends in CRLF, where every line ends in LF alone",
            id="crlf",
        ),
        pytest.param(
            CannedResponse(200, (JSON_LINES_TYPE,), b'{"type":"heartbeat"}'),
            "the stream ended within it, with no LF",
            id="no-final-lf",
        ),
    ],
)
def test_a_lease_line_that_doesnt_end_in_lf_alone_fails_the_contract(
    answer: LeaseScript | CannedResponse, expected: str
) -> None:
    token = random_b64u_32()
    with (
        FakeServer(token, FakeScript(lease=answer)) as fake,
        RawClient(fake.endpoint) as client,
    ):
        hello = client.hello()
        with client.lease(hello, token) as stream:
            if isinstance(answer, LeaseScript):
                stream.read_event()
            with pytest.raises(ContractViolation, match=expected):
                stream.read_event()


@pytest.mark.parametrize("transport", sorted(ENDPOINTS))
def test_the_raw_client_reaches_exactly_the_transports_it_declares(
    transport: str,
) -> None:
    if transport in TRANSPORTS:
        RawClient(ENDPOINTS[transport]).close()
    else:
        with pytest.raises(UnsupportedEndpoint, match=f"no {transport}://"):
            RawClient(ENDPOINTS[transport])


def test_a_refused_lease_meets_the_contract_and_has_no_events() -> None:
    token = random_b64u_32()
    script = FakeScript(lease=Rejection("enrollment_failed"))
    with (
        FakeServer(token, script) as fake,
        RawClient(fake.endpoint) as client,
    ):
        hello = client.hello()
        with client.lease(hello, token) as stream:
            assert stream.status == 401
            assert stream.response.header("X-PipeAPI-Rejected") == "enrollment_failed"
            assert (
                stream.response.header("WWW-Authenticate")
                == 'PipeAPI error="enrollment_failed"'
            )
            with pytest.raises(UnexpectedStatus):
                stream.read_event()
