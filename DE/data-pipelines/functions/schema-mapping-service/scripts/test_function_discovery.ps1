# Test if the function is being discovered by the runtime

$functionAppName = "schema-mapping-service"
$resourceGroup = "blache-cdtscr-dev-data-rg"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Testing Function Discovery" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Check function via REST API
Write-Host "1. Checking function via REST API..." -ForegroundColor Yellow
$functions = az rest --method GET --uri "https://$functionAppName.azurewebsites.net/admin/functions" 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Function API accessible" -ForegroundColor Green
    $functions | ConvertFrom-Json | ForEach-Object {
        Write-Host "  Function: $($_.name)" -ForegroundColor Gray
        Write-Host "    Language: $($_.language)" -ForegroundColor Gray
        Write-Host "    Script Root Path: $($_.scriptRootPathHref)" -ForegroundColor Gray
    }
} else {
    Write-Host "[WARNING] Could not access function API" -ForegroundColor Yellow
    Write-Host "Response: $functions" -ForegroundColor Gray
}
Write-Host ""

# Check specific function
Write-Host "2. Checking schema_mapping_orchestrator function..." -ForegroundColor Yellow
$function = az functionapp function show `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --function-name schema_mapping_orchestrator `
    --query "{name:name, config:config.bindings}" `
    --output json

if ($function) {
    Write-Host "[OK] Function found" -ForegroundColor Green
    $function | ConvertFrom-Json | Format-List
} else {
    Write-Host "[ERROR] Function not found!" -ForegroundColor Red
}
Write-Host ""

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "If function is not found, check:" -ForegroundColor Yellow
Write-Host "  1. Deployment was successful" -ForegroundColor White
Write-Host "  2. function_app.py is in the root directory" -ForegroundColor White
Write-Host "  3. No import errors in function_app.py" -ForegroundColor White
Write-Host "  4. host.json is configured correctly" -ForegroundColor White
Write-Host ""
