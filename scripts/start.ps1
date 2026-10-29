<#
.SYNOPSIS
    Start the CRM Graph demo: checks, API in a new window, demo data, browser.
.DESCRIPTION
    1. Creates api\.env from api\.env.example if it is missing (then asks you to set the password).
    2. Checks that the dev Neo4j is reachable (start it with C:\neo4j\dev\bin\neo4j.bat console).
    3. Creates api\.venv and installs the Python packages if needed.
    4. Builds the web UI if ui\dist is missing (needs Node.js 22+).
    5. Starts the API (uvicorn) in a new window, or reuses one already running on the port.
    6. Waits up to 3 minutes for /api/health to report ok and schema_ok.
    7. Resets the demo data (POST /api/admin/seed) unless -SkipSeed, then opens the browser.
.EXAMPLE
    .\scripts\start.ps1
.EXAMPLE
    .\scripts\start.ps1 -SkipSeed     # keep the current data
#>
param(
    [int]$Port = 8000,
    [switch]$SkipSeed,
    [switch]$NoBrowser
)

. "$PSScriptRoot\_common.ps1"
$Api = "http://localhost:$Port"

# 1. api\.env ------------------------------------------------------------------------------
Write-Step "Configuration (api\.env)"
if (-not (Test-Path $EnvFile)) {
    Copy-Item (Join-Path $ApiDir ".env.example") $EnvFile
    Fail ("Created api\.env from api\.env.example. Set NEO4J_PASSWORD in it to the password of " +
          "your Neo4j instances (see README 'Neo4j setup'), then run this script again.")
}
$password = Get-EnvValue "NEO4J_PASSWORD"
if (-not $password -or $password -eq "change-me-please") {
    Fail "NEO4J_PASSWORD in api\.env is not set. Use the password you gave neo4j-admin (README 'Neo4j setup')."
}
Write-Ok "api\.env found"

# 2. dev Neo4j -----------------------------------------------------------------------------
Write-Step "Dev Neo4j"
$bolt = Get-BoltEndpoint (Get-EnvValue "NEO4J_URI" "bolt://localhost:7687")
if (-not (Test-Port $bolt.Host $bolt.Port)) {
    Fail ("Neo4j is not reachable at $($bolt.Host):$($bolt.Port). Start it in another terminal with:`n" +
          "    C:\neo4j\dev\bin\neo4j.bat console`n" +
          "wait until it prints 'Started.', then run this script again.")
}
Write-Ok "listening on $($bolt.Host):$($bolt.Port)"

# 3. Python environment --------------------------------------------------------------------
Write-Step "Python environment (api\.venv)"
if (-not (Test-Path $VenvPython)) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) { Fail "Python 3.12+ not found on PATH. Install it and open a new terminal." }
    Write-Note "creating api\.venv (first run only)"
    Invoke-Native "Creating the virtual environment" { & python -m venv (Join-Path $ApiDir ".venv") }
    Invoke-Native "Installing Python packages" {
        & $VenvPython -m pip install --disable-pip-version-check -q -r (Join-Path $ApiDir "requirements.txt")
    }
}
Write-Ok (& $VenvPython --version)

# 4. Web UI --------------------------------------------------------------------------------
Write-Step "Web UI (ui\dist)"
if (-not (Test-Path (Join-Path $UiDir "dist\index.html"))) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Fail "ui\dist is missing and npm was not found. Install Node.js 22+ (LTS) and run this script again."
    }
    Write-Note "building the UI (first run only, takes a few minutes)"
    Push-Location $UiDir
    try {
        Invoke-Native "npm ci" { & npm ci --no-audit --no-fund }
        Invoke-Native "npm run build" { & npm run build }
    } finally {
        Pop-Location
    }
}
Write-Ok "built"

# 5. API -----------------------------------------------------------------------------------
Write-Step "API on port $Port"
if (Test-Port "localhost" $Port) {
    if (-not (Get-Health $Api)) {
        Fail "Port $Port is in use by something that is not this API. Stop it or use -Port <other>."
    }
    Write-Ok "already running, reusing it"
} else {
    $command = "Set-Location '$ApiDir'; & '$VenvPython' -m uvicorn app.main:app --port $Port --no-access-log"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $command -WorkingDirectory $ApiDir | Out-Null
    Write-Ok "started in a new window (close that window or press Ctrl+C there to stop it)"
}

# 6. Wait for health -----------------------------------------------------------------------
Write-Step "Waiting for /api/health (up to 3 minutes)"
$deadline = (Get-Date).AddMinutes(3)
$health = $null
while ((Get-Date) -lt $deadline) {
    $health = Get-Health $Api
    if ($health -and $health.status -eq "ok" -and $health.schema_ok) { break }
    Start-Sleep -Seconds 3
}
if (-not ($health -and $health.status -eq "ok" -and $health.schema_ok)) {
    $detail = if ($health) { ($health | ConvertTo-Json -Depth 4 -Compress) } else { "no response" }
    Fail "The API did not become healthy in 3 minutes. Last health: $detail. Check the API window for errors."
}
Write-Ok ("Neo4j {0} {1}, APOC {2}, GDS {3}, data as of {4}" -f $health.neo4j.version, $health.neo4j.edition,
          $health.neo4j.apoc_version, $health.neo4j.gds_version, $health.as_of_date)

# 7. Demo data + browser -------------------------------------------------------------------
if ($SkipSeed) {
    Write-Note "keeping the current data (-SkipSeed)"
} else {
    Write-Step "Resetting the demo data"
    $seed = Invoke-RestMethod -Method Post -Uri "$Api/api/admin/seed" -TimeoutSec 300
    Write-Ok ("{0} sales people, {1} clients, {2} deals, {3} activities, {4} similar pairs ({5:n1} s)" -f
              $seed.counts.SalesPerson, $seed.counts.Client, $seed.counts.Deal, $seed.counts.Activity,
              $seed.similar_pairs, ($seed.duration_ms / 1000))
}

if (-not $NoBrowser) { Start-Process $Api }
Write-Host ""
Write-Host "Ready: $Api   (API docs: $Api/docs, Neo4j Browser: http://localhost:7474)" -ForegroundColor Green
