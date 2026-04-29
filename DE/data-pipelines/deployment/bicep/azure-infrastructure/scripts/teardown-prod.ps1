param(
    [Parameter(Mandatory = $true)]
    [string]$DeploymentName,
    [string]$SubscriptionId = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI is required. Install Azure CLI and retry."
}

if (-not [string]::IsNullOrWhiteSpace($SubscriptionId)) {
    Write-Info "Setting subscription to $SubscriptionId"
    az account set --subscription $SubscriptionId | Out-Null
}

$account = az account show -o json 2>$null | ConvertFrom-Json
if ($null -eq $account) {
    throw "You are not logged in. Run 'az login' and retry."
}
Write-Info "Subscription: $($account.name) ($($account.id))"

Write-Info "Loading outputs from deployment: $DeploymentName"
$outputsJson = az deployment sub show --name $DeploymentName --query properties.outputs -o json
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($outputsJson)) {
    throw "Deployment '$DeploymentName' not found or has no outputs."
}

$outputs = $outputsJson | ConvertFrom-Json
$rgMap = $outputs.resourceGroupNames.value
if ($null -eq $rgMap) {
    throw "Deployment '$DeploymentName' does not expose output 'resourceGroupNames'."
}

$resourceGroups = @(
    [string]$rgMap.core,
    [string]$rgMap.networking,
    [string]$rgMap.data,
    [string]$rgMap.compute,
    [string]$rgMap.ml,
    [string]$rgMap.security,
    [string]$rgMap.monitoring,
    [string]$rgMap.agents
) | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Sort-Object -Unique

if ($resourceGroups.Count -eq 0) {
    throw "No resource groups were resolved from deployment outputs."
}

Write-Host ""
Write-Host "Resource groups queued for deletion:" -ForegroundColor Yellow
foreach ($rg in $resourceGroups) {
    $exists = az group exists --name $rg
    $status = if ($exists -eq "true") { "exists" } else { "not-found" }
    Write-Host " - $rg [$status]"
}
Write-Host ""

if (-not $Force) {
    Write-Warn "This permanently deletes the full prod environment (all listed resource groups)."
    $typed = Read-Host "Type DESTROY PROD to continue"
    if ($typed -ne "DESTROY PROD") {
        throw "Confirmation text mismatch. Aborting."
    }
}

foreach ($rg in $resourceGroups) {
    $exists = az group exists --name $rg
    if ($exists -ne "true") {
        Write-Warn "Skipping '$rg' (not found)."
        continue
    }

    Write-Info "Deleting resource group '$rg'..."
    az group delete --name $rg --yes --no-wait | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to start deletion for resource group '$rg'."
    }
}

Write-Host ""
Write-Info "Deletion requests submitted."
Write-Info "Track progress with:"
Write-Host "az group list --query ""[?contains(name, '$($outputs.namingPrefix.value)')].{Name:name,Location:location}"" -o table" -ForegroundColor Gray
