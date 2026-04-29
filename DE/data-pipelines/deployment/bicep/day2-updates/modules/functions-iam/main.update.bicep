targetScope = 'subscription'

@description('Function apps that should receive IAM grants')
param functionApps array

@description('Function app names to exclude from IAM role assignment')
param excludedFunctionAppNames array = []

@description('Blob storage account name')
param blobStorageAccountName string

@description('Data Lake storage account name')
param dataLakeStorageAccountName string

@description('Resource group hosting blob/data lake accounts')
param storageResourceGroupName string

@description('Key Vault name')
param keyVaultName string

@description('Resource group hosting Key Vault')
param keyVaultResourceGroupName string

@description('Service Bus namespace name for data-plane role assignments')
param serviceBusNamespaceName string = ''

@description('Resource group hosting Service Bus namespace')
param serviceBusResourceGroupName string = ''

var assignServiceBusRoles = !empty(serviceBusNamespaceName) && !empty(serviceBusResourceGroupName)
module blobStorageIam './storage-iam.module.bicep' = {
  name: 'functions-blob-storage-iam'
  scope: resourceGroup(storageResourceGroupName)
  params: {
    functionApps: functionApps
    excludedFunctionAppNames: excludedFunctionAppNames
    storageAccountName: blobStorageAccountName
  }
}

module dataLakeStorageIam './storage-iam.module.bicep' = if (toLower(dataLakeStorageAccountName) != toLower(blobStorageAccountName)) {
  name: 'functions-datalake-storage-iam'
  scope: resourceGroup(storageResourceGroupName)
  params: {
    functionApps: functionApps
    excludedFunctionAppNames: excludedFunctionAppNames
    storageAccountName: dataLakeStorageAccountName
  }
}

module keyVaultIam './keyvault-iam.module.bicep' = {
  name: 'functions-keyvault-iam'
  scope: resourceGroup(keyVaultResourceGroupName)
  params: {
    functionApps: functionApps
    excludedFunctionAppNames: excludedFunctionAppNames
    keyVaultName: keyVaultName
  }
}

module serviceBusIam './servicebus-iam.module.bicep' = if (assignServiceBusRoles) {
  name: 'functions-servicebus-iam'
  scope: resourceGroup(serviceBusResourceGroupName)
  params: {
    functionApps: functionApps
    excludedFunctionAppNames: excludedFunctionAppNames
    serviceBusNamespaceName: serviceBusNamespaceName
  }
}

output iamFunctionApps array = [for app in functionApps: app.name]
