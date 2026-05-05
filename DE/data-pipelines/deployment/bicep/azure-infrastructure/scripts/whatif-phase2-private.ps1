param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [string]$DataResourceGroup = "",
    [ValidateSet("premium", "consumption")]
    [string]$FunctionsTier = "premium",
    [string]$FunctionsLocationOverride = ""
)

$ErrorActionPreference = "Stop"

function Resolve-DataResourceGroup {
    param(
        [string]$ExplicitValue,
        [string]$EnvironmentName
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitValue)) { return $ExplicitValue }

    $globalDataRg = (Get-Variable -Name "DATA_RG" -Scope Global -ErrorAction SilentlyContinue).Value
    if (-not [string]::IsNullOrWhiteSpace([string]$globalDataRg)) { return [string]$globalDataRg }

    if (-not [string]::IsNullOrWhiteSpace($env:DATA_RG)) { return $env:DATA_RG }

    throw "Data resource group is required. Pass -DataResourceGroup `$DATA_RG (recommended) or set global/env DATA_RG."
}

$DataResourceGroup = Resolve-DataResourceGroup -ExplicitValue $DataResourceGroup -EnvironmentName $Environment

$rgExists = az group exists --name $DataResourceGroup -o tsv
if ($LASTEXITCODE -ne 0 -or $rgExists -ne "true") {
    throw "Resource group '$DataResourceGroup' does not exist in current subscription. Set `$DATA_RG correctly or pass -DataResourceGroup."
}

$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$phase2 = Join-Path $root "phase2-data-ingestion"

$serviceBusTemplate = Join-Path $phase2 "service-bus\service-bus.bicep"
$serviceBusParams = Join-Path $phase2 "service-bus\parameters\$Environment.parameters.json"

$adfTemplate = Join-Path $phase2 "azure-data-factory\data-factory.bicep"
$adfParams = Join-Path $phase2 "azure-data-factory\parameters\$Environment.parameters.json"

$peTemplate = Join-Path $phase2 "private-network\private-endpoints.bicep"
$peParams = Join-Path $phase2 "private-network\parameters\$Environment.parameters.json"

$funcTemplate = if ($FunctionsTier -eq "consumption") {
    Join-Path $phase2 "functions\functions-consumption.bicep"
} else {
    Join-Path $phase2 "functions\functions-premium.bicep"
}

$funcParams = if ($FunctionsTier -eq "consumption") {
    Join-Path $phase2 "functions\parameters\$Environment.consumption.parameters.json"
} else {
    Join-Path $phase2 "functions\parameters\$Environment.parameters.json"
}

if (-not (Test-Path $funcTemplate)) {
    throw "Functions template not found for tier '$FunctionsTier': $funcTemplate"
}
if (-not (Test-Path $funcParams)) {
    throw "Functions parameters file not found for tier '$FunctionsTier': $funcParams"
}

Write-Host "Running what-if for Service Bus..." -ForegroundColor Cyan
az deployment group what-if --resource-group $DataResourceGroup --template-file $serviceBusTemplate --parameters "@$serviceBusParams"
if ($LASTEXITCODE -ne 0) { throw "Service Bus what-if failed." }

Write-Host "Running what-if for Data Factory..." -ForegroundColor Cyan
az deployment group what-if --resource-group $DataResourceGroup --template-file $adfTemplate --parameters "@$adfParams"
if ($LASTEXITCODE -ne 0) { throw "Data Factory what-if failed." }

Write-Host "Running what-if for Private Endpoints..." -ForegroundColor Cyan
az deployment group what-if --resource-group $DataResourceGroup --template-file $peTemplate --parameters "@$peParams"
if ($LASTEXITCODE -ne 0) { throw "Private Endpoints what-if failed." }

Write-Host "Running what-if for Functions tier: $FunctionsTier..." -ForegroundColor Cyan
if ([string]::IsNullOrWhiteSpace($FunctionsLocationOverride)) {
    az deployment group what-if --resource-group $DataResourceGroup --template-file $funcTemplate --parameters "@$funcParams"
} else {
    Write-Host "Overriding Functions location to: $FunctionsLocationOverride" -ForegroundColor Yellow
    az deployment group what-if --resource-group $DataResourceGroup --template-file $funcTemplate --parameters "@$funcParams" --parameters "location=$FunctionsLocationOverride"
}
if ($LASTEXITCODE -ne 0) { throw "Functions what-if failed for tier '$FunctionsTier'." }

Write-Host "What-if completed." -ForegroundColor Green
