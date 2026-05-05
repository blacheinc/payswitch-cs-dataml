<#
AKS Deployment Script

This script deploys AKS and Container Registry.

Recommended usage (from repo root):
  .\credit-scoring\azure-infrastructure\scripts\deploy-aks.ps1 -Location eastus2 -NamingPrefix blache-creditscore-dev

If you already ran the environment setup block from ..\docs\DEPLOYMENT_GUIDE.md in the same PowerShell session,
you can omit most parameters and the script will reuse the existing variables.
#>

[CmdletBinding()]
param(
    [string]$Location,
    [string]$NamingPrefix,
    [string]$ResourceGroupNetworking,
    [string]$ResourceGroupCompute,
    [string]$AksSubnetId,
    [string]$AksNodeCount,
    [string]$AksVmSize,
    [switch]$EnableAutoScaling,
    [switch]$DisableAutoScaling,
    [string]$AksMinNodes,
    [string]$AksMaxNodes,
    [string]$AksK8sVersion,
    [string]$LogAnalyticsWorkspaceId,
    [array]$AksAvailabilityZones,
    [object]$Tags
)

function Get-SessionValue([string]$Name) {
    # Prefer session/global variables from the user's environment block
    $gv = Get-Variable -Name $Name -Scope Global -ErrorAction SilentlyContinue
    if ($gv) { return $gv.Value }

    # Then environment variables (OS-level), if user set them that way
    $ev = [Environment]::GetEnvironmentVariable($Name)
    if (-not [string]::IsNullOrWhiteSpace($ev)) { return $ev }

    return $null
}

# Use session/global variables (preferred) if parameters weren't provided
if ([string]::IsNullOrWhiteSpace($Location)) { $Location = Get-SessionValue 'LOCATION' }
if ([string]::IsNullOrWhiteSpace($NamingPrefix)) { $NamingPrefix = Get-SessionValue 'NAMING_PREFIX' }
if ([string]::IsNullOrWhiteSpace($ResourceGroupNetworking)) { $ResourceGroupNetworking = Get-SessionValue 'RG_NETWORKING' }
if ([string]::IsNullOrWhiteSpace($ResourceGroupCompute)) { $ResourceGroupCompute = Get-SessionValue 'RG_COMPUTE' }
if ([string]::IsNullOrWhiteSpace($AksSubnetId)) { $AksSubnetId = Get-SessionValue 'AKS_SUBNET_ID' }
if ([string]::IsNullOrWhiteSpace($AksNodeCount)) { $AksNodeCount = (Get-SessionValue 'AKS_NODE_COUNT'); if ([string]::IsNullOrWhiteSpace($AksNodeCount)) { $AksNodeCount = "3" } }
if ([string]::IsNullOrWhiteSpace($AksVmSize)) { $AksVmSize = (Get-SessionValue 'AKS_VM_SIZE'); if ([string]::IsNullOrWhiteSpace($AksVmSize)) { $AksVmSize = "Standard_D4s_v3" } }
if ([string]::IsNullOrWhiteSpace($AksMinNodes)) { $AksMinNodes = (Get-SessionValue 'AKS_MIN_NODES'); if ([string]::IsNullOrWhiteSpace($AksMinNodes)) { $AksMinNodes = "3" } }
if ([string]::IsNullOrWhiteSpace($AksMaxNodes)) { $AksMaxNodes = (Get-SessionValue 'AKS_MAX_NODES'); if ([string]::IsNullOrWhiteSpace($AksMaxNodes)) { $AksMaxNodes = "10" } }
if ([string]::IsNullOrWhiteSpace($AksK8sVersion)) { $AksK8sVersion = (Get-SessionValue 'AKS_K8S_VERSION') }
if ([string]::IsNullOrWhiteSpace($LogAnalyticsWorkspaceId)) { $LogAnalyticsWorkspaceId = (Get-SessionValue 'LOG_ANALYTICS_WORKSPACE_ID') }
if ($null -eq $AksAvailabilityZones) { 
    $envZones = Get-SessionValue 'AKS_AVAILABILITY_ZONES'
    if ($null -ne $envZones -and $envZones -is [array]) {
        $AksAvailabilityZones = $envZones
    } else {
        # Default to empty array (works for all regions, including those that don't support zones)
        $AksAvailabilityZones = @()
    }
}
if ($null -eq $Tags) { $Tags = Get-SessionValue 'TAGS' }

# Handle EnableAutoScaling - use switch parameters or script variable
if ($DisableAutoScaling) {
    $EnableAutoScalingValue = $false
} elseif ($EnableAutoScaling) {
    $EnableAutoScalingValue = $true
} else {
    $envAuto = Get-SessionValue 'ENABLE_AUTO_SCALING'
    if ($envAuto -is [bool]) {
        $EnableAutoScalingValue = $envAuto
    } elseif ($envAuto -is [string] -and $envAuto -ne "") {
        $tempBool = $false
        if ([bool]::TryParse($envAuto, [ref]$tempBool)) {
            $EnableAutoScalingValue = $tempBool
        } else {
            $EnableAutoScalingValue = $true  # Default
        }
    } else {
        $EnableAutoScalingValue = $true  # Default
    }
}

function Fail($Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Ensure-Value([string]$Name, $Value) {
    if ($null -eq $Value -or ($Value -is [string] -and [string]::IsNullOrWhiteSpace($Value))) {
        Fail "$Name is not set. Run the environment setup section in ..\docs\DEPLOYMENT_GUIDE.md OR pass -$Name explicitly."
    }
}

# If RGs weren't set but naming prefix is known, derive them (matches guide convention)
if ([string]::IsNullOrWhiteSpace($ResourceGroupNetworking) -and -not [string]::IsNullOrWhiteSpace($NamingPrefix)) {
    # Match ..\docs\DEPLOYMENT_GUIDE.md naming convention
    $ResourceGroupNetworking = "$NamingPrefix-network-rg"
}
if ([string]::IsNullOrWhiteSpace($ResourceGroupCompute) -and -not [string]::IsNullOrWhiteSpace($NamingPrefix)) {
    $ResourceGroupCompute = "$NamingPrefix-compute-rg"
}

Write-Host "Deploying AKS and Container Registry..." -ForegroundColor Green

Ensure-Value "Location" $Location
Ensure-Value "NamingPrefix" $NamingPrefix
Ensure-Value "ResourceGroupNetworking" $ResourceGroupNetworking
Ensure-Value "ResourceGroupCompute" $ResourceGroupCompute
Ensure-Value "LogAnalyticsWorkspaceId" $LogAnalyticsWorkspaceId

if ($null -eq $Tags) {
    # Not fatal; tags file helper may require it though
    Write-Host "WARNING: Tags not set. If New-TagsParametersFile fails, run the environment setup block first." -ForegroundColor Yellow
}

# Check if AKS cluster already exists with incompatible availability zones
$EXISTING_AKS = az aks list --resource-group $ResourceGroupCompute --query "[?contains(name, '$NamingPrefix')].{Name:name, Zones:agentPoolProfiles[0].availabilityZones}" -o json | ConvertFrom-Json
if ($EXISTING_AKS -and $EXISTING_AKS.Count -gt 0) {
    $AKS_NAME = $EXISTING_AKS[0].Name
    $EXISTING_ZONES = $EXISTING_AKS[0].Zones
    
    # Check if zones are set but we're trying to deploy without zones (or vice versa)
    $HAS_ZONES = $EXISTING_ZONES -and $EXISTING_ZONES.Count -gt 0
    $WANT_ZONES = $AksAvailabilityZones -and $AksAvailabilityZones.Count -gt 0
    
    if ($HAS_ZONES -and -not $WANT_ZONES) {
        Write-Host "`n⚠️  WARNING: Existing AKS cluster '$AKS_NAME' has availability zones configured: $($EXISTING_ZONES -join ', ')" -ForegroundColor Yellow
        Write-Host "   You are trying to deploy without zones (empty array)." -ForegroundColor Yellow
        Write-Host "   Azure does not allow changing availability zones on existing node pools." -ForegroundColor Yellow
        Write-Host "`n   To fix this, you must delete the existing cluster first:" -ForegroundColor Cyan
        Write-Host "   az aks delete --name $AKS_NAME --resource-group $ResourceGroupCompute --yes" -ForegroundColor White
        Write-Host "`n   Then run this deployment again." -ForegroundColor Cyan
        Write-Host "`n   Alternatively, if the cluster is working, you can skip this deployment." -ForegroundColor Gray
        exit 1
    } elseif (-not $HAS_ZONES -and $WANT_ZONES) {
        Write-Host "`n⚠️  WARNING: Existing AKS cluster '$AKS_NAME' does not have availability zones configured." -ForegroundColor Yellow
        Write-Host "   You are trying to deploy with zones: $($AksAvailabilityZones -join ', ')" -ForegroundColor Yellow
        Write-Host "   Azure does not allow changing availability zones on existing node pools." -ForegroundColor Yellow
        Write-Host "`n   To fix this, you must delete the existing cluster first:" -ForegroundColor Cyan
        Write-Host "   az aks delete --name $AKS_NAME --resource-group $ResourceGroupCompute --yes" -ForegroundColor White
        Write-Host "`n   Then run this deployment again." -ForegroundColor Cyan
        exit 1
    } else {
        Write-Host "Existing AKS cluster '$AKS_NAME' found. Zones configuration matches - proceeding with deployment..." -ForegroundColor Cyan
    }
}

# Verify required variables - try to capture if missing
if ([string]::IsNullOrWhiteSpace($AksSubnetId)) {
    Write-Host "WARNING: AKS_SUBNET_ID not set. Attempting to capture from Networking deployment..." -ForegroundColor Yellow
    
    # Try to find the most recent Networking deployment
    $networkingDeployments = az deployment group list --resource-group $ResourceGroupNetworking --query "[?contains(name, 'networking')].{Name:name, Time:properties.timestamp}" -o json | ConvertFrom-Json | Sort-Object Time -Descending
    
    if ($networkingDeployments -and $networkingDeployments.Count -gt 0) {
        $latestDeployment = $networkingDeployments[0].Name
        Write-Host "Found Networking deployment: $latestDeployment" -ForegroundColor Cyan
        
        $NETWORKING_OUTPUT = az deployment group show --resource-group $ResourceGroupNetworking --name $latestDeployment --query properties.outputs -o json | ConvertFrom-Json
        
        $AksSubnetId = $NETWORKING_OUTPUT.aksSubnetId.value
        $DATA_SUBNET_ID = $NETWORKING_OUTPUT.dataSubnetId.value
        $VNET_ID = $NETWORKING_OUTPUT.vnetId.value
        
        if ($AksSubnetId) {
            Write-Host "Successfully captured AKS_SUBNET_ID: $AksSubnetId" -ForegroundColor Green
        } else {
            Fail "Could not extract AKS_SUBNET_ID from deployment outputs. Run the 'Capture Outputs' section from Step 1.1 (Networking) manually."
        }
    } else {
        Fail "No Networking deployment found in resource group $ResourceGroupNetworking. Deploy Networking module (Step 1.1) first, then capture outputs."
    }
}

# Navigate to compute directory - check if already there first
$currentPath = (Get-Location).Path
if ($currentPath -like "*compute*" -and (Test-Path "aks.bicep")) {
    Write-Host "Already in compute directory." -ForegroundColor Cyan
} elseif (Test-Path "credit-scoring\azure-infrastructure\bicep-templates\compute\aks.bicep") {
    cd "credit-scoring\azure-infrastructure\bicep-templates\compute"
} elseif (Test-Path "..\..\..\credit-scoring\azure-infrastructure\bicep-templates\compute\aks.bicep") {
    cd "..\..\..\credit-scoring\azure-infrastructure\bicep-templates\compute"
} elseif (Test-Path "..\..\azure-infrastructure\bicep-templates\compute\aks.bicep") {
    cd "..\..\azure-infrastructure\bicep-templates\compute"
} elseif (Test-Path "..\compute\aks.bicep") {
    cd "..\compute"
} else {
    Write-Host "ERROR: Cannot find aks.bicep. Current location: $currentPath" -ForegroundColor Red
    Write-Host "Please navigate to the workspace root and try again." -ForegroundColor Yellow
    exit 1
}

$DEPLOYMENT_NAME = "aks-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Kubernetes version (patch) selection
if (-not [string]::IsNullOrWhiteSpace($AksK8sVersion)) {
    $LATEST_K8S_VERSION = $AksK8sVersion
    Write-Host "Using Kubernetes version from AKS_K8S_VERSION: $LATEST_K8S_VERSION" -ForegroundColor Green
} else {
    Write-Host "AKS_K8S_VERSION not set. Attempting to query a supported patch version for $Location..." -ForegroundColor Yellow

    $allVersionsData = az aks get-versions --location $Location -o json | ConvertFrom-Json
    $allMinors = $allVersionsData.values | Where-Object { $_.isPreview -ne $true } | ForEach-Object { $_.version }

    if (-not $allMinors -or $allMinors.Count -eq 0) {
        Fail "Could not query supported versions. Please set AKS_K8S_VERSION (patch) manually (e.g. 1.33.6)."
    }

    $sortedMinors = $allMinors | Sort-Object { [version]$_ } -Descending
    $latestMinor = $sortedMinors[0]

    $patchMap = ($allVersionsData.values | Where-Object { $_.version -eq $latestMinor } | Select-Object -First 1).patchVersions
    $patches = $patchMap.PSObject.Properties.Name | Sort-Object { [version]$_ } -Descending
    $LATEST_K8S_VERSION = $patches[0]

    Write-Host "Auto-selected Kubernetes patch version: $LATEST_K8S_VERSION" -ForegroundColor Green
    Write-Host "TIP: Set `$AKS_K8S_VERSION = `"$LATEST_K8S_VERSION`" in the variables block for repeatable runs." -ForegroundColor Cyan
}

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $Tags -FilePath $TAGS_FILE

# Format availability zones as JSON array for Azure CLI
if ($AksAvailabilityZones.Count -eq 0) {
    $ZONES_PARAM = "[]"
    Write-Host "Using empty availability zones array (region may not support zones)" -ForegroundColor Yellow
} else {
    $zonesQuoted = $AksAvailabilityZones | ForEach-Object { "`"$_`"" }
    $ZONES_PARAM = "[$($zonesQuoted -join ',')]"
    Write-Host "Using availability zones: $($AksAvailabilityZones -join ', ')" -ForegroundColor Cyan
}

# Deploy using inline parameters for simple values, file for tags
az deployment group create --resource-group $ResourceGroupCompute --template-file aks.bicep --parameters location=$Location --parameters namingPrefix=$NamingPrefix --parameters nodeCount=$AksNodeCount --parameters vmSize=$AksVmSize --parameters enableAutoScaling=$EnableAutoScalingValue --parameters minNodeCount=$AksMinNodes --parameters maxNodeCount=$AksMaxNodes --parameters vnetSubnetId=$AksSubnetId --parameters kubernetesVersion=$LATEST_K8S_VERSION --parameters logAnalyticsWorkspaceId=$LogAnalyticsWorkspaceId --parameters availabilityZones="$ZONES_PARAM" --parameters "@$TAGS_FILE" --name $DEPLOYMENT_NAME --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "AKS deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
    exit 1
} else {
    Write-Host "AKS and Container Registry deployed successfully!" -ForegroundColor Green
    
    # Capture outputs and set cluster name for subsequent commands
    Write-Host "`nCapturing deployment outputs..." -ForegroundColor Cyan
    $AKS_OUTPUT = az deployment group show --resource-group $ResourceGroupCompute --name $DEPLOYMENT_NAME --query properties.outputs -o json | ConvertFrom-Json
    
    if ($AKS_OUTPUT -and $AKS_OUTPUT.aksClusterName) {
        $AKS_CLUSTER_NAME = $AKS_OUTPUT.aksClusterName.value
        $ACR_NAME = $AKS_OUTPUT.containerRegistryName.value
        
        # Set as global/session variable for use in subsequent commands
        Set-Variable -Name "AKS_CLUSTER_NAME" -Value $AKS_CLUSTER_NAME -Scope Global -ErrorAction SilentlyContinue
        Set-Variable -Name "ACR_NAME" -Value $ACR_NAME -Scope Global -ErrorAction SilentlyContinue
        
        Write-Host "Cluster Name: $AKS_CLUSTER_NAME" -ForegroundColor Green
        Write-Host "Container Registry: $ACR_NAME" -ForegroundColor Green
        Write-Host "`nThese variables are now available in your session for subsequent commands." -ForegroundColor Cyan
    } else {
        # Fallback: derive from naming prefix
        $AKS_CLUSTER_NAME = "$NamingPrefix-aks"
        Set-Variable -Name "AKS_CLUSTER_NAME" -Value $AKS_CLUSTER_NAME -Scope Global -ErrorAction SilentlyContinue
        Write-Host "WARNING: Could not extract cluster name from outputs. Using derived name: $AKS_CLUSTER_NAME" -ForegroundColor Yellow
    }
}
