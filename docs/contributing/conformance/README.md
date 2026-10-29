# The conformance project

`conformance/` is the conformance project ([#5](https://github.com/jaARke/pipeapi/issues/5)). It holds the conformance suite: the cases, defined once; the runner, which runs them against one connector at a time through the connector's adapter; the baseline adapter; and the reference app, a FastAPI app whose routes and settings give the cases something to exercise and observe. Its tests check its own parts, and also the protocol's files: the test vectors, through a second implementation of their rules, and the examples of streams in each `openapi.yaml`, against their item schemas. It's a Python project that follows the [Python projects](../python.md) conventions, whose import contracts keep its packages apart.

| Directory | Holds |
| --- | --- |
| [`cases/`](../../../conformance/cases/) | The case list, the component table, and the schemas of both and of a connector's expected failures |
| [`adapter-protocol/`](../../../conformance/adapter-protocol/) | Each version of the adapter protocol, with its schema and its examples, and the schema of an adapter's manifest |
| [`reference_app/`](../../../conformance/reference_app/) | The reference app |
| [`runner/`](../../../conformance/runner/) | The runner, a pytest plugin, with the cases' implementations in `runner/implementations/` |
| [`baseline_adapter/`](../../../conformance/baseline_adapter/) | The baseline adapter, a plain HTTP client with proxies off, and its `adapter.yaml` |
| [`tests/`](../../../conformance/tests/) | The project's tests |
| `traces/` | The runner's traces, which Git ignores |

## Commands

| Command | What it does |
| --- | --- |
| `just conformance::check` | Checks the project as a pull request must, the suite's baseline run among its tests |
| `just conformance::fix` | Applies ruff's fixes and formatting |
| `just conformance::run <connector>` | Runs the suite against one connector, by the name its `adapter.yaml` gives; `baseline` runs the baseline's run |
| `just conformance::case <id> [connector]` | Runs one case, by its ID, against one connector, the baseline unless one is named |

[`conformance/justfile`](../../../conformance/justfile) holds each recipe, and CONTRIBUTING.md's [prerequisites](../../../CONTRIBUTING.md#prerequisites) say what each needs.

## Pages

- [Conformance cases](cases.md): the case list, how to add or change a case, and how to implement one.
- [Running the suite](running.md): what a run holds, how to run it, what each result means, and how to read a failure from its trace.
- [Adapters and connectors](adapters.md): how the runner finds, starts and ends an adapter, a connector's expected failures, and what adding a connector takes.
- [The reference app](reference-app.md): how a runner starts, observes and stops the app, its settings, its observation log and its routes.
- [The runner's design](design.md): what the runner guarantees, why it's built this way, the prior art, and its limits.

The [adapter protocol](../adapter-protocol.md), which the runner and every adapter speak, has a page of its own.
