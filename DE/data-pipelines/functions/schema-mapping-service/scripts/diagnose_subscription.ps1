# Diagnostic script to check subscription and rules
# This helps identify why the filter script might be hanging

param(
    [string]$ServiceBusNamespace = "blache-cdtscr-dev-sb-y27jgavel2x32",
    [string]$ResourceGroup = "blache-cdtscr-dev-data-rg",
    [string]$TopicName = "data-ingested",
    [string]$SubscriptionName = "start-transformation"
)

Write-Host "`n=== Diagnostic Check ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check Azure CLI
Write-Host "1. Checking Azure CLI..." -ForegroundColor Yellow
$azVersion = az version --output json 2>&1 | ConvertFrom-Json
if ($LASTEXITCODE -eq 0) {
    Write-Host "   [OK] Azure CLI version: $($azVersion.'azure-cli')" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Azure CLI not found or not working" -ForegroundColor Red
    exit 1
}

# 2. Check authentication
Write-Host "`n2. Checking authentication..." -ForegroundColor Yellow
$account = az account show --output json 2>&1 | ConvertFrom-Json
if ($LASTEXITCODE -eq 0 -and $account) {
    Write-Host "   [OK] Authenticated as: $($account.user.name)" -ForegroundColor Green
    Write-Host "   Subscription: $($account.name)" -ForegroundColor Gray
} else {
    Write-Host "   [ERROR] Not authenticated. Run: az login" -ForegroundColor Red
    exit 1
}

# 3. Check resource group exists
Write-Host "`n3. Checking resource group..." -ForegroundColor Yellow
$rg = az group show --name $ResourceGroup --output json 2>&1 | ConvertFrom-Json
if ($LASTEXITCODE -eq 0 -and $rg) {
    Write-Host "   [OK] Resource group exists: $($rg.name)" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Resource group not found: $ResourceGroup" -ForegroundColor Red
    exit 1
}

# 4. Check Service Bus namespace
Write-Host "`n4. Checking Service Bus namespace..." -ForegroundColor Yellow
$ns = az servicebus namespace show `
    --name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --output json 2>&1 | ConvertFrom-Json

if ($LASTEXITCODE -eq 0 -and $ns) {
    Write-Host "   [OK] Namespace exists: $($ns.name)" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Namespace not found: $ServiceBusNamespace" -ForegroundColor Red
    Write-Host "   Error: $ns" -ForegroundColor Red
    exit 1
}

# 5. Check topic exists
Write-Host "`n5. Checking topic..." -ForegroundColor Yellow
$topic = az servicebus topic show `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --name $TopicName `
    --output json 2>&1 | ConvertFrom-Json

if ($LASTEXITCODE -eq 0 -and $topic) {
    Write-Host "   [OK] Topic exists: $($topic.name)" -ForegroundColor Green
} else {
    Write-Host "   [ERROR] Topic not found: $TopicName" -ForegroundColor Red
    exit 1
}

# 6. Check subscription exists (with timeout)
Write-Host "`n6. Checking subscription (this might take a moment)..." -ForegroundColor Yellow
$subscription = az servicebus topic subscription show `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --name $SubscriptionName `
    --query "{FilterType:filterType, Status:status, MessageCount:countDetails.activeMessageCount}" `
    --output json 2>&1

if ($LASTEXITCODE -eq 0) {
    $subObj = $subscription | ConvertFrom-Json
    Write-Host "   [OK] Subscription exists" -ForegroundColor Green
    Write-Host "   Filter Type: $($subObj.FilterType)" -ForegroundColor Gray
    Write-Host "   Status: $($subObj.Status)" -ForegroundColor Gray
    Write-Host "   Message Count: $($subObj.MessageCount)" -ForegroundColor Gray
} else {
    Write-Host "   [ERROR] Subscription not found or access denied" -ForegroundColor Red
    Write-Host "   Error: $subscription" -ForegroundColor Red
    exit 1
}

# 7. List rules (with timeout)
Write-Host "`n7. Listing rules (this might take a moment)..." -ForegroundColor Yellow
$rules = az servicebus topic subscription rule list `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --subscription-name $SubscriptionName `
    --output json 2>&1

if ($LASTEXITCODE -eq 0) {
    $rulesObj = $rules | ConvertFrom-Json
    if ($rulesObj -and $rulesObj.Count -gt 0) {
        Write-Host "   [OK] Found $($rulesObj.Count) rule(s):" -ForegroundColor Green
        foreach ($rule in $rulesObj) {
            $filterExpr = if ($rule.filter.sqlFilter.sqlExpression) { $rule.filter.sqlFilter.sqlExpression } else { "N/A" }
            Write-Host "     - $($rule.name): $filterExpr" -ForegroundColor Gray
        }
    } else {
        Write-Host "   [OK] No rules found (subscription accepts all messages)" -ForegroundColor Yellow
    }
} else {
    Write-Host "   [WARNING] Could not list rules" -ForegroundColor Yellow
    Write-Host "   Error: $rules" -ForegroundColor Yellow
}

Write-Host "`n=== Diagnostic Complete ===" -ForegroundColor Green
Write-Host "If all checks passed, the filter script should work." -ForegroundColor White
Write-Host "If any step hangs, that's where the problem is." -ForegroundColor Yellow
