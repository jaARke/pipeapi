# Contributing

pipeapi welcomes contributions: bug reports, fixes, features, documentation and new ideas. Everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Questions

Ask how to use pipeapi, or get help with a problem that may not be a bug, in [Discussions](https://github.com/jaARke/pipeapi/discussions) rather than in an issue.

## Issues

- Open an issue with one of the forms. Its type says what kind of work it is (Feature, Bug or Task), and its `area:` labels name the components it touches.
- A bug report needs the packages and versions, the OS, the transport and a minimal reproduction, so the bug can be reproduced before it's fixed.
- `good first issue` marks work that suits a first contribution, and `help wanted` marks work where help is especially welcome.
- An issue's body holds its current design. Open questions are a checklist in the body, and each one is ticked when its answer lands in the Proposal. Comments hold the discussion that leads there.

Report a security vulnerability privately, as [SECURITY.md](SECURITY.md) describes, never in an issue.

## Development

Every check is a named command run with [just](https://just.systems/), and CI runs the same commands, so any CI step can be reproduced locally. [The repository](docs/contributing/repository.md) says how the projects and their commands fit together.

### Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| [Git](https://git-scm.com/) | Any recent | Cloning; the hooks check only the files Git tracks |
| [just](https://just.systems/) | 1.56 or later | Every command |
| [uv](https://docs.astral.sh/uv/) | 0.13.5 or later | Every check, and the `conformance` commands |
| [Node.js](https://nodejs.org/) and npm | The Node version `docs/.node-version` names, with npm 11.10.0 or later | The `docs` commands |

`just check` and `just fix` run every project's commands, so they need all of these. Every other tool the checks use, Python and Go included, runs at a version the repository pins, and the checks fetch it themselves: [Pinned versions](docs/contributing/versions.md) lists each.

uv can also install just: `uv tool install rust-just`. Tools that uv installs run from its tool directory, which `uv tool update-shell` adds to PATH. A version manager that reads `.node-version`, such as [fnm](https://github.com/Schniz/fnm), installs the Node the site pins.

### Set up

1. Install the prerequisites.
2. Run `just check`. The first run installs each project's dependencies and builds the hooks, the OpenAPI linter among them, which takes several minutes. Later runs reuse what it built.
3. In VS Code, open `pipeapi.code-workspace` rather than the repository's folder, and install the recommended extensions. Each project is a folder of its own there, with its settings.
4. To run the hooks on every commit too, install the prek `just lint` runs, with `uv tool install prek==0.5.5`, then the Git hook with `prek install`.

### Commands

`just` lists every command with what it does. The ones you'll use most:

| Command | What it does |
| --- | --- |
| `just check` | Runs every check a pull request must pass |
| `just fix` | Applies every project's fixes and formatting |
| `just docs::dev` | Serves the guide site locally, reloading each page as you edit it |

What `just lint` and each project's checks cover, and why, is on the pages in [`docs/contributing/`](docs/contributing/).

## Design

[`docs/contributing/`](docs/contributing/) is the home of the design rationale and of each component's contributor page: how the component is built and checked, the conventions it follows, why it's built that way and what was rejected. Read the page for the part you're changing, and update it in the pull request that makes it untrue.

## Pull requests

- For anything beyond a small fix, comment on the issue first (or open one), so the approach is agreed before the code is written.
- Fill in the template's Summary, Changes and Testing, and link the issue the pull request resolves.
- A change lands with its tests and its documentation.
- Pull requests are squash-merged, so the title becomes the commit message on `main`. Write it as a short imperative sentence, such as "Retry busy pipes on every connection".

## License

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
