# Azure Infrastructure Deployment Guide - Individual Modules

**Deployment Method:** Individual Bicep modules in dependency order  
**Resource Prefix:** `blache-dev`  
**Last Updated:** January 2026

---

## Private Network Path

For private networking + Premium Functions deployment path, use:

- `credit-scoring/azure-infrastructure/PHASE2_PRIVATE_DEPLOYMENT_GUIDE.md`
- `credit-scoring/azure-infrastructure/scripts/deploy-phase2-private.ps1`
- `credit-scoring/azure-infrastructure/scripts/whatif-phase2-private.ps1`

---

## 📋 Table of Contents

1. [Prerequisites](#prerequisites)
2. [Variables Configuration](#variables-configuration)
3. [Deployment Phases](#deployment-phases)
4. [Post-Deployment Tasks](#post-deployment-tasks)
5. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

```powershell
# Verify Azure CLI installed
az --version  # Should be 2.50+

# Verify Bicep installed
az bicep version  # Should be 0.40.2+

# Install/upgrade Bicep if needed
az bicep install
az bicep upgrade
```

### Azure Authentication

```powershell
# Login to Azure
az login

# Set subscription (if you have multiple)
az account set --subscription "YOUR_SUBSCRIPTION_ID"

# Verify current subscription
az account show

# Verify permissions (need Contributor role minimum)
az role assignment list --assignee $(az account show --query user.name -o tsv) --scope /subscriptions/$(az account show --query id -o tsv)
```

---

## Variables Configuration

**⚠️ IMPORTANT: These variables are TEMPORARY and only exist in your current PowerShell session.**
- ✅ They will **NOT** be saved permanently on your laptop
- ✅ They will **disappear** when you close the PowerShell window
- ✅ You can run these commands directly in PowerShell terminal

### Option 1: Run Variables Directly in PowerShell (Recommended)

**Simply copy and paste the variable block below into your PowerShell terminal:**

```powershell
# ==================================================
# REQUIRED VARIABLES - UPDATE THESE VALUES
# Copy and paste this entire block into PowerShell
# ==================================================

# Environment Configuration
$ENVIRONMENT = "dev"
$LOCATION = "eastus2"  # Change to your preferred Azure region
$ORG_NAME = "blache"
$PROJECT_NAME = "creditscore"
$NAMING_PREFIX = "$ORG_NAME-$PROJECT_NAME-$ENVIRONMENT"  # Result: "blache-creditscore-dev"
#$NAMING_PREFIX = "$ORG_NAME-$ENVIRONMENT"  # Result: "blache-dev"

# Administrator Configuration
$ADMIN_EMAIL = "ops@blache.com"  # CHANGE THIS - Used for alerts and notifications

# Network Configuration
$VNET_ADDRESS_PREFIX = "10.0.0.0/16"
$ENABLE_DDOS_PROTECTION = $false  # Set to $true for production

# Security Configuration
$ENABLE_PURGE_PROTECTION = $false  # Set to $true for production
$ENABLE_ADVANCED_SECURITY = $true

# Data Services Configuration
$POSTGRES_SKU = "Standard_B1ms"  # Burstable tier for dev (Standard_B1ms, Standard_B1s, Standard_B2ms, etc.)
$REDIS_SKU = "Basic"  # Basic, Standard, or Premium
$BACKUP_RETENTION_DAYS = 7  # 7 for dev, 14 for staging, 30 for prod
$ENABLE_HA = $false  # High Availability (set to $true for production)

# Compute Configuration
$AKS_NODE_COUNT = 2
$AKS_VM_SIZE = "Standard_D2s_v3"  # D2s_v3 for dev, D4s_v3 for staging, D8s_v3 for prod
$ENABLE_AUTO_SCALING = $true
$AKS_MIN_NODES = 2
$AKS_MAX_NODES = 4
$AKS_K8S_VERSION = "1.33.6"  # AKS patch version (MUST be a patch, e.g. 1.33.6). Get options: az aks get-versions --location $LOCATION
# RECOMMENDED: Query for the most stable version in your region and update this value accordingly
$AKS_AVAILABILITY_ZONES = @()  # Empty array for regions without zone support (e.g., eastus2). For regions with zones, use: @('1', '2', '3')

# Cosmos DB Configuration
$COSMOS_THROUGHPUT = 400  # RU/s (400 for dev, 1000 for prod)
$COSMOS_CONSISTENCY_LEVEL = "Session"  # Session, BoundedStaleness, Strong, etc.

# Service Bus Configuration
$SERVICE_BUS_SKU = "Standard"  # Standard or Premium (Standard supports topics)

# Tags (applied to all resources)
$TAGS = @{
    Project = "Credit-Scoring-Agentic-AI"
    Environment = $ENVIRONMENT
    ManagedBy = "Bicep"
    Owner = "Blache-Ltd"
    CostCenter = "FinTech-Operations"
    DeployedBy = "Data-Engineering-Team"
}

# Note: Tags will be passed as object in parameters file (not JSON string)

# ==================================================
# HELPER FUNCTION (For Tags Parameter)
# ==================================================

# Helper function to create a temporary tags parameters file
# Azure CLI requires complex objects like tags to be passed via parameters file
function New-TagsParametersFile {
    param(
        [hashtable]$Tags,
        [string]$FilePath
    )
    $tagsParams = @{
        '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
        contentVersion = '1.0.0.0'
        parameters = @{
            tags = @{
                value = $Tags
            }
        }
    }
    $tagsParams | ConvertTo-Json -Depth 10 | Out-File -FilePath $FilePath -Encoding utf8
}

# ==================================================
# DERIVED VARIABLES (Don't modify these)
# ==================================================

# Resource Group Names
$RG_CORE = "$NAMING_PREFIX-core-rg"
$RG_NETWORKING = "$NAMING_PREFIX-network-rg"
$RG_DATA = "$NAMING_PREFIX-data-rg"
$RG_COMPUTE = "$NAMING_PREFIX-compute-rg"
$RG_ML = "$NAMING_PREFIX-ml-rg"
$RG_SECURITY = "$NAMING_PREFIX-security-rg"
$RG_MONITORING = "$NAMING_PREFIX-monitoring-rg"
$RG_AGENTS = "$NAMING_PREFIX-agents-rg"

# Base paths
# Note: These are relative paths from credit-scoring directory
# When navigating, use: cd ..\..\..\$PHASE2_BASE\service-bus (from bicep-templates/data)
$BICEP_BASE = "credit-scoring\azure-infrastructure\bicep-templates"
$PHASE2_BASE = "phase2-data-ingestion"
$PHASE5_BASE = "phase5-api-gateway"
```

**Verify variables are set:**
```powershell
# Check that key variables are set
Write-Host "Environment: $ENVIRONMENT"
Write-Host "Location: $LOCATION"
Write-Host "Naming Prefix: $NAMING_PREFIX"
Write-Host "Admin Email: $ADMIN_EMAIL"
```

### Option 2: Create a Variables Script File (Optional)

**If you prefer to save variables in a file (still temporary when sourced):**

1. Create a file `set-variables.ps1` in the project root:
```powershell
# Save the variable block above to: set-variables.ps1
```

2. Source it in your PowerShell session:
```powershell
# Navigate to project root
cd C:\Users\olanr\Desktop\blache

# Source the variables (they're still only in this session)
. .\set-variables.ps1

# Verify
Write-Host "Naming Prefix: $NAMING_PREFIX"
```

**Note:** Even when sourced from a file, variables are still **session-only** and won't persist after closing PowerShell.

---

## Deployment Phases

### Phase 1: Foundation (No Dependencies)

Deploy these modules first - they have no dependencies on other modules.

---

#### Step 1.1: Create Resource Groups

**Purpose:** Create all resource groups upfront (no cost)

```powershell
Write-Host "Creating Resource Groups..." -ForegroundColor Green

az group create --name $RG_CORE --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_NETWORKING --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_DATA --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_COMPUTE --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_ML --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_SECURITY --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_MONITORING --location $LOCATION --tags $TAGS_JSON
az group create --name $RG_AGENTS --location $LOCATION --tags $TAGS_JSON

Write-Host "Resource Groups created successfully!" -ForegroundColor Green
```

**Validation:**
```powershell
az group list --query "[?contains(name, '$NAMING_PREFIX')].{Name:name, Location:location}" -o table
```

**Expected Output:** 8 resource groups listed

---

#### Step 1.2: Deploy Networking Module

**Purpose:** Virtual Network, Subnets, Network Security Groups  
**Bicep File:** `networking/vnet.bicep`  
**Dependencies:** None

```powershell
Write-Host "Deploying Networking Module..." -ForegroundColor Green

# Navigate to networking directory - check if already there first
$currentPath = (Get-Location).Path
if ($currentPath -like "*networking*" -and (Test-Path "vnet.bicep")) {
    Write-Host "Already in networking directory." -ForegroundColor Cyan
} elseif (Test-Path "credit-scoring\azure-infrastructure\bicep-templates\networking\vnet.bicep") {
    cd "credit-scoring\azure-infrastructure\bicep-templates\networking"
} elseif (Test-Path "..\..\..\credit-scoring\azure-infrastructure\bicep-templates\networking\vnet.bicep") {
    cd "..\..\..\credit-scoring\azure-infrastructure\bicep-templates\networking"
} elseif (Test-Path "..\..\azure-infrastructure\bicep-templates\networking\vnet.bicep") {
    cd "..\..\azure-infrastructure\bicep-templates\networking"
} elseif (Test-Path "..\networking\vnet.bicep") {
    cd "..\networking"
} else {
    Write-Host "ERROR: Cannot find vnet.bicep. Current location: $currentPath" -ForegroundColor Red
    Write-Host "Please navigate to the workspace root and try again." -ForegroundColor Yellow
}

# Create deployment name
$DEPLOYMENT_NAME = "networking-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create a minimal parameters file for tags (complex objects need proper JSON structure)
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
$tagsParams = @{
    '$schema' = 'https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#'
    contentVersion = '1.0.0.0'
    parameters = @{
        tags = @{
            value = $TAGS
        }
    }
}
$tagsParams | ConvertTo-Json -Depth 10 | Out-File -FilePath $TAGS_FILE -Encoding utf8

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_NETWORKING `
  --template-file vnet.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters vnetAddressPrefix=$VNET_ADDRESS_PREFIX `
  --parameters enableDdosProtection=$ENABLE_DDOS_PROTECTION `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Networking deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Networking module deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**

```powershell
# Capture outputs from Networking deployment (required by later modules)
$NETWORKING_OUTPUT = az deployment group show `
  --resource-group $RG_NETWORKING `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

# Subnet + VNet IDs used by Data Services, AKS, etc.
$AKS_SUBNET_ID = $NETWORKING_OUTPUT.aksSubnetId.value
$DATA_SUBNET_ID = $NETWORKING_OUTPUT.dataSubnetId.value
$VNET_ID = $NETWORKING_OUTPUT.vnetId.value
$ML_SUBNET_ID = $NETWORKING_OUTPUT.mlSubnetId.value
$APIM_SUBNET_ID = $NETWORKING_OUTPUT.apimSubnetId.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  AKS Subnet ID: $AKS_SUBNET_ID"
Write-Host "  Data Subnet ID: $DATA_SUBNET_ID"
Write-Host "  VNet ID: $VNET_ID"
Write-Host "  ML Subnet ID: $ML_SUBNET_ID"
Write-Host "  APIM Subnet ID: $APIM_SUBNET_ID"

# Optional: persist in current session for later steps
Set-Variable -Name "AKS_SUBNET_ID" -Value $AKS_SUBNET_ID -Scope Global -ErrorAction SilentlyContinue
Set-Variable -Name "DATA_SUBNET_ID" -Value $DATA_SUBNET_ID -Scope Global -ErrorAction SilentlyContinue
Set-Variable -Name "VNET_ID" -Value $VNET_ID -Scope Global -ErrorAction SilentlyContinue
Set-Variable -Name "ML_SUBNET_ID" -Value $ML_SUBNET_ID -Scope Global -ErrorAction SilentlyContinue
Set-Variable -Name "APIM_SUBNET_ID" -Value $APIM_SUBNET_ID -Scope Global -ErrorAction SilentlyContinue
```

**Validation:**
```powershell
# Verify VNet created
az network vnet list --resource-group $RG_NETWORKING --query "[].{Name:name, AddressSpace:addressSpace.addressPrefixes}" -o table

# Verify subnets created
$VNET_NAME = az network vnet list --resource-group $RG_NETWORKING --query "[0].name" -o tsv
az network vnet subnet list --resource-group $RG_NETWORKING --vnet-name $VNET_NAME --query "[].{Name:name, AddressPrefix:addressPrefix}" -o table
```

**Expected Output:** 1 VNet with 7 subnets

---

#### Step 1.3: Deploy Monitoring Module (Recommended Before Security)

**Purpose:** Log Analytics, Application Insights  
**Bicep File:** `monitoring/monitoring.bicep`  
**Dependencies:** None  
**Note:** Deploy this before Security to enable Key Vault diagnostics

```powershell
Write-Host "Deploying Monitoring Module..." -ForegroundColor Green

cd ..\monitoring

$DEPLOYMENT_NAME = "monitoring-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_MONITORING `
  --template-file monitoring.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters adminEmail=$ADMIN_EMAIL `
  --parameters enableMetricAlerts=false `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Monitoring deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Monitoring module deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$MONITORING_OUTPUT = az deployment group show `
  --resource-group $RG_MONITORING `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$APP_INSIGHTS_ID = $MONITORING_OUTPUT.applicationInsightsId.value
$LOG_ANALYTICS_WORKSPACE_ID = $MONITORING_OUTPUT.logAnalyticsId.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  Application Insights ID: $APP_INSIGHTS_ID"
Write-Host "  Log Analytics Workspace ID: $LOG_ANALYTICS_WORKSPACE_ID"
```

**Validation:**
```powershell
# Verify Log Analytics Workspace
az monitor log-analytics workspace list --resource-group $RG_MONITORING --query "[].{Name:name, Location:location}" -o table

# Verify Application Insights (using resource ID)
az monitor app-insights component show --ids $APP_INSIGHTS_ID --query "{Name:name, State:provisioningState}" -o json
```

**Expected Output:** Log Analytics Workspace and Application Insights in "Succeeded" state

---

#### Step 1.4: Deploy Security Module (Key Vault)

**Purpose:** Key Vault, Managed Identities  
**Bicep File:** `security/keyvault.bicep`  
**Dependencies:** None

**Note:** Diagnostic settings for Key Vault are now handled by the centralized diagnostic settings module (Step 2.4).

```powershell
Write-Host "Deploying Security Module (Key Vault)..." -ForegroundColor Green

cd ..\security

$DEPLOYMENT_NAME = "security-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Verify required variables are set
if (-not $LOG_ANALYTICS_WORKSPACE_ID) {
    Write-Host "ERROR: Missing required dependency!" -ForegroundColor Red
    Write-Host "  LOG_ANALYTICS_WORKSPACE_ID: $LOG_ANALYTICS_WORKSPACE_ID" -ForegroundColor Yellow
    Write-Host "Please deploy Monitoring module (Step 1.3) first to get Log Analytics Workspace ID." -ForegroundColor Yellow
    Write-Host "Continuing anyway - deployment will likely fail..." -ForegroundColor Yellow
}

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
# Note: Diagnostic settings are now handled by centralized module (Step 2.4)
az deployment group create `
  --resource-group $RG_SECURITY `
  --template-file keyvault.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters enablePurgeProtection=$ENABLE_PURGE_PROTECTION `
  --parameters enableAdvancedSecurity=$ENABLE_ADVANCED_SECURITY `
  --parameters adminEmail=$ADMIN_EMAIL `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Security deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Security module deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$SECURITY_OUTPUT = az deployment group show `
  --resource-group $RG_SECURITY `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$KEY_VAULT_NAME = $SECURITY_OUTPUT.keyVaultName.value
$KEY_VAULT_ID = $SECURITY_OUTPUT.keyVaultId.value
$MANAGED_IDENTITY_ID = $SECURITY_OUTPUT.managedIdentityPrincipalId.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  Key Vault Name: $KEY_VAULT_NAME"
Write-Host "  Key Vault ID: $KEY_VAULT_ID"
Write-Host "  Managed Identity ID: $MANAGED_IDENTITY_ID"
```

**Validation:**
```powershell
# Verify Key Vault created
az keyvault list --resource-group $RG_SECURITY --query "[].{Name:name, Location:location, State:properties.provisioningState}" -o table

# Verify Key Vault accessible
az keyvault show --name $KEY_VAULT_NAME --query "{Name:name, VaultUri:properties.vaultUri, State:properties.provisioningState}" -o json
```

**Expected Output:** Key Vault in "Succeeded" state

---

#### Step 1.4: Deploy Monitoring Module

**Purpose:** Log Analytics, Application Insights  
**Bicep File:** `monitoring/monitoring.bicep`  
**Dependencies:** None

```powershell
Write-Host "Deploying Monitoring Module..." -ForegroundColor Green

cd ..\monitoring

$DEPLOYMENT_NAME = "monitoring-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_MONITORING `
  --template-file monitoring.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters adminEmail=$ADMIN_EMAIL `
  --parameters enableMetricAlerts=false `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Monitoring deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Monitoring module deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$MONITORING_OUTPUT = az deployment group show `
  --resource-group $RG_MONITORING `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$APP_INSIGHTS_ID = $MONITORING_OUTPUT.applicationInsightsId.value
$LOG_ANALYTICS_WORKSPACE_ID = $MONITORING_OUTPUT.logAnalyticsId.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  Application Insights ID: $APP_INSIGHTS_ID"
Write-Host "  Log Analytics Workspace ID: $LOG_ANALYTICS_WORKSPACE_ID"
```

**Validation:**
```powershell
# Verify Log Analytics Workspace
az monitor log-analytics workspace list --resource-group $RG_MONITORING --query "[].{Name:name, Location:location}" -o table

# Verify Application Insights
az monitor app-insights component show --app "$NAMING_PREFIX-appinsights" --resource-group $RG_MONITORING --query "{Name:name, AppId:appId, State:provisioningState}" -o json
```

**Expected Output:** Both resources in "Succeeded" state

---

### Phase 2: Data Layer (Depends on Phase 1)

Deploy data services that depend on networking and security.

---

#### Step 2.1: Deploy Data Services Module

**Purpose:** PostgreSQL, Redis, Storage Account (Blob Storage), Data Lake Gen2  
**Bicep File:** `data/data-services.bicep`  
**Dependencies:** Networking (subnet), Security (Key Vault name)

**⚠️ IMPORTANT:** This module requires outputs from Networking and Security modules.

**Storage Accounts Created:**
- **Blob Storage Account:** Standard StorageV2 account WITHOUT hierarchical namespace (for models, artifacts, data containers)
- **Data Lake Gen2 Account:** StorageV2 account WITH hierarchical namespace enabled (for bronze/silver/gold data layers)
- **Note:** Hierarchical namespace (HNS) must be enabled at creation time - cannot be changed later

```powershell
Write-Host "Deploying Data Services Module..." -ForegroundColor Green

# Verify required variables are set
# If networking outputs weren't captured yet, attempt to capture them now (best-effort)
if (-not $DATA_SUBNET_ID -or -not $VNET_ID) {
    Write-Host "WARNING: DATA_SUBNET_ID and/or VNET_ID not set. Attempting to capture from latest Networking deployment..." -ForegroundColor Yellow
    $networkingDeployments = az deployment group list --resource-group $RG_NETWORKING --query "[?contains(name, 'networking')].{Name:name, Time:properties.timestamp}" -o json | ConvertFrom-Json | Sort-Object Time -Descending
    if ($networkingDeployments -and $networkingDeployments.Count -gt 0) {
        $latestNetworkingDeployment = $networkingDeployments[0].Name
        Write-Host "Found Networking deployment: $latestNetworkingDeployment" -ForegroundColor Cyan
        $NETWORKING_OUTPUT = az deployment group show --resource-group $RG_NETWORKING --name $latestNetworkingDeployment --query properties.outputs -o json | ConvertFrom-Json
        if (-not $DATA_SUBNET_ID) { $DATA_SUBNET_ID = $NETWORKING_OUTPUT.dataSubnetId.value }
        if (-not $VNET_ID) { $VNET_ID = $NETWORKING_OUTPUT.vnetId.value }
    }
}

if (-not $DATA_SUBNET_ID -or -not $KEY_VAULT_NAME -or -not $VNET_ID) {
    Write-Host "ERROR: Missing required dependencies!" -ForegroundColor Red
    Write-Host "  DATA_SUBNET_ID: $DATA_SUBNET_ID"
    Write-Host "  KEY_VAULT_NAME: $KEY_VAULT_NAME"
    Write-Host "  VNET_ID: $VNET_ID"
    Write-Host "Please deploy Networking and Security modules first." -ForegroundColor Yellow
    Write-Host "Continuing anyway - deployment will likely fail..." -ForegroundColor Yellow
}

cd ..\data

$DEPLOYMENT_NAME = "data-services-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_DATA `
  --template-file data-services.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters postgresSkuName=$POSTGRES_SKU `
  --parameters redisCacheSku=$REDIS_SKU `
  --parameters backupRetentionDays=$BACKUP_RETENTION_DAYS `
  --parameters enableHA=$ENABLE_HA `
  --parameters keyVaultName=$KEY_VAULT_NAME `
  --parameters subnetId=$DATA_SUBNET_ID `
  --parameters vnetId=$VNET_ID `
  --parameters mlSubnetId=$ML_SUBNET_ID `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Data Services deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Data Services module deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$DATA_OUTPUT = az deployment group show `
  --resource-group $RG_DATA `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$STORAGE_ACCOUNT_ID = $DATA_OUTPUT.storageAccountId.value
$STORAGE_ACCOUNT_NAME = $DATA_OUTPUT.storageAccountName.value
$DATA_LAKE_ID = $DATA_OUTPUT.dataLakeId.value
$DATA_LAKE_NAME = $DATA_OUTPUT.dataLakeName.value
$POSTGRES_SERVER_ID = $DATA_OUTPUT.postgresServerId.value
$POSTGRES_SERVER_NAME = $DATA_OUTPUT.postgresServerName.value
$REDIS_ID = $DATA_OUTPUT.redisId.value
$REDIS_NAME = $DATA_OUTPUT.redisName.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  Storage Account ID: $STORAGE_ACCOUNT_ID"
Write-Host "  Storage Account Name: $STORAGE_ACCOUNT_NAME"
Write-Host "  Data Lake ID: $DATA_LAKE_ID"
Write-Host "  Data Lake Name: $DATA_LAKE_NAME"
Write-Host "  PostgreSQL Server ID: $POSTGRES_SERVER_ID"
Write-Host "  PostgreSQL Server: $POSTGRES_SERVER_NAME"
Write-Host "  Redis ID: $REDIS_ID"
Write-Host "  Redis Name: $REDIS_NAME"
```

**Validation:**
```powershell
# Verify PostgreSQL
az postgres flexible-server list --resource-group $RG_DATA --query "[].{Name:name, State:state, Location:location}" -o table

# Verify Redis
az redis list --resource-group $RG_DATA --query "[].{Name:name, State:provisioningState, Location:location}" -o table

# Verify Storage Accounts (should show 2 accounts)
Write-Host "`n=== Storage Accounts ===" -ForegroundColor Cyan
az storage account list --resource-group $RG_DATA --query "[].{Name:name, Kind:kind, Location:location}" -o table

# Verify Blob Storage Account (should have isHnsEnabled = false or null)
Write-Host "`n=== Blob Storage Account (No Hierarchical Namespace) ===" -ForegroundColor Cyan
Write-Host "Storage Account Name: $STORAGE_ACCOUNT_NAME" -ForegroundColor Yellow
az storage account show --name $STORAGE_ACCOUNT_NAME --resource-group $RG_DATA --query "{Name:name, Kind:kind, HierarchicalNamespace:properties.isHnsEnabled, BlobEndpoint:primaryEndpoints.blob}" -o json

# Verify Data Lake Gen2 (should have isHnsEnabled = true)
Write-Host "`n=== Data Lake Gen2 Account (Hierarchical Namespace Enabled) ===" -ForegroundColor Cyan
Write-Host "Data Lake Name: $DATA_LAKE_NAME" -ForegroundColor Yellow
az storage account show --name $DATA_LAKE_NAME --resource-group $RG_DATA --query "{Name:name, Kind:kind, HierarchicalNamespace:properties.isHnsEnabled, DfsEndpoint:primaryEndpoints.dfs}" -o json

# Verify both accounts are correctly configured
$BLOB_HNS = az storage account show --name $STORAGE_ACCOUNT_NAME --resource-group $RG_DATA --query "properties.isHnsEnabled" -o tsv
$LAKE_HNS = az storage account show --name $DATA_LAKE_NAME --resource-group $RG_DATA --query "properties.isHnsEnabled" -o tsv

if ($BLOB_HNS -eq "true") {
    Write-Host "`n⚠️ WARNING: Blob Storage Account has hierarchical namespace enabled (should be false/null)" -ForegroundColor Red
} else {
    Write-Host "`n✓ Blob Storage Account correctly configured (no hierarchical namespace)" -ForegroundColor Green
}

if ($LAKE_HNS -eq "true") {
    Write-Host "✓ Data Lake Gen2 correctly configured (hierarchical namespace enabled)" -ForegroundColor Green
} else {
    Write-Host "`n⚠️ ERROR: Data Lake Gen2 does NOT have hierarchical namespace enabled!" -ForegroundColor Red
    Write-Host "   This cannot be fixed after creation - account must be recreated with isHnsEnabled=true" -ForegroundColor Yellow
}
```

**Expected Output:** All 4 resources in "Succeeded" or "Ready" state

---

#### Step 2.2: Deploy Service Bus

**Purpose:** Event-driven messaging for AI agents  
**Bicep File:** `phase2-data-ingestion/service-bus/service-bus.bicep`  
**Dependencies:** None (can deploy in parallel with other Phase 2 resources)

```powershell
Write-Host "Deploying Service Bus..." -ForegroundColor Green

# Navigate to Service Bus directory (from workspace root or bicep-templates/data)
if (Test-Path "credit-scoring\$PHASE2_BASE\service-bus") {
    cd "credit-scoring\$PHASE2_BASE\service-bus"
} elseif (Test-Path "..\..\..\credit-scoring\$PHASE2_BASE\service-bus") {
    cd "..\..\..\credit-scoring\$PHASE2_BASE\service-bus"
} else {
    Write-Host "ERROR: Cannot find Service Bus directory. Current location: $(Get-Location)" -ForegroundColor Red
    Write-Host "Please navigate to workspace root or bicep-templates/data directory first." -ForegroundColor Yellow
}

$DEPLOYMENT_NAME = "service-bus-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_DATA `
  --template-file service-bus.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters environment=$ENVIRONMENT `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Service Bus deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Service Bus deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$SERVICE_BUS_OUTPUT = az deployment group show `
  --resource-group $RG_DATA `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$SERVICE_BUS_NAMESPACE_ID = $SERVICE_BUS_OUTPUT.serviceBusNamespaceId.value
$SERVICE_BUS_NAMESPACE = $SERVICE_BUS_OUTPUT.serviceBusNamespaceName.value
$SERVICE_BUS_CONNECTION_STRING = $SERVICE_BUS_OUTPUT.serviceBusConnectionString.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  Service Bus Namespace ID: $SERVICE_BUS_NAMESPACE_ID"
Write-Host "  Service Bus Namespace: $SERVICE_BUS_NAMESPACE"
Write-Host "  Connection String: [Hidden]"
```

**Validation:**
```powershell
# Verify Service Bus Namespace
az servicebus namespace list --resource-group $RG_DATA --query "[].{Name:name, State:provisioningState, SKU:sku.name}" -o table

# Verify Topics created
$NAMESPACE = az servicebus namespace list --resource-group $RG_DATA --query "[0].name" -o tsv
az servicebus topic list --resource-group $RG_DATA --namespace-name $NAMESPACE --query "[].{Name:name, MaxSizeInMegabytes:maxSizeInMegabytes}" -o table

# Verify Subscriptions
az servicebus topic subscription list --resource-group $RG_DATA --namespace-name $NAMESPACE --topic-name "data-ingested" --query "[].{Name:name, Topic:topicName}" -o table
```

**Expected Output:** 
- 1 Service Bus namespace (Standard tier)
- 3+ topics (data-ingested, data-quality-checked, features-engineered)
- Multiple subscriptions

---

#### Step 2.3: Deploy Cosmos DB (MongoDB API)

**Purpose:** Document database for agent state and credit applications  
**Bicep File:** `phase2-data-ingestion/mongodb/mongodb.bicep`  
**Dependencies:** None

```powershell
Write-Host "Deploying Cosmos DB (MongoDB API)..." -ForegroundColor Green

# Navigate to Cosmos DB directory
if (Test-Path "credit-scoring\$PHASE2_BASE\mongodb") {
    cd "credit-scoring\$PHASE2_BASE\mongodb"
} elseif (Test-Path "..\..\..\credit-scoring\$PHASE2_BASE\mongodb") {
    cd "..\..\..\credit-scoring\$PHASE2_BASE\mongodb"
} else {
    Write-Host "ERROR: Cannot find Cosmos DB directory. Current location: $(Get-Location)" -ForegroundColor Red
}

$DEPLOYMENT_NAME = "cosmosdb-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_DATA `
  --template-file mongodb.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters environment=$ENVIRONMENT `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Cosmos DB deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Cosmos DB deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$COSMOS_OUTPUT = az deployment group show `
  --resource-group $RG_DATA `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$COSMOS_ACCOUNT_NAME = $COSMOS_OUTPUT.cosmosAccountName.value
$COSMOS_CONNECTION_STRING = $COSMOS_OUTPUT.connectionString.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  Cosmos DB Account: $COSMOS_ACCOUNT_NAME"
Write-Host "  Connection String: [Hidden]"
```

**Validation:**
```powershell
# Verify Cosmos DB account
az cosmosdb list --resource-group $RG_DATA --query "[].{Name:name, Kind:kind, State:provisioningState}" -o table

# Verify MongoDB API enabled
az cosmosdb show --name $COSMOS_ACCOUNT_NAME --resource-group $RG_DATA --query "{Name:name, Kind:kind, ConsistencyLevel:consistencyPolicy.defaultConsistencyLevel}" -o json

# Verify databases
az cosmosdb mongodb database list --account-name $COSMOS_ACCOUNT_NAME --resource-group $RG_DATA --query "[].{Name:name}" -o table
```

**Expected Output:** Cosmos DB account with MongoDB API, 1+ databases

---

#### Step 2.4: Deploy Centralized Diagnostic Settings

**Purpose:** Configure Log Analytics diagnostics for all Phase 1 & 2 resources  
**Bicep File:** `monitoring/diagnostic-settings.bicep`  
**Dependencies:** Monitoring (workspace ID), Data Services (resource IDs), Security (Key Vault ID), Service Bus (namespace ID), Cosmos DB (account ID)

**⚠️ IMPORTANT:** This step requires outputs from Monitoring, Data Services, Security, Service Bus, and Cosmos DB modules.

```powershell
Write-Host "Deploying Centralized Diagnostic Settings..." -ForegroundColor Green

# Verify required variables are set
if (-not $LOG_ANALYTICS_WORKSPACE_ID) {
    Write-Host "ERROR: Missing required dependency!" -ForegroundColor Red
    Write-Host "  LOG_ANALYTICS_WORKSPACE_ID: $LOG_ANALYTICS_WORKSPACE_ID" -ForegroundColor Yellow
    Write-Host "Please deploy Monitoring module (Step 1.3) first." -ForegroundColor Yellow
    Write-Host "Continuing anyway - deployment will likely fail..." -ForegroundColor Yellow
}

if (-not $STORAGE_ACCOUNT_ID -or -not $POSTGRES_SERVER_ID -or -not $REDIS_ID) {
    Write-Host "WARNING: Some resource IDs are missing!" -ForegroundColor Yellow
    Write-Host "  STORAGE_ACCOUNT_ID: $STORAGE_ACCOUNT_ID" -ForegroundColor Yellow
    Write-Host "  POSTGRES_SERVER_ID: $POSTGRES_SERVER_ID" -ForegroundColor Yellow
    Write-Host "  REDIS_ID: $REDIS_ID" -ForegroundColor Yellow
    Write-Host "Please deploy Data Services module (Step 2.1) first." -ForegroundColor Yellow
    Write-Host "Diagnostic settings will be created only for available resources." -ForegroundColor Yellow
}

$DEPLOYMENT_NAME = "diagnostic-settings-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Set defaults for optional resource IDs (empty string = skip)
if (-not $STORAGE_ACCOUNT_ID) { $STORAGE_ACCOUNT_ID = '' }
if (-not $DATA_LAKE_ID) { $DATA_LAKE_ID = '' }
if (-not $POSTGRES_SERVER_ID) { $POSTGRES_SERVER_ID = '' }
if (-not $REDIS_ID) { $REDIS_ID = '' }
if (-not $KEY_VAULT_ID) { $KEY_VAULT_ID = '' }
if (-not $SERVICE_BUS_NAMESPACE_ID) { $SERVICE_BUS_NAMESPACE_ID = '' }
if (-not $COSMOS_ACCOUNT_ID) { $COSMOS_ACCOUNT_ID = '' }

# Navigate to monitoring directory - check if already there first
$currentPath = (Get-Location).Path
if ($currentPath -like "*monitoring*" -and (Test-Path "diagnostic-settings.bicep")) {
    Write-Host "Already in monitoring directory." -ForegroundColor Cyan
} elseif (Test-Path "credit-scoring\azure-infrastructure\bicep-templates\monitoring\diagnostic-settings.bicep") {
    cd "credit-scoring\azure-infrastructure\bicep-templates\monitoring"
} elseif (Test-Path "..\..\..\credit-scoring\azure-infrastructure\bicep-templates\monitoring\diagnostic-settings.bicep") {
    cd "..\..\..\credit-scoring\azure-infrastructure\bicep-templates\monitoring"
} elseif (Test-Path "..\..\azure-infrastructure\bicep-templates\monitoring\diagnostic-settings.bicep") {
    cd "..\..\azure-infrastructure\bicep-templates\monitoring"
} else {
    Write-Host "ERROR: Cannot find diagnostic-settings.bicep. Current location: $currentPath" -ForegroundColor Red
    Write-Host "Please navigate to the workspace root and try again." -ForegroundColor Yellow
}

# Deploy diagnostic settings
# Note: Resource IDs are optional - empty strings will skip those diagnostics
# Tags parameter removed - no longer needed in diagnostic-settings.bicep
az deployment group create `
  --resource-group $RG_MONITORING `
  --template-file diagnostic-settings.bicep `
  --parameters logAnalyticsWorkspaceId=$LOG_ANALYTICS_WORKSPACE_ID `
  --parameters storageAccountId=$STORAGE_ACCOUNT_ID `
  --parameters dataLakeId=$DATA_LAKE_ID `
  --parameters postgresServerId=$POSTGRES_SERVER_ID `
  --parameters redisId=$REDIS_ID `
  --parameters keyVaultId=$KEY_VAULT_ID `
  --parameters serviceBusNamespaceId=$SERVICE_BUS_NAMESPACE_ID `
  --parameters cosmosAccountId=$COSMOS_ACCOUNT_ID `
  --name $DEPLOYMENT_NAME `
  --verbose

if ($LASTEXITCODE -ne 0) {
    Write-Host "Diagnostic settings deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Diagnostic settings deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$DIAGNOSTICS_OUTPUT = az deployment group show `
  --resource-group $RG_MONITORING `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$DIAGNOSTICS_CREATED = $DIAGNOSTICS_OUTPUT.diagnosticSettingsCreated.value

Write-Host "Diagnostic settings created for:" -ForegroundColor Yellow
foreach ($resource in $DIAGNOSTICS_CREATED) {
    Write-Host "  - $resource" -ForegroundColor Green
}
```

**Validation:**

**Option 1: Using captured variables (if available):**
```powershell
# Verify diagnostic settings exist (only for resources that were configured)
Write-Host "Checking diagnostic settings..." -ForegroundColor Cyan

if ($STORAGE_ACCOUNT_ID) {
    Write-Host "`nStorage Account Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $STORAGE_ACCOUNT_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "Storage Account ID not set - skipping validation" -ForegroundColor Gray
}

if ($DATA_LAKE_ID) {
    Write-Host "`nData Lake Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $DATA_LAKE_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "Data Lake ID not set - skipping validation" -ForegroundColor Gray
}

if ($POSTGRES_SERVER_ID) {
    Write-Host "`nPostgreSQL Server Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $POSTGRES_SERVER_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "PostgreSQL Server ID not set - skipping validation" -ForegroundColor Gray
}

if ($REDIS_ID) {
    Write-Host "`nRedis Cache Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $REDIS_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "Redis ID not set - skipping validation" -ForegroundColor Gray
}

if ($KEY_VAULT_ID) {
    Write-Host "`nKey Vault Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $KEY_VAULT_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "Key Vault ID not set - skipping validation" -ForegroundColor Gray
}

if ($SERVICE_BUS_NAMESPACE_ID) {
    Write-Host "`nService Bus Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $SERVICE_BUS_NAMESPACE_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "Service Bus Namespace ID not set - skipping validation" -ForegroundColor Gray
}

if ($COSMOS_ACCOUNT_ID) {
    Write-Host "`nCosmos DB Diagnostics:" -ForegroundColor Yellow
    az monitor diagnostic-settings list --resource $COSMOS_ACCOUNT_ID --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
} else {
    Write-Host "Cosmos DB Account ID not set - skipping validation" -ForegroundColor Gray
}
```

**Option 2: Query by resource group (works without variables):**
```powershell
# Alternative validation: Query resources directly from resource groups
Write-Host "Checking diagnostic settings by resource group..." -ForegroundColor Cyan

# Data Services Resource Group
Write-Host "`n=== Data Services Resources ===" -ForegroundColor Yellow
$storageAccounts = az storage account list --resource-group $RG_DATA --query "[].{Name:name, Id:id}" -o json | ConvertFrom-Json
foreach ($sa in $storageAccounts) {
    Write-Host "`nStorage Account: $($sa.Name)" -ForegroundColor Cyan
    az monitor diagnostic-settings list --resource $sa.Id --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
}

$postgresServers = az postgres flexible-server list --resource-group $RG_DATA --query "[].{Name:name, Id:id}" -o json | ConvertFrom-Json
foreach ($pg in $postgresServers) {
    Write-Host "`nPostgreSQL Server: $($pg.Name)" -ForegroundColor Cyan
    az monitor diagnostic-settings list --resource $pg.Id --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
}

$redisCaches = az redis list --resource-group $RG_DATA --query "[].{Name:name, Id:id}" -o json | ConvertFrom-Json
foreach ($redis in $redisCaches) {
    Write-Host "`nRedis Cache: $($redis.Name)" -ForegroundColor Cyan
    az monitor diagnostic-settings list --resource $redis.Id --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
}

# Security Resource Group
Write-Host "`n=== Security Resources ===" -ForegroundColor Yellow
$keyVaults = az keyvault list --resource-group $RG_SECURITY --query "[].{Name:name, Id:id}" -o json | ConvertFrom-Json
foreach ($kv in $keyVaults) {
    Write-Host "`nKey Vault: $($kv.Name)" -ForegroundColor Cyan
    az monitor diagnostic-settings list --resource $kv.Id --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
}

# Service Bus (in Data Resource Group)
Write-Host "`n=== Service Bus Resources ===" -ForegroundColor Yellow
$serviceBusNamespaces = az servicebus namespace list --resource-group $RG_DATA --query "[].{Name:name, Id:id}" -o json | ConvertFrom-Json
foreach ($sb in $serviceBusNamespaces) {
    Write-Host "`nService Bus Namespace: $($sb.Name)" -ForegroundColor Cyan
    az monitor diagnostic-settings list --resource $sb.Id --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
}

# Cosmos DB (in Data Resource Group)
Write-Host "`n=== Cosmos DB Resources ===" -ForegroundColor Yellow
$cosmosAccounts = az cosmosdb list --resource-group $RG_DATA --query "[].{Name:name, Id:id}" -o json | ConvertFrom-Json
foreach ($cosmos in $cosmosAccounts) {
    Write-Host "`nCosmos DB Account: $($cosmos.Name)" -ForegroundColor Cyan
    az monitor diagnostic-settings list --resource $cosmos.Id --query "[].{Name:name, Workspace:properties.workspaceId}" -o table
}
```

**Expected Output:** Diagnostic settings created for all provided resources, all pointing to the Log Analytics workspace

---

### Phase 3: Compute (Depends on Phase 1)

Deploy compute resources that depend on networking.

---

#### Step 3.1: Deploy AKS and Container Registry

**Purpose:** Kubernetes cluster and container registry  
**Bicep File:** `compute/aks.bicep`  
**Dependencies:** Networking (subnet)


**⚠️ IMPORTANT:** This module requires:
- AKS subnet ID from Networking module (Step 1.1)
- Log Analytics Workspace ID from Monitoring module (Step 1.3)

**✅ Recommendation (fallback):** If the inline block below is unreliable in your terminal (PowerShell pasting/runs line-by-line), run the script instead:

`.\credit-scoring\azure-infrastructure\scripts\deploy-aks.ps1`

This script reuses the same session variables (if set), and includes the same checks and parameters.

**💡 TIP:** To avoid PowerShell execution issues when pasting, either:
1. **Use the script file** (recommended): Run `.\credit-scoring\azure-infrastructure\scripts\deploy-aks.ps1` from workspace root
2. **Copy the entire code block at once** (select all lines, then paste all at once)
3. **Save as a script file**: Copy code to `deploy-aks.ps1` and run: `.\deploy-aks.ps1`

```powershell
Write-Host "Deploying AKS and Container Registry..." -ForegroundColor Green

# Check if AKS cluster already exists with incompatible availability zones
$EXISTING_AKS = az aks list --resource-group $RG_COMPUTE --query "[?contains(name, '$NAMING_PREFIX')].{Name:name, Zones:agentPoolProfiles[0].availabilityZones}" -o json | ConvertFrom-Json
if ($EXISTING_AKS -and $EXISTING_AKS.Count -gt 0) {
    $AKS_NAME = $EXISTING_AKS[0].Name
    $EXISTING_ZONES = $EXISTING_AKS[0].Zones
    
    # Check if zones are set but we're trying to deploy without zones (or vice versa)
    $HAS_ZONES = $EXISTING_ZONES -and $EXISTING_ZONES.Count -gt 0
    $WANT_ZONES = $AKS_AVAILABILITY_ZONES -and $AKS_AVAILABILITY_ZONES.Count -gt 0
    
    if ($HAS_ZONES -and -not $WANT_ZONES) {
        Write-Host "`n⚠️  WARNING: Existing AKS cluster '$AKS_NAME' has availability zones configured: $($EXISTING_ZONES -join ', ')" -ForegroundColor Yellow
        Write-Host "   You are trying to deploy without zones (empty array)." -ForegroundColor Yellow
        Write-Host "   Azure does not allow changing availability zones on existing node pools." -ForegroundColor Yellow
        Write-Host "`n   To fix this, you must delete the existing cluster first:" -ForegroundColor Cyan
        Write-Host "   az aks delete --name $AKS_NAME --resource-group $RG_COMPUTE --yes" -ForegroundColor White
        Write-Host "`n   Then run this deployment again." -ForegroundColor Cyan
        Write-Host "`n   Alternatively, if the cluster is working, you can skip this deployment." -ForegroundColor Gray
        exit 1
    } elseif (-not $HAS_ZONES -and $WANT_ZONES) {
        Write-Host "`n⚠️  WARNING: Existing AKS cluster '$AKS_NAME' does not have availability zones configured." -ForegroundColor Yellow
        Write-Host "   You are trying to deploy with zones: $($AKS_AVAILABILITY_ZONES -join ', ')" -ForegroundColor Yellow
        Write-Host "   Azure does not allow changing availability zones on existing node pools." -ForegroundColor Yellow
        Write-Host "`n   To fix this, you must delete the existing cluster first:" -ForegroundColor Cyan
        Write-Host "   az aks delete --name $AKS_NAME --resource-group $RG_COMPUTE --yes" -ForegroundColor White
        Write-Host "`n   Then run this deployment again." -ForegroundColor Cyan
        exit 1
    } else {
        Write-Host "Existing AKS cluster '$AKS_NAME' found. Zones configuration matches - proceeding with deployment..." -ForegroundColor Cyan
    }
}

# Verify required variables - try to capture if missing
if (-not $LOG_ANALYTICS_WORKSPACE_ID) {
    Write-Host "ERROR: Missing required dependency!" -ForegroundColor Red
    Write-Host "  LOG_ANALYTICS_WORKSPACE_ID: $LOG_ANALYTICS_WORKSPACE_ID" -ForegroundColor Yellow
    Write-Host "Please deploy Monitoring module (Step 1.3) first and capture outputs." -ForegroundColor Yellow
    Write-Host "Continuing anyway - deployment will likely fail..." -ForegroundColor Yellow
}

if (-not $AKS_SUBNET_ID) {
    Write-Host "WARNING: AKS_SUBNET_ID not set. Attempting to capture from Networking deployment..." -ForegroundColor Yellow
    
    # Try to find the most recent Networking deployment
    $networkingDeployments = az deployment group list --resource-group $RG_NETWORKING --query "[?contains(name, 'networking')].{Name:name, Time:properties.timestamp}" -o json | ConvertFrom-Json | Sort-Object Time -Descending
    
    if ($networkingDeployments -and $networkingDeployments.Count -gt 0) {
        $latestDeployment = $networkingDeployments[0].Name
        Write-Host "Found Networking deployment: $latestDeployment" -ForegroundColor Cyan
        
        $NETWORKING_OUTPUT = az deployment group show --resource-group $RG_NETWORKING --name $latestDeployment --query properties.outputs -o json | ConvertFrom-Json
        
        $AKS_SUBNET_ID = $NETWORKING_OUTPUT.aksSubnetId.value
        $DATA_SUBNET_ID = $NETWORKING_OUTPUT.dataSubnetId.value
        $VNET_ID = $NETWORKING_OUTPUT.vnetId.value
        
        if ($AKS_SUBNET_ID) {
            Write-Host "Successfully captured AKS_SUBNET_ID: $AKS_SUBNET_ID" -ForegroundColor Green
        } else {
            Write-Host "ERROR: Could not extract AKS_SUBNET_ID from deployment outputs!" -ForegroundColor Red
            Write-Host "Please run the 'Capture Outputs' section from Step 1.1 (Networking) manually." -ForegroundColor Yellow
            exit 1
        }
    } else {
        Write-Host "ERROR: No Networking deployment found in resource group $RG_NETWORKING" -ForegroundColor Red
        Write-Host "Please deploy Networking module (Step 1.1) first, then capture outputs." -ForegroundColor Yellow
        exit 1
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
}

$DEPLOYMENT_NAME = "aks-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Kubernetes version (patch) selection
# Recommended: set $AKS_K8S_VERSION in the variables block (e.g., "1.33.6")
if ($AKS_K8S_VERSION) {
    $LATEST_K8S_VERSION = $AKS_K8S_VERSION
    Write-Host "Using Kubernetes version from environment: $LATEST_K8S_VERSION" -ForegroundColor Green
} else {
    Write-Host "AKS_K8S_VERSION not set. Attempting to query a supported patch version for $LOCATION..." -ForegroundColor Yellow

    # Get all versions and filter in PowerShell (Azure sometimes returns isPreview=null)
    $allVersionsData = az aks get-versions --location $LOCATION -o json | ConvertFrom-Json
    $allVersions = $allVersionsData.values | Where-Object { $_.isPreview -ne $true } | ForEach-Object { $_.version }

    if ($allVersions -and $allVersions.Count -gt 0) {
        $sortedVersions = $allVersions | Sort-Object { [version]$_ } -Descending
        $LATEST_MINOR = $sortedVersions[0]

        # Pick the newest patch for the newest minor stream
        $patchMap = ($allVersionsData.values | Where-Object { $_.version -eq $LATEST_MINOR } | Select-Object -First 1).patchVersions
        $patches = $patchMap.PSObject.Properties.Name | Sort-Object { [version]$_ } -Descending
        $LATEST_K8S_VERSION = $patches[0]

        Write-Host "Auto-selected Kubernetes patch version: $LATEST_K8S_VERSION" -ForegroundColor Green
        Write-Host "TIP: Add this to your variables block as `$AKS_K8S_VERSION = `"$LATEST_K8S_VERSION`"" -ForegroundColor Cyan
    } else {
        Write-Host "ERROR: Could not determine a supported AKS version. Please set `$AKS_K8S_VERSION (patch) manually." -ForegroundColor Red
        Write-Host "Run: az aks get-versions --location $LOCATION" -ForegroundColor Yellow
        exit 1
    }
}

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Set availability zones (empty array for regions that don't support zones, e.g., eastus2)
# For regions that support zones, use: $AKS_AVAILABILITY_ZONES = @('1', '2', '3')
# For regions that don't support zones, use: $AKS_AVAILABILITY_ZONES = @()
if (-not $AKS_AVAILABILITY_ZONES) {
    # Default to empty array (no zones) - works for all regions
    $AKS_AVAILABILITY_ZONES = @()
    Write-Host "Using empty availability zones array (region may not support zones)" -ForegroundColor Yellow
}

# Format availability zones as JSON array for Azure CLI
if ($AKS_AVAILABILITY_ZONES.Count -eq 0) {
    $ZONES_PARAM = "[]"
} else {
    $zonesQuoted = $AKS_AVAILABILITY_ZONES | ForEach-Object { "`"$_`"" }
    $ZONES_PARAM = "[$($zonesQuoted -join ',')]"
}

# Deploy using inline parameters for simple values, file for tags
az deployment group create --resource-group $RG_COMPUTE --template-file aks.bicep --parameters location=$LOCATION --parameters namingPrefix=$NAMING_PREFIX --parameters nodeCount=$AKS_NODE_COUNT --parameters vmSize=$AKS_VM_SIZE --parameters enableAutoScaling=$ENABLE_AUTO_SCALING --parameters minNodeCount=$AKS_MIN_NODES --parameters maxNodeCount=$AKS_MAX_NODES --parameters vnetSubnetId=$AKS_SUBNET_ID --parameters kubernetesVersion=$LATEST_K8S_VERSION --parameters logAnalyticsWorkspaceId=$LOG_ANALYTICS_WORKSPACE_ID --parameters availabilityZones="$ZONES_PARAM" --parameters "@$TAGS_FILE" --name $DEPLOYMENT_NAME --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "AKS deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "AKS and Container Registry deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$AKS_OUTPUT = az deployment group show `
  --resource-group $RG_COMPUTE `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$AKS_CLUSTER_NAME = $AKS_OUTPUT.aksClusterName.value
$ACR_NAME = $AKS_OUTPUT.containerRegistryName.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  AKS Cluster Name: $AKS_CLUSTER_NAME"
Write-Host "  ACR Name: $ACR_NAME"
```

**Validation:**
```powershell
# Set cluster name if not already captured from outputs
if (-not $AKS_CLUSTER_NAME) {
    # Try to get from deployment outputs first
    $AKS_OUTPUT = az deployment group show --resource-group $RG_COMPUTE --name $DEPLOYMENT_NAME --query properties.outputs -o json | ConvertFrom-Json
    if ($AKS_OUTPUT -and $AKS_OUTPUT.aksClusterName) {
        $AKS_CLUSTER_NAME = $AKS_OUTPUT.aksClusterName.value
    } else {
        # Fallback: derive from naming prefix (matches Bicep template)
        $AKS_CLUSTER_NAME = "$NAMING_PREFIX-aks"
        Write-Host "Cluster name not found in outputs. Using derived name: $AKS_CLUSTER_NAME" -ForegroundColor Yellow
    }
}

# Verify AKS cluster
az aks list --resource-group $RG_COMPUTE --query "[].{Name:name, State:provisioningState, NodeCount:agentPoolProfiles[0].count}" -o table

# Verify Container Registry
az acr list --resource-group $RG_COMPUTE --query "[].{Name:name, State:provisioningState, SKU:sku.name}" -o table

# Get AKS credentials (for kubectl access)
if ($AKS_CLUSTER_NAME) {
    az aks get-credentials --resource-group $RG_COMPUTE --name $AKS_CLUSTER_NAME --overwrite-existing
} else {
    Write-Host "WARNING: AKS_CLUSTER_NAME not set. Skipping credential retrieval." -ForegroundColor Yellow
    Write-Host "Set it manually: `$AKS_CLUSTER_NAME = `"$NAMING_PREFIX-aks`"" -ForegroundColor Cyan
}

# Verify nodes (if kubectl installed)
kubectl get nodes 2>$null
```

**Expected Output:** AKS cluster in "Succeeded" state, ACR in "Succeeded" state

---

### Phase 4: ML and Data Factory (Depends on Phase 1, 2, 3)

Deploy ML workspace and Data Factory that depend on multiple previous modules.

---

#### Step 4.1: Deploy Azure ML Workspace

**Purpose:** Machine Learning workspace for model training  
**Bicep File:** `compute/ml-workspace.bicep`  
**Dependencies:** Security (Key Vault), Data (Storage), Monitoring (App Insights)

**⚠️ IMPORTANT:** Requires outputs from Security, Data, Monitoring, and Networking modules.

**💡 TIP (GPU cluster optional):**  
- By default, the GPU training cluster is **disabled** to avoid quota errors in dev/test subscriptions.  
- To enable it (once you have sufficient GPU vCPU quota), add: `--parameters enableGpuCluster=true` to the ML workspace deployment command below.

```powershell
Write-Host "Deploying Azure ML Workspace..." -ForegroundColor Green

# Verify required variables
if (-not $KEY_VAULT_ID -or -not $STORAGE_ACCOUNT_ID -or -not $APP_INSIGHTS_ID -or -not $ML_SUBNET_ID) {
    Write-Host "ERROR: Missing required dependencies!" -ForegroundColor Red
    Write-Host "  KEY_VAULT_ID: $KEY_VAULT_ID"
    Write-Host "  STORAGE_ACCOUNT_ID: $STORAGE_ACCOUNT_ID"
    Write-Host "  APP_INSIGHTS_ID: $APP_INSIGHTS_ID"
    Write-Host "  ML_SUBNET_ID: $ML_SUBNET_ID"
    Write-Host "Please deploy Security, Data, Monitoring, and Networking modules first (and capture outputs)." -ForegroundColor Yellow
    Write-Host "Continuing anyway - deployment will likely fail..." -ForegroundColor Yellow
}

cd ..\compute

$DEPLOYMENT_NAME = "ml-workspace-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_ML `
  --template-file ml-workspace.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters keyVaultId=$KEY_VAULT_ID `
  --parameters storageAccountId=$STORAGE_ACCOUNT_ID `
  --parameters applicationInsightsId=$APP_INSIGHTS_ID `
  --parameters subnetId=$ML_SUBNET_ID `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "ML Workspace deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "ML Workspace deployed successfully!" -ForegroundColor Green
}
```

**Capture Outputs:**
```powershell
$ML_OUTPUT = az deployment group show `
  --resource-group $RG_ML `
  --name $DEPLOYMENT_NAME `
  --query properties.outputs -o json | ConvertFrom-Json

$ML_WORKSPACE_NAME = $ML_OUTPUT.workspaceName.value
$ML_WORKSPACE_ID = $ML_OUTPUT.workspaceId.value

Write-Host "Captured outputs:" -ForegroundColor Yellow
Write-Host "  ML Workspace Name: $ML_WORKSPACE_NAME"
Write-Host "  ML Workspace ID: $ML_WORKSPACE_ID"
```

**Validation:**
```powershell
# Verify ML Workspace
az ml workspace list --resource-group $RG_ML --query "[].{Name:name, Location:location}" -o table

# Verify ML Workspace details
az ml workspace show --name $ML_WORKSPACE_NAME --resource-group $RG_ML --query "{Name:name, State:provisioningState, KeyVault:keyVault}" -o json
```

**Expected Output:** ML Workspace in "Succeeded" state

---

#### Step 4.2: Deploy Azure Data Factory

**Purpose:** Data ingestion pipelines  
**Bicep File:** `phase2-data-ingestion/azure-data-factory/data-factory.bicep`  
**Dependencies:** Service Bus, Data Lake, Key Vault

**⚠️ IMPORTANT:** Requires Service Bus namespace name, Data Lake storage account name, and Key Vault name.

```powershell
Write-Host "Deploying Azure Data Factory..." -ForegroundColor Green

# Verify required variables
if (-not $SERVICE_BUS_NAMESPACE -or -not $DATA_LAKE_NAME -or -not $KEY_VAULT_NAME) {
    Write-Host "ERROR: Missing required dependencies!" -ForegroundColor Red
    Write-Host "  SERVICE_BUS_NAMESPACE: $SERVICE_BUS_NAMESPACE"
    Write-Host "  DATA_LAKE_NAME: $DATA_LAKE_NAME"
    Write-Host "  KEY_VAULT_NAME: $KEY_VAULT_NAME"
    Write-Host "Please deploy Service Bus, Data Services, and Security modules first." -ForegroundColor Yellow
    Write-Host "Continuing anyway - deployment will likely fail..." -ForegroundColor Yellow
}

# Navigate to Data Factory directory - robust path handling
$currentPath = (Get-Location).Path
if ($currentPath -like "*azure-data-factory*" -and (Test-Path "data-factory.bicep")) {
    Write-Host "Already in Azure Data Factory directory." -ForegroundColor Cyan
} elseif (Test-Path "credit-scoring\$PHASE2_BASE\azure-data-factory\data-factory.bicep") {
    # From workspace root
    cd "credit-scoring\$PHASE2_BASE\azure-data-factory"
} elseif (Test-Path "..\..\$PHASE2_BASE\azure-data-factory\data-factory.bicep") {
    # From bicep-templates\data or bicep-templates\compute
    cd "..\..\$PHASE2_BASE\azure-data-factory"
} elseif (Test-Path "..\..\..\credit-scoring\$PHASE2_BASE\azure-data-factory\data-factory.bicep") {
    # From inside azure-infrastructure or similar
    cd "..\..\..\credit-scoring\$PHASE2_BASE\azure-data-factory"
} else {
    Write-Host "ERROR: Cannot find Data Factory directory. Current location: $currentPath" -ForegroundColor Red
    Write-Host "Please navigate to the workspace root and try again (project root: ...\\blache)." -ForegroundColor Yellow
}

$DEPLOYMENT_NAME = "data-factory-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_DATA `
  --template-file data-factory.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters environment=$ENVIRONMENT `
  --parameters dataLakeStorageAccountName=$DATA_LAKE_NAME `
  --parameters keyVaultName=$KEY_VAULT_NAME `
  --parameters serviceBusNamespaceName=$SERVICE_BUS_NAMESPACE `
  --parameters "@$TAGS_FILE" `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Data Factory deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Data Factory deployed successfully!" -ForegroundColor Green
}
```

**Validation:**
```powershell
# Verify Data Factory
az datafactory list --resource-group $RG_DATA --query "[].{Name:name, State:provisioningState, Location:location}" -o table

# Verify Linked Services
$ADF_NAME = az datafactory list --resource-group $RG_DATA --query "[0].name" -o tsv
az datafactory linked-service list --factory-name $ADF_NAME --resource-group $RG_DATA --query "[].{Name:name, Type:properties.type}" -o table

# Verify Pipelines
az datafactory pipeline list --factory-name $ADF_NAME --resource-group $RG_DATA --query "[].{Name:name}" -o table
```

**Expected Output:** Data Factory with linked services and pipelines

---

### Phase 5: API Gateway (Depends on Phase 1)

Deploy API Management and Azure AD B2C.

---

#### Step 5.1: Deploy Azure AD B2C

**⚠️ CRITICAL: Azure AD B2C Deprecation Notice**

**As of May 1, 2025, Azure AD B2C is no longer available for new sales and new tenants cannot be created.**

**Microsoft Recommendation:** Use **Microsoft Entra External ID** instead for managing external identities.

**For New Deployments:**
- **You cannot create new Azure AD B2C tenants** - the deployment will fail
- Plan to use **Microsoft Entra External ID** for new projects
- Learn more: https://aka.ms/EEIDOverview

**For Existing B2C Tenants:**
- Existing tenants continue to function normally
- You can still deploy configurations to existing B2C tenants
- Consider planning migration to Microsoft Entra External ID for future projects

**B2C Tenant Creation Tutorial (Will Fail for New Tenants):**
- Official tutorial: https://learn.microsoft.com/en-us/azure/active-directory-b2c/tutorial-create-tenant?WT.mc_id=Portal-Microsoft_AAD_B2CAdmin
- **Note:** Following this tutorial will result in an error: "As of May 1, 2025, Azure AD B2C is no longer available for new sales; hence, new tenants cannot be created."

**Purpose:** User authentication (for existing B2C tenants only)  
**Bicep File:** `phase5-api-gateway/aad-b2c/aad-b2c-config.bicep`  
**Dependencies:** Monitoring (App Insights - optional)  
**Status:** ⚠️ **Cannot deploy new B2C tenants - use Microsoft Entra External ID instead**

```powershell
Write-Host "Deploying Azure AD B2C..." -ForegroundColor Green

# Navigate to Azure AD B2C directory - robust path handling
$currentPath = (Get-Location).Path
if ($currentPath -like "*aad-b2c*" -and (Test-Path "aad-b2c-config.bicep")) {
    Write-Host "Already in Azure AD B2C directory." -ForegroundColor Cyan
} elseif (Test-Path "credit-scoring\$PHASE5_BASE\aad-b2c\aad-b2c-config.bicep") {
    # From workspace root
    cd "credit-scoring\$PHASE5_BASE\aad-b2c"
} elseif (Test-Path "..\..\$PHASE5_BASE\aad-b2c\aad-b2c-config.bicep") {
    # From bicep-templates\monitoring or bicep-templates\compute
    cd "..\..\$PHASE5_BASE\aad-b2c"
} elseif (Test-Path "..\..\..\credit-scoring\$PHASE5_BASE\aad-b2c\aad-b2c-config.bicep") {
    # From inside azure-infrastructure or similar
    cd "..\..\..\credit-scoring\$PHASE5_BASE\aad-b2c"
} else {
    Write-Host "ERROR: Cannot find aad-b2c-config.bicep. Current location: $currentPath" -ForegroundColor Red
    Write-Host "Please navigate to the workspace root and try again (project root: ...\blache)." -ForegroundColor Yellow
}

$DEPLOYMENT_NAME = "aad-b2c-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values, file for tags
az deployment group create `
  --resource-group $RG_COMPUTE `
  --template-file aad-b2c-config.bicep `
  --parameters location=$LOCATION `
  --parameters namingPrefix=$NAMING_PREFIX `
  --parameters environment=$ENVIRONMENT `
  --parameters appInsightsId=$APP_INSIGHTS_ID `
  --name $DEPLOYMENT_NAME `
  --verbose

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "Azure AD B2C deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "Azure AD B2C deployed successfully!" -ForegroundColor Green
}
```

**Validation:**
```powershell
# Note: Azure AD B2C is a tenant-level resource, verification may differ
# Check deployment status
az deployment group show --resource-group $RG_COMPUTE --name $DEPLOYMENT_NAME --query "properties.provisioningState" -o tsv
```

---

#### Step 5.2: Deploy API Management

**Purpose:** API Gateway for external access (requires B2C when API policy is enabled)  
**Bicep File:** `phase5-api-gateway/apim/api-management.bicep`  
**Dependencies:** Monitoring (App Insights - optional), Azure AD B2C (Step 5.1) or Microsoft Entra External ID

**⚠️ IMPORTANT: Azure AD B2C Deprecation**
- **As of May 1, 2025, new Azure AD B2C tenants cannot be created**
- If you have an **existing B2C tenant**, you can use it with APIM
- For **new deployments**, plan to use **Microsoft Entra External ID** instead
- See Step 5.1 above for more details

**⚠️ IMPORTANT: Before deploying, you must identify your B2C tenant configuration (for existing tenants only):**

```powershell
# ==================================================
# STEP 1: Identify Your B2C Configuration
# ==================================================
Write-Host "Identifying B2C tenant configuration..." -ForegroundColor Yellow

# Option A: If you know your B2C tenant name, set it directly
# $B2C_TENANT_NAME = "blache-creditscore-b2c"  # Replace with your actual tenant name
# $B2C_TENANT_DOMAIN = "blache-creditscore-b2c.onmicrosoft.com"  # Replace with your actual domain
# $B2C_POLICY_NAME = "B2C_1_SignUpSignIn"  # Replace with your actual policy name

# Option B: Query Azure AD B2C tenants (if you have access)
# $B2C_TENANTS = az ad tenant list --query "[?contains(displayName, 'b2c')].{Name:displayName, Domain:defaultDomain}" -o json | ConvertFrom-Json
# if ($B2C_TENANTS -and $B2C_TENANTS.Count -gt 0) {
#     $B2C_TENANT_NAME = $B2C_TENANTS[0].Name
#     $B2C_TENANT_DOMAIN = $B2C_TENANTS[0].Domain
#     Write-Host "Found B2C tenant: $B2C_TENANT_NAME" -ForegroundColor Green
# }

# Option C: Test the OpenID configuration URL directly
# Replace with your actual values and test in browser or PowerShell:
# $TEST_URL = "https://YOUR-TENANT-NAME.b2clogin.com/YOUR-TENANT-DOMAIN/v2.0/.well-known/openid-configuration?p=YOUR-POLICY-NAME"
# Invoke-WebRequest -Uri $TEST_URL -UseBasicParsing

# If B2C configuration is not set, deployment will use default placeholder values
# and will likely fail if those don't match your actual B2C tenant
if (-not $B2C_TENANT_NAME -or -not $B2C_TENANT_DOMAIN) {
    Write-Host "WARNING: B2C configuration not set!" -ForegroundColor Yellow
    Write-Host "  Please set the following variables before deployment:" -ForegroundColor Yellow
    Write-Host "    `$B2C_TENANT_NAME = 'your-b2c-tenant-name'" -ForegroundColor Cyan
    Write-Host "    `$B2C_TENANT_DOMAIN = 'your-b2c-tenant.onmicrosoft.com'" -ForegroundColor Cyan
    Write-Host "    `$B2C_POLICY_NAME = 'B2C_1_SignUpSignIn'  # or your actual policy name" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  To find your B2C tenant:" -ForegroundColor Yellow
    Write-Host "    1. Go to Azure Portal > Azure AD B2C" -ForegroundColor Cyan
    Write-Host "    2. Note the tenant name (e.g., 'blache-creditscore-b2c')" -ForegroundColor Cyan
    Write-Host "    3. Note the primary domain (e.g., 'blache-creditscore-b2c.onmicrosoft.com')" -ForegroundColor Cyan
    Write-Host "    4. Go to User flows > Note the policy name (e.g., 'B2C_1_SignUpSignIn')" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Or test the OpenID config URL in your browser:" -ForegroundColor Yellow
    Write-Host "    https://YOUR-TENANT.b2clogin.com/YOUR-DOMAIN/v2.0/.well-known/openid-configuration?p=YOUR-POLICY" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  If the URL returns JSON, it's valid. If it returns 404/error, check your tenant/policy names." -ForegroundColor Yellow
    Write-Host ""
    $CONTINUE = Read-Host "Continue with deployment anyway? (y/N)"
    if ($CONTINUE -ne 'y' -and $CONTINUE -ne 'Y') {
        Write-Host "Deployment cancelled. Please set B2C configuration and try again." -ForegroundColor Red
        return
    }
}

# Set default policy name if not specified
if (-not $B2C_POLICY_NAME) {
    $B2C_POLICY_NAME = "B2C_1_SignUpSignIn"
    Write-Host "Using default B2C policy name: $B2C_POLICY_NAME" -ForegroundColor Cyan
}

Write-Host "Deploying API Management..." -ForegroundColor Green

# Navigate to API Management directory - check if already there first
$currentPath = (Get-Location).Path
if ($currentPath -like "*apim*" -and (Test-Path "api-management.bicep")) {
    Write-Host "Already in API Management directory." -ForegroundColor Cyan
} elseif (Test-Path "credit-scoring\$PHASE5_BASE\apim\api-management.bicep") {
    cd "credit-scoring\$PHASE5_BASE\apim"
} elseif (Test-Path "..\..\..\credit-scoring\$PHASE5_BASE\apim\api-management.bicep") {
    cd "..\..\..\credit-scoring\$PHASE5_BASE\apim"
} elseif (Test-Path "..\..\credit-scoring\$PHASE5_BASE\apim\api-management.bicep") {
    cd "..\..\credit-scoring\$PHASE5_BASE\apim"
} else {
    Write-Host "ERROR: Cannot find api-management.bicep. Current location: $currentPath" -ForegroundColor Red
    Write-Host "Please navigate to the workspace root and try again." -ForegroundColor Yellow
}

$DEPLOYMENT_NAME = "apim-$(Get-Date -Format 'yyyyMMdd-HHmmss')"

# Create tags parameters file
$TAGS_FILE = "tags-$DEPLOYMENT_NAME.json"
New-TagsParametersFile -Tags $TAGS -FilePath $TAGS_FILE

# Deploy using inline parameters for simple values (APIM template does not take tags directly)
# NOTE: enableApiPolicy defaults to true in the Bicep template. This means:
#   - If B2C is not fully configured or reachable, this deployment will FAIL on the validate-jwt policy.
#   - This is intentional to ensure B2C is in place before exposing the API through APIM.

# Build deployment command with B2C parameters (if provided)
$DEPLOY_CMD = "az deployment group create " +
  "--resource-group `$RG_COMPUTE " +
  "--template-file api-management.bicep " +
  "--parameters location=`$LOCATION " +
  "--parameters namingPrefix=`$NAMING_PREFIX " +
  "--parameters environment=`$ENVIRONMENT " +
  "--parameters vnetId=`$VNET_ID " +
  "--parameters apimSubnetId=`$APIM_SUBNET_ID " +
  "--parameters appInsightsId=`$APP_INSIGHTS_ID "

# Add B2C parameters if configured
if ($B2C_TENANT_NAME -and $B2C_TENANT_DOMAIN) {
    $DEPLOY_CMD += "--parameters b2cTenantName=`"$B2C_TENANT_NAME`" "
    $DEPLOY_CMD += "--parameters b2cTenantDomain=`"$B2C_TENANT_DOMAIN`" "
    $DEPLOY_CMD += "--parameters b2cPolicyName=`"$B2C_POLICY_NAME`" "
    Write-Host "Using B2C configuration:" -ForegroundColor Cyan
    Write-Host "  Tenant: $B2C_TENANT_NAME" -ForegroundColor Gray
    Write-Host "  Domain: $B2C_TENANT_DOMAIN" -ForegroundColor Gray
    Write-Host "  Policy: $B2C_POLICY_NAME" -ForegroundColor Gray
} else {
    Write-Host "WARNING: B2C parameters not provided. Using default placeholder values." -ForegroundColor Yellow
    Write-Host "  Deployment may fail if default values don't match your B2C tenant." -ForegroundColor Yellow
}

$DEPLOY_CMD += "--name `$DEPLOYMENT_NAME --verbose"

# Execute deployment
Invoke-Expression $DEPLOY_CMD

# Clean up tags file
Remove-Item $TAGS_FILE -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-Host "API Management deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
} else {
    Write-Host "API Management deployed successfully!" -ForegroundColor Green
}
```

**Validation:**
```powershell
# Verify API Management
az apim list --resource-group $RG_COMPUTE --query "[].{Name:name, State:provisioningState, SKU:sku.name}" -o table

# Get Gateway URL
$APIM_NAME = az apim list --resource-group $RG_COMPUTE --query "[0].name" -o tsv
az apim show --name $APIM_NAME --resource-group $RG_COMPUTE --query "{Name:name, GatewayUrl:properties.gatewayUrl, State:provisioningState}" -o json
```

**Expected Output:** API Management service in "Succeeded" state

---


## Post-Deployment Tasks

### Manual Role Assignments

Since role assignments were commented out in Bicep files (due to permissions), assign them manually:

#### 1. Key Vault Secrets User Role (for Managed Identity)

```powershell
Write-Host "Assigning Key Vault Secrets User role..." -ForegroundColor Yellow

# Get Managed Identity Principal ID (from Security module output)
if (-not $MANAGED_IDENTITY_ID) {
    Write-Host "ERROR: MANAGED_IDENTITY_ID not set. Please capture from Security module deployment." -ForegroundColor Red
    Write-Host "Skipping role assignment..." -ForegroundColor Yellow
    return
}

# Assign role
az role assignment create `
  --role "Key Vault Secrets User" `
  --assignee $MANAGED_IDENTITY_ID `
  --scope "/subscriptions/$(az account show --query id -o tsv)/resourceGroups/$RG_SECURITY/providers/Microsoft.KeyVault/vaults/$KEY_VAULT_NAME"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Key Vault role assignment failed. See error above." -ForegroundColor Red
} else {
    Write-Host "Key Vault role assigned successfully!" -ForegroundColor Green
}
```

#### 2. AKS Network Contributor Role

```powershell
Write-Host "Assigning AKS Network Contributor role..." -ForegroundColor Yellow

# Ensure AKS cluster name is set
if (-not $AKS_CLUSTER_NAME) {
    Write-Host "AKS_CLUSTER_NAME not set. Attempting to auto-detect from resource group $RG_COMPUTE..." -ForegroundColor Yellow

    $AKS_CLUSTER_NAME = az aks list --resource-group $RG_COMPUTE --query "[0].name" -o tsv

    if (-not $AKS_CLUSTER_NAME) {
        Write-Host "ERROR: Could not determine AKS cluster name. Please set \$AKS_CLUSTER_NAME manually, e.g.:" -ForegroundColor Red
        Write-Host '  $AKS_CLUSTER_NAME = "blache-creditscore-dev-aks"' -ForegroundColor Yellow
        return
    }

    Write-Host "Detected AKS cluster: $AKS_CLUSTER_NAME" -ForegroundColor Green
}

# Get AKS Managed Identity Principal ID
$AKS_PRINCIPAL_ID = az aks show --name $AKS_CLUSTER_NAME --resource-group $RG_COMPUTE --query "identity.principalId" -o tsv

if (-not $AKS_PRINCIPAL_ID) {
    Write-Host "ERROR: Could not retrieve AKS principal ID. Check that the cluster exists and try again." -ForegroundColor Red
    return
}

# Get subscription ID
$SUBSCRIPTION_ID = az account show --query id -o tsv

# Validate networking resource group exists
$NETWORKING_RG_EXISTS = az group show --name $RG_NETWORKING --query "name" -o tsv 2>$null
if (-not $NETWORKING_RG_EXISTS) {
    Write-Host "ERROR: Resource group '$RG_NETWORKING' not found." -ForegroundColor Red
    Write-Host "Please verify the resource group name or deploy Networking module first." -ForegroundColor Yellow
    return
}

# Assign role to resource group (for VNet access)
Write-Host "Assigning Network Contributor role to AKS managed identity on resource group: $RG_NETWORKING" -ForegroundColor Cyan
az role assignment create `
  --role "Network Contributor" `
  --assignee $AKS_PRINCIPAL_ID `
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_NETWORKING"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: AKS Network Contributor role assignment failed. See error above." -ForegroundColor Red
} else {
    Write-Host "AKS Network Contributor role assigned successfully!" -ForegroundColor Green
}
```

#### 3. ACR Pull Role (for AKS)

```powershell
Write-Host "Assigning ACR Pull role..." -ForegroundColor Yellow

# Ensure AKS cluster name is set
if (-not $AKS_CLUSTER_NAME) {
    Write-Host "AKS_CLUSTER_NAME not set. Attempting to auto-detect from resource group $RG_COMPUTE..." -ForegroundColor Yellow

    $AKS_CLUSTER_NAME = az aks list --resource-group $RG_COMPUTE --query "[0].name" -o tsv

    if (-not $AKS_CLUSTER_NAME) {
        Write-Host "ERROR: Could not determine AKS cluster name. Please set `$AKS_CLUSTER_NAME manually, e.g.:" -ForegroundColor Red
        Write-Host '  $AKS_CLUSTER_NAME = "blache-creditscore-dev-aks"' -ForegroundColor Yellow
        return
    }

    Write-Host "Detected AKS cluster: $AKS_CLUSTER_NAME" -ForegroundColor Green
}

# Ensure ACR name is set
if (-not $ACR_NAME) {
    Write-Host "ACR_NAME not set. Attempting to auto-detect from AKS deployment outputs..." -ForegroundColor Yellow
    
    # Try to get from most recent AKS deployment
    $AKS_DEPLOYMENTS = az deployment group list --resource-group $RG_COMPUTE --query "[?contains(name, 'aks')].{Name:name, Time:properties.timestamp}" -o json | ConvertFrom-Json | Sort-Object Time -Descending
    
    if ($AKS_DEPLOYMENTS -and $AKS_DEPLOYMENTS.Count -gt 0) {
        $LATEST_AKS_DEPLOYMENT = $AKS_DEPLOYMENTS[0].Name
        Write-Host "Found AKS deployment: $LATEST_AKS_DEPLOYMENT" -ForegroundColor Cyan
        
        $AKS_OUTPUT = az deployment group show --resource-group $RG_COMPUTE --name $LATEST_AKS_DEPLOYMENT --query properties.outputs -o json | ConvertFrom-Json
        $ACR_NAME = $AKS_OUTPUT.containerRegistryName.value
        
        if ($ACR_NAME) {
            Write-Host "Detected ACR name from deployment: $ACR_NAME" -ForegroundColor Green
        }
    }
    
    # If still not found, try to list ACRs in the resource group
    if (-not $ACR_NAME) {
        Write-Host "Trying to find ACR by listing container registries in resource group..." -ForegroundColor Yellow
        $ACR_NAME = az acr list --resource-group $RG_COMPUTE --query "[0].name" -o tsv
        
        if ($ACR_NAME) {
            Write-Host "Detected ACR name: $ACR_NAME" -ForegroundColor Green
        }
    }
    
    # Last resort: derive from naming prefix
    if (-not $ACR_NAME) {
        $ACR_NAME = "$NAMING_PREFIX-acr"
        Write-Host "Could not auto-detect ACR name. Using derived name: $ACR_NAME" -ForegroundColor Yellow
        Write-Host "If this is incorrect, please set `$ACR_NAME manually." -ForegroundColor Yellow
    }
}

# Validate ACR exists
$ACR_EXISTS = az acr show --name $ACR_NAME --resource-group $RG_COMPUTE --query "name" -o tsv 2>$null
if (-not $ACR_EXISTS) {
    Write-Host "ERROR: Container Registry '$ACR_NAME' not found in resource group $RG_COMPUTE." -ForegroundColor Red
    Write-Host "Please verify the ACR name or deploy AKS first (which creates the ACR)." -ForegroundColor Yellow
    return
}

# Get AKS Kubelet Identity Principal ID
$KUBELET_IDENTITY_ID = az aks show --name $AKS_CLUSTER_NAME --resource-group $RG_COMPUTE --query "identityProfile.kubeletidentity.objectId" -o tsv

if (-not $KUBELET_IDENTITY_ID) {
    Write-Host "ERROR: Could not retrieve AKS kubelet identity object ID. Check that the cluster exists and try again." -ForegroundColor Red
    return
}

# Get subscription ID
$SUBSCRIPTION_ID = az account show --query id -o tsv

# Assign AcrPull role
Write-Host "Assigning AcrPull role to AKS kubelet identity on ACR: $ACR_NAME" -ForegroundColor Cyan
az role assignment create `
  --role "AcrPull" `
  --assignee $KUBELET_IDENTITY_ID `
  --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RG_COMPUTE/providers/Microsoft.ContainerRegistry/registries/$ACR_NAME"

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: ACR Pull role assignment failed. See error above." -ForegroundColor Red
} else {
    Write-Host "ACR Pull role assigned successfully!" -ForegroundColor Green
}
```

**Validation:**
```powershell
# List all role assignments for verification
az role assignment list --scope "/subscriptions/$(az account show --query id -o tsv)" --query "[?contains(principalName, '$NAMING_PREFIX')].{Principal:principalName, Role:roleDefinitionName, Scope:scope}" -o table
```

---

### Resources Without Bicep Files

#### Azure Functions

**Deployment Method:** Manual via Azure Functions Core Tools

```powershell
# Install Azure Functions Core Tools (if not installed)
# npm install -g azure-functions-core-tools@4

# Prerequisite: Ensure Microsoft.Web provider is registered (required for Azure Functions)
Write-Host "Checking Microsoft.Web provider registration..." -ForegroundColor Yellow
$WEB_PROVIDER_STATE = az provider show --namespace Microsoft.Web --query "registrationState" -o tsv
if ($WEB_PROVIDER_STATE -ne "Registered") {
    Write-Host "Microsoft.Web provider is not registered. Registering now..." -ForegroundColor Yellow
    az provider register --namespace Microsoft.Web
    Write-Host "Waiting for registration to complete (this may take 1-2 minutes)..." -ForegroundColor Yellow
    do {
        Start-Sleep -Seconds 10
        $WEB_PROVIDER_STATE = az provider show --namespace Microsoft.Web --query "registrationState" -o tsv
        Write-Host "  Registration state: $WEB_PROVIDER_STATE" -ForegroundColor Gray
    } while ($WEB_PROVIDER_STATE -eq "Registering")
    
    if ($WEB_PROVIDER_STATE -ne "Registered") {
        Write-Host "ERROR: Microsoft.Web provider registration failed or is still pending." -ForegroundColor Red
        Write-Host "Please wait a few minutes and try again, or register manually:" -ForegroundColor Yellow
        Write-Host "  az provider register --namespace Microsoft.Web" -ForegroundColor Cyan
        return
    }
    Write-Host "Microsoft.Web provider registered successfully!" -ForegroundColor Green
} else {
    Write-Host "Microsoft.Web provider is already registered." -ForegroundColor Green
}

# Create a dedicated **Functions** storage account in the agents resource group (once per environment)
# NOTE: We use a separate variable ($FUNC_STORAGE_ACCOUNT_NAME) so we don't override $STORAGE_ACCOUNT_NAME
# from the Data Services module. This keeps data storage and functions storage clearly separated.
Write-Host "Creating (or reusing) Functions storage account in agents RG..." -ForegroundColor Yellow

if (-not $RG_AGENTS) {
    $RG_AGENTS = "$NAMING_PREFIX-agents-rg"
    Write-Host "RG_AGENTS not set. Defaulting to $RG_AGENTS" -ForegroundColor Yellow
}

# Choose a deterministic, unique name (3-24 chars, lowercase, no hyphens)
# Storage account names: lowercase letters and numbers only, 3-24 chars
$PREFIX_FIRST = ($NAMING_PREFIX -split '-')[0].ToLower() # e.g. "blache" from "blache-creditscore-dev"
$FUNC_SA_NAME = ($PREFIX_FIRST + "funcsa")               # e.g. "blachefuncsa"
if ($FUNC_SA_NAME.Length -gt 24) {
    # Truncate to 24 chars if needed
    $FUNC_SA_NAME = $FUNC_SA_NAME.Substring(0, 24)
}

# Check if functions storage account already exists
$EXISTING_FUNC_SA = az storage account list --resource-group $RG_AGENTS --query "[?name=='$FUNC_SA_NAME'].name" -o tsv

if (-not $EXISTING_FUNC_SA) {
    az storage account create `
      --name $FUNC_SA_NAME `
      --resource-group $RG_AGENTS `
      --location $LOCATION `
      --sku Standard_LRS `
      --kind StorageV2
} else {
    Write-Host "Functions storage account $FUNC_SA_NAME already exists in $RG_AGENTS. Reusing it." -ForegroundColor Cyan
}

$FUNC_STORAGE_ACCOUNT_NAME = $FUNC_SA_NAME
Write-Host "Using Functions storage account: $FUNC_STORAGE_ACCOUNT_NAME" -ForegroundColor Green

# Navigate to function directory
cd credit-scoring\phase2-data-ingestion\agents\data-quality-agent

# Create Function App (if not exists)
az functionapp create `
  --resource-group $RG_AGENTS `
  --consumption-plan-location $LOCATION `
  --os-type Linux `
  --runtime python `
  --runtime-version 3.11 `
  --functions-version 4 `
  --name "$NAMING_PREFIX-func-dqa" `
  --storage-account $FUNC_STORAGE_ACCOUNT_NAME

# Deploy function code
func azure functionapp publish "$NAMING_PREFIX-func-dqa" --python

# Repeat for other agents:
# - feature-engineering-agent
# - decision-agent
# - risk-monitoring-agent
# - compliance-agent
# - model-training-agent
```

#### Static Web Apps

**Deployment Method:** Azure CLI or Portal

**Prerequisites:**
- GitHub Personal Access Token (PAT) with `repo` scope
- Repository must exist on GitHub and be accessible
- **For organization repositories:** You must have access to the repository, and the organization must allow PATs (check with your org admin if unsure)

**Step 1: Create GitHub Personal Access Token (if not already created)**

**For Personal or Organization Repositories:**

Yes, you can generate a Personal Access Token (PAT) for company/organization repositories if:
- ✅ You have read/write access to the repository
- ✅ Your organization allows PATs (some orgs restrict them for security)
- ✅ The token has the required scopes

**Creating the Token:**

1. Go to GitHub: https://github.com/settings/tokens
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a name (e.g., "Azure Static Web Apps - Blache Credit Scoring")
4. Select scopes:
   - ✅ `repo` (Full control of private repositories) - **Required**
   - ✅ `workflow` (Update GitHub Action workflows) - if using GitHub Actions
5. **For organization repos:** Your organization may require approval for PATs. If prompted, request approval from your org admin.
6. Click "Generate token"
7. **Copy the token immediately** (you won't be able to see it again)

**Alternative: Fine-Grained Personal Access Token (Recommended for Organizations)**

Some organizations prefer fine-grained PATs for better security:
1. Go to: https://github.com/settings/tokens?type=beta
2. Click "Generate new token" → "Fine-grained token"
3. Select your organization and repository
4. Set expiration and permissions (Repository access: Read and write)
5. Generate and copy the token

**Note:** If your organization has restrictions on PATs, you may need to:
- Request approval from your organization admin
- Use a GitHub App instead (requires org admin setup)
- Use the `--login-with-github` flag for interactive authentication (works with org repos if you have access)

**Step 2: Set GitHub Token Variable**

```powershell
# Set your GitHub Personal Access Token
# Option 1: Set as environment variable (recommended for security)
$env:GITHUB_TOKEN = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"

# Option 2: Set as PowerShell variable (less secure, visible in history)
$GITHUB_TOKEN = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"
```

**Step 3: Deploy Static Web App**

```powershell
# Set default app and API locations (customize if your repo structure differs)
# App location: Root of the frontend application (Next.js project root)
if (-not $STATIC_WEB_APP_LOCATION) {
    $STATIC_WEB_APP_LOCATION = "phase6-user-interface"
}

# API location: Path to API routes (Next.js App Router uses app/api)
if (-not $STATIC_WEB_API_LOCATION) {
    $STATIC_WEB_API_LOCATION = "phase6-user-interface/app/api"
}

# Output location: Next.js build output directory
if (-not $STATIC_WEB_OUTPUT_LOCATION) {
    $STATIC_WEB_OUTPUT_LOCATION = ".next"
}

# GitHub repository URL (default: blacheinc/credit-scoring)
if (-not $GITHUB_REPO_URL) {
    $GITHUB_REPO_URL = "https://github.com/blacheinc/credit-scoring.git"
    Write-Host "Using default GitHub repository: $GITHUB_REPO_URL" -ForegroundColor Cyan
    Write-Host "To use a different repository, set `$GITHUB_REPO_URL before running this script." -ForegroundColor Yellow
}

# Get GitHub token from environment variable or PowerShell variable
if (-not $GITHUB_TOKEN) {
    $GITHUB_TOKEN = $env:GITHUB_TOKEN
}

# Check if GitHub token is set
if (-not $GITHUB_TOKEN) {
    Write-Host "ERROR: GitHub Personal Access Token is required!" -ForegroundColor Red
    Write-Host "Please create a token at: https://github.com/settings/tokens" -ForegroundColor Yellow
    Write-Host "Then set it using one of these methods:" -ForegroundColor Yellow
    Write-Host '  1. $env:GITHUB_TOKEN = "YOUR_TOKEN"' -ForegroundColor Cyan
    Write-Host '  2. $GITHUB_TOKEN = "YOUR_TOKEN"' -ForegroundColor Cyan
    Write-Host "  3. Use --login-with-github flag (interactive login)" -ForegroundColor Cyan
    Write-Host "" -ForegroundColor Yellow
    Write-Host "Alternatively, you can use interactive GitHub login:" -ForegroundColor Yellow
    Write-Host '  az staticwebapp create --login-with-github ...' -ForegroundColor Cyan
    return
}

Write-Host "Creating Static Web App..." -ForegroundColor Green

# Create Static Web App with GitHub token
az staticwebapp create `
  --name "$NAMING_PREFIX-frontend" `
  --resource-group $RG_COMPUTE `
  --source $GITHUB_REPO_URL `
  --location $LOCATION `
  --branch main `
  --app-location $STATIC_WEB_APP_LOCATION `
  --api-location $STATIC_WEB_API_LOCATION `
  --output-location $STATIC_WEB_OUTPUT_LOCATION `
  --login-with-github

# Alternative: If you prefer to use token directly (not recommended, use --login-with-github instead)
# az staticwebapp create `
#   --name "$NAMING_PREFIX-frontend" `
#   --resource-group $RG_COMPUTE `
#   --source $GITHUB_REPO_URL `
#   --location $LOCATION `
#   --branch main `
#   --app-location $STATIC_WEB_APP_LOCATION `
#   --api-location $STATIC_WEB_API_LOCATION `
#   --output-location $STATIC_WEB_OUTPUT_LOCATION `
#   --sku Free `
#   --token $GITHUB_TOKEN

if ($LASTEXITCODE -ne 0) {
    Write-Host "Static Web App deployment failed!" -ForegroundColor Red
    Write-Host "Check the error message above for details." -ForegroundColor Yellow
    Write-Host "" -ForegroundColor Yellow
    Write-Host "Common issues:" -ForegroundColor Yellow
    Write-Host "  - Invalid or expired GitHub token" -ForegroundColor Yellow
    Write-Host "  - Repository not accessible with the provided token" -ForegroundColor Yellow
    Write-Host "  - Missing 'repo' scope on the token" -ForegroundColor Yellow
    Write-Host "" -ForegroundColor Yellow
    Write-Host "For organization repositories:" -ForegroundColor Yellow
    Write-Host "  - Organization may have PAT restrictions - check with org admin" -ForegroundColor Yellow
    Write-Host "  - PAT may need organization approval - request from org admin" -ForegroundColor Yellow
    Write-Host "  - Try using --login-with-github for interactive authentication" -ForegroundColor Yellow
    Write-Host "  - Verify you have read/write access to the repository" -ForegroundColor Yellow
} else {
    Write-Host "Static Web App deployed successfully!" -ForegroundColor Green
}
```

**Note:** The `--login-with-github` flag will open a browser for interactive authentication. This is the recommended method as it handles token management securely.

---

## Troubleshooting

### Common Errors

#### Error: "Authorization failed for roleAssignments"

**Cause:** You don't have Owner or User Access Administrator role.

**Solution:** 
1. Ask subscription admin to grant you "User Access Administrator" role, OR
2. Skip role assignments in Bicep (already done) and assign manually after deployment (see Post-Deployment Tasks)

#### Error: "Resource group not found"

**Cause:** Resource groups not created or wrong name.

**Solution:**
```powershell
# Verify resource groups exist
az group list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

# Create missing resource groups
az group create --name $RG_NETWORKING --location $LOCATION
```

#### Error: "Subnet not found" or "Key Vault not found"

**Cause:** Dependencies not deployed or outputs not captured.

**Solution:**
```powershell
# Re-capture outputs from previous deployments
$NETWORKING_OUTPUT = az deployment group show --resource-group $RG_NETWORKING --name "networking-*" --query properties.outputs -o json | ConvertFrom-Json
$DATA_SUBNET_ID = $NETWORKING_OUTPUT.dataSubnetId.value

$SECURITY_OUTPUT = az deployment group show --resource-group $RG_SECURITY --name "security-*" --query properties.outputs -o json | ConvertFrom-Json
$KEY_VAULT_NAME = $SECURITY_OUTPUT.keyVaultName.value
```

#### Error: "Deployment validation failed"

**Cause:** Bicep template syntax error or invalid parameters.

**Solution:**
```powershell
# Validate before deploying
az deployment group validate `
  --resource-group $RG_NETWORKING `
  --template-file $BICEP_BASE\networking\vnet.bicep `
  --parameters location=$LOCATION namingPrefix=$NAMING_PREFIX ...
```

#### Error: "MissingSubscriptionRegistration - The subscription is not registered to use namespace 'Microsoft.Web'"

**Cause:** The Azure subscription hasn't registered the `Microsoft.Web` resource provider, which is required for Azure Functions and App Service resources.

**Solution:**
```powershell
# Register the Microsoft.Web provider
az provider register --namespace Microsoft.Web

# Check registration status
az provider show --namespace Microsoft.Web --query "registrationState" -o tsv

# Wait until status shows "Registered" (usually takes 1-2 minutes)
# Then retry your Function App creation command
```

**Note:** The deployment guide now includes automatic provider registration checks before creating Function Apps.

#### Error: "Quota exceeded"

**Cause:** Azure subscription quota limits reached.

**Solution:**
```powershell
# Check quota usage
az vm list-usage --location $LOCATION --output table

# Request quota increase in Azure Portal:
# Subscriptions > Usage + quotas > Search for resource > Request increase
```

### Deployment Status Check

```powershell
# Check deployment status for a resource group
az deployment group list --resource-group $RG_NETWORKING --query "[].{Name:name, State:properties.provisioningState, Timestamp:properties.timestamp}" -o table

# Check failed deployments
az deployment group list --resource-group $RG_NETWORKING --query "[?properties.provisioningState=='Failed'].{Name:name, Error:properties.error.message}" -o json

# View detailed error
az deployment group show --resource-group $RG_NETWORKING --name "DEPLOYMENT_NAME" --query "properties.error" -o json
```

---

## Deployment Summary

After completing all steps, verify all resources:

```powershell
Write-Host "=== Deployment Summary ===" -ForegroundColor Cyan

# Count resources by type
Write-Host "`nResource Groups:" -ForegroundColor Yellow
az group list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nKey Vaults:" -ForegroundColor Yellow
az keyvault list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nStorage Accounts:" -ForegroundColor Yellow
az storage account list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nPostgreSQL Servers:" -ForegroundColor Yellow
az postgres flexible-server list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nRedis Caches:" -ForegroundColor Yellow
az redis list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nAKS Clusters:" -ForegroundColor Yellow
az aks list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nService Bus Namespaces:" -ForegroundColor Yellow
az servicebus namespace list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nData Factories:" -ForegroundColor Yellow
az datafactory list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nCosmos DB Accounts:" -ForegroundColor Yellow
az cosmosdb list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nML Workspaces:" -ForegroundColor Yellow
az ml workspace list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`nAPI Management:" -ForegroundColor Yellow
az apim list --query "[?contains(name, '$NAMING_PREFIX')].name" -o table

Write-Host "`n=== Deployment Complete ===" -ForegroundColor Green
```

---

## Tearing Down the Deployment

If you need to completely remove all deployed resources (e.g., to start fresh with a new location), use the PowerShell destroy script:

### Quick Teardown

```powershell
# Navigate to scripts directory
cd credit-scoring\azure-infrastructure\scripts

# Run destroy script (interactive - will ask for confirmation)
.\destroy.ps1 -Environment "dev" -OrgName "blache" -ProjectName "creditscore"

# Or use -Force flag to skip confirmation (use with caution!)
.\destroy.ps1 -Environment "dev" -OrgName "blache" -ProjectName "creditscore" -Force
```

### What Gets Deleted

The script will:
- Find all resource groups matching `blache-creditscore-dev-*`
- Delete all resource groups (which deletes all resources within them)
- Show Private DNS Zones that will be cleaned up
- Run deletions in background (non-blocking)

### Monitor Deletion Progress

```powershell
# List remaining resource groups
az group list --query "[?contains(name, 'blache-creditscore-dev')].{Name:name, State:properties.provisioningState}" -o table

# Check specific resource group status
az group show --name $RG_NETWORKING --query "properties.provisioningState" -o tsv
```

### After Teardown

Once all resource groups are deleted:
1. Update `$LOCATION` variable to your new region
2. Start deployment from **Phase 1, Step 1.1** (Networking)
3. All resources will be created in the new location

**⚠️ WARNING:** This is **irreversible**. All data, configurations, and resources will be permanently deleted. Make sure you have backups if needed.

---

## Next Steps

1. **Run Test Scripts:** Use the PowerShell test scripts to validate deployments
   ```powershell
   cd credit-scoring\azure-infrastructure\scripts\testing
   .\test-phase-0.ps1 -Environment $ENVIRONMENT -NamingPrefix $NAMING_PREFIX
   ```

2. **Configure Secrets:** Store connection strings and credentials in Key Vault

3. **Deploy Application Code:** Deploy Azure Functions and application containers

4. **Set Up Monitoring:** Configure alerts and dashboards in Application Insights

---

**Document Version:** 1.0  
**Last Updated:** January 2026
