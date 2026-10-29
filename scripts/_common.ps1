# Shared helpers for start.ps1 / reset.ps1 / test.ps1. Dot-source it: . "$PSScriptRoot\_common.ps1"
# ASCII only (Windows PowerShell 5.1 reads scripts without a BOM as ANSI).

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $RepoRoot "api"
$UiDir = Join-Path $RepoRoot "ui"
$EnvFile = Join-Path $ApiDir ".env"
$VenvPython = Join-Path $ApiDir ".venv\Scripts\python.exe"

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "    $Message" -ForegroundColor Green }
function Write-Note([string]$Message) { Write-Host "    $Message" -ForegroundColor Yellow }

function Fail([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

# Run a native command; stop with a clear message if it exits non-zero.
# ($ErrorActionPreference does not apply to native exit codes in Windows PowerShell.)
function Invoke-Native([string]$Description, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { Fail "$Description failed (exit code $LASTEXITCODE)." }
}

# Value of KEY=value from api\.env (or $Default).
function Get-EnvValue([string]$Key, [string]$Default = "") {
    if (-not (Test-Path $EnvFile)) { return $Default }
    foreach ($line in Get-Content $EnvFile) {
        if ($line -match "^\s*$Key\s*=(.*)$") {
            $value = $Matches[1].Trim()
            if ($value) { return $value }
        }
    }
    return $Default
}

# host and port from a bolt://host:port URI
function Get-BoltEndpoint([string]$Uri, [int]$DefaultPort = 7687) {
    $u = [Uri]($Uri -replace '^bolt(\+s|\+ssc)?://', 'tcp://' -replace '^neo4j(\+s|\+ssc)?://', 'tcp://')
    $port = if ($u.Port -gt 0) { $u.Port } else { $DefaultPort }
    return @{ Host = $u.Host; Port = $port }
}

# Quick TCP check without Test-NetConnection's slowness and progress output.
function Test-Port([string]$HostName, [int]$Port, [int]$TimeoutMs = 2000) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync($HostName, $Port)
        return ($task.Wait($TimeoutMs) -and $client.Connected)
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Get-Health([string]$Api) {
    try { return Invoke-RestMethod -Uri "$Api/api/health" -TimeoutSec 30 } catch { return $null }
}
