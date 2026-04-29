# Deploy ADF Pipeline Trigger Azure Function (Python 3.11, Functions v4)
# Creates the app on first run when -CreateResources is specified; always publishes code.

param(
    [Parameter(Mandatory = $false)]
    [string]$ResourceGroupName = "blache-cdtscr-dev-data-rg",

    [Parameter(Mandatory = $false)]
    [string]$FunctionAppName = "blache-cdtscr-dev-adfpt-y27jgavel2x32",

    [Parameter(Mandatory = $false)]
    [string]$Location = "eastus2",

    [Parameter(Mandatory = $false)]
    [string]$KeyVaultName = "blachekvruhclai6km",

    [Parameter(Mandatory = $false)]
    [string]$AdfSubscriptionId = "411d9dd9-b1d7-4ed2-87fb-bc7c9a53cbaf",

    [Parameter(Mandatory = $false)]
    [string]$AdfResourceGroup = "blache-cdtscr-dev-data-rg",

    [Parameter(Mandatory = $false)]
    [string]$AdfFactoryName = "blache-cdtscr-dev-adf-y27jgavel2x32",

    [Parameter(Mandatory = $false)]
    [string]$AdfPipelineName = "pipeline-training-data-ingestion",

    [Parameter(Mandatory = $false)]
    [switch]$CreateResources
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "ADF Pipeline Trigger - deploy" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Function App: $FunctionAppName" -ForegroundColor Yellow
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow
Write-Host ""

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure CLI not found." -ForegroundColor Red
    exit 1
}

$account = az account show 2>$null
if (-not $account) {
    Write-Host "Run az login first." -ForegroundColor Red
    exit 1
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$rgExists = az group exists --name $ResourceGroupName | ConvertFrom-Json
if (-not $rgExists) {
    Write-Host "ERROR: Resource group '$ResourceGroupName' does not exist." -ForegroundColor Red
    exit 1
}

$appExists = $false
try {
    $null = az functionapp show --name $FunctionAppName --resource-group $ResourceGroupName -o none 2>$null
    if ($LASTEXITCODE -eq 0) { $appExists = $true }
} catch { }

if (-not $appExists -and -not $CreateResources) {
    Write-Host "Function app '$FunctionAppName' was not found. Re-run with -CreateResources to create it." -ForegroundColor Red
    exit 1
}

if ($CreateResources -and -not $appExists) {
    $rand = Get-Random -Maximum 99999
    $storageAccountName = ("blcdevadfpt{0:00000}" -f $rand).ToLower()
    if ($storageAccountName.Length -gt 24) {
        $storageAccountName = $storageAccountName.Substring(0, 24)
    }

    Write-Host "Creating storage account: $storageAccountName" -ForegroundColor Yellow
    az storage account create `
        --name $storageAccountName `
        --resource-group $ResourceGroupName `
        --location $Location `
        --sku Standard_LRS

    Write-Host "Creating Function App (Linux consumption)..." -ForegroundColor Yellow
    az functionapp create `
        --name $FunctionAppName `
        --resource-group $ResourceGroupName `
        --storage-account $storageAccountName `
        --consumption-plan-location $Location `
        --runtime python `
        --runtime-version 3.11 `
        --functions-version 4 `
        --os-type Linux

    Write-Host "Enabling system-assigned managed identity..." -ForegroundColor Yellow
    $identityResult = az functionapp identity assign `
        --name $FunctionAppName `
        --resource-group $ResourceGroupName `
        --output json | ConvertFrom-Json
    $principalId = $identityResult.principalId

    $keyVaultUrl = "https://$KeyVaultName.vault.azure.net/"
    $keyVaultId = az keyvault show --name $KeyVaultName --query id -o tsv 2>$null
    if (-not $keyVaultId) {
        $keyVaultId = az keyvault list --query "[?name=='$KeyVaultName'].id" -o tsv | Select-Object -First 1
    }

    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"

    if ($keyVaultId) {
        Write-Host "Granting Key Vault Secrets User on vault..." -ForegroundColor Yellow
        $null = az role assignment create `
            --role "Key Vault Secrets User" `
            --assignee $principalId `
            --scope $keyVaultId `
            2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARNING: Key Vault role assignment failed (permissions?). Assign Key Vault Secrets User to the app managed identity in the portal." -ForegroundColor Yellow
        }
    } else {
        Write-Host "WARNING: Could not resolve Key Vault ID for RBAC." -ForegroundColor Yellow
    }

    $factoryId = az resource show `
        --name $AdfFactoryName `
        --resource-group $AdfResourceGroup `
        --resource-type "Microsoft.DataFactory/factories" `
        --query id -o tsv 2>$null
    if ($factoryId) {
        Write-Host "Granting Data Factory Contributor on factory..." -ForegroundColor Yellow
        $null = az role assignment create `
            --role "Data Factory Contributor" `
            --assignee $principalId `
            --scope $factoryId `
            2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "WARNING: Data Factory role assignment failed. Assign Data Factory Contributor on the factory to the Function app's managed identity (Portal -> Function App -> Identity)." -ForegroundColor Yellow
        }
    } else {
        Write-Host "WARNING: Could not resolve Data Factory resource ID. Grant Data Factory Contributor manually to the managed identity." -ForegroundColor Yellow
    }

    $ErrorActionPreference = $prevEap
}

$keyVaultUrl = "https://$KeyVaultName.vault.azure.net/"

Write-Host "Setting application settings..." -ForegroundColor Yellow
az functionapp config appsettings set `
    --name $FunctionAppName `
    --resource-group $ResourceGroupName `
    --settings `
    "KEY_VAULT_URL=$keyVaultUrl" `
    "ADF_SUBSCRIPTION_ID=$AdfSubscriptionId" `
    "ADF_RESOURCE_GROUP=$AdfResourceGroup" `
    "ADF_FACTORY_NAME=$AdfFactoryName" `
    "ADF_PIPELINE_NAME=$AdfPipelineName" `
    "ENVIRONMENT=azure" `
    "FUNCTIONS_EXTENSION_VERSION=~4" `
    "FUNCTIONS_WORKER_RUNTIME=python" `
    "PYTHON_VERSION=3.11" | Out-Null

Write-Host "Retrieving Service Bus connection string from Key Vault..." -ForegroundColor Yellow
$sbSecret = az keyvault secret show --vault-name $KeyVaultName --name "ServiceBusConnectionString" --query value -o tsv 2>$null
if ($sbSecret) {
    az functionapp config appsettings set `
        --name $FunctionAppName `
        --resource-group $ResourceGroupName `
        --settings "ServiceBusConnectionString=$sbSecret" | Out-Null
    Write-Host "ServiceBusConnectionString set from Key Vault." -ForegroundColor Green
} else {
    Write-Host "WARNING: Secret ServiceBusConnectionString not found in Key Vault. Set ServiceBusConnectionString manually in the portal." -ForegroundColor Yellow
}

Write-Host "Publishing function code (func azure functionapp publish)..." -ForegroundColor Yellow
func azure functionapp publish $FunctionAppName --python
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: func publish failed." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Deployment finished." -ForegroundColor Green
Write-Host "  App: $FunctionAppName" -ForegroundColor Cyan
Write-Host "  URL: https://${FunctionAppName}.azurewebsites.net" -ForegroundColor Cyan
Write-Host ('  Logs: az functionapp log tail --name ' + $FunctionAppName + ' --resource-group ' + $ResourceGroupName) -ForegroundColor Gray
