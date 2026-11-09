# VulnTell daily briefing scheduler wrapper (Windows Task Scheduler / manual).
#
# Example registration (run once in an elevated PowerShell):
#   schtasks /create /tn "VulnTell Daily" /sc daily /st 08:00 /tr ^
#     "powershell -ExecutionPolicy Bypass -File <repo>\scripts\daily_briefing.ps1"
#
# The daily entry point IS the explicit live collection command (keyless
# sources only: CISA KEV + local MCP OSV server + dual-path probe). Offline
# determinism lives in the test/CI suite; see docs/vulntell/daily_briefing.md.
param(
    [int]$WindowDays = 7,
    [string]$OutDir = "",
    [switch]$SkipDualPath = $false
)

$ErrorActionPreference = "Stop"
$RepoDir = Split-Path -Parent $PSScriptRoot
Push-Location $RepoDir
try {
    $python = if ($env:MAGENT_PYTHON) { $env:MAGENT_PYTHON } else { "python" }
    $args = @("-m", "apps.vulntell.daily", "--window-days", "$WindowDays")
    if ($OutDir -ne "") { $args += @("--out", $OutDir) }
    if ($SkipDualPath) { $args += "--skip-dual-path" }
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "daily briefing exited with $LASTEXITCODE" }
}
finally {
    Pop-Location
}
