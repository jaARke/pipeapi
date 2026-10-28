# Pinned versions

Every tool and toolchain that the checks use runs at a pinned version, so a check gives the same result on every machine and in CI. Dependabot moves most of the pins, as `.github/dependabot.yml` sets it up: it looks every Monday, and holds each update back until the release is 7 days old. The rest move by hand, and this page lists them.

## What Dependabot moves

| Pins | Where | Ecosystem |
| --- | --- | --- |
| GitHub Actions, such as `actions/cache` | Each `uses:` in `.github/workflows/` | `github-actions` |
| Remote pre-commit hooks, such as actionlint, zizmor, check-jsonschema and vacuum | Each `rev` in `.pre-commit-config.yaml`, and those hooks' `additional_dependencies` | `pre-commit` |
| The site's packages, its development dependencies included | `docs/package.json` and `docs/package-lock.json` | `npm` |
| The conformance project's packages | `conformance/pyproject.toml` and `conformance/uv.lock` | `uv` |

Packages that must match move in one pull request, in the groups `.github/dependabot.yml` defines: Astro with Starlight and its plugins, starlight-openapi included; ESLint with typescript-eslint and ESLint's plugins; Prettier with its plugin.

An action or a hook is pinned to a full commit SHA with its version in a comment beside it, and Dependabot rewrites the comment with the SHA only when the comment ends with the version. Keep each in the form it already has: `# v1.2.3` after an action's SHA, and `# frozen: v1.2.3` after a hook's.

## What moves by hand

Dependabot moves no toolchain. It reads no justfile, changes no action's inputs, skips local pre-commit hooks, never reads a hook's `language_version`, never edits `.node-version`, `.python-version`, `devEngines` or uv's settings, and leaves an npm override nested under a package alone. Each row below is one version, and every place it's set or stated moves together, in one pull request.

| Version | Set in | Moves with it |
| --- | --- | --- |
| just | `minimum-version` in `settings.just` | Every `just-version` in `.github/workflows/`, so CI runs the stated minimum; "1.56 or later" in CONTRIBUTING.md |
| prek | `prek` in the root `justfile` | |
| lychee | The lychee hooks' `additional_dependencies` in `.pre-commit-config.yaml` | `lychee` in `docs/justfile` |
| Go, which prek builds the vacuum hook with | The vacuum hook's `language_version` in `.pre-commit-config.yaml` | |
| form-data under httpsnippet | The `overrides` entry for `httpsnippet` in `docs/package.json` | |
| Node, and the npm it ships with | `docs/.node-version`, which CI's Node setup reads | |
| npm's minimum | `devEngines.packageManager.version` in `docs/package.json` | "npm 11.10.0 or later" in CONTRIBUTING.md |
| The conformance project's Python | `conformance/.python-version` | `requires-python` in `conformance/pyproject.toml`, which must admit it, so a new minor version changes both |
| uv's minimum | `required-version` in `conformance/pyproject.toml`, which CI's conformance job reads | "uv 0.12.22 or later" in CONTRIBUTING.md |
| The reference app's Python floor | `per-file-target-version` in `conformance/pyproject.toml` | `reference_app_python` in `conformance/justfile` |
| The 7-day cooldown | Each entry's `cooldown` in `.github/dependabot.yml` | `exclude-newer` in `conformance/pyproject.toml`; `min-release-age` in `docs/.npmrc` |

uv's minimum and the reference app's floor follow the project's needs rather than the newest release: [Python projects](python.md) says when each moves. npm's minimum is the first release that honors `min-release-age`, as [The guide site](guide-site.md#npm) says, so it moves only if npm changes which release honors it. The cooldown is a policy rather than a version, but its three settings hold one value, so they move together like the others.

The form-data override is a security pin. starlight-openapi depends on httpsnippet, which pins a form-data version with a known vulnerability ([GHSA-hmw2-7cc7-3qxx](https://github.com/advisories/GHSA-hmw2-7cc7-3qxx)), and the override replaces it with the first fixed release. It stays while httpsnippet pins a form-data older than 4.0.6, and comes out once the httpsnippet the lockfile holds pins 4.0.6 or later.
