# Grant Managed Identity Permissions for Data Lake Storage
# This script grants the Function App's Managed Identity the necessary permissions
# to perform DFS operations on the Data Lake Storage account

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName = "blache-cdtscr-dev-data-rg",
    
    [Parameter(Mandatory=$false)]
    [string]$FunctionAppName = "func-training-ingestion-prod",
    
    [Parameter(Mandatory=$false)]
    [string]$DataLakeStorageAccountName = "blachedly27jgavel2x32"
)

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Granting Managed Identity Permissions" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

# Check if Azure CLI is installed
if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure CLI is not installed." -ForegroundColor Red
    exit 1
}

# Get Function App's Managed Identity Principal ID
Write-Host "Getting Function App Managed Identity..." -ForegroundColor Yellow
$functionAppJson = az functionapp show --name $FunctionAppName --resource-group $ResourceGroupName --query "{principalId:identity.principalId, tenantId:identity.tenantId}" --output json
$functionApp = $functionAppJson | ConvertFrom-Json

if (-not $functionApp.principalId) {
    Write-Host "ERROR: Function App does not have a Managed Identity enabled." -ForegroundColor Red
    Write-Host "Please enable System-Assigned Managed Identity first." -ForegroundColor Yellow
    exit 1
}

Write-Host "✓ Found Managed Identity Principal ID: $($functionApp.principalId)" -ForegroundColor Green

# Get Storage Account Resource ID
Write-Host "Getting Storage Account Resource ID..." -ForegroundColor Yellow
$storageAccountId = az storage account show --name $DataLakeStorageAccountName --resource-group $ResourceGroupName --query "id" --output tsv

if (-not $storageAccountId) {
    Write-Host "ERROR: Storage account '$DataLakeStorageAccountName' not found in resource group '$ResourceGroupName'." -ForegroundColor Red
    Write-Host "Trying to find it in any resource group..." -ForegroundColor Yellow
    $storageAccountId = az storage account show --name $DataLakeStorageAccountName --query "id" --output tsv 2>$null
    if (-not $storageAccountId) {
        Write-Host "ERROR: Storage account '$DataLakeStorageAccountName' not found." -ForegroundColor Red
        exit 1
    }
}

Write-Host "✓ Found Storage Account ID: $storageAccountId" -ForegroundColor Green

# Role definition ID for "Storage Blob Data Contributor"
# This is a built-in role that allows read, write, and delete access to blob containers and data
$roleDefinitionId = "ba92f5b4-2d11-453d-a403-e96b0029c9fe"  # Storage Blob Data Contributor

Write-Host ""
Write-Host "Assigning 'Storage Blob Data Contributor' role..." -ForegroundColor Yellow

# Check if role assignment already exists
$existingAssignment = az role assignment list --assignee $functionApp.principalId --scope $storageAccountId --role $roleDefinitionId --query "[0].id" --output tsv 2>$null

if ($existingAssignment) {
    Write-Host "✓ Role assignment already exists: $existingAssignment" -ForegroundColor Green
} else {
    # Create role assignment
    Write-Host "Creating role assignment..." -ForegroundColor Gray
    $assignmentJson = az role assignment create --assignee $functionApp.principalId --role $roleDefinitionId --scope $storageAccountId --output json
    
    if ($LASTEXITCODE -eq 0) {
        $assignment = $assignmentJson | ConvertFrom-Json
        Write-Host "✓ Successfully assigned 'Storage Blob Data Contributor' role" -ForegroundColor Green
        Write-Host "  Assignment ID: $($assignment.id)" -ForegroundColor Gray
    } else {
        Write-Host "ERROR: Failed to assign role." -ForegroundColor Red
        Write-Host "Error output: $assignmentJson" -ForegroundColor Red
        exit 1
    }
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "Permissions granted successfully!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "The Function App's Managed Identity now has 'Storage Blob Data Contributor' role" -ForegroundColor White
Write-Host "on the Data Lake Storage account '$DataLakeStorageAccountName'." -ForegroundColor White
Write-Host ""
Write-Host "Note: It may take a few minutes for permissions to propagate." -ForegroundColor Yellow
