# Fix Function App Managed Identity and Key Vault Access
# This enables the function to read from Key Vault

$functionAppName = "schema-mapping-service"
$resourceGroup = "blache-cdtscr-dev-data-rg"
$keyVaultName = "blachekvruhclai6km"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Fixing Function App Identity for Key Vault Access" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Step 1: Enable System-Assigned Managed Identity
Write-Host "Step 1: Enabling System-Assigned Managed Identity..." -ForegroundColor Yellow
$identity = az functionapp identity assign `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "{principalId:principalId, tenantId:tenantId}" `
    --output json

if ($identity) {
    $identityObj = $identity | ConvertFrom-Json
    $principalId = $identityObj.principalId
    Write-Host "[OK] Managed Identity enabled" -ForegroundColor Green
    Write-Host "  Principal ID: $principalId" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host "[ERROR] Failed to enable managed identity" -ForegroundColor Red
    exit 1
}

# Step 2: Grant Key Vault Secrets User role
Write-Host "Step 2: Granting Key Vault Secrets User role..." -ForegroundColor Yellow
$roleAssignment = az role assignment create `
    --assignee $principalId `
    --role "Key Vault Secrets User" `
    --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$resourceGroup/providers/Microsoft.KeyVault/vaults/$keyVaultName" `
    --query "{id:id, principalId:principalId, roleDefinitionName:roleDefinitionName}" `
    --output json

if ($roleAssignment) {
    Write-Host "[OK] Role assignment created" -ForegroundColor Green
    $roleObj = $roleAssignment | ConvertFrom-Json
    Write-Host "  Role: $($roleObj.roleDefinitionName)" -ForegroundColor Gray
    Write-Host ""
} else {
    Write-Host "[WARNING] Role assignment may have failed or already exists" -ForegroundColor Yellow
    Write-Host "  Checking existing assignments..." -ForegroundColor Gray
    
    # Check if role already exists
    $existingRole = az role assignment list `
        --assignee $principalId `
        --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$resourceGroup/providers/Microsoft.KeyVault/vaults/$keyVaultName" `
        --query "[?roleDefinitionName=='Key Vault Secrets User']" `
        --output json
    
    if ($existingRole -and ($existingRole | ConvertFrom-Json).Count -gt 0) {
        Write-Host "[OK] Role already assigned" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to assign role. Please assign manually:" -ForegroundColor Red
        Write-Host "  az role assignment create --assignee $principalId --role 'Key Vault Secrets User' --scope '/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$resourceGroup/providers/Microsoft.KeyVault/vaults/$keyVaultName'" -ForegroundColor Gray
    }
    Write-Host ""
}

# Step 3: Verify configuration
Write-Host "Step 3: Verifying configuration..." -ForegroundColor Yellow
$verifyIdentity = az functionapp identity show `
    --name $functionAppName `
    --resource-group $resourceGroup `
    --query "{principalId:principalId, type:type}" `
    --output json

if ($verifyIdentity) {
    $verifyObj = $verifyIdentity | ConvertFrom-Json
    Write-Host "[OK] Managed Identity verified" -ForegroundColor Green
    Write-Host "  Type: $($verifyObj.type)" -ForegroundColor Gray
    Write-Host "  Principal ID: $($verifyObj.principalId)" -ForegroundColor Gray
    Write-Host ""
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Configuration Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "1. Restart the function app to apply changes:" -ForegroundColor White
Write-Host "   az functionapp restart --name $functionAppName --resource-group $resourceGroup" -ForegroundColor Gray
Write-Host ""
Write-Host "2. Wait 1-2 minutes for the function to reconnect" -ForegroundColor White
Write-Host ""
Write-Host "3. Send a test message again" -ForegroundColor White
Write-Host ""
