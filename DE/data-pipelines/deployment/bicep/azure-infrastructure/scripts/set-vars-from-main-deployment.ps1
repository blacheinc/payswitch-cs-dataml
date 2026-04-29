<#
.SYNOPSIS
  Loads Azure subscription deployment outputs from main.bicep into global PowerShell variables.

.EXAMPLE
  cd $SCRIPTS
  . .\set-vars-from-main-deployment.ps1 -DeploymentName $DEPLOYMENT_NAME_MAIN

  Uses $MainBlobStorageAccountName (GPv2 blob), $MainDataLakeStorageAccountName (ADLS Gen2), $MainRgData, etc.
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$DeploymentName,
    [string]$SubscriptionId = "",
    [switch]$RequireCoreValues
)

$ErrorActionPreference = "Stop"

if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
    az account set --subscription $SubscriptionId | Out-Null
}

$jsonText = az deployment sub show --name $DeploymentName --query properties.outputs -o json 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($jsonText)) {
    throw "Deployment '$DeploymentName' not found or has no outputs. Use the exact name from az deployment sub list."
}

$raw = $jsonText | ConvertFrom-Json

function Get-ArmOutput([string]$key) {
    $p = $raw.$key
    if ($null -eq $p) { return "" }
    return [string]$p.value
}

$blob = Get-ArmOutput "blobStorageAccountName"
if ([string]::IsNullOrWhiteSpace($blob)) {
    $blob = Get-ArmOutput "storageAccountName"
}

$global:MainNamingPrefix = Get-ArmOutput "namingPrefix"
$global:MainBlobStorageAccountName = $blob
$global:MainDataLakeStorageAccountName = Get-ArmOutput "dataLakeStorageAccountName"
$global:MainPostgresServerFqdn = Get-ArmOutput "postgresServerFqdn"
$global:MainKeyVaultName = Get-ArmOutput "keyVaultName"
$global:MainPostgresServerName = Get-ArmOutput "postgresServerName"
$global:MainRedisName = Get-ArmOutput "redisName"
$global:MainVnetId = Get-ArmOutput "vnetId"
$global:MainBastionName = Get-ArmOutput "bastionName"
$global:MainJumpVmName = Get-ArmOutput "jumpVmName"
$global:MainAksClusterName = Get-ArmOutput "aksClusterName"
$global:MainMlWorkspaceName = Get-ArmOutput "mlWorkspaceName"

$rgObj = $raw.resourceGroupNames
if ($null -ne $rgObj -and $null -ne $rgObj.value) {
    $rg = $rgObj.value
    $global:MainRgAgents = [string]$rg.agents
    $global:MainRgCompute = [string]$rg.compute
    $global:MainRgCore = [string]$rg.core
    $global:MainRgData = [string]$rg.data
    $global:MainRgMl = [string]$rg.ml
    $global:MainRgMonitoring = [string]$rg.monitoring
    $global:MainRgNetworking = [string]$rg.networking
    $global:MainRgSecurity = [string]$rg.security
} else {
    $global:MainRgAgents = ""
    $global:MainRgCompute = ""
    $global:MainRgCore = ""
    $global:MainRgData = ""
    $global:MainRgMl = ""
    $global:MainRgMonitoring = ""
    $global:MainRgNetworking = ""
    $global:MainRgSecurity = ""
}

$global:MainFunctionsSubnetId = ""
$global:MainPrivateEndpointsSubnetId = ""
if (-not [string]::IsNullOrWhiteSpace($global:MainVnetId)) {
    $global:MainFunctionsSubnetId = "$($global:MainVnetId)/subnets/functions-subnet"
    $global:MainPrivateEndpointsSubnetId = "$($global:MainVnetId)/subnets/private-endpoints-subnet"
}

# Convenience aliases used in runbooks/one-off CLI commands
$global:DATA_RG = $global:MainRgData
$global:SECURITY_RG = $global:MainRgSecurity
$global:NETWORK_RG = $global:MainRgNetworking
$global:VNET_ID = $global:MainVnetId
$global:FUNCTIONS_SUBNET_ID = $global:MainFunctionsSubnetId
$global:PRIVATE_ENDPOINTS_SUBNET_ID = $global:MainPrivateEndpointsSubnetId

$global:VNET_NAME = ""
if (-not [string]::IsNullOrWhiteSpace($global:VNET_ID)) {
    $parts = $global:VNET_ID -split '/'
    if ($parts.Length -gt 0) {
        $global:VNET_NAME = $parts[-1]
    }
}

function Assert-Set([string]$name, [string]$value) {
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Required variable '$name' is empty. Ensure deployment outputs include it and rerun this script."
    }
}

if ($RequireCoreValues) {
    Assert-Set "MainRgData / DATA_RG" $global:DATA_RG
    Assert-Set "MainRgSecurity / SECURITY_RG" $global:SECURITY_RG
    Assert-Set "MainRgNetworking / NETWORK_RG" $global:NETWORK_RG
    Assert-Set "MainVnetId / VNET_ID" $global:VNET_ID
    Assert-Set "VNET_NAME" $global:VNET_NAME
    Assert-Set "MainBlobStorageAccountName" $global:MainBlobStorageAccountName
    Assert-Set "MainDataLakeStorageAccountName" $global:MainDataLakeStorageAccountName
}

Write-Host "Loaded outputs from deployment '$DeploymentName' (Main* globals + DATA_RG/SECURITY_RG/NETWORK_RG aliases)." -ForegroundColor Green
