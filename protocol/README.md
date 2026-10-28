# protocol

The machine-readable contract of the pipeapi protocol: the names, values, routes and shapes that the server and every client share. Each protocol version has a directory of its own, and the guide site renders that version's page, its tables and a page for each reserved route from these files, so no page restates them by hand. Protocol v1 is a draft, so its files may still change in any way; `draftProtocolVersions` in `docs/src/protocol.ts` marks its pages as a draft on the site and changes with this sentence.

## Files

| File | Owns |
| --- | --- |
| [`v1/openapi.yaml`](v1/openapi.yaml) | The routes pipeapi reserves under `/__pipeapi/`, their headers as reusable parameters, and their bodies, as an OpenAPI 3.2 document. |
| [`v1/registry.yaml`](v1/registry.yaml) | The names and values an OpenAPI document can't hold, in one section per kind: environment variables, and constants such as the Host value. Each section maps a name to its entry. |
| [`v1/registry.schema.json`](v1/registry.schema.json) | The registry's shape, as a JSON Schema (2020-12). |
| [`vacuum-ruleset.yaml`](vacuum-ruleset.yaml) | The rules the OpenAPI linter applies to every version's `openapi.yaml`, and why each rule it turns off doesn't fit. |

The schemas leave a set of names open, such as the environment variables, so a section gains entries without a schema change; each entry's fields are fixed, so a misspelled field fails validation.

## Changing the contract

1. Edit the file that owns the fact:
   - A new name or value: add an entry to its section of `registry.yaml`, with every field the schema requires. An entry's description is plain text of one or two sentences; the spec page states the rules that apply to it.
   - A route, header or body: edit `openapi.yaml`. Every example it gives must be valid against its schema.
   - A new kind of name: add a section to `registry.schema.json` with its entry's definition in `$defs`, then render it on the site, as the link below describes.
2. Run `just lint`, which validates `v1/registry.yaml` against its schema, every `*.schema.json` under `protocol/` against its metaschema, and each `openapi.yaml` against the OpenAPI 3.2 schema with its examples against their schemas.
3. Run `just docs::check`, which builds the pages that render the files, or `just docs::dev` to see a change as you make it.

[How the contract renders](../docs/contributing/guide-site.md#how-the-contract-renders) says how the site reads these files, and what a new section needs there.

In VS Code, the YAML extension the workspace recommends validates `registry.yaml` against the schema its first line names, and `openapi.yaml` against the OpenAPI schema SchemaStore associates with that file name.
