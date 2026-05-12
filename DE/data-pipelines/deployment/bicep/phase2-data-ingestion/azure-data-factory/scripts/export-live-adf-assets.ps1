param(
    # Example resource group: <namingPrefix>-data-rg (see hydrate-phase2-parameters.ps1 output)
    [string]$ResourceGroup = "",
    # Example factory: <namingPrefix>-adf-<suffix>
    [string]$FactoryName = "",
    [string]$OutputDir = "..\live-export"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ResourceGroup) -or [string]::IsNullOrWhiteSpace($FactoryName)) {
    throw "Set -ResourceGroup and -FactoryName (defaults are empty in the repo; see comments above each parameter)."
}

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
