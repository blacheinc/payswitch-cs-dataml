param(
    [Parameter(Mandatory = $true)]
    [string]$KeyVaultName,
    [Parameter(Mandatory = $true)]
    [string]$PostgresResourceGroup
)

$ErrorActionPreference = "Stop"

function Read-RequiredValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prompt
    )
    while ($true) {
        $value = Read-Host $Prompt
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
        Write-Host "Value is required." -ForegroundColor Yellow
    }
}

$postgresServerName = Read-RequiredValue -Prompt "PostgreSQL server name (without FQDN)"
$postgresHost = Read-RequiredValue -Prompt "PostgreSQL host/FQDN"
$postgresDatabase = Read-RequiredValue -Prompt "PostgreSQL database name"
$postgresAdminUser = Read-RequiredValue -Prompt "PostgreSQL admin username"
$securePassword = Read-Host "PostgreSQL admin password" -MaskInput

if (-not $securePassword) {
    throw "Password is required."
}

$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $postgresPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}

if ([string]::IsNullOrWhiteSpace($postgresPassword)) {
    throw "Password is required."
}

Write-Host "Writing PostgreSQL secrets to Key Vault '$KeyVaultName'..." -ForegroundColor Cyan
az keyvault secret set --vault-name $KeyVaultName --name "PostgreSQLServerName" --value $postgresServerName --only-show-errors -o none
az keyvault secret set --vault-name $KeyVaultName --name "PostgreSQLHost" --value $postgresHost --only-show-errors -o none
az keyvault secret set --vault-name $KeyVaultName --name "PostgreSQLDatabase" --value $postgresDatabase --only-show-errors -o none
az keyvault secret set --vault-name $KeyVaultName --name "PostgreSQLAdminUsername" --value $postgresAdminUser --only-show-errors -o none
az keyvault secret set --vault-name $KeyVaultName --name "postgres-admin-password" --value $postgresPassword --only-show-errors -o none

Write-Host "Ensuring PostgreSQL database '$postgresDatabase' exists on server '$postgresServerName'..." -ForegroundColor Cyan
$existingDb = az postgres flexible-server db show `
    --resource-group $PostgresResourceGroup `
    --server-name $postgresServerName `
    --database-name $postgresDatabase `
    --query name -o tsv 2>$null

if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($existingDb)) {
    Write-Host "Database already exists: $existingDb" -ForegroundColor Green
} else {
    az postgres flexible-server db create `
        --resource-group $PostgresResourceGroup `
        --server-name $postgresServerName `
        --database-name $postgresDatabase `
        --only-show-errors -o none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create PostgreSQL database '$postgresDatabase'."
    }
    Write-Host "Database created: $postgresDatabase" -ForegroundColor Green
}

Write-Host "PostgreSQL secrets updated and database is ready." -ForegroundColor Green
