# Azure Function Deployment Script
# Deploys the training-data-ingestion function app to Azure

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName = "blache-cdtscr-dev-data-rg",
    
    [Parameter(Mandatory=$false)]
    [string]$FunctionAppName = "func-training-ingestion-prod",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus2",
    
    [Parameter(Mandatory=$false)]
    [string]$StorageAccountName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$AppServicePlanName = "",
    
    [Parameter(Mandatory=$false)]
    [string]$KeyVaultName = "blachekvruhclai6km",
    
    [Parameter(Mandatory=$false)]
    [switch]$CreateResources
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Training Data Ingestion Function Deployment" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Azure CLI is installed
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure CLI is not installed. Please install it from https://aka.ms/installazurecliwindows" -ForegroundColor Red
    exit 1
}

# Check if logged in
$account = az account show 2>$null
if (-not $account) {
    Write-Host "Please log in to Azure CLI..." -ForegroundColor Yellow
    az login
}

# Get current directory
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Check if resource group exists
$rgExists = az group exists --name $ResourceGroupName | ConvertFrom-Json
if (-not $rgExists) {
    Write-Host "ERROR: Resource group '$ResourceGroupName' does not exist!" -ForegroundColor Red
    Write-Host "Please create it first or use an existing resource group." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "Using existing resource group: $ResourceGroupName" -ForegroundColor Green
}

# Create resources if requested
if ($CreateResources) {
    Write-Host "Creating Azure resources..." -ForegroundColor Yellow
    
    # Create Storage Account if not provided
    if ([string]::IsNullOrEmpty($StorageAccountName)) {
        # Storage account name rules:
        # - 3 to 24 characters
        # - lowercase letters and numbers only
        # Build a short, valid prefix from the Function App name
        $prefix = ($FunctionAppName -replace '[^a-z0-9]', '').ToLower()
        if ([string]::IsNullOrEmpty($prefix)) {
            $prefix = "tidingest"
        }
        # Trim prefix to leave room for random suffix
        if ($prefix.Length -gt 16) {
            $prefix = $prefix.Substring(0,16)
        }
        $rand = Get-Random -Maximum 9999
        $StorageAccountName = "{0}{1:0000}" -f $prefix, $rand

        Write-Host "Creating storage account: $StorageAccountName" -ForegroundColor Yellow
        az storage account create `
            --name $StorageAccountName `
            --resource-group $ResourceGroupName `
            --location $Location `
            --sku Standard_LRS
    }
    
    # Create Function App
    Write-Host "Creating Function App: $FunctionAppName" -ForegroundColor Yellow

    if ([string]::IsNullOrEmpty($AppServicePlanName)) {
        # Use Linux consumption plan (no explicit App Service plan)
        az functionapp create `
            --name $FunctionAppName `
            --resource-group $ResourceGroupName `
            --storage-account $StorageAccountName `
            --consumption-plan-location $Location `
            --runtime python `
            --runtime-version 3.11 `
            --functions-version 4 `
            --os-type Linux
    }
    else {
        # Use an existing App Service plan if explicitly provided
        az functionapp create `
            --name $FunctionAppName `
            --resource-group $ResourceGroupName `
            --storage-account $StorageAccountName `
            --plan $AppServicePlanName `
            --runtime python `
            --runtime-version 3.11 `
            --functions-version 4
    }
    
    Write-Host "Function App created successfully!" -ForegroundColor Green
}

# Configure Managed Identity and Key Vault access
if (-not [string]::IsNullOrEmpty($KeyVaultName)) {
    Write-Host "Configuring Managed Identity and Key Vault access..." -ForegroundColor Yellow
    
    # Enable System-Assigned Managed Identity
    Write-Host "  Enabling System-Assigned Managed Identity..." -ForegroundColor Gray
    $identityResult = az functionapp identity assign `
        --name $FunctionAppName `
        --resource-group $ResourceGroupName `
        --output json | ConvertFrom-Json
    
    $principalId = $identityResult.principalId
    Write-Host "  Managed Identity Principal ID: $principalId" -ForegroundColor Gray
    
    # Grant Key Vault access to Managed Identity (RBAC)
    Write-Host "  Granting Key Vault access to Managed Identity (RBAC)..." -ForegroundColor Gray
    # Try to find Key Vault (may be in different resource group)
    $keyVaultId = az keyvault list --query "[?name=='$KeyVaultName'].id" -o tsv | Select-Object -First 1
    if (-not $keyVaultId) {
        # Fallback: try in the same resource group
        $keyVaultId = az keyvault show --name $KeyVaultName --resource-group $ResourceGroupName --query id -o tsv 2>$null
    }
    
    if ($keyVaultId) {
        # Role ID for "Key Vault Secrets User"
        $roleId = "4633458b-17de-408a-b874-0445c86b69e6"
        az role assignment create `
            --role $roleId `
            --assignee $principalId `
            --scope $keyVaultId `
            2>&1 | Out-Null
        
        Write-Host "  Key Vault RBAC access granted!" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: Could not find Key Vault. Please grant 'Key Vault Secrets User' role manually." -ForegroundColor Yellow
    }
    
    $keyVaultUrl = "https://$KeyVaultName.vault.azure.net"
    
    # Set KEY_VAULT_URL
    Write-Host "  Setting KEY_VAULT_URL..." -ForegroundColor Gray
    az functionapp config appsettings set `
        --name $FunctionAppName `
        --resource-group $ResourceGroupName `
        --settings "KEY_VAULT_URL=$keyVaultUrl/" `
        2>&1 | Out-Null
    
    # Retrieve secrets from Key Vault and set them directly (not as references) for faster access
    Write-Host "  Retrieving secrets from Key Vault and setting as direct values..." -ForegroundColor Gray
    $secretsToRetrieve = @(
        @{Name="ServiceBusConnectionString"; KeyVaultName="ServiceBusConnectionString"},
        @{Name="PostgreSQLConnectionString"; KeyVaultName="PostgreSQLConnectionString"},
        @{Name="PostgreSQLDatabase"; KeyVaultName="PostgreSQLDatabase"},
        @{Name="BLOB_STORAGE_ACCOUNT_NAME"; KeyVaultName="BlobStorageAccountName"},
        @{Name="DATALAKE_STORAGE_ACCOUNT_NAME"; KeyVaultName="DataLakeStorageAccountName"},
        @{Name="BLOB_STORAGE_CONNECTION_STRING"; KeyVaultName="BlobStorageConnectionString"},
        @{Name="DATALAKE_STORAGE_CONNECTION_STRING"; KeyVaultName="StorageConnectionString"}
    )
    
    $settingsToSet = @()
    foreach ($secret in $secretsToRetrieve) {
        Write-Host "    Retrieving: $($secret.KeyVaultName)" -ForegroundColor DarkGray
        try {
            $secretValue = az keyvault secret show `
                --vault-name $KeyVaultName `
                --name $secret.KeyVaultName `
                --query value `
                -o tsv 2>$null
            
            if ($secretValue) {
                $settingsToSet += "$($secret.Name)=$secretValue"
                Write-Host "      [OK] Retrieved successfully" -ForegroundColor DarkGreen
            } else {
                Write-Host "      [WARN] Secret not found, skipping" -ForegroundColor DarkYellow
            }
        } catch {
            Write-Host "      [WARN] Failed to retrieve secret, skipping" -ForegroundColor DarkYellow
        }
    }
    
    if ($settingsToSet.Count -gt 0) {
        Write-Host "  Setting connection strings and secrets as direct values..." -ForegroundColor Gray
        az functionapp config appsettings set `
            --name $FunctionAppName `
            --resource-group $ResourceGroupName `
            --settings $settingsToSet `
            2>&1 | Out-Null
        Write-Host "  Connection strings and secrets configured!" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: No secrets were retrieved. Please set them manually in Function App settings." -ForegroundColor Yellow
    }
}

# Set other environment variables
Write-Host "Setting environment variables..." -ForegroundColor Yellow
az functionapp config appsettings set `
    --name $FunctionAppName `
    --resource-group $ResourceGroupName `
    --settings `
        "ENVIRONMENT=azure" `
        "SERVICEBUS_TOPIC_NAME=data-awaits-ingestion" `
        "SERVICEBUS_SUBSCRIPTION_NAME=temp-peek-subscription" `
        "BLOB_CONTAINER_NAME=data" `
        "BRONZE_CONTAINER_NAME=bronze" `
        "LOG_LEVEL=INFO" `
    2>&1 | Out-Null
Write-Host "Environment variables configured!" -ForegroundColor Green

# Deploy function code
Write-Host "Deploying function code..." -ForegroundColor Yellow
func azure functionapp publish $FunctionAppName --python

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "Deployment completed successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Function App Name: $FunctionAppName" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Yellow
Write-Host "1. Verify all app settings are configured correctly (check Azure Portal)" -ForegroundColor White
Write-Host "2. Grant Storage Blob Data Contributor role to Managed Identity on both storage accounts (when permissions are available)" -ForegroundColor White
Write-Host "3. Test the function by sending a message to the Service Bus topic" -ForegroundColor White
Write-Host "4. Monitor function logs: az functionapp log tail --name $FunctionAppName --resource-group $ResourceGroupName" -ForegroundColor White
