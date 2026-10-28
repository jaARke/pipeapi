# protocol

The machine-readable contract of the pipeapi protocol: the names, values, routes and shapes that the server and every client share. Each protocol version has a directory of its own, and the guide site renders that version's page, its tables and a page for each reserved route from these files, so no page restates them by hand. The [connector API](#the-connector-api), the surface every connector offers the app that uses it, has a directory of its own too, since it isn't versioned with the protocol. Protocol v1 is a draft, so its files may still change in any way; `draftProtocolVersions` in `docs/src/protocol.ts` marks its pages as a draft on the site and changes with this sentence.

## Files

| File | Owns |
| --- | --- |
| [`v1/openapi.yaml`](v1/openapi.yaml) | The routes pipeapi reserves under `/__pipeapi/`, their headers as reusable components, and their bodies and responses, as an OpenAPI 3.2 document. |
| [`v1/registry.yaml`](v1/registry.yaml) | The names and values an OpenAPI document can't hold, in one section per kind: environment variables, constants such as the Host value, rejection codes, durations, exit codes, feature flags, lease event types, lease end reasons and protocol versions. Each section maps a name to its entry. |
| [`v1/registry.schema.json`](v1/registry.schema.json) | The registry's shape, as a JSON Schema (2020-12). |
| [`v1/rendezvous.schema.json`](v1/rendezvous.schema.json) | The rendezvous file's shape, as a JSON Schema (2020-12). |
| [`v1/vectors/`](v1/vectors/) | Test vectors for the hello proof, the enrollment proof and endpoint template expansion, with their shape in `vectors.schema.json`. |
| [`connector-api/connector-api.schema.json`](connector-api/connector-api.schema.json) | The connector API's options, request options, lifecycle events, reasons for a lost `Backend`, errors and log records, as a JSON Schema, and the fixed values every connector uses. |
| [`connector-api/meta.schema.json`](connector-api/meta.schema.json) | How `connector-api.schema.json` is written beyond what makes it a JSON Schema, as a JSON Schema (2020-12). |
| [`vacuum-ruleset.yaml`](vacuum-ruleset.yaml) | The rules the OpenAPI linter applies to every version's `openapi.yaml`, and why each rule it turns off doesn't fit. |

The registry's schemas leave a set of names open, such as the environment variables, so a section gains entries without a schema change; each entry's fields are fixed, so a misspelled field fails validation.

## Changing the contract

1. Edit the file that owns the fact:
   - A new name or value: add an entry to its section of `registry.yaml`, with every field the schema requires. An entry's description is plain text of one or two sentences; the spec page states the rules that apply to it.
   - A route, header or body: edit `openapi.yaml`. Every header is a component, so the guide site finds it: a request header in `components/parameters`, and a response header in `components/headers` under its own name, which each response refers to. Every example it gives must be valid against its schema; vacuum checks an example's `value`, but not OpenAPI 3.2's `dataValue` or `serializedValue`. The conformance project's tests check every example of a stream, item by item, against its `itemSchema`, so give a stream's example as `serializedValue`, the whole stream, or `dataValue`, one item.
   - A new kind of name: add a section to `registry.schema.json` with its entry's definition in `$defs`, then render it on the version's page, as the link below describes.
   - A test vector: see [Test vectors](#test-vectors).
2. A few facts are written in two files, each naming the other in a comment, so change both together: the lease event types (`registry.yaml` and the `lease_event` schema's branches), the authentication scheme (a constant and the `WWW-Authenticate` header's pattern), the rejection codes and their statuses (`registry.yaml`'s rejections and the descriptions of `openapi.yaml`'s responses, which name them), and the lease TTL's minimum (a duration and the `session_event` schema). The proofs' labels are constants that the vectors were computed with and the vectors' cross-check holds too.
3. Run `just lint`, which validates each version's `registry.yaml` and vectors against their schemas, the connector API against its meta-schema, every `*.schema.json` under `protocol/` against its metaschema, and each `openapi.yaml` against the OpenAPI 3.2 schema with its examples against their schemas.
4. Run `just docs::check`, which builds the pages that render the files, or `just docs::dev` to see a change as you make it, and `just conformance::check`, which checks the vectors and the examples of streams.

[How the contract renders](../docs/contributing/guide-site.md#how-the-contract-renders) says how the site reads these files, what a new section needs there, and how a page cites a name.

In VS Code, the YAML extension the workspace recommends validates `registry.yaml` against the schema its first line names, and `openapi.yaml` against the OpenAPI schema SchemaStore associates with that file name. Each vector file's `$schema` names its schema for the JSON editor, and the connector API's names JSON Schema's own, so the editor checks it as a schema; only `just lint` checks it against its meta-schema.

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

`x-constants` holds the fixed values every connector uses, each a number of `seconds` or `bytes`. `meta.schema.json` states the rest of how the file is written: options and fields are named in camelCase, the names apps match on are in snake_case, and every option, field, member, shared type and constant has a description of one or two sentences, which leaves the rules to the connector API page.

A union's members don't forbid fields they don't list, so a schema that refers to a union may add fields of its own, and close it where it needs to with `unevaluatedProperties: false` beside the reference. Only the two kinds of options are closed, so a misspelled option fails validation.

To change the connector API, edit the definition that owns the name, then run `just lint`, and `just docs::check`, which builds the page that renders the file and fails on an option whose variable the protocol's registry doesn't hold, or on a type the site can't describe.

The connector API isn't versioned with the protocol, and no package has released it yet, so it is a draft, which may still change in any way; `connectorApiStatus` in `docs/src/protocol.ts` marks its page as a draft on the site and changes with this sentence. From each package's first release, the error codes, lifecycle event types and reasons for a lost `Backend` it ships are identifiers apps match on, so they are only ever added to; option names, fields and log events follow that package's semantic versioning.

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
