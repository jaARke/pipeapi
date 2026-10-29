import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property, partial
from pathlib import Path, PurePosixPath
from typing import Final, Literal, TypeIs, cast, override

import yaml

type Status = Literal["draft", "released"]
type Fields = Mapping[str, object]
type Names = Mapping[str, Fields]
"""Each name a revision holds, mapped to the fields frozen with it."""
type FieldShape = Literal["value", "set"]
"""How a frozen field compares: as a value, or as a set, which no reordering changes."""


@dataclass(frozen=True)
class NamedUnion:
    """A union of a JSON Schema whose members each have a name, such as error codes."""

    members: tuple[str, ...]
    """The keys from the schema's root to the list of its members."""
    name: tuple[str, ...]
    """The keys from a member to its name."""


ROOT: Final = Path(__file__).resolve().parents[1]
STATUSES: Final[tuple[Status, ...]] = ("draft", "released")
RELEASED: Final[Status] = "released"
# A protocol version is a directory of protocol/ that holds a registry.
REGISTRY: Final = re.compile(r"protocol/(v[1-9][0-9]*)/registry\.yaml")
# A vector file, as the vectors' check-jsonschema hook in .pre-commit-config.yaml
# matches them.
VECTOR_FILE: Final = re.compile(r"[a-z-]+\.json")
CONNECTOR_API: Final = "protocol/connector-api/connector-api.schema.json"
# An adapter protocol version is a directory of conformance/adapter-protocol/ that
# holds a schema.
ADAPTER_PROTOCOL: Final = re.compile(
    r"conformance/adapter-protocol/(v[1-9][0-9]*)/adapter-protocol\.schema\.json"
)
CASES: Final = "conformance/cases/cases.yaml"
CASES_SCHEMA: Final = "conformance/cases/cases.schema.json"
# Each field frozen with a conformance case. A case that leaves one out has the default
# the revision's cases.schema.json gives it, or None where the schema gives none.
FROZEN_CASE_FIELDS: Final[Mapping[str, FieldShape]] = {
    "expectation": "value",
    "kind": "value",
    "backends": "set",
    "needs": "set",
    "relies_on": "set",
    "transports": "set",
    "platforms": "set",
    "vias": "set",
    "once": "value",
}
# Each field frozen with an invariant, which takes its default as a case's fields do.
FROZEN_INVARIANT_FIELDS: Final[Mapping[str, FieldShape]] = {
    "expectation": "value",
    "needs": "set",
}
REJECTED_HEADER: Final = "x-pipeapi-rejected"
# The extension on each response that carries X-PipeAPI-Rejected, which lists the
# codes it may carry.
REJECTIONS_EXTENSION: Final = "x-rejections"
# The connector API's unions whose names apps match on, by the section of the site's
# page that lists each.
CONNECTOR_API_UNIONS: Final = {
    "events": NamedUnion(("$defs", "event", "oneOf"), ("properties", "type", "const")),
    "errors": NamedUnion(("$defs", "error", "oneOf"), ("properties", "code", "const")),
    "lost_reasons": NamedUnion(("$defs", "lost_reason", "oneOf"), ("const",)),
}
# The adapter protocol's unions whose names the runner and an adapter match on.
ADAPTER_PROTOCOL_UNIONS: Final = {
    "commands": NamedUnion(
        ("$defs", "command", "oneOf"), ("properties", "command", "const")
    ),
    "events": NamedUnion(("$defs", "event", "oneOf"), ("properties", "event", "const")),
    "capabilities": NamedUnion(("$defs", "capability", "oneOf"), ("const",)),
    "refusals": NamedUnion(
        ("$defs", "refusal", "properties", "code", "oneOf"), ("const",)
    ),
    "vias": NamedUnion(("$defs", "via", "oneOf"), ("const",)),
    "sinks": NamedUnion(("$defs", "sink", "oneOf"), ("const",)),
    "language_error_kinds": NamedUnion(
        ("$defs", "language_error", "properties", "kind", "oneOf"), ("const",)
    ),
}
# Each kind of proof vector, by the registry constant whose label starts its message.
PROOF_LABELS: Final = {
    "hello_proof": "hello_label",
    "enrollment_proof": "enrollment_label",
}
# A hang guard on each git command, which reads only the local repository.
GIT_TIMEOUT_SECONDS: Final = 60
EXIT_FAILED: Final = 1
EXIT_UNREADABLE: Final = 2


class UnreadableError(Exception):
    """A revision the check can't read at all, such as a base ref the clone lacks."""


class MalformedError(Exception):
    """A file that doesn't hold what one check reads from it, which fails that check."""


@dataclass(frozen=True)
class Tree:
    """
    The repository's files as one revision holds them.

    A git ref's files, or the working tree's copies of the files Git tracks, which are
    the files prek checks.
    """

    ref: str | None
    """The git ref, or None for the working tree."""

    @property
    def label(self) -> str:
        """How findings name the revision."""
        return "the working tree" if self.ref is None else self.ref

    @cached_property
    def paths(self) -> frozenset[str]:
        """Every file the revision holds, by its path from the repository's root."""
        if self.ref is None:
            tracked = _git("ls-files", "-z").split("\0")
            return frozenset(path for path in tracked if (ROOT / path).is_file())
        listed = _git("ls-tree", "-r", "--name-only", "-z", self.ref).split("\0")
        return frozenset(path for path in listed if path)

    def data(self, path: str) -> object:
        """
        Read a YAML or JSON file, by its suffix.

        Args:
            path: The file's path from the repository's root.

        Returns:
            The file's data, or None when the revision doesn't hold the file.

        Raises:
            MalformedError: The file doesn't parse.
        """
        if path not in self.paths:
            return None
        if self.ref is None:
            text = (ROOT / path).read_text(encoding="utf-8")
        else:
            text = _git("show", f"{self.ref}:{path}")
        try:
            if path.endswith(".json"):
                return json.loads(text)
            return yaml.safe_load(text)
        except (json.JSONDecodeError, yaml.YAMLError) as error:
            raise MalformedError(f"{path} doesn't parse: {error}") from error


@dataclass(frozen=True)
class Contract:
    """A part of the contract that's released on its own, then only grows."""

    name: str
    """How findings name it, such as protocol v1."""
    holds: Callable[[Tree], bool]
    """Whether a revision holds it at all."""
    status: Callable[[Tree], Status | None]
    """Its status in a revision, or None where the revision states none."""
    frozen: Mapping[str, Callable[[Tree], Names]]
    """
    Each kind of name it only ever adds to once released, by its check's ID.

    Each reads the names a revision holds. The check reports a name the integration
    branch holds that the working tree removed, or whose frozen fields it changed, and
    fails on one once the contract is released.
    """
    agreements: Mapping[str, Callable[[Tree], Sequence[str]]]
    """
    Each fact it holds in two files, by its check's ID.

    Each reads how a revision's two copies disagree, and the check fails on a
    disagreement in the working tree whatever the status.
    """


@dataclass(frozen=True)
class Finding:
    """One change or disagreement a check found."""

    check: str
    """The check's ID."""
    contract: str
    """The contract it concerns, as findings name it."""
    message: str
    fails: bool
    """Whether it fails the run, rather than only being reported."""

    @override
    def __str__(self) -> str:
        level = "error" if self.fails else "report"
        return f"{level}\t[{self.check}] {self.contract}: {self.message}"


@dataclass(frozen=True)
class ProtocolVersion:
    """One protocol version's directory of protocol/."""

    name: str
    """The directory's name, such as v1."""

    @property
    def registry(self) -> str:
        """The path of the version's registry."""
        return f"protocol/{self.name}/registry.yaml"

    @property
    def openapi(self) -> str:
        """The path of the version's OpenAPI document."""
        return f"protocol/{self.name}/openapi.yaml"

    def vector_files(self, tree: Tree) -> list[str]:
        """
        Find the version's vector files in a revision.

        Args:
            tree: The revision.

        Returns:
            Each vector file's path, in order.
        """
        directory = f"protocol/{self.name}/vectors/"
        return sorted(
            path
            for path in tree.paths
            if path.startswith(directory)
            and VECTOR_FILE.fullmatch(path.removeprefix(directory))
        )


def protocol_version(version: ProtocolVersion) -> Contract:
    """
    Describe the checks of one protocol version, whose registry states its status.

    Args:
        version: The version.

    Returns:
        The version as a contract.
    """
    return Contract(
        name=f"protocol {version.name}",
        holds=lambda tree: version.registry in tree.paths,
        status=partial(registry_status, version=version),
        frozen={
            "registry-entries": partial(registry_entries, version=version),
            "vector-cases": partial(vector_cases, version=version),
            "conformance-cases": conformance_cases,
        },
        agreements={
            "lease-event-types": partial(lease_event_types, version=version),
            "auth-scheme": partial(auth_scheme, version=version),
            "lease-ttl-minimum": partial(lease_ttl_minimum, version=version),
            "rejection-statuses": partial(rejection_statuses, version=version),
            "proof-labels": partial(proof_labels, version=version),
        },
    )


def connector_api() -> Contract:
    """
    Describe the checks of the connector API, whose file states its status.

    Returns:
        The connector API as a contract.
    """
    return Contract(
        name="the connector API",
        holds=lambda tree: CONNECTOR_API in tree.paths,
        status=partial(schema_status, path=CONNECTOR_API),
        frozen={
            "connector-api-identifiers": partial(
                union_names, path=CONNECTOR_API, unions=CONNECTOR_API_UNIONS
            )
        },
        agreements={},
    )


def adapter_protocol_version(name: str) -> Contract:
    """
    Describe the checks of one adapter protocol version, whose schema states its status.

    Args:
        name: The version's directory, such as v1.

    Returns:
        The version as a contract.
    """
    path = f"conformance/adapter-protocol/{name}/adapter-protocol.schema.json"
    return Contract(
        name=f"adapter protocol {name}",
        holds=lambda tree: path in tree.paths,
        status=partial(schema_status, path=path),
        frozen={
            "adapter-protocol-names": partial(
                union_names, path=path, unions=ADAPTER_PROTOCOL_UNIONS
            )
        },
        agreements={},
    )


def contracts(base: Tree, head: Tree) -> list[Contract]:
    """
    List every contract either revision holds.

    Args:
        base: The integration branch.
        head: The working tree.

    Returns:
        Each protocol version in order, the connector API, then each adapter protocol
        version in order.
    """
    protocol = [
        protocol_version(ProtocolVersion(name))
        for name in _versions(REGISTRY, base, head)
    ]
    adapter = [
        adapter_protocol_version(name)
        for name in _versions(ADAPTER_PROTOCOL, base, head)
    ]
    return [*protocol, connector_api(), *adapter]


def check(contract: Contract, base: Tree, head: Tree) -> list[Finding]:
    """
    Compare a contract in the working tree with the integration branch.

    A frozen name's change fails once the contract is released in either revision.
    A released contract that returns to draft, a disagreement and a malformed file in
    the working tree always fail. A malformed file in the integration branch fails
    once the contract is released, and is only reported while it's a draft, which may
    restructure its files.

    Args:
        contract: The contract.
        base: The integration branch.
        head: The working tree.

    Returns:
        What its checks found.
    """
    found: list[Finding] = []
    try:
        head_status = contract.status(head)
    except MalformedError as error:
        found.append(Finding("status", contract.name, _in(head, error), fails=True))
        head_status = RELEASED
    try:
        base_status = contract.status(base)
    except MalformedError as error:
        fails = head_status == RELEASED
        found.append(Finding("status", contract.name, _in(base, error), fails=fails))
        base_status = None
    if base_status == RELEASED and head_status != RELEASED:
        message = f"is released in {base.label}, and a released contract stays so"
        found.append(Finding("status", contract.name, message, fails=True))
    released = RELEASED in (base_status, head_status)
    label = f"{contract.name}, {'released' if released else 'a draft'}"
    for name, names in contract.frozen.items():
        found += _frozen(name, label, names, base, head, released=released)
    if contract.holds(head):
        for name, disagreements in contract.agreements.items():
            try:
                messages = disagreements(head)
            except MalformedError as error:
                messages = [_in(head, error)]
            found += [
                Finding(name, contract.name, message, fails=True)
                for message in messages
            ]
    return found


def registry_status(tree: Tree, version: ProtocolVersion) -> Status | None:
    """
    Read a protocol version's status from its registry.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        The status, or None where the revision states none.
    """
    registry = tree.data(version.registry)
    if registry is None:
        return None
    status = _mapping(registry, version.registry).get("status")
    return _status(status, f"{version.registry}'s status")


def registry_entries(tree: Tree, version: ProtocolVersion) -> Names:
    """
    Read a protocol version's registry entries, with every field but the description.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        Each entry, named as its section and its name, such as rejections.draining.
    """
    registry = tree.data(version.registry)
    if registry is None:
        return {}
    names: dict[str, Fields] = {}
    for section, entries in _mapping(registry, version.registry).items():
        if section == "status":
            continue
        where = f"{version.registry}'s {section}"
        for name, entry in _mapping(entries, where).items():
            fields = _mapping(entry, f"{where}.{name}")
            names[f"{section}.{name}"] = _without(fields, "description")
    return names


def vector_cases(tree: Tree, version: ProtocolVersion) -> Names:
    """
    Read a protocol version's test vectors, each case with every field but its comment.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        Each case, named as its file and its tcId, such as hello-proof.json case 3.
    """
    names: dict[str, Fields] = {}
    for path in version.vector_files(tree):
        tests = _at(tree.data(path), path, "tests")
        for case in _sequence(tests, f"{path}'s tests"):
            fields = _mapping(case, f"a case in {path}")
            name = f"{PurePosixPath(path).name} case {fields.get('tcId')}"
            names[name] = _without(fields, "comment")
    return names


def conformance_cases(tree: Tree) -> Names:
    """
    Read the conformance cases and invariants, each with the fields frozen with it.

    The cases hold for every protocol version, so each version's check reads them all.
    A field a case or an invariant leaves out has the default its schema gives, and a
    field that holds a set is sorted, so reordering it changes nothing.

    Args:
        tree: The revision.

    Returns:
        Each case and invariant, by its ID, such as endpoint.invalid-refused.
    """
    cases = tree.data(CASES)
    if cases is None:
        return {}
    schema = tree.data(CASES_SCHEMA)
    case_defaults = _defaults(schema, "case")
    invariant_defaults = _defaults(schema, "invariant")
    names: dict[str, Fields] = {}
    areas = _at(cases, CASES, "areas")
    for area, definition in _mapping(areas, f"{CASES}'s areas").items():
        where = f"{CASES}'s area {area}"
        for case_id, case in _mapping(_at(definition, where, "cases"), where).items():
            fields = _mapping(case, f"{CASES}'s {case_id}")
            names[case_id] = _frozen_fields(fields, case_defaults, FROZEN_CASE_FIELDS)
    invariants = _mapping(_at(cases, CASES, "invariants"), f"{CASES}'s invariants")
    for invariant_id, invariant in invariants.items():
        fields = _mapping(invariant, f"{CASES}'s {invariant_id}")
        names[invariant_id] = _frozen_fields(
            fields, invariant_defaults, FROZEN_INVARIANT_FIELDS
        )
    return names


def schema_status(tree: Tree, path: str) -> Status | None:
    """
    Read a contract's status from the x-status of the JSON Schema that defines it.

    Args:
        tree: The revision.
        path: The schema's path from the repository's root.

    Returns:
        The status, or None where the revision states none.
    """
    schema = tree.data(path)
    if schema is None:
        return None
    status = _mapping(schema, path).get("x-status")
    return _status(status, f"{path}'s x-status")


def union_names(tree: Tree, path: str, unions: Mapping[str, NamedUnion]) -> Names:
    """
    Read the names of a JSON Schema's unions, such as the connector API's error codes.

    Args:
        tree: The revision.
        path: The schema's path from the repository's root.
        unions: Each union, by the section that names its members.

    Returns:
        Each name, by its section and itself, such as errors.closed.
    """
    schema = tree.data(path)
    if schema is None:
        return {}
    names: dict[str, Fields] = {}
    for section, union in unions.items():
        pointer = "/".join(union.members)
        members = _sequence(_at(schema, path, *union.members), f"{path}'s {pointer}")
        for index, member in enumerate(members):
            where = f"{path}'s {pointer} member {index + 1}"
            name = _string(_at(member, where, *union.name), where)
            names[f"{section}.{name}"] = {}
    return names


def lease_event_types(tree: Tree, version: ProtocolVersion) -> list[str]:
    """
    Check that the registry's lease event types are the lease_event schema's branches.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        Each type only one of the two files holds.
    """
    registry, openapi = tree.data(version.registry), tree.data(version.openapi)
    listed = _at(registry, version.registry, "lease_event_types")
    types = {str(name) for name in _mapping(listed, "lease_event_types")}
    union = _at(openapi, version.openapi, "components", "schemas", "lease_event")
    allof = _sequence(_at(union, "lease_event", "allOf"), "lease_event's allOf")
    branches: set[str] = set()
    for index, branch in enumerate(allof):
        where = f"{version.openapi}'s lease_event branch {index + 1}"
        branch_type = _at(branch, where, "if", "properties", "type", "const")
        branches.add(_string(branch_type, where))
    return [
        *(
            f"registry.yaml's lease_event_types has {name}, which no branch of "
            "openapi.yaml's lease_event schema matches"
            for name in sorted(types - branches)
        ),
        *(
            f"openapi.yaml's lease_event schema has a branch for {name}, which "
            "registry.yaml's lease_event_types lacks"
            for name in sorted(branches - types)
        ),
    ]


def auth_scheme(tree: Tree, version: ProtocolVersion) -> list[str]:
    """
    Check that the WWW-Authenticate pattern starts with the registry's scheme.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        The disagreement, if any.
    """
    registry, openapi = tree.data(version.registry), tree.data(version.openapi)
    constant = _at(registry, version.registry, "constants", "auth_scheme", "value")
    scheme = _string(constant, "constants.auth_scheme")
    header = _at(openapi, version.openapi, "components", "headers", "WWW-Authenticate")
    pattern = _string(_at(header, "WWW-Authenticate", "schema", "pattern"), "pattern")
    if pattern.startswith(f"^{re.escape(scheme)} "):
        return []
    return [
        f"openapi.yaml's WWW-Authenticate pattern, {pattern}, doesn't start with "
        f"registry.yaml's constants.auth_scheme, {scheme}"
    ]


def lease_ttl_minimum(tree: Tree, version: ProtocolVersion) -> list[str]:
    """
    Check that the session event's lease_ttl minimum is the registry's minimum.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        The disagreement, if any.
    """
    registry, openapi = tree.data(version.registry), tree.data(version.openapi)
    duration = _at(registry, version.registry, "durations", "lease_ttl_minimum")
    seconds = _at(duration, "lease_ttl_minimum", "seconds")
    event = _at(openapi, version.openapi, "components", "schemas", "session_event")
    minimum = _at(event, "session_event", "properties", "lease_ttl", "minimum")
    if seconds == minimum:
        return []
    return [
        f"registry.yaml's durations.lease_ttl_minimum is {seconds} seconds, and the "
        f"minimum of openapi.yaml's session_event lease_ttl is {minimum}"
    ]


def rejection_statuses(tree: Tree, version: ProtocolVersion) -> list[str]:
    """
    Check the rejection codes that openapi.yaml's responses list against the registry.

    A response that carries X-PipeAPI-Rejected, and only such a response, lists the
    codes it may carry in x-rejections. Each must be a rejection in the registry whose
    status is the response's, and the response's description names exactly the
    registry's codes it lists. Such a response gives no content, since a rejection's
    body is empty.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        Each response that lists no code or lists one without the marker, one with the
        marker that gives content, a code the registry lacks, a code whose status
        differs, and a description that leaves out a code the response lists or names
        one it doesn't.
    """
    registry, document = tree.data(version.registry), tree.data(version.openapi)
    rejections = _mapping(_at(registry, version.registry, "rejections"), "rejections")
    statuses = {
        str(code): _at(entry, f"rejections.{code}", "status")
        for code, entry in rejections.items()
    }
    found: list[str] = []
    for route, operation in _operations(document, version.openapi):
        responses = _at(operation, route, "responses")
        for status, given in _mapping(responses, f"{route}'s responses").items():
            where = f"{route}'s {status} response"
            response = _mapping(_resolve(document, given, version.openapi), where)
            headers = _mapping(response.get("headers", {}), f"{where}'s headers")
            marked = REJECTED_HEADER in {str(name).lower() for name in headers}
            if not marked:
                if REJECTIONS_EXTENSION in response:
                    found.append(
                        f"{where} has {REJECTIONS_EXTENSION} and doesn't carry "
                        "X-PipeAPI-Rejected"
                    )
                continue
            if "content" in response:
                found.append(
                    f"{where} carries X-PipeAPI-Rejected and gives content, though a "
                    "rejection's body is empty"
                )
            if REJECTIONS_EXTENSION not in response:
                found.append(
                    f"{where} carries X-PipeAPI-Rejected and has no "
                    f"{REJECTIONS_EXTENSION}"
                )
                continue
            within = f"{where}'s {REJECTIONS_EXTENSION}"
            listed = [
                _string(code, within)
                for code in _sequence(response[REJECTIONS_EXTENSION], within)
            ]
            if not listed:
                found.append(f"{within} lists no code")
            text = _string(response.get("description"), f"{where}'s description")
            for code in listed:
                if code not in statuses:
                    found.append(
                        f"{within} lists {code}, which registry.yaml's rejections lack"
                    )
                elif str(statuses[code]) != str(status):
                    found.append(
                        f"{within} lists {code}, whose status in registry.yaml is "
                        f"{statuses[code]}"
                    )
                if not _names(text, code):
                    found.append(f"{where}'s description doesn't name {code}")
            found += [
                f"{where}'s description names {code}, which its "
                f"{REJECTIONS_EXTENSION} doesn't list"
                for code in sorted(statuses)
                if _names(text, code) and code not in listed
            ]
    return found


def proof_labels(tree: Tree, version: ProtocolVersion) -> list[str]:
    """
    Check that each proof vector's message starts with the registry's label.

    Args:
        tree: The revision.
        version: The version.

    Returns:
        Each case whose message starts otherwise.
    """
    registry = tree.data(version.registry)
    found: list[str] = []
    for path in version.vector_files(tree):
        vectors = _mapping(tree.data(path), path)
        constant = PROOF_LABELS.get(str(vectors.get("kind")))
        if constant is None:
            continue
        value = _at(registry, version.registry, "constants", constant, "value")
        label = _string(value, f"constants.{constant}")
        prefix = f"{label.encode().hex()}00"
        for case in _sequence(vectors.get("tests"), f"{path}'s tests"):
            fields = _mapping(case, f"a case in {path}")
            message = fields.get("message")
            if isinstance(message, str) and not message.startswith(prefix):
                name = f"{PurePosixPath(path).name} case {fields.get('tcId')}"
                found.append(
                    f"{name}'s message doesn't start with registry.yaml's "
                    f"constants.{constant}, {label}, and a zero byte"
                )
    return found


def main() -> int:
    """
    Check the contract in the working tree against the integration branch.

    Returns:
        The exit status: 0 when nothing fails, 1 when a finding does, and 2 when a
        revision can't be read.
    """
    parser = argparse.ArgumentParser(
        description="Check that the contract only grows once released, "
        "and that the facts two of its files hold agree. A draft's changes are "
        "reported, and a released contract's fail."
    )
    parser.add_argument(
        "--base",
        required=True,
        help="the git ref of the integration branch, such as origin/main",
    )
    base, head = Tree(parser.parse_args().base), Tree(None)
    try:
        _git("rev-parse", "--verify", "--quiet", f"{base.ref}^{{commit}}")
    except UnreadableError:
        print(
            f"{base.ref} names no commit in this clone. Fetch the integration "
            "branch, such as with git fetch origin main, then run the check again.",
            file=sys.stderr,
        )
        return EXIT_UNREADABLE
    try:
        found = [
            finding
            for contract in contracts(base, head)
            for finding in check(contract, base, head)
        ]
    except UnreadableError as error:
        print(error, file=sys.stderr)
        return EXIT_UNREADABLE
    for finding in found:
        print(finding)
    errors = sum(finding.fails for finding in found)
    if found:
        print(f"{errors} errors, {len(found) - errors} reports")
    return EXIT_FAILED if errors else 0


def _versions(directory: re.Pattern[str], base: Tree, head: Tree) -> list[str]:
    names = {
        match.group(1)
        for tree in (base, head)
        for path in tree.paths
        if (match := directory.fullmatch(path))
    }
    return sorted(names, key=lambda name: int(name.removeprefix("v")))


def _frozen(
    check: str,
    contract: str,
    names: Callable[[Tree], Names],
    base: Tree,
    head: Tree,
    *,
    released: bool,
) -> list[Finding]:
    try:
        after = names(head)
    except MalformedError as error:
        return [Finding(check, contract, _in(head, error), fails=True)]
    try:
        before = names(base)
    except MalformedError as error:
        return [Finding(check, contract, _in(base, error), fails=released)]
    return [
        Finding(check, contract, message, fails=released)
        for message in _changes(before, after)
    ]


def _changes(before: Names, after: Names) -> list[str]:
    # Values compare as JSON text, which tells 0 from false and 1 from 1.0.
    found: list[str] = []
    for name, fields in before.items():
        if name not in after:
            found.append(f"{name} was removed")
            continue
        for key, value in fields.items():
            if key not in after[name]:
                found.append(f"{name}'s {key} was removed")
            elif _text(after[name][key]) != _text(value):
                change = f"from {_text(value)} to {_text(after[name][key])}"
                found.append(f"{name}'s {key} changed {change}")
    return found


def _defaults(schema: object, definition: str) -> Fields:
    # The default cases.schema.json gives each property of a definition, or None.
    properties = _at(schema, CASES_SCHEMA, "$defs", definition, "properties")
    within = f"{CASES_SCHEMA}'s {definition} properties"
    return {
        key: _mapping(field, f"{within}.{key}").get("default")
        for key, field in _mapping(properties, within).items()
    }


def _frozen_fields(
    fields: Fields, defaults: Fields, frozen: Mapping[str, FieldShape]
) -> Fields:
    return {
        key: _frozen_value(fields.get(key, defaults.get(key)), shape)
        for key, shape in frozen.items()
    }


def _frozen_value(value: object, shape: FieldShape) -> object:
    if shape == "set" and isinstance(value, list):
        return sorted(cast("list[object]", value), key=_text)
    return value


def _in(tree: Tree, error: MalformedError) -> str:
    return f"in {tree.label}, {error}"


def _operations(document: object, path: str) -> list[tuple[str, object]]:
    # Every value of a path item that has responses is an operation, as is each of
    # OpenAPI 3.2's additionalOperations, so no list of methods is kept here.
    operations: list[tuple[str, object]] = []
    paths = _mapping(_at(document, path, "paths"), f"{path}'s paths")
    for route, item in paths.items():
        fields = _mapping(item, f"{path}'s {route}")
        additional = fields.get("additionalOperations", {})
        others = _mapping(additional, f"{route}'s additionalOperations")
        for method, operation in [*fields.items(), *others.items()]:
            if _is_mapping(operation) and "responses" in operation:
                operations.append((f"{method.upper()} {route}", operation))
    return operations


def _resolve(document: object, node: object, path: str) -> object:
    while _is_mapping(node) and isinstance(ref := node.get("$ref"), str):
        if not ref.startswith("#/"):
            raise MalformedError(f"{path} refers to {ref}, outside the document")
        keys = ref.removeprefix("#/").split("/")
        node = _at(document, path, *(_unescape(key) for key in keys))
    return node


def _unescape(key: str) -> str:
    return key.replace("~1", "/").replace("~0", "~")


def _names(text: str, code: str) -> bool:
    return re.search(rf"\b{re.escape(code)}\b", text) is not None


def _at(node: object, where: str, *keys: str) -> object:
    for depth, key in enumerate(keys):
        within = where if depth == 0 else f"{where}'s {'.'.join(keys[:depth])}"
        fields = _mapping(node, within)
        if key not in fields:
            raise MalformedError(f"{where} has no {'.'.join(keys[: depth + 1])}")
        node = fields[key]
    return node


def _mapping(node: object, where: str) -> Mapping[str, object]:
    if not _is_mapping(node):
        raise MalformedError(f"{where} is not a mapping")
    return node


def _is_mapping(node: object) -> TypeIs[dict[str, object]]:
    return isinstance(node, dict)


def _sequence(node: object, where: str) -> Sequence[object]:
    if not isinstance(node, list):
        raise MalformedError(f"{where} is not a list")
    return cast("list[object]", node)


def _string(node: object, where: str) -> str:
    if not isinstance(node, str):
        raise MalformedError(f"{where} is not a string")
    return node


def _status(node: object, where: str) -> Status | None:
    if node is None:
        return None
    for status in STATUSES:
        if node == status:
            return status
    raise MalformedError(f"{where} is {_text(node)}, not {' or '.join(STATUSES)}")


def _without(fields: Fields, key: str) -> Fields:
    return {name: value for name, value in fields.items() if name != key}


def _text(value: object) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def _git(*arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=ROOT,
            capture_output=True,
            encoding="utf-8",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        message = f"git {arguments[0]} took more than {GIT_TIMEOUT_SECONDS} seconds"
        raise UnreadableError(message) from error
    if result.returncode != 0:
        message = f"git {arguments[0]} exited with {result.returncode}"
        raise UnreadableError(f"{message}: {result.stderr.strip()}")
    return result.stdout


if __name__ == "__main__":
    sys.exit(main())
