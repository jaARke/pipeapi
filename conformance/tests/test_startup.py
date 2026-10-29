from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reference_app.app import StartupFailure, create_app
from reference_app.environment import (
    FAIL_STARTUP_VARIABLE,
    FAKE_READY_VARIABLE,
    LOG_VARIABLE,
    Settings,
    read_settings,
)
from runner.observations import read_observations
from runner.uvicorn_server import run_server

# The status uvicorn exits with when the app's lifespan startup fails.
UVICORN_STARTUP_FAILURE = 3

# A line a connector that scans stdout for readiness might take for uvicorn's own.
FAKE_READY_LINE = "INFO:     Application startup complete."


def test_settings_are_read_from_their_variables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(LOG_VARIABLE, str(tmp_path / "log.jsonl"))
    monkeypatch.setenv(FAKE_READY_VARIABLE, "ready")
    monkeypatch.setenv(FAIL_STARTUP_VARIABLE, "")
    assert read_settings() == Settings(
        log=tmp_path / "log.jsonl", fake_ready="ready", fail_startup=None
    )


def test_a_relative_log_path_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_VARIABLE, "relative.jsonl")
    with pytest.raises(ValueError, match=LOG_VARIABLE):
        read_settings()


def test_an_app_without_a_log_records_nothing(tmp_path: Path) -> None:
    with TestClient(create_app(Settings())) as client:
        assert client.get("/items").status_code == 200
    assert list(tmp_path.iterdir()) == []


def test_a_startup_that_fails_on_request_raises_in_process(tmp_path: Path) -> None:
    log = tmp_path / "observations.jsonl"
    app = create_app(Settings(log=log, fail_startup="asked to fail"))
    with pytest.raises(StartupFailure, match="asked to fail"), TestClient(app):
        pass
    assert [o["event"] for o in read_observations(log)] == ["startup_failure"]


def test_a_failed_startup_exits_before_serving_with_its_message_on_stderr(
    tmp_path: Path,
) -> None:
    with run_server(tmp_path, fail_startup="canary startup failure") as server:
        assert server.wait_for_exit() == UVICORN_STARTUP_FAILURE
        tail = server.stderr.read_text().splitlines()[-5:]
        observations = server.observations()
    assert any("canary startup failure" in line for line in tail)
    assert [(o["event"], o.get("message")) for o in observations] == [
        ("startup_failure", "canary startup failure")
    ]


def test_the_fake_ready_line_comes_first_and_the_app_still_serves(
    tmp_path: Path,
) -> None:
    with run_server(tmp_path, fake_ready=FAKE_READY_LINE) as server:
        server.wait_until_serving()
        with server.client() as client:
            assert client.get("/items").status_code == 200
        assert server.stdout.read_text().splitlines()[0] == FAKE_READY_LINE
