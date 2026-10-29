import json
from pathlib import Path
from typing import Any

Observation = dict[str, Any]


def read_observations(log: Path) -> list[Observation]:
    """
    Read every complete observation in the log.

    Args:
        log: The observation log.

    Returns:
        The observations, in the order they were written: none for a log not yet
        written.
    """
    if not log.exists():
        return []
    *lines, _unfinished = log.read_bytes().decode().split("\n")
    return [json.loads(line) for line in lines]
