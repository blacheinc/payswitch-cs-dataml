# Check PostgreSQL Flexible Server Availability
# Verifies if PostgreSQL Flexible Server can be deployed in a region

param(
    [Parameter(Mandatory=$true)]
    [string]$Location
)

Write-Host ""
Write-Host "Checking PostgreSQL Flexible Server availability in: $Location" -ForegroundColor Cyan
Write-Host ""

# Check available SKUs for PostgreSQL Flexible Server
Write-Host "Checking available SKUs..." -ForegroundColor Yellow
$skus = az postgres flexible-server list-skus --location $Location -o json 2>&1

if ($LASTEXITCODE -eq 0) {
    $skuList = $skus | ConvertFrom-Json
    if ($skuList.Count -gt 0) {
        Write-Host "PostgreSQL Flexible Server IS AVAILABLE in $Location" -ForegroundColor Green
        Write-Host ""
        Write-Host "Available SKUs (showing first 10):" -ForegroundColor Yellow
        $skuList | Select-Object -First 10 | Format-Table -Property name, tier, @{Label="Size";Expression={$_.size}}
        Write-Host ""
        Write-Host "You can proceed with deployment in $Location" -ForegroundColor Green
    } else {
        Write-Host "No SKUs available in $Location" -ForegroundColor Red
        Write-Host "PostgreSQL Flexible Server may not be available in this region" -ForegroundColor Yellow
    }
} else {
    Write-Host "ERROR checking availability" -ForegroundColor Red
    Write-Host ""
    Write-Host "Error details:" -ForegroundColor Yellow
    Write-Host $skus -ForegroundColor Red
    Write-Host ""
    Write-Host "This may indicate:" -ForegroundColor Yellow
    Write-Host "  1. PostgreSQL Flexible Server is not available in $Location" -ForegroundColor Yellow
    Write-Host "  2. Your subscription does not have access to this service in $Location" -ForegroundColor Yellow
    Write-Host "  3. You need to request quota/access from Azure Support" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "To check other regions, run:" -ForegroundColor Cyan
Write-Host '  .\check-postgres-availability.ps1 -Location "region-name"' -ForegroundColor Cyan
Write-Host ""
Write-Host "Common regions to try:" -ForegroundColor Cyan
Write-Host "  - eastus2" -ForegroundColor White
Write-Host "  - westeurope" -ForegroundColor White
Write-Host "  - westus2" -ForegroundColor White
Write-Host "  - centralus" -ForegroundColor White
Write-Host "  - uksouth" -ForegroundColor White
Write-Host ""
