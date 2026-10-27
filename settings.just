# Settings every justfile imports, since just doesn't carry settings into modules.

# CI runs this version (ci.yml's just-version), so keep the two equal.
set minimum-version := "1.56.0"

# sh is the default, which Windows lacks unless Git's Unix tools are on PATH.
# Recipe lines must therefore run unchanged in sh and Windows PowerShell 5.1.
[windows]
set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
