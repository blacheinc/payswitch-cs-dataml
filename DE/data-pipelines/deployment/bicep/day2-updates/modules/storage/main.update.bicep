@description('Blob storage account name (non-HNS)')
param blobStorageAccountName string

@description('Data Lake storage account name (HNS enabled)')
param dataLakeStorageAccountName string

@description('Blob containers/filesystems to ensure exist in blob storage account')
param blobContainerNames array = [
  'bronze'
  'silver'
  'curated'
]

@description('Containers/filesystems to ensure exist in ADLS account')
param dataLakeContainerNames array = [
  'bronze'
  'silver'
  'curated'
]

resource blobStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: blobStorageAccountName
}

resource dataLakeStorageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: dataLakeStorageAccountName
}

resource blobServiceBlob 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = {
  parent: blobStorageAccount
  name: 'default'
}

resource blobServiceDls 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' existing = {
  parent: dataLakeStorageAccount
  name: 'default'
}

resource blobContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = [for c in blobContainerNames: {
  parent: blobServiceBlob
  name: c
  properties: {
    publicAccess: 'None'
  }
}]

resource dataLakeContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = [for c in dataLakeContainerNames: {
  parent: blobServiceDls
  name: c
  properties: {
    publicAccess: 'None'
  }
}]

output blobContainersApplied array = [for c in blobContainerNames: c]
output dataLakeContainersApplied array = [for c in dataLakeContainerNames: c]
