targetScope = 'resourceGroup'

@description('Function apps that should receive IAM grants')
param functionApps array

@description('Function app names to exclude from IAM role assignment')
param excludedFunctionAppNames array = []

@description('Service Bus namespace name in this resource group')
param serviceBusNamespaceName string

var serviceBusDataSenderRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
)
var serviceBusDataReceiverRoleDefinitionId = subscriptionResourceId(
  'Microsoft.Authorization/roleDefinitions',
  '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
)

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = {
  name: serviceBusNamespaceName
}

resource serviceBusDataSenderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for app in functionApps: if (!contains(excludedFunctionAppNames, app.name)) {
  name: guid(serviceBusNamespace.id, app.name, serviceBusDataSenderRoleDefinitionId)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: serviceBusDataSenderRoleDefinitionId
    principalId: reference(resourceId(app.resourceGroupName, 'Microsoft.Web/sites', app.name), '2023-12-01', 'Full').identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

resource serviceBusDataReceiverAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for app in functionApps: if (!contains(excludedFunctionAppNames, app.name)) {
  name: guid(serviceBusNamespace.id, app.name, serviceBusDataReceiverRoleDefinitionId)
  scope: serviceBusNamespace
  properties: {
    roleDefinitionId: serviceBusDataReceiverRoleDefinitionId
    principalId: reference(resourceId(app.resourceGroupName, 'Microsoft.Web/sites', app.name), '2023-12-01', 'Full').identity.principalId
    principalType: 'ServicePrincipal'
  }
}]

