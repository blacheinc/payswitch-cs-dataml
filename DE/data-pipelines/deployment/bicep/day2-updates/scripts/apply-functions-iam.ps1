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
    [string]$ServiceBusNamespaceName = "",
    [string]$ServiceBusResourceGroupName = "",
    [string[]]$ExcludedFunctionAppNames = @()
)

$ErrorActionPreference = "Stop"

function Ensure-RoleAssignment {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PrincipalId,
        [Parameter(Mandatory = $true)]
        [string]$RoleName,
        [Parameter(Mandatory = $true)]
        [string]$Scope
    )

    $existing = az role assignment list `
        --assignee-object-id $PrincipalId `
        --scope $Scope `
        --query "[?roleDefinitionName=='$RoleName'] | length(@)" `
        -o tsv

    if ($existing -eq "0") {
        az role assignment create `
            --assignee-object-id $PrincipalId `
            --assignee-principal-type ServicePrincipal `
            --role $RoleName `
            --scope $Scope | Out-Null
    }
}

$functionApps = $FunctionAppsJson | ConvertFrom-Json
if ($null -eq $functionApps -or $functionApps.Count -eq 0) {
    throw "No function apps provided."
}

$blobScope = az storage account show -g $StorageResourceGroupName -n $BlobStorageAccountName --query id -o tsv
$dlsScope = az storage account show -g $StorageResourceGroupName -n $DataLakeStorageAccountName --query id -o tsv
$kvScope = az keyvault show -g $KeyVaultResourceGroupName -n $KeyVaultName --query id -o tsv
$sbScope = ""
if (-not [string]::IsNullOrWhiteSpace($ServiceBusNamespaceName) -and -not [string]::IsNullOrWhiteSpace($ServiceBusResourceGroupName)) {
    $sbScope = az servicebus namespace show -g $ServiceBusResourceGroupName -n $ServiceBusNamespaceName --query id -o tsv
}

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

    Ensure-RoleAssignment -PrincipalId $principalId -RoleName "Storage Blob Data Contributor" -Scope $blobScope
    Ensure-RoleAssignment -PrincipalId $principalId -RoleName "Storage Blob Data Contributor" -Scope $dlsScope
    Ensure-RoleAssignment -PrincipalId $principalId -RoleName "Key Vault Secrets User" -Scope $kvScope
    Ensure-RoleAssignment -PrincipalId $principalId -RoleName "Contributor" -Scope $kvScope
    if (-not [string]::IsNullOrWhiteSpace($sbScope)) {
        Ensure-RoleAssignment -PrincipalId $principalId -RoleName "Azure Service Bus Data Sender" -Scope $sbScope
        Ensure-RoleAssignment -PrincipalId $principalId -RoleName "Azure Service Bus Data Receiver" -Scope $sbScope
    }
}

Write-Host "Functions IAM assignment completed." -ForegroundColor Green
