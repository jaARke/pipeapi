import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final, Literal, cast

from runner.repository import REPOSITORY, files_named
from runner.schemas import read_document, validator

CASES_DIRECTORY: Final = REPOSITORY / "conformance" / "cases"
CASES_FILE: Final = CASES_DIRECTORY / "cases.yaml"
COMPONENTS_FILE: Final = CASES_DIRECTORY / "components.yaml"
CASES_SCHEMA: Final = CASES_DIRECTORY / "cases.schema.json"
COMPONENTS_SCHEMA: Final = CASES_DIRECTORY / "components.schema.json"
EXPECTED_FAILURES_SCHEMA: Final = CASES_DIRECTORY / "expected-failures.schema.json"
# The name of a connector's expected failures, beside its adapter's manifest, which the
# hook that validates them in .pre-commit-config.yaml matches too.
EXPECTED_FAILURES_FILE_NAME: Final = "expected-failures.yaml"

# The values cases.schema.json allows for each, which a test holds equal.
type Kind = Literal["server", "connector"]
type Backend = Literal["app", "fake"]
# The connector API's transports, which cases.schema.json takes from it.
type Transport = Literal["unix", "npipe", "tcp"]
type Platform = Literal["posix", "windows"]
# The adapter protocol's ways a request goes through, which cases.schema.json takes.
type Via = Literal["untyped", "primitive"]
# How the runner runs a case: against the server through its raw client, through a
# connector's adapter, or through the baseline adapter against the app under uvicorn.
type Run = Literal["server", "connector", "baseline"]

PLATFORM: Final[Platform] = "windows" if sys.platform == "win32" else "posix"
"""The platform the runner runs on."""

TRANSPORTS_OF: Final[Mapping[Platform, tuple[Transport, ...]]] = {
    "posix": ("unix", "tcp"),
    "windows": ("npipe", "tcp"),
}
# The baseline serves the app under plain uvicorn, which it reaches over loopback TCP.
BASELINE_TRANSPORT: Final[Transport] = "tcp"

# The components a case's backends and its run imply, which its needs never list.
SERVER: Final = "server"
FAKE_SERVER: Final = "fake-server"
BASELINE_ADAPTER: Final = "baseline-adapter"
REFERENCE_APP: Final = "reference-app"
LISTENER_OF: Final[Mapping[Transport, str]] = {
    "unix": "listener-unix",
    "npipe": "listener-npipe",
    "tcp": "listener-loopback",
}
IMPLIED_COMPONENTS: Final = frozenset(
    {SERVER, FAKE_SERVER, BASELINE_ADAPTER, REFERENCE_APP, *LISTENER_OF.values()}
)


class InvalidData(Exception):
    """A file of the case list that doesn't parse, or doesn't meet its schema."""


@dataclass(frozen=True)
class Permutation:
    """One place a case runs: a platform, a transport on it, and a way to request."""

    platform: Platform
    transport: Transport | None
    """The transport, or None for a case that runs once, on one the runner picks."""
    via: Via | None = None
    """What its requests go through, or None for a case that doesn't vary by it."""


@dataclass(frozen=True)
class Case:
    """One case, with the defaults cases.schema.json gives the fields it leaves out."""

    id: str
    area: str
    title: str
    expectation: str
    kind: Kind
    backends: frozenset[Backend]
    needs: frozenset[str]
    transports: frozenset[Transport] | None
    """The transports it applies to, or None for every transport its platform has."""
    platforms: frozenset[Platform] | None
    """The platforms it applies to, or None for both."""
    vias: tuple[Via, ...]
    """What its requests go through, once for each, or none if it doesn't vary by it."""
    once: bool
    relies_on: frozenset[str]
    """The capabilities it needs of an adapter, as the adapter protocol names them."""
    baseline: bool
    slow: bool
    covers: tuple[str, ...]

    def permutations(self) -> list[Permutation]:
        """
        List every place the case runs.

        Returns:
            Each permutation, by platform, then by transport, then by what its
            requests go through.
        """
        vias: tuple[Via | None, ...] = self.vias or (None,)
        found: list[Permutation] = []
        for platform, transports in TRANSPORTS_OF.items():
            if self.platforms is not None and platform not in self.platforms:
                continue
            applicable: list[Transport] = [
                transport
                for transport in transports
                if self.transports is None or transport in self.transports
            ]
            if self.once and applicable:
                found += [Permutation(platform, None, via) for via in vias]
            else:
                found += [
                    Permutation(platform, transport, via)
                    for transport in applicable
                    for via in vias
                ]
        return found

    def needs_in(self, run: Run, transport: Transport) -> frozenset[str]:
        """
        Every component the case needs in a run on a transport, its backends' included.

        A case that talks to the app reaches it through pipeapi's server and its
        listener on the transport, except in the baseline run, where plain uvicorn
        serves it. A case that talks to the fake needs the fake server.

        Args:
            run: The run.
            transport: The transport the case runs on.

        Returns:
            The IDs of the components.
        """
        needs = set(self.needs)
        if run == "baseline":
            needs.add(BASELINE_ADAPTER)
        if run == "server":
            needs.add(SERVER)
        if "app" in self.backends:
            needs.add(REFERENCE_APP)
            if run != "baseline":
                needs |= {SERVER, LISTENER_OF[transport]}
        if "fake" in self.backends:
            needs.add(FAKE_SERVER)
        return frozenset(needs)

    def runs(self) -> list[Run]:
        """
        List the runs that run the case.

        Returns:
            The runs.
        """
        if self.kind == "server":
            return ["server"]
        return ["connector", "baseline"] if self.baseline else ["connector"]


@dataclass(frozen=True)
class Area:
    """An area of the case list, which groups its cases."""

    name: str
    title: str
    description: str
    cases: tuple[str, ...]
    """Its cases' IDs, in the file's order."""


@dataclass(frozen=True)
class Invariant:
    """
    A check the runner applies in every case, once the components it needs are built,
    with the defaults cases.schema.json gives the fields it leaves out.
    """

    id: str
    title: str
    expectation: str
    needs: frozenset[str]
    covers: tuple[str, ...]


@dataclass(frozen=True)
class Component:
    """A component that cases need, and whether it's built."""

    id: str
    description: str
    issue: int
    built: bool


@dataclass(frozen=True)
class CaseList:
    """The case list's files, read and checked against their schemas."""

    areas: Mapping[str, Area]
    cases: Mapping[str, Case]
    invariants: Mapping[str, Invariant]
    uncovered: Mapping[str, str]
    components: Mapping[str, Component]


@dataclass(frozen=True)
class ExpectedFailure:
    """The permutations of one case that a connector is known to fail."""

    case: str
    reason: str
    transports: frozenset[Transport] | None
    platforms: frozenset[Platform] | None
    vias: frozenset[Via] | None = None

    def matches(self, permutation: Permutation) -> bool:
        """
        Tell whether the entry covers a permutation of its case.

        Args:
            permutation: The permutation.

        Returns:
            Whether it does.
        """
        if self.platforms is not None and permutation.platform not in self.platforms:
            return False
        if self.vias is not None and permutation.via not in self.vias:
            return False
        if self.transports is None:
            return True
        return permutation.transport in self.transports


def check_schema(data: Any, path: Path, schema: Path) -> None:
    """
    Check a file's data against its schema.

    Args:
        data: The data the file holds.
        path: The file, which the error names.
        schema: The schema's file.

    Raises:
        InvalidData: The data doesn't meet the schema, with each place it fails.
    """
    errors = [
        f"{error.json_path}: {error.message}"
        for error in validator(schema).iter_errors(data)
    ]
    if errors:
        where = path.relative_to(REPOSITORY).as_posix()
        raise InvalidData(f"{where} doesn't meet {schema.name}:\n" + "\n".join(errors))


def load_case_list() -> CaseList:
    """
    Read the case list and the component table, each checked against its schema.

    Returns:
        The case list.

    Raises:
        yaml.YAMLError: A file doesn't parse, or a mapping holds a key twice.
        InvalidData: A file doesn't meet its schema.
    """
    data = read_document(CASES_FILE)
    check_schema(data, CASES_FILE, CASES_SCHEMA)
    table = read_document(COMPONENTS_FILE)
    check_schema(table, COMPONENTS_FILE, COMPONENTS_SCHEMA)
    areas: dict[str, Area] = {}
    cases: dict[str, Case] = {}
    for name, area in data["areas"].items():
        for case_id, definition in area["cases"].items():
            cases[case_id] = case_of(case_id, name, definition)
        areas[name] = Area(
            name, area["title"], area["description"], tuple(area["cases"])
        )
    invariants = {
        invariant_id: invariant_of(invariant_id, invariant)
        for invariant_id, invariant in data["invariants"].items()
    }
    components = {
        component_id: Component(
            component_id, entry["description"], entry["issue"], entry["built"]
        )
        for component_id, entry in table.items()
    }
    return CaseList(areas, cases, invariants, dict(data["uncovered"]), components)


def case_of(case_id: str, area: str, definition: Mapping[str, Any]) -> Case:
    """
    Make a case from its definition, which cases.schema.json has checked.

    A field the definition leaves out takes the default the schema states.

    Args:
        case_id: The case's ID.
        area: The name of its area.
        definition: Its definition.

    Returns:
        The case.
    """
    fields = {**_defaults("case"), **definition}
    return Case(
        id=case_id,
        area=area,
        title=fields["title"],
        expectation=fields["expectation"],
        kind=fields["kind"],
        backends=frozenset(fields["backends"]),
        needs=frozenset(fields["needs"]),
        transports=_optional_set(fields.get("transports")),
        platforms=_optional_set(fields.get("platforms")),
        vias=tuple(fields.get("vias", [])),
        once=fields["once"],
        relies_on=frozenset(fields.get("relies_on", [])),
        baseline=fields["baseline"],
        slow=fields["slow"],
        covers=tuple(fields["covers"]),
    )


def invariant_of(invariant_id: str, definition: Mapping[str, Any]) -> Invariant:
    """
    Make an invariant from its definition, which cases.schema.json has checked.

    A field the definition leaves out takes the default the schema states.

    Args:
        invariant_id: The invariant's ID.
        definition: Its definition.

    Returns:
        The invariant.
    """
    fields = {**_defaults("invariant"), **definition}
    return Invariant(
        id=invariant_id,
        title=fields["title"],
        expectation=fields["expectation"],
        needs=frozenset(fields["needs"]),
        covers=tuple(fields["covers"]),
    )


def load_expected_failures(path: Path) -> list[ExpectedFailure]:
    """
    Read a connector's expected failures, checked against their schema.

    Args:
        path: The file.

    Returns:
        Each entry, in the file's order.

    Raises:
        yaml.YAMLError: The file doesn't parse, or names a case twice.
        InvalidData: The file doesn't meet its schema.
    """
    # An empty file holds no entries.
    data: Any = read_document(path) or {}
    check_schema(data, path, EXPECTED_FAILURES_SCHEMA)
    return [
        ExpectedFailure(
            case_id,
            entry["reason"],
            _optional_set(entry.get("transports")),
            _optional_set(entry.get("platforms")),
            _optional_set(entry.get("vias")),
        )
        for case_id, entry in cast("dict[str, Any]", data).items()
    ]


def expected_failure_files() -> list[Path]:
    """
    Find every connector's expected failures among the repository's files.

    Returns:
        Their paths, sorted.

    Raises:
        subprocess.SubprocessError: Git failed, or took longer than its hang guard.
    """
    return files_named(EXPECTED_FAILURES_FILE_NAME)


@cache
def _defaults(definition: Literal["case", "invariant"]) -> Mapping[str, Any]:
    properties = read_document(CASES_SCHEMA)["$defs"][definition]["properties"]
    return {
        key: definition["default"]
        for key, definition in properties.items()
        if "default" in definition
    }


def _optional_set[T](values: Sequence[T] | None) -> frozenset[T] | None:
    return None if values is None else frozenset(values)
