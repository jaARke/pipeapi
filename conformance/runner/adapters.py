import shutil
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from runner.cases import EXPECTED_FAILURES_FILE_NAME, InvalidData, check_schema
from runner.repository import REPOSITORY, files_named
from runner.schemas import read_document

ADAPTER_PROTOCOL: Final = REPOSITORY / "conformance" / "adapter-protocol"
MANIFEST_SCHEMA: Final = ADAPTER_PROTOCOL / "manifest.schema.json"
# The name of an adapter's manifest, in the directory that holds the adapter.
MANIFEST_FILE_NAME: Final = "adapter.yaml"

SCRIPTS: Final = Path(sysconfig.get_path("scripts"))
"""
The scripts directory of the runner's own environment, which ``uv run`` puts first on
PATH. The runner looks there first for a manifest's program, and puts it first on an
adapter's PATH, so a run started another way, such as by an editor's test explorer,
runs the programs a run under ``uv run`` does.
"""


class UnknownConnector(Exception):
    """No adapter manifest names the connector a run asked for."""


class ProgramNotFound(Exception):
    """The program an adapter's manifest names isn't there."""


@dataclass(frozen=True)
class AdapterManifest:
    """How the runner starts one connector's adapter, read from its manifest."""

    path: Path
    """The manifest's file."""
    connector: str
    command: tuple[str, ...]
    """The program, as the manifest names it, and its arguments."""
    directory: Path
    """The adapter's working directory."""

    @property
    def expected_failures(self) -> Path:
        """The file of the connector's expected failures, which may not exist."""
        return self.path.parent / EXPECTED_FAILURES_FILE_NAME

    def resolved_command(self) -> list[str]:
        """
        Find the program the manifest names, as the OS would run it.

        A program named with a slash is a path from the manifest's directory, and any
        other is looked up in :data:`SCRIPTS`, then on PATH, with Windows' executable
        extensions either way. The runner starts the path found, so the OS searches
        no other directory first, such as the runner's own interpreter's.

        Returns:
            The program's path and the arguments.

        Raises:
            ProgramNotFound: There's no such program.
        """
        program, *arguments = self.command
        if "/" in program:
            found = shutil.which(str(self.path.parent / program))
        else:
            found = shutil.which(program, path=str(SCRIPTS)) or shutil.which(program)
        if found is None:
            where = self.path.relative_to(REPOSITORY).as_posix()
            message = f"{where} names {program}, which isn't there or isn't executable"
            raise ProgramNotFound(message)
        return [found, *arguments]


def load_manifest(path: Path) -> AdapterManifest:
    """
    Read an adapter's manifest, checked against its schema.

    Args:
        path: The manifest's file.

    Returns:
        The manifest.

    Raises:
        yaml.YAMLError: The file doesn't parse, or a mapping holds a key twice.
        InvalidData: The file doesn't meet its schema.
    """
    data: Any = read_document(path)
    check_schema(data, path, MANIFEST_SCHEMA)
    directory = (path.parent / data.get("directory", ".")).resolve()
    return AdapterManifest(path, data["connector"], tuple(data["command"]), directory)


def manifests() -> list[AdapterManifest]:
    """
    Read every adapter manifest the repository holds.

    Returns:
        The manifests, by their paths.

    Raises:
        InvalidData: A manifest doesn't meet its schema, or two name one connector.
    """
    found = [load_manifest(path) for path in files_named(MANIFEST_FILE_NAME)]
    seen: dict[str, Path] = {}
    for manifest in found:
        if manifest.connector in seen:
            first = seen[manifest.connector].relative_to(REPOSITORY).as_posix()
            second = manifest.path.relative_to(REPOSITORY).as_posix()
            message = (
                f"{first} and {second} both name the connector {manifest.connector}"
            )
            raise InvalidData(message)
        seen[manifest.connector] = manifest.path
    return found


def manifest_of(connector: str) -> AdapterManifest:
    """
    Find the manifest of a connector's adapter.

    Args:
        connector: The connector's name.

    Returns:
        Its manifest.

    Raises:
        UnknownConnector: No manifest names it, with the names they give.
    """
    every = manifests()
    for manifest in every:
        if manifest.connector == connector:
            return manifest
    known = ", ".join(sorted(manifest.connector for manifest in every)) or "none"
    message = (
        f"no {MANIFEST_FILE_NAME} names the connector {connector}; "
        f"the manifests name: {known}"
    )
    raise UnknownConnector(message)
