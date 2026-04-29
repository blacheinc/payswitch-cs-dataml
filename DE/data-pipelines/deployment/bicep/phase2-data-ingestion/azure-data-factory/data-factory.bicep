// ==================================================
// Azure Data Factory Module
// Core Data Factory infrastructure and required linked services.
// Canonical pipeline JSON is imported by deploy-phase2-private.ps1 after this module deploys.
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
param deploymentEnvironment string = 'dev'

@description('Data Lake Storage Account Name')
param dataLakeStorageAccountName string

@description('Key Vault Name for secrets')
param keyVaultName string

@description('Service Bus Namespace Name')
param serviceBusNamespaceName string

@description('Source blob storage account name used for awaits-ingestion input')
param sourceBlobStorageAccountName string = ''

@description('Metadata PostgreSQL server FQDN (without protocol)')
param metadataPostgresServerFqdn string = ''

@description('Enable private networking posture for Data Factory (disables public access on the factory resource)')
param privateNetworkMode bool = false

@description('When true, deploys the older sample/master pipelines and extra linked services (not in support-live export).')
param deployLegacyStarterCatalog bool = false

@description('Resource tags')
param tags object

var dataLakeDfsUrl = 'https://${dataLakeStorageAccountName}.dfs.${environment().suffixes.storage}/'
var sourceBlobEndpoint = empty(sourceBlobStorageAccountName)
  ? ''
  : 'https://${sourceBlobStorageAccountName}.blob.${environment().suffixes.storage}/'
var managedVnetName = 'default'
var integrationRuntimeName = 'integrationRuntime1'
var keyVaultLinkedServiceName = 'key_vault_ls'
var dataIngestedLinkedServiceName = 'data_ingested_ls'
var dataAwaitsIngestionLinkedServiceName = 'data_awaits_ingestion_ls'
var metadataPostgresLinkedServiceName = 'metadata_postgres_ls'

var dataFactoryName = '${namingPrefix}-adf-${uniqueString(resourceGroup().id)}'
var managedIdentityName = '${dataFactoryName}-identity'

resource dataFactoryIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: managedIdentityName
  location: location
  tags: tags
}

resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' = {
  name: dataFactoryName
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned,UserAssigned'
    userAssignedIdentities: {
      '${dataFactoryIdentity.id}': {}
    }
  }
  properties: {
    publicNetworkAccess: privateNetworkMode ? 'Disabled' : 'Enabled'
    globalParameters: {
      environment: {
        type: 'String'
        value: deploymentEnvironment
      }
      dataLakeStorageAccount: {
        type: 'String'
        value: dataLakeStorageAccountName
      }
      blobStorageAccount: {
        type: 'String'
        value: sourceBlobStorageAccountName
      }
      keyVaultName: {
        type: 'String'
        value: keyVaultName
      }
      serviceBusNamespace: {
        type: 'String'
        value: serviceBusNamespaceName
      }
      serviceBusAPIVersion: {
        type: 'String'
        value: 'api-version=2017-04'
      }
    }
  }
}

resource managedVirtualNetwork 'Microsoft.DataFactory/factories/managedVirtualNetworks@2018-06-01' = {
  parent: dataFactory
  name: managedVnetName
  properties: {}
}

resource integrationRuntime 'Microsoft.DataFactory/factories/integrationRuntimes@2018-06-01' = {
  parent: dataFactory
  name: integrationRuntimeName
  properties: {
    type: 'Managed'
    typeProperties: {
      computeProperties: {
        location: location
        dataFlowProperties: {
          computeType: 'General'
          coreCount: 8
          timeToLive: 10
          cleanup: false
          customProperties: []
        }
        pipelineExternalComputeScaleProperties: {
          timeToLive: 60
          numberOfPipelineNodes: 1
          numberOfExternalNodes: 1
        }
      }
    }
    managedVirtualNetwork: {
      type: 'ManagedVirtualNetworkReference'
      referenceName: managedVnetName
    }
  }
  dependsOn: [
    managedVirtualNetwork
  ]
}

resource keyVaultLinkedServiceAlias 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = {
  parent: dataFactory
  name: keyVaultLinkedServiceName
  properties: {
    type: 'AzureKeyVault'
    annotations: []
    typeProperties: {
      baseUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/'
    }
  }
}

resource dataIngestedLinkedServiceAlias 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = {
  parent: dataFactory
  name: dataIngestedLinkedServiceName
  properties: {
    type: 'AzureBlobFS'
    annotations: []
    typeProperties: {
      url: dataLakeDfsUrl
    }
    connectVia: {
      referenceName: integrationRuntimeName
      type: 'IntegrationRuntimeReference'
    }
  }
  dependsOn: [
    integrationRuntime
  ]
}

resource dataAwaitsIngestionLinkedServiceAlias 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = if (!empty(sourceBlobStorageAccountName)) {
  parent: dataFactory
  name: dataAwaitsIngestionLinkedServiceName
  properties: {
    type: 'AzureBlobStorage'
    annotations: []
    typeProperties: {
      serviceEndpoint: sourceBlobEndpoint
      accountKind: 'StorageV2'
    }
    connectVia: {
      referenceName: integrationRuntimeName
      type: 'IntegrationRuntimeReference'
    }
  }
  dependsOn: [
    integrationRuntime
  ]
}

resource metadataPostgresLinkedServiceAlias 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = if (!empty(metadataPostgresServerFqdn)) {
  parent: dataFactory
  name: metadataPostgresLinkedServiceName
  properties: {
    type: 'AzurePostgreSql'
    annotations: []
    typeProperties: {
      server: metadataPostgresServerFqdn
      database: 'postgres'
      username: 'postgres_admin'
      encryptedCredential: ''
      password: {
        type: 'AzureKeyVaultSecret'
        store: {
          type: 'LinkedServiceReference'
          referenceName: keyVaultLinkedServiceName
        }
        secretName: 'postgres-admin-password'
      }
    }
    connectVia: {
      referenceName: integrationRuntimeName
      type: 'IntegrationRuntimeReference'
    }
  }
  dependsOn: [
    keyVaultLinkedServiceAlias
    integrationRuntime
  ]
}

// ==================================================
// Optional legacy starter catalog (kept for demos / older docs)
// ==================================================

resource keyVaultLinkedService 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'AzureKeyVault'
  properties: {
    type: 'AzureKeyVault'
    typeProperties: {
      baseUrl: 'https://${keyVaultName}${environment().suffixes.keyvaultDns}/'
    }
    annotations: []
  }
}

resource dataLakeLinkedService 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'AzureDataLakeStorage'
  properties: {
    type: 'AzureBlobFS'
    typeProperties: {
      url: dataLakeDfsUrl
      accountKey: {
        type: 'AzureKeyVaultSecret'
        store: {
          referenceName: 'AzureKeyVault'
          type: 'LinkedServiceReference'
        }
        secretName: 'data-lake-storage-key'
      }
    }
    annotations: []
  }
  dependsOn: [
    keyVaultLinkedService
  ]
}

resource serviceBusLinkedService 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'AzureServiceBus'
  properties: {
    type: 'AzureServiceBus'
    typeProperties: {
      connectionString: {
        type: 'AzureKeyVaultSecret'
        store: {
          referenceName: 'AzureKeyVault'
          type: 'LinkedServiceReference'
        }
        secretName: 'service-bus-connection-string'
      }
    }
    annotations: []
  }
  dependsOn: [
    keyVaultLinkedService
  ]
}

resource restApiLinkedService 'Microsoft.DataFactory/factories/linkedServices@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'RestApiGeneric'
  properties: {
    type: 'RestService'
    typeProperties: {
      url: 'https://api.example.com'
      enableServerCertificateValidation: true
      authenticationType: 'Anonymous'
    }
    annotations: []
  }
}

resource rawDataLakeDataset 'Microsoft.DataFactory/factories/datasets@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'RawDataLakeJson'
  properties: {
    linkedServiceName: {
      referenceName: dataLakeLinkedService.name
      type: 'LinkedServiceReference'
    }
    parameters: {
      folderPath: {
        type: 'String'
      }
      fileName: {
        type: 'String'
      }
    }
    type: 'Json'
    typeProperties: {
      location: {
        type: 'AzureBlobFSLocation'
        folderPath: {
          value: '@dataset().folderPath'
          type: 'Expression'
        }
        fileName: {
          value: '@dataset().fileName'
          type: 'Expression'
        }
        fileSystem: 'raw'
      }
    }
  }
}

resource processedDataLakeDataset 'Microsoft.DataFactory/factories/datasets@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'ProcessedDataLakeParquet'
  properties: {
    linkedServiceName: {
      referenceName: dataLakeLinkedService.name
      type: 'LinkedServiceReference'
    }
    parameters: {
      folderPath: {
        type: 'String'
      }
    }
    type: 'Parquet'
    typeProperties: {
      location: {
        type: 'AzureBlobFSLocation'
        folderPath: {
          value: '@dataset().folderPath'
          type: 'Expression'
        }
        fileSystem: 'processed'
      }
      compressionCodec: 'snappy'
    }
  }
}

resource serviceBusDataset 'Microsoft.DataFactory/factories/datasets@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'ServiceBusMessage'
  properties: {
    linkedServiceName: {
      referenceName: serviceBusLinkedService.name
      type: 'LinkedServiceReference'
    }
    parameters: {
      topicName: {
        type: 'String'
      }
    }
    type: 'AzureServiceBusMessage'
    typeProperties: {
      topicName: {
        value: '@dataset().topicName'
        type: 'Expression'
      }
    }
  }
}

resource creditBureauPipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'CreditBureauIngestionPipeline'
  properties: {
    activities: [
      {
        name: 'CallCreditBureauAPI'
        type: 'Copy'
        dependsOn: []
        policy: {
          timeout: '0.00:10:00'
          retry: 3
          retryIntervalInSeconds: 30
        }
        userProperties: []
        typeProperties: {
          source: {
            type: 'RestSource'
            httpRequestTimeout: '00:05:00'
            requestInterval: '00.00:00:00.010'
          }
          sink: {
            type: 'JsonSink'
            storeSettings: {
              type: 'AzureBlobFSWriteSettings'
            }
            formatSettings: {
              type: 'JsonWriteSettings'
            }
          }
          enableStaging: false
        }
        inputs: [
          {
            referenceName: restApiLinkedService.name
            type: 'LinkedServiceReference'
          }
        ]
        outputs: [
          {
            referenceName: rawDataLakeDataset.name
            type: 'DatasetReference'
            parameters: {
              folderPath: 'credit-bureau/@{utcnow(\'yyyy-MM-dd\')}'
              fileName: '@{utcnow(\'yyyyMMddHHmmss\')}.json'
            }
          }
        ]
      }
    ]
    annotations: []
  }
}

resource bankingDataPipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'BankingDataIngestionPipeline'
  properties: {
    activities: []
    annotations: []
  }
}

resource telcoDataPipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'TelcoDataIngestionPipeline'
  properties: {
    activities: []
    annotations: []
  }
}

resource masterIngestionPipeline 'Microsoft.DataFactory/factories/pipelines@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'MasterDataIngestionPipeline'
  properties: {
    activities: []
    annotations: []
  }
}

resource dailyIngestionTrigger 'Microsoft.DataFactory/factories/triggers@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'DailyIngestionTrigger'
  properties: {
    type: 'ScheduleTrigger'
    typeProperties: {
      recurrence: {
        frequency: 'Day'
        interval: 1
        startTime: '2025-01-01T02:00:00Z'
        timeZone: 'UTC'
      }
    }
    pipelines: []
  }
}

resource blobEventTrigger 'Microsoft.DataFactory/factories/triggers@2018-06-01' = if (deployLegacyStarterCatalog) {
  parent: dataFactory
  name: 'BlobCreatedTrigger'
  properties: {
    type: 'BlobEventsTrigger'
    typeProperties: {
      blobPathBeginsWith: '/raw/blobs/'
      blobPathEndsWith: '.json'
      ignoreEmptyBlobs: true
      scope: resourceId('Microsoft.Storage/storageAccounts', dataLakeStorageAccountName)
      events: [
        'Microsoft.Storage.BlobCreated'
      ]
    }
    pipelines: []
  }
}

// ==================================================
// Outputs
// ==================================================

output dataFactoryId string = dataFactory.id
output dataFactoryName string = dataFactory.name
output dataFactoryIdentityPrincipalId string = dataFactory.identity.principalId
output managedIdentityId string = dataFactoryIdentity.id
output linkedServicesDeployed array = [
  keyVaultLinkedServiceAlias.name
  dataIngestedLinkedServiceAlias.name
]
output pipelinesDeployed array = deployLegacyStarterCatalog ? [
    masterIngestionPipeline.name
    creditBureauPipeline.name
    bankingDataPipeline.name
    telcoDataPipeline.name
  ] : []
