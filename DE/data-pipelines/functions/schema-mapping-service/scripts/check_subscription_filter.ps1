# PowerShell script to check Service Bus subscription filter
# Run this to verify the SQL filter on the start-transformation subscription

param(
    [string]$ServiceBusNamespace = "",
    [string]$ResourceGroup = "",
    [string]$TopicName = "",
    [string]$SubscriptionName = ""
)

$namespaceName = if ($ServiceBusNamespace) { $ServiceBusNamespace } else { $env:SB_NAMESPACE_NAME }
$resourceGroup = if ($ResourceGroup) { $ResourceGroup } else { $env:SB_RESOURCE_GROUP }
$topicName = if ($TopicName) { $TopicName } else { $env:SB_TOPIC_NAME }
$subscriptionName = if ($SubscriptionName) { $SubscriptionName } else { $env:SB_SUBSCRIPTION_NAME }

if (-not $topicName) { $topicName = "data-ingested" }
if (-not $subscriptionName) { $subscriptionName = "start-transformation" }

if (-not $namespaceName -or -not $resourceGroup) {
    Write-Host "ERROR: Missing Service Bus namespace/resource group. Pass parameters or set SB_NAMESPACE_NAME and SB_RESOURCE_GROUP." -ForegroundColor Red
    exit 1
}

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
