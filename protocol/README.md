# protocol

The machine-readable contract of the pipeapi protocol: the names, values, routes and shapes that the server and every client share. Each protocol version has a directory of its own, and the guide site renders that version's specification, its tables and a page for each reserved route from these files, so no page restates them by hand. The [connector API](#the-connector-api), the surface every connector offers the app that uses it, has a directory of its own too, since it isn't versioned with the protocol. Each protocol version, and the connector API, is a draft until it's released, and changes only by addition from then on, as [Freezing](#freezing) says; the site marks a draft's pages as a draft.

## Files

| File | Owns |
| --- | --- |
| [`v1/openapi.yaml`](v1/openapi.yaml) | The routes pipeapi reserves under `/__pipeapi/`, their headers as reusable components, and their bodies and responses, as an OpenAPI 3.2 document. |
| [`v1/registry.yaml`](v1/registry.yaml) | The version's `status`, draft or released, and the names and values an OpenAPI document can't hold, in one section per kind: environment variables, constants such as the Host value, rejection codes, durations, exit codes, feature flags, lease event types, lease end reasons and protocol versions. Each section maps a name to its entry. |
| [`v1/registry.schema.json`](v1/registry.schema.json) | The registry's shape, as a JSON Schema (2020-12). |
| [`v1/rendezvous.schema.json`](v1/rendezvous.schema.json) | The rendezvous file's shape, as a JSON Schema (2020-12). |
| [`v1/vectors/`](v1/vectors/) | Test vectors for the hello proof, the enrollment proof and endpoint template expansion, with their shape in `vectors.schema.json`. |
| [`connector-api/connector-api.schema.json`](connector-api/connector-api.schema.json) | The connector API's options, request options, lifecycle events, reasons for a lost `Backend`, errors and log records, as a JSON Schema, the fixed values every connector uses, and its status in `x-status`. |
| [`connector-api/meta.schema.json`](connector-api/meta.schema.json) | How `connector-api.schema.json` is written beyond what makes it a JSON Schema, as a JSON Schema (2020-12). |
| [`vacuum-ruleset.yaml`](vacuum-ruleset.yaml) | The rules the OpenAPI linter applies to every version's `openapi.yaml`, and why each rule it turns off doesn't fit. |

The registry's schemas leave a set of names open, such as the environment variables, so a section gains entries without a schema change; each entry's fields are fixed, so a misspelled field fails validation.

## Changing the contract

1. Edit the file that owns the fact:
   - A new name or value: add an entry to its section of `registry.yaml`, with every field the schema requires. An entry's description is plain text of one or two sentences; the spec's pages state the rules that apply to it.
   - A route, header or body: edit `openapi.yaml`. Every header is a component, so the guide site finds it: a request header in `components/parameters`, and a response header in `components/headers` under its own name, which each response refers to. A response that carries `X-PipeAPI-Rejected` lists the codes it may carry in `x-rejections`, names each in its description, and gives no content, since a rejection's body is empty. Every example it gives must be valid against its schema; vacuum checks an example's `value`, but not OpenAPI 3.2's `dataValue` or `serializedValue`. The conformance project's tests check every example of a stream, item by item, against its `itemSchema`, so give a stream's example as `serializedValue`, the whole stream, or `dataValue`, one item.
   - A new kind of name: add a section to `registry.schema.json` with its entry's definition in `$defs`, then render it on one of the version's pages, as the link below describes.
   - A test vector: see [Test vectors](#test-vectors).
2. A few facts are written in two files, each naming the other in a comment, so change both together; `just lint` fails when they disagree. They are the lease event types (`registry.yaml` and the `lease_event` schema's branches), the authentication scheme (a constant and the start of the `WWW-Authenticate` header's pattern), the rejection codes and their statuses (`registry.yaml`'s rejections and the `x-rejections` of each `openapi.yaml` response that carries `X-PipeAPI-Rejected`, whose description names exactly the codes it lists), the lease TTL's minimum (a duration and the `session_event` schema), and the proofs' labels (constants, which start each valid proof vector's message, and which the vectors' cross-check holds too).
3. Run `just lint`, which validates each version's `registry.yaml` and vectors against their schemas, the connector API against its meta-schema, every `*.schema.json` under `protocol/` against its metaschema, and each `openapi.yaml` against the OpenAPI 3.2 schema with its examples against their schemas. It also compares the contract with `main`, as [Freezing](#freezing) says.
4. Run `just docs::check`, which builds the pages that render the files, or `just docs::dev` to see a change as you make it, and `just conformance::check`, which checks the vectors and the examples of streams.

[How the contract renders](../docs/contributing/guide-site.md#how-the-contract-renders) says how the site reads these files, what a new section needs there, and how a page cites a name.

In VS Code, the YAML extension the workspace recommends validates `registry.yaml` against the schema its first line names, and `openapi.yaml` against the OpenAPI schema SchemaStore associates with that file name. Each vector file's `$schema` names its schema for the JSON editor, and the connector API's names JSON Schema's own, so the editor checks it as a schema; only `just lint` checks it against its meta-schema.

## Freezing

A contract is a draft, which may still change in any way, until it's released. From then on it changes only by addition, so what clients and apps already rely on keeps working, and a released contract stays released. Each states its status in its own files: a protocol version in its `registry.yaml`'s `status`, the connector API in its file's `x-status`, and a version of the conformance suite's [adapter protocol](../docs/contributing/adapter-protocol.md) in its schema's `x-status`.

- **A protocol version** is released by the release that first ships it. A change that would break a client or a server built to its earlier rules then starts the next version's directory instead, as the spec's [compatible changes](https://jaarke.github.io/pipeapi/reference/protocol-v1/versioning/#compatible-changes) say, and the version's directory stays while any supported server speaks it. The new version gets hooks of its own in `.pre-commit-config.yaml`, as v1 has, each matching only its files: the validation of its registry and its vectors against its own schemas, and an `oasdiff-breaking` hook for its `openapi.yaml`, since each oasdiff hook's args hold its version's mode, as below.
- **The connector API** is released by the first release of any package that ships it, as [The connector API](#the-connector-api) says.
- **An adapter protocol version** is released by the first connector release that includes an adapter speaking it, as the adapter protocol's [Versioning](../docs/contributing/adapter-protocol.md#versioning) says.

`just lint` compares the working tree with `origin/main`, the integration branch as your clone last fetched it. A branch behind `main` would report `main`'s newer entries as removed, so fetch `main` and rebase onto it before trusting a local run. CI compares a pull request with the commit of `main` it merges into, a push to `main` with the commit before it, and a run by hand with `main`'s tip. While a contract is a draft, its checks report what would break it and pass; once it's released, they fail:

| What's frozen | How it may still change | Checked by |
| --- | --- | --- |
| Each version's `openapi.yaml` | Only in ways oasdiff's [breaking-change rules](https://github.com/oasdiff/oasdiff/blob/main/docs/BREAKING-CHANGES.md) allow, apart from the limit below | oasdiff's `oasdiff-breaking` hook |
| Each version's `registry.yaml` entries | New entries and fields. An entry is never removed or renamed, and its fields, but for its description, never change or go. | [`scripts/check_contract.py`](../scripts/check_contract.py), as the `contract` hook |
| Each version's test vectors | New cases, appended. A case is never removed, and its fields, but for its comment, never change or go. | `scripts/check_contract.py` |
| The connector API's error codes, lifecycle event types and reasons for a lost `Backend` | New ones. None is removed or renamed. | `scripts/check_contract.py` |
| The conformance cases in [`conformance/cases/cases.yaml`](../conformance/cases/cases.yaml), under each protocol version's status | New cases and invariants. A case is never removed or renamed, and its expectation, its kind, what it reaches and relies on (its `backends`, `needs` and `relies_on`) and where it applies (its `transports`, `platforms`, `vias` and `once`) never change, nor do an invariant's expectation and `needs`; changed behavior is a new case. A field a case or an invariant leaves out has its schema's default, and reordering a list of these changes nothing. | `scripts/check_contract.py` |
| Each adapter protocol version's commands, events, capabilities, refusal codes, vias, sinks and kinds of language error, in its `adapter-protocol.schema.json` | New ones. None is removed or renamed. Review holds the rest of the adapter protocol's [rule for additions](../docs/contributing/adapter-protocol.md#versioning). | `scripts/check_contract.py` |

oasdiff's hook can't read a status, so each version's OpenAPI document has a hook of its own, whose args hold that version's mode: while protocol v1 is a draft, its hook's args hold no `--fail-on`, and the hook sets `verbose`, since prek shows a passing hook's output only then. The change that releases a version sets its `status` to `released`, adds `--fail-on ERR` to its hook's args and drops `verbose`; the hook and the registry each name the other. Whatever the status, the script fails when a released contract returns to draft, when the copies of a fact two files hold disagree, as [Changing the contract](#changing-the-contract) lists them, and when it can't read a contract file in the working tree. A contract file of `main`'s that it can't read fails it only once the contract is released, and is reported while it's a draft, which may restructure its files. Each finding names its check, such as `[registry-entries]`, and the contract it concerns.

### oasdiff's limit

oasdiff compares a stream's `itemSchema` as it compares a body's `schema`, but it rates a change inside an `allOf` branch as a warning rather than an error, since another branch may still guarantee what the change dropped, and the `lease_event` schema gives each event type's fields in a branch of its `allOf`. In oasdiff 1.34.1, removing `secret` from the `session_event` schema's properties and required fields is reported as `response-required-property-removed` at warning level: `--fail-on ERR` passes it, `--fail-on WARN` fails on it, and `--flatten-allof` reports nothing, since merging the branches drops their conditions. So a released version's hook, with `--fail-on ERR`, doesn't fail on a breaking change to a lease event's fields, and review holds the lease events' shape. When the hook's args or an oasdiff release make that removal fail the hook while the status is released, check that it does, and remove this limit.

## The connector API

`connector-api/connector-api.schema.json` is a JSON Schema, so the conformance suite's adapter schema and each connector's tests use its definitions as they are, by `$ref`, and a package may generate its types from them. Its definitions are:

| Definition | Holds |
| --- | --- |
| `options` | The options `connect()` takes, as the properties of an object closed to other names. An option with a fixed default carries JSON Schema's `default`, and an option the connector also reads from the environment names the protocol's variable in `x-environment-variable`. |
| `request_options` | The options a request takes, in the same form as `options`. |
| `event` | The lifecycle events, one member of its `oneOf` each, named by the constant its `type` holds. |
| `error` | The errors, one member each, named by the constant its `code` holds. |
| `log_record` | The log events, one member each, named by the constant its `event` holds, with the constant its `level` holds. Every record's context is the union's own fields. |
| `lost_reason` | The reasons a `Backend` is lost, one member of its `oneOf` each, a constant with a description of its own. |
| Any other | A type the definitions share, such as `seconds`. The guide site shows a type's `title` where it is used, or the type itself when it has none. |

`x-constants` holds the fixed values every connector uses, each a number of `seconds` or `bytes`. `meta.schema.json` states the rest of how the file is written: options and fields are named in camelCase, the names apps match on are in snake_case, and every option, field, member, shared type and constant has a description of one or two sentences, which leaves the rules to the connector API's pages.

A union's members don't forbid fields they don't list, so a schema that refers to a union may add fields of its own, and close it where it needs to with `unevaluatedProperties: false` beside the reference. Only the two kinds of options are closed, so a misspelled option fails validation. The conformance suite's adapter schema also refers to a few members by JSON pointer, such as `log_record/properties/level`, so renaming one fails the conformance project's tests.

To change the connector API, edit the definition that owns the name, then run `just lint`, and `just docs::check`, which builds the pages that render the file and fails on an option whose variable the protocol's registry doesn't hold, or on a type the site can't describe.

The connector API isn't versioned with the protocol. Its `x-status` is `draft` until the first release of any package that ships it, which sets it to `released`. From then on, its error codes, lifecycle event types and reasons for a lost `Backend` are identifiers apps match on, so they are only ever added to, as [Freezing](#freezing) says; option names, fields and log events follow each package's semantic versioning.

## Test vectors

Each vector file holds cases in the style of [Project Wycheproof](https://github.com/C2SP/wycheproof): a case is `valid` or `invalid`, and its flags, which the file's `notes` describe, name what it exercises, such as the mistake an invalid case catches. Implementations' tests read the files by their path in the repository.

The expected values never come from pipeapi's code. Each proof is computed once with the OpenSSL command line, and each template expansion is written by hand from the spec's rules. `conformance/tests/test_vectors.py` then checks every case with a second implementation, written from the spec with Python's standard library alone, so `just conformance::check` fails on a wrong expected value, and `just lint` on a malformed case.

To add a case, append it with the next `tcId`, and give a new flag a note. A new flag of a proof case also needs its place in `conformance/tests/test_vectors.py`: a derivation of the mistake it names, or a place among the flags that describe an input. A case whose proof uses an input other than its own records it, as `otherPid` and `otherChallenge` do. These shell functions compute a proof vector with `openssl` and `xxd`, which Git for Windows and macOS ship, and which Linux has in its `xxd` or `vim` package:

```sh
hex() { printf '%s' "$1" | xxd -p | tr -d '\n'; }
b64u_hex() { printf '%s=' "$1" | tr '_-' '/+' | openssl base64 -d -A | xxd -p | tr -d '\n'; }
b64u() { openssl base64 -A | tr '/+' '_-' | tr -d '='; }
hmac_b64u() { printf '%s' "$2" | xxd -r -p | openssl dgst -sha256 -mac HMAC -macopt "hexkey:$1" -binary | b64u; }

# A generated token, nonce or challenge: b64u(32).
openssl rand 32 | b64u; echo

# A hello vector.
token='...'; nonce='...'; pid=4242
message=$(hex pipeapi-hello-v1)00$(b64u_hex "$nonce")$(printf '%08x' "$pid")
echo "message: $message"
echo "proof: $(hmac_b64u "$(hex "$token")" "$message")"

# An enrollment vector.
token='...'; challenge='...'
message=$(hex pipeapi-enroll-v1)00$(b64u_hex "$challenge")
proof=$(hmac_b64u "$(hex "$token")" "$message")
echo "message: $message"; echo "proof: $proof"; echo "header: $challenge.$proof"
```

An invalid case's proof is the same `hmac_b64u` call with the mistaken input in the message or the key, such as `"$(b64u_hex "$token")"` for a key decoded from the token. Avoid `openssl rand -base64`, which ends its output in CRLF on Windows.
