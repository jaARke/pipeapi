# The repository

pipeapi keeps its projects, such as the conformance project and the guide site, and the protocol's contract in one repository. This page says how the projects are laid out, how the commands and the editor join them, and what a new project adds.

## Layout

Each project is a directory at the repository's root, laid out the way its ecosystem expects, so it builds with its own toolchain and no knowledge of the others. It holds what its own tools need: its manifest and lockfile, its toolchain's version, ignore rules for the files its tools generate, its justfile and its VS Code settings. A published package also keeps its README there, since its registry shows that file. `protocol/` belongs to no project: the guide site renders it, and `just lint` validates it.

The root holds what spans the projects, such as the root justfile and `settings.just`, the CI workflows, the hooks in `.pre-commit-config.yaml`, Dependabot's configuration, `.editorconfig` and `.gitattributes`, and the VS Code workspace.

A directory per project at the root follows the multi-language repositories closest to pipeapi: Valkey GLIDE and Cucumber's messages keep a directory per language, each with its own README and ignore rules, and Protocol Buffers keeps its conformance suite in a top-level `conformance/`. Two ways of joining the projects at the root were rejected:

- **A build system that spans languages,** such as Bazel, Pants or Nx, gives one build graph, caches across languages and runs CI only for what a change affects. Every contributor would have to learn it, and it works against each ecosystem's own build and publishing, while pipeapi's projects share no build: they read `protocol/` as data.
- **A root workspace per ecosystem,** such as a uv workspace or npm workspaces, resolves every project of that ecosystem in one lockfile, and a uv workspace takes one Python range for all its members. Each package declares the dependency ranges its users install from, and `conformance/` uses the packages as a user's app would, so each project resolves on its own.

## Commands

Each project keeps its commands in its own justfile, which the root justfile loads as a module, so `just docs::check` runs from the root and `just check` from inside `docs/`, and either way the recipe runs in the project's directory. just doesn't carry settings into modules, so each project's justfile starts with `import "../settings.just"`, which sets the minimum just version and the Windows shell. `just` alone lists the commands, at the root or inside a project.

`just lint` runs the hooks in `.pre-commit-config.yaml` over the files Git tracks: actionlint and zizmor's security audits over the workflows, the schema of Dependabot's configuration, `.editorconfig`'s rules, lychee over the links and anchors in the Markdown read on GitHub, and the checks of the protocol's contract that [its README](../../protocol/README.md) describes. zizmor and lychee publish no Windows on Arm build, so their hooks call just, which has uv install their x64 builds on Windows, and Windows on Arm runs those under emulation.

The root's `check` and `fix` run every project's, so a project joins them when it lands, and locally `check` stops at the first check that fails. CI runs `lint` and each project's `check` as jobs of their own, on every OS, so one project's failure never hides another's, and `CI passed` needs them all. CI doesn't run the root's `check`, so only review notices a project missing from it.

## The editor

VS Code opens `pipeapi.code-workspace`, a multi-root workspace: the repository's root is one folder, and each project is another. VS Code scopes settings by folder and by language, never by path, so only a folder of its own lets a project choose what runs on save, which formatter a language gets or how its tests run, without the choice reaching every other project. Opened as a plain folder, the repository applies no project's settings.

Each folder keeps its settings and recommended extensions in its own `.vscode/`, and the root's `.vscode/` recommends what serves the whole repository. The root `.gitignore`'s rules for `.vscode/` apply in every folder: they share the settings, tasks, launch configurations, recommended extensions and snippets, and keep everything else in `.vscode/` local. They also keep the shared files and the workspace file where a contributor's global ignore rules exclude them.

VS Code applies some settings to the whole window, such as the TypeScript compiler, and reads those from the workspace file rather than a folder's settings. `pipeapi.code-workspace` sets them, and the project they serve keeps a copy in its own `.vscode/settings.json` for when it's opened on its own.

## Adding a project

A new project lands with:

- its directory at the root, laid out as its ecosystem expects;
- its justfile, starting with `import "../settings.just"` and holding `default`, `check` and `fix`; a `mod` line in the root justfile; and its recipes in the root's `check` and `fix`;
- a job in `.github/workflows/ci.yml` that runs its `check` on every OS, in the needs of `CI passed`;
- an entry in `.github/dependabot.yml` for its packages, and its package manager held to the same 7-day cooldown;
- its folder in `pipeapi.code-workspace`, and its settings and recommended extensions in its `.vscode/`;
- each version it pins by hand, and its cooldown setting, in [Pinned versions](versions.md);
- its toolchain in CONTRIBUTING.md's [prerequisites](../../CONTRIBUTING.md#prerequisites), where the table lacks it;
- its page in this folder, listed in the folder's [index](README.md).
