param(
    [Parameter(Mandatory = $true)]
    [string]$ParameterFilePath,
    [string]$SubscriptionId = ""
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ParameterFilePath)) {
    throw "Parameter file not found: $ParameterFilePath"
}

if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
    az account set --subscription $SubscriptionId | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Failed to set subscription: $SubscriptionId" }
}

$paramsDoc = Get-Content $ParameterFilePath -Raw | ConvertFrom-Json
$p = $paramsDoc.parameters

$functionApps = @($p.functionApps.value)
$excluded = @($p.excludedFunctionAppNames.value)
$blobStorage = [string]$p.blobStorageAccountName.value
$dataLakeStorage = [string]$p.dataLakeStorageAccountName.value
$storageRg = [string]$p.storageResourceGroupName.value
$keyVaultName = [string]$p.keyVaultName.value
$keyVaultRg = [string]$p.keyVaultResourceGroupName.value
$sbNamespace = [string]$p.serviceBusNamespaceName.value
$sbRg = [string]$p.serviceBusResourceGroupName.value

$subId = az account show --query id -o tsv
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($subId)) {
    throw "Unable to resolve active subscription id."
}

$roleStorageBlobDataContributor = "/subscriptions/$subId/providers/Microsoft.Authorization/roleDefinitions/ba92f5b4-2d11-453d-a403-e96b0029c9fe"
$roleKeyVaultSecretsUser = "/subscriptions/$subId/providers/Microsoft.Authorization/roleDefinitions/4633458b-17de-408a-b874-0445c86b69e6"
$roleContributor = "/subscriptions/$subId/providers/Microsoft.Authorization/roleDefinitions/b24988ac-6180-42a0-ab88-20f7382dd24c"
$roleSbDataSender = "/subscriptions/$subId/providers/Microsoft.Authorization/roleDefinitions/69a216fc-b8fb-44d8-bc22-1f3c2cd27a39"
$roleSbDataReceiver = "/subscriptions/$subId/providers/Microsoft.Authorization/roleDefinitions/4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0"

function Ensure-RoleAssignment {
    param(
        [Parameter(Mandatory = $true)][string]$PrincipalId,
        [Parameter(Mandatory = $true)][string]$Scope,
        [Parameter(Mandatory = $true)][string]$RoleDefinitionId,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $existing = az role assignment list `
        --assignee-object-id $PrincipalId `
        --scope $Scope `
        --query "[?roleDefinitionId=='$RoleDefinitionId'].id | [0]" `
        -o tsv
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to query existing role assignment for $Description"
    }

    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        Write-Host "SKIP  $Description (already assigned)" -ForegroundColor Yellow
        return
    }

    az role assignment create `
        --assignee-object-id $PrincipalId `
        --role $RoleDefinitionId `
        --scope $Scope `
        --assignee-principal-type ServicePrincipal `
        -o none
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create role assignment for $Description"
    }
    Write-Host "CREATE $Description" -ForegroundColor Green
}

$activeFunctionApps = @($functionApps | Where-Object { $excluded -notcontains $_.name })
if ($activeFunctionApps.Count -eq 0) {
    Write-Host "No active function apps to process (all excluded)." -ForegroundColor Yellow
    exit 0
}

$storageAccounts = @()
if (-not [string]::IsNullOrWhiteSpace($blobStorage)) { $storageAccounts += $blobStorage }
if (-not [string]::IsNullOrWhiteSpace($dataLakeStorage) -and $storageAccounts -notcontains $dataLakeStorage) {
    $storageAccounts += $dataLakeStorage
}

$resolvedKeyVaultRg = $keyVaultRg
if (-not [string]::IsNullOrWhiteSpace($keyVaultName)) {
    $kvResolved = az keyvault show --name $keyVaultName --query resourceGroup -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($kvResolved)) {
        $resolvedKeyVaultRg = $kvResolved
    }
}

$kvScope = ""
if (-not [string]::IsNullOrWhiteSpace($keyVaultName) -and -not [string]::IsNullOrWhiteSpace($resolvedKeyVaultRg)) {
    $kvScope = "/subscriptions/$subId/resourceGroups/$resolvedKeyVaultRg/providers/Microsoft.KeyVault/vaults/$keyVaultName"
}

$resolvedSbRg = $sbRg
if (-not [string]::IsNullOrWhiteSpace($sbNamespace)) {
    $sbResolved = az servicebus namespace list --query "[?name=='$sbNamespace'].resourceGroup | [0]" -o tsv 2>$null
    if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($sbResolved)) {
        $resolvedSbRg = $sbResolved
    }
}

$sbScope = ""
if (-not [string]::IsNullOrWhiteSpace($sbNamespace) -and -not [string]::IsNullOrWhiteSpace($resolvedSbRg)) {
    $sbScope = "/subscriptions/$subId/resourceGroups/$resolvedSbRg/providers/Microsoft.ServiceBus/namespaces/$sbNamespace"
}

Write-Host "Applying idempotent Function IAM assignments..." -ForegroundColor Cyan
Write-Host "Subscription: $subId" -ForegroundColor Cyan

foreach ($app in $activeFunctionApps) {
    $name = [string]$app.name
    $rg = [string]$app.resourceGroupName
    if ([string]::IsNullOrWhiteSpace($name) -or [string]::IsNullOrWhiteSpace($rg)) {
        throw "functionApps entries must contain non-empty name and resourceGroupName"
    }

    $principalId = az functionapp identity show --name $name --resource-group $rg --query principalId -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($principalId)) {
        throw "Unable to resolve managed identity principal for function app $name in $rg"
    }

    Write-Host "Processing $name ($principalId)" -ForegroundColor Cyan

    foreach ($sa in $storageAccounts) {
        $scope = "/subscriptions/$subId/resourceGroups/$storageRg/providers/Microsoft.Storage/storageAccounts/$sa"
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $scope `
            -RoleDefinitionId $roleStorageBlobDataContributor `
            -Description "$name -> Storage Blob Data Contributor on $sa"
    }

    if (-not [string]::IsNullOrWhiteSpace($kvScope)) {
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $kvScope `
            -RoleDefinitionId $roleKeyVaultSecretsUser `
            -Description "$name -> Key Vault Secrets User on $keyVaultName"
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $kvScope `
            -RoleDefinitionId $roleContributor `
            -Description "$name -> Contributor on $keyVaultName"
    }

    if (-not [string]::IsNullOrWhiteSpace($sbScope)) {
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $sbScope `
            -RoleDefinitionId $roleSbDataSender `
            -Description "$name -> Service Bus Data Sender on $sbNamespace"
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $sbScope `
            -RoleDefinitionId $roleSbDataReceiver `
            -Description "$name -> Service Bus Data Receiver on $sbNamespace"
    }
}

Write-Host "Idempotent function IAM assignment pass completed." -ForegroundColor Green
