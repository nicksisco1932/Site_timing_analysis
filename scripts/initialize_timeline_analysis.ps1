# Project: Site Timing Analysis
# File: scripts/initialize_timeline_analysis.ps1
# Primary author: Nicholas J. Sisco, Ph.D.
# Organization: Profound Medical, LLC
# Created: 2026-08-11
# Purpose: Bootstraps the repository environment and starts guided Timeline Analysis onboarding.
#
# Provenance: Original implementation or material contribution by
# Nicholas J. Sisco, Ph.D. for Profound Medical, LLC.
#
# Rights status: Proprietary / internal use unless otherwise specified
# by Profound Medical, LLC.
[CmdletBinding()]
param(
  [switch]$Yes,
  [switch]$SkipDependencyInstall,
  [switch]$FullTests,
  [switch]$PlanOnly,
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$WizardArguments
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$repoPython = Join-Path $repoRoot '.venv\Scripts\python.exe'

function Confirm-InitializationStep {
  param([Parameter(Mandatory = $true)][string]$Message)
  if ($Yes) {
    return $true
  }
  $answer = Read-Host "$Message [y/N]"
  return $answer.Trim().ToLowerInvariant() -in @('y', 'yes')
}

function Invoke-CheckedCommand {
  param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [Parameter(Mandatory = $true)][string]$Description
  )
  & $Executable @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "$Description failed with exit code $LASTEXITCODE."
  }
}

function Test-SupportedPythonCandidate {
  param(
    [Parameter(Mandatory = $true)][string]$Executable,
    [string[]]$PrefixArguments = @()
  )
  & $Executable @PrefixArguments '-c' 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 2)' 2>$null
  return $LASTEXITCODE -eq 0
}

function Resolve-SupportedPython {
  $directCandidates = @(
    Get-Command 'python.exe', 'python3.exe' -All -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandType -eq 'Application' } |
      Select-Object -ExpandProperty Source -Unique
  )
  foreach ($candidate in $directCandidates) {
    if (Test-SupportedPythonCandidate -Executable $candidate) {
      return [pscustomobject]@{
        Executable = $candidate
        PrefixArguments = @()
      }
    }
  }

  $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
  if ($null -ne $launcher) {
    foreach ($selector in @('-3', '-3.14', '-3.13', '-3.12')) {
      if (Test-SupportedPythonCandidate -Executable $launcher.Source -PrefixArguments @($selector)) {
        return [pscustomobject]@{
          Executable = $launcher.Source
          PrefixArguments = @($selector)
        }
      }
    }
  }
  return $null
}

if ($env:OS -ne 'Windows_NT') {
  throw 'Guided Timeline Analysis initialization currently requires Windows.'
}
if ($PSVersionTable.PSVersion.Major -lt 5) {
  throw "PowerShell 5.1 or newer is required; found $($PSVersionTable.PSVersion)."
}

$environmentExists = Test-Path -LiteralPath $repoPython -PathType Leaf
Write-Host "Repository: $repoRoot"
Write-Host "Virtual environment: $repoPython"
Write-Host "Environment present: $environmentExists"

if ($PlanOnly) {
  if (-not $environmentExists) {
    Write-Host 'Plan: create .venv with an available Python 3.12+ interpreter.'
  }
  if (-not $SkipDependencyInstall) {
    Write-Host 'Plan: install runtime, development, and editable-project dependencies after confirmation.'
  }
  Write-Host 'Plan: run dependency/CLI checks, then start the Python onboarding wizard.'
  exit 0
}

if (-not $environmentExists) {
  $systemPython = Resolve-SupportedPython
  if ($null -eq $systemPython) {
    throw 'Python 3.12+ was not found. Install it locally, then rerun; this script never installs system Python.'
  }
  if (-not (Confirm-InitializationStep 'Create the repository .venv with the detected Python 3.12+ interpreter?')) {
    throw 'Virtual-environment creation was declined.'
  }
  $venvArguments = @($systemPython.PrefixArguments) + @('-m', 'venv', (Join-Path $repoRoot '.venv'))
  Invoke-CheckedCommand -Executable $systemPython.Executable -Arguments $venvArguments -Description 'Virtual-environment creation'
}

if (-not (Test-Path -LiteralPath $repoPython -PathType Leaf)) {
  throw "Repository Python executable is missing after setup: $repoPython"
}

Invoke-CheckedCommand -Executable $repoPython -Arguments @('-c', 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 2)') -Description 'Python 3.12+ validation'

if (-not $SkipDependencyInstall) {
  if (Confirm-InitializationStep 'Install or refresh declared runtime, development, and editable-project dependencies?') {
    Invoke-CheckedCommand -Executable $repoPython -Arguments @('-m', 'pip', 'install', '--upgrade', 'pip') -Description 'pip upgrade'
    Invoke-CheckedCommand -Executable $repoPython -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $repoRoot 'requirements.txt')) -Description 'Runtime dependency installation'
    Invoke-CheckedCommand -Executable $repoPython -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $repoRoot 'requirements-dev.txt')) -Description 'Development dependency installation'
    Invoke-CheckedCommand -Executable $repoPython -Arguments @('-m', 'pip', 'install', '-e', $repoRoot) -Description 'Editable project installation'
  } else {
    Write-Warning 'Dependency installation was skipped by the user; the validation checks may fail.'
  }
}

$initializer = Join-Path $repoRoot 'scripts\initialize_timeline_analysis.py'
$arguments = @($initializer)
if ($FullTests) {
  $arguments += '--full-tests'
}
if ($WizardArguments) {
  $arguments += $WizardArguments
}

Set-Location -LiteralPath $repoRoot
& $repoPython @arguments
exit $LASTEXITCODE
