# Conformance cases

Each conformance case is defined once, in the case list, and implemented once, in the runner. This page says how a case is defined and changed, and how it's implemented. [Running the suite](running.md) says where each case runs and what its results mean.

## The case list

[`cases/cases.yaml`](../../../conformance/cases/cases.yaml) defines every case once, grouped by area, with the invariants every case checks, which the runner checks as [its design](design.md#why-its-built-this-way) says, and the anchors of the spec no case covers; [`cases.schema.json`](../../../conformance/cases/cases.schema.json) beside it describes each field. The guide site's [conformance cases](https://jaarke.github.io/pipeapi/reference/protocol-v1/conformance/) page renders them, and maps every section and table row of the spec to the cases that cover it.

- **IDs.** A case's ID is its area's name, a period, then its own name, both in lowercase kebab-case, such as `endpoint.invalid-refused`. The transport, the platform and the connector are never part of it.
- **Adding or changing a case.** Add it under its area with its expectation, its kind, where it runs, the components it needs and the anchors it covers. A case whose rule no page states yet names the issue whose design it follows. Run `just lint`, which validates the files against their schemas and compares the cases with `main`; `just conformance::check`, whose `tests/test_cases.py` checks the rules a schema can't, each by name, such as an ID outside its area or a need the component table lacks; and `just docs::check`, which fails on a citation that doesn't resolve and on a section or row of the spec that no case covers and `uncovered` doesn't explain.
- **Components.** [`cases/components.yaml`](../../../conformance/cases/components.yaml) lists what cases need beyond the connector under test, each with the issue that builds it and whether it's built; the runner skips a case until each component it needs is built, and an invariant until each component its `needs` names is, and the issue that builds a component sets its `built` to true. A case never lists what its backends imply: pipeapi's server and its listener on the case's transport for a case that talks to the reference app, and the fake server for one that talks to it.
- **Expected failures** are each connector's own, beside its adapter, as [Adapters](adapters.md#expected-failures) says.
- **The freeze.** Once protocol v1 is released, a case's ID, expectation, kind and where it runs never change, as [protocol/README.md](../../../protocol/README.md#freezing) says, and changed behavior is a new case.

## Implementing a case

A case's implementation is a function in `runner/implementations/`, in the module named for the case's area, such as `request.py` for the `request` area. The `implements` decorator from `runner/registry.py` names the case it implements by its ID, and the runner imports every module of the package, so a new module needs nothing more. The function takes the permutation's `CaseRun`, sets up the case and checks its expectation.

- **Implemented once.** A case has at most one implementation, and every implementation names a case the list defines; `tests/test_cases.py` fails on either mistake by name. A case can be implemented before the components it needs are built, and is skipped until they are. A case whose components are all built but which no implementation names fails, so the issue that builds a case's last component implements it.
- **Then the invariants.** Once the implementation returns, the runner ends the case's clients and checks the invariants, so an implementation ends no client itself and checks no invariant.
- **An invariant's check** is a function of `runner/invariants.py`, in its `CHECKS` under the invariant's ID, which takes the permutation's `CaseRun` and checks what the case left behind, such as its clients' transcripts or its files. `tests/test_cases.py` fails on a check that names no invariant, and a run fails on an invariant whose components are all built but which no check names, so the issue that builds an invariant's last component checks it.
- **Expectations.** Write each check as a plain `assert`. pytest rewrites the implementations' assertions, so a failure shows the values compared, and a note added to the failure with `add_note()` gives it context. An `AssertionError` is the case's own failure, the one an expected failure covers, so an expectation that doesn't hold raises nothing else. A reply's `result()` raises one when the call failed instead.
- **What it reads of the app.** The reference app's own models, such as `Seen` in `reference_app/routers/requests.py`, read its answers, through a response's `answer()`, so a case and the app share one definition of each answer.

### The case run

`CaseRun`, in `runner/case_run.py`, is what an implementation works with. Everything a case starts through it closes on every path out of the case, so an implementation closes none of it.

| Member | Gives |
| --- | --- |
| `app()` | A backend serving the reference app, once it serves. In the baseline run it's the app under plain uvicorn on loopback; in any other run it fails, since a case there reaches the app through pipeapi's server, which the runner doesn't start. The backend's observation log is the case's view of the app. |
| `client(changes)` | A client: an adapter of the run's connector, once its hello has come, started with the changes given to its environment, such as proxy variables. Each call starts another. |
| `clients` | Each client the case started, in order. |
| `connect(client, app)` | `connect()` on the client, with the backend's endpoint and the case's token. It returns the `Backend`'s handle. |
| `fake(script, token)` | The fake server, answering as its script says, on the permutation's transport: loopback TCP, or a Unix domain socket on POSIX. |
| `transport`, `via` | The permutation's transport, and what its requests go through. Every request passes `via=run.via`, so a case that varies by it runs each way. |
| `deadline` | The case's deadline, which every wait in the case takes. |
| `token` | The token the case's backends and clients share. |
| `trace` | The case's trace, for records of the case's own. |

The rest of the runner's surface for cases:

- `runner/adapter_session.py`: a client's session, with its commands and their replies, its events and the waits for them, requests and their responses, its transcript, and killing the client hard.
- `runner/uvicorn_server.py`: the backend `app()` returns, with its endpoint, its observation log and the waits on it, and stopping or killing it.
- `runner/fake_server.py`: the fake server's scripts, such as a hello with a mistake in its proof, a rejection or a lease's lines, and what it recorded.
- `runner/raw_client.py`: the raw client a server case drives pipeapi's server with, which checks every response against the protocol's OpenAPI document.
- `runner/listeners.py`: a loopback listener that records each connection, for a case that shows nothing connects, such as to a proxy.
- `runner/proofs.py`: tokens and proofs, with the mistakes the protocol's vectors name.

### Timing

A case never sleeps to let something happen. A sleep long enough for a loaded CI runner is slow everywhere else, and a shorter one flakes. A case waits for an observation instead:

- an adapter's reply or event, through the session's `reply()` and `wait_for_event()`, where the `started` event says a call is under way;
- a record in a backend's observation log, through its `wait_for()`, such as the `disconnect` a client leaves behind;
- a request the fake server recorded, or a lease stream standing as the case needs, through `wait_for_request()` and `wait_for_lease()`;
- the reference app's barrier route, `/barrier/{name}`, whose answers show that requests were in flight together.

A case checks an absence, such as no further request or no event, once it observes a control that would have shown it by then, as `expectation` in [`cases.schema.json`](../../../conformance/cases/cases.schema.json) says, and the session's `events(before=…)` takes what came before a control event. A case orders the other side after what it observed: the fake server writes a lease line that waits for a cue only once the case gives it with `cue()`. The session's waits take the case's deadline themselves, and a case passes `deadline=run.deadline` to the backend's and the fake server's, so the case ends by its deadline whichever wait it's in. A duration is checked as a lower bound, or measured where it happens, as the adapter protocol's [limits](../adapter-protocol.md#limits) say. A case that lasts 15 seconds or more by design, since a fixed duration must pass, such as one of the protocol's durations or an HTTP library's read timeout, is marked `slow`, which gives it a longer deadline.
