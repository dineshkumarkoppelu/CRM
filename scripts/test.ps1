<#
.SYNOPSIS
    Run every check: backend tests with coverage, ruff, UI lint and build.
.DESCRIPTION
    Needs the TEST Neo4j instance (C:\neo4j\test\bin\neo4j.bat console, Bolt 7688). The tests wipe
    and reseed that instance; the dev database is never touched.
.EXAMPLE
    .\scripts\test.ps1
.EXAMPLE
    .\scripts\test.ps1 -SkipUi
#>
param([switch]$SkipUi)

. "$PSScriptRoot\_common.ps1"

Write-Step "Test Neo4j"
$bolt = Get-BoltEndpoint (Get-EnvValue "TEST_NEO4J_URI" "bolt://localhost:7688") 7688
if (-not (Test-Port $bolt.Host $bolt.Port)) {
    Fail ("The test Neo4j is not reachable at $($bolt.Host):$($bolt.Port). Start it in another terminal with:`n" +
          "    C:\neo4j\test\bin\neo4j.bat console")
}
Write-Ok "listening on $($bolt.Host):$($bolt.Port)"
if (-not (Test-Path $VenvPython)) { Fail "api\.venv is missing. Run .\scripts\start.ps1 once first." }

Push-Location $ApiDir
try {
    Write-Step "Python dev packages"
    Invoke-Native "pip install" {
        & $VenvPython -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-dev.txt
    }
    Write-Step "ruff"
    Invoke-Native "ruff check" { & $VenvPython -m ruff check . }
    Invoke-Native "ruff format --check" { & $VenvPython -m ruff format --check . }
    Write-Step "pytest with coverage"
    Invoke-Native "pytest" { & $VenvPython -m pytest -q --cov=app --cov-report=term }
} finally {
    Pop-Location
}

if (-not $SkipUi) {
    Push-Location $UiDir
    try {
        if (-not (Test-Path "node_modules")) {
            Write-Step "npm ci"
            Invoke-Native "npm ci" { & npm ci --no-audit --no-fund }
        }
        Write-Step "UI lint"
        Invoke-Native "npm run lint" { & npm run lint }
        Write-Step "UI build (type check + bundle)"
        Invoke-Native "npm run build" { & npm run build }
    } finally {
        Pop-Location
    }
}

Write-Host ""
Write-Host "All checks passed." -ForegroundColor Green
