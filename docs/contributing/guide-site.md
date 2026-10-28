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

Each section is a directory of the content root and a group in the sidebar, which `docs/astro.config.mjs` generates from that directory. The site has its homepage and the Reference section; the first page of another section adds its directory and its sidebar group. A page that would do two jobs is two pages that link each other, such as a how-to guide that links the reference for each option it sets.

## Links between pages

Write a link to another page of the site with the site's base path, such as `[Reference](/pipeapi/reference/)`. Astro doesn't rewrite the links in Markdown, so a link without the base path points outside the site, and `just docs::check` reports it as broken. A sidebar entry's `link` in `docs/astro.config.mjs` leaves the base path out, since Starlight adds it.

The site's URL is `siteUrl` in `docs/astro.config.mjs`, from which Astro takes the base path. The built-site check in `docs/justfile` holds a copy of its host and path, and the two name each other. Every link between pages carries the path too, so after the path changes, the link checks report any link, or the check's copy, still holding the old one.

## How the contract renders

The site reads the protocol's contract from `protocol/` as it builds, and no page restates it. [protocol/README.md](../../protocol/README.md) says which file owns what and how to change the contract. On the site's side:

- `docs/src/protocol.ts` lists the protocol versions the site renders, which of them are drafts, and the contract files it reads from each version's directory.
- `docs/src/content.config.ts` defines a content collection for each section of a version's `registry.yaml`, such as `v1EnvironmentVariables` and `v1Constants`, and one that holds its `openapi.yaml` as text, `v1OpenApiSource`. Their loaders, in `docs/src/loaders/`, wrap Astro's `file()` loader, which reads files from outside the site and, under `just docs::dev`, reloads them as they change.
- A registry collection's entry type is generated from `registry.schema.json` as Astro syncs. `just lint` validates the data against the same schema, so the site declares no shape of its own.
- The components in `docs/src/components/protocol/` render each registry section as a table sorted by name, and the OpenAPI document in full with a link to it on GitHub. The version's page, an MDX page in `reference/`, uses them, such as `<EnvironmentVariableTable version="v1" />`.
- The starlight-openapi plugin, set up in `docs/astro.config.mjs`, generates a page for each reserved route under the version's page and adds them to the Reference sidebar. It renders OpenAPI 3.1 and leaves out what only 3.2 adds, such as a stream's `itemSchema`, so the version's page also includes the document in full.
- A route middleware, `docs/src/routeData.ts`, gives a draft version's page, and the route pages under it, a draft banner.

A new registry section needs a collection in `docs/src/content.config.ts` and a component in `docs/src/components/protocol/` that renders it, which the version's page then uses. A new protocol version adds its name to `docs/src/protocol.ts`, its collections to `docs/src/content.config.ts` and its page to `reference/`.

When a contract file fails [the checks](#checks), the error names only the file: the loader sends the parser's reason to debug output, and `just lint`'s schema check shows the cause of a registry that doesn't parse or doesn't match its schema.

## Checks

`just docs::check` runs, in order:

1. `npm ci`, which installs exactly what `docs/package-lock.json` records into an empty `node_modules`, as CI does;
2. Prettier's check, over `docs/` except `docs/contributing/`, which keeps the repository's Markdown conventions;
3. `astro sync`, which loads every content collection, so invalid page frontmatter and a missing or unreadable contract file fail here, then ESLint, with typescript-eslint's strict type-checked rules;
4. `astro check`, over the site's types, failing on warnings;
5. the build, failing on any warning or error that Astro's logger reports, while starlight-links-validator checks the links and anchors that pages write;
6. lychee, offline, over the built site, for the links that the header, sidebar, configuration, components and generated route pages add.

Only `check` and `external-links` install from scratch. `just docs::dev` and `just docs::fix` run `npm install`, which changes nothing while `node_modules` matches the lockfile.

`just lint` checks, with lychee offline, the links and anchors in every tracked Markdown file outside `docs/src/`, the contributor pages included. `just docs::external-links` and `just external-links` check the same links online, external ones included.

CI runs `just lint` and `just docs::check` on every pull request, on Windows, Linux and macOS, since contributors build the site on each. On Linux it also keeps the built site as the run's `site` artifact for 7 days, which is the pull request's preview.

The Links workflow, `.github/workflows/links.yml`, runs both online checks every Monday at 06:00 America/Denver, and whenever it's dispatched from the Actions tab. Each run checks every link afresh, with the job's read-only token. When it fails, it opens an issue titled "Broken links in the documentation", labeled `area: docs`, or comments on the one already open. Each report links the run, whose log shows every broken link. The workflow never closes the issue: close it once the links are fixed and a dispatched run passes.

## Why it's built this way

### Starlight

Starlight renders the contract from the contract's own files: Astro's content collections load files from outside the site and feed tables, and a plugin generates a page for each route of an OpenAPI document. It also has language tabs whose choice carries across pages, built-in search and frequent releases, and comparable projects use it, such as Connect RPC, Tauri and Biome. Its costs are a Node toolchain for the docs, MDX syntax for tabs, a check composed of several tools, and glue to bring the Python API reference into the site.

The alternatives each fell short: Zensical is in alpha and silently ignores MkDocs plugins it doesn't list; Material for MkDocs reaches its end of life on 2027-05-05; Docusaurus has no built-in search and no global strict switch; Sphinx fits an OpenAPI 3.2 file worst; and VitePress's tab choice doesn't carry across pages.

### starlight-openapi for the route pages

starlight-openapi generates a static page for each reserved route as the site builds, so the routes are in the sidebar and in search, and their pages are built and link-checked like every other page. It leaves out what only OpenAPI 3.2 has, which the version's page covers by including the document in full. Scalar's reference was rejected: it adds about 4.6 MB of JavaScript and 180 more packages, and it renders in the browser, where the site's search doesn't index it.

### npm

npm ships with Node, so the docs need no package manager of their own. GitHub's dependency graph, from which Dependabot raises security alerts, reads `docs/package-lock.json`, while pnpm 12's lockfile reads as empty there. `min-release-age=7` in `docs/.npmrc` holds local installs to versions at least 7 days old, as Dependabot's cooldown holds its updates, so both resolve alike. npm 11.10.0 is the first release that honors `min-release-age`, so `devEngines.packageManager` in `docs/package.json` requires it or later: an older npm stops with `EBADDEVENGINES` rather than ignoring the cooldown.

### A build that fails on logged warnings

A warning from Astro, Vite or an integration usually marks something that builds but is broken, such as invalid frontmatter or a missing entry. `astro check` takes a minimum failing severity, but the build has no such option, so a log handler, `docs/fail-on-warning.mjs`, fails it on any warning or error that passes through Astro's logger; its comments say how. A warning written to the console directly, as some of Starlight's are, prints but fails nothing.

### Link checks split by what the project controls

A pull request is gated only on the links the project controls, checked offline, so the gate needs no network and fails only for something the pull request can fix. External links break without any change in the repository, so a schedule checks them, and a failure opens an issue rather than blocking unrelated work. Inside the gate, the validator knows only the site's content pages, so lychee covers the links it can't see, as [the checks](#checks) list.

### GitHub Pages

Pages needs no account, secrets or money, and it serves a site that an Actions workflow builds, so the published site can come from the recipe CI runs on every pull request. Read the Docs shows ads on its community plan, builds only on Ubuntu, and would compose the docs build a second time outside CI; Netlify charges deploy credits; and Vercel's free plan is for non-commercial use only.

### One unversioned site

The site has no version switcher. pipeapi's five packages each follow their own semantic versioning and release on their own, and the protocol has an integer version of its own, so a version for the whole site has no single axis. Each versioned thing carries its version on its own axis instead: the spec keeps a page per protocol version, the Rust and Go API references are kept per version on docs.rs and pkg.go.dev, and pages mark what no release includes yet, as [the documentation system](documentation.md#unreleased-features) describes. A site-wide switcher, such as starlight-versions, would need one package's version as the axis, or every package released in lockstep.
