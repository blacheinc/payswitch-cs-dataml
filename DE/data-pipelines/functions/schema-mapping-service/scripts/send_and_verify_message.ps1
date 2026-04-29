# Send a message and immediately verify it appears in the subscription
# This will help us understand if messages are actually being delivered

$namespaceName = "blache-cdtscr-dev-sb-y27jgavel2x32"
$resourceGroup = "blache-cdtscr-dev-data-rg"
$topicName = "data-ingested"
$subscriptionName = "start-transformation"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Send Message and Verify Delivery" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# Get initial count
Write-Host "1. Checking initial message count..." -ForegroundColor Yellow
$initialCount = az servicebus topic subscription show `
    --namespace-name $namespaceName `
    --resource-group $resourceGroup `
    --topic-name $topicName `
    --name $subscriptionName `
    --query "countDetails.activeMessageCount" `
    --output tsv

Write-Host "   Initial count: $initialCount" -ForegroundColor White
Write-Host ""

# Send a test message
Write-Host "2. Sending test message..." -ForegroundColor Yellow
cd "C:\Users\olanr\Desktop\blache\data-pipelines\functions\schema-mapping-service"
.\schema-mapping-env\Scripts\Activate.ps1
$testId = [guid]::NewGuid().ToString()
python -c "import sys; sys.path.insert(0, '.'); from scripts.send_test_message import send_test_message; send_test_message('https://blachekvruhclai6km.vault.azure.net/', '$testId', 'bank-digital-001', None)"
Write-Host ""

# Wait a moment
Start-Sleep -Seconds 3

# Check count again
Write-Host "3. Checking message count after sending..." -ForegroundColor Yellow
$newCount = az servicebus topic subscription show `
    --namespace-name $namespaceName `
    --resource-group $resourceGroup `
    --topic-name $topicName `
    --name $subscriptionName `
    --query "countDetails.activeMessageCount" `
    --output tsv

Write-Host "   New count: $newCount" -ForegroundColor White
Write-Host ""

if ($newCount -gt $initialCount) {
    Write-Host "[OK] Message count increased! Message was delivered." -ForegroundColor Green
} else {
    Write-Host "[WARNING] Message count did NOT increase!" -ForegroundColor Red
    Write-Host "   This suggests messages are NOT being delivered to the subscription" -ForegroundColor Yellow
}
Write-Host ""
