# PowerShell script to check Service Bus subscription filter
# Run this to verify the SQL filter on the start-transformation subscription

$namespaceName = "blache-cdtscr-dev-sb-y27jgavel2x32"
$resourceGroup = "blache-cdtscr-dev-data-rg"
$topicName = "data-ingested"
$subscriptionName = "start-transformation"

Write-Host "Checking subscription filter for: $subscriptionName" -ForegroundColor Cyan
Write-Host ""

# Get subscription details
$subscription = az servicebus topic subscription show `
    --namespace-name $namespaceName `
    --resource-group $resourceGroup `
    --topic-name $topicName `
    --name $subscriptionName `
    --query "{FilterType:filterType, SqlFilter:sqlFilter, Status:status, MessageCount:countDetails.activeMessageCount}" `
    --output json

if ($subscription) {
    Write-Host "Subscription Details:" -ForegroundColor Green
    $subscription | ConvertFrom-Json | Format-List
    Write-Host ""
    
    # Check if there's a SQL filter
    $subObj = $subscription | ConvertFrom-Json
    if ($subObj.FilterType -eq "SqlFilter" -and $subObj.SqlFilter) {
        Write-Host "SQL Filter Found:" -ForegroundColor Yellow
        Write-Host $subObj.SqlFilter.sqlExpression -ForegroundColor White
        Write-Host ""
        Write-Host "NOTE: Messages must match this filter to be delivered to this subscription!" -ForegroundColor Red
    } else {
        Write-Host "No SQL Filter - All messages to the topic will be delivered to this subscription" -ForegroundColor Green
    }
} else {
    Write-Host "Could not retrieve subscription details. Check if subscription exists." -ForegroundColor Red
}

Write-Host ""
Write-Host "To check message count in subscription:" -ForegroundColor Cyan
Write-Host "az servicebus topic subscription show --namespace-name $namespaceName --resource-group $resourceGroup --topic-name $topicName --name $subscriptionName --query countDetails.activeMessageCount" -ForegroundColor Gray
