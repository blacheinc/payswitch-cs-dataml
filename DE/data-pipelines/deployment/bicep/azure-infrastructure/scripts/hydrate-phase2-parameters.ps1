param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [string]$SubscriptionId = "",
    # After main.bicep: pass the same name used in az deployment sub create --name (recommended)
    [string]$SubscriptionDeploymentName = "",
    [string]$DataResourceGroup = "",
    [string]$SecurityResourceGroup = "",
    [string]$NetworkResourceGroup = "",
    [string]$NamingPrefix = "",
    [string]$MainParametersPath = ""
)

$ErrorActionPreference = "Stop"

if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
    az account set --subscription $SubscriptionId | Out-Null
}

function Get-ArmDeploymentOutput {
    param([string]$DeploymentName)
    $jsonText = az deployment sub show --name $DeploymentName --query properties.outputs -o json 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($jsonText)) {
        throw "Subscription deployment '$DeploymentName' not found or has no outputs."
    }
    return ($jsonText | ConvertFrom-Json)
}

function Get-ArmOutputValue {
    param(
        [object]$OutputsRoot,
        [string]$Key
    )
    $p = $OutputsRoot.$Key
    if ($null -eq $p) { return "" }
    return [string]$p.value
}

function Get-FirstNameOrEmpty {
    param([string]$query)
    $value = az resource list --query $query -o tsv
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($value)) { return "" }
    return ($value -split "`n")[0].Trim()
}

# Key Vault data-plane calls fail when the vault firewall blocks this client (e.g. "not authorized and caller is not a trusted service").
# With $ErrorActionPreference = 'Stop', native stderr from `az` would otherwise terminate the script.
function Get-KeyVaultSecretTextOptional {
    param(
        [Parameter(Mandatory = $true)][string]$VaultName,
        [Parameter(Mandatory = $true)][string]$SecretName
    )
    $prevEa = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $raw = az keyvault secret show --vault-name $VaultName --name $SecretName --query value -o tsv 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) { return "" }
        return $raw.Trim()
    } finally {
        $ErrorActionPreference = $prevEa
    }
}

function Set-ParamValue {
    param(
        [object]$json,
        [string]$paramName,
        [object]$value
    )
    if ($null -eq $json.parameters.$paramName) {
        $json.parameters | Add-Member -NotePropertyName $paramName -NotePropertyValue @{ value = $value }
    } else {
        $json.parameters.$paramName.value = $value
    }
}

function Update-ParamFile {
    param(
        [string]$path,
        [hashtable]$updates,
        [string[]]$ForceEmptyKeys = @()
    )
    if (-not (Test-Path $path)) {
        Write-Host "Skipping missing file: $path" -ForegroundColor Yellow
        return
    }

    $content = Get-Content -Path $path -Raw | ConvertFrom-Json
    foreach ($k in $updates.Keys) {
        $candidate = $updates[$k]
        if ($null -eq $candidate) { continue }
        if ($candidate -is [string] -and [string]::IsNullOrWhiteSpace($candidate)) {
            if ($ForceEmptyKeys -contains $k) {
                Set-ParamValue -json $content -paramName $k -value ""
            }
            continue
        }
        Set-ParamValue -json $content -paramName $k -value $updates[$k]
    }
    $content | ConvertTo-Json -Depth 20 | Set-Content -Path $path
    Write-Host "Updated: $path" -ForegroundColor Green
}

$location = "eastus2"

# --- Resolve naming / RGs / storage / DB / KV from subscription deployment or discovery ---
$dataRg = ""
$securityRg = ""
$networkRg = ""
$namingPrefixResolved = ""
$sourceStorage = ""
$dataLakeStorage = ""
$functionsDedicatedStorage = ""
$serviceBus = ""
$redis = ""
$postgres = ""
$keyVault = ""
$vnet = ""
$postgresFqdn = ""
$postgresDbName = ""
$postgresAdminUser = ""

if (-not [string]::IsNullOrWhiteSpace($SubscriptionDeploymentName)) {
    Write-Host "Using outputs from subscription deployment: $SubscriptionDeploymentName" -ForegroundColor Cyan
    $outRoot = Get-ArmDeploymentOutput -DeploymentName $SubscriptionDeploymentName
    $namingPrefixResolved = Get-ArmOutputValue -OutputsRoot $outRoot -Key "namingPrefix"
    $sourceStorage = Get-ArmOutputValue -OutputsRoot $outRoot -Key "blobStorageAccountName"
    if ([string]::IsNullOrWhiteSpace($sourceStorage)) {
        $sourceStorage = Get-ArmOutputValue -OutputsRoot $outRoot -Key "storageAccountName"
    }
    $functionsDedicatedStorage = Get-ArmOutputValue -OutputsRoot $outRoot -Key "functionsStorageAccountName"
    $dataLakeStorage = Get-ArmOutputValue -OutputsRoot $outRoot -Key "dataLakeStorageAccountName"
    $postgresFqdn = Get-ArmOutputValue -OutputsRoot $outRoot -Key "postgresServerFqdn"
    $postgres = Get-ArmOutputValue -OutputsRoot $outRoot -Key "postgresServerName"
    $redis = Get-ArmOutputValue -OutputsRoot $outRoot -Key "redisName"
    $keyVault = Get-ArmOutputValue -OutputsRoot $outRoot -Key "keyVaultName"
    $vnet = Get-ArmOutputValue -OutputsRoot $outRoot -Key "vnetId"

    $rgObj = $outRoot.resourceGroupNames
    if ($null -ne $rgObj -and $null -ne $rgObj.value) {
        $rg = $rgObj.value
        $dataRg = [string]$rg.data
        $securityRg = [string]$rg.security
        $networkRg = [string]$rg.networking
    }
} else {
    if ([string]::IsNullOrWhiteSpace($NamingPrefix)) {
        $paramPath = $MainParametersPath
        if ([string]::IsNullOrWhiteSpace($paramPath)) {
            $paramPath = Join-Path $PSScriptRoot "..\bicep-templates\main.parameters.json"
        }
        if (-not (Test-Path $paramPath)) {
            throw "NamingPrefix is required when SubscriptionDeploymentName is not set, or pass -MainParametersPath to a main.*.parameters.json (missing: $paramPath)."
        }
        $mainParams = Get-Content -Path $paramPath -Raw | ConvertFrom-Json
        $on = [string]$mainParams.parameters.orgName.value
        $pn = [string]$mainParams.parameters.projectName.value
        if ([string]::IsNullOrWhiteSpace($on) -or [string]::IsNullOrWhiteSpace($pn)) {
            throw "main.parameters.json must define orgName and projectName, or pass -NamingPrefix explicitly."
        }
        $NamingPrefix = "$on-$pn-$Environment"
    }
    $namingPrefixResolved = $NamingPrefix
    $dataRg = if ([string]::IsNullOrWhiteSpace($DataResourceGroup)) { "$NamingPrefix-data-rg" } else { $DataResourceGroup }
    $securityRg = if ([string]::IsNullOrWhiteSpace($SecurityResourceGroup)) { "$NamingPrefix-security-rg" } else { $SecurityResourceGroup }
    $networkRg = if ([string]::IsNullOrWhiteSpace($NetworkResourceGroup)) { "$NamingPrefix-network-rg" } else { $NetworkResourceGroup }

    $sourceStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && !contains(name, 'dl') && !contains(name, 'fn')].name"
    $functionsDedicatedStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && tags.Purpose=='functions-runtime'].name"
    if ([string]::IsNullOrWhiteSpace($functionsDedicatedStorage)) {
        $functionsDedicatedStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && contains(name, 'fn')].name"
    }
    $dataLakeStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && contains(name, 'dl')].name"
    $serviceBus = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.ServiceBus/namespaces'].name"
    $redis = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Cache/Redis'].name"
    $postgres = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.DBforPostgreSQL/flexibleServers'].name"
    $keyVault = Get-FirstNameOrEmpty "[?resourceGroup=='$securityRg' && type=='Microsoft.KeyVault/vaults'].name"
    $vnet = Get-FirstNameOrEmpty "[?resourceGroup=='$networkRg' && type=='Microsoft.Network/virtualNetworks'].id"

    $postgresFqdn = ""
    if (-not [string]::IsNullOrWhiteSpace($postgres)) {
        $postgresFqdn = "$postgres.postgres.database.azure.com"
    }
}

# Explicit RG overrides beat subscription-derived values when provided
if (-not [string]::IsNullOrWhiteSpace($DataResourceGroup)) { $dataRg = $DataResourceGroup }
if (-not [string]::IsNullOrWhiteSpace($SecurityResourceGroup)) { $securityRg = $SecurityResourceGroup }
if (-not [string]::IsNullOrWhiteSpace($NetworkResourceGroup)) { $networkRg = $NetworkResourceGroup }
if (-not [string]::IsNullOrWhiteSpace($NamingPrefix)) { $namingPrefixResolved = $NamingPrefix }

# Subscription deployments created before main.bicep exposed dataLakeStorageAccountName / postgresServerFqdn / namingPrefix
# leave those strings empty — fill from live Azure using the data/security/network RGs we already resolved.
if (-not [string]::IsNullOrWhiteSpace($dataRg)) {
    if ([string]::IsNullOrWhiteSpace($namingPrefixResolved) -and $dataRg -match '^(.+)-data-rg$') {
        $namingPrefixResolved = $Matches[1]
        Write-Host "Derived namingPrefix from data RG name: $namingPrefixResolved" -ForegroundColor DarkYellow
    }
    if ([string]::IsNullOrWhiteSpace($sourceStorage)) {
        $sourceStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && !contains(name, 'dl') && !contains(name, 'fn')].name"
    }
    if ([string]::IsNullOrWhiteSpace($functionsDedicatedStorage)) {
        $functionsDedicatedStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && tags.Purpose=='functions-runtime'].name"
        if ([string]::IsNullOrWhiteSpace($functionsDedicatedStorage)) {
            $functionsDedicatedStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && contains(name, 'fn')].name"
        }
    }
    if ([string]::IsNullOrWhiteSpace($dataLakeStorage)) {
        $dataLakeStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && contains(name, 'dl')].name"
    }
    if ([string]::IsNullOrWhiteSpace($postgres)) {
        $postgres = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.DBforPostgreSQL/flexibleServers'].name"
    }
    if ([string]::IsNullOrWhiteSpace($redis)) {
        $redis = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Cache/Redis'].name"
    }
}
if (-not [string]::IsNullOrWhiteSpace($securityRg) -and [string]::IsNullOrWhiteSpace($keyVault)) {
    $keyVault = Get-FirstNameOrEmpty "[?resourceGroup=='$securityRg' && type=='Microsoft.KeyVault/vaults'].name"
}
if (-not [string]::IsNullOrWhiteSpace($networkRg) -and [string]::IsNullOrWhiteSpace($vnet)) {
    $vnet = Get-FirstNameOrEmpty "[?resourceGroup=='$networkRg' && type=='Microsoft.Network/virtualNetworks'].id"
}
if ([string]::IsNullOrWhiteSpace($postgresFqdn) -and -not [string]::IsNullOrWhiteSpace($postgres)) {
    $postgresFqdn = "$postgres.postgres.database.azure.com"
}

if (-not [string]::IsNullOrWhiteSpace($keyVault)) {
    $kvDb = Get-KeyVaultSecretTextOptional -VaultName $keyVault -SecretName "PostgreSQLDatabase"
    if (-not [string]::IsNullOrWhiteSpace($kvDb)) {
        $postgresDbName = $kvDb
    }
    $kvUser = Get-KeyVaultSecretTextOptional -VaultName $keyVault -SecretName "PostgreSQLAdminUsername"
    if (-not [string]::IsNullOrWhiteSpace($kvUser)) {
        $postgresAdminUser = $kvUser
    }
    if ([string]::IsNullOrWhiteSpace($kvDb) -and [string]::IsNullOrWhiteSpace($kvUser)) {
        Write-Warning "Key Vault data-plane read failed or secrets missing for vault '$keyVault' (e.g. client IP not allowed by vault firewall, or secrets not created). PostgreSQL name fields in parameters may stay empty; run from an allowed network or set values manually. See: https://learn.microsoft.com/azure/key-vault/general/network-security"
    }
}

$functionsSubnetId = ""
$privateEndpointsSubnetId = ""
if (-not [string]::IsNullOrWhiteSpace($vnet)) {
    $functionsSubnetId = "$vnet/subnets/functions-subnet"
    $privateEndpointsSubnetId = "$vnet/subnets/private-endpoints-subnet"
}

# Phase 2 Functions templates expect the dedicated Functions runtime storage account from main.bicep (data-services).
$functionsStorage = $functionsDedicatedStorage
if ([string]::IsNullOrWhiteSpace($functionsStorage)) {
    $functionsStorage = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.Storage/storageAccounts' && tags.Purpose=='functions-runtime'].name"
}
if ([string]::IsNullOrWhiteSpace($functionsStorage)) {
    $functionsStorage = $sourceStorage
    Write-Warning "functionsStorageAccountName ARM output missing; falling back to blob storage account for Functions parameters. Redeploy main.bicep with updated data-services for a dedicated Functions storage account."
}

# Service Bus is created in Phase 2 — hydrate discovers it after deploy; until then UPDATE skips empty and placeholders remain
if ([string]::IsNullOrWhiteSpace($serviceBus) -and -not [string]::IsNullOrWhiteSpace($dataRg)) {
    $serviceBus = Get-FirstNameOrEmpty "[?resourceGroup=='$dataRg' && type=='Microsoft.ServiceBus/namespaces'].name"
}

Write-Host "Hydration context:" -ForegroundColor Cyan
Write-Host "  namingPrefix: $namingPrefixResolved"
Write-Host "  dataRg: $dataRg"
Write-Host "  securityRg: $securityRg"
Write-Host "  networkRg: $networkRg"
Write-Host "  blob storage (backend / sourceBlob): $sourceStorage"
Write-Host "  functions runtime storage (dedicated): $functionsStorage"
Write-Host "  data lake (ADLS Gen2): $dataLakeStorage"
Write-Host "  serviceBus: $serviceBus"
Write-Host "  redis: $redis"
Write-Host "  postgres: $postgres"
Write-Host "  postgresFqdn: $postgresFqdn"
Write-Host "  postgresDbName: $postgresDbName"
Write-Host "  postgresAdminUser: $postgresAdminUser"
Write-Host "  keyVault: $keyVault"
Write-Host "  vnetId: $vnet"

$phase2 = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..")) "phase2-data-ingestion"

Update-ParamFile -path (Join-Path $phase2 "service-bus\parameters\$Environment.parameters.json") -updates @{
    location           = $location
    namingPrefix       = $namingPrefixResolved
    environment        = $Environment
    privateNetworkMode = $true
}

Update-ParamFile -path (Join-Path $phase2 "azure-data-factory\parameters\$Environment.parameters.json") -updates @{
    location                     = $location
    namingPrefix                 = $namingPrefixResolved
    deploymentEnvironment        = $Environment
    dataLakeStorageAccountName   = $dataLakeStorage
    keyVaultName                 = $keyVault
    serviceBusNamespaceName      = $serviceBus
    sourceBlobStorageAccountName = $sourceStorage
    metadataPostgresServerFqdn   = $postgresFqdn
    metadataPostgresDatabaseName = $postgresDbName
    metadataPostgresUsername     = $postgresAdminUser
    metadataPostgresPasswordSecretName = "postgres-admin-password"
    privateNetworkMode           = $true
}

Update-ParamFile -path (Join-Path $phase2 "private-network\parameters\$Environment.parameters.json") -updates @{
    location                   = $location
    namingPrefix               = $namingPrefixResolved
    vnetId                     = $vnet
    privateEndpointsSubnetId   = $privateEndpointsSubnetId
    dataResourceGroupName      = $dataRg
    securityResourceGroupName  = $securityRg
    storageAccountName         = $sourceStorage
    dataLakeStorageAccountName = $dataLakeStorage
    serviceBusNamespaceName    = $serviceBus
    redisName                  = $redis
    postgresServerName         = $postgres
    keyVaultName               = $keyVault
}

Update-ParamFile -path (Join-Path $phase2 "functions\parameters\$Environment.parameters.json") -updates @{
    location                    = $location
    namingPrefix                = $namingPrefixResolved
    functionsSubnetId           = $functionsSubnetId
    privateEndpointsSubnetId      = $privateEndpointsSubnetId
    functionsStorageAccountName = $functionsStorage
    privateNetworkMode          = $true
}

Update-ParamFile -path (Join-Path $phase2 "functions\parameters\$Environment.consumption.parameters.json") -updates @{
    location                    = $location
    namingPrefix                = $namingPrefixResolved
    functionsStorageAccountName = $functionsStorage
}

Write-Host "Parameter hydration complete for environment: $Environment" -ForegroundColor Green
