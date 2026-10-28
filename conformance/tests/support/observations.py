import json
from pathlib import Path
from typing import Any

Observation = dict[str, Any]


def read_observations(log: Path) -> list[Observation]:
    """Read every complete observation in the log, in the order they were written."""
    if not log.exists():
        return []
    *lines, _unfinished = log.read_bytes().decode().split("\n")
    return [json.loads(line) for line in lines]
