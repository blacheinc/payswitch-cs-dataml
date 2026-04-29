# Set Service Bus connection string directly (temporary workaround)
# This bypasses Key Vault reference resolution issues

$functionAppName = "schema-mapping-service"
$resourceGroup = "blache-cdtscr-dev-data-rg"
$keyVaultName = "blachekvruhclai6km"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Setting Service Bus Connection String Directly" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[WARNING] This sets the connection string directly (less secure)" -ForegroundColor Yellow
Write-Host "This is a temporary workaround to test if the function triggers" -ForegroundColor Yellow
Write-Host ""

# Get connection string from Key Vault
Write-Host "Retrieving connection string from Key Vault..." -ForegroundColor Yellow
$connStr = az keyvault secret show `
    --vault-name $keyVaultName `
    --name ServiceBusConnectionString `
    --query value `
    --output tsv

if (-not $connStr) {
    Write-Host "[ERROR] Failed to retrieve connection string from Key Vault" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Connection string retrieved" -ForegroundColor Green
Write-Host ""

# Set it directly in function app
Write-Host "Setting connection string in function app..." -ForegroundColor Yellow
az functionapp config appsettings set `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --settings ServiceBusConnectionString="$connStr" `
    --output none

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Connection string set successfully" -ForegroundColor Green
    Write-Host ""
    Write-Host "Restarting function app..." -ForegroundColor Yellow
    az functionapp restart --name $functionAppName --resource-group $resourceGroup --output none
    Write-Host "[OK] Function app restarted" -ForegroundColor Green
    Write-Host ""
    Write-Host "Wait 30-60 seconds for the function to reconnect, then send a test message" -ForegroundColor Cyan
} else {
    Write-Host "[ERROR] Failed to set connection string" -ForegroundColor Red
    exit 1
}
