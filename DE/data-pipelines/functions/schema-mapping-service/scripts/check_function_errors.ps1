# Check for function errors and connection issues
$functionAppName = "schema-mapping-service"
$resourceGroup = "blache-cdtscr-dev-data-rg"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Checking Function App Status and Errors" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check function app status
Write-Host "1. Function App Status:" -ForegroundColor Yellow
$status = az functionapp show `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "{state:state, enabledHostNames:enabledHostNames, defaultHostName:defaultHostName}" `
    --output json

$status | ConvertFrom-Json | Format-List
Write-Host ""

# Check if function is enabled
Write-Host "2. Function Status:" -ForegroundColor Yellow
$function = az functionapp function show `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --function-name schema_mapping_orchestrator `
    --query "{name:name, enabled:isEnabled}" `
    --output json

$function | ConvertFrom-Json | Format-List
Write-Host ""

# Check connection string setting
Write-Host "3. ServiceBusConnectionString Setting:" -ForegroundColor Yellow
$connStr = az functionapp config appsettings list `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "[?name=='ServiceBusConnectionString'].value" `
    --output tsv

if ($connStr -like "*@Microsoft.KeyVault*") {
    Write-Host "  [INFO] Using Key Vault reference" -ForegroundColor Green
    Write-Host "  Value: $($connStr.Substring(0, [Math]::Min(100, $connStr.Length)))..." -ForegroundColor Gray
    Write-Host ""
    Write-Host "  [WARNING] If function can't resolve this, it won't trigger!" -ForegroundColor Yellow
    Write-Host "  Verify managed identity has 'Key Vault Secrets User' role" -ForegroundColor Cyan
} else {
    Write-Host "  [INFO] Using direct connection string" -ForegroundColor Green
}
Write-Host ""

# Check recent invocations
Write-Host "4. Recent Function Invocations:" -ForegroundColor Yellow
Write-Host "  Check in Azure Portal: Functions -> schema_mapping_orchestrator -> Monitor" -ForegroundColor Gray
Write-Host ""

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "If function is not triggering:" -ForegroundColor Yellow
Write-Host "  1. Check if ServiceBusConnectionString can be resolved" -ForegroundColor White
Write-Host "  2. Try setting connection string directly (temporary workaround)" -ForegroundColor White
Write-Host "  3. Check function logs for binding errors" -ForegroundColor White
Write-Host "  4. Verify Service Bus topic/subscription names match" -ForegroundColor White
Write-Host ""
