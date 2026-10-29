# Adapters and connectors

The runner drives each connector through its adapter, a small program of the connector's own that speaks the [adapter protocol](../adapter-protocol.md). This page says how the runner finds, starts and ends an adapter, how a connector lists the cases it's known to fail, and what adding a connector to the suite takes. The adapter protocol's page owns the messages, and what an adapter does with its streams and at its end.

## The manifest

An adapter's `adapter.yaml`, in the directory that holds the adapter, names the connector, the command that starts the adapter and its working directory. [`manifest.schema.json`](../../../conformance/adapter-protocol/manifest.schema.json) defines each field, and how the command's program is found. The baseline's, [`baseline_adapter/adapter.yaml`](../../../conformance/baseline_adapter/adapter.yaml), is an example.

- **Finding it.** A run names a connector, and the runner reads every `adapter.yaml` among the files Git tracks or would track, so a manifest in an ignored directory, such as a build's output, is never found. Two manifests that name one connector fail the run and the conformance project's tests, and a run that names a connector no manifest names stops, listing the names they give.
- **Starting it.** The runner starts the command without a shell, in the manifest's working directory, with the runner's environment and the changes the case makes to it. It builds nothing, so the adapter is built before the run, by its connector's own toolchain.
- **PATH.** `uv run` puts the conformance project's environment's scripts directory first on PATH, and the runner does the same for an adapter whichever way it was started: it looks there first for a program the command names without a slash, and puts it first on the adapter's PATH. The baseline's `python` relies on it, so the baseline's cases run alike under the recipes and under an editor's test explorer, which runs the environment's interpreter directly.
- **Its hello** must name the manifest's connector, and a PID that is the process the runner started or a descendant of it, such as the interpreter a virtual environment's launcher runs. A hello that names another connector or another process fails as an adapter fault. Before the first connector case, the runner starts the adapter once to read its hello, whose transports and capabilities decide where each case applies, as [Running the suite](running.md#results) says. That start's trace is the run's `hello.log`. Each case then starts an adapter of its own for each client, so an adapter that starts slowly slows every case.

## Its end

What an adapter does [at its end](../adapter-protocol.md#running-an-adapter) is the adapter protocol's: at the end of its stdin it exits at once with status 0, and it ties no other process's life to its own. The runner holds it to that:

- Once a case's implementation passes, the runner ends the stdin of each client the case started, waits for it to exit within a hang guard, then reads its stdout to the end, before it checks the invariants. A client that exits with another status, or doesn't exit in time and is then killed, fails the case as an adapter fault, and so does a line that breaks the adapter protocol which no wait in the case raised, such as one after the last reply that breaks the schema. After a case that failed, the runner ends its clients the same way, and such a fault is an error beside the case's failure. A client the case killed isn't waited for, and nor is one whose stdin a write was stuck on, which the runner kills first, since the write holds the stream until it fails. Their lines count all the same, except a last line the kill cut short.
- To kill a client, the runner kills the process its hello's PID names, hard, and only that process, as [the runner's design](design.md#ending-processes) says, then the process it started, if that still runs once the client has ended. Cases such as `topology.spawner-exits` kill a spawning client while another holds a lease, and need its backend to keep running, so a connector that ties its backends to the client fails them.

## Expected failures

Each connector keeps the cases it's known to fail in an `expected-failures.yaml` beside its `adapter.yaml`, keyed by case ID. Each entry gives its reason, naming the issue that tracks the fix, and may narrow the entry to the permutations it fails on; [`cases/expected-failures.schema.json`](../../../conformance/cases/expected-failures.schema.json) defines its fields, and `just lint` validates the file against it.

- **The list is strict.** A listed permutation that passes fails the run, as `[XPASS(strict)]`, with the file and the reason, so an entry comes off in the change that fixes its case.
- **It covers only the case's own failure,** as the case runs: an `AssertionError`, a contract violation among them, or a deadline that passed while the case waited on the connector. Any other error, such as an adapter fault, fails a listed case all the same, since it's a fault of the runner or the adapter rather than the connector's behavior, and so does an assertion or a wait of the runner's own in setting up or ending the case, which raises `RunnerFault`.
- **It's checked.** `tests/test_cases.py` fails on a file beside no `adapter.yaml`, and on an entry that names no case, a server case, or none of its case's permutations.

## Adding a connector

What the suite asks of a new connector, beside what [a new project](../repository.md#adding-a-project) adds to the repository:

1. Implement the [connector API](https://jaarke.github.io/pipeapi/reference/connector-api/), the surface every connector offers, whose design [The connector API](../connector-api.md) records.
2. Write the connector's adapter in its package directory, built by the connector's own toolchain and speaking the [adapter protocol](../adapter-protocol.md). Its hello declares the transports the connector supports on the platform, and the capabilities the adapter offers. An adapter that offers the typed client generates it from the reference app's schema, whose operation IDs [the reference app](reference-app.md#routes) keeps fixed.
3. Add the adapter's `adapter.yaml`, naming the connector.
4. Build the adapter, then run `just conformance::run <connector>`, which runs the connector cases through it. The server cases run only in the baseline's run.
5. List each case the connector fails in its `expected-failures.yaml`, naming the issue that tracks the fix, until the run passes.
