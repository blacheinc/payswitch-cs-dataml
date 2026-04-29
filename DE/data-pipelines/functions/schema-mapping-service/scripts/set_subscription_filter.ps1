# Set SQL filter on start-transformation subscription
# This filter excludes error messages but allows messages with no status

param(
    [string]$ServiceBusNamespace = "blache-cdtscr-dev-sb-y27jgavel2x32",
    [string]$ResourceGroup = "blache-cdtscr-dev-data-rg",
    [string]$TopicName = "data-ingested",
    [string]$SubscriptionName = "start-transformation"
)

Write-Host "`n=== Setting SQL Filter on Subscription ===" -ForegroundColor Cyan
Write-Host "Topic: $TopicName" -ForegroundColor White
Write-Host "Subscription: $SubscriptionName" -ForegroundColor White
Write-Host "`nFilter: [status] IS NULL OR [status] != 'ERROR'" -ForegroundColor Yellow
Write-Host "This will:" -ForegroundColor Gray
Write-Host "  - Allow messages with no status property" -ForegroundColor Gray
Write-Host "  - Allow messages with status != 'ERROR'" -ForegroundColor Gray
Write-Host "  - Exclude error messages (status = 'ERROR')" -ForegroundColor Gray
Write-Host ""

$filterExpression = "[status] IS NULL OR [status] != 'ERROR'"

try {
    # First, check if there's a default rule that accepts all messages
    Write-Host "Checking existing rules..." -ForegroundColor Yellow
    $existingRules = az servicebus topic subscription rule list `
        --resource-group $ResourceGroup `
        --namespace-name $ServiceBusNamespace `
        --topic-name $TopicName `
        --subscription-name $SubscriptionName `
        --output json 2>&1 | ConvertFrom-Json
    
    if ($existingRules) {
        Write-Host "Found $($existingRules.Count) existing rule(s)" -ForegroundColor Gray
        
        # Check for default rule (accepts all)
        $defaultRule = $existingRules | Where-Object { $_.name -eq '$Default' -or ($_.filter.sqlFilter.sqlExpression -eq '1=1') }
        if ($defaultRule) {
            Write-Host "Found default rule that accepts all messages. Removing it..." -ForegroundColor Yellow
            az servicebus topic subscription rule delete `
                --resource-group $ResourceGroup `
                --namespace-name $ServiceBusNamespace `
                --topic-name $TopicName `
                --subscription-name $SubscriptionName `
                --name $defaultRule.name `
                2>&1 | Out-Null
            Write-Host "[OK] Default rule removed" -ForegroundColor Green
        }
        
        # Check if our filter rule already exists
        $existingFilterRule = $existingRules | Where-Object { $_.name -eq 'ExcludeErrors' }
        if ($existingFilterRule) {
            Write-Host "Updating existing ExcludeErrors rule..." -ForegroundColor Yellow
            az servicebus topic subscription rule update `
                --resource-group $ResourceGroup `
                --namespace-name $ServiceBusNamespace `
                --topic-name $TopicName `
                --subscription-name $SubscriptionName `
                --name "ExcludeErrors" `
                --filter-sql-expression $filterExpression `
                2>&1 | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Filter rule updated successfully" -ForegroundColor Green
            } else {
                Write-Host "[ERROR] Failed to update filter rule" -ForegroundColor Red
                exit 1
            }
        } else {
            Write-Host "Creating new ExcludeErrors rule..." -ForegroundColor Yellow
            az servicebus topic subscription rule create `
                --resource-group $ResourceGroup `
                --namespace-name $ServiceBusNamespace `
                --topic-name $TopicName `
                --subscription-name $SubscriptionName `
                --name "ExcludeErrors" `
                --filter-sql-expression $filterExpression `
                2>&1 | Out-Null
            
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Filter rule created successfully" -ForegroundColor Green
            } else {
                Write-Host "[ERROR] Failed to create filter rule" -ForegroundColor Red
                exit 1
            }
        }
    } else {
        # No existing rules, create our filter rule
        Write-Host "No existing rules found. Creating filter rule..." -ForegroundColor Yellow
        az servicebus topic subscription rule create `
            --resource-group $ResourceGroup `
            --namespace-name $ServiceBusNamespace `
            --topic-name $TopicName `
            --subscription-name $SubscriptionName `
            --name "ExcludeErrors" `
            --filter-sql-expression $filterExpression `
            2>&1 | Out-Null
        
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Filter rule created successfully" -ForegroundColor Green
        } else {
            Write-Host "[ERROR] Failed to create filter rule" -ForegroundColor Red
            exit 1
        }
    }
    
    Write-Host "`nVerifying filter..." -ForegroundColor Yellow
    $rule = az servicebus topic subscription rule show `
        --resource-group $ResourceGroup `
        --namespace-name $ServiceBusNamespace `
        --topic-name $TopicName `
        --subscription-name $SubscriptionName `
        --name "ExcludeErrors" `
        --output json 2>&1 | ConvertFrom-Json
    
    if ($rule) {
        Write-Host "[OK] Filter verified:" -ForegroundColor Green
        Write-Host "  Filter: $($rule.filter.sqlExpression)" -ForegroundColor White
        Write-Host "  Action: $($rule.action.sqlExpression)" -ForegroundColor White
    } else {
        Write-Host "[WARNING] Could not verify filter" -ForegroundColor Yellow
    }
    
    Write-Host "`n=== Filter Set Successfully ===" -ForegroundColor Green
    Write-Host "The subscription will now:" -ForegroundColor White
    Write-Host "  ✅ Accept messages with no status" -ForegroundColor Green
    Write-Host "  ✅ Accept messages with status != 'ERROR'" -ForegroundColor Green
    Write-Host "  ❌ Reject error messages (status = 'ERROR')" -ForegroundColor Red
    
} catch {
    Write-Host "[ERROR] Failed to set filter: $_" -ForegroundColor Red
    exit 1
}
