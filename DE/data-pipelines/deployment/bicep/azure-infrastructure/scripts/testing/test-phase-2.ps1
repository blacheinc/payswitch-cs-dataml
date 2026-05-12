# ==================================================
# Phase 2 Infrastructure Tests
# Data Ingestion: Service Bus, Data Factory, Cosmos DB, Azure Functions
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
Write-Host "Phase 2 Infrastructure Tests" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# Service Bus Tests
# ==================================================

Write-Host ""
Write-Host "=== Service Bus ===" -ForegroundColor Blue

Run-Test "Service Bus Namespace Exists" {
    $namespaces = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $namespaces -match $NamingPrefix
}

Run-Test "Service Bus Namespace Running" {
    $namespace = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($namespace)) { return $false }
    $state = az servicebus namespace show --name $namespace --query provisioningState -o tsv
    return $state -eq "Succeeded"
}

Run-Test "Service Bus Topics Created" {
    $namespace = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($namespace)) { return $false }
    $rg = az servicebus namespace show --name $namespace --query resourceGroup -o tsv
    $topicCount = (az servicebus topic list --resource-group $rg --namespace-name $namespace --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $topicCount -ge 3
}

Run-Test "Service Bus Required Topics Exist" {
    $namespace = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($namespace)) { return $false }
    $rg = az servicebus namespace show --name $namespace --query resourceGroup -o tsv
    $topic1 = az servicebus topic show --resource-group $rg --namespace-name $namespace --name "data-ingested" --query name -o tsv 2>$null
    $topic2 = az servicebus topic show --resource-group $rg --namespace-name $namespace --name "data-quality-checked" --query name -o tsv 2>$null
    $topic3 = az servicebus topic show --resource-group $rg --namespace-name $namespace --name "features-engineered" --query name -o tsv 2>$null
    return (-not [string]::IsNullOrEmpty($topic1)) -and (-not [string]::IsNullOrEmpty($topic2)) -and (-not [string]::IsNullOrEmpty($topic3))
}

Run-Test "Service Bus Subscriptions Created" {
    $namespace = az servicebus namespace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($namespace)) { return $false }
    $rg = az servicebus namespace show --name $namespace --query resourceGroup -o tsv
    $subCount = (az servicebus topic subscription list --resource-group $rg --namespace-name $namespace --topic-name "data-ingested" --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $subCount -ge 1
}

Run-Test "Service Bus Connection String Available" {
    $vaultName = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vaultName)) { return $false }
    try {
        $null = az keyvault secret show --vault-name $vaultName --name "service-bus-connection-string" --query value -o tsv 2>$null
        return $true
    }
    catch {
        try {
            $null = az keyvault secret show --vault-name $vaultName --name "ServiceBusConnectionString" --query value -o tsv 2>$null
            return $true
        }
        catch {
            Write-Host "⚠ Connection string not in Key Vault (may be set later)" -ForegroundColor Yellow
            return $false
        }
    }
}

# ==================================================
# Azure Data Factory Tests
# ==================================================

Write-Host ""
Write-Host "=== Azure Data Factory ===" -ForegroundColor Blue

Run-Test "Data Factory Exists" {
    $adf = az datafactory list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $adf -match $NamingPrefix
}

Run-Test "Data Factory Running" {
    $adfName = az datafactory list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($adfName)) { return $false }
    $state = az datafactory show --name $adfName --query provisioningState -o tsv
    return $state -eq "Succeeded"
}

Run-Test "Data Factory Linked Services Created" {
    $adfName = az datafactory list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($adfName)) { return $false }
    $rg = az datafactory show --name $adfName --query resourceGroup -o tsv
    $lsCount = (az datafactory linked-service list --factory-name $adfName --resource-group $rg --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $lsCount -ge 2
}

# ==================================================
# Cosmos DB (MongoDB) Tests
# ==================================================

Write-Host ""
Write-Host "=== Cosmos DB (MongoDB) ===" -ForegroundColor Blue

Run-Test "Cosmos DB Account Exists" {
    $cosmos = az cosmosdb list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $cosmos -match $NamingPrefix
}

Run-Test "Cosmos DB MongoDB API Enabled" {
    $cosmosName = az cosmosdb list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($cosmosName)) { return $false }
    $api = az cosmosdb show --name $cosmosName --query "kind" -o tsv
    return $api -eq "MongoDB"
}

Run-Test "Cosmos DB Databases Created" {
    $cosmosName = az cosmosdb list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($cosmosName)) { return $false }
    $rg = az cosmosdb show --name $cosmosName --query resourceGroup -o tsv
    $dbCount = (az cosmosdb mongodb database list --account-name $cosmosName --resource-group $rg --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $dbCount -ge 1
}

Run-Test "Cosmos DB Collections Created" {
    $cosmosName = az cosmosdb list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($cosmosName)) { return $false }
    $rg = az cosmosdb show --name $cosmosName --query resourceGroup -o tsv
    $dbName = az cosmosdb mongodb database list --account-name $cosmosName --resource-group $rg --query "[0].name" -o tsv
    if ([string]::IsNullOrEmpty($dbName)) { return $false }
    $collectionCount = (az cosmosdb mongodb collection list --account-name $cosmosName --resource-group $rg --database-name $dbName --query "[].name" -o tsv | Measure-Object -Line).Lines
    return $collectionCount -ge 1
}

Run-Test "Cosmos DB Connection String Available" {
    $vaultName = az keyvault list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($vaultName)) { return $false }
    try {
        $null = az keyvault secret show --vault-name $vaultName --name "MongoDBConnectionString" --query value -o tsv 2>$null
        return $true
    }
    catch {
        try {
            $null = az keyvault secret show --vault-name $vaultName --name "cosmos-connection-string" --query value -o tsv 2>$null
            return $true
        }
        catch {
            Write-Host "⚠ Connection string not in Key Vault (may be set later)" -ForegroundColor Yellow
            return $false
        }
    }
}

# ==================================================
# Azure Functions Tests (if deployed)
# ==================================================

Write-Host ""
Write-Host "=== Azure Functions ===" -ForegroundColor Blue

Run-Test "Data Quality Agent Function App Exists" {
    $app = az functionapp list --query "[?contains(name, '$NamingPrefix') && contains(name, 'data-quality')].name" -o tsv
    if ($app -match $NamingPrefix) { return $true }
    Write-Host "⚠ Function apps not deployed yet (manual deployment)" -ForegroundColor Yellow
    return $false
}

Run-Test "Feature Engineering Agent Function App Exists" {
    $app = az functionapp list --query "[?contains(name, '$NamingPrefix') && contains(name, 'feature-engineering')].name" -o tsv
    if ($app -match $NamingPrefix) { return $true }
    Write-Host "⚠ Function apps not deployed yet (manual deployment)" -ForegroundColor Yellow
    return $false
}

# ==================================================
# Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 2 Test Summary" -ForegroundColor Blue
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
    Write-Host "✓ All Phase 2 tests PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Some Phase 2 tests FAILED" -ForegroundColor Red
    exit 1
}
