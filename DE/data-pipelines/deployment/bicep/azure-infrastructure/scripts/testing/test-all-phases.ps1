# ==================================================
# Master Test Orchestrator
# Runs all phase tests in sequence
# ==================================================

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [string]$NamingPrefix = "blache-$Environment"
)

$ErrorActionPreference = "Stop"

$script:PHASES_PASSED = 0
$script:PHASES_FAILED = 0
$script:FAILED_PHASES = @()

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "========================================" -ForegroundColor Blue
Write-Host "Master Test Orchestrator" -ForegroundColor Blue
Write-Host "Environment: $Environment" -ForegroundColor Blue
Write-Host "Naming Prefix: $NamingPrefix" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

# Function to run phase test
function Run-PhaseTest {
    param(
        [int]$Phase,
        [string]$PhaseName
    )
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Blue
    Write-Host "Running Phase $Phase Tests: $PhaseName" -ForegroundColor Blue
    Write-Host "========================================" -ForegroundColor Blue
    
    $testScript = Join-Path $scriptDir "test-phase-$Phase.ps1"
    
    if (Test-Path $testScript) {
        try {
            & $testScript -Environment $Environment -NamingPrefix $NamingPrefix
            if ($LASTEXITCODE -eq 0) {
                Write-Host ""
                Write-Host "✓ Phase $Phase tests PASSED" -ForegroundColor Green
                $script:PHASES_PASSED++
                return $true
            }
            else {
                Write-Host ""
                Write-Host "✗ Phase $Phase tests FAILED" -ForegroundColor Red
                $script:PHASES_FAILED++
                $script:FAILED_PHASES += "Phase $Phase : $PhaseName"
                return $false
            }
        }
        catch {
            Write-Host ""
            Write-Host "✗ Phase $Phase tests FAILED with error: $_" -ForegroundColor Red
            $script:PHASES_FAILED++
            $script:FAILED_PHASES += "Phase $Phase : $PhaseName"
            return $false
        }
    }
    else {
        Write-Host ""
        Write-Host "✗ Test script not found: $testScript" -ForegroundColor Red
        $script:PHASES_FAILED++
        $script:FAILED_PHASES += "Phase $Phase : $PhaseName (script not found)"
        return $false
    }
}

# Run all phase tests
Run-PhaseTest -Phase 0 -PhaseName "Core Infrastructure"
Run-PhaseTest -Phase 1 -PhaseName "Data Layer"
Run-PhaseTest -Phase 2 -PhaseName "Data Ingestion"
Run-PhaseTest -Phase 3 -PhaseName "ML Foundation"
Run-PhaseTest -Phase 4 -PhaseName "API Gateway"
Run-PhaseTest -Phase 5 -PhaseName "Full System"

# Summary
Write-Host ""
Write-Host "========================================" -ForegroundColor Blue
Write-Host "Master Test Summary" -ForegroundColor Blue
Write-Host "========================================" -ForegroundColor Blue

$TOTAL_PHASES = $script:PHASES_PASSED + $script:PHASES_FAILED

Write-Host ""
Write-Host "Total Phases:   $TOTAL_PHASES"
Write-Host "Passed:         $($script:PHASES_PASSED)" -ForegroundColor Green

if ($script:PHASES_FAILED -gt 0) {
    Write-Host "Failed:         $($script:PHASES_FAILED)" -ForegroundColor Red
    Write-Host ""
    Write-Host "Failed Phases:"
    foreach ($phase in $script:FAILED_PHASES) {
        Write-Host "  - $phase" -ForegroundColor Red
    }
}
else {
    Write-Host "Failed:         $($script:PHASES_FAILED)"
}

$PASS_RATE = if ($TOTAL_PHASES -gt 0) { [math]::Round(($script:PHASES_PASSED * 100) / $TOTAL_PHASES) } else { 0 }
Write-Host "Pass Rate:      $PASS_RATE%"

if ($script:PHASES_FAILED -eq 0) {
    Write-Host ""
    Write-Host "✓ All phase tests PASSED" -ForegroundColor Green
    exit 0
}
else {
    Write-Host ""
    Write-Host "✗ Some phase tests FAILED" -ForegroundColor Red
    exit 1
}
