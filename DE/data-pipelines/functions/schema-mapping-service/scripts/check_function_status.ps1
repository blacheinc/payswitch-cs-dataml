# Comprehensive function status check

$functionAppName = "schema-mapping-service"
$resourceGroup = "blache-cdtscr-dev-data-rg"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Function Status Check" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check function app state
Write-Host "1. Function App State:" -ForegroundColor Yellow
$app = az functionapp show `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "{state:state, availabilityState:availabilityState, enabledHostNames:enabledHostNames[0]}" `
    --output json

$app | ConvertFrom-Json | Format-List
Write-Host ""

# 2. Check function registration
Write-Host "2. Function Registration:" -ForegroundColor Yellow
$function = az functionapp function show `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --function-name schema_mapping_orchestrator `
    --query "{name:name, config:config.bindings[0].type}" `
    --output json

if ($function) {
    Write-Host "[OK] Function is registered" -ForegroundColor Green
    $function | ConvertFrom-Json | Format-List
} else {
    Write-Host "[ERROR] Function not found!" -ForegroundColor Red
}
Write-Host ""

# 3. Check connection strings
Write-Host "3. Connection Strings:" -ForegroundColor Yellow
$connStr = az functionapp config appsettings list `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "[?name=='ServiceBusConnectionString'].value" `
    --output tsv

if ($connStr -and $connStr.Length -gt 50) {
    Write-Host "[OK] ServiceBusConnectionString is set" -ForegroundColor Green
    Write-Host "   Length: $($connStr.Length) characters" -ForegroundColor Gray
} else {
    Write-Host "[ERROR] ServiceBusConnectionString is missing or invalid!" -ForegroundColor Red
}
Write-Host ""

$storage = az functionapp config appsettings list `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "[?name=='AzureWebJobsStorage'].value" `
    --output tsv

if ($storage -and $storage.Contains("AccountKey=")) {
    Write-Host "[OK] AzureWebJobsStorage is set with credentials" -ForegroundColor Green
} else {
    Write-Host "[WARNING] AzureWebJobsStorage may be incomplete" -ForegroundColor Yellow
}
Write-Host ""

# 4. Check message count
Write-Host "4. Service Bus Message Count:" -ForegroundColor Yellow
$msgCount = az servicebus topic subscription show `
    --namespace-name blache-cdtscr-dev-sb-y27jgavel2x32 `
    --resource-group $resourceGroup `
    --topic-name data-ingested `
    --name start-transformation `
    --query "countDetails.activeMessageCount" `
    --output tsv

Write-Host "   Active messages: $msgCount" -ForegroundColor White
Write-Host ""

# 5. Recommendations
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Recommendations:" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "If function is not triggering:" -ForegroundColor Yellow
Write-Host "  1. Check function logs in Azure Portal:" -ForegroundColor White
Write-Host "     Functions -> schema_mapping_orchestrator -> Monitor" -ForegroundColor Gray
Write-Host ""
Write-Host "  2. Check Application Insights for errors" -ForegroundColor White
Write-Host ""
Write-Host "  3. Verify function runtime is healthy:" -ForegroundColor White
Write-Host "     Check 'Log stream' in Azure Portal" -ForegroundColor Gray
Write-Host ""
Write-Host "  4. Try manually triggering the function:" -ForegroundColor White
Write-Host "     Functions -> schema_mapping_orchestrator -> Test/Run" -ForegroundColor Gray
Write-Host ""
