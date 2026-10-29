import pytest

from runner.case_run import CaseRun
from runner.invariants import CHECKS, check_invariants
from runner.plan import PlannedInvariant
from runner.registry import implementation_of


def test_case(case_run: CaseRun, run_invariants: list[PlannedInvariant]) -> None:
    """
    Run one permutation of a conformance case through the case's implementation,
    then check the invariants every case holds to.

    A case that runs here, with every component it needs built, fails while no
    implementation names it, since the issue that builds the last of its components
    implements it.

    Args:
        case_run: The permutation's context.
        run_invariants: The run's invariants.
    """
    implementation = implementation_of(case_run.case.id)
    if implementation is None:
        pytest.fail(
            f"{case_run.case.id} runs here and every component it needs is built, "
            "but no implementation names it"
        )
    implementation(case_run)
    check_invariants(case_run, run_invariants)


def test_invariant(planned_invariant: PlannedInvariant) -> None:
    """
    Check that the runner checks an invariant, once every component it needs is built.

    An invariant is skipped while a component it needs isn't built, as a case is,
    and fails once every one is while :data:`~runner.invariants.CHECKS` has no check
    for it, since the issue that builds the last of its components checks it.

    Args:
        planned_invariant: The invariant.
    """
    invariant = planned_invariant.invariant.id
    if invariant not in CHECKS:
        pytest.fail(
            f"every component {invariant} needs is built, "
            "but runner/invariants.py has no check for it"
        )
