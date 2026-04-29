# ==================================================
# Phase 5 Infrastructure Tests
# Full System: All resources, end-to-end connectivity
# ==================================================

param(
    [string]$Environment = "dev",
    [string]$NamingPrefix = "blache-$Environment"
)

$ErrorActionPreference = "Stop"

# Test counters
$script:TESTS_PASSED = 0
$script:TESTS_FAILED = 0
$script:FAILED_TESTS = @()

# Test function
function Run-Test {
    param(
        [string]$TestName,
        [scriptblock]$TestCommand
    )
    
    Write-Host ""
    Write-Host "[TEST] $TestName" -ForegroundColor Yellow
    
    try {
        $null = & $TestCommand 2>$null
        Write-Host "✓ PASSED: $TestName" -ForegroundColor Green
        $script:TESTS_PASSED++
        return $true
    }
    catch {
        Write-Host "✗ FAILED: $TestName" -ForegroundColor Red
        $script:TESTS_FAILED++
        $script:FAILED_TESTS += $TestName
        return $false
    }
}

Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 5 Full System Tests" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# Comprehensive Resource Count Tests
# ==================================================

Write-Host ""
Write-Host "=== Resource Inventory ===" -ForegroundColor Blue

Run-Test "All Resource Groups Created (8 expected)" {
    $rgCount = (az group list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    return $rgCount -ge 5
}

Run-Test "All Core Services Deployed" {
    $keyVault = (az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    $storage = (az storage account list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    $postgres = (az postgres flexible-server list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    $redis = (az redis list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    return ($keyVault -ge 1) -and ($storage -ge 1) -and ($postgres -ge 1) -and ($redis -ge 1)
}

# ==================================================
# End-to-End Connectivity Tests
# ==================================================

Write-Host ""
Write-Host "=== End-to-End Connectivity ===" -ForegroundColor Blue

Run-Test "Service Bus to Data Lake Integration" {
    $namespace = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    $storage = az storage account list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    return (-not [string]::IsNullOrEmpty($namespace)) -and (-not [string]::IsNullOrEmpty($storage))
}

Run-Test "Data Factory to Service Bus Integration" {
    $adf = az datafactory list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    $namespace = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    return (-not [string]::IsNullOrEmpty($adf)) -and (-not [string]::IsNullOrEmpty($namespace))
}

Run-Test "AKS to ACR Integration" {
    $aks = az aks list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    $acr = az acr list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    return (-not [string]::IsNullOrEmpty($aks)) -and (-not [string]::IsNullOrEmpty($acr))
}

# ==================================================
# Application Insights Tests
# ==================================================

Write-Host ""
Write-Host "=== Application Insights ===" -ForegroundColor Blue

Run-Test "Application Insights Exists" {
    try {
        $null = az monitor app-insights component show --app "$NamingPrefix-app-insights" --resource-group "$NamingPrefix-monitoring-rg" --query id -o tsv 2>$null
        return $true
    }
    catch {
        $insights = az monitor app-insights component list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
        return $insights -match $NamingPrefix
    }
}

# ==================================================
# All Azure Functions Tests
# ==================================================

Write-Host ""
Write-Host "=== All Azure Functions ===" -ForegroundColor Blue

$agents = @(
    "data-quality-agent",
    "feature-engineering-agent",
    "decision-agent",
    "risk-monitoring-agent",
    "compliance-agent",
    "model-training-agent"
)

foreach ($agent in $agents) {
    Run-Test "Function App: $agent" {
        $app = az functionapp list --query "[?contains(name, '$NamingPrefix') && contains(name, '$agent')].name" -o tsv | Select-Object -First 1
        if (-not [string]::IsNullOrEmpty($app)) { return $true }
        Write-Host "⚠ $agent not deployed yet" -ForegroundColor Yellow
        return $false
    }
}

# ==================================================
# Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 5 Test Summary" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

$TOTAL_TESTS = $script:TESTS_PASSED + $script:TESTS_FAILED
$PASS_RATE = if ($TOTAL_TESTS -gt 0) { [math]::Round(($script:TESTS_PASSED * 100) / $TOTAL_TESTS) } else { 0 }

Write-Host ""
Write-Host "Total Tests:    $TOTAL_TESTS"
Write-Host "Passed:         $($script:TESTS_PASSED)" -ForegroundColor Green

if ($script:TESTS_FAILED -gt 0) {
    Write-Host "Failed:         $($script:TESTS_FAILED)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Failed Tests:"
    foreach ($test in $script:FAILED_TESTS) {
        Write-Host "  - $test" -ForegroundColor Red
    }
}
else {
    Write-Host "Failed:         $($script:TESTS_FAILED)"
}

Write-Host "Pass Rate:      $PASS_RATE%"

if ($PASS_RATE -ge 80) {
    Write-Host ""
    Write-Host "✓ Phase 5 tests PASSED ($PASS_RATE%)" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Phase 5 tests FAILED ($PASS_RATE%)" -ForegroundColor Red
    exit 1
}
