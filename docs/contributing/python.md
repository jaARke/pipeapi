# Python projects

Each Python project in the repository is a [uv](https://docs.astral.sh/uv/) project in a directory of its own, checked with ruff, Pyright in strict mode and pytest. The conformance project, `conformance/`, is the first. Its [`pyproject.toml`](../../conformance/pyproject.toml) holds each setting with its reason in a comment beside it, and its [justfile](../../conformance/justfile) chains the checks. This page holds the reasons that don't fit beside a single setting.

## Type checking: Pyright in strict mode

Strict mode requires every value to have a known type, including the values that come from dependencies. Pyright is also the engine of Pylance, VS Code's Python language server, so the editor reports as you type what the check reports. Strict mode is one setting rather than a list of flags to keep in step, and the few checks it leaves off that the project wants are turned on as errors beside it. A dependency that ships no types gets a typed stub package rather than a suppression. `conformance/` uses no import-linter: it's one package with no layers to guard, and Pyright's `reportImportCycles` catches import cycles.

## Lint and format: ruff

ruff is one tool for lint, import order and formatting, and its VS Code extension applies the same fixes and formatting on save. The selected rules start broad, and each ignored rule states why. ruff's preview rules run only where they're selected by their full code, so a ruff update never turns on a preview rule nobody chose.

Formatting is ruff's default: spaces, and lines of up to 88 characters. Each project is a normal project for its ecosystem, and this is the style Python's tools and contributors already expect, so there's nothing to configure.

## Python versions

A project runs on one Python, which its `.python-version` pins and its `requires-python` admits, and uv installs it. Code that also runs in an older environment is held to that environment's Python as well. The reference app runs inside the pipeapi server in the server's oldest supported environment, so it's held to the oldest Python the server supports, while the rest of `conformance/` runs on the pinned one.

Two checks hold code to an older Python:

- ruff's `per-file-target-version` sets the Python version those files are linted for, so syntax newer than it is reported and no fix rewrites them past it.
- A second Pyright run over those files with `--pythonversion` checks them against the standard library that Python has. An execution environment in Pyright's configuration can set its own Python version, but typeshed's version checks still use the project's, so only a run of its own catches a standard-library API the older Python lacks.

The two settings hold the same version and each names the other.

## uv

- **`required-version`** is the oldest uv the project needs, not the newest. Dependabot updates the lock by running uv itself, and its uv runs behind uv's newest release, so a `required-version` above Dependabot's uv makes every update fail. CI's conformance job runs exactly the oldest uv the setting allows, which proves the floor. Raise it only when the project needs a newer uv, and no further than the uv in Dependabot's [uv image](https://github.com/dependabot/dependabot-core/blob/main/uv/Dockerfile).
- **`exclude-newer = "7 days"`** makes uv resolve only versions released at least 7 days before it runs, which is how long Dependabot's cooldown holds back an update. A local `uv lock` and Dependabot's therefore choose the same versions, and no update proposes a version uv would refuse. In its relative form the setting records a span rather than a date, so the lock stays valid as the window moves. The setting and the uv entry in `.github/dependabot.yml` each name the other.
- **`uv run --locked`** runs every tool, from the project's directory. uv first syncs the project's environment to `uv.lock`, and `--locked` fails when the lock is out of date with `pyproject.toml` rather than updating it, so every check runs exactly the locked versions on every machine. The project's `check` recipe chains these commands, and CI runs that recipe.

A project that publishes a package promises its users the range of each dependency it declares, so its Dependabot entry sets `versioning-strategy: widen`, which widens a range to admit a new version rather than raising its lower bound. `conformance/` publishes nothing, so its entry keeps Dependabot's default.

## The environment

One module in a project reads the environment: in `conformance/`, `reference_app/environment.py`. ruff's banned-API setting rejects `os.environ`, `os.environb`, `os.getenv` and `os.getenvb` in every other file, tests included, so every variable the code reads is named and documented in one place.

## The editor

VS Code opens the repository through `pipeapi.code-workspace`, a multi-root workspace with one folder per project. Pylance reads `[tool.pyright]` only from the `pyproject.toml` at the root of a folder. In a window opened at the repository's root it would read no project's settings, so strict mode would have to be restated in the root's VS Code settings, a second copy that can drift. As a folder of the workspace, each Python project is governed by its own `pyproject.toml`.

Each project folder has its own `.vscode/settings.json` and recommended extensions. A Python project's settings point VS Code at the project's uv environment, run pytest as the project's check does, and format and fix with ruff on save. A new Python project adds its folder to the workspace, and those settings to its own `.vscode/`, as `conformance/.vscode/` has them. It adds no ignore rules for them: the root `.gitignore`'s rules for `.vscode/` apply in every folder, sharing the settings and keeping everything else local.
