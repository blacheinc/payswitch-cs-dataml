# Test if the function app can resolve the Key Vault reference
# This simulates what the function runtime does

$functionAppName = "schema-mapping-service"
$resourceGroup = "blache-cdtscr-dev-data-rg"

Write-Host "Testing Key Vault reference resolution..." -ForegroundColor Cyan
Write-Host ""

# Get the app setting value
$connectionString = az functionapp config appsettings list `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "[?name=='ServiceBusConnectionString'].value" `
    --output tsv

Write-Host "ServiceBusConnectionString setting value:" -ForegroundColor Yellow
Write-Host $connectionString -ForegroundColor White
Write-Host ""

if ($connectionString -like "*@Microsoft.KeyVault*") {
    Write-Host "[INFO] Setting uses Key Vault reference" -ForegroundColor Green
    Write-Host ""
    Write-Host "To test if the function can resolve this:" -ForegroundColor Yellow
    Write-Host "1. Check function app logs for Key Vault errors" -ForegroundColor White
    Write-Host "2. Verify managed identity has 'Key Vault Secrets User' role" -ForegroundColor White
    Write-Host "3. Check if the function app is using the correct identity" -ForegroundColor White
    Write-Host ""
} else {
    Write-Host "[INFO] Setting uses direct connection string" -ForegroundColor Green
}

# Check if we can manually resolve it
Write-Host "Attempting to resolve Key Vault secret..." -ForegroundColor Yellow
$secretUri = if ($connectionString -match "SecretUri=([^)]+)") { $matches[1] } else { $null }

if ($secretUri) {
    Write-Host "Secret URI: $secretUri" -ForegroundColor Gray
    Write-Host ""
    Write-Host "To manually test resolution, use:" -ForegroundColor Yellow
    Write-Host "  az keyvault secret show --id `"$secretUri`" --query value -o tsv" -ForegroundColor Gray
}
