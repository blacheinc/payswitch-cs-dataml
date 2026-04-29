@description('Key Vault name')
param keyVaultName string

@description('Function app principal IDs to grant Key Vault Secrets User')
param keyVaultSecretsUserPrincipalIds array = []

@description('Function app principal IDs to grant Contributor')
param contributorPrincipalIds array = []

var contributorRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b24988ac-6180-42a0-ab88-20f7382dd24c')
var keyVaultSecretsUserRoleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource keyVaultSecretsUserAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in keyVaultSecretsUserPrincipalIds: {
  name: guid(keyVault.id, principalId, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: keyVaultSecretsUserRoleDefinitionId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource contributorAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in contributorPrincipalIds: {
  name: guid(keyVault.id, principalId, contributorRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: contributorRoleDefinitionId
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output keyVaultRoleAssignmentCount int = length(keyVaultSecretsUserAssignments) + length(contributorAssignments)
