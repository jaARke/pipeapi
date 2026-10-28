from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from reference_app.app import create_app
from reference_app.environment import Settings
from tests.support.server import Server, run_server
from tests.support.targets import PROBE_VALUE, PROBE_VARIABLE, Target


@pytest.fixture(scope="session")
def server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Server]:
    """The app under uvicorn, which every test of a route under uvicorn shares."""
    with run_server(
        tmp_path_factory.mktemp("server"),
        environment={PROBE_VARIABLE: PROBE_VALUE},
    ) as running:
        running.wait_until_serving()
        yield running


@pytest.fixture
def log(tmp_path: Path) -> Path:
    """The observation log of the app in the test's own process."""
    return tmp_path / "observations.jsonl"


@pytest.fixture
def test_client(log: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Starlette's test client of an app in the test's own process."""
    monkeypatch.setenv(PROBE_VARIABLE, PROBE_VALUE)
    with TestClient(create_app(Settings(log=log))) as client:
        yield client


@pytest.fixture
def in_process(test_client: TestClient, log: Path) -> Target:
    """The app in the test's own process."""
    return Target(test_client, log, None)


@pytest.fixture
def under_uvicorn(server: Server) -> Iterator[Target]:
    """The shared app under uvicorn, over loopback."""
    with server.client() as client:
        yield Target(client, server.log, server)


@pytest.fixture(params=["in_process", "under_uvicorn"])
def target(request: pytest.FixtureRequest) -> Target:
    """Each way of reaching the app, so a route behaves alike in process and served."""
    reached: Target = request.getfixturevalue(request.param)
    return reached
