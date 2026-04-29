param(
    [Parameter(Mandatory = $true)]
    [string]$FunctionAppsJson,
    [Parameter(Mandatory = $true)]
    [string]$BlobStorageAccountName,
    [Parameter(Mandatory = $true)]
    [string]$DataLakeStorageAccountName,
    [Parameter(Mandatory = $true)]
    [string]$StorageResourceGroupName,
    [Parameter(Mandatory = $true)]
    [string]$KeyVaultName,
    [Parameter(Mandatory = $true)]
    [string]$KeyVaultResourceGroupName,
    [string[]]$ExcludedFunctionAppNames = @("payswitch-creditscore-prod-file-checksum-func")
)

$ErrorActionPreference = "Stop"

$functionApps = $FunctionAppsJson | ConvertFrom-Json
if ($null -eq $functionApps -or $functionApps.Count -eq 0) {
    throw "No function apps provided."
}

$blobScope = az storage account show -g $StorageResourceGroupName -n $BlobStorageAccountName --query id -o tsv
$dlsScope = az storage account show -g $StorageResourceGroupName -n $DataLakeStorageAccountName --query id -o tsv
$kvScope = az keyvault show -g $KeyVaultResourceGroupName -n $KeyVaultName --query id -o tsv

if ([string]::IsNullOrWhiteSpace($blobScope) -or [string]::IsNullOrWhiteSpace($dlsScope) -or [string]::IsNullOrWhiteSpace($kvScope)) {
    throw "Could not resolve one or more target scopes (blob/datalake/keyvault)."
}

foreach ($app in $functionApps) {
    $name = [string]$app.name
    $rg = [string]$app.resourceGroupName

    if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($rg)) {
        Write-Warning "Skipping invalid function app entry: $($app | ConvertTo-Json -Compress)"
        continue
    }

    if ($ExcludedFunctionAppNames -contains $name) {
        Write-Host "Skipping excluded function app: $name" -ForegroundColor Yellow
        continue
    }

    $principalId = az functionapp identity show -g $rg -n $name --query principalId -o tsv
    if ([string]::IsNullOrWhiteSpace($principalId)) {
        Write-Warning "No managed identity principalId for $name in $rg. Skipping."
        continue
    }

    Write-Host "Applying roles for $name ($rg)..." -ForegroundColor Cyan

    az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope $blobScope | Out-Null
    az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope $dlsScope | Out-Null
    az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $kvScope | Out-Null
    az role assignment create --assignee-object-id $principalId --assignee-principal-type ServicePrincipal --role "Contributor" --scope $kvScope | Out-Null
}

Write-Host "Functions IAM assignment completed." -ForegroundColor Green
