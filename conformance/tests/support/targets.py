from dataclasses import dataclass
from pathlib import Path
from typing import Final

import httpx2

from tests.support.observations import Observation, read_observations
from tests.support.server import Server

# A variable each target's environment holds, which the environment probe reports.
PROBE_VARIABLE: Final = "REFERENCE_APP_TEST_PROBE"
PROBE_VALUE: Final = "probe value for the tests"


@dataclass(frozen=True)
class Target:
    """The reference app as a test reaches it: in process, or under uvicorn."""

    client: httpx2.Client
    log: Path
    server: Server | None
    """The uvicorn process, for a target under uvicorn."""

    def observations(self) -> list[Observation]:
        return read_observations(self.log)
