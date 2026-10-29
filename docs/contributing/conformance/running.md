# Running the suite

The conformance runner is a pytest plugin in `conformance/runner/` that runs the [case list](cases.md#the-case-list) against one connector at a time. This page says what a run holds, how to run it, what each result means and how to read a failure.

## Runs

A run names a connector, by the name its [`adapter.yaml`](adapters.md#the-manifest) gives, and collects every permutation of the cases that run for it on this platform:

| Run | Its cases |
| --- | --- |
| The baseline's, for the connector named `baseline` | The server cases, through the runner's raw client against pipeapi's server; and the connector cases marked `baseline`, through the baseline adapter against the reference app under plain uvicorn, on loopback TCP |
| A connector's | Every connector case, through the connector's adapter |

The server cases run only in the baseline's run, so no connector's run repeats them. A case runs once on each transport it applies to, or once in all for a case marked `once`, and once for each way of requesting that it varies by. A permutation's ID is the case's ID, then its transport unless the case runs once, then what its requests go through if it varies by that, such as `request.head-tcp-untyped`.

Every run also holds a test for each [invariant](cases.md#the-case-list), by its ID, such as `test_invariant[invariant.event-order]`, which says whether the runner checks the invariant in each case.

## Running it

The conformance project's [commands](README.md#commands) run the suite against one connector, or run one case, in the project's environment. `just conformance::check` runs the baseline's run among the project's tests, as CI does.

The recipes run pytest over `runner/` with the runner's options: `--connector <name>`, which defaults to the baseline, and `--case <id>`, which may repeat. pytest's own options apply when pytest runs from `conformance/` through uv, such as `uv run --locked pytest runner --connector <name> -x`. One permutation runs by its test's ID, such as `uv run --locked pytest "runner/test_conformance.py::test_case[request.head-tcp-untyped]"`. pytest runs in the project's environment, through `uv run` as the recipes do, or through the environment's own interpreter, as an editor's test explorer does; either way the runner finds an adapter's program as `uv run` would, as [Adapters](adapters.md#the-manifest) says.

A case the run doesn't hold, such as a server case in a connector's run, collects nothing, which pytest reports as one skip, "got empty parameter set". A case ID the case list doesn't define, or a connector no manifest names, stops the run before any case runs.

## Results

| Result | Means |
| --- | --- |
| Passed | The case's expectation held, and so did each invariant the runner checks. An invariant's test passes when the runner checks the invariant. |
| Skipped, "needs … not built yet" | A component the case or the invariant needs isn't built, as [`components.yaml`](../../../conformance/cases/components.yaml) says, and the message names each with the issue that builds it. A case that runs once runs on a transport whose components are built, where it has one. |
| Skipped, "not applicable: …" | The adapter's hello doesn't declare a capability the case relies on, or any of the permutation's transports; or, for a server case, the raw client doesn't reach any of its transports on this platform. A permutation on another platform, or on a transport the case doesn't apply to, is never collected. |
| xfailed | The case failed as the connector's [expected failures](adapters.md#expected-failures) say it does. |
| Failed, "[XPASS(strict)] listed in … as failing" | A case the connector lists as failing passed, so its entry comes off. |
| Failed | The case failed in any other way: an invariant that doesn't hold, a client that doesn't exit with status 0 at the end of its stdin once the case's checks pass or that wrote a line breaking the adapter protocol which no wait raised, or a case that runs here, with every component it needs built, that no implementation names. An invariant's test fails when every component the invariant needs is built but `runner/invariants.py` has no check for it. |
| Error | Setting up or ending the case failed, such as an adapter that didn't start, a client that didn't exit at the end of its stdin after the case failed or that wrote a line breaking the adapter protocol which no wait raised, or a process that outlived the run. An assertion or a wait of the runner's own that fails there raises `RunnerFault`. |

## Reading a failure

A failed case's report ends with a section, `trace (<phase>)`, giving the path of the case's trace and its last lines. pytest's traceback above it shows the failing assertion, with the values compared.

### The traces

Each run writes its traces to a directory of its own under `conformance/traces/`, named `<started>-<connector>-<pid>`: when the run started, in UTC, its connector and the runner's PID. Git ignores the directory, and the runner never deletes a run's, so delete old runs by hand.

| Path, in the run's directory | Holds |
| --- | --- |
| `hello.log` | The trace of the adapter's start that read its hello for the run |
| `<permutation>/trace.log` | The trace of one permutation, named by its ID |
| `<permutation>/backend-<n>/observations.jsonl` | The observation log of the case's nth backend, as [the reference app](reference-app.md#the-observation-log) describes it |
| `<permutation>/backend-<n>/stdout.txt`, `stderr.txt` | What that backend wrote |

Each line of a trace is the seconds since the trace began, its source and its text. A case's trace records:

- what the case is, the run and transport it's in, and its deadline;
- each process's start, with its PID, working directory and command, and its exit, or its kill by the runner;
- every line on each adapter's stdin, stdout and stderr, so the adapter protocol's messages read as a session's transcript, as [the examples](../adapter-protocol.md#examples) do, with the case's token shown as `[secret]` in the runner's own commands, so a trace holds the token only where something else wrote it;
- the runner's own steps, such as a backend it ended by its PID.

### What failed

The exception that ended a case says what kind of failure it is:

| Exception | Means | An expected failure covers it |
| --- | --- | --- |
| `AssertionError` | The case's expectation didn't hold, or a call it needed to succeed failed, with the error the call gave. | Yes |
| `ContractViolation` | What a server sent the raw client doesn't meet its protocol version's `openapi.yaml`. It names the operation, the status and the document, and each problem with the place in the document it was checked against. It's an `AssertionError`. | Yes |
| `DeadlinePassed` | A wait on what the connector or the server does, such as a reply, an event, an observation or a lease line, outlasted its hang guard or the case's deadline, as the case ran. It names what the wait was for and which bound passed, with the adapter's last stderr lines when it waited on an adapter. | Yes |
| `AdapterFault` | The runner or the adapter broke the adapter protocol: a line that breaks its schema or its framing, a refusal, a reply to a command it wasn't sent or that names another command, a second reply, a request it says returned without a response, a hello that names another connector, a version the runner doesn't speak or a PID outside the adapter's own processes; or an adapter that wrote no hello or took no command in time, ended early, or didn't exit with status 0 at the end of its stdin. It quotes the adapter's last stderr lines. | No |
| Any other, such as `RunnerFault`, `StillRunning`, `ServerDidNotStart`, `FakeServerFailed` or `ProgramNotFound` | The runner's own work failed, such as an assertion or a wait in a case's setup or ending, a process that outlived its kill, a reference app or a fake server that didn't start, or a manifest's program that isn't there; or, in a server case, a request the raw client sent failed outright, with httpx2's error. | No |

### In CI

CI's conformance job runs `just conformance::check` on Windows, Linux and macOS. When the job fails, or is cancelled, as one that outlasts its time limit is, it uploads `conformance/traces/` as the workflow run's artifact `conformance-traces-<os>`, since a failed case's report names a trace that only the runner's machine holds.
