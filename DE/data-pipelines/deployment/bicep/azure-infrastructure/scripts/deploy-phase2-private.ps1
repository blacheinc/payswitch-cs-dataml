param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [string]$DataResourceGroup = "",
    [ValidateSet("premium", "consumption")]
    [string]$FunctionsTier = "premium",
    [string]$FunctionsLocationOverride = "",
    [switch]$SkipFunctions
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
$adfPipelineTemplate = Resolve-Path (Join-Path $root "..\adf\pipeline-training-data-ingestion\pipeline-training-data-ingestion.json")

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

Write-Host "Deploying Service Bus..." -ForegroundColor Cyan
az deployment group create --resource-group $DataResourceGroup --template-file $serviceBusTemplate --parameters "@$serviceBusParams"
if ($LASTEXITCODE -ne 0) { throw "Service Bus deployment failed." }

$serviceBusName = az resource list --resource-group $DataResourceGroup --query "[?type=='Microsoft.ServiceBus/namespaces'].name | [0]" -o tsv
if ([string]::IsNullOrWhiteSpace($serviceBusName)) {
    throw "No Service Bus namespace found in $DataResourceGroup after deployment."
}
Write-Host "Service Bus namespace: $serviceBusName" -ForegroundColor Cyan

Write-Host "Deploying Data Factory..." -ForegroundColor Cyan
az deployment group create --resource-group $DataResourceGroup --template-file $adfTemplate --parameters "@$adfParams" --parameters "serviceBusNamespaceName=$serviceBusName"
if ($LASTEXITCODE -ne 0) { throw "Data Factory deployment failed." }

$adfFactoryName = az datafactory list --resource-group $DataResourceGroup --query "[0].name" -o tsv
if ([string]::IsNullOrWhiteSpace($adfFactoryName)) {
    throw "No Data Factory found in $DataResourceGroup after deployment."
}
Write-Host "Importing canonical training pipeline JSON into Data Factory: $adfFactoryName" -ForegroundColor Cyan
az deployment group create --resource-group $DataResourceGroup --template-file $adfPipelineTemplate --parameters "factoryName=$adfFactoryName" --parameters "data_ingested_ls=data_ingested_ls" --parameters "metadata_postgres_ls=metadata_postgres_ls" --parameters "data_awaits_ingestion_ls=data_awaits_ingestion_ls"
if ($LASTEXITCODE -ne 0) { throw "Canonical ADF pipeline import failed." }

Write-Host "Deploying Private Endpoints..." -ForegroundColor Cyan
az deployment group create --resource-group $DataResourceGroup --template-file $peTemplate --parameters "@$peParams" --parameters "serviceBusNamespaceName=$serviceBusName"
if ($LASTEXITCODE -ne 0) { throw "Private Endpoints deployment failed." }

if ($SkipFunctions) {
    Write-Host "Skipping Functions deployment (-SkipFunctions specified)." -ForegroundColor Yellow
} else {
    Write-Host "Deploying Functions tier: $FunctionsTier" -ForegroundColor Cyan
    if ([string]::IsNullOrWhiteSpace($FunctionsLocationOverride)) {
        az deployment group create --resource-group $DataResourceGroup --template-file $funcTemplate --parameters "@$funcParams"
    } else {
        Write-Host "Overriding Functions location to: $FunctionsLocationOverride" -ForegroundColor Yellow
        az deployment group create --resource-group $DataResourceGroup --template-file $funcTemplate --parameters "@$funcParams" --parameters "location=$FunctionsLocationOverride"
    }
    if ($LASTEXITCODE -ne 0) { throw "Functions deployment failed for tier '$FunctionsTier'." }
}

Write-Host "Phase 2 private deployment completed." -ForegroundColor Green
