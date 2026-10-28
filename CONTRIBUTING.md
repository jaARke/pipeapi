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

Every check is a named command run with [just](https://just.systems/) 1.56 or later, and CI runs the same commands, so any CI step can be reproduced locally. Run `just` to list them. In VS Code, open `pipeapi.code-workspace`: each project is a folder of its own there, with its settings and recommended extensions.

- `just lint` lints repository-wide files: the GitHub Actions workflows, for errors and for security issues such as template injection and excessive permissions; the links and anchors in the Markdown read on GitHub, such as this file; and the protocol's contract in `protocol/`, as its [README](protocol/README.md) describes. It needs [uv](https://docs.astral.sh/uv/), which fetches [prek](https://prek.j178.dev/) to run the hooks at the versions `.pre-commit-config.yaml` pins. prek builds the OpenAPI linter, vacuum, with a Go toolchain it downloads, so the first run takes several minutes, and later runs reuse what it built. prek checks only the files Git tracks, so a new file is checked once it's added. To run the hooks on every commit too, install prek (for example with `uv tool install prek`) and then the Git hook with `prek install`.
- `just docs::check` checks the guide site in `docs/`, as [The guide site](docs/contributing/guide-site.md#checks) lists. It needs uv and [Node.js](https://nodejs.org/) at the version `docs/.node-version` names, with npm 11.10.0 or later, which installs the dependencies `docs/package-lock.json` records. `just docs::fix` applies ESLint's fixes and Prettier's formatting, and `just docs::dev` serves the site locally and reloads each page as you edit it.
- `just conformance::check` checks the conformance project in `conformance/`: ruff's lint and formatting, Pyright in strict mode (the reference app also at its older Python floor), and the reference app's tests, in process and under uvicorn. It needs uv 0.12.22 or later, as `conformance/pyproject.toml`'s `required-version` states, which installs the Python `conformance/.python-version` names and the packages `conformance/uv.lock` records. `just conformance::fix` applies ruff's fixes and formatting.
- `just external-links` and `just docs::external-links` check the same links online, external ones included: the first in the Markdown read on GitHub, the second in the site. A scheduled workflow runs both, since an external link can break without any change in the repository.

Each package is a normal project for its ecosystem in a directory of its own. Its commands live in a justfile there, which the root justfile loads as a module, so `just <package>::<recipe>` runs one from the repository root. just doesn't carry settings into modules, so each package's justfile starts with `import "../settings.just"`, which sets the minimum just version and the Windows shell.

Dependabot opens pull requests that update the GitHub Actions, the pre-commit hooks and each project's packages, lockfiles included. It moves no toolchain, such as Node or Python, and a few other versions too: [Pinned versions](docs/contributing/versions.md) lists each version that moves by hand, with every place that moves with it.

## Design

[`docs/contributing/`](docs/contributing/) is the home of the design rationale and of each component's contributor page: how the component is built and checked, the conventions it follows, why it's built that way and what was rejected. Read the page for the part you're changing, and update it in the pull request that makes it untrue.

## Pull requests

- For anything beyond a small fix, comment on the issue first (or open one), so the approach is agreed before the code is written.
- Fill in the template's Summary, Changes and Testing, and link the issue the pull request resolves.
- A change lands with its tests and its documentation.
- Pull requests are squash-merged, so the title becomes the commit message on `main`. Write it as a short imperative sentence, such as "Retry busy pipes on every connection".

## License

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
