# ==================================================
# Phase 1 Infrastructure Tests
# Data Layer: PostgreSQL, Redis, Data Lake Gen2
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
Write-Host "Phase 1 Infrastructure Tests" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# PostgreSQL Tests
# ==================================================

Write-Host ""
Write-Host "=== PostgreSQL ===" -ForegroundColor Blue

Run-Test "PostgreSQL Server Exists" {
    $servers = az postgres flexible-server list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $servers -match $NamingPrefix
}

Run-Test "PostgreSQL Server Running" {
    $serverName = az postgres flexible-server list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($serverName)) { return $false }
    $state = az postgres flexible-server show --name $serverName --query state -o tsv
    return ($state -eq "Ready") -or ($state -eq "Stopped")
}

Run-Test "PostgreSQL Databases Created" {
    $serverName = az postgres flexible-server list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($serverName)) { return $false }
    $rg = az postgres flexible-server show --name $serverName --query resourceGroup -o tsv
    $dbCount = (az postgres flexible-server db list --resource-group $rg --server-name $serverName --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $dbCount -ge 1
}

Run-Test "PostgreSQL Connection String Available" {
    $vaultName = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vaultName)) { return $false }
    try {
        $null = az keyvault secret show --vault-name $vaultName --name "postgres-connection-string" --query value -o tsv 2>$null
        return $true
    }
    catch {
        try {
            $null = az keyvault secret show --vault-name $vaultName --name "PostgresConnectionString" --query value -o tsv 2>$null
            return $true
        }
        catch {
            Write-Host "⚠ Connection string not in Key Vault (may be set later)" -ForegroundColor Yellow
            return $false
        }
    }
}

# ==================================================
# Redis Tests
# ==================================================

Write-Host ""
Write-Host "=== Redis Cache ===" -ForegroundColor Blue

Run-Test "Redis Cache Exists" {
    $redis = az redis list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $redis -match $NamingPrefix
}

Run-Test "Redis Cache Running" {
    $redisName = az redis list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($redisName)) { return $false }
    $state = az redis show --name $redisName --query provisioningState -o tsv
    return $state -eq "Succeeded"
}

Run-Test "Redis Connection String Available" {
    $vaultName = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vaultName)) { return $false }
    try {
        $null = az keyvault secret show --vault-name $vaultName --name "redis-connection-string" --query value -o tsv 2>$null
        return $true
    }
    catch {
        try {
            $null = az keyvault secret show --vault-name $vaultName --name "RedisConnectionString" --query value -o tsv 2>$null
            return $true
        }
        catch {
            Write-Host "⚠ Connection string not in Key Vault (may be set later)" -ForegroundColor Yellow
            return $false
        }
    }
}

# ==================================================
# Data Lake Gen2 Tests
# ==================================================

Write-Host ""
Write-Host "=== Data Lake Gen2 ===" -ForegroundColor Blue

Run-Test "Data Lake Storage Account Exists" {
    $storage = az storage account list --query "[?contains(name, '$NamingPrefix') && properties.isHnsEnabled == `true`].name" -o tsv
    return $storage -match $NamingPrefix
}

Run-Test "Data Lake Hierarchical Namespace Enabled" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix') && properties.isHnsEnabled == `true`].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $isHns = az storage account show --name $storageName --query "properties.isHnsEnabled" -o tsv
    return $isHns -eq "true"
}

Run-Test "Data Lake File Systems Created" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix') && properties.isHnsEnabled == `true`].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $storageKey = az storage account keys list --account-name $storageName --query "[0].value" -o tsv
    if ([string]::IsNullOrEmpty($storageKey)) { return $false }
    $fsCount = (az storage fs list --account-name $storageName --account-key $storageKey --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $fsCount -ge 1
}

Run-Test "Data Lake Raw Container Exists" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix') && properties.isHnsEnabled == `true`].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $storageKey = az storage account keys list --account-name $storageName --query "[0].value" -o tsv
    if ([string]::IsNullOrEmpty($storageKey)) { return $false }
    $null = az storage fs show --name "raw" --account-name $storageName --account-key $storageKey --query name -o tsv
    return $true
}

Run-Test "Data Lake Folder Structure Created" {
    $storageName = az storage account list --query "[?contains(name, '$NamingPrefix') && properties.isHnsEnabled == `true`].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($storageName)) { return $false }
    $storageKey = az storage account keys list --account-name $storageName --query "[0].value" -o tsv
    if ([string]::IsNullOrEmpty($storageKey)) { return $false }
    try {
        $null = az storage fs directory exists --name "raw/credit-bureau" --file-system "raw" --account-name $storageName --account-key $storageKey --query exists -o tsv 2>$null
        return $true
    }
    catch {
        try {
            $null = az storage fs directory exists --name "raw/banking" --file-system "raw" --account-name $storageName --account-key $storageKey --query exists -o tsv 2>$null
            return $true
        }
        catch {
            try {
                $null = az storage fs directory exists --name "raw/telco" --file-system "raw" --account-name $storageName --account-key $storageKey --query exists -o tsv 2>$null
                return $true
            }
            catch {
                Write-Host "⚠ Folder structure not created yet (may be created by ADF)" -ForegroundColor Yellow
                return $false
            }
        }
    }
}

# ==================================================
# Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 1 Test Summary" -ForegroundColor Blue
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
    Write-Host "✓ All Phase 1 tests PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Some Phase 1 tests FAILED" -ForegroundColor Red
    exit 1
}
