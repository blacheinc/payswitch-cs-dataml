// ==================================================
// AKS (Azure Kubernetes Service) Module
// ==================================================

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Initial node count')
param nodeCount int = 3

@description('VM size for nodes')
param vmSize string = 'Standard_D4s_v3'

@description('Enable autoscaling')
param enableAutoScaling bool = true

@description('Minimum node count for autoscaling')
param minNodeCount int = 3

@description('Maximum node count for autoscaling')
param maxNodeCount int = 10

@description('VNet subnet ID for AKS')
param vnetSubnetId string

@description('Kubernetes version (e.g., 1.27.10). If not specified, deployment script will query for latest supported non-LTS version.')
param kubernetesVersion string = '1.27.10' // Default to 1.27.x (non-LTS); override via deployment script

@description('Log Analytics Workspace resource ID (required for omsagent addon)')
param logAnalyticsWorkspaceId string

@description('Availability zones for node pools (empty array if region does not support zones, e.g., eastus2)')
param availabilityZones array = []

@description('Resource tags')
param tags object

// ==================================================
// Variables
// ==================================================

var aksClusterName = '${namingPrefix}-aks'
var nodePoolName = 'nodepool1'
var dnsPrefix = '${namingPrefix}-aks-dns'
var useAvailabilityZones = length(availabilityZones) > 0

// ==================================================
// AKS Cluster
// ==================================================

resource aksCluster 'Microsoft.ContainerService/managedClusters@2023-10-01' = {
  name: aksClusterName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    dnsPrefix: dnsPrefix
    kubernetesVersion: kubernetesVersion
    enableRBAC: true
    networkProfile: {
      networkPlugin: 'azure'
      networkPolicy: 'azure'
      serviceCidr: '172.16.0.0/16'
      dnsServiceIP: '172.16.0.10'
      loadBalancerSku: 'standard'
    }
    agentPoolProfiles: [
      {
        name: nodePoolName
        count: nodeCount
        vmSize: vmSize
        osDiskSizeGB: 128
        osDiskType: 'Managed'
        osType: 'Linux'
        mode: 'System'
        type: 'VirtualMachineScaleSets'
        vnetSubnetID: vnetSubnetId
        enableAutoScaling: enableAutoScaling
        minCount: enableAutoScaling ? minNodeCount : null
        maxCount: enableAutoScaling ? maxNodeCount : null
        availabilityZones: useAvailabilityZones ? availabilityZones : []
        enableNodePublicIP: false
      }
    ]
    addonProfiles: {
      azureKeyvaultSecretsProvider: {
        enabled: true
        config: {
          enableSecretRotation: 'true'
          rotationPollInterval: '2m'
        }
      }
      azurepolicy: {
        enabled: true
      }
      omsagent: {
        enabled: true
        config: {
          logAnalyticsWorkspaceResourceID: logAnalyticsWorkspaceId
        }
      }
    }
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
    }
    apiServerAccessProfile: {
      enablePrivateCluster: false // Set to true for production with private endpoints
    }
  }
}

// ==================================================
// Additional Node Pools (GPU for ML workloads - optional)
// ==================================================

resource gpuNodePool 'Microsoft.ContainerService/managedClusters/agentPools@2023-10-01' = {
  parent: aksCluster
  name: 'gpupool'
  properties: {
    count: 0 // Start with 0, scale up when needed
    vmSize: 'Standard_NC6s_v3' // GPU-enabled VM
    osDiskSizeGB: 128
    osDiskType: 'Managed'
    osType: 'Linux'
    mode: 'User'
    type: 'VirtualMachineScaleSets'
    vnetSubnetID: vnetSubnetId
    enableAutoScaling: true
    minCount: 0
    maxCount: 3
    availabilityZones: useAvailabilityZones ? availabilityZones : []
    enableNodePublicIP: false
    nodeTaints: [
      'sku=gpu:NoSchedule'
    ]
    nodeLabels: {
      workload: 'gpu'
    }
  }
}

// ==================================================
// Role Assignments
// ==================================================

// NOTE: Role assignments require "Owner" or "User Access Administrator" role.
// If you only have "Contributor" role, comment out this section and assign roles manually after deployment.

// Grant AKS access to the VNet
// resource aksVnetRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
//   name: guid(aksCluster.id, vnetSubnetId, 'Network Contributor')
//   scope: resourceGroup()
//   properties: {
//     roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7') // Network Contributor
//     principalId: aksCluster.identity.principalId
//     principalType: 'ServicePrincipal'
//   }
// }

// ==================================================
// Container Registry
// ==================================================

resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: replace('${namingPrefix}acr${uniqueString(resourceGroup().id)}', '-', '')
  location: location
  tags: tags
  sku: {
    name: 'Premium' // Premium for VNet integration and geo-replication
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
    networkRuleBypassOptions: 'AzureServices'
    zoneRedundancy: 'Enabled'
  }
}

// NOTE: Role assignments require "Owner" or "User Access Administrator" role.
// If you only have "Contributor" role, comment out this section and assign roles manually after deployment.

// Grant AKS pull access to ACR
// resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
//   name: guid(containerRegistry.id, aksCluster.id, 'AcrPull')
//   scope: containerRegistry
//   properties: {
//     roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
//     principalId: aksCluster.properties.identityProfile.kubeletidentity.objectId
//     principalType: 'ServicePrincipal'
//   }
// }

// ==================================================
// Outputs
// ==================================================

output aksClusterId string = aksCluster.id
output aksClusterName string = aksCluster.name
output aksClusterFqdn string = aksCluster.properties.fqdn
output aksIdentityPrincipalId string = aksCluster.identity.principalId
output aksKubeletIdentityObjectId string = aksCluster.properties.identityProfile.kubeletidentity.objectId
output containerRegistryId string = containerRegistry.id
output containerRegistryName string = containerRegistry.name
output containerRegistryLoginServer string = containerRegistry.properties.loginServer
