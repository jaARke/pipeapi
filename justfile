import "settings.just"

# The guide site, built from docs/.
mod docs

# The conformance suite and its reference app, in conformance/.
mod conformance

prek := "uvx prek@0.5.5"

# List the available commands.
default:
    @just --list

# Lint repository-wide files, such as the GitHub Actions workflows and the links in the Markdown read on GitHub.
lint:
    {{ prek }} run --all-files

# Check the links in the Markdown read on GitHub online, external ones included.
external-links:
    {{ prek }} run --all-files --hook-stage manual lychee-online
