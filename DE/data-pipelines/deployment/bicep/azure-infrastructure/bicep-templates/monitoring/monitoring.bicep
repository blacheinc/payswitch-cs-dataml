// ==================================================
// Monitoring Module
// Log Analytics, Application Insights, Alerts
// ==================================================

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Administrator email for alerts')
param adminEmail string

@description('Enable metric alerts (set to false if alerts fail to deploy)')
param enableMetricAlerts bool = true

@description('Resource tags')
param tags object

// ==================================================
// Variables
// ==================================================

var logAnalyticsName = '${namingPrefix}-law'
var appInsightsName = '${namingPrefix}-appinsights'
var actionGroupName = '${namingPrefix}-actiongroup'

// ==================================================
// Log Analytics Workspace
// ==================================================

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 90
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ==================================================
// Application Insights
// ==================================================

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  dependsOn: [
    logAnalytics
  ]
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// ==================================================
// Action Group for Alerts
// ==================================================

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: actionGroupName
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'CSAlerts'
    enabled: true
    emailReceivers: [
      {
        name: 'AdminEmail'
        emailAddress: adminEmail
        useCommonAlertSchema: true
      }
    ]
  }
}

// ==================================================
// Metric Alerts
// ==================================================

// High CPU alert
resource highCpuAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (enableMetricAlerts) {
  name: '${namingPrefix}-high-cpu-alert'
  location: 'global'
  tags: tags
  dependsOn: [
    actionGroup
  ]
  properties: {
    description: 'Alert when CPU usage exceeds 80%'
    severity: 2
    enabled: true
    scopes: [
      resourceGroup().id
    ]
    targetResourceType: 'Microsoft.Compute/virtualMachines'
    targetResourceRegion: location
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'HighCPU'
          criterionType: 'StaticThresholdCriterion'
          metricName: 'Percentage CPU'
          metricNamespace: 'Microsoft.Compute/virtualMachines'
          operator: 'GreaterThan'
          threshold: 80
          timeAggregation: 'Average'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

// High memory alert
resource highMemoryAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = if (enableMetricAlerts) {
  name: '${namingPrefix}-high-memory-alert'
  location: 'global'
  tags: tags
  dependsOn: [
    actionGroup
  ]
  properties: {
    description: 'Alert when memory usage exceeds 85%'
    severity: 2
    enabled: true
    scopes: [
      resourceGroup().id
    ]
    targetResourceType: 'Microsoft.Compute/virtualMachines'
    targetResourceRegion: location
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'HighMemory'
          criterionType: 'StaticThresholdCriterion'
          metricName: 'Available Memory Bytes'
          metricNamespace: 'Microsoft.Compute/virtualMachines'
          operator: 'LessThan'
          threshold: 1073741824 // 1 GB
          timeAggregation: 'Average'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}

// ==================================================
// Log Analytics Solutions
// ==================================================

resource containerInsights 'Microsoft.OperationsManagement/solutions@2015-11-01-preview' = {
  name: 'ContainerInsights(${logAnalytics.name})'
  location: location
  tags: tags
  plan: {
    name: 'ContainerInsights(${logAnalytics.name})'
    product: 'OMSGallery/ContainerInsights'
    promotionCode: ''
    publisher: 'Microsoft'
  }
  properties: {
    workspaceResourceId: logAnalytics.id
  }
}

resource securityInsights 'Microsoft.OperationsManagement/solutions@2015-11-01-preview' = {
  name: 'SecurityInsights(${logAnalytics.name})'
  location: location
  tags: tags
  dependsOn: [
    logAnalytics
  ]
  plan: {
    name: 'SecurityInsights(${logAnalytics.name})'
    product: 'OMSGallery/SecurityInsights'
    promotionCode: ''
    publisher: 'Microsoft'
  }
  properties: {
    workspaceResourceId: logAnalytics.id
  }
}

// ==================================================
// Workbook for Custom Dashboards
// ==================================================

resource customWorkbook 'Microsoft.Insights/workbooks@2022-04-01' = {
  name: guid('${namingPrefix}-workbook')
  location: location
  tags: tags
  kind: 'shared'
  properties: {
    displayName: 'Credit Scoring Dashboard'
    category: 'workbook'
    serializedData: '''
    {
      "version": "Notebook/1.0",
      "items": [
        {
          "type": 1,
          "content": {
            "json": "## Credit Scoring Platform - Monitoring Dashboard\\n\\nComprehensive monitoring for credit scoring and agentic AI components"
          }
        },
        {
          "type": 3,
          "content": {
            "version": "KqlItem/1.0",
            "query": "requests\\n| summarize count() by bin(timestamp, 5m)\\n| render timechart",
            "size": 0,
            "title": "API Request Rate"
          }
        }
      ]
    }
    '''
    sourceId: appInsights.id
  }
}

// ==================================================
// Outputs
// ==================================================

output logAnalyticsId string = logAnalytics.id
output logAnalyticsWorkspaceId string = logAnalytics.properties.customerId
output applicationInsightsId string = appInsights.id
output applicationInsightsKey string = appInsights.properties.InstrumentationKey
output applicationInsightsConnectionString string = appInsights.properties.ConnectionString
output actionGroupId string = actionGroup.id
