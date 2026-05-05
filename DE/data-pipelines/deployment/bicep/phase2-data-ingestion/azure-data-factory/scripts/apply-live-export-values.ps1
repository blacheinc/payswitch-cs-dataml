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
    Where-Object { $_.Name -ne "live-export.values.example.json" }

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw
    foreach ($token in $rawValues.Keys) {
        $replacement = [string]$rawValues[$token]
        $content = $content.Replace($token, $replacement)
    }
    Set-Content -Path $file.FullName -Value $content -NoNewline
}

Write-Host "Applied placeholder values from $ValuesFile into $($files.Count) file(s) in $TargetDir"
