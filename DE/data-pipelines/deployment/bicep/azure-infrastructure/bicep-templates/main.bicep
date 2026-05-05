// ==================================================
// Main Bicep Template - Credit Scoring Platform
// Azure + Agentic AI Implementation
// ==================================================
// This is the main orchestration template that deploys the entire
// credit scoring infrastructure on Azure

targetScope = 'subscription'

// ==================================================
// Parameters
// ==================================================

@description('Environment name (dev, staging, prod)')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string = 'dev'

@description('Primary Azure region for deployment')
param primaryLocation string = 'eastus'

@description('Secondary Azure region for DR')
param secondaryLocation string = 'westus2'

@description('Project name prefix for resource naming')
param projectName string = 'creditscore'

@description('Organization/Company name')
param orgName string = 'payswitch'

@description('Tags to apply to all resources')
param tags object = {
  Project: 'Credit-Scoring-Agentic-AI'
  Environment: environment
  ManagedBy: 'Bicep'
  Owner: 'PaySwitch'
  CostCenter: 'FinTech-Operations'
}

@description('Administrator email for alerts and notifications')
param adminEmail string

@description('Enable Azure Defender and advanced security features')
param enableAdvancedSecurity bool = true

@description('Enable multi-region deployment for DR')
param enableMultiRegion bool = false

@description('Enable Azure OpenAI Service')
param enableOpenAI bool = true

@description('Deploy AKS cluster (optional; off by default in prod unless overridden)')
param deployAks bool = environment != 'prod'

@description('Deploy Azure Machine Learning workspace module (defaults on for all environments)')
param deployMlWorkspace bool = true

@description('Deploy Azure Bastion + a private-subnet Windows jump VM for PE/DNS/RBAC troubleshooting')
param deployJumpBox bool = environment == 'prod'

@description('Admin username for the jump VM Windows OS profile')
param jumpVmAdminUsername string = 'azureuser'

@secure()
@description('Windows jump VM admin password (required when deployJumpBox is true)')
param jumpVmAdminPassword string = ''

@description('VM size for jump host')
param jumpVmSize string = 'Standard_B2s'

// ==================================================
// Variables
// ==================================================

var namingPrefix = '${orgName}-${projectName}-${environment}'
var resourceGroupNames = {
  core: '${namingPrefix}-core-rg'
  networking: '${namingPrefix}-network-rg'
  data: '${namingPrefix}-data-rg'
  compute: '${namingPrefix}-compute-rg'
  ml: '${namingPrefix}-ml-rg'
  security: '${namingPrefix}-security-rg'
  monitoring: '${namingPrefix}-monitoring-rg'
  agents: '${namingPrefix}-agents-rg'
}

// Environment-specific configuration
var environmentConfig = {
  dev: {
    skuTier: 'Basic'
    replicaCount: 1
    enableHA: false
    backupRetentionDays: 7
    aksNodeCount: 2
    aksVMSize: 'Standard_D2s_v3'
    // PostgreSQL Flexible Server SKU names (not legacy Single Server B_Gen5_/GP_Gen5_)
    postgresSkuName: 'Standard_B1ms'
    redisCacheSku: 'Basic'
  }
  staging: {
    skuTier: 'Standard'
    replicaCount: 2
    enableHA: false
    backupRetentionDays: 14
    aksNodeCount: 3
    aksVMSize: 'Standard_D4s_v3'
    postgresSkuName: 'Standard_D2s_v3'
    redisCacheSku: 'Standard'
  }
  prod: {
    skuTier: 'Premium'
    replicaCount: 3
    enableHA: true
    backupRetentionDays: 30
    aksNodeCount: 5
    aksVMSize: 'Standard_D8s_v3'
    postgresSkuName: 'Standard_D4s_v3'
    redisCacheSku: 'Premium'
  }
}

var config = environmentConfig[environment]

// ==================================================
// Resource Groups
// ==================================================

resource coreResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.core
  location: primaryLocation
  tags: tags
}

resource networkingResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.networking
  location: primaryLocation
  tags: tags
}

resource dataResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.data
  location: primaryLocation
  tags: tags
}

resource computeResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.compute
  location: primaryLocation
  tags: tags
}

resource mlResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.ml
  location: primaryLocation
  tags: tags
}

resource securityResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.security
  location: primaryLocation
  tags: tags
}

resource monitoringResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.monitoring
  location: primaryLocation
  tags: tags
}

resource agentsResourceGroup 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: resourceGroupNames.agents
  location: primaryLocation
  tags: tags
}

// ==================================================
// Core Modules
// ==================================================

// Networking Module
module networking './networking/vnet.bicep' = {
  name: 'networking-deployment'
  scope: networkingResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    vnetAddressPrefix: '10.0.0.0/16'
    enableDdosProtection: environment == 'prod'
    tags: tags
  }
}

// Security Module - Key Vault, Managed Identities
module security './security/keyvault.bicep' = {
  name: 'security-deployment'
  scope: securityResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    enablePurgeProtection: environment == 'prod'
    enableAdvancedSecurity: enableAdvancedSecurity
    adminEmail: adminEmail
    tags: tags
  }
}

// Monitoring Module (before ML workspace — workspace references Application Insights)
module monitoring './monitoring/monitoring.bicep' = {
  name: 'monitoring-deployment'
  scope: monitoringResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    adminEmail: adminEmail
    tags: tags
  }
}

// Data Layer Module - Storage, Databases
module dataLayer './data/data-services.bicep' = {
  name: 'data-layer-deployment'
  scope: dataResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    postgresSkuName: config.postgresSkuName
    redisCacheSku: config.redisCacheSku
    backupRetentionDays: config.backupRetentionDays
    enableHA: config.enableHA
    keyVaultName: security.outputs.keyVaultName
    subnetId: networking.outputs.dataSubnetId
    tags: tags
  }
}

// Compute Module - AKS
module compute './compute/aks.bicep' = if (deployAks) {
  name: 'compute-deployment'
  scope: computeResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    nodeCount: config.aksNodeCount
    vmSize: config.aksVMSize
    enableAutoScaling: true
    minNodeCount: config.aksNodeCount
    maxNodeCount: config.aksNodeCount * 2
    vnetSubnetId: networking.outputs.aksSubnetId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsId
    tags: tags
  }
}

// ML Workspace Module
module mlWorkspace './compute/ml-workspace.bicep' = if (deployMlWorkspace) {
  name: 'ml-workspace-deployment'
  scope: mlResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    keyVaultId: security.outputs.keyVaultId
    storageAccountId: dataLayer.outputs.storageAccountId
    applicationInsightsId: monitoring.outputs.applicationInsightsId
    subnetId: networking.outputs.mlSubnetId
    tags: tags
  }
}

// ==================================================
// Bastion + jump VM (private-only operator access path)
// ==================================================

module bastionJump './networking/bastion-jump.bicep' = {
  name: 'bastion-jump-deployment'
  scope: networkingResourceGroup
  params: {
    location: primaryLocation
    namingPrefix: namingPrefix
    bastionSubnetId: networking.outputs.bastionSubnetId
    jumpSubnetId: networking.outputs.jumpSubnetId
    jumpVmAdminUsername: jumpVmAdminUsername
    jumpVmAdminPassword: jumpVmAdminPassword
    jumpVmSize: jumpVmSize
    tags: tags
    deploy: deployJumpBox
  }
}

// ==================================================
// Outputs
// ==================================================

output resourceGroupNames object = resourceGroupNames
output namingPrefix string = namingPrefix
output vnetId string = networking.outputs.vnetId
output aksClusterName string = deployAks ? compute.outputs.aksClusterName : ''
output keyVaultName string = security.outputs.keyVaultName
output mlWorkspaceName string = deployMlWorkspace ? mlWorkspace.outputs.workspaceName : ''
// General-purpose v2 blob account (no hierarchical namespace) — backend / artifacts / models containers
output storageAccountName string = dataLayer.outputs.storageAccountName
output blobStorageAccountName string = dataLayer.outputs.storageAccountName
// ADLS Gen2 — hierarchical namespace (raw / processed / curated)
output dataLakeStorageAccountName string = dataLayer.outputs.dataLakeName
output postgresServerName string = dataLayer.outputs.postgresServerName
output postgresServerFqdn string = dataLayer.outputs.postgresServerFqdn
output redisName string = dataLayer.outputs.redisName
output bastionName string = bastionJump.outputs.bastionHostName
output jumpVmName string = bastionJump.outputs.jumpVmName
