<#
.SYNOPSIS
    Reset the demo data: wipes the dev database and reloads the synthetic dataset.
.EXAMPLE
    .\scripts\reset.ps1
#>
param([string]$Api = "http://localhost:8000")

. "$PSScriptRoot\_common.ps1"

if (-not (Get-Health $Api)) {
    Fail "The API is not reachable at $Api. Start it with .\scripts\start.ps1"
}

Write-Step "Resetting demo data at $Api (this wipes everything)"
try {
    $seed = Invoke-RestMethod -Method Post -Uri "$Api/api/admin/seed" -TimeoutSec 300
} catch {
    $message = $_.ErrorDetails.Message
    if ($message) { Fail "Seed failed: $message" } else { throw }
}

$seed.counts.PSObject.Properties |
    ForEach-Object { [pscustomobject]@{ Item = $_.Name; Count = $_.Value } } |
    Format-Table -AutoSize | Out-String | Write-Host
Write-Ok ("EXPERTISE_IN {0}, SIMILAR_TO {1}; as of {2}; seed {3}; {4:n1} s" -f
          $seed.expertise_edges, $seed.similar_pairs, $seed.as_of_date, $seed.seed, ($seed.duration_ms / 1000))
