# Purge Key Vault in Soft Delete State
# Key Vaults are globally unique and must be purged before name can be reused

param(
    [Parameter(Mandatory=$true)]
    [string]$KeyVaultName,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus2"
)

Write-Host ""
Write-Host "Checking Key Vault: $KeyVaultName" -ForegroundColor Cyan
Write-Host ""

# Check if Key Vault exists (including soft-deleted)
$deletedVaults = az keyvault list-deleted --query "[?name=='$KeyVaultName']" -o json 2>&1 | ConvertFrom-Json

if ($deletedVaults.Count -gt 0) {
    Write-Host "Found Key Vault in soft-delete state:" -ForegroundColor Yellow
    Write-Host "  Name: $($deletedVaults[0].name)" -ForegroundColor Yellow
    Write-Host "  Location: $($deletedVaults[0].properties.location)" -ForegroundColor Yellow
    Write-Host "  Deletion Date: $($deletedVaults[0].properties.deletionDate)" -ForegroundColor Yellow
    Write-Host "  Scheduled Purge Date: $($deletedVaults[0].properties.scheduledPurgeDate)" -ForegroundColor Yellow
    Write-Host ""
    
    Write-Host "Purging Key Vault..." -ForegroundColor Yellow
    az keyvault purge --name $KeyVaultName --location $Location
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Key Vault purged successfully!" -ForegroundColor Green
        Write-Host "You can now deploy with the same name." -ForegroundColor Green
    } else {
        Write-Host "Failed to purge Key Vault. Error:" -ForegroundColor Red
        Write-Host "You may need to wait for the scheduled purge date, or use a different name." -ForegroundColor Yellow
    }
} else {
    Write-Host "Key Vault not found in soft-delete state." -ForegroundColor Yellow
    Write-Host "The name might be taken by another subscription, or it was never created." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Options:" -ForegroundColor Cyan
    Write-Host "  1. Use a different naming prefix to generate a new unique name" -ForegroundColor White
    Write-Host "  2. Wait and try again later" -ForegroundColor White
    Write-Host "  3. Check if the Key Vault exists in another resource group:" -ForegroundColor White
    Write-Host "     az keyvault list --query `"[?name=='$KeyVaultName']`" -o table" -ForegroundColor Cyan
}

Write-Host ""
