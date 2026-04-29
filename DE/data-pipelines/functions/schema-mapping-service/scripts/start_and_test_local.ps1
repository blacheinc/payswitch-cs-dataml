# Script to start the function locally and send a test message
# This helps test the orchestrator end-to-end

Write-Host "`n=== Starting Schema Mapping Service Locally ===" -ForegroundColor Cyan
Write-Host ""

# Check if we're in the right directory
if (-not (Test-Path "function_app.py")) {
    Write-Host "[ERROR] function_app.py not found. Please run this from the schema-mapping-service directory." -ForegroundColor Red
    exit 1
}

# Check if local.settings.json exists
if (-not (Test-Path "local.settings.json")) {
    Write-Host "[ERROR] local.settings.json not found. Please create it first." -ForegroundColor Red
    exit 1
}

Write-Host "Step 1: Starting Azure Functions host..." -ForegroundColor Yellow
Write-Host "This will start the function runtime. Keep this window open." -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop when done testing." -ForegroundColor Gray
Write-Host ""
Write-Host "Starting in 3 seconds..." -ForegroundColor Gray
Start-Sleep -Seconds 3

# Start the function host
Write-Host "`n[INFO] Starting function host..." -ForegroundColor Green
Write-Host "Watch for: 'Job host started' message" -ForegroundColor Yellow
Write-Host ""

# Start func in background
$job = Start-Job -ScriptBlock {
    Set-Location $using:PWD
    func start --python
}

Write-Host "[OK] Function host starting in background (Job ID: $($job.Id))" -ForegroundColor Green
Write-Host ""
Write-Host "Step 2: Wait for function to start, then send test message" -ForegroundColor Yellow
Write-Host ""
Write-Host "In a NEW terminal window, run:" -ForegroundColor Cyan
Write-Host "  cd data-pipelines\functions\schema-mapping-service" -ForegroundColor White
Write-Host "  python scripts\send_test_message.py" -ForegroundColor White
Write-Host ""
Write-Host "To see the function logs, check the output above or run:" -ForegroundColor Yellow
Write-Host "  Receive-Job -Id $($job.Id) -Keep" -ForegroundColor White
Write-Host ""
Write-Host "To stop the function host:" -ForegroundColor Yellow
Write-Host "  Stop-Job -Id $($job.Id)" -ForegroundColor White
Write-Host "  Remove-Job -Id $($job.Id)" -ForegroundColor White
