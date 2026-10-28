# Settings every justfile imports, since just doesn't carry settings into modules.

# CI runs this version (every just-version in .github/workflows), so keep them all equal.
set minimum-version := "1.56.0"

# sh is the default, which Windows lacks unless Git's Unix tools are on PATH.
# Recipe lines must therefore run unchanged in sh and Windows PowerShell 5.1.
# Windows' default policy blocks the .ps1 shims that npm and npx run through; machine and user
# group policies still take precedence over this process-scope setting.
[windows]
set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
