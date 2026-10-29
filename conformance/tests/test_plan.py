from collections.abc import Sequence

import pytest

from runner.cases import (
    Case,
    CaseList,
    Component,
    ExpectedFailure,
    Invariant,
    case_of,
    invariant_of,
)
from runner.plan import (
    BASELINE,
    UnknownCase,
    UnknownComponent,
    plan_invariants,
    plan_run,
)

BUILT = frozenset({"reference-app", "baseline-adapter"})


def case(case_id: str, **fields: object) -> Case:
    definition: dict[str, object] = {
        "title": "A case",
        "expectation": "It holds.",
        "kind": "connector",
        **fields,
    }
    return case_of(case_id, case_id.split(".")[0], definition)


def invariant(invariant_id: str, **fields: object) -> Invariant:
    definition: dict[str, object] = {
        "title": "An invariant",
        "expectation": "It holds in every case.",
        "covers": ["protocol-v1#tokens"],
        **fields,
    }
    return invariant_of(invariant_id, definition)


def case_list(
    *cases: Case,
    built: frozenset[str] = BUILT,
    invariants: Sequence[Invariant] = (),
) -> CaseList:
    names = (
        "reference-app",
        "baseline-adapter",
        "fake-server",
        "server",
        "server-test-hooks",
        "listener-unix",
        "listener-npipe",
        "listener-loopback",
    )
    components = {
        name: Component(name, "A component.", 5, name in built) for name in names
    }
    return CaseList(
        {},
        {each.id: each for each in cases},
        {each.id: each for each in invariants},
        {},
        components,
    )


def test_the_baseline_run_collects_baseline_and_server_cases_on_tcp() -> None:
    cases = case_list(
        case("area.baseline", baseline=True),
        case("area.connector"),
        case("area.server", kind="server"),
    )
    planned = plan_run(
        cases, connector=BASELINE, expected_failures=[], platform="windows"
    )
    assert [(each.id, each.run) for each in planned] == [
        ("area.baseline-tcp", "baseline"),
        ("area.server-npipe", "server"),
        ("area.server-tcp", "server"),
    ]


def test_a_connector_run_collects_every_connector_case_on_each_transport() -> None:
    cases = case_list(
        case("area.baseline", baseline=True),
        case("area.server", kind="server"),
        case("area.posix", platforms=["posix"]),
    )
    planned = plan_run(cases, connector="node", expected_failures=[], platform="posix")
    assert [(each.id, each.run) for each in planned] == [
        ("area.baseline-unix", "connector"),
        ("area.baseline-tcp", "connector"),
        ("area.posix-unix", "connector"),
        ("area.posix-tcp", "connector"),
    ]


def test_a_case_whose_components_arent_built_names_them() -> None:
    planned = plan_run(
        case_list(case("area.hooks", needs=["server-test-hooks"])),
        connector="node",
        expected_failures=[],
        platform="posix",
    )
    assert [component.id for component in planned[0].unbuilt] == [
        "listener-unix",
        "server",
        "server-test-hooks",
    ]


def test_the_baseline_reaches_the_app_without_the_server() -> None:
    planned = plan_run(
        case_list(case("area.baseline", baseline=True)),
        connector=BASELINE,
        expected_failures=[],
        platform="posix",
    )
    assert planned[0].unbuilt == ()


def test_a_case_that_runs_once_runs_on_a_transport_whose_components_are_built() -> None:
    built = BUILT | {"server", "listener-loopback"}
    planned = plan_run(
        case_list(case("area.once", once=True), built=built),
        connector="node",
        expected_failures=[],
        platform="windows",
    )
    assert [(each.id, each.transports, each.unbuilt) for each in planned] == [
        ("area.once", ("tcp",), ())
    ]


def test_an_expected_failure_covers_only_the_permutations_it_names() -> None:
    failure = ExpectedFailure("area.case", "Fails, #7.", frozenset({"npipe"}), None)
    planned = plan_run(
        case_list(case("area.case")),
        connector="node",
        expected_failures=[failure],
        platform="windows",
    )
    assert [(each.id, each.expected_failure) for each in planned] == [
        ("area.case-npipe", failure),
        ("area.case-tcp", None),
    ]


def test_a_case_that_varies_by_via_runs_once_for_each() -> None:
    failure = ExpectedFailure(
        "area.case", "Fails, #7.", None, None, frozenset({"primitive"})
    )
    planned = plan_run(
        case_list(case("area.case", transports=["tcp"], vias=["untyped", "primitive"])),
        connector="node",
        expected_failures=[failure],
        platform="posix",
    )
    assert [(each.id, each.via, each.expected_failure) for each in planned] == [
        ("area.case-tcp-untyped", "untyped", None),
        ("area.case-tcp-primitive", "primitive", failure),
    ]


def test_a_run_of_named_cases_collects_only_them() -> None:
    cases = case_list(case("area.one"), case("area.two"))
    planned = plan_run(
        cases,
        connector="node",
        expected_failures=[],
        only=["area.two"],
        platform="posix",
    )
    assert {each.case.id for each in planned} == {"area.two"}


def test_a_run_that_names_an_unknown_case_is_refused() -> None:
    with pytest.raises(UnknownCase, match=r"area\.missing"):
        plan_run(
            case_list(case("area.one")),
            connector="node",
            expected_failures=[],
            only=["area.missing"],
        )


def test_a_case_that_needs_a_component_the_table_lacks_names_both() -> None:
    message = r"area\.case needs nothing-such, which components\.yaml lacks"
    with pytest.raises(UnknownComponent, match=message):
        plan_run(
            case_list(case("area.case", needs=["nothing-such"])),
            connector="node",
            expected_failures=[],
            platform="posix",
        )


def test_an_invariant_that_needs_a_component_the_table_lacks_names_both() -> None:
    invariants = [invariant("invariant.any", needs=["nothing-such"])]
    message = r"invariant\.any needs nothing-such, which components\.yaml lacks"
    with pytest.raises(UnknownComponent, match=message):
        plan_invariants(case_list(invariants=invariants))


def test_an_invariant_whose_components_arent_built_names_them() -> None:
    invariants = [
        invariant("invariant.anywhere"),
        invariant("invariant.server", needs=["server", "reference-app"]),
    ]
    planned = plan_invariants(case_list(invariants=invariants))
    assert [
        (each.invariant.id, [component.id for component in each.unbuilt])
        for each in planned
    ] == [("invariant.anywhere", []), ("invariant.server", ["server"])]
