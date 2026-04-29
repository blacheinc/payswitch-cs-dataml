// ==================================================
// Security Module - Key Vault, Managed Identities
// ==================================================

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Enable purge protection (required for production)')
param enablePurgeProtection bool = false

@description('Enable advanced security features')
param enableAdvancedSecurity bool = true

@description('Administrator email for security alerts')
param adminEmail string

@description('Enable private networking posture (disable public Key Vault access)')
param privateNetworkMode bool = false

@description('Resource tags')
param tags object

// NOTE: logAnalyticsWorkspaceId parameter removed - diagnostic settings moved to centralized module
// See: bicep-templates/monitoring/diagnostic-settings.bicep

// ==================================================
// Variables
// ==================================================

// Key Vault names must be 3-24 characters, alphanumeric, no consecutive hyphens
// Extract org name (first part before first hyphen) and use shorter hash
// Format: <org>kv<hash> = e.g., "blachekv<10-char-hash>" = ~18 characters
var orgName = split(namingPrefix, '-')[0]
var uniqueHash = substring(uniqueString(resourceGroup().id), 0, 10)
var keyVaultName = '${orgName}kv${uniqueHash}'
var managedIdentityName = '${namingPrefix}-identity'

// ==================================================
// Managed Identity
// ==================================================

resource managedIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: tags
}

// ==================================================
// Key Vault
// ==================================================

resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    sku: {
      family: 'A'
      name: enableAdvancedSecurity ? 'premium' : 'standard'
    }
    tenantId: subscription().tenantId
    enabledForDeployment: true
    enabledForDiskEncryption: true
    enabledForTemplateDeployment: true
    enablePurgeProtection: enablePurgeProtection ? true : null
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enableRbacAuthorization: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: []
      virtualNetworkRules: []
    }
    publicNetworkAccess: privateNetworkMode ? 'Disabled' : 'Enabled'
  }
}

// ==================================================
// Key Vault Diagnostic Settings
// ==================================================
// NOTE: Diagnostic settings have been moved to centralized module
// See: bicep-templates/monitoring/diagnostic-settings.bicep
// This ensures all diagnostics are managed in one place and avoids
// dependency issues between modules.

// resource keyVaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
//   name: '${keyVaultName}-diagnostics'
//   scope: keyVault
//   properties: {
//     workspaceId: logAnalyticsWorkspaceId
//     logs: [
//       {
//         category: 'AuditEvent'
//         enabled: true
//       }
//     ]
//     metrics: [
//       {
//         category: 'AllMetrics'
//         enabled: true
//       }
//     ]
//   }
// }

// ==================================================
// Key Vault Secrets (Placeholders)
// ==================================================

resource postgresPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'postgres-admin-password'
  properties: {
    value: 'PLACEHOLDER-${uniqueString(resourceGroup().id, 'postgres')}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource redisPasswordSecret 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'redis-password'
  properties: {
    value: 'PLACEHOLDER-${uniqueString(resourceGroup().id, 'redis')}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource mongoConnectionSecret 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'mongodb-connection-string'
  properties: {
    value: 'PLACEHOLDER-${uniqueString(resourceGroup().id, 'mongo')}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource apiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'api-secret-key'
  properties: {
    value: 'PLACEHOLDER-${uniqueString(resourceGroup().id, 'api')}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

resource openAIKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-02-01' = {
  parent: keyVault
  name: 'azure-openai-key'
  properties: {
    value: 'PLACEHOLDER-${uniqueString(resourceGroup().id, 'openai')}'
    contentType: 'text/plain'
    attributes: {
      enabled: true
    }
  }
}

// ==================================================
// RBAC Role Assignments
// ==================================================

// NOTE: Role assignments require "Owner" or "User Access Administrator" role.
// If you only have "Contributor" role, comment out this section and assign roles manually after deployment.
// To assign manually: az role assignment create --role "Key Vault Secrets User" --assignee <managed-identity-principal-id> --scope <key-vault-id>

// Grant the managed identity Key Vault Secrets User role
// resource keyVaultSecretsUserRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
//   name: guid(keyVault.id, managedIdentity.id, 'SecretsUser')
//   scope: keyVault
//   properties: {
//     roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
//     principalId: managedIdentity.properties.principalId
//     principalType: 'ServicePrincipal'
//   }
// }

// ==================================================
// Security Alert Action Group
// ==================================================

resource securityActionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${namingPrefix}-security-alerts'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'SecAlerts'
    enabled: true
    emailReceivers: [
      {
        name: 'SecurityTeam'
        emailAddress: adminEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

// ==================================================
// Outputs
// ==================================================

output keyVaultId string = keyVault.id
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
output managedIdentityId string = managedIdentity.id
output managedIdentityPrincipalId string = managedIdentity.properties.principalId
output managedIdentityClientId string = managedIdentity.properties.clientId
output securityActionGroupId string = securityActionGroup.id
