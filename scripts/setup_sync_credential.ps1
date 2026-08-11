# Project: Site Timing Analysis
# File: scripts/setup_sync_credential.ps1
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Invokes the vendored ProfoundTools prompt to store or remove the Sync.com credential.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.

[CmdletBinding()]
param(
    [switch]$Forget
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repoRoot ".venv\Scripts\python.exe"
$syncToolRoot = Join-Path $repoRoot "tools\profoundtools"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "Repository Python executable is missing: $pythonPath"
}
if (-not (Test-Path -LiteralPath (Join-Path $syncToolRoot "sync_tdc_logs\credentials.py") -PathType Leaf)) {
    throw "ProfoundTools credential utility is missing: $syncToolRoot"
}

$previousPythonPath = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
try {
    if ([string]::IsNullOrWhiteSpace($previousPythonPath)) {
        $env:PYTHONPATH = $syncToolRoot
    }
    else {
        $env:PYTHONPATH = "$syncToolRoot;$previousPythonPath"
    }

    $arguments = @("-m", "sync_tdc_logs", "setup")
    if ($Forget) {
        $arguments += "--forget"
    }

    & $pythonPath @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "ProfoundTools credential setup exited with code $LASTEXITCODE."
    }
}
finally {
    if ($null -eq $previousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    }
    else {
        $env:PYTHONPATH = $previousPythonPath
    }
}
