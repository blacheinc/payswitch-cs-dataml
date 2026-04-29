@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Resource tags')
param tags object

@description('Functions subnet resource ID (delegated to Microsoft.Web/serverFarms)')
param functionsSubnetId string

@description('Private endpoints subnet resource ID')
param privateEndpointsSubnetId string

@description('Storage account name for function runtime')
param functionsStorageAccountName string

@description('Service Bus namespace name used for identity-based trigger bindings')
param serviceBusNamespaceName string = ''

@description('Enable private network posture for function apps')
param privateNetworkMode bool = true

@description('Plan SKU for premium functions')
param premiumPlanSku string = 'EP1'

@description('Plan tier for the Functions hosting plan (ElasticPremium or PremiumV3)')
@allowed([
  'ElasticPremium'
  'PremiumV3'
])
param planTier string = 'ElasticPremium'

var planName = '${namingPrefix}-functions-premium-plan'
var storageKey = listKeys(runtimeStorage.id, '2023-01-01').keys[0].value
var runtimeStorageConnectionString = 'DefaultEndpointsProtocol=https;EndpointSuffix=${environment().suffixes.storage};AccountName=${runtimeStorage.name};AccountKey=${storageKey}'
var isElasticPremium = planTier == 'ElasticPremium'

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
  kind: 'linux'
  sku: {
    name: premiumPlanSku
    tier: planTier
    size: premiumPlanSku
    capacity: 1
  }
  tags: tags
  properties: union({
    reserved: true
    perSiteScaling: false
  }, isElasticPremium ? {
    maximumElasticWorkerCount: 20
  } : {})
}

resource websitesPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = if (privateNetworkMode) {
  name: 'privatelink.azurewebsites.net'
  location: 'global'
  tags: tags
}

resource functionAppsResource 'Microsoft.Web/sites@2023-12-01' = [for appName in functionApps: {
  name: appName
  location: location
  kind: 'functionapp,linux'
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    serverFarmId: appServicePlan.id
    httpsOnly: true
    publicNetworkAccess: privateNetworkMode ? 'Disabled' : 'Enabled'
    virtualNetworkSubnetId: functionsSubnetId
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      minTlsVersion: '1.2'
      ftpsState: 'Disabled'
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
          name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'
          value: runtimeStorageConnectionString
        }
        {
          name: 'WEBSITE_CONTENTSHARE'
          value: toLower(replace(appName, '-', ''))
        }
        {
          name: 'AzureWebJobsStorage'
          value: runtimeStorageConnectionString
        }
        {
          name: 'ServiceBusConnectionString__fullyQualifiedNamespace'
          value: empty(serviceBusNamespaceName) ? '' : '${serviceBusNamespaceName}.servicebus.windows.net'
        }
      ]
    }
  }
}]

resource privateEndpoints 'Microsoft.Network/privateEndpoints@2023-09-01' = [for (appName, i) in functionApps: if (privateNetworkMode) {
  name: '${appName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${appName}-pls'
        properties: {
          privateLinkServiceId: functionAppsResource[i].id
          groupIds: [
            'sites'
          ]
        }
      }
    ]
  }
}]

resource websitesDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = if (privateNetworkMode) {
  parent: websitesPrivateDnsZone
  name: '${namingPrefix}-webapps-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: substring(functionsSubnetId, 0, indexOf(functionsSubnetId, '/subnets/'))
    }
  }
}

resource websitesDnsZoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = [for (appName, i) in functionApps: if (privateNetworkMode) {
  parent: privateEndpoints[i]
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'webapps-zone'
        properties: {
          privateDnsZoneId: websitesPrivateDnsZone.id
        }
      }
    ]
  }
}]

output premiumPlanId string = appServicePlan.id
output functionAppNames array = functionApps
