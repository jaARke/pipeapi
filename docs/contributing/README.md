# Contributor documentation

These pages are for people changing pipeapi. Each covers one part of the repository: how it's built and checked, the conventions it follows, and why its design is what it is, so a closed issue isn't the only record of a decision. [CONTRIBUTING.md](../../CONTRIBUTING.md) is the place to start: it covers questions, issues, setting up for development, the everyday commands and pull requests.

The documentation for people using pipeapi is the guide site, built from `docs/src/`. This folder sits outside the site's build, so these pages are read here, on GitHub. [The documentation system](documentation.md#contributor-pages) says what a page here holds.

## Pages

- [The repository](repository.md): how the projects are laid out, how the commands and the editor join them, and what a new project adds.
- [The documentation system](documentation.md): where each kind of documentation goes, which file or page owns each fact, what a page here holds, and how to mark unreleased behavior.
- [The guide site](guide-site.md): how the site is organized, how the protocol's contract renders into it, how it's checked, and why it's built this way.
- [The protocol](protocol.md): what the protocol guarantees and to whom, why it's built this way, and what was rejected.
- [The connector API](connector-api.md): what the surface every connector offers guarantees and to whom, why it's built this way, and what was rejected.
- [Python projects](python.md): the conventions every Python project in the repository follows, and their reasons.
- [The conformance project](conformance.md): the reference app, and how a runner starts, observes and stops it.
- [Pinned versions](versions.md): the versions Dependabot moves, and the ones that move by hand.
