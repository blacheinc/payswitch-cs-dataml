param(
    [Parameter(Mandatory = $true)]
    [string]$ValuesFile,
    [string]$TargetDir = "..\live-export"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ValuesFile)) {
    throw "Values file not found: $ValuesFile"
}

if (-not (Test-Path $TargetDir)) {
    throw "Target directory not found: $TargetDir"
}

$rawValues = Get-Content $ValuesFile -Raw | ConvertFrom-Json -AsHashtable
if ($rawValues.Count -eq 0) {
    throw "Values file is empty: $ValuesFile"
}

$files = Get-ChildItem -Path $TargetDir -Filter *.json -File |
    Where-Object { $_.Name -ne "live-export.values.example.json" -and $_.Name -ne "live-export.values.local.json" }

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw
    foreach ($token in $rawValues.Keys) {
        $actual = [string]$rawValues[$token]
        if ([string]::IsNullOrWhiteSpace($actual)) {
            continue
        }
        $content = $content.Replace($actual, $token)
    }
    Set-Content -Path $file.FullName -Value $content -NoNewline
}

Write-Host "Sanitized $($files.Count) file(s) in $TargetDir using token map from $ValuesFile"
