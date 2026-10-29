# The protocol

The protocol is the contract between a pipeapi server and every client, in any language. It's HTTP/1.1 with a few reserved routes and headers, so the app stays an unmodified FastAPI app and each connector stays a thin layer on an HTTP client its language already has ([#1](https://github.com/jaARke/pipeapi/issues/1)). Its specification is the guide site's [Protocol v1](https://jaarke.github.io/pipeapi/reference/protocol-v1/) pages, which render the contract's files in `protocol/`, and [protocol/README.md](../../protocol/README.md) says which file owns what and how to change the contract.

This page says what the protocol guarantees and to whom, why it's built the way it is, and what was rejected. It states none of the spec's rules or values: each reason links the section that holds its rule.

## What it guarantees

| To | The protocol guarantees | Where the spec holds it |
| --- | --- | --- |
| A client | That it enrolls only after a proof that the server holds the token, and that the app is ready once the server answers | [Connect sequence](https://jaarke.github.io/pipeapi/reference/protocol-v1/connecting/#connect-sequence), [hello proof](https://jaarke.github.io/pipeapi/reference/protocol-v1/tokens-and-proofs/#hello-proof) |
| A client | That a response carrying pipeapi's rejection marker never reached the app | [Rejections](https://jaarke.github.io/pipeapi/reference/protocol-v1/requests/#rejections) |
| A client | That the backend doesn't stop on its own while the client holds a lease, whichever client started it | [Leases](https://jaarke.github.io/pipeapi/reference/protocol-v1/leases/), [sharing a backend](https://jaarke.github.io/pipeapi/reference/protocol-v1/connecting/#sharing-a-backend) |
| A client | That a server keeps speaking an older protocol version for a published window | [Protocol versions](https://jaarke.github.io/pipeapi/reference/protocol-v1/versioning/#protocol-versions) |
| The app | That its requests arrive as a web app's do, without pipeapi's credentials or reserved routes | [Headers](https://jaarke.github.io/pipeapi/reference/protocol-v1/requests/#headers), [reserved routes](https://jaarke.github.io/pipeapi/reference/protocol-v1/requests/#reserved-routes) |
| The app | That each request identifies its client, and that it learns when a client's lease ends | [Identity](https://jaarke.github.io/pipeapi/reference/protocol-v1/connecting/#identity) |
| The user | That the network, other OS users and web content are kept out, within the limits the spec lists | [Trust boundary](https://jaarke.github.io/pipeapi/reference/protocol-v1/security-considerations/#trust-boundary), [limits](https://jaarke.github.io/pipeapi/reference/protocol-v1/security-considerations/#limits) |

### Why the boundary is the OS user

A process that runs unsandboxed as the same user can read the memory, environment and files of both the client and the server, so it can take any secret pipeapi holds, and no protocol can keep it out. The spec therefore claims nothing against it.

Inside that boundary, the protocol still authenticates every client. It costs a client one more HMAC than verifying the server already takes, and it turns an accident, such as a stale client from an earlier run reaching a new backend, into a refused request rather than a call the app serves.

Named pipes are the primary transport, since pipeapi exists for apps where a listening port is a problem: on multi-session Windows, ports collide between users and can be reached across sessions, and security reviews and endpoint protection flag them ([#1](https://github.com/jaARke/pipeapi/issues/1)). Loopback is a transport too, for apps where pipes and sockets don't fit, at the cost the spec's [limits](https://jaarke.github.io/pipeapi/reference/protocol-v1/security-considerations/#limits) name.

## Why it's built this way

### Endpoints and transports

- **One URL names the transport and the address,** so one string configures a client and one environment variable passes it to a backend. The `unix://` and `npipe://` forms are Docker's. A client reads the part after the scheme as text rather than through a URL parser, since parsers differ between languages in what they decode and normalize, and every client must reach the same path.
- **Loopback takes literal addresses only.** A name such as `localhost` resolves to IPv4 on one system and IPv6 on another, so a client and a server could disagree on the address, and a name can resolve off the machine.
- **Templates** let independent clients compute the same shared name without talking to each other. On Windows, `{user}` is the user name rather than the SID, since Node's standard library can read the name but not the SID, and every connector must expand it alike. The spec's [limits](https://jaarke.github.io/pipeapi/reference/protocol-v1/security-considerations/#limits) name what that costs.
- **A socket's lock file is named after the socket,** rather than fixed for its directory, so sockets that share a directory don't lock each other out.
  - A server takes the lock without waiting, so a server that loses a race exits at once and its client attaches, rather than queueing to take the endpoint over once the winner stops.
  - It holds the lock until its socket file is gone, so a socket file found while the lock is free is always a stopped server's, and safe to remove.
  - The OS releases the lock when its holder dies, so a crash never leaves an endpoint locked.
- **A generated port reaches the client through a file.** The server binds port 0, so the OS picks a free port within the bind itself; a client that picked a free port and passed it in would race any process that bound it first. The port goes in a file rather than on stdout, since [stdio](#stdio) carries no protocol. How each connector's language creates the file's directory with a user-only access list on Windows is [#8](https://github.com/jaARke/pipeapi/issues/8)'s.
- **Only the client that generated a port-0 endpoint spawns a backend for it,** and every client given one attaches. Binding port 0 never conflicts, so no bind could settle a race between two clients that shared one, and a lock beside the rendezvous file would add a second arbiter for this one case.
- **A rendezvous file's directory is always one a client generated, which only the user can access.** Otherwise another user could point clients at a port of their own and relay the real server's hello and enrollment, which a client on TCP can't detect, since it can't read its peer's PID.
- **A server removes only what it wrote:** the rendezvous file, then the directory only if it's empty, since a server can't tell that a directory was generated. The client that generated the directory keeps it while it may start another backend there, so a respawn keeps its endpoint.

The spec's [endpoint URLs](https://jaarke.github.io/pipeapi/reference/protocol-v1/endpoints/#endpoint-urls) say why a backend on Windows listens on a named pipe rather than a Unix domain socket.

### The Host value

Every request carries one fixed Host, on every transport. HTTP/1.1 requires a Host, and a pipe or a socket has no host name to put there, so every client needs a placeholder that any HTTP client accepts as a host name. Docker's client uses `api.moby.localhost` for the same need ([moby/moby#45942](https://github.com/moby/moby/pull/45942)), and pipeapi's value follows it. The spec's [host and proxies](https://jaarke.github.io/pipeapi/reference/protocol-v1/requests/#host-and-proxies) say why a `.localhost` name is never resolved, and why a client turns proxies off.

Rejected:

- **A `.local` name.** It's multicast DNS ([RFC 6762](https://www.rfc-editor.org/rfc/rfc6762)), so a resolver that looks it up asks the whole LAN, where any host can answer, and lookups on macOS stall for seconds.
- **A `.internal` name,** which goes to corporate DNS.
- **A single label,** which gets search-domain expansion.

On loopback the same value defends against DNS rebinding, as the spec's [ports 80 and 443](https://jaarke.github.io/pipeapi/reference/protocol-v1/security-considerations/#ports-80-and-443) explain.

### Encodings and proofs

- **base64url without padding** needs no escaping in headers, URLs, file names or JSON, and its alphabet holds no period, so a header that joins two values with a period splits unambiguously.
- **Only the canonical form is valid,** since lenient and strict decoders disagree on non-canonical input: one implementation would accept a value another refuses, and two strings would decode to the same bytes.
- **HMAC-SHA256** is in every connector language's standard library or a maintained package, and one primitive serves both proofs.
- **A proof's input is a label, a 0x00 byte and fixed-length fields.** Fixed lengths need no length prefixes or delimiters, so two different sets of fields never give the same bytes. The 0x00 ends the label, so no label reads as the start of another. Each label names its protocol version, so a later version that computes a proof another way gives it a label of its own.
- **A PID's field** is as wide as a Windows PID, which every POSIX PID fits, and its byte order is the network's.

The spec's [proofs](https://jaarke.github.io/pipeapi/reference/protocol-v1/tokens-and-proofs/#proofs) say why the key is the token's text.

### Verification and enrollment

A client verifies the server before it enrolls, then proves it holds the token by answering a challenge, and receives a session for its lease. D-Bus's `DBUS_COOKIE_SHA1` mechanism has the same shape: a secret only the user can read, proved by a hash over a challenge and never sent. The design gives four things:

- The token never crosses the wire, so a process that takes the endpoint first collects nothing.
- A client ID can't be used without its client's secret.
- One client can be revoked alone.
- A leaked session ends with its lease.

It adds no round trip, since the challenge rides on the hello and its answer on the lease request.

Rejected:

- **A token on every request,** as a bearer token. It crosses the wire, so a squatter collects it, and every client's requests look alike, so the app can't tell clients apart or revoke one.
- **The token alone, with sessions as a feature a server advertises.** The server and every connector would keep two ways to authenticate until a later protocol version and its deprecation window retired one, and the token would cross the wire wherever a server didn't require sessions.
- **Sessions also bound to the client's OS process,** through `SO_PEERCRED`, `LOCAL_PEERPID` or `GetNamedPipeClientProcessId`. The binding changes nothing on the wire, so a server can add it on pipes and sockets at any time, and loopback has no reliable peer identity. It's [#6](https://github.com/jaARke/pipeapi/issues/6)'s.

The rest of verification and enrollment:

- **The hello answers without credentials,** so any client can check a server before it reveals anything. That also lets a squatter relay a hello, and the spec's [hello proof](https://jaarke.github.io/pipeapi/reference/protocol-v1/tokens-and-proofs/#hello-proof) says how binding the PID of the endpoint's listener detects it.
- **The PID check and opening a pipe at identification level apply where a client's runtime allows them,** rather than binding every client, since both guard against a process of the same user, which sits outside the trust boundary. The spec's [limits](https://jaarke.github.io/pipeapi/reference/protocol-v1/security-considerations/#limits) name what a client without them leaves open. A process of the same user can also add its own instances to a named pipe, and the defense against that is [#8](https://github.com/jaARke/pipeapi/issues/8)'s.
- **A client generates a token only with an endpoint it generates.** A client given an endpoint shares its backend, and a token of its own would match no other client's: it couldn't verify a backend already there, and every other client would fail to verify a backend it spawned.
- **A token the user gives needs enough entropy,** since the hello answers anyone who can reach the endpoint with a proof over a nonce they chose, and a weak token can be guessed offline against that proof.
- **A server may bound its unused challenges,** since anyone who can reach a hello can make the server issue one. Evicting the oldest costs an evicted client only a fresh hello.

### Sessions and identity

- **Identity is part of the protocol, not a feature.** A response already returns on its request's connection, but leases are internal to pipeapi, so without an ID the app couldn't address a message to one client or learn that one has gone.
- **One header carries the ID and its secret,** so an ID never travels without its proof, and one header does the work of a token header and an ID header.
- **A session belongs to a client, not to a connection,** since connectors build on HTTP clients that pool connections and open new ones as they need.

The spec's [identity](https://jaarke.github.io/pipeapi/reference/protocol-v1/connecting/#identity) says why a client that reconnects gets a new ID.

### The marker on pipeapi's rejections

- **A header marks pipeapi's own refusals.** The app answers 401, 404 and 503 of its own, such as an OAuth2 app's 401, so a status alone can't tell a client whether the app saw its request. A header's presence is one check in any HTTP client, where reading a 401's challenge needs a parser most clients lack. The spec's [headers](https://jaarke.github.io/pipeapi/reference/protocol-v1/requests/#headers) and [rejections](https://jaarke.github.io/pipeapi/reference/protocol-v1/requests/#rejections) say why the server strips the marker from the app's responses, and why a 401 also carries a challenge.
- **pipeapi adds no error body.** The app's clients, often generated from its OpenAPI schema, already parse the app's error bodies, and a second shape on the same statuses would be one more case for each of them.
- **The order of checks** has a reason at each step:
  - Host and `Origin` come first, so a web page's request gets that refusal and nothing else.
  - The protocol version comes before credentials, since a server that speaks several versions checks credentials by the rules of the version a request names.

### Lifetime and leases

- **A backend lives while a lease is open,** rather than while the client that spawned it runs, since any client may attach and outlive the one that started it. A lease is a held connection, which the OS closes when a process dies, however it dies.
- **The startup grace's default** sits well above a connector's connect deadline, so it doesn't stop a backend that a live client is still connecting to. Kotlin's compile daemon waits as long, from its start, for its first compilation.
- **The idle grace's default stops a backend at once,** for the reason the spec's [graces](https://jaarke.github.io/pipeapi/reference/protocol-v1/lifetime/#graces) give, and because a running process locks its executable on Windows, so a lingering backend blocks the app's update or rebuild. The cost is that a backend on a shared endpoint needs its idle grace set.
- **Leases have no TTL by default,** for the reason the spec's [lease TTL](https://jaarke.github.io/pipeapi/reference/protocol-v1/leases/#lease-ttl) gives. The cost is that a hung client keeps its backend running until it's killed. With a TTL, the renewal ratio follows etcd's client, which renews its leases at the same fraction of their TTL, and a busy client's own requests renew its lease, so it sends nothing extra.
- **A server takes its endpoint before the app's lifespan startup,** so a server that loses a spawn race never runs the app, whose startup may act outside its process, such as by migrating a database.
- **A stopping server refuses hellos as well as leases, and a client treats that refusal as no answer yet,** polling within its deadline and spawning once nothing accepts its connection, rather than retrying once. An immediate retry usually reaches the same stopping server, and a named pipe's name stays taken until the old server's last instance closes.
- **Any client with a lease may stop the backend,** since every client proves the same token, which gives the protocol no basis to rank one above another.
- **Dedicated exit codes** let a client tell a lost spawn race, which it answers by attaching, from a broken app, where uvicorn's own startup failure status covers both. Their values come from sysexits, whose meanings for a temporary failure and a configuration error fit the two.

### Stdio

Standard input, output and error carry nothing of the protocol, since they belong to the user ([#1](https://github.com/jaARke/pipeapi/issues/1)). Any library the app imports may print, so a signal on stdout could be faked by accident, and a connector would have to parse output the user wants to see as it is. Readiness comes from the hello instead, so one request both verifies the server and finds it ready.

### Versioning and freezing

- **The protocol has an integer version of its own,** apart from the packages' versions, since five packages release on their own schedules and the protocol is what they share.
- **Names that grow within a version are open sets.** The schemas type rejection codes, feature flags, lease event types and lease end reasons as strings rather than enums, and bodies admit unknown properties, since a closed enum would make each addition break a validator built from the earlier file. The spec's [compatible changes](https://jaarke.github.io/pipeapi/reference/protocol-v1/versioning/#compatible-changes) say what each side ignores.
- **The deprecation window** has the shape of Kubernetes' policy: a span of time and a count of releases, whichever ends later. A count alone, as PEP 387 uses, fits poorly when five packages release on their own schedules, so the window has a time floor. A major release of the server is its other bound, so dropping a version is always a breaking release. A longer window, such as the 24 months GitHub's REST API keeps a version, costs in proportion: while one is open, each package keeps two code paths and twice the version pairs to test ([#23](https://github.com/jaARke/pipeapi/issues/23)). The spec's [protocol versions](https://jaarke.github.io/pipeapi/reference/protocol-v1/versioning/#protocol-versions) say why connectors keep the same window.
- **Each protocol version has a directory of its own,** as MCP keeps its schemas, so a version's contract stays readable as it shipped for as long as a server speaks it. A version is a draft, which may still change in any way, until the release that first ships it, and changes only by addition from then on.
- **Checks enforce the freeze, so review doesn't have to catch a removed name.** oasdiff, a maintained OpenAPI diff with breaking-change rules, compares each version's `openapi.yaml` with `main` through a pre-commit hook of its own. No maintained tool compares a data file's names, so a short script in `scripts/` checks that the registry's entries, the vectors' cases, the conformance cases, the connector API's identifiers and the adapter protocol's names are only added to, and that the facts two files hold agree. Both report a draft's breaking changes without failing, which proves them on the files before they gate anything, and fail once the contract is released. [protocol/README.md](../../protocol/README.md#freezing) says what each covers, and the limit oasdiff has with the lease events' schema.
- **Each contract's status is in its own files,** a version's `registry.yaml`, and the `x-status` of the connector API's and each adapter protocol version's schema, where the script, the site's draft banner and a reader of the files all find it. oasdiff's hook takes its mode from its args instead, since prek gives a hook no way to read a file, so the release that flips a status changes the hook's args with it. oasdiff's own draft mark, `x-stability-level` on each operation, was rejected: it ignores a draft operation's changes rather than reporting them, and covers neither the registry nor the vectors.

The spec's [discovery and negotiation](https://jaarke.github.io/pipeapi/reference/protocol-v1/versioning/#discovery-and-negotiation) say why the hello stays the same across versions.

### The machine-readable contract

- **The files are hand-written and language-neutral.** One server and five connectors in five languages implement the contract, so it can't live in any one's code. Hand-written neutral files suit a protocol with several implementations, as Docker's `swagger.yaml` and the Debug Adapter Protocol's JSON schema show; a contract generated from code suits one authoritative implementation that uses those types at runtime, as Kubernetes and LSP do.
- **OpenAPI 3.2** describes HTTP routes, headers and bodies, and it's the first version that describes a stream item by item, which the lease stream is. Docker's `swagger.yaml` is the closest precedent: an HTTP API served over a Unix domain socket or a named pipe. [How the contract renders](guide-site.md#how-the-contract-renders) says how the site shows what its OpenAPI plugin leaves out.
- **A registry** holds the names an OpenAPI document can't, as a data file rendered into tables, the way IANA's registries and OpenTelemetry's semantic conventions keep theirs.
- **Prose keeps the behavior.** The connect sequence, lifetime and security are rules no schema language states, and every name the prose uses comes from the files, as [citing a name](guide-site.md#citing-a-name) describes.
- **`protocol/` belongs to no project.** Under `docs/` it would mix the site's source with a contract the server and connectors consume, and under `conformance/` it would sit inside one of its consumers.
- **The test vectors follow Project Wycheproof's style,** so an invalid case names the mistake it catches, and a failing test says what an implementation got wrong. Their expected values come from outside pipeapi's code, and a second implementation checks them, since vectors captured from the code under test would bless its bugs. [protocol/README.md](../../protocol/README.md#test-vectors) says how.

Rejected:

- **Pydantic or zod as the source.** A schema ties an implementation to the contract only if the implementation uses it at runtime, which pipeapi's dependency rule forbids: the server requires only the standard library and uvicorn, and the Node connector only its standard library ([#1](https://github.com/jaARke/pipeapi/issues/1)). Kept to development time, either is a schema language in one implementation's syntax, which the other four read poorly. FastAPI couldn't generate the reserved routes either, since pipeapi's middleware answers them before the app.
- **Generated constants for each language:** five generators for a few dozen names, whose drift the test vectors and the conformance cases ([#5](https://github.com/jaARke/pipeapi/issues/5)) catch.
- **TypeSpec:** its streaming libraries are pre-1.0, and its OpenAPI 3.2 output has open bugs.
- **AsyncAPI:** a second document and toolchain for one stream.
- **WebIDL and Smithy:** neither models an idiomatic client library in each language, which is what a connector is, as [the connector API](connector-api.md) describes.
