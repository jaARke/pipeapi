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

Every check is a named command run with [just](https://just.systems/) 1.56 or later, and CI runs the same commands, so any CI step can be reproduced locally. Run `just` to list them.

- `just lint` lints repository-wide files, such as the GitHub Actions workflows. It needs [uv](https://docs.astral.sh/uv/), which fetches [prek](https://prek.j178.dev/) to run the hooks at the versions `.pre-commit-config.yaml` pins. To run them on every commit too, install prek (for example with `uv tool install prek`) and then the Git hook with `prek install`.

Each package is a normal project for its ecosystem in a directory of its own. Its commands live in a justfile there, which the root justfile loads as a module, so `just <package>::<recipe>` runs one from the repository root. just doesn't carry settings into modules, so each package's justfile starts with `import "../settings.just"`, which sets the minimum just version and the Windows shell.

## Pull requests

- For anything beyond a small fix, comment on the issue first (or open one), so the approach is agreed before the code is written.
- Fill in the template's Summary, Changes and Testing, and link the issue the pull request resolves.
- A change lands with its tests and its documentation.
- Pull requests are squash-merged, so the title becomes the commit message on `main`. Write it as a short imperative sentence, such as "Retry busy pipes on every connection".

## License

By contributing, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
