targetScope = 'resourceGroup'

@description('Function apps that should receive IAM grants')
param functionApps array

@description('Function app names to exclude from IAM role assignment')
param excludedFunctionAppNames array = []

@description('Storage account name in this resource group')
param storageAccountName string

var blobDataContributorRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
)

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: storageAccountName
}

resource blobContributorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for app in functionApps: if (!contains(excludedFunctionAppNames, app.name)) {
  name: guid(storageAccount.id, app.name, blobDataContributorRoleDefinitionId)
  scope: storageAccount
  properties: {
    roleDefinitionId: blobDataContributorRoleDefinitionId
    principalId: reference(resourceId(app.resourceGroupName, 'Microsoft.Web/sites', app.name), '2023-12-01', 'Full').identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

