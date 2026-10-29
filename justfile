import "settings.just"

# The guide site, built from docs/.
mod docs

# The conformance suite and its reference app, in conformance/.
mod conformance

# The scripts the checks run over the repository, such as the contract check, in scripts/.
mod scripts

prek := "uvx prek@0.5.5"

# zizmor runs online audits whenever GH_TOKEN or GITHUB_TOKEN is set, which would make results
# differ by shell; Dependabot's security updates cover vulnerable actions.
zizmor := uvx-x64 + " zizmor@1.31.1 --no-progress --offline"

# List the available commands, each project's included.
default:
    @just --list --list-submodules

# Run every check a pull request must pass: the repository-wide lint, then each project's check.
check: lint docs::check conformance::check scripts::check

# Apply every project's fixes and formatting.
fix: docs::fix conformance::fix scripts::fix

# Lint repository-wide files, such as the GitHub Actions workflows, the links in the Markdown read on GitHub and the protocol's contract.
lint:
    {{ prek }} run --all-files

# Check the links in the Markdown read on GitHub online, external ones included.
external-links:
    {{ prek }} run --all-files --hook-stage manual lychee-online

# Run zizmor on the files given, as the workflow hook in .pre-commit-config.yaml does.
[private]
zizmor *files:
    {{ zizmor }} {{ files }}

# Run lychee with the arguments given, as the link hooks in .pre-commit-config.yaml do.
[private]
lychee *args:
    {{ lychee }} {{ args }}
