import builtins
import subprocess
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from reference_app.routers import process
from reference_app.routers.process import output_line
from tests.support.server import Server, run_server
from tests.support.targets import PROBE_VALUE, PROBE_VARIABLE, Target

UNSET_VARIABLE = "REFERENCE_APP_TEST_UNSET"


def test_the_probe_reports_only_the_variables_asked_for(target: Target) -> None:
    report = target.client.post(
        "/environment",
        json={"names": [PROBE_VARIABLE, UNSET_VARIABLE], "containing": [PROBE_VALUE]},
    ).json()
    assert report == {
        "variables": {PROBE_VARIABLE: PROBE_VALUE, UNSET_VARIABLE: None},
        "containing": {PROBE_VALUE: [PROBE_VARIABLE]},
    }


def test_the_probe_refuses_to_look_for_empty_text(target: Target) -> None:
    response = target.client.post("/environment", json={"containing": [""]})
    assert response.status_code == 422


def test_input_gets_eof_from_a_null_stdin(under_uvicorn: Target) -> None:
    assert under_uvicorn.client.post("/input").json() == {
        "outcome": "eof",
        "line": None,
        "error": None,
    }


def test_input_reads_a_line_from_a_piped_stdin(tmp_path: Path) -> None:
    with run_server(tmp_path, stdin=subprocess.PIPE) as server:
        server.wait_until_serving()
        assert server.process.stdin is not None
        server.process.stdin.write(b"from the pipe\n")
        server.process.stdin.flush()
        with server.client() as client:
            outcome = client.post("/input").json()
    assert (outcome["outcome"], outcome["line"]) == ("line", "from the pipe")


def test_input_that_fails_reports_why(
    in_process: Target, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_prompt: object = "") -> str:
        raise OSError("stdin is gone")

    monkeypatch.setattr(builtins, "input", fail)
    outcome = in_process.client.post("/input").json()
    assert (outcome["outcome"], outcome["error"]) == ("failed", "stdin is gone")


def test_input_still_waiting_at_the_deadline_is_reported_blocked(
    in_process: Target, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()

    def never_answers(_prompt: object = "") -> str:
        release.wait()
        return "too late"

    monkeypatch.setattr(builtins, "input", never_answers)
    monkeypatch.setattr(process, "INPUT_DEADLINE_SECONDS", 0)
    try:
        assert in_process.client.post("/input").json()["outcome"] == "blocked"
    finally:
        release.set()


def test_output_writes_numbered_lines_to_the_stream_asked_for(
    in_process: Target, capsys: pytest.CaptureFixture[str]
) -> None:
    response = in_process.client.post(
        "/output", json={"stream": "stderr", "lines": 3, "width": 30, "tag": "sink"}
    )
    assert response.json() == {"lines": 3}
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [output_line("sink", i, 30) for i in range(3)]
    assert captured.out == ""


def test_plentiful_output_reaches_the_servers_stdout(server: Server) -> None:
    lines = [output_line("plenty", index, 100) for index in range(2000)]
    with server.client() as client:
        response = client.post(
            "/output",
            json={
                "stream": "stdout",
                "lines": len(lines),
                "width": 100,
                "tag": "plenty",
            },
        )
    assert response.json() == {"lines": len(lines)}
    written = server.stdout.read_text().splitlines()
    start = written.index(lines[0])
    assert written[start : start + len(lines)] == lines


def test_a_line_exactly_as_wide_as_its_prefix_is_written_unpadded(
    in_process: Target, capsys: pytest.CaptureFixture[str]
) -> None:
    tag = "A" * 16
    width = len(output_line(tag, 0, 0))
    response = in_process.client.post(
        "/output", json={"stream": "stdout", "lines": 1, "width": width, "tag": tag}
    )
    assert response.json() == {"lines": 1}
    assert capsys.readouterr().out.splitlines() == [f"{tag} 00000000 "]


def test_a_line_narrower_than_its_prefix_is_refused(target: Target) -> None:
    tag = "A" * 16
    response = target.client.post(
        "/output",
        json={
            "stream": "stdout",
            "lines": 1,
            "width": len(output_line(tag, 0, 0)) - 1,
            "tag": tag,
        },
    )
    assert response.status_code == 422


def test_output_past_its_bound_is_refused(target: Target) -> None:
    response = target.client.post(
        "/output",
        json={"stream": "stdout", "lines": process.MAX_OUTPUT_CHARACTERS, "width": 24},
    )
    assert response.status_code == 422


@pytest.fixture
def stopped(tmp_path: Path) -> Iterator[Server]:
    with run_server(tmp_path) as server:
        server.wait_until_serving()
        yield server


def test_the_log_outlives_a_backend_that_stops(stopped: Server) -> None:
    with stopped.client() as client:
        pid = client.get("/seen").json()["pid"]
    stopped.stop()
    # The readiness check's request, then the test's.
    assert [(o["event"], o["pid"]) for o in stopped.observations()] == [
        ("startup", pid),
        ("request", pid),
        ("request", pid),
        ("shutdown", pid),
    ]


def test_the_log_outlives_a_backend_killed_hard(stopped: Server) -> None:
    with stopped.client() as client:
        pid = client.get("/seen").json()["pid"]
    stopped.kill()
    assert [(o["event"], o["pid"]) for o in stopped.observations()] == [
        ("startup", pid),
        ("request", pid),
        ("request", pid),
    ]
