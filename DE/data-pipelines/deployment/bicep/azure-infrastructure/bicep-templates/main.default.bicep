targetScope = 'subscription'

@description('Environment name (dev, staging, prod).')
@allowed([
  'dev'
  'staging'
  'prod'
])
param environment string

@description('Primary Azure region for all resource groups and modules.')
param primaryLocation string

@description('Secondary Azure region for DR')
param secondaryLocation string = 'westus2'

@description('Project name prefix for resource naming.')
param projectName string

@description('Organization short name for resource naming.')
param orgName string

@description('Tags to apply to all resources.')
param tags object

@description('Administrator email for alerts and notifications')
param adminEmail string

@description('Enable Azure Defender and advanced security features')
param enableAdvancedSecurity bool = true

@description('Enable multi-region deployment for DR')
param enableMultiRegion bool = false

@description('Enable Azure OpenAI Service')
param enableOpenAI bool = true

@description('Deploy AKS cluster (optional)')
param deployAks bool = environment != 'prod'

@description('Deploy Azure Machine Learning workspace module')
param deployMlWorkspace bool = true

@description('Deploy Azure Bastion + a private-subnet Windows jump VM')
param deployJumpBox bool = environment == 'prod'

@description('Admin username for the jump VM Windows OS profile')
param jumpVmAdminUsername string = 'azureuser'

@secure()
@description('Windows jump VM admin password (required when deployJumpBox is true)')
param jumpVmAdminPassword string = ''

@description('VM size for jump host')
param jumpVmSize string = 'Standard_B2s'

module main './main.bicep' = {
  name: 'main-default-${environment}'
  params: {
    environment: environment
    primaryLocation: primaryLocation
    secondaryLocation: secondaryLocation
    privateNetworkMode: false
    projectName: projectName
    orgName: orgName
    tags: tags
    adminEmail: adminEmail
    enableAdvancedSecurity: enableAdvancedSecurity
    enableMultiRegion: enableMultiRegion
    enableOpenAI: enableOpenAI
    deployAks: deployAks
    deployMlWorkspace: deployMlWorkspace
    deployJumpBox: deployJumpBox
    jumpVmAdminUsername: jumpVmAdminUsername
    jumpVmAdminPassword: jumpVmAdminPassword
    jumpVmSize: jumpVmSize
  }
}

output resourceGroupNames object = main.outputs.resourceGroupNames
output namingPrefix string = main.outputs.namingPrefix
output vnetId string = main.outputs.vnetId
output aksClusterName string = main.outputs.aksClusterName
output keyVaultName string = main.outputs.keyVaultName
output mlWorkspaceName string = main.outputs.mlWorkspaceName
output storageAccountName string = main.outputs.storageAccountName
output blobStorageAccountName string = main.outputs.blobStorageAccountName
output functionsStorageAccountName string = main.outputs.functionsStorageAccountName
output dataLakeStorageAccountName string = main.outputs.dataLakeStorageAccountName
output postgresServerName string = main.outputs.postgresServerName
output postgresServerFqdn string = main.outputs.postgresServerFqdn
output redisName string = main.outputs.redisName
output bastionName string = main.outputs.bastionName
output jumpVmName string = main.outputs.jumpVmName
