@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Resource tags')
param tags object

@description('Storage account name for function runtime')
param functionsStorageAccountName string

@description('Optional list of CIDRs allowed to call function apps (empty = no explicit allow-list).')
param allowedCallerCidrs array = []

@description('Whether to disable public network access for SCM/Kudu endpoint.')
param disableScmPublicAccess bool = true

var planName = '${namingPrefix}-functions-consumption-plan'
var allowedCallerRules = [for (cidr, i) in allowedCallerCidrs: {
  ipAddress: cidr
  action: 'Allow'
  priority: 200 + i
  name: 'AllowCaller${i}'
}]

var functionApps = [
  '${namingPrefix}-schema-mapping-func'
  '${namingPrefix}-transformation-func'
  '${namingPrefix}-training-ingestion-func'
  '${namingPrefix}-adf-trigger-func'
  '${namingPrefix}-file-checksum-func'
]

resource runtimeStorage 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: functionsStorageAccountName
}

resource appServicePlan 'Microsoft.Web/serverfarms@2023-12-01' = {
  name: planName
  location: location
  kind: 'functionapp'
  sku: {
    name: 'Y1'
    tier: 'Dynamic'
    size: 'Y1'
    capacity: 0
  }
  tags: tags
  properties: {
    reserved: false
    perSiteScaling: false
  }
}

resource functionAppsResource 'Microsoft.Web/sites@2023-12-01' = [for appName in functionApps: {
  name: appName
  location: location
  kind: 'functionapp'
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    publicNetworkAccess: 'Enabled'
    siteConfig: {
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
      scmIpSecurityRestrictionsUseMain: true
      appSettings: [
        {
          name: 'FUNCTIONS_WORKER_RUNTIME'
          value: 'python'
        }
        {
          name: 'FUNCTIONS_EXTENSION_VERSION'
          value: '~4'
        }
        {
          name: 'WEBSITE_RUN_FROM_PACKAGE'
          value: '1'
        }
        {
          name: 'AzureWebJobsStorage__accountName'
          value: runtimeStorage.name
        }
      ]
      ipSecurityRestrictions: concat([
        {
          ipAddress: 'AzureCloud'
          tag: 'ServiceTag'
          action: 'Allow'
          priority: 100
          name: 'AllowAzureServices'
          description: 'Allow Azure service traffic'
        }
      ], allowedCallerRules, [
        {
          ipAddress: 'Any'
          action: 'Deny'
          priority: 2147483647
          name: 'DenyAll'
        }
      ])
      scmIpSecurityRestrictions: disableScmPublicAccess ? [
        {
          ipAddress: 'Any'
          action: 'Deny'
          priority: 100
          name: 'DenyScmPublic'
        }
      ] : []
    }
  }
}]

output planId string = appServicePlan.id
output functionAppNames array = functionApps
