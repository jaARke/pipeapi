# The reference app

The reference app is a FastAPI app in `conformance/reference_app/` whose routes and settings give the conformance cases something to exercise and observe. This page is for a runner that starts the app as a backend and observes it from outside, as the conformance runner does in `runner/uvicorn_server.py`.

## Starting it

The app's import path is `reference_app.main:app`. Serve it from `conformance/`, in the project's environment:

```sh
uv run --locked python -m uvicorn reference_app.main:app --host 127.0.0.1 --port 8000 --lifespan on
```

A runner that already runs in the project's environment starts the same `python -m uvicorn` command with its own interpreter. `--lifespan on` makes the lifespan required, since the `startup` record a runner waits for comes from it. A failure inside the app's lifespan fails the start under either setting, since Starlette reports it as a failed startup. An error the app raises on the lifespan scope before Starlette's handler, such as while building its middleware, differs. Under uvicorn's default, `auto`, uvicorn takes it for an app without lifespan support and serves the app without a `startup` record, so a runner waits until its own deadline. Under `on`, the start fails at once.

## Its settings

The app reads its settings from these variables once, as `reference_app.main` is imported. `reference_app/environment.py` is the one module that reads the environment. An empty value counts as unset.

| Variable | Effect |
| --- | --- |
| `REFERENCE_APP_LOG` | The observation log's path, which must be absolute, since the server's working directory may not be the runner's; a relative path fails the app's import. Unset, the app records nothing. |
| `REFERENCE_APP_FAKE_READY` | A line the app writes to stdout as its lifespan startup begins. It stands in for a readiness signal on stdio, which the protocol doesn't have, so a client that waits for one is caught. |
| `REFERENCE_APP_FAIL_STARTUP` | A message the lifespan startup fails with, before the app serves. uvicorn then exits with status 3, with the message in the last lines of its stderr. |

## The observation log

The log records what the app saw, in a file that outlives the process. It's JSON lines: each line is one object with the `event`, the `pid` of the process that saw it, and the event's own fields. Each line is appended in binary, so it ends in LF on every OS, and written before the code that saw the event goes on, so it survives the process being killed. Read only the lines that end in LF, since the last one may still be being written.

| `event` | Recorded when | Fields |
| --- | --- | --- |
| `startup` | The lifespan startup has run, and the app is about to serve | None |
| `startup_failure` | The lifespan startup failed, as `REFERENCE_APP_FAIL_STARTUP` asked | `message` |
| `shutdown` | The lifespan shutdown has run | None |
| `request` | An HTTP or WebSocket request reaches the app, recorded by the app's own middleware | `type` (`http` or `websocket`), `method` (null for a WebSocket), `path`, `query` |
| `disconnect` | A client left a stream that the server hadn't ended | `route`: `events` with `last_event_id`, the ID of the last event the client has, sent or resumed after (0 if none), or `ws` with `code`, the client's close code, and `echoed`, the messages echoed |

The `request` record comes from inside the app, so a request that pipeapi's middleware rejects leaves none, which is how a case shows that the app never ran. The `pid` tells apart backends that share a log one after another. Backends that may run at the same time need logs of their own, since appends from several processes aren't atomic on Windows.

## Knowing when it serves

Wait for the `startup` record, then connect. uvicorn binds its socket only after the lifespan startup, so the record comes first. Connecting before then is slow on Windows, which retries a refused connection for about two seconds before failing it.

If the process exits instead, the start failed: a `startup_failure` record and stderr's last lines say why.

## Stopping it

- **On Linux and macOS,** send SIGTERM.
- **On Windows,** start the app with `CREATE_NEW_PROCESS_GROUP` and send `CTRL_BREAK_EVENT`, which uvicorn handles as SIGBREAK. Ctrl+Break reaches a whole process group, and the group of its own keeps it from reaching the runner.

Either way uvicorn shuts down, then raises the signal again, so the exit status reports the signal rather than success: on Windows it's 3, and on Linux and macOS the process ends by SIGTERM. Judge a stop by the `shutdown` record, not by the exit status. A process killed hard leaves no `shutdown` record.

## Its PID on Windows

On Windows, a virtual environment's `python.exe` is a launcher that runs the base interpreter as its child, so the PID that starting it returns isn't the app's. Take the app's PID from the log's `pid`, or from the `pid` that `/seen` reports. Killing the launcher ends the app as well.

## Routes

The routes are grouped as the app's routers group them, each with the [#5](https://github.com/jaARke/pipeapi/issues/5) cases it serves. Each router module holds its routes' parameters, defaults and deadlines in full. FastAPI also serves the app's OpenAPI schema at `/openapi.json`, from which a typed client is generated; the schema leaves out `/seen`, which a generated client has no use for. Every route in the schema names its operation ID, and building the app fails on one that doesn't. Each adapter names its typed client's methods by these IDs, so an ID that FastAPI derived from a function's name and path would rename every adapter's methods whenever either changed.

**Items** ([`routers/items.py`](../../../conformance/reference_app/routers/items.py)), a typed API over an in-memory store that each app instance holds, so a new backend starts empty:

| Route | Answers | Cases |
| --- | --- | --- |
| `GET /items`, `HEAD /items` | The items as JSON, each with its `id`, `name` and `tags`, in the order they were created; HEAD with the same headers and no body | Typed list; HEAD |
| `POST /items` | 201 and the created item, from a JSON body with `name` and `tags` | Typed create; whole body |
| `POST /items/form` | 201 and the created item, from a URL-encoded or multipart form, whose `tags` may repeat | Whole body |
| `DELETE /items/{item_id}` | 204 with no body, or 404 for an item the store lacks | 204 |

**Requests** ([`routers/requests.py`](../../../conformance/reference_app/routers/requests.py)):

| Route | Answers | Cases |
| --- | --- | --- |
| `/seen`, and any path below it, for GET, POST, PUT, PATCH and DELETE | What the app saw of the request: the `pid` that served it, `method`, `path` decoded and `raw_path` as it arrived, `query`, `http_version`, `scheme`, `headers` in the order they arrived with repeats kept, `body` in base64, `client` as `request.client` gives it, `server`, and `pipeapi`, what pipeapi's middleware put under the ASGI scope's `pipeapi` extension | GET with query string; whole body; `request.client`; the headers the app receives |
| `POST /echo` | The request's body, streamed back in the chunks it arrived in, with the request's content type | Streamed body |
| `GET /headers` | Two `Set-Cookie` headers, and their values as JSON | Multi-value response headers |
| `GET /status/{code}`, `POST /status/{code}` | The final status asked for, as the app itself answers: 204, 205 and 304 with no body, any other with `{"status": code}`, and 401 with a `WWW-Authenticate: Bearer` challenge and no pipeapi marker | 204; 401 from the app itself |
| `GET /barrier/{name}?parties=<n>` | Holds each request until `n` wait at the barrier of that name, where the first request's `n` holds, then answers each with `filled` true, so requests that all answer so were in flight together. A barrier still short at its deadline answers its parties with `filled` false. Each answer says how many had `arrived`. | Concurrent requests |

**Streams** ([`routers/streams.py`](../../../conformance/reference_app/routers/streams.py)), which record a client that leaves early as a `disconnect`:

| Route | Answers | Cases |
| --- | --- | --- |
| `GET /events?count=<n>&end=<bool>` | Server-sent events 1 to `count`, each with `id: <i>` and `data: event <i>`, or only those after a `Last-Event-ID` header (400 for an ID it never sent). The stream then stays open until the client leaves or the router's hold deadline passes; with `end=true`, it ends after the last event. | SSE endpoint; abort mid-stream; SSE stream across a restart |
| WebSocket `/ws?close_after=<n>&close_code=<c>` | Echoes each text and binary message. After `n` messages it closes with code `c`, from the range WebSocket keeps for private use, and the reason "closed by the server"; after the hold deadline passes with no message, with the reason "idle". | WebSocket echo; server closes the socket |

**Process** ([`routers/process.py`](../../../conformance/reference_app/routers/process.py)), which shows what a backend's process was given:

| Route | Answers | Cases |
| --- | --- | --- |
| `POST /environment` with `names` and `containing` lists | The value of each variable named (null where unset), and for each text the names of the variables whose values contain it. No other value leaves the process. | Environment |
| `POST /input` | What `input()` gave: `eof`, `line` with the line read, `failed` with the error, or `blocked` when it's still waiting at the route's deadline | App calls `input()` |
| `POST /output` with `stream`, `lines`, `width` and `tag` | Writes `lines` lines to `stdout` or `stderr`, each the `tag`, a space, its zero-padded index and a space, padded with dots to `width` characters, so a sink can check each line. It refuses (422) a `width` too narrow for a line's tag and index, and a request for more output in all than the route's bound. A sink that stops reading blocks only this request. | Slow or ignored stdout sink; stdio guard |

The settings serve the rest: `REFERENCE_APP_FAKE_READY` the fake ready string, `REFERENCE_APP_FAIL_STARTUP` the startup failure, and the log the readiness, `close()` and disconnect cases.
