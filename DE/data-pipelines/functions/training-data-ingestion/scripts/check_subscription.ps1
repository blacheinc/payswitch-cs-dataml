# PowerShell script to check Service Bus subscription for data-awaits-ingestion topic
# This helps diagnose why messages might not be received

param(
    [string]$ServiceBusNamespace = "blache-cdtscr-dev-sb-y27jgavel2x32",
    [string]$ResourceGroup = "blache-cdtscr-dev-data-rg",
    [string]$TopicName = "data-awaits-ingestion",
    [string]$SubscriptionName = "temp-peek-subscription"
)

Write-Host "`n=== Checking Service Bus Subscription ===" -ForegroundColor Cyan
Write-Host "Topic: $TopicName" -ForegroundColor White
Write-Host "Subscription: $SubscriptionName" -ForegroundColor White
Write-Host "Namespace: $ServiceBusNamespace" -ForegroundColor White
Write-Host ""

# Check if subscription exists
Write-Host "Checking if subscription exists..." -ForegroundColor Yellow
$subscription = az servicebus topic subscription show `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --topic-name $TopicName `
    --name $SubscriptionName `
    --query "{Name:name, FilterType:filterType, SqlFilter:sqlFilter, Status:status, ActiveMessages:countDetails.activeMessageCount, DeadLetterMessages:countDetails.deadLetterMessageCount}" `
    --output json 2>$null

if ($subscription) {
    $subObj = $subscription | ConvertFrom-Json
    Write-Host "✅ Subscription exists!" -ForegroundColor Green
    Write-Host ""
    Write-Host "Subscription Details:" -ForegroundColor Cyan
    Write-Host "  Name: $($subObj.Name)" -ForegroundColor White
    Write-Host "  Status: $($subObj.Status)" -ForegroundColor White
    Write-Host "  Active Messages: $($subObj.ActiveMessages)" -ForegroundColor $(if ($subObj.ActiveMessages -gt 0) { "Green" } else { "Yellow" })
    Write-Host "  Dead Letter Messages: $($subObj.DeadLetterMessages)" -ForegroundColor $(if ($subObj.DeadLetterMessages -gt 0) { "Red" } else { "White" })
    Write-Host ""
    
    # Check filter
    if ($subObj.FilterType -eq "SqlFilter" -and $subObj.SqlFilter) {
        Write-Host "⚠️  SQL FILTER FOUND:" -ForegroundColor Yellow
        Write-Host "  Filter Expression: $($subObj.SqlFilter.sqlExpression)" -ForegroundColor White
        Write-Host ""
        Write-Host "  ⚠️  WARNING: Messages must match this filter to be delivered!" -ForegroundColor Red
        Write-Host "  If your messages don't have the required custom properties," -ForegroundColor Red
        Write-Host "  they will NOT be delivered to this subscription." -ForegroundColor Red
    } else {
        Write-Host "✅ No SQL Filter - All messages will be delivered" -ForegroundColor Green
    }
} else {
    Write-Host "❌ Subscription does NOT exist!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Available subscriptions on topic '$TopicName':" -ForegroundColor Yellow
    az servicebus topic subscription list `
        --namespace-name $ServiceBusNamespace `
        --resource-group $ResourceGroup `
        --topic-name $TopicName `
        --output table
}

Write-Host ""
Write-Host "=== Topic Message Count ===" -ForegroundColor Cyan
$topic = az servicebus topic show `
    --namespace-name $ServiceBusNamespace `
    --resource-group $ResourceGroup `
    --name $TopicName `
    --query "{ActiveMessages:countDetails.activeMessageCount, SizeInBytes:sizeInBytes}" `
    --output json 2>$null

if ($topic) {
    $topicObj = $topic | ConvertFrom-Json
    Write-Host "  Active Messages in Topic: $($topicObj.ActiveMessages)" -ForegroundColor $(if ($topicObj.ActiveMessages -gt 0) { "Green" } else { "Yellow" })
    Write-Host "  Topic Size: $($topicObj.SizeInBytes) bytes" -ForegroundColor White
} else {
    Write-Host "  Could not retrieve topic details" -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Recommendations ===" -ForegroundColor Cyan
if ($subscription) {
    $subObj = $subscription | ConvertFrom-Json
    if ($subObj.ActiveMessages -eq 0 -and $topicObj.ActiveMessages -gt 0) {
        Write-Host "  ⚠️  Topic has messages but subscription has none!" -ForegroundColor Yellow
        Write-Host "  This likely means:" -ForegroundColor Yellow
        Write-Host "    1. The subscription has a SQL filter that doesn't match the messages" -ForegroundColor Yellow
        Write-Host "    2. The messages don't have the required custom properties" -ForegroundColor Yellow
        Write-Host ""
        Write-Host "  Solution: Check the message custom properties and update the filter" -ForegroundColor Green
    } elseif ($subObj.ActiveMessages -gt 0) {
        Write-Host "  ✅ Subscription has $($subObj.ActiveMessages) message(s) ready to be received" -ForegroundColor Green
    } else {
        Write-Host "  ℹ️  No messages in topic or subscription" -ForegroundColor White
    }
} else {
    Write-Host "  ❌ Create the subscription first, or use an existing one" -ForegroundColor Red
}
