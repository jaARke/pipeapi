# The adapter protocol

The conformance suite ([#5](https://github.com/jaARke/pipeapi/issues/5)) drives each connector through a small program of the connector's own, its adapter. The runner writes commands to the adapter's stdin, the adapter turns each one into a call of its connector's API, and it writes what the connector did to its stdout. One runner and one case list then hold every connector to the [connector API](https://jaarke.github.io/pipeapi/reference/connector-api/).

The schema, [`conformance/adapter-protocol/v1/adapter-protocol.schema.json`](../../conformance/adapter-protocol/v1/adapter-protocol.schema.json), defines every message and field, and this page links it rather than restating them. [The examples](#examples) are transcripts of whole sessions, which the conformance project's tests validate against the schema. This page says what the protocol guarantees, how an adapter runs, how the protocol is framed and versioned, what each message does, its limits, and why it's built this way.

## What it guarantees

| To | The adapter protocol guarantees |
| --- | --- |
| The runner | That every connector takes the same commands and reports in the connector API's own shapes, so each case is written once |
| The runner | That each command gets exactly one reply, and that a fault of the runner or the adapter is never mistaken for the connector's behavior |
| A connector's author | That an adapter only maps commands onto the connector's API: the runner runs a case only on a transport the adapter's hello declares, and only when the hello declares every capability the case relies on, and an adapter refuses a command it has nothing to call for |
| Older connectors ([#23](https://github.com/jaARke/pipeapi/issues/23)) | That the runner keeps speaking the version an older connector's adapter speaks |

## Running an adapter

- **Where it lives.** Each connector keeps its adapter in its own package directory, built by its own toolchain, with an `adapter.yaml` beside it that names the connector, the command that starts the adapter and its working directory, as [`manifest.schema.json`](../../conformance/adapter-protocol/manifest.schema.json) defines. A run names a connector, and the runner starts, without a shell, the command of the `adapter.yaml` among the repository's files that names it.
- **Its environment** is the one the case sets, such as proxy variables or a prefixed endpoint, with the conformance project's environment's scripts directory first on PATH, as `uv run` puts it, so no command sets the environment.
- **Its streams.** stdin carries the runner's commands, stdout the adapter's messages, and stderr the adapter's diagnostics, as free text.
  - Nothing else goes to stdout. An adapter takes the process's stdout for the protocol before it loads its connector, and points its language's standard output at stderr, so a stray print becomes a diagnostic rather than a broken line. It writes stdout in binary mode, since a text stream on Windows ends lines in CRLF.
  - The runner keeps stderr in the case's trace, and once a case passes it searches every file the case wrote, the trace and each backend's output, for the case's token, as `invariant.no-token-in-output` has it, so an adapter never writes a command, or anything from one, to stderr.
- **Its end.** At the end of its stdin, an adapter exits at once with status 0, without waiting for the calls under way or closing its `Backend`s, so the runner closes first what a case needs closed. To kill a client, the runner kills its adapter hard, and the backends it spawned must keep running, as the cases of a spawning client killed while another holds a lease require. So an adapter ties no other process's life to its own: no kill-on-close job object on Windows, no parent-death signal on Linux, no process group it ends on exit. A connector that did would fail those cases.

## Framing

Each message is one JSON object, with no name twice and no NaN or Infinity, in UTF-8 without a byte order mark, on one line that ends in LF, with no CR before it, as the protocol's lease stream is. JSON can't hold a raw line feed inside a string, so a message written without indentation is one line, and needs no length. Bytes travel as `text` when they are UTF-8, and in `base64` otherwise. Each side writes a message whole, so lines from calls running at once never interleave.

## Versioning

A version of the protocol is a directory, `conformance/adapter-protocol/v<n>/`, holding its schema and its examples.

- **Negotiation.** The adapter's hello names the one version it speaks, in `adapterProtocol`. The runner speaks every version in the directory; on a hello that names another, it stops the adapter and fails the run, naming the version the hello gave and those it speaks. An adapter speaks the version of its connector's release, while the runner, built from the repository's head, speaks every version a supported release's adapter might, so #23 runs an older connector through the version its adapter's hello names.
- **Additions.** From the first connector release that includes its adapter, the version that adapter speaks changes only by addition: a new command, event, optional field or capability. A field a version gains is never required, so an older adapter's messages still validate, and the runner sends a newer command or field only to an adapter whose hello declares the capability it came with.
- **Status.** Each version's schema states its status in `x-status`: `draft` until the first connector release that includes an adapter speaking it, which sets it to `released`. `just lint` then fails on a change that removes one of its names, which are its commands, events, capabilities, refusal codes, vias, sinks and kinds of language error, as [Freezing](../../protocol/README.md#freezing) says; review holds the rest of the rule for additions, such as a new field that is required.
- **A breaking change,** such as a removed or renamed field, a new required field or a changed meaning, starts the next version's directory, and the earlier one stays while the runner runs any release whose adapter speaks it.

## Messages

Every message has a `type`: a `command` goes to the adapter's stdin, and a `hello`, a `reply` or an `event` comes from its stdout.

### The hello

The adapter writes the hello once it has loaded its connector, before it reads a command, and the runner sends nothing before it reads the hello. The hello names the protocol version, the connector and its version, the adapter's PID, the transports the connector supports on this platform, and the optional capabilities the adapter offers. The PID is the client process's, which a case expands `{pid}` with, kills hard and compares with what the backend sees. It is the process the runner started or a descendant of it, such as the interpreter a virtual environment's launcher runs, and the runner refuses any other as an adapter fault. A connector that fails as it loads fails before its hello, which is how a case shows that an unsupported transport fails only when `connect()` runs.

A case that relies on a capability is skipped as not applicable when the hello doesn't declare it. The schema's `capability` describes each: an Electron integration, an optional native piece the adapter can run without, reading the PID of a pipe's or a socket's other end, opening pipes at identification level, and the typed client.

### Commands and replies

- **Correlation.** The runner gives each command an `id`, which it never reuses with the same adapter. The adapter answers each command with exactly one reply, which carries the command's `id` and its name, once the call it made has returned or failed, and after every event of that call. What a WebSocket or a dialed connection reports belongs to the connection, not to a call: its events follow the reply of the command that opened it, and aren't ordered against any other command's reply, so an echo of a `websocket_send` may come before or after that command's reply.
- **Concurrency.** The adapter reads each command as it arrives, whatever is under way, and runs its calls concurrently, so a call that waits never holds up the next command: a case can cancel it, or send other requests beside it.
- **Handles.** A `Backend`, a request, a dialed connection and a WebSocket are each named by the ID of the command that opened it, in a field named for its kind: `backend`, `request`, `connection` or `socket`.
- **Names pass through.** An error's code, an event's type and a log event's name are the strings the connector carries, never a translation of a language's member, so the cases test the connector API's [names in each language](https://jaarke.github.io/pipeapi/reference/connector-api/#names-in-each-language). Fields are spelled as the connector API's file spells them, and the schema refers to its definitions: it closes each union it refers to with `unevaluatedProperties: false` beside the reference, and the two kinds of options are closed by their own `additionalProperties: false`, so a field the connector API doesn't define fails validation.
- **No partial calls.** An adapter refuses a command it can't carry out as written, such as one with an option its connector doesn't take, rather than making the call without part of it.

A reply holds exactly one outcome:

| Outcome | The call |
| --- | --- |
| `result` | Returned. What it holds depends on the command, as the schema's `reply` says. |
| `error` | Failed with one of the connector's errors, in the connector API's shape, with the error's message. |
| `languageError` | Failed with an error of the language's own: the cancellation `cancel` fired, the request's own timeout, or any other. Its `kind` says which, for the case to judge; its type's name and its message are for the report. |
| `refusal` | Wasn't made. `unknown_command`, `invalid_command` (including a line that isn't a command, answered with a null `id`) and `adapter_error` are faults of the runner or the adapter, so the runner fails the case as such, never as its expectation, and an expected failure never covers one. |

The commands, whose fields the schema's `command` holds:

| Command | The adapter |
| --- | --- |
| `connect` | Calls `connect()` with the options and a cancellation signal. It turns the connector's logging on from the level given, and supplies sinks of its own for output streams the case names. |
| `close`, `shutdown` | Calls the `Backend`'s `close()` or `shutdown()`. |
| `read_backend` | Reads the `Backend`'s `clientId`, and the values of the headers a request on a dialed connection carries. |
| `request` | Sends a request through the untyped request or the primitive, with a whole body, a form the language's own encoder builds, or a streamed body; with request options; with the language's own timeout; and, when asked, applies `ValidationError` to the response. |
| `body_chunk`, `body_end` | Feeds a request's streamed body. |
| `typed_request` | Calls an operation of the client generated from the reference app's schema, which it builds on the `Backend`'s primitive as `connect()` returns, so a call after a respawn uses the client built before it. |
| `sse` | Sends a GET request and iterates its response with the SSE helper. |
| `dial`, `connection_write`, `connection_close` | Calls `dial()`, reads the connection until it ends, writes to it and closes it. |
| `websocket_open`, `websocket_send`, `websocket_close` | Opens a WebSocket through the path its connector's documentation gives, sends text and binary messages on it, and closes it. `websocket_close`'s reply comes once the library's close call returns, before or after the `websocket_closed` event that reports how the WebSocket closed. An adapter whose library always sends a close code refuses a `websocket_close` without one. |
| `stdin_write`, `stdin_close` | Writes to and closes the stream the `Backend` exposes for a piped stdin. |
| `sink_resume` | Lets a sink that stalled read again. |
| `cancel` | Fires the cancellation signal of a call under way. The cancelled command still gets its reply, with whatever its call then gave. A `cancel` of a command whose call has ended does nothing and returns, and one naming an ID the runner never sent is refused. |

### Events

The adapter writes each event as soon as it has it, so the order on its stdout is the order in which it saw things happen. [Correlation](#commands-and-replies) says how events are ordered against replies.

| Event | Reports |
| --- | --- |
| `started` | That a call is under way: the adapter has made it, or is about to make a call that blocks until its result. A case uses it as a barrier, such as for a request issued while the `Backend` reconnects. |
| `lifecycle` | A lifecycle event the `Backend` emitted. |
| `log` | A record the connector logged, at or above the level `connect` turned on, with its message. Its `name` tells which `Backend` logged it, since some languages' logging mechanisms are global. |
| `output` | What a spawned backend wrote to a sink the adapter supplied: one that collects, or one that stalls until `sink_resume`. |
| `response`, `response_chunk` | A request's status and headers once they arrive, then its body as the adapter reads it. |
| `sse_event` | An event the SSE helper gave. |
| `connection_data`, `connection_end` | What the adapter read from a dialed connection, and the end of its reading. |
| `websocket_message`, `websocket_closed` | A message a WebSocket received, and how it closed. |

## Examples

Each file in [`conformance/adapter-protocol/v1/examples/`](../../conformance/adapter-protocol/v1/examples/) is one session, as the merged lines of the adapter's stdin and stdout:

- [`connect-and-request.jsonl`](../../conformance/adapter-protocol/v1/examples/connect-and-request.jsonl): spawning a backend with logging on, one request and `close()`.
- [`connect-failures.jsonl`](../../conformance/adapter-protocol/v1/examples/connect-failures.jsonl): `connect()` failing with an invalid option, with nothing at the endpoint and on an unsupported transport, and being cancelled.
- [`lease-loss.jsonl`](../../conformance/adapter-protocol/v1/examples/lease-loss.jsonl): a lease that drops while a request waits for ready, the `Backend`'s values before and after, and `shutdown()`.
- [`streamed-body.jsonl`](../../conformance/adapter-protocol/v1/examples/streamed-body.jsonl): a request whose body the runner feeds in chunks.
- [`sse-cancel.jsonl`](../../conformance/adapter-protocol/v1/examples/sse-cancel.jsonl): an SSE iteration that the runner cancels.
- [`dial.jsonl`](../../conformance/adapter-protocol/v1/examples/dial.jsonl): a hand-written request on a dialed connection.
- [`websocket.jsonl`](../../conformance/adapter-protocol/v1/examples/websocket.jsonl): a WebSocket's echoes and its close.
- [`stdio.jsonl`](../../conformance/adapter-protocol/v1/examples/stdio.jsonl): a piped stdin, a collecting sink and a stalled one.
- [`typed-client-and-validation.jsonl`](../../conformance/adapter-protocol/v1/examples/typed-client-and-validation.jsonl): the typed client, and `ValidationError` on a validation error and on another 422.
- [`refusals.jsonl`](../../conformance/adapter-protocol/v1/examples/refusals.jsonl): the baseline adapter refusing a command it doesn't know and a handle that names nothing.

`just conformance::check` validates each line against its version's schema, and checks that each session opens with the hello and answers each command once, that the examples show every command, event and outcome, that each typed request names an operation of the reference app, and that each `Backend`'s lifecycle events keep the connector API's order.

## Limits

- **stdin and stdout `inherit` aren't covered.** An inherited stdin would read the runner's commands, and an inherited stdout would write into the adapter's messages, so the schema refuses them in `connect`, and each package's own tests cover them. stderr's `inherit` is covered: the backend's lines appear on the adapter's stderr.
- **`started` says only that a call is under way,** not how far the connector has taken it, since the adapter sees the call from outside. A case that needs more waits for an observation after it, such as a log record or the app's own record of a request.
- **Timing passes through the adapter.** An event reaches the runner after the adapter and a pipe, so a case checks a duration as a lower bound, or measures it where it happens, at the fake server or in the app's log.
- **A global logging mechanism,** such as Python's `logging` or Rust's `log`, can't hold two `Backend`s at different levels, so in such a language the most verbose level any `connect` asked for applies to every `Backend`.
- **Typed operations are named by the reference app's schema,** by their `operationId`, and each adapter generates its client from that schema with its language's generator, so changing an operation's ID changes every adapter's client.
- **The connector API is today's.** The schema refers to the connector API's file as it stands in the repository, so an older connector's adapter is checked against today's definitions. Once released, the connector API keeps only its identifiers: its error codes, event types and reasons for a lost `Backend` are only added to, but a member may gain a required field, so an older connector's messages may not validate against today's definitions. Running older connectors ([#23](https://github.com/jaARke/pipeapi/issues/23)) needs each validated against the schemas of its connector's release. An option added since a release reaches that release's adapter as a command it can't carry out, which it refuses.

## Why it's built this way

The runner drives an adapter rather than running a suite in each language, since the process cases, such as killing a client or running two at once, need a client program per language either way, and the cases are then defined once, for every connector. The protocol takes from the conformance and adapter protocols closest to it:

| Prior art | Taken | Left |
| --- | --- | --- |
| [Connect RPC's conformance suite](https://github.com/connectrpc/conformance/blob/main/docs/testing_clients.md) | A program per implementation, driven over stdin and stdout, which needs no port or readiness check of its own and ends when its input does; results written as they complete, in any order, and matched to their requests | Protobuf messages with a four-byte length prefix, since pipeapi's contract is JSON throughout; and cancellation described inside a request, since pipeapi's cases cancel in answer to what they observe |
| The [Debug Adapter Protocol](https://microsoft.github.io/debug-adapter-protocol/specification) | Requests, responses and events as the three kinds of message; a response that names its command; a cancelled request that still gets its response; features added within a version as capabilities | `Content-Length` headers, which JSON lines don't need; and a protocol without versions, since a breaking change needs a version that #23 can tell apart |
| [JSON-RPC](https://www.jsonrpc.org/specification), as the [Language Server Protocol](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) frames it | An ID the requester gives, which the response carries; a refusal of its own for an unknown method; a null ID for a message that can't be read | Its envelope and numeric error codes, since the connector API's names apps match on are snake_case strings, and so are the adapter protocol's |
| [Datadog's system-tests](https://github.com/DataDog/system-tests/blob/main/docs/understand/scenarios/parametric.md) parametric apps | One interface that a small app in each language implements, behind one set of tests shared by every language | An HTTP server per language, which takes a port and a readiness check of its own, and can't send the unprompted events a `Backend` emits without a stream; and an interface defined by its reference implementation's OpenAPI document, which its documentation says not every language follows |

- **The connector API's shapes by reference.** Options, request options, lifecycle events, errors and log records come from [`connector-api.schema.json`](../../protocol/connector-api/connector-api.schema.json) by `$ref`, closed as [Names pass through](#commands-and-replies) says, so the adapter protocol restates none of them, and every shape an adapter reports is checked against the definitions apps rely on.
- **Handles are command IDs,** so a session has one kind of name, and a transcript reads with each resource beside the command that opened it.
- **The adapter speaks first.** Its hello is also its readiness, and it carries what the runner needs before it chooses which cases apply.
- **An adapter speaks one version, the runner every one.** The runner is built from the repository's head, so an adapter never meets a runner older than itself, and only the runner needs to know the older versions.
- **Refusals stand apart from failures,** so a runner or adapter bug can't pass as a connector's expected failure, nor fail a case as if the connector were wrong.

Rejected:

- **The channel on descriptors other than stdin and stdout,** which would let a case prove stdin and stdout `inherit`. Python's `subprocess` passes a child further descriptors, through `pass_fds`, only on POSIX. On Windows a child can inherit further handles, but Node's standard library can't open an inherited handle as a stream, nor duplicate a descriptor to move its own channel, so an adapter in every language couldn't do it on every platform.
- **HTTP between the runner and the adapter,** for the reasons Datadog's row gives.
