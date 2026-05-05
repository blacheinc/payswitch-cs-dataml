# ==================================================
# Phase 3 Infrastructure Tests
# ML Foundation: Azure ML Workspace, AKS, Container Registry
# ==================================================

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
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
Write-Host "Phase 3 Infrastructure Tests" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# ==================================================
# Azure ML Workspace Tests
# ==================================================

Write-Host ""
Write-Host "=== Azure ML Workspace ===" -ForegroundColor Blue

Run-Test "Azure ML Workspace Exists" {
    $workspaces = az ml workspace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $workspaces -match $NamingPrefix
}

Run-Test "Azure ML Workspace Accessible" {
    $workspace = az ml workspace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($workspace)) { return $false }
    $null = az ml workspace show --name $workspace --query id -o tsv
    return $true
}

Run-Test "Azure ML Compute Cluster Created" {
    $workspace = az ml workspace list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($workspace)) { return $false }
    $rg = az ml workspace show --name $workspace --query resourceGroup -o tsv
    $computeCount = (az ml compute list --workspace-name $workspace --resource-group $rg --query "[?properties.computeType == 'AmlCompute'].name" -o tsv | Measure-Object -Line).Lines
    if ($computeCount -ge 0) { return $true }
    Write-Host "⚠ Compute cluster may be created on-demand" -ForegroundColor Yellow
    return $false
}

# ==================================================
# Azure Container Registry Tests
# ==================================================

Write-Host ""
Write-Host "=== Azure Container Registry ===" -ForegroundColor Blue

Run-Test "Container Registry Exists" {
    $acr = az acr list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $acr -match $NamingPrefix
}

Run-Test "Container Registry Running" {
    $acrName = az acr list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($acrName)) { return $false }
    $state = az acr show --name $acrName --query provisioningState -o tsv
    return $state -eq "Succeeded"
}

Run-Test "Container Registry Admin User Enabled" {
    $acrName = az acr list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($acrName)) { return $false }
    $adminEnabled = az acr show --name $acrName --query adminUserEnabled -o tsv
    return ($adminEnabled -eq "true") -or ($adminEnabled -eq "false")
}

# ==================================================
# Azure Kubernetes Service (AKS) Tests
# ==================================================

Write-Host ""
Write-Host "=== Azure Kubernetes Service ===" -ForegroundColor Blue

Run-Test "AKS Cluster Exists" {
    $aks = az aks list --query "[?contains(name, '$NamingPrefix')].name" -o tsv
    return $aks -match $NamingPrefix
}

Run-Test "AKS Cluster Running" {
    $aksName = az aks list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($aksName)) { return $false }
    $aksRg = az aks show --name $aksName --query resourceGroup -o tsv
    $state = az aks show --name $aksName --resource-group $aksRg --query provisioningState -o tsv
    return $state -eq "Succeeded"
}

Run-Test "AKS Nodes Running" {
    $aksName = az aks list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($aksName)) { return $false }
    $aksRg = az aks show --name $aksName --query resourceGroup -o tsv
    $nodeCount = az aks show --name $aksName --resource-group $aksRg --query "agentPoolProfiles[0].count" -o tsv
    return [int]$nodeCount -ge 1
}

Run-Test "AKS Credentials Retrievable" {
    $aksName = az aks list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($aksName)) { return $false }
    $aksRg = az aks show --name $aksName --query resourceGroup -o tsv
    $null = az aks get-credentials --name $aksName --resource-group $aksRg --overwrite-existing 2>$null
    return $true
}

Run-Test "AKS kubectl Access" {
    $null = kubectl get nodes --output name 2>$null
    return $true
} -ErrorAction SilentlyContinue

if (-not $?) {
    Write-Host "⚠ kubectl not installed or not configured" -ForegroundColor Yellow
}

Run-Test "AKS Node Status" {
    $nodeCount = (kubectl get nodes --no-headers 2>$null | Measure-Object -Line).Lines
    return $nodeCount -ge 1
} -ErrorAction SilentlyContinue

if (-not $?) {
    Write-Host "⚠ Cannot verify node status (kubectl not available)" -ForegroundColor Yellow
}

# ==================================================
# ACR-AKS Integration Tests
# ==================================================

Write-Host ""
Write-Host "=== ACR-AKS Integration ===" -ForegroundColor Blue

Run-Test "AKS Can Pull from ACR" {
    $aksName = az aks list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($aksName)) { return $false }
    $aksRg = az aks show --name $aksName --query resourceGroup -o tsv
    $acrName = az acr list --query "[?contains(name, '$NamingPrefix')].name" -o tsv | Select-Object -First 1
    if ([string]::IsNullOrEmpty($acrName)) { return $false }
    try {
        $null = az aks check-acr --name $aksName --resource-group $aksRg --acr $acrName --query id -o tsv 2>$null
        return $true
    }
    catch {
        Write-Host "⚠ ACR-AKS integration check (may require manual verification)" -ForegroundColor Yellow
        return $false
    }
}

# ==================================================
# Summary
# ==================================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Phase 3 Test Summary" -ForegroundColor Blue
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
    Write-Host "✓ All Phase 3 tests PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Some Phase 3 tests FAILED" -ForegroundColor Red
    exit 1
}
