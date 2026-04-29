// ==================================================
// Enhanced Data Services Module
// PostgreSQL with Geo-Redundancy, Private Endpoints, and Advanced Backup
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

@description('PostgreSQL SKU name')
param postgresSkuName string = environment == 'prod' ? 'GP_Standard_D4s_v3' : 'GP_Standard_D2s_v3'

@description('Redis Cache SKU')
param redisCacheSku string = environment == 'prod' ? 'Premium' : 'Standard'

@description('Backup retention days')
param backupRetentionDays int = environment == 'prod' ? 35 : 7

@description('Enable High Availability (Zone Redundancy)')
param enableHA bool = environment == 'prod'

@description('Enable Geo-Redundant Backups (always enabled for prod)')
param enableGeoRedundantBackup bool = environment == 'prod'

@description('Enable Private Endpoints (recommended for prod)')
param enablePrivateEndpoints bool = environment == 'prod'

@description('Key Vault name for secret storage')
param keyVaultName string

@description('Data subnet ID for private endpoints')
param dataSubnetId string

@description('Private endpoints subnet ID')
param privateEndpointsSubnetId string

@description('Resource tags')
param tags object

@description('Virtual Network ID for private DNS zones')
param vnetId string

// ==================================================
// Variables
// ==================================================

var postgresServerName = '${namingPrefix}-postgres-${uniqueString(resourceGroup().id)}'
var redisName = '${namingPrefix}-redis-${uniqueString(resourceGroup().id)}'
var storageAccountName = replace('${namingPrefix}st${uniqueString(resourceGroup().id)}', '-', '')
var dataLakeName = replace('${namingPrefix}dl${uniqueString(resourceGroup().id)}', '-', '')

// Storage SKU based on environment
var storageAccountSku = environment == 'prod' ? 'Standard_GRS' : 'Standard_LRS'
var dataLakeSku = environment == 'prod' ? 'Standard_GRS' : 'Standard_LRS'

// Administrator credentials
var postgresAdminUser = 'csadmin'
var postgresAdminPassword = '${uniqueString(resourceGroup().id, 'postgres')}!Aa1' // This should be rotated

// ==================================================
// Storage Account (General Purpose) - Enhanced
// ==================================================

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: storageAccountSku
  }
  kind: 'StorageV2'
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_3'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: environment == 'prod' ? false : true // Enforce Azure AD auth in prod
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: enablePrivateEndpoints ? 'Deny' : 'Allow'
      virtualNetworkRules: !enablePrivateEndpoints ? [
        {
          id: dataSubnetId
          action: 'Allow'
        }
      ] : []
    }
    encryption: {
      services: {
        blob: {
          enabled: true
        }
        file: {
          enabled: true
        }
      }
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: environment == 'prod'
    }
  }
}

// Blob service with advanced features
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: environment == 'prod' ? 30 : 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: environment == 'prod' ? 30 : 7
    }
    isVersioningEnabled: environment == 'prod'
    changeFeed: {
      enabled: environment == 'prod'
      retentionInDays: environment == 'prod' ? 90 : null
    }
  }
}

// Containers
resource modelsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'models'
  properties: {
    publicAccess: 'None'
  }
}

resource artifactsContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'artifacts'
  properties: {
    publicAccess: 'None'
  }
}

resource dataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: blobService
  name: 'data'
  properties: {
    publicAccess: 'None'
  }
}

// ==================================================
// Data Lake Storage Gen2 - Enhanced
// ==================================================

resource dataLake 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: dataLakeName
  location: location
  tags: tags
  sku: {
    name: dataLakeSku
  }
  kind: 'StorageV2'
  properties: {
    isHnsEnabled: true // Hierarchical namespace for Data Lake Gen2
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_3'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: environment == 'prod' ? false : true
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: enablePrivateEndpoints ? 'Deny' : 'Allow'
      virtualNetworkRules: !enablePrivateEndpoints ? [
        {
          id: dataSubnetId
          action: 'Allow'
        }
      ] : []
    }
    encryption: {
      services: {
        blob: {
          enabled: true
        }
        file: {
          enabled: true
        }
      }
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: environment == 'prod'
    }
  }
}

// Data Lake containers (file systems)
resource dataLakeBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: dataLake
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: environment == 'prod' ? 30 : 7
    }
    isVersioningEnabled: environment == 'prod'
  }
}

resource rawDataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: dataLakeBlobService
  name: 'raw'
  properties: {
    publicAccess: 'None'
  }
}

resource processedDataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: dataLakeBlobService
  name: 'processed'
  properties: {
    publicAccess: 'None'
  }
}

resource curatedDataContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = {
  parent: dataLakeBlobService
  name: 'curated'
  properties: {
    publicAccess: 'None'
  }
}

// ==================================================
// Azure Database for PostgreSQL - Enhanced with Geo-Redundancy
// ==================================================

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: postgresServerName
  location: location
  tags: union(tags, {
    'geo-redundancy': enableGeoRedundantBackup ? 'enabled' : 'disabled'
    'backup-retention-days': string(backupRetentionDays)
  })
  sku: {
    name: postgresSkuName
    tier: startsWith(postgresSkuName, 'B_') ? 'Burstable' : 'GeneralPurpose'
  }
  properties: {
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    version: '14'
    storage: {
      storageSizeGB: environment == 'prod' ? 256 : 128
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: enableGeoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    highAvailability: enableHA ? {
      mode: 'ZoneRedundant'
      standbyAvailabilityZone: '2'
    } : {
      mode: 'Disabled'
    }
    network: {
      publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    }
    maintenanceWindow: {
      customWindow: 'Enabled'
      dayOfWeek: 0 // Sunday
      startHour: 2
      startMinute: 0
    }
  }
}

// PostgreSQL Databases
resource creditScoringDB 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: postgresServer
  name: 'credit_scoring'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource metadataDB 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: postgresServer
  name: 'metadata'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

resource mlflowDB 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2022-12-01' = {
  parent: postgresServer
  name: 'mlflow'
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
}

// PostgreSQL firewall rule (allow Azure services) - only if not using private endpoints
resource postgresFirewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = if (!enablePrivateEndpoints) {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ==================================================
// Azure Cache for Redis - Enhanced
// ==================================================

resource redis 'Microsoft.Cache/redis@2023-08-01' = {
  name: redisName
  location: location
  tags: tags
  properties: {
    sku: {
      name: redisCacheSku
      family: redisCacheSku == 'Premium' ? 'P' : 'C'
      capacity: redisCacheSku == 'Premium' ? 1 : 1
    }
    enableNonSslPort: false
    minimumTlsVersion: '1.3'
    publicNetworkAccess: enablePrivateEndpoints ? 'Disabled' : 'Enabled'
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
      'maxmemory-reserved': redisCacheSku == 'Premium' ? '200' : '50'
      'maxfragmentationmemory-reserved': redisCacheSku == 'Premium' ? '200' : '50'
    }
    redisVersion: '6'
    // Data persistence for Premium tier
    ...(redisCacheSku == 'Premium' ? {
      replicasPerMaster: 1
      shardCount: 1
    } : {})
  }
  zones: redisCacheSku == 'Premium' && environment == 'prod' ? ['1', '2', '3'] : null
}

// ==================================================
// Private Endpoints (Production)
// ==================================================

// Private DNS Zones
resource privateStorageDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (enablePrivateEndpoints) {
  name: 'privatelink.blob.${az.environment().suffixes.storage}'
  location: 'global'
  tags: tags
}

resource privateDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (enablePrivateEndpoints) {
  parent: privateStorageDnsZone
  name: '${namingPrefix}-storage-dns-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

resource privatePostgresDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (enablePrivateEndpoints) {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource privatePostgresDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (enablePrivateEndpoints) {
  parent: privatePostgresDnsZone
  name: '${namingPrefix}-postgres-dns-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

// Private Endpoint for Storage Account
resource storagePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if (enablePrivateEndpoints) {
  name: '${storageAccountName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${storageAccountName}-connection'
        properties: {
          privateLinkServiceId: storageAccount.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource storagePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-05-01' = if (enablePrivateEndpoints) {
  parent: storagePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'config1'
        properties: {
          privateDnsZoneId: privateStorageDnsZone.id
        }
      }
    ]
  }
}

// Private Endpoint for Data Lake
resource dataLakePrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if (enablePrivateEndpoints) {
  name: '${dataLakeName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${dataLakeName}-connection'
        properties: {
          privateLinkServiceId: dataLake.id
          groupIds: [
            'blob'
          ]
        }
      }
    ]
  }
}

resource dataLakePrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-05-01' = if (enablePrivateEndpoints) {
  parent: dataLakePrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'config1'
        properties: {
          privateDnsZoneId: privateStorageDnsZone.id
        }
      }
    ]
  }
}

// Private Endpoint for PostgreSQL
resource postgresPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = if (enablePrivateEndpoints) {
  name: '${postgresServerName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${postgresServerName}-connection'
        properties: {
          privateLinkServiceId: postgresServer.id
          groupIds: [
            'postgresqlServer'
          ]
        }
      }
    ]
  }
}

resource postgresPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-05-01' = if (enablePrivateEndpoints) {
  parent: postgresPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'config1'
        properties: {
          privateDnsZoneId: privatePostgresDnsZone.id
        }
      }
    ]
  }
}

// ==================================================
// Diagnostic Settings
// ==================================================

resource storageAccountDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${storageAccountName}-diagnostics'
  scope: storageAccount
  properties: {
    metrics: [
      {
        category: 'Transaction'
        enabled: true
        retentionPolicy: {
          enabled: true
          days: 90
        }
      }
    ]
  }
}

resource postgresDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${postgresServerName}-diagnostics'
  scope: postgresServer
  properties: {
    logs: [
      {
        category: 'PostgreSQLLogs'
        enabled: true
        retentionPolicy: {
          enabled: true
          days: 90
        }
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          enabled: true
          days: 90
        }
      }
    ]
  }
}

resource redisDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: '${redisName}-diagnostics'
  scope: redis
  properties: {
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
        retentionPolicy: {
          enabled: true
          days: 90
        }
      }
    ]
  }
}

// ==================================================
// Outputs
// ==================================================

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
output dataLakeId string = dataLake.id
output dataLakeName string = dataLake.name
output postgresServerId string = postgresServer.id
output postgresServerName string = postgresServer.name
output postgresServerFqdn string = postgresServer.properties.fullyQualifiedDomainName
output postgresAdminUser string = postgresAdminUser
output postgresGeoRedundantBackupEnabled bool = enableGeoRedundantBackup
output postgresBackupRetentionDays int = backupRetentionDays
output redisId string = redis.id
output redisName string = redis.name
output redisHostName string = redis.properties.hostName
output redisSslPort int = redis.properties.sslPort
output privateEndpointsEnabled bool = enablePrivateEndpoints
