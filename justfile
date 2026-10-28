import "settings.just"

# The guide site, built from docs/.
mod docs

# The conformance suite and its reference app, in conformance/.
mod conformance

prek := "uvx prek@0.5.5"

# List the available commands, each project's included.
default:
    @just --list --list-submodules

# Run every check a pull request must pass: the repository-wide lint, then each project's check.
check: lint docs::check conformance::check

# Apply every project's fixes and formatting.
fix: docs::fix conformance::fix

# Lint repository-wide files, such as the GitHub Actions workflows, the links in the Markdown read on GitHub and the protocol's contract.
lint:
    {{ prek }} run --all-files

# Check the links in the Markdown read on GitHub online, external ones included.
external-links:
    {{ prek }} run --all-files --hook-stage manual lychee-online
