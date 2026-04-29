# ==================================================
# Azure Infrastructure Cleanup Script (PowerShell)
# Credit Scoring + Agentic AI Platform
# ==================================================

param(
    [string]$Environment = "dev",
    [string]$OrgName = "blache",
    [string]$ProjectName = "creditscore",
    [switch]$Force
)

# ==================================================
# Configuration
# ==================================================

$NamingPrefix = "$OrgName-$ProjectName-$Environment"

# ==================================================
# Functions
# ==================================================

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Get-ResourceGroups {
    Write-Info "Finding resource groups for environment: $Environment"
    Write-Info "Searching for resource groups matching: $NamingPrefix"
    
    $query = '[?contains(name, ''' + $NamingPrefix + ''')].{Name:name, Location:location}'
    $resourceGroups = az group list --query $query -o json | ConvertFrom-Json
    
    return $resourceGroups
}

function Remove-ResourceGroups {
    param([array]$ResourceGroups)
    
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
        Write-Warn "This will DELETE all resources in these resource groups!"
        $confirmation = Read-Host "Are you absolutely sure? Type 'DELETE' to confirm"
        
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
            Write-Info "  ✓ Deletion initiated for: $($rg.Name)"
        } else {
            Write-Error "  ✗ Failed to initiate deletion for: $($rg.Name)"
        }
    }
    
    Write-Host ""
    Write-Info "Deletion initiated for all resource groups (running in background)"
    Write-Info "Use 'az group list' to monitor progress"
    Write-Info "Use 'az group show --name <rg-name>' to check status of specific resource group"
}

function Get-PrivateDnsZones {
    Write-Info "Finding Private DNS Zones that may have been created..."
    
    $query = '[?contains(name, ''privatelink'')].{Name:name, ResourceGroup:resourceGroup}'
    $dnsZones = az network private-dns zone list --query $query -o json | ConvertFrom-Json
    
    return $dnsZones
}

function Remove-PrivateDnsZones {
    param([array]$DnsZones)
    
    if ($DnsZones.Count -eq 0) {
        Write-Info "No Private DNS Zones found to clean up"
        return
    }
    
    Write-Host ""
    Write-Info "Private DNS Zones found (may be in resource groups):"
    foreach ($zone in $DnsZones) {
        Write-Host "  - $($zone.Name) (RG: $($zone.ResourceGroup))" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Info "These will be deleted when their resource groups are deleted"
}

# ==================================================
# Main Execution
# ==================================================

function Main {
    Write-Host ""
    Write-Info "========================================"
    Write-Info "Azure Infrastructure Cleanup"
    Write-Info "Credit Scoring + Agentic AI Platform"
    Write-Info "========================================"
    Write-Host ""
    
    # Check Azure CLI
    if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
        Write-Error "Azure CLI is not installed. Please install it first."
        exit 1
    }
    
    # Check if logged in
    try {
        $account = az account show 2>&1 | ConvertFrom-Json
        if (-not $account) {
            throw
        }
        Write-Info "Current subscription: $($account.name) ($($account.id))"
    } catch {
        Write-Error "Not logged in to Azure. Please run 'az login' first."
        exit 1
    }
    
    Write-Host ""
    
    # Get resource groups
    $resourceGroups = Get-ResourceGroups
    
    # Get Private DNS Zones (for information)
    $dnsZones = Get-PrivateDnsZones
    
    # Delete resource groups
    Remove-ResourceGroups -ResourceGroups $resourceGroups
    
    # Show Private DNS Zones info
    if ($dnsZones.Count -gt 0) {
        Remove-PrivateDnsZones -DnsZones $dnsZones
    }
    
    Write-Host ""
    Write-Info "========================================"
    Write-Info "Cleanup initiated successfully!"
    Write-Info "========================================"
    Write-Host ""
    Write-Info "To monitor deletion progress:"
    Write-Host "  az group list --query `"[?contains(name, '$NamingPrefix')].{Name:name, State:properties.provisioningState}`" -o table" -ForegroundColor Cyan
    Write-Host ""
}

# Run main function
Main
