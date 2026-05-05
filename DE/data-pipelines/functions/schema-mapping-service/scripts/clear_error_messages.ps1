# Clear error messages from start-transformation subscription
# This script will consume (remove) all messages that have status = 'ERROR'

param(
    [string]$ServiceBusNamespace = "",
    [string]$ResourceGroup = "",
    [string]$TopicName = "",
    [string]$SubscriptionName = "",
    [string]$KeyVaultUrl = ""
)

if (-not $ServiceBusNamespace) { $ServiceBusNamespace = $env:SB_NAMESPACE_NAME }
if (-not $ResourceGroup) { $ResourceGroup = $env:SB_RESOURCE_GROUP }
if (-not $TopicName) { $TopicName = $env:SB_TOPIC_NAME }
if (-not $SubscriptionName) { $SubscriptionName = $env:SB_SUBSCRIPTION_NAME }
if (-not $KeyVaultUrl) { $KeyVaultUrl = $env:KEY_VAULT_URL }

if (-not $TopicName) { $TopicName = "data-ingested" }
if (-not $SubscriptionName) { $SubscriptionName = "start-transformation" }

foreach ($pair in @(
    @{ Name = "ServiceBusNamespace"; Value = $ServiceBusNamespace },
    @{ Name = "ResourceGroup"; Value = $ResourceGroup },
    @{ Name = "KeyVaultUrl"; Value = $KeyVaultUrl }
)) {
    if (-not $pair.Value) {
        Write-Host "ERROR: Missing required value: $($pair.Name). Pass parameter or set env var." -ForegroundColor Red
        exit 1
    }
}

Write-Host "`n=== Clearing Error Messages from Subscription ===" -ForegroundColor Cyan
Write-Host "Topic: $TopicName" -ForegroundColor White
Write-Host "Subscription: $SubscriptionName" -ForegroundColor White
Write-Host "`nThis will consume (remove) all messages with status = 'ERROR'" -ForegroundColor Yellow
Write-Host ""

# Import the Python script path
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir "deprecated\read_subscription_messages.py"

Write-Host "Reading messages from subscription..." -ForegroundColor Yellow
Write-Host "Messages with status = 'ERROR' will be consumed and removed" -ForegroundColor Gray
Write-Host ""

# Run the Python script which will consume messages
Set-Item -Path Env:SB_NAMESPACE_NAME -Value $ServiceBusNamespace
Set-Item -Path Env:SB_RESOURCE_GROUP -Value $ResourceGroup
Set-Item -Path Env:SB_TOPIC_NAME -Value $TopicName
Set-Item -Path Env:SB_SUBSCRIPTION_NAME -Value $SubscriptionName
Set-Item -Path Env:KEY_VAULT_URL -Value $KeyVaultUrl
python $pythonScript

Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "Error messages have been cleared from the subscription" -ForegroundColor White
Write-Host "You can now send a new test message with the correct format" -ForegroundColor White
