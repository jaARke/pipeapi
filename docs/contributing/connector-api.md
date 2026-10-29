# The connector API

The connector API is the surface every connector offers the app that uses it, in Node, .NET, Rust, Go and Python alike, each in its language's idiom. Its reference is the guide site's [Connector API](https://jaarke.github.io/pipeapi/reference/connector-api/) pages, which render `protocol/connector-api/connector-api.schema.json`, and [protocol/README.md](../../protocol/README.md#the-connector-api) says how that file is written, how to change it and how it's frozen. [The protocol](protocol.md) says why the wire contract under it is built as it is.

This page says what the connector API guarantees and to whom, why it's built the way it is, and what was rejected. It states none of the reference's rules or values: each reason links the section that holds its rule.

## What it guarantees

| To | The connector API guarantees | Where the reference holds it |
| --- | --- | --- |
| The app | The same capabilities, options, events, errors and log records in every language, each in its idiom | [Conventions](https://jaarke.github.io/pipeapi/reference/connector-api/#conventions), [capabilities](https://jaarke.github.io/pipeapi/reference/connector-api/#capabilities) |
| The app | That a generated client needs no knowledge of pipeapi, and keeps working across a reconnect or a respawn | [Requests](https://jaarke.github.io/pipeapi/reference/connector-api/requests/), [addresses](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#addresses) |
| The app | That a request goes out again only where that is safe, and a stream is never replayed from its start without the app knowing | [Safe retry](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#safe-retry), [server-sent events](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#server-sent-events) |
| The app | That an outage ends in one event that says how it ended, unless the app closes the `Backend` first | [Lease loss](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#lease-loss), [lost](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#lost) |
| The app | That one backend failing leaves its other backends alone | [The Backend](https://jaarke.github.io/pipeapi/reference/connector-api/connecting/#the-backend) |
| Other clients of a shared backend | That a connector starts a backend only in `connect()` or a respawn | [Reconnecting](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#reconnecting), [respawn](https://jaarke.github.io/pipeapi/reference/connector-api/respawn/) |
| A spawned backend | That it never blocks on its output, and never inherits settings or a token meant for another backend | [Draining](https://jaarke.github.io/pipeapi/reference/connector-api/a-spawned-backends-stdio/#draining), [what a spawned backend receives](https://jaarke.github.io/pipeapi/reference/connector-api/options/#what-a-spawned-backend-receives) |
| The user | That a connector's logs never hold the token or a session secret | [Logging](https://jaarke.github.io/pipeapi/reference/connector-api/logging/) |

## Why it's built this way

### One surface in each language's idiom

- **The file spells each name once, and each language spells it its own way,** so a connector reads as native code in its language while every connector offers the same thing. The names apps match on stay exact strings in every language, so an app, a log query or the conformance suite matches the same text whichever connector produced it.
- **The primitive is the language's standard HTTP client,** in the form its code generators already accept. pipeapi owns the transport and the contract, not the client style: it generates no code and ships no typed API ([#1](https://github.com/jaARke/pipeapi/issues/1)).
- **Each connector's issue settles its forms,** such as its event mechanism, its error types and its durations, since what is idiomatic differs by language. The conformance suite drives every connector through a small adapter that speaks the file's shapes ([#5](https://github.com/jaARke/pipeapi/issues/5)), so it checks behavior once for all five. Each package's own tests, its API report ([#2](https://github.com/jaARke/pipeapi/issues/2)) and its example ([#14](https://github.com/jaARke/pipeapi/issues/14)) cover the idiomatic surface.
- **An HTTP status is never a connector's error.** Statuses are the app's, and its generated client already handles them. A connector's errors are the failures only it can see, in transport and lifecycle, each with a stable code.

### The file

- **It's a JSON Schema,** so the conformance adapter's schema refers to its definitions rather than copying them, and the reference pages, the adapter and each connector's tests read options, events and errors from one home. [protocol/README.md](../../protocol/README.md#the-connector-api) says which of its definitions are closed and why.
- **It sits in `protocol/` beside the wire contract but outside any version's directory,** since the two change on different axes. Under a protocol version, an option's name would be tied to the wire: renaming one would take a new protocol version, though nothing on the wire changed. Its freeze follows the packages instead, as the README says.
- **It's hand-written and language-neutral,** rather than generated from Pydantic, zod or another candidate, for the reasons [the machine-readable contract](protocol.md#the-machine-readable-contract) gives.

### Transports and spawning

- **A generated endpoint's transport is an option of its own,** since every endpoint a client is given, port 0 included, names a backend to attach to, so no endpoint can ask for a generated one.
- **`args`, `cwd` and `env`** are options because every language's child-process API and VS Code's languageclient offer them.
- **An unsupported transport fails when `connect()` runs, never at import or compile time,** so an app built once for several platforms imports the connector everywhere and chooses its endpoint at run time, without conditionals of its own.
- **A busy pipe is retried on every connection, not only the first,** since the primitive opens pooled connections whenever it needs one, and any of them can find every instance busy.
- **The reference's [what a spawned backend receives](https://jaarke.github.io/pipeapi/reference/connector-api/options/#what-a-spawned-backend-receives)** says why a connector clears protocol-named variables, prefixed or not, before it sets its own.
- **No console window opens on Windows unless a stream is inherited.** That is libuv's rule for Node's `windowsHide`: a GUI app that starts a console program would otherwise flash a window, and an inherited stream needs the console to share.

### Outages

A connector handles each request by what it knows about that request, rather than queueing requests and replaying them after an outage. The hard case is a request in flight when the backend went away: a `POST` may or may not have run, and replaying it blindly can do its work twice.

- **Wait-for-ready** follows gRPC's option of that name: a request that never left the client can't run twice, so holding it costs only time. Its default differs from gRPC's, which fails fast, since a pipeapi outage is a local backend restarting, which waiting usually outlasts; a request opts out to fail fast.
- **Safe retry** is modeled on Go's `http.Transport`'s rule for replaying a request, and keeps its test of whether a request can run twice: an idempotent method or an `Idempotency-Key` header, and a body it can send again. It's narrower than Go's, since a request nothing of which was written needs no retry here: it waits for ready, or for its connection to open. It applies only before the response's headers arrive, since after them the app has answered, so the request ran whatever its method. A request that may have run fails with an error that says so, and the app decides, since only it knows whether its operation can repeat.
- **A rejected request is resent only after the two rejections a newer lease cures.** Every rejection is safe to resend, since the app never saw the request, but any other would get the same answer again.
- **A stream resumes only from an event with an ID,** as a browser's `EventSource` resumes with `Last-Event-ID`, so an app opts in by giving its events IDs. It waits before resuming, as `EventSource` does, so a backend that is restarting isn't met with a burst of requests. A resumed stream that fails before a new event fails the iteration, since a stream that dies the same way each time would otherwise resume forever. A WebSocket is never reopened, since it has no such resume point, and a reopened socket would silently lose whatever state the app kept on it.
- **Reconnecting only attaches.** A backend that went away was stopped, is restarting, or crashed. A connector that spawned on reconnect would undo a stop someone asked for, could take the endpoint from a backend that is restarting, and would restart a crash it never saw. Respawn is the one exception: only the client that saw the exit restarts the backend, within limits. Reusing the resolved endpoint and token keeps the app's typed client working, as [addresses](https://jaarke.github.io/pipeapi/reference/connector-api/lease-loss-and-outages/#addresses) says.
- **An outage ends in exactly one of `reconnected`, `respawned` or `lost`,** so an app that shows it always learns how it ended, and its state has no dangling case.
- **`close()` ends an outage at once, and no event follows it,** since the app has let the `Backend` go, and an event then would run the app's handlers during its teardown.
- **Requests already written when the `Backend` is lost finish or fail on their own connections,** since a connection still open may yet carry the app's response, and failing the request early would throw that away.
- **`lost` carries a reason,** so an app can tell a revocation, which it shouldn't retry, from a crash or a requested stop, and show the user the right one.
- **`shutdown()` ends the caller's own lease as it ends every other client's,** rather than acting as `close()`. The server ends every lease alike when it stops, so the app handles one outcome, `lost` with the reason `shutdown`, whichever client asked.

Rejected:

- **A general request queue, replayed after reconnect.** It would send again requests the app may already have processed.

### Respawn

Respawn is part of the shared API, rather than left to each app to build on `lost`, since it reuses what only the connector reaches: waiting requests, safe retry, stream resume, and a primitive that survives. An app that called `connect()` again itself would see its waiting requests fail, get a new `Backend`, and rebuild its typed client on the new primitive.

- **Its default** has the reason the reference's [respawn](https://jaarke.github.io/pipeapi/reference/connector-api/respawn/) gives, and prior art agrees: VS Code's languageclient restarts by default only because language servers hold no state, and systemd's default is not to restart.
- **Only the spawning client respawns, and only after an unexpected exit,** which is supervisord's `autorestart=unexpected`. A clean exit is a stop someone asked for.
- **The limits have known shapes:** a number of restarts within a window, as Erlang/OTP supervisors and VS Code's languageclient count them, and a wait that doubles to a cap and starts over after a stable run, as Kubernetes backs off a container that keeps crashing. Each is an option, since how long a backend takes to start differs by app.
- The reference's [concurrent respawns](https://jaarke.github.io/pipeapi/reference/connector-api/respawn/#concurrent-respawns) says why several clients can't respawn one backend twice.

### Output and logging

- **A spawned backend's output goes to the connector's log by default,** as VS Code's languageclient and Playwright forward a child's output to their own logs. A GUI app has no console, so output with nowhere to go would be lost exactly when the backend fails.
- **Output is always drained, through a bounded queue that drops and logs rather than blocking.** A backend blocked on a full pipe stops serving every client, so a lost line costs less than a hung backend, and the bound keeps a stalled destination from growing memory without limit.
- **Each language logs through its own mechanism,** so the app routes and filters pipeapi's records as it does its own, and no logging library becomes a requirement ([#1](https://github.com/jaARke/pipeapi/issues/1)). Each connector's issue settles which.
- **Every connector logs the same events at the same levels,** so a log reads alike whichever connector wrote it.
- **Silent by default,** since a library writes to an app's output only when the app asks.
- **Queries, environments and arguments are never logged,** beside the secrets the reference names, since an app may put secrets of its own there, which a connector can't tell apart.

### WebSockets

Every connector supports WebSockets on every transport, since a FastAPI app serves them like any other route, and an app that uses them in one language would otherwise find them missing in another. Whether a language needs a helper or only a recipe depends on what its WebSocket libraries accept, so each connector's issue decides. The reference's [WebSockets](https://jaarke.github.io/pipeapi/reference/connector-api/websockets/) says why outage handling must pass an upgraded connection through untouched.
