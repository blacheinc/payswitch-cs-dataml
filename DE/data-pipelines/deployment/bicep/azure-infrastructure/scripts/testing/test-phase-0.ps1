# ==================================================
# Phase 0 Infrastructure Tests
# Core Infrastructure: Key Vault, Monitoring, VNet, Storage
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
Write-Host "Phase 0 Infrastructure Tests" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# Resource Group Tests
# ==================================================

Write-Host ""
Write-Host "=== Resource Groups ===" -ForegroundColor Blue

Run-Test "Resource Groups Created" {
    $rgCount = (az group list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    return $rgCount -ge 5
}

# ==================================================
# Key Vault Tests
# ==================================================

Write-Host ""
Write-Host "=== Key Vault ===" -ForegroundColor Blue

Run-Test "Key Vault Exists" {
    $vaults = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $vaults -match $NamingPrefix
}

Run-Test "Key Vault Accessible" {
    $vaultName = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vaultName)) { return $false }
    $null = az keyvault show --name $vaultName --query id -o tsv
    return $true
}

Run-Test "Key Vault Secrets Access" {
    $vaultName = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vaultName)) { return $false }
    $null = az keyvault secret list --vault-name $vaultName --output tsv
    return $true
}

# ==================================================
# Azure Monitor Tests
# ==================================================

Write-Host ""
Write-Host "=== Azure Monitor ===" -ForegroundColor Blue

Run-Test "Log Analytics Workspace Exists" {
    $workspaces = az monitor log-analytics workspace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $workspaces -match $NamingPrefix
}

Run-Test "Log Analytics Workspace Accessible" {
    $workspace = az monitor log-analytics workspace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($workspace)) { return $false }
    $null = az monitor log-analytics workspace show --workspace-name $workspace --query id -o tsv
    return $true
}

# ==================================================
# Virtual Network Tests
# ==================================================

Write-Host ""
Write-Host "=== Virtual Network ===" -ForegroundColor Blue

Run-Test "Virtual Network Exists" {
    $vnets = az network vnet list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $vnets -match $NamingPrefix
}

Run-Test "Virtual Network Subnets Created" {
    $vnetName = az network vnet list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vnetName)) { return $false }
    $subnetCount = (az network vnet subnet list --vnet-name $vnetName --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $subnetCount -ge 3
}

Run-Test "Network Security Groups Created" {
    $nsgCount = (az network nsg list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Measure-Object -Line).Lines
    return $nsgCount -ge 1
}

# ==================================================
# Storage Account Tests
# ==================================================

Write-Host ""
Write-Host "=== Storage Account ===" -ForegroundColor Blue

Run-Test "Storage Account Exists" {
    $storage = az storage account list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $storage -match $NamingPrefix
}

Run-Test "Storage Account Accessible" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $null = az storage account show --name $storageName --query id -o tsv
    return $true
}

Run-Test "Storage Account Blob Service Enabled" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $null = az storage account blob-service-properties show --account-name $storageName --query id -o tsv
    return $true
}

Run-Test "Storage Account Container Operations" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $storageKey = az storage account keys list --account-name $storageName --query "[0].value" -o tsv
    if ([string]::IsNullOrEmpty($storageKey)) { return $false }
    $null = az storage container list --account-name $storageName --account-key $storageKey --output tsv
    return $true
}

# ==================================================
# Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 0 Test Summary" -ForegroundColor Blue
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
    Write-Host "✓ All Phase 0 tests PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Some Phase 0 tests FAILED" -ForegroundColor Red
    exit 1
}
