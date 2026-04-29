// ==================================================
// Data Services Module
// PostgreSQL, Redis, Storage Account, Data Lake
// ==================================================

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('PostgreSQL SKU name (e.g., Standard_B1ms for Burstable, Standard_D2s_v3 for GeneralPurpose)')
param postgresSkuName string = 'Standard_B1ms'

@description('Redis Cache SKU')
param redisCacheSku string = 'Standard'

@description('Backup retention days')
param backupRetentionDays int = 30

@description('Enable High Availability')
param enableHA bool = true

@description('Key Vault name for secret storage (currently unused but reserved for future use)')
param keyVaultName string

@description('Data subnet ID for private endpoints')
param subnetId string

@description('Virtual Network ID for Private DNS Zone linking (optional for dev, required for prod)')
param vnetId string = ''

@description('ML subnet ID (optional) to allow Azure ML compute access to storage/Data Lake')
param mlSubnetId string = ''

@description('Environment (dev or production) - controls publicNetworkAccess')
@allowed([
  'dev'
  'production'
])
param environment string = 'dev'

@description('Enable private networking posture regardless of environment')
param privateNetworkMode bool = false

@description('Resource tags')
param tags object

// ==================================================
// Variables
// ==================================================

var postgresServerName = '${namingPrefix}-postgres-${uniqueString(resourceGroup().id)}'
var redisName = '${namingPrefix}-redis-${uniqueString(resourceGroup().id)}'
// Storage account names must be 3-24 characters, lowercase alphanumeric only
// Use short prefix: first 8 chars of org name + "st" or "dl" + 13-char hash = max 23 chars
var shortPrefix = substring(split(namingPrefix, '-')[0], 0, min(8, length(split(namingPrefix, '-')[0])))
var storageAccountName = '${shortPrefix}st${substring(uniqueString(resourceGroup().id), 0, 13)}'
var dataLakeName = '${shortPrefix}dl${substring(uniqueString(resourceGroup().id), 0, 13)}'

// Administrator credentials
var postgresAdminUser = 'csadmin'
// Note: Password is generated dynamically - Bicep linter warning is expected for dynamic values
// In production, use Key Vault reference instead: @keyVault.getSecret('postgres-admin-password')
var postgresAdminPassword = '${uniqueString(resourceGroup().id, 'postgres')}!Aa1' // This should be rotated

// Environment-based configuration
var isProduction = environment == 'production' || privateNetworkMode
var postgresPublicNetworkAccess = isProduction ? 'Disabled' : 'Enabled'
var redisPublicNetworkAccess = isProduction ? 'Disabled' : 'Enabled'
var storageDefaultAction = isProduction ? 'Deny' : 'Allow'

// ==================================================
// Storage Account (Blob Storage - General Purpose)
// NOTE: This is a standard blob storage account WITHOUT hierarchical namespace
// Used for: models, artifacts, and data containers
// ==================================================

// Virtual network rules shared by Storage & Data Lake
var storageVirtualNetworkRules = empty(mlSubnetId) ? [
  {
    id: subnetId
    action: 'Allow'
  }
] : [
  {
    id: subnetId
    action: 'Allow'
  }
  {
    id: mlSubnetId
    action: 'Allow'
  }
]

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    // NOTE: isHnsEnabled is NOT set (defaults to false) - this is a standard blob storage account
    // Hierarchical namespace cannot be enabled after account creation
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: storageDefaultAction
      virtualNetworkRules: isProduction ? storageVirtualNetworkRules : []
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
    }
  }
}

// Blob service
resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
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
// Data Lake Storage Gen2
// NOTE: This storage account has hierarchical namespace (HNS) enabled
// Used for: bronze, silver, gold data layers with file system structure
// IMPORTANT: isHnsEnabled must be set to true at creation time - cannot be changed later
// ==================================================

resource dataLake 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: dataLakeName
  location: location
  tags: tags
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    // CRITICAL: isHnsEnabled must be true for Data Lake Gen2
    // This enables hierarchical namespace (file system structure)
    // Cannot be enabled after account creation - must be set at creation time
    isHnsEnabled: true
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: storageDefaultAction
      virtualNetworkRules: isProduction ? storageVirtualNetworkRules : []
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
    }
  }
}

// Data Lake containers (file systems)
resource dataLakeBlobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: dataLake
  name: 'default'
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
// Private DNS Zone for PostgreSQL
// Only create if vnetId is provided (for production with private endpoints)
// ==================================================

resource privatePostgresDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (!empty(vnetId) && isProduction) {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

// Only create Private DNS Zone link if vnetId is provided and not empty
resource privatePostgresDnsZoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (!empty(vnetId) && isProduction) {
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

// ==================================================
// Azure Database for PostgreSQL
// ==================================================

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  name: postgresServerName
  location: location
  tags: tags
  sku: {
    name: postgresSkuName
    tier: contains(postgresSkuName, 'Standard_B') ? 'Burstable' : 'GeneralPurpose'
  }
  properties: {
    administratorLogin: postgresAdminUser
    administratorLoginPassword: postgresAdminPassword
    version: '14'
    storage: {
      storageSizeGB: 128
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: enableHA ? 'Enabled' : 'Disabled'
    }
    highAvailability: enableHA ? {
      mode: 'ZoneRedundant'
    } : {
      mode: 'Disabled'
    }
    network: (isProduction && !empty(vnetId) && !empty(subnetId)) ? {
      publicNetworkAccess: postgresPublicNetworkAccess
      delegatedSubnetResourceId: subnetId
      privateDnsZoneArmResourceId: privatePostgresDnsZone.id
    } : {
      publicNetworkAccess: postgresPublicNetworkAccess
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

// PostgreSQL firewall rule (allow Azure services)
resource postgresFirewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = if (!privateNetworkMode) {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}

// ==================================================
// Azure Cache for Redis
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
    minimumTlsVersion: '1.2'  // Redis only supports TLS 1.2, not 1.3
    publicNetworkAccess: redisPublicNetworkAccess
    redisConfiguration: {
      'maxmemory-policy': 'allkeys-lru'
    }
    redisVersion: '6'
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
output redisId string = redis.id
output redisName string = redis.name
output redisHostName string = redis.properties.hostName
output redisSslPort int = redis.properties.sslPort
