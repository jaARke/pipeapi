# The guide site

The guide site is a [Starlight](https://starlight.astro.build/) project in `docs/`, built with Astro, and its URL is `https://jaarke.github.io/pipeapi/`. Its pages are Markdown or MDX files under `docs/src/content/docs/`, the site's content root, and nothing outside it is built. This page says how the site is organized, built and checked, and why. [The documentation system](documentation.md) says where the site sits among pipeapi's documentation, which file or page owns each fact, and how to mark unreleased behavior.

## Sections

The site's navigation follows the [Diátaxis](https://diataxis.fr/) framework: every page has one job, and its job decides its section.

| Section | A page's job | Directory |
| --- | --- | --- |
| Tutorials | Take a newcomer to a first working result | `tutorials/` |
| How-to guides | Take a reader who knows what they want through one task | `guides/` |
| Reference | State a contract exactly: its names, shapes, values and rules | `reference/` |
| Explanation | Say why: the architecture, the trade-offs, the security model | `explanation/` |

Each section is a directory of the content root and a top-level group of the sidebar, in the table's order. The site has its homepage and the Reference section; the first page of another section adds its directory, its overview and its group. A page that would do two jobs is two pages that link each other, such as a how-to guide that links the reference for each option it sets.

### The sidebar

`docs/astro.config.mjs` lists the sidebar's groups, which follow one rule:

- **A section** is a group whose first entry is its overview, the section directory's `index.mdx`, labeled Overview.
- **A document**, such as a protocol version's specification or the connector API's reference, is a link when it has one page. Otherwise it's a group named for the document, which autogenerates the document's directory, so a page added there joins the group. Its first page is its overview, labeled Overview, and each page's `sidebar.order` gives its place in reading order, with the generated listings last: the registry's tables, the OpenAPI document and the conformance cases. In Reference, the connector API comes first, then each protocol version, newest first.
- **A family of generated pages**, such as a protocol version's reserved routes, is the last group of its document, collapsed until one of its pages is open.
- **Depth.** Groups nest at most three deep: section, document and family. A group autogenerates only a directory without subdirectories, since Starlight labels a subdirectory's group with its raw name.
- **Status.** The group of a document whose contract is a draft carries a Draft badge, and each of its pages a banner, from the status its contract's file states.

### Labels

Sidebar labels, page titles and headings are in sentence case: only the first word and proper nouns start with a capital, and names keep their own spelling, such as API, OpenAPI or WebSockets. Besides:

- A label never starts with a lowercase letter, so never with code or an identifier, such as `connect()`; a name that starts with one, such as pipeapi, goes later in the label. A heading may start with code.
- A label names what its page covers, as a noun phrase, such as Leases or Lease loss and outages.
- A group takes its document's name, its overview is Overview, and no entry repeats another entry's label in its group, or its group's own label.

The route middleware fails the build, naming the label, on a label that starts with a lowercase letter, on a group that holds two entries with one label, and on an entry that repeats its group's label; review holds the rest of the rule. A route's page is labeled with its operation's `summary` in `openapi.yaml`, with its method as a badge, and the routes' group with the `summary` of the document's one tag.

### Reference documents

A reference document that takes more than a few minutes to read is a directory of topic pages, and its overview keeps the document's URL:

- The overview, `index.mdx`, says what the document covers, lists its pages through `PageIndex`, then states the document's conventions. `PageIndex` renders a card for each other entry of the page's sidebar group, with that page's frontmatter `description`, so a description is written once and a new page is listed by adding it. The Reference section's overview lists its documents the same way.
- A page that holds one section of the document takes the section's heading as its title, sets `heading: true` in its frontmatter, and is named by the heading's anchor, such as `leases.mdx` for Leases. The section's subsections become its headings, and sections after it may join it whole. A page that groups several sections, such as protocol v1's Requests, takes a title of its own and keeps each section's heading as it is.
- Every heading's anchor, a section page's name included, is unique within its document, so a link or a conformance case names a section by its document and its anchor, and a section moves between pages without its anchor changing.
- A page's table of contents shows its h2 and h3 headings, Starlight's default; a page without headings, such as the OpenAPI document's, turns it off.

Every table that renders a contract file or the case list puts the name first and its prose, a description or an expectation, last, and anchors each row as `<section>.<name>`, which a case's ID already is.

## Links between pages

Write a link to another page of the site with the site's base path, such as `[Reference](/pipeapi/reference/)`. Astro doesn't rewrite the links in Markdown, so a link without the base path points outside the site, and `just docs::check` reports it as broken. A sidebar entry's `link` in `docs/astro.config.mjs` leaves the base path out, since Starlight adds it.

The site's URL is `siteUrl` in `docs/astro.config.mjs`, from which Astro takes the base path. The link checks in `docs/justfile` hold a copy of its host and path, and the two name each other. Every link between pages carries the path too, so after the path changes, the link checks report any link, or the checks' copy, still holding the old one.

A page that moves keeps its old URL: `redirects` in `docs/astro.config.mjs` maps the old path to the new one, and Astro writes a page at the old path that sends the browser on. Astro adds the base path to a redirect's source, but writes its destination into that page as it is, so the destination carries the base path. A redirect moves a page and never an anchor, since the page it writes can't see the fragment, so when a section moves to another page, every link to its anchor changes where it's written. `just docs::check` checks the links in the built site, the redirect pages' included, and the repository's Markdown links into the site, such as these pages' (see [Checks](#checks)). Links in issue bodies have no check: a change that moves an anchor updates them by hand.

## How the contract renders

The site reads the protocol's contract and the connector API from `protocol/`, and the conformance cases from `conformance/cases/`, as it builds, and no page restates them. [protocol/README.md](../../protocol/README.md) says which file owns what and how to change the contract, and [the conformance project](conformance/cases.md#the-case-list) how to change a case. On the site's side:

- `docs/src/protocol.ts` lists the protocol versions the site renders, the contract files it reads from each version's directory and the statuses a contract's file states, and names the connector API's file. It also lists the documents of the spec, each protocol version's specification and the connector API's reference, with each one's slug, which is its overview's and its directory's, and finds the document a page belongs to. `docs/src/conformance.ts` names the case list's files and the slug of its page.
- `docs/src/content.config.ts` defines two content collections for each version, and one for the connector API. `v1Registry` holds the version's `registry.yaml`, in one entry whose ID is the version: its status and each section. `v1OpenApi` holds its `openapi.yaml`: the document's text, its summary and tags, and an index of its reserved routes and headers. `connectorApi` holds an index of the connector API's file, `connector-api.schema.json`: its status, and for each section of the connector API (its options, request options, lifecycle events, reasons for a lost `Backend`, errors, log events and constants), each name in the file's order, with what its table shows of it. Two more hold the conformance cases: `conformanceCases`, the case list's areas, cases, invariants and uncovered anchors, and `conformanceComponents`, the component table. Their loaders, in `docs/src/loaders/`, wrap Astro's `file()` loader, which reads files from outside the site and, under `just docs::dev`, reloads them as they change. The `docs` collection adds `heading` to Starlight's frontmatter, for [a page titled by a heading](#reference-documents).
- The registry collection's entry type is generated from `registry.schema.json` as Astro syncs, and `just lint` validates the data against the same schema, so the site declares no shape of the registry's. The OpenAPI index is the site's own view of the document, so its loader declares that view's shape; it finds every header among the document's components, where `protocol/README.md` says each one goes. The connector API's index is the site's own view of its file too, which `just lint` validates against its meta-schema. Its loader describes each type in words, such as `array of string`, from the JSON Schema, and fails on a form of schema it doesn't know rather than describe it wrongly. The case list's view is the site's own as well, which `just lint` validates against `cases.schema.json`: its loader gives each case the defaults that schema states for the fields it leaves out, and the view admits only the kinds and backends the page knows how to describe.
- The components in `docs/src/components/protocol/` render the files, and the pages of each version's specification and of the connector API, MDX pages in `reference/`, use them. Each table has one page, which `docs/src/components/protocol/contract.ts` gives it, in a map keyed by each version's registry sections, `routes` and `headers`, and one keyed by the connector API's sections, so a new section fails to compile until it has a page. A table component fails the build, naming both pages, when it renders on another, so a citation of a row always links the page that holds it:
  - `RegistryTable` renders any registry section, such as `<RegistryTable version="v1" section="rejections" />`, as a table sorted by name, with numeric names in numeric order. Its columns are the name, each other field under its key, and the description; an entry without a field another entry has leaves that cell empty. A section with no entries renders as a sentence saying so.
  - `HeaderTable` and `RouteTable` list the OpenAPI document's headers and reserved routes, in the document's order, each row anchored as `headers.<name>` or `routes.<operationId>`, and `OpenApiSource` shows the document in full with a link to it on GitHub.
  - `ConnectorApiTable` renders a section of the connector API, such as `<ConnectorApiTable section="errors" />`, in the file's order. Its columns are the name, what the section's entries have of an option's type, default and environment variable, a log event's level, a constant's value and a union member's fields, and the description. An options table takes the protocol version whose environment variables it links, as `version="v1"`, and fails the build on a variable that version's registry doesn't hold.
  - `ContractLink` links a file or a directory under `protocol/` or `conformance/cases/` on GitHub, such as `<ContractLink path="protocol/v1/vectors/" />`, showing its path, or the text it wraps. It fails the build when the repository has no such file or directory, so a page links a contract file only through it. With `fragment`, it links an anchor in the file, such as `<ContractLink path="protocol/README.md" fragment="freezing" />`, which the built-site check finds in the working tree's copy.
  - `Cite` names one name inline. The next section says how.
- The starlight-openapi plugin, set up in `docs/astro.config.mjs`, generates a page for each reserved route in the version's directory, under `routes/`, into a sidebar group that the configuration places last in the version's group. It renders OpenAPI 3.1 and leaves out what only 3.2 adds, such as a stream's `itemSchema`, so the version's OpenAPI document page includes the document in full. It groups the routes by tag, and gives a tag an overview page only when the tag has a `description`, which `openapi.yaml`'s one tag leaves out, since the document's own description says what the routes are.
- A route middleware, `docs/src/routeData.ts`, gives each page of a draft document, the route pages among them, a draft banner, reading each status from the contract's file: a version's `registry.yaml` and the connector API's `x-status`. Once starlight-openapi's middleware has added the routes, it changes the sidebar and checks it, through `docs/src/sidebar.ts`: it replaces the routes' tag group with the routes, labels the routes' group with the tag's `summary`, gives each draft document's group its badge, and checks every label against [the rule](#labels). It fails the build, naming the version, when the routes' group doesn't hold exactly one tag's group, the one tag `openapi.yaml` declares.
- `docs/src/components/PageIndex.astro` lists an overview's pages from the sidebar, as [Reference documents](#reference-documents) says.
- The components in `docs/src/components/conformance/` render the case list's page, `reference/protocol-v1/conformance.mdx`: `ComponentTable`, `CaseList`, `InvariantTable` and `CoverageMap`. [The case list](#the-case-list) says how.

A new registry section needs a `RegistryTable` on one of the version's pages, and that page in `contract.ts`'s map. A new kind of name in the connector API needs a section in its loader's index, then a `ConnectorApiTable` on one of its pages, and that page in the map. A new protocol version adds its name to `docs/src/protocol.ts`, its collections to `docs/src/content.config.ts`, its tables' pages to the map and its directory of pages to `reference/`.

### Citing a name

A page names a protocol name, or a name the connector API defines, through `<Cite name="..." />`, never by writing it out, so every name a page uses comes from the contract's files. `Cite` looks the name up by its form and fails the build, naming it, when the files don't hold it:

| Form | Looked up in |
| --- | --- |
| Starts with `PIPEAPI_` | The registry's environment variables |
| Starts with `/` | The OpenAPI document's routes |
| Any other name | The OpenAPI document's headers, ignoring case |
| Any name, with `section` | That section of the registry, such as `<Cite name="draining" section="rejections" />` |
| Any name, with `connectorApi` | That section of the connector API, such as `<Cite name="envPrefix" connectorApi="options" />` |

It renders the name as its file spells it, or a constant's value in place of its name, and links it to the row that defines it, on its table's page, or to a route's own page. On a version's own pages, it reads that version's files; any other page passes the version too, as `version="v1"`, after `name`. A connector API name links to its row on its section's page, from any page, and takes no version.

Astro doesn't type an MDX page's props, so these checks happen as the page renders. The `protocol-names` hook in `.pre-commit-config.yaml`, which `just lint` runs, covers what `Cite` can't see: it fails on any `PIPEAPI_` variable, `X-PipeAPI-` header or reserved route written in a page under `docs/src/content/docs/` anywhere but directly after `<Cite name="`. An example in a page therefore can't hold those names; render it from the files, or leave it out. The connector API's names have no such hook: many of them are ordinary words, such as `name` or `command`, which a pattern can't tell from prose, so review holds a page to citing them.

### The case list

The case list's page lists the component table, then each area's cases in the file's order, each case's row anchored by its ID, then the invariants, then the coverage map. A case's and an invariant's citations link the spec, and their needs link the component table. The case list's texts are data the page renders as they are, so they write protocol names out rather than citing them, and the conformance project's tests resolve each `PIPEAPI_` variable, `X-PipeAPI-` header and reserved route they name against the protocol's files, but for the few names a case writes because no version defines them.

A citation names a document and an anchor, such as `protocol-v1#rejections.draining`, never a page, and the page resolves it as it renders. An anchor without a period is a heading's, which the page finds among the document's pages, in the sidebar's order: a page's title where it sets `heading: true`, named by the page's file, then the headings its table of contents shows, as Astro's `render()` gives them. A document's pages are its overview and every page in its directory but the case list's own. An anchor with one is a table row's, which the page finds among the rows the contract's files give the document's tables, through the same lookups `Cite` uses: each registry section, the reserved routes and the headers for a protocol version, and each section of the connector API's index. So when a document's sections move between pages, each keeps its anchor, and the cases stay as they are. The build fails, naming the case and the citation, on a citation that names no document, no anchor of its document, or a heading that more than one of its pages holds.

`CoverageMap` lists every anchor of every document, in the pages' order and then the tables' rows, with the cases and invariants that cite it, each row anchored as `coverage.<document>.<anchor>`. It fails the build on an anchor that nothing cites and the case list's `uncovered` doesn't explain, and on one that `uncovered` explains but a case cites, so the map always shows each section and row the spec adds. The page sits in protocol v1's directory, which gives it the draft banner while v1 is a draft and a place in v1's sidebar group after the specification's pages; it isn't one of the specification's pages, so none of its headings is an anchor of the document.

When a contract file fails [the checks](#checks), the error names only the file: the loader sends the parser's reason to debug output, and `just lint`'s schema check shows the cause of a registry that doesn't parse or doesn't match its schema, as vacuum does for an OpenAPI document.

## Checks

`just docs::check` runs, in order:

1. `npm ci --dry-run`, which fails when `docs/package-lock.json` lacks a package `docs/package.json` needs or locks a version it doesn't admit, then `npm install --package-lock --no-save`, which installs the packages and versions the lockfile records whatever the user's npm configuration says, and writes nothing back;
2. Prettier's check, over `docs/` except `docs/contributing/`, which keeps the repository's Markdown conventions;
3. `astro sync`, which loads every content collection, so invalid page frontmatter and a missing or unreadable contract file fail here, then ESLint, with typescript-eslint's strict type-checked rules;
4. `astro check`, over the site's types, failing on warnings;
5. the build, failing on any warning or error that Astro's logger reports, while starlight-links-validator checks the links and anchors that pages write, the components fail on a table rendered off its page or a citation that doesn't resolve, and the route middleware checks the sidebar;
6. lychee, offline, over the built site, for the links that the header, sidebar, configuration, components, redirects and generated route pages add, with each link to a contract file on GitHub's `main` checked against the working tree's copy, its anchor included;
7. lychee, offline, over the repository's Markdown outside `docs/src/` that git doesn't ignore, for its links into the site, which it checks against the built site.

`just docs::dev` and `just docs::fix` skip the dry run and run a plain `npm install`, which also updates the lockfile after a change to `package.json`. No command runs a real `npm ci`, which empties `node_modules` before it installs: Windows refuses to delete Astro's native compiler while an editor's ESLint or Prettier has it loaded, so the check would fail while the editor has the site open. An install that replaces the compiler, as an Astro update does, still succeeds then: npm moves the old copy aside and warns that it couldn't remove it. CI starts with no `node_modules`, so its install is a clean one all the same. To start clean locally, close the editor and delete `docs/node_modules`.

`just lint` checks, with lychee offline, the links and anchors in every tracked Markdown file outside `docs/src/`, the contributor pages included, but for their links into the site, which only the built site can check. `just docs::external-links` and `just external-links` check the same links online, external ones included.

CI runs `just lint` and `just docs::check` on every pull request, on Windows, Linux and macOS, since contributors build the site on each. On Linux it also keeps the built site as the run's `site` artifact for 7 days, which is the pull request's preview.

The Links workflow, `.github/workflows/links.yml`, runs both online checks every Monday at 06:00 America/Denver, and whenever it's dispatched from the Actions tab. Each run checks every link afresh, with the job's read-only token. When it fails, it opens an issue titled "Broken links in the documentation", labeled `area: docs`, or comments on the one already open. Each report links the run, whose log shows every broken link. The workflow never closes the issue: close it once the links are fixed and a dispatched run passes.

## Publishing

The Pages workflow, `.github/workflows/pages.yml`, publishes the site on every push to `main`, and whenever it's dispatched from the Actions tab. Its first job runs `just docs::check`, the recipe CI runs on every pull request, and uploads the built site; its second deploys that build to GitHub Pages through the `github-pages` environment, which deploys only from `main`. So the published site is always a build that passed the docs check.

- Runs queue rather than overlap, and a newer run replaces one still waiting, so an older build never replaces a newer one.
- The build restores no cache, since a pull request's run can write one and this build goes live.
- Only the deploy job holds the tokens that publish, so the code the build runs never sees them.

## Why it's built this way

### Starlight

Starlight renders the contract from the contract's own files: Astro's content collections load files from outside the site and feed tables, and a plugin generates a page for each route of an OpenAPI document. It also has language tabs whose choice carries across pages, built-in search and frequent releases, and comparable projects use it, such as Connect RPC, Tauri and Biome. Its costs are a Node toolchain for the docs, MDX syntax for tabs, a check composed of several tools, and glue to bring the Python API reference into the site.

The alternatives each fell short: Zensical is in alpha and silently ignores MkDocs plugins it doesn't list; Material for MkDocs reaches its end of life on 2027-05-05; Docusaurus has no built-in search and no global strict switch; Sphinx fits an OpenAPI 3.2 file worst; and VitePress's tab choice doesn't carry across pages.

### starlight-openapi for the route pages

starlight-openapi generates a static page for each reserved route as the site builds, so the routes are in the sidebar and in search, and their pages are built and link-checked like every other page. It leaves out what only OpenAPI 3.2 has, which the version's OpenAPI document page covers by including the document in full. Scalar's reference was rejected: it adds about 4.6 MB of JavaScript and 180 more packages, and it renders in the browser, where the site's search doesn't index it.

### The sidebar's shape

The sidebar takes the shape that comparable documentation shares. Groups nest at most three deep, and a document of several pages is a group whose first entry is its overview, as in [Astro's docs](https://github.com/withastro/docs/blob/main/astro.sidebar.ts) and [MCP's specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/docs.json); large generated families are collapsed or reached from an index, as Astro's [error reference](https://docs.astro.build/en/reference/error-reference/) and Biome's [rule index](https://biomejs.dev/linter/javascript/rules/) are. The API an app uses comes before the wire protocol, as [Connect](https://github.com/connectrpc/connectrpc.com/blob/main/astro.config.mjs), [grpc.io](https://grpc.io/docs/) and MCP order theirs, since more readers use a connector than implement the protocol; Starlight sorts autogenerated entries by ID, which would put the protocol first. Protocol versions come newest first, as MCP lists its specification's. Each group autogenerates its directory, Starlight's documented mechanism, so a page joins its group without a change to the configuration, and a draft carries a badge, as MCP labels its draft and Biome badges new pages.

Rejected: autogenerating `reference/` whole, which labels each document's group with its directory's name, such as `protocol-v1`; listing every page in the configuration; and Starlight's sidebar topics, as Tauri uses, which suit several large sections rather than one.

### A directory of pages per long document

Protocol v1's specification, about 7,000 words of prose under 55 headings, is the size of the specifications that split by topic, such as MCP's, about 30 pages of about 1,000 words each per version ([lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)), and [OpenTelemetry's](https://opentelemetry.io/docs/specs/otel/). The specifications on one page are a quarter to a third of the size, such as [Connect's](https://connectrpc.com/docs/protocol/), [gRPC's](https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md) and [OTLP's](https://opentelemetry.io/docs/specs/otlp/), or hard to navigate, as [LSP's](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/) is. A topic page reads in a few minutes, its table of contents stays short, and the sidebar shows the document's structure, while Starlight's previous and next links still read the document in order, and search finds each heading either way.

Anchors belong to sections, not pages. Each heading keeps its text and its anchor on whichever page holds it, a page that holds one section is named by its anchor, and a conformance case cites a document and an anchor, never a page, so the case list, which freezes with its protocol version, stays as it is when pages change. A page that groups several sections adds no anchor of its own, since a case would have nothing on it to cite. Rows are anchored by their names, as OpenTelemetry's [attribute tables](https://opentelemetry.io/docs/specs/semconv/registry/attributes/http/) and MCP's [schema reference](https://modelcontextprotocol.io/specification/2025-06-18/schema) anchor theirs.

Rejected:

- One page per document, with only the OpenAPI listing on its own: the tables of contents keep 55 and 42 entries.
- A page per heading: about 95 pages of 50 to 300 words, and a sidebar longer than the content.
- A script that sends an old fragment to the page that holds it now, as [WHATWG's multipage HTML](https://html.spec.whatwg.org/link-fixup.js) does: a generated map and a script on every overview, for links that are all known and editable.
- Explicit heading IDs through remark-custom-heading-id, as Connect writes them: a dependency for anchors that pages already keep.
- Page paths in the case list's citations, which would tie the frozen cases to the site's layout.

### Sentence case

Sentence case is what [Astro's docs](https://github.com/withastro/docs/blob/main/src/content/nav/en.ts), [Temporal's references](https://docs.temporal.io/references) and [Docker's API reference](https://docs.docker.com/reference/api/engine/) use, and what [Google's developer style guide](https://developers.google.com/style/capitalization) states, and every heading the site has follows it. The sites in title case, such as Starlight's own docs, Tauri and MCP, mix in labels in sentence case, and the consistent sites are the ones that state one rule. A label that starts with a lowercase identifier, as a tag's name or a directory's would, is what a build can catch, so it fails the build; the rest of the rule is a matter of wording, which review holds. Title case was rejected: it would reword every heading.

### The reserved routes without a tag level

`openapi.yaml`'s tag keeps OpenAPI 3.2's split between `name`, the identifier operations use, and `summary`, its display name ([Tag Object](https://spec.openapis.org/oas/v3.2.0.html#tag-object)). starlight-openapi 0.27.0 renders OpenAPI 3.1: it labels a tag's group with its `name`, and nests that group in the document's even when the document has one tag, with no option for either, and its maintainer declined an option to drop tag overview pages ([starlight-openapi#107](https://github.com/HiDeoo/starlight-openapi/issues/107)). That is a stated limit of the plugin. The route middleware makes up for it through Starlight's documented way to change a plugin's sidebar ([route data](https://starlight.astro.build/guides/route-data/)), and fails the build when the plugin's group takes another shape, so an update that changes it fails by name.

Rejected: renaming the tag to "Reserved routes", which bends the contract's identifier to one renderer and still nests twice; removing the tags, which fails vacuum's recommended `operation-tags` rule; and patching the plugin, which every update would need again.

### npm

npm ships with Node, so the docs need no package manager of their own. GitHub's dependency graph, from which Dependabot raises security alerts, reads `docs/package-lock.json`, while pnpm 12's lockfile reads as empty there. `min-release-age=7` in `docs/.npmrc` holds local installs to versions at least 7 days old, as Dependabot's cooldown holds its updates, so both resolve alike. npm 11.10.0 is the first release that honors `min-release-age`, so `devEngines.packageManager` in `docs/package.json` requires it or later: an older npm stops with `EBADDEVENGINES` rather than ignoring the cooldown.

### A build that fails on logged warnings

A warning from Astro, Vite or an integration usually marks something that builds but is broken, such as invalid frontmatter or a missing entry. `astro check` takes a minimum failing severity, but the build has no such option, so a log handler, `docs/fail-on-warning.mjs`, fails it on any warning or error that passes through Astro's logger; its comments say how. A warning written to the console directly, as some of Starlight's are, prints but fails nothing.

### Link checks split by what the project controls

A pull request is gated only on the links the project controls, checked offline, so the gate needs no network and fails only for something the pull request can fix. External links break without any change in the repository, so a schedule checks them, and a failure opens an issue rather than blocking unrelated work. Inside the gate, the validator knows only the site's content pages, so lychee covers the links it can't see, as [the checks](#checks) list. The contributor pages link the site by its URL, which an offline check of their Markdown skips, so the docs check maps those links onto the build: a change that moves a page or an anchor fails its own pull request, rather than the next scheduled run after the deploy.

### GitHub Pages

Pages needs no account, secrets or money, and it serves a site that an Actions workflow builds, so the published site can come from the recipe CI runs on every pull request. Read the Docs shows ads on its community plan, builds only on Ubuntu, and would compose the docs build a second time outside CI; Netlify charges deploy credits; and Vercel's free plan is for non-commercial use only.

### One unversioned site

The site has no version switcher. pipeapi's five packages each follow their own semantic versioning and release on their own, and the protocol has an integer version of its own, so a version for the whole site has no single axis. Each versioned thing carries its version on its own axis instead: the spec keeps a set of pages per protocol version, the Rust and Go API references are kept per version on docs.rs and pkg.go.dev, and pages mark what no release includes yet, as [the documentation system](documentation.md#unreleased-features) describes. A site-wide switcher, such as starlight-versions, would need one package's version as the axis, or every package released in lockstep.
