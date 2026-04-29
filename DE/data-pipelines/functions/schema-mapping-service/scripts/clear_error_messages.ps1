# Clear error messages from start-transformation subscription
# This script will consume (remove) all messages that have status = 'ERROR'

param(
    [string]$ServiceBusNamespace = "blache-cdtscr-dev-sb-y27jgavel2x32",
    [string]$ResourceGroup = "blache-cdtscr-dev-data-rg",
    [string]$TopicName = "data-ingested",
    [string]$SubscriptionName = "start-transformation"
)

Write-Host "`n=== Clearing Error Messages from Subscription ===" -ForegroundColor Cyan
Write-Host "Topic: $TopicName" -ForegroundColor White
Write-Host "Subscription: $SubscriptionName" -ForegroundColor White
Write-Host "`nThis will consume (remove) all messages with status = 'ERROR'" -ForegroundColor Yellow
Write-Host ""

# Import the Python script path
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "read_subscription_messages.py"

Write-Host "Reading messages from subscription..." -ForegroundColor Yellow
Write-Host "Messages with status = 'ERROR' will be consumed and removed" -ForegroundColor Gray
Write-Host ""

# Run the Python script which will consume messages
python $pythonScript

Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "Error messages have been cleared from the subscription" -ForegroundColor White
Write-Host "You can now send a new test message with the correct format" -ForegroundColor White
