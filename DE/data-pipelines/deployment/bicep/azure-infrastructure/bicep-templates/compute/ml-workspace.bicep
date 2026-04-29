// ==================================================
// Azure Machine Learning Workspace Module
// ==================================================

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Key Vault resource ID')
param keyVaultId string

@description('Storage Account resource ID')
param storageAccountId string

@description('Application Insights resource ID')
param applicationInsightsId string

@description('Subnet resource ID for AML compute (must be in same VNet as the Storage Account when storage has VNet restrictions)')
param subnetId string

@description('Enable GPU compute cluster for deep learning workloads (may require additional vCPU quota)')
param enableGpuCluster bool = false

@description('Workspace SKU name')
@allowed([
  'Basic'
  'Standard'
  'Premium'
])
param workspaceSkuName string = 'Basic'

@description('Resource tags')
param tags object

// ==================================================
// Variables
// ==================================================

var workspaceName = '${namingPrefix}-mlw'

// ==================================================
// Azure Machine Learning Workspace
// ==================================================

resource mlWorkspace 'Microsoft.MachineLearningServices/workspaces@2023-10-01' = {
  name: workspaceName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  sku: {
    name: workspaceSkuName
    tier: workspaceSkuName
  }
  properties: {
    friendlyName: 'Credit Scoring ML Workspace'
    description: 'Machine Learning workspace for credit scoring models and agentic AI'
    keyVault: keyVaultId
    storageAccount: storageAccountId
    applicationInsights: applicationInsightsId
    publicNetworkAccess: 'Enabled'
    hbiWorkspace: true // High Business Impact for sensitive financial data
    v1LegacyMode: false
  }
}

// ==================================================
// Compute Clusters for Training
// ==================================================

// CPU Compute Cluster
resource cpuComputeCluster 'Microsoft.MachineLearningServices/workspaces/computes@2023-10-01' = {
  parent: mlWorkspace
  name: 'cpu-cluster'
  location: location
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: 'Standard_D4s_v3'
      vmPriority: 'Dedicated'
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: 4
        nodeIdleTimeBeforeScaleDown: 'PT5M'
      }
      remoteLoginPortPublicAccess: 'Disabled'
      subnet: {
        id: subnetId
      }
    }
  }
}

// GPU Compute Cluster (for deep learning models)
resource gpuComputeCluster 'Microsoft.MachineLearningServices/workspaces/computes@2023-10-01' = if (enableGpuCluster) {
  parent: mlWorkspace
  name: 'gpu-cluster'
  location: location
  properties: {
    computeType: 'AmlCompute'
    properties: {
      vmSize: 'Standard_NC6s_v3'
      vmPriority: 'LowPriority' // Use low priority for cost savings
      scaleSettings: {
        minNodeCount: 0
        maxNodeCount: 2
        nodeIdleTimeBeforeScaleDown: 'PT5M'
      }
      remoteLoginPortPublicAccess: 'Disabled'
      subnet: {
        id: subnetId
      }
    }
  }
}

// ==================================================
// Compute Instance (for development/notebooks)
// ==================================================

resource computeInstance 'Microsoft.MachineLearningServices/workspaces/computes@2023-10-01' = {
  parent: mlWorkspace
  name: 'dev-compute-instance'
  location: location
  properties: {
    computeType: 'ComputeInstance'
    properties: {
      vmSize: 'Standard_D4s_v3'
      applicationSharingPolicy: 'Personal'
      sshSettings: {
        sshPublicAccess: 'Disabled'
      }
      computeInstanceAuthorizationType: 'personal'
      subnet: {
        id: subnetId
      }
    }
  }
}

// ==================================================
// Datastores (connections to data sources)
// ==================================================

// Note: Datastores are typically created via Azure ML SDK/CLI after workspace deployment
// They connect to the storage account, data lake, and databases

// ==================================================
// Outputs
// ==================================================

output workspaceId string = mlWorkspace.id
output workspaceName string = mlWorkspace.name
output workspacePrincipalId string = mlWorkspace.identity.principalId
output discoveryUrl string = mlWorkspace.properties.discoveryUrl
