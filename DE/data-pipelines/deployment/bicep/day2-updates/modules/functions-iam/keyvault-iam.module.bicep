targetScope = 'resourceGroup'

@description('Function apps that should receive IAM grants')
param functionApps array

@description('Function app names to exclude from IAM role assignment')
param excludedFunctionAppNames array = []

@description('Key Vault name in this resource group')
param keyVaultName string

var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4633458b-17de-408a-b874-0445c86b69e6'
)
var contributorRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  'b24988ac-6180-42a0-ab88-20f7382dd24c'
)

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultSecretsUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for app in functionApps: if (!contains(excludedFunctionAppNames, app.name)) {
  name: guid(keyVault.id, app.name, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: reference(resourceId(app.resourceGroupName, 'Microsoft.Web/sites', app.name), '2023-12-01', 'Full').identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource keyVaultContributorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for app in functionApps: if (!contains(excludedFunctionAppNames, app.name)) {
  name: guid(keyVault.id, app.name, contributorRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: contributorRoleDefinitionId
    principalId: reference(resourceId(app.resourceGroupName, 'Microsoft.Web/sites', app.name), '2023-12-01', 'Full').identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

