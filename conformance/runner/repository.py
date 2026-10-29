import subprocess
from pathlib import Path
from typing import Final

REPOSITORY: Final = Path(__file__).resolve().parents[2]

# Git lists the repository's files in well under this; a hang guard.
GIT_TIMEOUT_SECONDS: Final = 60


def files_named(name: str) -> list[Path]:
    """
    Find the repository's files of a name, wherever they sit.

    They are the files Git tracks, or would track once added, so a file Git ignores,
    such as one in a dependency's directory, is never found.

    Args:
        name: The file name.

    Returns:
        Their paths, sorted.

    Raises:
        subprocess.SubprocessError: Git failed, or took longer than its hang guard.
    """
    listed = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            f"*{name}",
        ],
        cwd=REPOSITORY,
        capture_output=True,
        encoding="utf-8",
        timeout=GIT_TIMEOUT_SECONDS,
        check=True,
    ).stdout
    paths = {REPOSITORY / each for each in listed.split("\0") if each}
    return sorted(path for path in paths if path.name == name and path.is_file())
