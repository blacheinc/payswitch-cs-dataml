# ==================================================
# Deploy → Test → Teardown Workflow
# Automated testing workflow for infrastructure validation
# ==================================================

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [int]$Phase = 0,
    [string]$NamingPrefix = "blache-$Environment",
    [string]$Teardown = "yes"
)

$ErrorActionPreference = "Stop"

# Phase names
$phaseNames = @{
    0 = "Core Infrastructure"
    1 = "Data Layer"
    2 = "Data Ingestion"
    3 = "ML Foundation"
    4 = "API Gateway"
    5 = "Full System"
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$infraDir = Split-Path -Parent (Split-Path -Parent $scriptDir)
$deployScript = Join-Path $infraDir "scripts\deploy.sh"
$destroyScript = Join-Path $infraDir "scripts\destroy.sh"
$testScript = Join-Path $scriptDir "test-phase-$Phase.ps1"

Write-Host "========================================" -ForegroundColor Blue
Write-Host "Deploy → Test → Teardown Workflow" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Phase: $Phase - $($phaseNames[$Phase])" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "Teardown: $Teardown" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# Step 1: Deploy Infrastructure
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Step 1: Deploying Infrastructure" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# Check if deploy.sh exists (for bash) or if we need PowerShell deployment
if (-not (Test-Path $deployScript)) {
    Write-Host "✗ Deploy script not found: $deployScript" -ForegroundColor Red
    Write-Host "⚠ Note: deploy.sh is a bash script. You may need to run deployment manually or use WSL/Git Bash" -ForegroundColor Yellow
    Write-Host "   Alternatively, deploy using Azure CLI directly:" -ForegroundColor Yellow
    Write-Host "   cd $infraDir\bicep-templates" -ForegroundColor Yellow
    Write-Host "   az deployment sub create --location eastus --template-file main.bicep --parameters @main.parameters.json --parameters environment=$Environment" -ForegroundColor Yellow
    exit 1
}

Write-Host "Running deployment script..." -ForegroundColor Yellow
Write-Host "⚠ Note: deploy.sh is a bash script. If this fails, use WSL/Git Bash or deploy manually" -ForegroundColor Yellow

# Try to run deploy.sh (requires WSL or Git Bash)
$deployDir = Split-Path -Parent $deployScript
Push-Location $deployDir

try {
    # Try bash (WSL or Git Bash)
    if (Get-Command bash -ErrorAction SilentlyContinue) {
        bash $deployScript $Environment
        if ($LASTEXITCODE -ne 0) {
            throw "Deployment failed with exit code $LASTEXITCODE"
        }
    }
    else {
        Write-Host "✗ bash not found. Please install WSL or Git Bash, or deploy manually" -ForegroundColor Red
        exit 1
    }
}
catch {
    Write-Host "✗ Deployment failed: $_" -ForegroundColor Red
    Pop-Location
    exit 1
}
finally {
    Pop-Location
}

Write-Host "✓ Deployment completed successfully" -ForegroundColor Green

# Wait for resources to be ready
Write-Host ""
Write-Host "Waiting 30 seconds for resources to stabilize..." -ForegroundColor Yellow
Start-Sleep -Seconds 30

# ==================================================
# Step 2: Run Tests
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Step 2: Running Tests" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

if (-not (Test-Path $testScript)) {
    Write-Host "✗ Test script not found: $testScript" -ForegroundColor Red
    Write-Host "⚠ Skipping tests, proceeding to teardown..." -ForegroundColor Yellow
    $TEST_RESULT = 1
}
else {
    try {
        & $testScript -Environment $Environment -NamingPrefix $NamingPrefix
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ All tests PASSED" -ForegroundColor Green
            $TEST_RESULT = 0
        }
        else {
            Write-Host "✗ Some tests FAILED" -ForegroundColor Red
            $TEST_RESULT = 1
        }
    }
    catch {
        Write-Host "✗ Tests failed with error: $_" -ForegroundColor Red
        $TEST_RESULT = 1
    }
}

# ==================================================
# Step 3: Teardown (if requested)
# ==================================================

if ($Teardown -eq "yes") {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Step 3: Teardown" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    
    if (-not (Test-Path $destroyScript)) {
        Write-Host "✗ Destroy script not found: $destroyScript" -ForegroundColor Red
        exit 1
    }
    
    Write-Host "This will DELETE all resources in resource groups matching: $NamingPrefix" -ForegroundColor Yellow
    Write-Host "Press Ctrl+C within 10 seconds to cancel..." -ForegroundColor Yellow
    Start-Sleep -Seconds 10
    
    $destroyDir = Split-Path -Parent $destroyScript
    Push-Location $destroyDir
    
    try {
        # Try bash (WSL or Git Bash)
        if (Get-Command bash -ErrorAction SilentlyContinue) {
            bash $destroyScript $Environment
            if ($LASTEXITCODE -ne 0) {
                throw "Teardown failed with exit code $LASTEXITCODE"
            }
        }
        else {
            Write-Host "✗ bash not found. Please install WSL or Git Bash, or destroy manually" -ForegroundColor Red
            Write-Host "   Manual teardown: az group delete --name <resource-group-name> --yes --no-wait" -ForegroundColor Yellow
            Pop-Location
            exit 1
        }
    }
    catch {
        Write-Host "✗ Teardown failed: $_" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    finally {
        Pop-Location
    }
    
    Write-Host "✓ Teardown completed successfully" -ForegroundColor Green
}
else {
    Write-Host ""
    Write-Host "⚠ Teardown skipped (TEARDOWN=no)" -ForegroundColor Yellow
    Write-Host "Resources remain deployed for manual inspection" -ForegroundColor Yellow
}

# ==================================================
# Final Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Workflow Summary" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

Write-Host ""
Write-Host "Deployment:     ✓ Completed" -ForegroundColor Green

if ($TEST_RESULT -eq 0) {
    Write-Host "Tests:          ✓ All PASSED" -ForegroundColor Green
}
else {
    Write-Host "Tests:          ✗ Some FAILED" -ForegroundColor Red
}

if ($Teardown -eq "yes") {
    Write-Host "Teardown:       ✓ Completed" -ForegroundColor Green
}
else {
    Write-Host "Teardown:       ⚠ Skipped" -ForegroundColor Yellow
}

if ($TEST_RESULT -eq 0) {
    Write-Host ""
    Write-Host "✓ Workflow completed successfully" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Workflow completed with test failures" -ForegroundColor Red
    exit 1
}
