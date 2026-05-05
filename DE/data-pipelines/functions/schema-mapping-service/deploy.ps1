# Deploy Schema Mapping Azure Function (Python 3.11, Functions v4)
# Publishes code from this folder. With -CreateResources, creates the app, storage, and MI RBAC.
#
# Prerequisites: az login, Azure Functions Core Tools (`func`), subscription with rights to
# create resources / assign roles (or assign roles manually after create).
#
# Data Lake auth (both supported by orchestrator.py):
#   - If app setting DATALAKE_STORAGE_CONNECTION_STRING is set → shared key (connection string).
#   - Else → Managed Identity + DataLakeStorageAccountName from Key Vault (dfs endpoint).
# This script grants MI access to ADLS (RBAC) and, by default, copies the connection string from
# Key Vault into the app setting so you can switch methods without redeploying (clear the app setting to use MI only).
#
# Key Vault secrets used:
#   - ServiceBusConnectionString (required for trigger)
#   - DataLakeStorageAccountName (required for MI path)
#   - StorageConnectionString OR DataLakeStorageConnectionString OR DataLakeConnectionString → DATALAKE_STORAGE_CONNECTION_STRING (optional; same names as training-data-ingestion)

param(
    [Parameter(Mandatory = $false)]
    [string]$ResourceGroupName = "",

    [Parameter(Mandatory = $false)]
    [string]$FunctionAppName = "",

    [Parameter(Mandatory = $false)]
    [string]$Location = "",

    [Parameter(Mandatory = $false)]
    [string]$KeyVaultName = "",

    # ADLS Gen2 account name (no FQDN). Used for RBAC when -CreateResources is used.
    # If empty, the script tries Key Vault secret DataLakeStorageAccountName.
    [Parameter(Mandatory = $false)]
    [string]$DataLakeStorageAccountName = "",

    [Parameter(Mandatory = $false)]
    [switch]$CreateResources,

    [Parameter(Mandatory = $false)]
    [switch]$SkipPublish,

    # Do not set DATALAKE_STORAGE_CONNECTION_STRING on the Function App (use MI + account name only at runtime).
    [Parameter(Mandatory = $false)]
    [switch]$SkipDatalakeConnectionStringAppSetting
)

$ErrorActionPreference = "Stop"

# Resolve from env vars when parameters are omitted
if (-not $ResourceGroupName) { $ResourceGroupName = $env:RESOURCE_GROUP_NAME }
if (-not $FunctionAppName) { $FunctionAppName = $env:FUNCTION_APP_NAME }
if (-not $Location) { $Location = $env:AZURE_LOCATION }
if (-not $KeyVaultName) { $KeyVaultName = $env:KEY_VAULT_NAME }

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Schema Mapping Service - deploy" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Function App: $FunctionAppName" -ForegroundColor Yellow
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Yellow
Write-Host ""

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure CLI not found." -ForegroundColor Red
    exit 1
}

if (-not $SkipPublish -and -not (Get-Command func -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure Functions Core Tools (`func`) not found. Install or use -SkipPublish." -ForegroundColor Red
    exit 1
}

$account = az account show 2>$null
if (-not $account) {
    Write-Host "Run az login first." -ForegroundColor Red
    exit 1
}

if (-not $Location) { $Location = "eastus2" }
foreach ($pair in @(
    @{ Name = "ResourceGroupName"; Value = $ResourceGroupName },
    @{ Name = "FunctionAppName"; Value = $FunctionAppName },
    @{ Name = "KeyVaultName"; Value = $KeyVaultName }
)) {
    if (-not $pair.Value) {
        Write-Host "ERROR: Missing required value: $($pair.Name). Pass a parameter or set the matching environment variable." -ForegroundColor Red
        exit 1
    }
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

# Resolve ADLS account name for RBAC when not passed (Key Vault must be readable via az login).
$adlsAccountForRbac = $DataLakeStorageAccountName.Trim()
if (-not $adlsAccountForRbac) {
    $adlsAccountForRbac = az keyvault secret show --vault-name $KeyVaultName --name "DataLakeStorageAccountName" --query value -o tsv 2>$null
    if ($adlsAccountForRbac) {
        Write-Host "Using DataLakeStorageAccountName from Key Vault for ADLS RBAC: $adlsAccountForRbac" -ForegroundColor Gray
    }
}

if ($CreateResources -and -not $appExists) {
    $rand = Get-Random -Maximum 99999
    $storageAccountName = ("blcdevsms{0:00000}" -f $rand).ToLower()
    if ($storageAccountName.Length -gt 24) {
        $storageAccountName = $storageAccountName.Substring(0, 24)
    }

    Write-Host "Creating host storage account: $storageAccountName" -ForegroundColor Yellow
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
            Write-Host "WARNING: Key Vault role assignment failed. Assign Key Vault Secrets User to the Function MI in the portal." -ForegroundColor Yellow
        }
    } else {
        Write-Host "WARNING: Could not resolve Key Vault ID for RBAC." -ForegroundColor Yellow
    }

    if ($adlsAccountForRbac) {
        $dlScope = az storage account show --name $adlsAccountForRbac --query id -o tsv 2>$null
        if ($dlScope) {
            Write-Host "Granting Storage Blob Data Contributor on $adlsAccountForRbac (ADLS data plane; MI path)..." -ForegroundColor Yellow
            $null = az role assignment create `
                --role "Storage Blob Data Contributor" `
                --assignee $principalId `
                --scope $dlScope `
                2>&1
            if ($LASTEXITCODE -ne 0) {
                Write-Host "WARNING: Storage RBAC failed. Grant Storage Blob Data Contributor on the ADLS account to the Function MI." -ForegroundColor Yellow
            }
        } else {
            Write-Host "WARNING: Storage account '$adlsAccountForRbac' not found; skip ADLS RBAC." -ForegroundColor Yellow
        }
    } else {
        Write-Host "INFO: No ADLS account name (parameter or Key Vault DataLakeStorageAccountName); skip ADLS RBAC. Grant Storage Blob Data Contributor on your ADLS account to the Function MI." -ForegroundColor Yellow
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
    Write-Host "WARNING: Secret ServiceBusConnectionString not found in Key Vault. Set ServiceBusConnectionString manually on the Function App." -ForegroundColor Yellow
}

if (-not $SkipDatalakeConnectionStringAppSetting) {
    Write-Host "Retrieving Data Lake connection string from Key Vault (first match wins)..." -ForegroundColor Yellow
    $dlConn = $null
    $dlSecretUsed = $null
    foreach ($secretName in @("StorageConnectionString", "DataLakeStorageConnectionString", "DataLakeConnectionString")) {
        $dlConn = az keyvault secret show --vault-name $KeyVaultName --name $secretName --query value -o tsv 2>$null
        if ($dlConn) {
            $dlSecretUsed = $secretName
            break
        }
    }
    if ($dlConn) {
        az functionapp config appsettings set `
            --name $FunctionAppName `
            --resource-group $ResourceGroupName `
            --settings "DATALAKE_STORAGE_CONNECTION_STRING=$dlConn" | Out-Null
        Write-Host "DATALAKE_STORAGE_CONNECTION_STRING set from Key Vault secret: $dlSecretUsed (orchestrator uses this before MI)." -ForegroundColor Green
    } else {
        Write-Host "INFO: No StorageConnectionString / DataLakeStorageConnectionString / DataLakeConnectionString in Key Vault - ADLS will use Managed Identity + DataLakeStorageAccountName." -ForegroundColor Yellow
    }
} else {
    Write-Host "Skipped DATALAKE_STORAGE_CONNECTION_STRING (-SkipDatalakeConnectionStringAppSetting); runtime uses MI for ADLS when unset." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Runtime: DATALAKE_STORAGE_CONNECTION_STRING wins when set; otherwise DefaultAzureCredential + DataLakeStorageAccountName." -ForegroundColor Gray
Write-Host ""

if (-not $SkipPublish) {
    Write-Host "Publishing function code (func azure functionapp publish)..." -ForegroundColor Yellow
    func azure functionapp publish $FunctionAppName --python
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: func publish failed." -ForegroundColor Red
        exit 1
    }
} else {
    Write-Host "Skipped code publish (-SkipPublish)." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Deployment finished." -ForegroundColor Green
Write-Host "  App: $FunctionAppName" -ForegroundColor Cyan
Write-Host "  URL: https://$($FunctionAppName).azurewebsites.net" -ForegroundColor Cyan
Write-Host ('  Logs: az functionapp log tail --name ' + $FunctionAppName + ' --resource-group ' + $ResourceGroupName) -ForegroundColor Gray
