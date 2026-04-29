// ==================================================
// MongoDB Deployment Configuration (Azure Cosmos DB MongoDB API)
// Enterprise-Grade Document Database for Application Data
// ==================================================

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Environment (dev, staging, prod)')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string = 'dev'

@description('Resource tags')
param tags object

// ==================================================
// Variables
// ==================================================

var cosmosAccountName = '${namingPrefix}-cosmos-${uniqueString(resourceGroup().id)}'

// Throughput based on environment
var throughput = environment == 'prod' ? 1000 : (environment == 'staging' ? 400 : 400)

// ==================================================
// Azure Cosmos DB Account (MongoDB API)
// ==================================================

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: cosmosAccountName
  location: location
  tags: tags
  kind: 'MongoDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    apiProperties: {
      serverVersion: '4.2'
    }
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: environment == 'prod'
      }
    ]
    backupPolicy: {
      type: 'Periodic'
      periodicModeProperties: {
        backupIntervalInMinutes: 240  // 4 hours
        backupRetentionIntervalInHours: environment == 'prod' ? 720 : 168  // 30 days prod, 7 days dev
        backupStorageRedundancy: environment == 'prod' ? 'Geo' : 'Local'
      }
    }
    enableAutomaticFailover: environment == 'prod'
    enableMultipleWriteLocations: false
    enableFreeTier: false
    publicNetworkAccess: 'Enabled'
    networkAclBypass: 'AzureServices'
    capabilities: [
      {
        name: 'EnableMongo'
      }
      {
        name: 'DisableRateLimitingResponses'
      }
    ]
  }
}

// ==================================================
// MongoDB Databases
// ==================================================

resource creditScoringDatabase 'Microsoft.DocumentDB/databaseAccounts/mongodbDatabases@2023-04-15' = {
  parent: cosmosAccount
  name: 'credit_scoring'
  properties: {
    resource: {
      id: 'credit_scoring'
    }
    options: {
      throughput: throughput
    }
  }
}

// ==================================================
// MongoDB Collections
// ==================================================

// Applications Collection
resource applicationsCollection 'Microsoft.DocumentDB/databaseAccounts/mongodbDatabases/collections@2023-04-15' = {
  parent: creditScoringDatabase
  name: 'applications'
  properties: {
    resource: {
      id: 'applications'
      shardKey: {
        applicant_id: 'Hash'
      }
      indexes: [
        {
          key: {
            keys: ['_id']
          }
        }
        {
          key: {
            keys: ['applicant_id']
          }
        }
        {
          key: {
            keys: ['application_status']
          }
        }
        {
          key: {
            keys: ['submitted_at']
          }
        }
      ]
    }
  }
}

// Feature Store Collection
resource featureStoreCollection 'Microsoft.DocumentDB/databaseAccounts/mongodbDatabases/collections@2023-04-15' = {
  parent: creditScoringDatabase
  name: 'feature_store'
  properties: {
    resource: {
      id: 'feature_store'
      shardKey: {
        record_id: 'Hash'
      }
      indexes: [
        {
          key: {
            keys: ['_id']
          }
        }
        {
          key: {
            keys: ['record_id']
          }
        }
        {
          key: {
            keys: ['feature_hash']
          }
        }
        {
          key: {
            keys: ['timestamp']
          }
        }
      ]
    }
  }
}

// Agent State Collection
resource agentStateCollection 'Microsoft.DocumentDB/databaseAccounts/mongodbDatabases/collections@2023-04-15' = {
  parent: creditScoringDatabase
  name: 'agent_state'
  properties: {
    resource: {
      id: 'agent_state'
      shardKey: {
        agent_name: 'Hash'
      }
      indexes: [
        {
          key: {
            keys: ['_id']
          }
        }
        {
          key: {
            keys: ['agent_name']
          }
        }
        {
          key: {
            keys: ['last_updated']
          }
        }
      ]
    }
  }
}

// ==================================================
// Diagnostic Settings
// ==================================================
// NOTE: Diagnostic settings are managed centrally via the diagnostic-settings.bicep module
// This ensures consistent monitoring configuration and avoids "data sink" errors
// See: azure-infrastructure/bicep-templates/monitoring/diagnostic-settings.bicep

// resource cosmosDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
//   name: '${cosmosAccountName}-diagnostics'
//   scope: cosmosAccount
//   properties: {
//     workspaceId: logAnalyticsWorkspaceId  // Would need to be passed as parameter
//     logs: [
//       {
//         category: 'DataPlaneRequests'
//         enabled: true
//       }
//       {
//         category: 'MongoRequests'
//         enabled: true
//       }
//       {
//         category: 'QueryRuntimeStatistics'
//         enabled: true
//       }
//     ]
//     metrics: [
//       {
//         category: 'Requests'
//         enabled: true
//       }
//     ]
//   }
// }

// ==================================================
// Outputs
// ==================================================

output cosmosAccountId string = cosmosAccount.id
output cosmosAccountName string = cosmosAccount.name
output mongoConnectionString string = cosmosAccount.listConnectionStrings().connectionStrings[0].connectionString
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = creditScoringDatabase.name
