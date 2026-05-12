# ==================================================
# Azure Infrastructure Cleanup Script (PowerShell)
# ==================================================

param(
    [Parameter(Mandatory = $false)]
    [ValidateSet("dev", "staging", "prod")]
    [string]$Environment,
    [string]$OrgName,
    [string]$ProjectName,
    [switch]$Force
)

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Resolve-DestroyInputs {
    $envVal = $Environment
    if ([string]::IsNullOrWhiteSpace($envVal)) { $envVal = $env:ENVIRONMENT }
    if ([string]::IsNullOrWhiteSpace($envVal)) {
        $envVal = Read-Host "Environment (dev, staging, prod) - same as ENVIRONMENT in deployment guide"
    }
    if ($envVal -notin @("dev", "staging", "prod")) {
        throw "Environment must be dev, staging, or prod (got: '$envVal')."
    }

    $orgVal = $OrgName
    if ([string]::IsNullOrWhiteSpace($orgVal)) { $orgVal = $env:ORG_NAME }
    while ([string]::IsNullOrWhiteSpace($orgVal)) {
        $orgVal = Read-Host "Org name (required) - same as orgName / ORG_NAME"
    }

    $projVal = $ProjectName
    if ([string]::IsNullOrWhiteSpace($projVal)) { $projVal = $env:PROJECT_NAME }
    while ([string]::IsNullOrWhiteSpace($projVal)) {
        $projVal = Read-Host "Project name (required) - same as projectName / PROJECT_NAME"
    }

    return @{
        Environment  = $envVal
        OrgName      = $orgVal
        ProjectName  = $projVal
        NamingPrefix = "$orgVal-$projVal-$envVal"
    }
}

function Get-ResourceGroups {
    param([string]$NamingPrefix, [string]$Environment)
    Write-Info "Finding resource groups for environment: $Environment"
    Write-Info "Searching for resource groups matching: $NamingPrefix"

    $json = az group list -o json
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        return @()
    }

    $allGroups = $json | ConvertFrom-Json
    if ($allGroups -isnot [System.Array]) {
        $allGroups = @($allGroups)
    }
    $resourceGroups = @()
    foreach ($group in $allGroups) {
        if ($group.name -like "*$NamingPrefix*") {
            $resourceGroups += [PSCustomObject]@{
                Name = $group.name
                Location = $group.location
            }
        }
    }
    return @($resourceGroups)
}

function Remove-ResourceGroups {
    param([array]$ResourceGroups, [string]$NamingPrefix, [switch]$Force)

    if ($ResourceGroups.Count -eq 0) {
        Write-Warn "No resource groups found matching: $NamingPrefix"
        return
    }

    Write-Host ""
    Write-Info "Resource groups to be deleted:"
    foreach ($rg in $ResourceGroups) {
        Write-Host "  - $($rg.Name) ($($rg.Location))" -ForegroundColor Yellow
    }
    Write-Host ""

    if (-not $Force) {
        Write-Warn "This will delete all resources in these resource groups."
        $confirmation = Read-Host "Type DELETE to confirm"
        if ($confirmation -ne "DELETE") {
            Write-Warn "Deletion cancelled by user"
            return
        }
    }

    Write-Host ""
    foreach ($rg in $ResourceGroups) {
        Write-Info "Deleting resource group: $($rg.Name)"
        az group delete --name $rg.Name --yes --no-wait
        if ($LASTEXITCODE -eq 0) {
            Write-Info "Deletion initiated for: $($rg.Name)"
        } else {
            Write-Err "Failed to initiate deletion for: $($rg.Name)"
        }
    }

    Write-Host ""
    Write-Info "Deletion initiated for all resource groups (async)."
    Write-Info "Use az group list to monitor progress."
}

function Get-PrivateDnsZones {
    param([string[]]$ResourceGroupNames)
    Write-Info "Finding Private DNS zones in matched resource groups..."
    $query = "[?contains(name, 'privatelink')].{Name:name, ResourceGroup:resourceGroup}"
    $json = az network private-dns zone list --query $query -o json
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($json)) {
        return @()
    }
    $zones = $json | ConvertFrom-Json
    if ($zones -isnot [System.Array]) {
        $zones = @($zones)
    }
    if ($null -eq $ResourceGroupNames -or $ResourceGroupNames.Count -eq 0) {
        return @()
    }
    return @($zones | Where-Object { $ResourceGroupNames -contains $_.ResourceGroup })
}

function Remove-PrivateDnsZones {
    param([array]$DnsZones)
    if ($DnsZones.Count -eq 0) {
        Write-Info "No Private DNS zones found to clean up"
        return
    }

    Write-Host ""
    Write-Info "Private DNS zones found (deleted when RGs are deleted):"
    foreach ($zone in $DnsZones) {
        Write-Host "  - $($zone.Name) (RG: $($zone.ResourceGroup))" -ForegroundColor Yellow
    }
}

function Main {
    Write-Host ""
    Write-Info "========================================"
    Write-Info "Azure Infrastructure Cleanup"
    Write-Info "========================================"
    Write-Host ""

    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Err "Azure CLI is not installed. Install it first."
        exit 1
    }

    try {
        $account = az account show 2>&1 | ConvertFrom-Json
        if (-not $account) { throw }
        Write-Info "Current subscription: $($account.name) ($($account.id))"
    } catch {
        Write-Err "Not logged in to Azure. Run az login first."
        exit 1
    }

    $ctx = Resolve-DestroyInputs
    Write-Host ""
    Write-Info "Using naming prefix: $($ctx.NamingPrefix)"
    Write-Host ""

    $resourceGroups = Get-ResourceGroups -NamingPrefix $ctx.NamingPrefix -Environment $ctx.Environment
    $matchedRgNames = @($resourceGroups | ForEach-Object { $_.Name })
    $dnsZones = Get-PrivateDnsZones -ResourceGroupNames $matchedRgNames

    Remove-ResourceGroups -ResourceGroups $resourceGroups -NamingPrefix $ctx.NamingPrefix -Force:$Force
    Remove-PrivateDnsZones -DnsZones $dnsZones

    Write-Host ""
    Write-Info "Cleanup initiated."
    Write-Host "az group list --query ""[?contains(name, '$($ctx.NamingPrefix)')].{Name:name, State:properties.provisioningState}"" -o table" -ForegroundColor Cyan
}

Main
