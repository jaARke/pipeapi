from collections.abc import Collection, Iterable
from dataclasses import dataclass
from typing import Final

from runner.cases import (
    BASELINE_TRANSPORT,
    COMPONENTS_FILE,
    PLATFORM,
    TRANSPORTS_OF,
    Case,
    CaseList,
    Component,
    ExpectedFailure,
    Invariant,
    Permutation,
    Platform,
    Run,
    Transport,
    Via,
)

BASELINE: Final = "baseline"
"""The baseline adapter's connector name, whose run is the baseline run."""


class UnknownCase(Exception):
    """A run asked for a case the case list doesn't define."""


class UnknownComponent(Exception):
    """A case or an invariant needs a component the component table lacks."""


@dataclass(frozen=True)
class Planned:
    """One permutation of one case that a run collects, and what gates it."""

    case: Case
    run: Run
    transports: tuple[Transport, ...]
    """
    The transport it runs on, or for a case that runs once, each it may run on, in
    the order the runner tries them, all with the components they need built.
    """
    via: Via | None
    """What its requests go through, or None for a case that doesn't vary by it."""
    unbuilt: tuple[Component, ...]
    """The components it needs that aren't built, so it doesn't run yet."""
    expected_failure: ExpectedFailure | None
    """The connector's expected failure that covers it, if any."""

    @property
    def id(self) -> str:
        """
        The permutation's ID: the case's, with its transport unless it runs once, and
        what its requests go through if it varies by that.
        """
        parts = [self.case.id]
        if not self.case.once:
            parts.append(self.transports[0])
        if self.via is not None:
            parts.append(self.via)
        return "-".join(parts)


@dataclass(frozen=True)
class PlannedInvariant:
    """An invariant a run checks in every case, and what gates it."""

    invariant: Invariant
    unbuilt: tuple[Component, ...]
    """The components it needs that aren't built, so the run doesn't check it yet."""


def runs_of(connector: str) -> frozenset[Run]:
    """
    Tell which runs a run for a connector holds.

    A connector's run holds the connector cases, through its adapter. The baseline's
    run is the conformance project's own: the baseline cases through the baseline
    adapter, and the server cases, which no connector's run repeats.

    Args:
        connector: The connector's name.

    Returns:
        The runs.
    """
    if connector == BASELINE:
        return frozenset({"baseline", "server"})
    return frozenset({"connector"})


def plan_run(
    case_list: CaseList,
    *,
    connector: str,
    expected_failures: Collection[ExpectedFailure],
    only: Collection[str] = (),
    platform: Platform = PLATFORM,
) -> list[Planned]:
    """
    Plan the permutations a run collects on this platform, in the case list's order.

    Args:
        case_list: The case list.
        connector: The connector the run is for.
        expected_failures: The connector's expected failures.
        only: The IDs of the cases to collect, or none for every case.
        platform: The platform the run is on.

    Returns:
        The planned permutations.

    Raises:
        UnknownCase: ``only`` names a case the list doesn't define.
        UnknownComponent: A case needs a component the component table lacks.
    """
    unknown = sorted(set(only) - case_list.cases.keys())
    if unknown:
        raise UnknownCase(f"the case list defines no case {', '.join(unknown)}")
    runs = runs_of(connector)
    failures: dict[str, list[ExpectedFailure]] = {}
    for entry in expected_failures:
        failures.setdefault(entry.case, []).append(entry)
    planned: list[Planned] = []
    for case in case_list.cases.values():
        if only and case.id not in only:
            continue
        for run in runs.intersection(case.runs()):
            for permutation in case.permutations():
                if permutation.platform != platform:
                    continue
                transports = _transports_of(case, run, permutation)
                if not transports:
                    continue
                expected = next(
                    (
                        entry
                        for entry in failures.get(case.id, [])
                        if entry.matches(permutation)
                    ),
                    None,
                )
                planned.append(
                    _gated(case_list, case, run, transports, permutation.via, expected)
                )
    return planned


def plan_invariants(case_list: CaseList) -> list[PlannedInvariant]:
    """
    Plan the invariants a run checks, in the case list's order.

    Every run checks each invariant whose components are built, in every case, since
    the components are the same for every run.

    Args:
        case_list: The case list.

    Returns:
        Each invariant, with the components it needs that aren't built.

    Raises:
        UnknownComponent: An invariant needs a component the component table lacks.
    """
    return [
        PlannedInvariant(invariant, _unbuilt(case_list, invariant.id, invariant.needs))
        for invariant in case_list.invariants.values()
    ]


def unbuilt_reason(unbuilt: Iterable[Component]) -> str:
    """
    Say why a case or an invariant whose components aren't all built doesn't run.

    Args:
        unbuilt: The components it needs that aren't built.

    Returns:
        The reason, naming each with the issue that builds it, such as ``needs server
        (#6), not built yet``.
    """
    needs = ", ".join(f"{component.id} (#{component.issue})" for component in unbuilt)
    return f"needs {needs}, not built yet"


def _transports_of(
    case: Case, run: Run, permutation: Permutation
) -> tuple[Transport, ...]:
    applicable: tuple[Transport, ...] = (
        (permutation.transport,)
        if permutation.transport is not None
        else tuple(
            transport
            for transport in TRANSPORTS_OF[permutation.platform]
            if case.transports is None or transport in case.transports
        )
    )
    if run == "baseline":
        return (BASELINE_TRANSPORT,) if BASELINE_TRANSPORT in applicable else ()
    return applicable


def _gated(
    case_list: CaseList,
    case: Case,
    run: Run,
    transports: tuple[Transport, ...],
    via: Via | None,
    expected: ExpectedFailure | None,
) -> Planned:
    unbuilt_of = {
        transport: _unbuilt(case_list, case.id, case.needs_in(run, transport))
        for transport in transports
    }
    ready: tuple[Transport, ...] = tuple(
        transport for transport in transports if not unbuilt_of[transport]
    )
    if ready:
        return Planned(case, run, ready, via, (), expected)
    return Planned(case, run, transports, via, unbuilt_of[transports[0]], expected)


def _unbuilt(
    case_list: CaseList, subject: str, needs: Collection[str]
) -> tuple[Component, ...]:
    unknown = sorted(set(needs) - case_list.components.keys())
    if unknown:
        named = ", ".join(unknown)
        message = f"{subject} needs {named}, which {COMPONENTS_FILE.name} lacks"
        raise UnknownComponent(message)
    return tuple(
        case_list.components[need]
        for need in sorted(needs)
        if not case_list.components[need].built
    )
