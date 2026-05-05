targetScope = 'subscription'

@description('ADF factory name')
param dataFactoryName string

@description('Resource group hosting ADF factory')
param dataFactoryResourceGroupName string

@description('Blob storage account name')
param blobStorageAccountName string

@description('Data Lake storage account name')
param dataLakeStorageAccountName string

@description('Resource group hosting storage accounts')
param storageResourceGroupName string

@description('Key Vault name')
param keyVaultName string

@description('Resource group hosting Key Vault')
param keyVaultResourceGroupName string

@description('Service Bus namespace name')
param serviceBusNamespaceName string

@description('Resource group hosting Service Bus namespace')
param serviceBusResourceGroupName string

var blobDataContributorRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)
var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)
var serviceBusDataSenderRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
)
var serviceBusDataReceiverRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
)

resource blobStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  scope: resourceGroup(storageResourceGroupName)
  name: blobStorageAccountName
}

resource dataLakeStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  scope: resourceGroup(storageResourceGroupName)
  name: dataLakeStorageAccountName
}

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  scope: resourceGroup(keyVaultResourceGroupName)
  name: keyVaultName
}

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  scope: resourceGroup(serviceBusResourceGroupName)
  name: serviceBusNamespaceName
}

var adfPrincipalId = reference(
  resourceId(dataFactoryResourceGroupName, 'Microsoft.DataFactory/factories', dataFactoryName),
  '2018-06-01',
  'Full'
).identity.principalId

resource adfBlobContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(blobStorageAccount.id, dataFactoryName, blobDataContributorRoleDefinitionId)
  scope: blobStorageAccount
  properties: {
    roleDefinitionId: blobDataContributorRoleDefinitionId
    principalId: adfPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource adfDataLakeContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (toLower(dataLakeStorageAccountName) != toLower(blobStorageAccountName)) {
  name: guid(dataLakeStorageAccount.id, dataFactoryName, blobDataContributorRoleDefinitionId)
  scope: dataLakeStorageAccount
  properties: {
    roleDefinitionId: blobDataContributorRoleDefinitionId
    principalId: adfPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource adfKeyVaultSecretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, dataFactoryName, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: adfPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource adfServiceBusSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, dataFactoryName, serviceBusDataSenderRoleDefinitionId)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: serviceBusDataSenderRoleDefinitionId
    principalId: adfPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource adfServiceBusReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBusNamespace.id, dataFactoryName, serviceBusDataReceiverRoleDefinitionId)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: serviceBusDataReceiverRoleDefinitionId
    principalId: adfPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output adfPrincipalId string = adfPrincipalId
