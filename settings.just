# Settings and values every justfile imports, since just carries neither into modules.

# CI runs this version (every just-version in .github/workflows), so keep them all equal.
set minimum-version := "1.56.0"

# sh is the default, which Windows lacks unless Git's Unix tools are on PATH.
# Recipe lines must therefore run unchanged in sh and Windows PowerShell 5.1.
# Windows' default policy blocks the .ps1 shims that npm and npx run through; machine and user
# group policies still take precedence over this process-scope setting.
[windows]
set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

# uvx for a tool that publishes no Windows on Arm build, such as zizmor or lychee: on Windows it
# installs the x64 build, which Windows on Arm runs under emulation and uv otherwise refuses there.
uvx-x64 := "uvx" + if os() == "windows" { " --python-platform x86_64-pc-windows-msvc" } else { "" }

# lychee, which the Markdown link hooks and the site's link checks run.
lychee := uvx-x64 + " --from lychee-bin@0.24.2 lychee --no-progress --include-fragments"

# pyright's wrapper otherwise asks PyPI for the newest pyright on every run, so a Python
# project's check would reach the network and warn whenever a newer one is out.
export PYRIGHT_PYTHON_IGNORE_WARNINGS := "1"
