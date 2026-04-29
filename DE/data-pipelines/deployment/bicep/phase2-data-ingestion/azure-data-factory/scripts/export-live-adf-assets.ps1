param(
    [string]$ResourceGroup = "blache-cdtscr-dev-data-rg",
    [string]$FactoryName = "blache-cdtscr-dev-adf-y27jgavel2x32",
    [string]$OutputDir = "..\live-export"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Exporting linked services from $FactoryName ..."
$linkedServices = az datafactory linked-service list `
    --resource-group $ResourceGroup `
    --factory-name $FactoryName `
    -o json | ConvertFrom-Json

foreach ($ls in $linkedServices) {
    $name = $ls.name
    $outFile = Join-Path $OutputDir ("linkedservice-" + $name + ".json")
    ($ls | ConvertTo-Json -Depth 100) | Set-Content -Encoding UTF8 -Path $outFile
}

Write-Host "Exporting pipelines from $FactoryName ..."
$pipelines = az datafactory pipeline list `
    --resource-group $ResourceGroup `
    --factory-name $FactoryName `
    -o json | ConvertFrom-Json

foreach ($p in $pipelines) {
    $name = $p.name
    $outFile = Join-Path $OutputDir ("pipeline-" + $name + ".json")
    ($p | ConvertTo-Json -Depth 100) | Set-Content -Encoding UTF8 -Path $outFile
}

Write-Host "Export complete. Files written to: $OutputDir"
