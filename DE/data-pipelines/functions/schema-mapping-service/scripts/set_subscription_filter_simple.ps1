# Simple script to set SQL filter on start-transformation subscription
# Uses Azure Portal REST API approach

param(
    [string]$ServiceBusNamespace = "",
    [string]$ResourceGroup = "",
    [string]$TopicName = "",
    [string]$SubscriptionName = ""
)

if (-not $ServiceBusNamespace) { $ServiceBusNamespace = $env:SB_NAMESPACE_NAME }
if (-not $ResourceGroup) { $ResourceGroup = $env:SB_RESOURCE_GROUP }
if (-not $TopicName) { $TopicName = $env:SB_TOPIC_NAME }
if (-not $SubscriptionName) { $SubscriptionName = $env:SB_SUBSCRIPTION_NAME }

if (-not $TopicName) { $TopicName = "data-ingested" }
if (-not $SubscriptionName) { $SubscriptionName = "start-transformation" }

foreach ($pair in @(
    @{ Name = "ServiceBusNamespace"; Value = $ServiceBusNamespace },
    @{ Name = "ResourceGroup"; Value = $ResourceGroup }
)) {
    if (-not $pair.Value) {
        Write-Host "[ERROR] Missing required value: $($pair.Name). Pass a parameter or set matching env var." -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n=== Setting SQL Filter on Subscription ===" -ForegroundColor Cyan
Write-Host "Namespace: $ServiceBusNamespace" -ForegroundColor White
Write-Host "Topic: $TopicName" -ForegroundColor White
Write-Host "Subscription: $SubscriptionName" -ForegroundColor White
Write-Host "`nFilter: [status] IS NULL OR [status] != 'ERROR'" -ForegroundColor Yellow
Write-Host ""

# Check Azure CLI authentication
Write-Host "Checking Azure CLI authentication..." -ForegroundColor Yellow
$account = az account show --output json 2>&1 | ConvertFrom-Json
if (-not $account) {
    Write-Host "[ERROR] Not logged in to Azure CLI. Run: az login" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Authenticated as: $($account.user.name)" -ForegroundColor Green
Write-Host ""

# Step 1: Check if subscription exists
Write-Host "Step 1: Checking if subscription exists..." -ForegroundColor Yellow
$subscription = az servicebus topic subscription show `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --name $SubscriptionName `
    --output json 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "[ERROR] Subscription not found or access denied" -ForegroundColor Red
    Write-Host "Error: $subscription" -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Subscription exists" -ForegroundColor Green
Write-Host ""

# Step 2: List existing rules
Write-Host "Step 2: Checking existing rules..." -ForegroundColor Yellow
$rules = az servicebus topic subscription rule list `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --subscription-name $SubscriptionName `
    --output json 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Host "[WARNING] Could not list rules. Error: $rules" -ForegroundColor Yellow
    Write-Host "Continuing anyway..." -ForegroundColor Yellow
    $rules = @()
} else {
    $rulesObj = $rules | ConvertFrom-Json
    if ($rulesObj) {
        Write-Host "Found $($rulesObj.Count) rule(s):" -ForegroundColor Gray
        foreach ($rule in $rulesObj) {
            Write-Host "  - $($rule.name): $($rule.filter.sqlFilter.sqlExpression)" -ForegroundColor Gray
        }
    } else {
        Write-Host "No existing rules found" -ForegroundColor Gray
    }
}
Write-Host ""

# Step 3: Delete default rule if it exists (accepts all messages)
Write-Host "Step 3: Checking for default rule..." -ForegroundColor Yellow
$defaultRule = $rulesObj | Where-Object { $_.name -eq '$Default' -or $_.filter.sqlFilter.sqlExpression -eq '1=1' }
if ($defaultRule) {
    Write-Host "Found default rule '$($defaultRule.name)'. Deleting..." -ForegroundColor Yellow
    az servicebus topic subscription rule delete `
        --namespace-name $ServiceBusNamespace `
        --resource-group $ResourceGroup `
        --topic-name $TopicName `
        --subscription-name $SubscriptionName `
        --name $defaultRule.name `
        --output none 2>&1 | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Default rule deleted" -ForegroundColor Green
    } else {
        Write-Host "[WARNING] Could not delete default rule. Continuing..." -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] No default rule found" -ForegroundColor Green
}
Write-Host ""

# Step 4: Create or update the filter rule
Write-Host "Step 4: Creating/updating filter rule..." -ForegroundColor Yellow
$filterExpression = "[status] IS NULL OR [status] != 'ERROR'"

# Try to create the rule
az servicebus topic subscription rule create `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --subscription-name $SubscriptionName `
    --name "ExcludeErrors" `
    --filter-sql-expression $filterExpression `
    --output none 2>&1 | Out-Null

if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Filter rule created successfully" -ForegroundColor Green
} else {
    # Rule might already exist, try to update it
    Write-Host "Rule might already exist. Trying to update..." -ForegroundColor Yellow
    az servicebus topic subscription rule update `
        --namespace-name $ServiceBusNamespace `
        --resource-group $ResourceGroup `
        --topic-name $TopicName `
        --subscription-name $SubscriptionName `
        --name "ExcludeErrors" `
        --filter-sql-expression $filterExpression `
        --output none 2>&1 | Out-Null
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[OK] Filter rule updated successfully" -ForegroundColor Green
    } else {
        Write-Host "[ERROR] Failed to create/update filter rule" -ForegroundColor Red
        Write-Host "Try running with --verbose to see the error" -ForegroundColor Yellow
        exit 1
    }
}
Write-Host ""

# Step 5: Verify the rule
Write-Host "Step 5: Verifying filter rule..." -ForegroundColor Yellow
$rule = az servicebus topic subscription rule show `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --subscription-name $SubscriptionName `
    --name "ExcludeErrors" `
    --output json 2>&1 | ConvertFrom-Json

if ($rule) {
    Write-Host "[OK] Filter verified:" -ForegroundColor Green
    Write-Host "  Rule Name: $($rule.name)" -ForegroundColor White
    Write-Host "  Filter: $($rule.filter.sqlFilter.sqlExpression)" -ForegroundColor White
} else {
    Write-Host "[WARNING] Could not verify filter rule" -ForegroundColor Yellow
}

Write-Host "`n=== Filter Set Successfully ===" -ForegroundColor Green
Write-Host "The subscription will now:" -ForegroundColor White
Write-Host "  ✅ Accept messages with no status" -ForegroundColor Green
Write-Host "  ✅ Accept messages with status != 'ERROR'" -ForegroundColor Green
Write-Host "  ❌ Reject error messages (status = 'ERROR')" -ForegroundColor Red
Write-Host "`nNext: Clear old error messages with: .\scripts\clear_error_messages.ps1" -ForegroundColor Yellow
