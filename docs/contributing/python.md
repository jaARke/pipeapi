# Python projects

Each Python project in the repository is a [uv](https://docs.astral.sh/uv/) project in a directory of its own, checked with ruff and Pyright in strict mode, and with pytest where it has tests. There are two: the conformance project, `conformance/`, and the scripts the checks run over the repository, `scripts/`. The settings they share sit in two files at the root, [`ruff.base.toml`](../../ruff.base.toml) and [`pyright.base.json`](../../pyright.base.json), which each project's `pyproject.toml`, such as [`conformance/pyproject.toml`](../../conformance/pyproject.toml), extends. Each file holds every setting with its reason in a comment beside it, and each project's justfile, such as [`conformance/justfile`](../../conformance/justfile), chains its checks. This page holds the reasons that don't fit beside a single setting.

## The shared settings

Every Python project shares one configuration of each tool, in a base at the repository's root, as [The repository](repository.md#tool-configuration) sets out for every language. `ruff.base.toml` holds the selected rules and their ignores, the docstring convention, the banned API and the tests' per-file ignores. `pyright.base.json` holds strict mode and the checks added to it. Each project's `pyproject.toml` names them through the tools' own mechanisms, `[tool.ruff] extend` and `[tool.pyright] extends`, and adds only what is its own: its paths, its Python target versions, its environment module and its virtual environment.

Repositories with several Python projects, such as Apache Airflow, Microsoft's Agent Framework and Datadog's integrations-core, share their settings the same way. The alternatives fail in known ways:

- **A copy in every project,** as LangChain keeps, drifts, and only review holds the copies equal.
- **One root configuration that every project inherits by discovery** fails once a project needs a setting of its own, since neither tool merges configuration files, and Pylance reads Pyright's settings only at a workspace folder's root, as [The editor](#the-editor) says.

The bases sit at the root because each tool resolves a path in a configuration file from that file's directory. The tests' per-file ignores, written as `**/tests/**/*.py`, match every project's `tests/` only from a directory above them all, and paths that belong to one project, such as `reference_app/**`, stay in that project's file. Neither tool discovers a file named `*.base.*`, so a base applies only where a project names it. A root `pyproject.toml` would also hold them, but uv, Dependabot and VS Code would read it as a project.

ruff's `extend` merges by rules that review holds, since each mistake lints quietly with fewer rules or different ones:

- A project adds rules with `extend-select`, never `select`, which sets a new rule set and drops the base's ignores. A project's `ignore` adds to the base's.
- A project adds per-file ignores with `extend-per-file-ignores`, never `per-file-ignores`, which replaces the base's.
- A project's banned-API table would replace the base's whole, so a project sets none: it names its environment module only in `extend-per-file-ignores`.
- A project that leaves out `extend` lints with ruff's defaults, a different rule set.

Pyright's `extends` loads the base, and a key the project sets replaces the base's. The base is JSON with comments, which Pyright reads, because a TOML base is read only from a `[tool.pyright]` table and every other key in it is silently ignored, strict mode included. A relative path resolves from the file that holds it, so `venvPath` and `venv` stay in each project.

A base a project names but can't find fails the check: ruff exits with status 2 and Pyright with 3. Each project's check reads the bases and CI runs every project's check, so a change to a base is checked everywhere it applies. Dependabot's version updates move each package the projects share, such as ruff and Pyright, in all of them in one pull request, as [Pinned versions](versions.md) says, so the projects move to each new version together. Nothing checks that they agree, though: a local upgrade in one project, or a security update, which a group of its own moves, can leave the bases meeting two versions of a tool. A package published from a project carries its `pyproject.toml`, `extend` included, in its source distribution. Building and installing ignore the `[tool.*]` tables, so only linting an unpacked sdist fails.

## Type checking: Pyright in strict mode

Strict mode requires every value to have a known type, including the values that come from dependencies. Pyright is also the engine of Pylance, VS Code's Python language server, so the editor reports as you type what the check reports. Strict mode is one setting rather than a list of flags to keep in step, and the few checks it leaves off that the projects want are turned on as errors beside it in the base. A dependency that ships no types gets a typed stub package rather than a suppression. Pyright's `reportImportCycles` catches import cycles, and in `conformance/`, which holds the reference app, the conformance runner, the baseline adapter and the tests as packages of their own, import-linter's contracts in its `pyproject.toml` hold the direction between them: the reference app and the baseline adapter import nothing of the others, and the runner nothing of the baseline adapter or the tests.

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

- **`required-version`** is the oldest uv the project needs, not the newest. Dependabot updates the lock by running uv itself, and its uv runs behind uv's newest release, so a `required-version` above Dependabot's uv makes every update fail. Each project's CI job runs exactly the oldest uv its setting allows, which proves the floor. Raise it only when the project needs a newer uv, and no further than the uv in Dependabot's [uv image](https://github.com/dependabot/dependabot-core/blob/main/uv/Dockerfile).
- **`exclude-newer = "7 days"`** makes uv resolve only versions released at least 7 days before it runs, which is how long Dependabot's cooldown holds back an update. A local `uv lock` and Dependabot's therefore choose the same versions, and no update proposes a version uv would refuse. In its relative form the setting records a span rather than a date, so the lock stays valid as the window moves. The setting and the uv entry in `.github/dependabot.yml` each name the other.
- **`uv run --locked`** runs every tool, from the project's directory, or with `--project` naming the project where a hook runs it from the root. uv first syncs the project's environment to `uv.lock`, and `--locked` fails when the lock is out of date with `pyproject.toml` rather than updating it, so every check runs exactly the locked versions on every machine. The project's `check` recipe chains these commands, and CI runs that recipe.

A project that publishes a package promises its users the range of each dependency it declares, so its Dependabot entry sets `versioning-strategy: widen`, which widens a range to admit a new version rather than raising its lower bound. `conformance/` and `scripts/` publish nothing, so their entry keeps Dependabot's default.

## The environment

One module in a project reads the environment: in `conformance/`, `reference_app/environment.py`. The base's banned-API setting rejects `os.environ`, `os.environb`, `os.getenv` and `os.getenvb` in every file, tests included, and a project exempts its one module with `extend-per-file-ignores`, so every variable the code reads is named and documented in one place. `scripts/` reads no variable, so it exempts no file.

## The editor

Each Python project is a folder of the repository's [VS Code workspace](repository.md#the-editor). Pylance, VS Code's Python language server, reads `[tool.pyright]` from the `pyproject.toml` at the root of a workspace folder, and the base it extends. In a window opened at the repository's root it would read no project's settings, so strict mode would have to be restated in the root's VS Code settings, a second copy that can drift. Pylance's `python.analysis.useNearestConfiguration` reads the nearest `pyproject.toml` instead, but Pylance marks it experimental, so the workspace gives each project its own folder.

A Python project's `.vscode/settings.json` points VS Code at the project's uv environment, runs pytest as the project's check does where it has tests, and formats and fixes with ruff on save. A new Python project adds those settings to its own `.vscode/`, as `conformance/.vscode/` has them.
