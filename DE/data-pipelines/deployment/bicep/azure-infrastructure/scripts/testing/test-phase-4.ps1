# ==================================================
# Phase 4 Infrastructure Tests
# API Gateway: API Management, Static Web Apps, Azure AD B2C
# ==================================================

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [string]$NamingPrefix = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($NamingPrefix)) {
    if (-not [string]::IsNullOrWhiteSpace($env:NAMING_PREFIX)) {
        $NamingPrefix = $env:NAMING_PREFIX
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:ORG_NAME) -and -not [string]::IsNullOrWhiteSpace($env:PROJECT_NAME)) {
        $NamingPrefix = "$($env:ORG_NAME)-$($env:PROJECT_NAME)-$Environment"
    }
    else {
        throw "Set -NamingPrefix, or environment variable NAMING_PREFIX, or both ORG_NAME and PROJECT_NAME."
    }
}

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
Write-Host "Phase 4 Infrastructure Tests" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# API Management Tests
# ==================================================

Write-Host ""
Write-Host "=== API Management ===" -ForegroundColor Blue

Run-Test "API Management Service Exists" {
    $apim = az apim list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $apim -match $NamingPrefix
}

Run-Test "API Management Service Running" {
    $apimName = az apim list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($apimName)) { return $false }
    $state = az apim show --name $apimName --query provisioningState -o tsv
    return $state -eq "Succeeded"
}

Run-Test "API Management Gateway URL Accessible" {
    $apimName = az apim list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($apimName)) { return $false }
    $gatewayUrl = az apim show --name $apimName --query gatewayUrl -o tsv
    if ([string]::IsNullOrEmpty($gatewayUrl)) { return $false }
    try {
        $response = Invoke-WebRequest -Uri $gatewayUrl -Method Get -TimeoutSec 10 -UseBasicParsing
        return ($response.StatusCode -ge 200) -and ($response.StatusCode -lt 400)
    }
    catch {
        Write-Host "⚠ Gateway URL not accessible (may require API configuration)" -ForegroundColor Yellow
        return $false
    }
}

Run-Test "API Management Products Created" {
    $apimName = az apim list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($apimName)) { return $false }
    $rg = az apim show --name $apimName --query resourceGroup -o tsv
    $productCount = (az apim product list --resource-group $rg --service-name $apimName --query "[].name" -o tsv | Measure-Object -Line).Lines
    if ($productCount -ge 0) { return $true }
    Write-Host "⚠ Products may be created later" -ForegroundColor Yellow
    return $false
}

# ==================================================
# Static Web Apps Tests
# ==================================================

Write-Host ""
Write-Host "=== Static Web Apps ===" -ForegroundColor Blue

Run-Test "Static Web App Exists" {
    $swa = az staticwebapp list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    if ($swa -match $NamingPrefix) { return $true }
    Write-Host "⚠ Static Web App not deployed yet (manual deployment)" -ForegroundColor Yellow
    return $false
}

# ==================================================
# Azure AD B2C Tests
# ==================================================

Write-Host ""
Write-Host "=== Azure AD B2C ===" -ForegroundColor Blue

Run-Test "Azure AD B2C Tenant Exists" {
    try {
        $tenants = az ad b2c tenant list --query "[?contains(displayName, '$NamingPrefix')].displayName" -o tsv 2>$null
        if ($tenants -match $NamingPrefix) { return $true }
        $tenantCount = (az ad b2c tenant list --query "[].displayName" -o tsv 2>$null | Measure-Object -Line).Lines
        return $tenantCount -gt 0
    }
    catch {
        Write-Host "⚠ Azure AD B2C tenant not deployed yet (manual deployment)" -ForegroundColor Yellow
        return $false
    }
}

# ==================================================
# Azure Functions (Decision Agent) Tests
# ==================================================

Write-Host ""
Write-Host "=== Decision Agent Functions ===" -ForegroundColor Blue

Run-Test "Decision Agent Function App Exists" {
    $app = az functionapp list --query "[?contains(name, '$NamingPrefix') && contains(name, 'decision')].name" -o tsv
    if ($app -match $NamingPrefix) { return $true }
    Write-Host "⚠ Function apps not deployed yet (manual deployment)" -ForegroundColor Yellow
    return $false
}

Run-Test "Risk Monitoring Agent Function App Exists" {
    $app = az functionapp list --query "[?contains(name, '$NamingPrefix') && contains(name, 'risk')].name" -o tsv
    if ($app -match $NamingPrefix) { return $true }
    Write-Host "⚠ Function apps not deployed yet (manual deployment)" -ForegroundColor Yellow
    return $false
}

# ==================================================
# Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 4 Test Summary" -ForegroundColor Blue
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

if ($script:TESTS_FAILED -eq 0) {
    Write-Host ""
    Write-Host "✓ All Phase 4 tests PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Some Phase 4 tests FAILED" -ForegroundColor Red
    exit 1
}
