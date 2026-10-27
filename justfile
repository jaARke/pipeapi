import "settings.just"

# List the available commands.
default:
    @just --list

# Lint repository-wide files, such as the GitHub Actions workflows.
lint:
    uvx prek@0.5.5 run --all-files
