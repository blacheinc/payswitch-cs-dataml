# Verify messages in Service Bus subscription
# This helps confirm messages are being delivered

$namespaceName = "blache-cdtscr-dev-sb-y27jgavel2x32"
$resourceGroup = "blache-cdtscr-dev-data-rg"
$topicName = "data-ingested"
$subscriptionName = "start-transformation"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Service Bus Subscription Message Verification" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Get initial count
Write-Host "Checking subscription: $subscriptionName" -ForegroundColor Yellow
$initialCount = az servicebus topic subscription show `
    --namespace-name $namespaceName `
    --resource-group $resourceGroup `
    --topic-name $topicName `
    --name $subscriptionName `
    --query "countDetails.activeMessageCount" `
    --output tsv

Write-Host "Current message count: $initialCount" -ForegroundColor Green
Write-Host ""

# Get subscription details
$subscription = az servicebus topic subscription show `
    --namespace-name $namespaceName `
    --resource-group $resourceGroup `
    --topic-name $topicName `
    --name $subscriptionName `
    --query "{status:status, filterType:filterType, maxDeliveryCount:maxDeliveryCount, lockDuration:lockDuration}" `
    --output json

Write-Host "Subscription Details:" -ForegroundColor Yellow
$subscription | ConvertFrom-Json | Format-List
Write-Host ""

# Check topic details
$topic = az servicebus topic show `
    --namespace-name $namespaceName `
    --resource-group $resourceGroup `
    --name $topicName `
    --query "{status:status, activeMessageCount:countDetails.activeMessageCount}" `
    --output json

Write-Host "Topic Details:" -ForegroundColor Yellow
$topic | ConvertFrom-Json | Format-List
Write-Host ""

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Interpretation:" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "If message count > 0:" -ForegroundColor White
Write-Host "  - Messages ARE being delivered to the subscription" -ForegroundColor Green
Write-Host "  - The function should process them (if it's running)" -ForegroundColor Gray
Write-Host ""
Write-Host "If message count = 0:" -ForegroundColor White
Write-Host "  - Either no messages were sent, OR" -ForegroundColor Yellow
Write-Host "  - Messages were processed/consumed by the function" -ForegroundColor Gray
Write-Host ""
Write-Host "To see messages in Azure Portal:" -ForegroundColor Cyan
Write-Host "  1. Go to Service Bus namespace" -ForegroundColor White
Write-Host "  2. Click 'Topics' -> '$topicName'" -ForegroundColor White
Write-Host "  3. Click 'Subscriptions' -> '$subscriptionName'" -ForegroundColor White
Write-Host "  4. Check 'Message count' in the Overview tab" -ForegroundColor White
Write-Host "  5. Click 'Refresh' if count doesn't update" -ForegroundColor Yellow
Write-Host ""
