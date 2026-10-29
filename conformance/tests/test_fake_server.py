import errno
import socket
import sys
import tempfile
from pathlib import Path
from typing import Final

import httpx2
import pytest

from runner.deadlines import Deadline
from runner.fake_server import (
    FakeScript,
    FakeServer,
    FakeServerFailed,
    HelloScript,
    LeaseScript,
    Line,
    Rejection,
    TcpListener,
    UnixListener,
    UnsupportedListener,
)
from runner.proofs import enrollment_proof, random_b64u_32
from runner.raw_client import RawClient

# The fake answers a socket at once; a hang guard.
SOCKET_GUARD_SECONDS: Final = 10.0
NO_AF_UNIX: Final = "Python on Windows has no AF_UNIX, so no Unix domain socket"


def test_the_fake_records_the_hello_and_the_lease_request_as_sent() -> None:
    token = random_b64u_32()
    repeated = (("X-Repeated", "a"), ("X-Repeated", "b"))
    with FakeServer(token) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello(headers=repeated)
        with client.lease(hello, token) as stream:
            stream.read_event()
            lease = fake.wait_for_lease(lambda each: each.all_sent, "the session")
    assert hello.body is not None
    [received] = fake.requests("hello")
    assert received.method == "GET"
    assert received.target == "/__pipeapi/ready"
    assert received.header("host") == "pipeapi.localhost"
    assert received.header("X-PipeAPI-Nonce") == hello.nonce
    assert received.header("Origin") is None
    assert [line for line in received.headers if line[0] == "X-Repeated"] == list(
        repeated
    )
    [leased] = fake.requests("lease")
    challenge = hello.body["challenge"]
    enrollment = f"{challenge}.{enrollment_proof(token, challenge)}"
    assert leased.target == "/__pipeapi/lease"
    assert leased.header("X-PipeAPI-Protocol") == "1"
    assert leased.header("X-PipeAPI-Enrollment") == enrollment
    assert lease.request == leased
    assert lease.enrollment == enrollment
    assert fake.requests() == (received, leased)


def test_the_fake_records_no_lease_request_when_none_comes() -> None:
    with FakeServer(random_b64u_32()) as fake, RawClient(fake.endpoint) as client:
        client.hello()
        fake.wait_for_request("hello")
    assert fake.requests("lease") == ()
    assert fake.leases() == ()


def test_a_lease_line_waits_for_its_cue() -> None:
    token = random_b64u_32()
    lines = (Line.heartbeat(), Line.heartbeat(cue="second"))
    script = FakeScript(lease=LeaseScript(lines=lines))
    with FakeServer(token, script) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello()
        with client.lease(hello, token) as stream:
            stream.read_event()
            assert stream.read_event() == {"type": "heartbeat"}
            lease = fake.wait_for_lease(
                lambda each: len(each.lines_sent) == 2, "two lines"
            )
            assert not lease.all_sent
            fake.cue("second")
            assert stream.read_event() == {"type": "heartbeat"}
            fake.wait_for_lease(lambda each: each.all_sent, "every line")


def test_a_client_that_closes_its_lease_closes_the_fakes_stream() -> None:
    token = random_b64u_32()
    with FakeServer(token) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello()
        with client.lease(hello, token) as stream:
            stream.read_event()
            assert fake.wait_for_lease(lambda each: each.all_sent, "the session").open
        fake.wait_for_lease(lambda each: not each.open, "the stream to close")


def test_stopping_the_fake_ends_a_held_lease_stream() -> None:
    token = random_b64u_32()
    with FakeServer(token) as fake, RawClient(fake.endpoint) as client:
        hello = client.hello()
        with client.lease(hello, token) as stream:
            assert stream.read_event() is not None
            fake.stop()
            assert stream.read_event() is None
            assert stream.end is not None
            assert not stream.end.complete


def test_the_fake_refuses_a_hello_without_a_well_formed_nonce() -> None:
    with FakeServer(random_b64u_32()) as fake, RawClient(fake.endpoint) as client:
        padded = client.hello(nonce=random_b64u_32() + "=")
        missing = client.request("hello")
    for refused in (padded.response, missing):
        assert refused.status == 400
        assert refused.header("X-PipeAPI-Rejected") == "invalid_nonce"


@pytest.mark.parametrize(
    ("method", "path", "marker"),
    [
        ("GET", "/__pipeapi/unknown", "unknown_route"),
        ("POST", "/__pipeapi/ready", "unknown_route"),
        ("GET", "/items", None),
    ],
)
def test_the_fake_answers_any_other_request_as_one_to_an_unknown_route(
    method: str, path: str, marker: str | None
) -> None:
    with (
        FakeServer(random_b64u_32()) as fake,
        httpx2.Client(
            base_url=fake.endpoint.replace("tcp://", "http://"),
            timeout=SOCKET_GUARD_SECONDS,
            trust_env=False,
        ) as client,
    ):
        response = client.request(method, path)
    assert response.status_code == 404
    assert response.headers.get("X-PipeAPI-Rejected") == marker
    [received] = fake.requests()
    assert received.operation is None


def test_the_fake_answers_a_request_that_isnt_http_with_400_and_records_it() -> None:
    with FakeServer(random_b64u_32()) as fake:
        host, port = fake.endpoint.removeprefix("tcp://").rsplit(":", 1)
        with socket.create_connection((host, int(port)), SOCKET_GUARD_SECONDS) as raw:
            raw.sendall(b"NOT HTTP AT ALL\r\n\r\n")
            answer = raw.recv(4096)
    assert answer.startswith(b"HTTP/1.1 400 ")
    [malformed] = fake.malformed_requests()
    assert malformed.connection == 1
    assert fake.requests() == ()


def test_the_fake_and_the_raw_client_meet_over_ipv6_loopback() -> None:
    try:
        with socket.create_server(("::1", 0), family=socket.AF_INET6):
            pass
    except OSError:
        pytest.skip("this host has no IPv6 loopback address")
    token = random_b64u_32()
    with (
        FakeServer(token, listener=TcpListener("::1")) as fake,
        RawClient(fake.endpoint) as client,
    ):
        hello = client.hello()
    assert fake.endpoint.startswith("tcp://[::1]:")
    assert hello.proof_verifies(token)


@pytest.mark.skipif(sys.platform == "win32", reason=NO_AF_UNIX)
def test_the_fake_and_the_raw_client_meet_over_a_unix_domain_socket() -> None:
    token = random_b64u_32()
    # A short directory, since a socket's path is limited to about 100 bytes.
    with tempfile.TemporaryDirectory(prefix="pipeapi", dir="/tmp") as directory:
        path = Path(directory) / "s.sock"
        with (
            FakeServer(token, listener=UnixListener(path)) as fake,
            RawClient(fake.endpoint) as client,
        ):
            hello = client.hello()
            with client.lease(hello, token) as stream:
                assert stream.read_event() is not None
        assert fake.endpoint == f"unix://{path}"
        assert hello.proof_verifies(token)
        assert not path.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="POSIX has AF_UNIX")
def test_the_fake_refuses_a_unix_domain_socket_on_windows(tmp_path: Path) -> None:
    listener = UnixListener(tmp_path / "s.sock")
    with (
        pytest.raises(UnsupportedListener),
        FakeServer(random_b64u_32(), None, listener),
    ):
        pass


def test_the_fake_fails_to_start_on_a_port_another_listener_holds() -> None:
    with socket.create_server(("127.0.0.1", 0)) as taken:
        port: int = taken.getsockname()[1]
        fake = FakeServer(random_b64u_32(), listener=TcpListener(port=port))
        in_use = pytest.raises(
            OSError, check=lambda error: error.errno == errno.EADDRINUSE
        )
        with in_use, fake:
            pass


def test_a_fake_that_doesnt_listen_in_time_is_the_runners_fault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(_self: FakeServer) -> None:
        return None

    monkeypatch.setattr(FakeServer, "_listening", never)
    with (
        pytest.raises(FakeServerFailed, match="didn't listen"),
        FakeServer(random_b64u_32(), deadline=Deadline.after(0, "the test")),
    ):
        pass


def test_a_rejection_of_an_unknown_code_needs_a_status() -> None:
    with pytest.raises(ValueError, match="give a status"):
        Rejection("future_refusal")


def test_a_scripted_mistake_that_changes_nothing_fails_as_the_fake_is_made() -> None:
    script = FakeScript(hello=HelloScript(mistake="TrimmedTokenKey"))
    with pytest.raises(ValueError, match="changes nothing"):
        FakeServer(random_b64u_32(), script)
