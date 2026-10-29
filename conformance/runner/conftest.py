import os
import time
from collections.abc import Collection, Generator, Iterator
from contextlib import ExitStack
from pathlib import Path
from typing import Final, cast

import pytest

from runner.adapter_session import Hello, start_adapter
from runner.adapters import AdapterManifest, UnknownConnector, manifest_of
from runner.case_run import CASE_DEADLINE_SECONDS, CaseRun, RunnerFault
from runner.cases import CaseList, Transport, load_case_list, load_expected_failures
from runner.deadlines import Deadline, DeadlinePassed
from runner.plan import (
    BASELINE,
    Planned,
    PlannedInvariant,
    UnknownCase,
    plan_invariants,
    plan_run,
    unbuilt_reason,
)
from runner.processes import Process, Processes, StillRunning
from runner.raw_client import TRANSPORTS as RAW_CLIENT_TRANSPORTS
from runner.repository import REPOSITORY
from runner.trace import Trace

# The run's traces, one directory per run, which the runner never deletes.
TRACES: Final = REPOSITORY / "conformance" / "traces"

# How many of a failed case's last trace lines its report shows.
TRACE_TAIL_LINES: Final = 60

CASE_LIST_KEY: Final = pytest.StashKey[CaseList]()
PLAN_KEY: Final = pytest.StashKey[list[Planned]]()
INVARIANTS_KEY: Final = pytest.StashKey[list[PlannedInvariant]]()
MANIFEST_KEY: Final = pytest.StashKey[AdapterManifest | None]()
RUN_NAME_KEY: Final = pytest.StashKey[str]()

# What an expected failure covers: the case's own failure, as its call raises it.
EXPECTED_FAILURE_TYPES: Final = (AssertionError, DeadlinePassed)

# The case implementations' and the invariant checks' assertions, rewritten as pytest
# rewrites a test's.
pytest.register_assert_rewrite("runner.implementations", "runner.invariants")


def pytest_addoption(parser: pytest.Parser) -> None:
    """
    Add the runner's options.

    Args:
        parser: pytest's parser.
    """
    group = parser.getgroup("conformance", "pipeapi's conformance suite")
    group.addoption(
        "--connector",
        default=BASELINE,
        help=(
            "The connector whose adapter runs the connector cases, by the name its "
            f"adapter.yaml gives. {BASELINE}, the default, runs the baseline cases "
            "through the baseline adapter, and the server cases."
        ),
    )
    group.addoption(
        "--case",
        action="append",
        default=[],
        dest="cases",
        metavar="ID",
        help="Run only the case with this ID; repeat it for more.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """
    Name the run, by when it started, its connector and the runner's PID.

    Args:
        config: pytest's configuration.
    """
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    connector = cast("str", config.getoption("connector"))
    config.stash[RUN_NAME_KEY] = f"{started}-{connector}-{os.getpid()}"


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """
    Parametrize the suite's tests: the case's by every permutation the run collects,
    and the invariant's by every invariant.

    Args:
        metafunc: The test function's request for parameters.

    Raises:
        pytest.UsageError: The options name no connector or no case.
    """
    config = metafunc.config
    if "planned" in metafunc.fixturenames:
        _plan(config)
        manifest = config.stash[MANIFEST_KEY]
        listed = None if manifest is None else manifest.expected_failures
        params = [
            pytest.param(planned, id=planned.id, marks=_marks(planned, listed))
            for planned in config.stash[PLAN_KEY]
        ]
        metafunc.parametrize("planned", params)
    if "planned_invariant" in metafunc.fixturenames:
        _plan(config)
        params = [
            pytest.param(
                planned,
                id=planned.invariant.id,
                marks=[pytest.mark.skip(reason=unbuilt_reason(planned.unbuilt))]
                if planned.unbuilt
                else [],
            )
            for planned in config.stash[INVARIANTS_KEY]
        ]
        metafunc.parametrize("planned_invariant", params)


@pytest.fixture(scope="session")
def run_directory(pytestconfig: pytest.Config) -> Path:
    """
    The run's directory of traces, one directory for each case within it.

    Returns:
        The directory.
    """
    directory = TRACES / pytestconfig.stash[RUN_NAME_KEY]
    directory.mkdir(parents=True, exist_ok=True)
    return directory


@pytest.fixture(scope="session")
def run_invariants(pytestconfig: pytest.Config) -> list[PlannedInvariant]:
    """
    The run's invariants, each with what gates it, which every case checks.

    Returns:
        The invariants.
    """
    return pytestconfig.stash[INVARIANTS_KEY]


@pytest.fixture(scope="session")
def run_processes() -> Iterator[list[Process]]:
    """
    Every process the run starts, which must all have ended when it ends.

    Yields:
        The processes, which each case's own processes join.

    Raises:
        StillRunning: A process outlived its case, which the runner then kills.
    """
    every: list[Process] = []
    yield every
    left = [process for process in every if process.running()]
    named = [f"{process.name} (PID {process.pid})" for process in left]
    for process in left:
        try:
            process.kill()
        except StillRunning as error:
            named.append(str(error))
    if left:
        raise StillRunning(f"processes outlived their cases: {', '.join(named)}")


@pytest.fixture(scope="session")
def connector_hello(
    pytestconfig: pytest.Config, run_directory: Path, run_processes: list[Process]
) -> Hello:
    """
    The hello of the run's adapter, read once, which says where cases apply.

    Returns:
        The hello.
    """
    manifest = pytestconfig.stash[MANIFEST_KEY]
    assert manifest is not None, "a run with connector cases has an adapter"
    deadline = Deadline.after(CASE_DEADLINE_SECONDS, "reading the adapter's hello")
    with (
        Trace(run_directory / "hello.log") as trace,
        Processes(trace, run_processes) as processes,
    ):
        session = start_adapter("adapter", manifest, processes, trace, deadline)
        session.close()
        return session.hello


@pytest.fixture
def case_run(
    request: pytest.FixtureRequest,
    planned: Planned,
    run_directory: Path,
    run_processes: list[Process],
) -> Iterator[CaseRun]:
    """
    The context of one permutation, with what it applies to checked first.

    pytest applies a test's expected failure to its setup and teardown too, so an
    assertion or a wait of the runner's own that fails there raises
    :class:`~runner.case_run.RunnerFault`, which no expected failure covers.

    Yields:
        The context, which closes everything the case started on the way out.

    Raises:
        RunnerFault: An assertion or a wait failed as the case was set up or ended.
    """
    try:
        hello: Hello | None = None
        manifest: AdapterManifest | None = None
        if planned.run == "server":
            capabilities: frozenset[str] = frozenset()
            transport = _applicable(
                planned, RAW_CLIENT_TRANSPORTS, capabilities, "the raw client"
            )
        else:
            read: Hello = request.getfixturevalue("connector_hello")
            hello = read
            manifest = request.config.stash[MANIFEST_KEY]
            transport = _applicable(
                planned, read.transports, read.capabilities, "the connector"
            )
        directory = run_directory / planned.id
        directory.mkdir(parents=True, exist_ok=True)
        with ExitStack() as stack:
            yield CaseRun(
                planned,
                transport,
                directory=directory,
                stack=stack,
                every=run_processes,
                manifest=manifest,
                hello=hello,
            )
    except EXPECTED_FAILURE_TYPES as error:
        message = f"setting up or ending {planned.id} failed: {error}"
        raise RunnerFault(message) from error


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """
    Add a failed case's trace, its path and its last lines, to its report.

    Args:
        item: The test.
        call: The phase that ran.

    Yields:
        To the hooks that make the report.

    Returns:
        The report.
    """
    report = yield
    run = item.funcargs.get("case_run") if isinstance(item, pytest.Function) else None
    trace = run.trace.path if isinstance(run, CaseRun) else None
    if report.failed and trace is not None and trace.is_file():
        lines = trace.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = "\n".join(lines[-TRACE_TAIL_LINES:])
        report.sections.append((f"trace ({call.when})", f"{trace}\n{tail}"))
    return report


def _plan(config: pytest.Config) -> None:
    # Plans the run once, whichever of the suite's tests asks first.
    if PLAN_KEY in config.stash:
        return
    connector = cast("str", config.getoption("connector"))
    try:
        manifest = manifest_of(connector)
    except UnknownConnector as error:
        raise pytest.UsageError(str(error)) from error
    case_list = config.stash[CASE_LIST_KEY] = load_case_list()
    expected = (
        load_expected_failures(manifest.expected_failures)
        if manifest.expected_failures.is_file()
        else []
    )
    try:
        plan = plan_run(
            case_list,
            connector=connector,
            expected_failures=expected,
            only=cast("list[str]", config.getoption("cases")),
        )
    except UnknownCase as error:
        raise pytest.UsageError(str(error)) from error
    config.stash[PLAN_KEY] = plan
    config.stash[INVARIANTS_KEY] = plan_invariants(case_list)
    config.stash[MANIFEST_KEY] = manifest


def _marks(planned: Planned, listed: Path | None) -> list[pytest.MarkDecorator]:
    marks: list[pytest.MarkDecorator] = []
    if planned.unbuilt:
        marks.append(pytest.mark.skip(reason=unbuilt_reason(planned.unbuilt)))
    expected = planned.expected_failure
    if expected is not None and listed is not None:
        where = listed.relative_to(REPOSITORY).as_posix()
        marks.append(
            pytest.mark.xfail(
                strict=True,
                raises=EXPECTED_FAILURE_TYPES,
                reason=f"listed in {where} as failing: {expected.reason}",
            )
        )
    return marks


def _applicable(
    planned: Planned,
    transports: Collection[str],
    capabilities: Collection[str],
    driver: str,
) -> Transport:
    # The first of the permutation's transports the driver reaches, where it declares
    # every capability the case relies on.
    missing = sorted(planned.case.relies_on - set(capabilities))
    if missing:
        pytest.skip(f"not applicable: {driver} doesn't declare {', '.join(missing)}")
    for transport in planned.transports:
        if transport in transports:
            return transport
    supported = ", ".join(sorted(transports))
    pytest.skip(f"not applicable: {driver} reaches only {supported} here")
