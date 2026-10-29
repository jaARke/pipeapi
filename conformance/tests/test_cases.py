import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Final, TypeAliasType, get_args

import pytest

from runner.adapters import MANIFEST_FILE_NAME, manifests
from runner.cases import (
    BASELINE_TRANSPORT,
    CASES_SCHEMA,
    IMPLIED_COMPONENTS,
    REPOSITORY,
    TRANSPORTS_OF,
    Backend,
    CaseList,
    Kind,
    Permutation,
    Platform,
    Transport,
    Via,
    case_of,
    expected_failure_files,
    load_case_list,
    load_expected_failures,
)
from runner.contract import PROTOCOL_VERSION, Contract, load_contract
from runner.invariants import CHECKS
from runner.registry import Registration, load_implementations
from runner.schemas import registry

# A rule finds what breaks it in the case list, one message each, naming the case.
type Rule = Callable[[CaseList], list[str]]

# A name the contract's files define, as the case list writes one out: a protocol
# variable, a header, whose name matches without regard to case, or a reserved route.
PROTOCOL_NAME: Final = re.compile(
    r"PIPEAPI_[A-Z0-9_]*[A-Z0-9]|(?i:X-PipeAPI-[A-Z0-9-]*[A-Z0-9])|/__pipeapi/[\w-]*"
)
HEADER_PREFIX: Final = "x-pipeapi-"
# The names cases write out because no protocol version defines them.
UNDEFINED_NAMES: Final = frozenset(
    {"PIPEAPI_FUTURE", "X-PipeAPI-Future", "/__pipeapi/nothing"}
)
# An issue a case's expectation names, such as #6.
ISSUE: Final = re.compile(r"#[1-9][0-9]*\b")


def transports_of(permutation: Permutation) -> list[Transport]:
    """The transport a permutation runs on, or each one a case that runs once may."""
    if permutation.transport is not None:
        return [permutation.transport]
    return list(TRANSPORTS_OF[permutation.platform])


def needs_of(case_list: CaseList) -> Iterator[tuple[str, str]]:
    """
    Each component each case needs, in each of its runs, on each transport, and each
    an invariant needs, with the ID of the case or invariant that needs it.
    """
    for case in case_list.cases.values():
        for run in case.runs():
            for permutation in case.permutations():
                transports: list[Transport] = transports_of(permutation)
                if run == "baseline":
                    transports = [BASELINE_TRANSPORT]
                for transport in transports:
                    for need in case.needs_in(run, transport):
                        yield case.id, need
    for invariant in case_list.invariants.values():
        for need in invariant.needs:
            yield invariant.id, need


def name_key(name: str) -> str:
    """The form a protocol name compares in: a header's in lower case, as HTTP's."""
    folded = name.lower()
    return folded if folded.startswith(HEADER_PREFIX) else name


def defined_names(contract: Contract) -> frozenset[str]:
    """Each name a protocol version defines that PROTOCOL_NAME can find, by its key."""
    components = contract.document["components"]
    request_headers = [
        parameter["name"]
        for parameter in components["parameters"].values()
        if parameter["in"] == "header"
    ]
    names = [
        *contract.registry["environment_variables"],
        *request_headers,
        *components["headers"],
        *(operation.path for operation in contract.operations),
        contract.constant("reserved_prefix"),
    ]
    return frozenset(name_key(name) for name in names)


def texts_of(case_list: CaseList) -> Iterator[tuple[str, str]]:
    """Each text of the case list's files that the site renders, with whose it is."""
    for area in case_list.areas.values():
        yield f"the area {area.name}", area.title
        yield f"the area {area.name}", area.description
    for case in case_list.cases.values():
        yield case.id, case.title
        yield case.id, case.expectation
    for invariant in case_list.invariants.values():
        yield invariant.id, invariant.title
        yield invariant.id, invariant.expectation
    for citation, reason in case_list.uncovered.items():
        yield f"uncovered's {citation}", reason
    for component in case_list.components.values():
        yield f"the component {component.id}", component.description


def ids_start_with_their_area(case_list: CaseList) -> list[str]:
    return [
        f"{case.id} is in the area {case.area}, so its ID starts with {case.area}."
        for case in case_list.cases.values()
        if not case.id.startswith(f"{case.area}.")
    ]


def ids_are_unique(case_list: CaseList) -> list[str]:
    # A mapping already refuses a key twice; this finds an ID two mappings share.
    seen: dict[str, str] = {}
    found: list[str] = []
    for area in case_list.areas.values():
        for case_id in area.cases:
            if case_id in seen:
                found.append(f"{case_id} is in both {seen[case_id]} and {area.name}.")
            seen.setdefault(case_id, area.name)
    found += [
        f"{invariant_id} is both a case and an invariant."
        for invariant_id in case_list.invariants
        if invariant_id in seen
    ]
    return found


def needs_are_components(case_list: CaseList) -> list[str]:
    found = {
        f"{subject} needs {need}, which components.yaml lacks."
        for subject, need in needs_of(case_list)
        if need not in case_list.components
    }
    return sorted(found)


def components_are_needed(case_list: CaseList) -> list[str]:
    needed = {need for _, need in needs_of(case_list)}
    return [
        f"{component} is in components.yaml, but no case needs it."
        for component in case_list.components
        if component not in needed
    ]


def needs_leave_out_what_backends_imply(case_list: CaseList) -> list[str]:
    return [
        f"{case.id} lists {need}, which its backends and its run imply."
        for case in case_list.cases.values()
        for need in sorted(case.needs & IMPLIED_COMPONENTS)
    ]


def cases_apply_somewhere(case_list: CaseList) -> list[str]:
    return [
        f"{case.id}'s transports and platforms leave it nowhere to run."
        for case in case_list.cases.values()
        if not case.permutations()
    ]


def baseline_cases_apply_on_its_transport(case_list: CaseList) -> list[str]:
    return [
        f"{case.id} runs in the baseline, which reaches the app over "
        f"{BASELINE_TRANSPORT}, so it applies there."
        for case in case_list.cases.values()
        if case.baseline
        and not any(
            BASELINE_TRANSPORT in transports_of(permutation)
            for permutation in case.permutations()
        )
    ]


def defaults_are_left_out(case_list: CaseList) -> list[str]:
    # The freeze reads a left-out field as its default, so each is spelled one way.
    every_transport = frozenset(
        transport for transports in TRANSPORTS_OF.values() for transport in transports
    )
    found: list[str] = []
    for case in case_list.cases.values():
        if case.transports == every_transport:
            found.append(f"{case.id} lists every transport, so it leaves them out.")
        if case.platforms == frozenset(TRANSPORTS_OF):
            found.append(f"{case.id} lists every platform, so it leaves them out.")
    return found


def cases_that_cover_nothing_name_an_issue(case_list: CaseList) -> list[str]:
    return [
        f"{case.id} covers no anchor, so its expectation names the issue whose design "
        "it follows, as #<n>."
        for case in case_list.cases.values()
        if not case.covers and ISSUE.search(case.expectation) is None
    ]


def protocol_names_are_defined(case_list: CaseList) -> list[str]:
    # The site renders these texts as they are, so nothing else resolves their names.
    files = f"protocol/v{PROTOCOL_VERSION}/"
    defined = defined_names(load_contract(PROTOCOL_VERSION))
    undefined = {name_key(name) for name in UNDEFINED_NAMES}
    named: set[str] = set()
    found: list[str] = []
    for subject, text in texts_of(case_list):
        for match in PROTOCOL_NAME.finditer(text):
            key = name_key(match[0])
            named.add(key)
            if key not in defined | undefined:
                message = f"{subject} names {match[0]}, which {files} doesn't define."
                found.append(message)
    for name in sorted(UNDEFINED_NAMES):
        if name_key(name) in defined:
            found.append(f"{name} is listed as undefined, but {files} defines it.")
        elif name_key(name) not in named:
            found.append(f"{name} is listed as undefined, but no case names it.")
    return found


def implementations_name_cases_once(case_list: CaseList) -> list[str]:
    found: list[str] = []
    first: dict[str, Registration] = {}
    for registration in load_implementations():
        where, case_id = registration.where, registration.case
        if case_id not in case_list.cases:
            found.append(f"{where} implements {case_id}, which is no case.")
        elif case_id in first:
            earlier = first[case_id].where
            found.append(f"{case_id} is implemented by both {earlier} and {where}.")
        else:
            first[case_id] = registration
    return found


def checks_name_invariants(case_list: CaseList) -> list[str]:
    return [
        f"runner/invariants.py checks {invariant_id}, which is no invariant."
        for invariant_id in CHECKS
        if invariant_id not in case_list.invariants
    ]


RULES: Final[Mapping[str, Rule]] = {
    "ids-start-with-their-area": ids_start_with_their_area,
    "ids-are-unique": ids_are_unique,
    "needs-are-components": needs_are_components,
    "components-are-needed": components_are_needed,
    "needs-leave-out-what-backends-imply": needs_leave_out_what_backends_imply,
    "cases-apply-somewhere": cases_apply_somewhere,
    "baseline-cases-apply-on-its-transport": baseline_cases_apply_on_its_transport,
    "defaults-are-left-out": defaults_are_left_out,
    "cases-that-cover-nothing-name-an-issue": cases_that_cover_nothing_name_an_issue,
    "protocol-names-are-defined": protocol_names_are_defined,
    "implementations-name-cases-once": implementations_name_cases_once,
    "checks-name-invariants": checks_name_invariants,
}

# Each type of the model, with the $defs entry of cases.schema.json that allows the
# same values, or None for a case's property of the type's name.
MODEL_TYPES: Final[list[tuple[TypeAliasType, str | None]]] = [
    (Kind, None),
    (Backend, "backend"),
    (Transport, "transport"),
    (Platform, "platform"),
    (Via, "via"),
]


def values_of(pointer: str) -> set[str]:
    """The values a definition of cases.schema.json allows, its references followed."""
    resolver = registry().resolver(base_uri=CASES_SCHEMA.as_uri())
    resolved = resolver.lookup(pointer)
    contents: dict[str, Any] = resolved.contents
    while "$ref" in contents:
        resolved = resolved.resolver.lookup(contents["$ref"])
        contents = resolved.contents
    if "enum" in contents:
        return set(contents["enum"])
    return {member["const"] for member in contents["oneOf"]}


def definition(**fields: object) -> dict[str, object]:
    """A connector case's definition, with the fields given over it."""
    return {
        "title": "A case",
        "expectation": "It holds.",
        "kind": "connector",
        **fields,
    }


@pytest.fixture(scope="module")
def case_list() -> CaseList:
    return load_case_list()


@pytest.mark.parametrize("rule", RULES)
def test_the_case_list_keeps_each_rule(case_list: CaseList, rule: str) -> None:
    assert RULES[rule](case_list) == []


def test_every_expected_failure_names_a_connector_case_it_can_fail(
    case_list: CaseList,
) -> None:
    found: list[str] = []
    for path in expected_failure_files():
        where = path.relative_to(REPOSITORY).as_posix()
        if not (path.parent / MANIFEST_FILE_NAME).is_file():
            found.append(f"{where} sits beside no {MANIFEST_FILE_NAME}.")
        for entry in load_expected_failures(path):
            case = case_list.cases.get(entry.case)
            if case is None:
                found.append(f"{where} names {entry.case}, which is no case.")
            elif case.kind != "connector":
                found.append(f"{where} names {entry.case}, a server case.")
            elif not any(entry.matches(each) for each in case.permutations()):
                found.append(f"{where} names none of {entry.case}'s permutations.")
    assert found == []


def test_every_adapter_manifest_meets_its_schema_and_names_a_connector_once() -> None:
    assert manifests(), f"the baseline adapter has its {MANIFEST_FILE_NAME}"


@pytest.mark.parametrize(
    ("model_type", "schema_definition"),
    MODEL_TYPES,
    ids=[model_type.__name__ for model_type, _ in MODEL_TYPES],
)
def test_the_model_allows_what_the_schema_allows(
    model_type: TypeAliasType, schema_definition: str | None
) -> None:
    if schema_definition is None:
        pointer = f"#/$defs/case/properties/{model_type.__name__.lower()}"
    else:
        pointer = f"#/$defs/{schema_definition}"
    assert set(get_args(model_type.__value__)) == values_of(pointer)


def test_a_case_runs_on_each_transport_of_each_platform_it_applies_to() -> None:
    case = case_of("area.name", "area", definition(transports=["npipe", "tcp"]))
    assert case.permutations() == [
        Permutation("posix", "tcp"),
        Permutation("windows", "npipe"),
        Permutation("windows", "tcp"),
    ]


def test_a_case_that_varies_by_via_runs_once_for_each_on_each_transport() -> None:
    fields = definition(platforms=["posix"], vias=["untyped", "primitive"])
    case = case_of("area.name", "area", fields)
    assert case.permutations() == [
        Permutation("posix", "unix", "untyped"),
        Permutation("posix", "unix", "primitive"),
        Permutation("posix", "tcp", "untyped"),
        Permutation("posix", "tcp", "primitive"),
    ]


def test_a_case_that_runs_once_has_one_permutation_on_each_platform() -> None:
    case = case_of("area.name", "area", definition(once=True, platforms=["windows"]))
    assert case.permutations() == [Permutation("windows", None)]


def test_a_server_case_needs_the_server_and_the_transports_listener() -> None:
    case = case_of("area.name", "area", definition(kind="server", needs=["hooks"]))
    assert case.needs_in("server", "npipe") == {
        "hooks",
        "server",
        "listener-npipe",
        "reference-app",
    }


def test_a_server_case_that_serves_nothing_needs_only_the_server() -> None:
    case = case_of("area.name", "area", definition(kind="server", backends=[]))
    assert case.needs_in("server", "unix") == {"server"}


def test_a_connector_case_needs_what_its_backends_reach() -> None:
    case = case_of("area.name", "area", definition(backends=["app", "fake"]))
    assert case.needs_in("connector", "unix") == {
        "server",
        "listener-unix",
        "fake-server",
        "reference-app",
    }


def test_the_baseline_reaches_the_app_without_the_server() -> None:
    case = case_of("area.name", "area", definition(baseline=True))
    assert case.needs_in("baseline", "tcp") == {
        "baseline-adapter",
        "reference-app",
    }
