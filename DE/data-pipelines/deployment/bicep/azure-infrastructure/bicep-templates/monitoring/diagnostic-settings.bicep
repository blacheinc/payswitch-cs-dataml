// ==================================================
// Centralized Diagnostic Settings Module
// Creates diagnostic settings for all Phase 1 & 2 resources
// ==================================================

@description('Log Analytics Workspace ID (required)')
param logAnalyticsWorkspaceId string

@description('Storage Account ID (optional - leave empty to skip)')
param storageAccountId string = ''

@description('Data Lake Storage Account ID (optional - leave empty to skip)')
param dataLakeId string = ''

@description('PostgreSQL Server ID (optional - leave empty to skip)')
param postgresServerId string = ''

@description('Redis Cache ID (optional - leave empty to skip)')
param redisId string = ''

@description('Key Vault ID (optional - leave empty to skip)')
param keyVaultId string = ''

@description('Service Bus Namespace ID (optional - leave empty to skip)')
param serviceBusNamespaceId string = ''

@description('Cosmos DB Account ID (optional - leave empty to skip)')
param cosmosAccountId string = ''

// ==================================================
// Storage Account Diagnostics
// ==================================================

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' existing = if (!empty(storageAccountId)) {
  name: split(storageAccountId, '/')[8]
}

resource storageAccountDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(storageAccountId)) {
  name: 'storage-account-diagnostics'
  scope: storageAccount
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'StorageRead'
        enabled: true
      }
      {
        category: 'StorageWrite'
        enabled: true
      }
      {
        category: 'StorageDelete'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

// ==================================================
// Data Lake Storage Gen2 Diagnostics
// ==================================================

resource dataLake 'Microsoft.Storage/storageAccounts@2023-01-01' existing = if (!empty(dataLakeId)) {
  name: split(dataLakeId, '/')[8]
}

resource dataLakeDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(dataLakeId)) {
  name: 'data-lake-diagnostics'
  scope: dataLake
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'StorageRead'
        enabled: true
      }
      {
        category: 'StorageWrite'
        enabled: true
      }
      {
        category: 'StorageDelete'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

// ==================================================
// PostgreSQL Flexible Server Diagnostics
// ==================================================

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' existing = if (!empty(postgresServerId)) {
  name: split(postgresServerId, '/')[8]
}

resource postgresDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(postgresServerId)) {
  name: 'postgres-diagnostics'
  scope: postgresServer
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'PostgreSQLLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ==================================================
// Redis Cache Diagnostics
// ==================================================

resource redisCache 'Microsoft.Cache/redis@2023-04-01' existing = if (!empty(redisId)) {
  name: split(redisId, '/')[8]
}

resource redisDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(redisId)) {
  name: 'redis-diagnostics'
  scope: redisCache
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ==================================================
// Key Vault Diagnostics
// ==================================================

resource keyVault 'Microsoft.KeyVault/vaults@2023-02-01' existing = if (!empty(keyVaultId)) {
  name: split(keyVaultId, '/')[8]
}

resource keyVaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(keyVaultId)) {
  name: 'key-vault-diagnostics'
  scope: keyVault
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'AuditEvent'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ==================================================
// Service Bus Diagnostics
// ==================================================

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = if (!empty(serviceBusNamespaceId)) {
  name: split(serviceBusNamespaceId, '/')[8]
}

resource serviceBusDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(serviceBusNamespaceId)) {
  name: 'service-bus-diagnostics'
  scope: serviceBusNamespace
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'OperationalLogs'
        enabled: true
      }
      {
        category: 'RuntimeAuditLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ==================================================
// Cosmos DB Diagnostics
// ==================================================

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' existing = if (!empty(cosmosAccountId)) {
  name: split(cosmosAccountId, '/')[8]
}

resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (!empty(cosmosAccountId)) {
  name: 'cosmos-db-diagnostics'
  scope: cosmosAccount
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      {
        category: 'DataPlaneRequests'
        enabled: true
      }
      {
        category: 'QueryRuntimeStatistics'
        enabled: true
      }
      {
        category: 'PartitionKeyStatistics'
        enabled: true
      }
      {
        category: 'ControlPlaneRequests'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// ==================================================
// Outputs
// ==================================================

var settingsArray = union(
  (!empty(storageAccountId) ? ['Storage Account'] : []),
  (!empty(dataLakeId) ? ['Data Lake'] : []),
  (!empty(postgresServerId) ? ['PostgreSQL'] : []),
  (!empty(redisId) ? ['Redis'] : []),
  (!empty(keyVaultId) ? ['Key Vault'] : []),
  (!empty(serviceBusNamespaceId) ? ['Service Bus'] : []),
  (!empty(cosmosAccountId) ? ['Cosmos DB'] : [])
)

output diagnosticSettingsCreated array = settingsArray
