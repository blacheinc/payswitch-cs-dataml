# Comprehensive Connectivity Analysis
## Credit Scoring Platform - All Resources

**Date:** 2025-01-28  
**Purpose:** Complete analysis of network connectivity for all resources, issues, and solutions for dev/prod environments

---

## Executive Summary

This document provides a comprehensive analysis of network connectivity for all resources in the credit scoring platform. It identifies connectivity requirements, potential issues, and provides solutions for both development and production environments.

**Key Findings:**
- **25+ Azure resources** require network connectivity
- **7 subnets** with specific security requirements
- **VNet-integrated resources** require private endpoints or service endpoints
- **Consumption plan Functions** cannot use VNet integration (must use service endpoints)
- **Static Web Apps** cannot be made fully private (Azure limitation)
- **Production requires** private endpoints for all PaaS services
- **TLS 1.3 Limitation:** Redis and Service Bus only support TLS 1.2 (Azure platform limitation)

---

## Table of Contents

1. [Resource Inventory](#resource-inventory)
2. [Network Architecture](#network-architecture)
3. [Connectivity Requirements](#connectivity-requirements)
4. [Connectivity Issues](#connectivity-issues)
5. [Solutions by Environment](#solutions-by-environment)
6. [Implementation Steps](#implementation-steps)
7. [Testing Procedures](#testing-procedures)

---

## Resource Inventory

### All Resources in the Architecture

| Resource Type | Resource Name | Location | Network Requirements |
|--------------|---------------|----------|---------------------|
| **Networking** |
| Virtual Network | `{prefix}-vnet` | Network RG | 7 subnets, NSGs |
| Network Security Groups | 7 NSGs (one per subnet) | Network RG | Inbound/outbound rules |
| Private DNS Zones | `privatelink.*` | Network RG | DNS resolution for private endpoints |
| **Security** |
| Key Vault | `{prefix}-kv-{hash}` | Security RG | Private endpoint or network rules |
| Managed Identities | Multiple | Security RG | No network requirements |
| **Data Services** |
| PostgreSQL Flexible Server | `{prefix}-postgres-{hash}` | Data RG | VNet integration or private endpoint |
| Azure Cache for Redis | `{prefix}-redis-{hash}` | Data RG | Private endpoint or firewall rules |
| Storage Account | `{prefix}st{hash}` | Data RG | Private endpoint or network rules |
| Data Lake Gen2 | `{prefix}dl{hash}` | Data RG | Private endpoint or network rules |
| Cosmos DB (MongoDB API) | `{prefix}-cosmos-{hash}` | Data RG | Private endpoint or firewall rules |
| **Compute** |
| AKS Cluster | `{prefix}-aks` | Compute RG | VNet-integrated subnet |
| Azure Container Registry | `{prefix}acr{hash}` | Compute RG | Private endpoint or network rules |
| Azure ML Workspace | `{prefix}-ml-{hash}` | ML RG | VNet integration (optional) |
| ML Compute Clusters | `cpu-cluster`, `gpu-cluster` | ML RG | VNet-integrated subnet |
| **Integration** |
| Azure Data Factory | `{prefix}-adf-{hash}` | Data RG | Managed VNet with private endpoints |
| Service Bus | `{prefix}-sb-{hash}` | Data RG | Private endpoint or firewall rules |
| **Functions (AI Agents)** |
| Decision Agent Function | `{prefix}-decision-agent` | Agents RG | Consumption plan (no VNet) |
| Risk Monitoring Agent | `{prefix}-risk-monitoring-agent` | Agents RG | Consumption plan (no VNet) |
| Customer Service Agent | `{prefix}-customer-service-agent` | Agents RG | Consumption plan (no VNet) |
| Compliance Agent | `{prefix}-compliance-agent` | Agents RG | Consumption plan (no VNet) |
| Model Training Agent | `{prefix}-model-training-agent` | Agents RG | Consumption plan (no VNet) |
| Data Quality Agent | `{prefix}-dq-agent` | Agents RG | Consumption plan (no VNet) |
| Feature Engineering Agent | `{prefix}-fe-agent` | Agents RG | Consumption plan (no VNet) |
| **API Gateway** |
| API Management | `{prefix}-apim-{hash}` | Compute RG | VNet-integrated subnet |
| Static Web Apps | `{prefix}-frontend` | Compute RG | Public (cannot be private) |
| **Monitoring** |
| Log Analytics Workspace | `{prefix}-law` | Monitoring RG | No network requirements |
| Application Insights | `{prefix}-appinsights-{hash}` | Monitoring RG | No network requirements |

**Total: 25+ resources requiring network configuration**

---

## Network Architecture

### VNet Structure

```
VNet: {prefix}-vnet (10.0.0.0/16)
│
├── Subnet 1: aks-subnet (10.0.1.0/24)
│   ├── Purpose: AKS cluster nodes
│   ├── NSG: aks-nsg
│   ├── Service Endpoints: Storage, KeyVault, SQL
│   └── Resources: AKS node pools
│
├── Subnet 2: data-subnet (10.0.2.0/24)
│   ├── Purpose: Data services (PostgreSQL, Redis)
│   ├── NSG: data-nsg
│   ├── Service Endpoints: Storage, KeyVault, SQL
│   └── Resources: PostgreSQL (VNet-integrated), Redis (private endpoint)
│
├── Subnet 3: ml-subnet (10.0.3.0/24)
│   ├── Purpose: Azure ML compute instances
│   ├── NSG: ml-nsg
│   ├── Service Endpoints: Storage, KeyVault
│   └── Resources: ML compute clusters
│
├── Subnet 4: functions-subnet (10.0.4.0/24)
│   ├── Purpose: Azure Functions (delegated, but not used - Functions are Consumption)
│   ├── NSG: functions-nsg
│   ├── Delegation: Microsoft.Web/serverFarms
│   ├── Service Endpoints: Storage, KeyVault
│   └── Resources: None (Functions are Consumption plan, cannot use VNet)
│
├── Subnet 5: apim-subnet (10.0.5.0/24)
│   ├── Purpose: API Management gateway
│   ├── NSG: apim-nsg
│   ├── Service Endpoints: Storage, KeyVault
│   └── Resources: APIM instance
│
├── Subnet 6: gateway-subnet (10.0.6.0/24)
│   ├── Purpose: Application Gateway (WAF) - Future
│   ├── NSG: gateway-nsg
│   └── Resources: None (future use)
│
└── Subnet 7: private-endpoints-subnet (10.0.7.0/24)
    ├── Purpose: Private endpoints for PaaS services
    ├── NSG: None (private endpoints bypass NSGs)
    ├── Private Endpoint Network Policies: Disabled
    └── Resources: Private endpoints for Storage, Data Lake, Key Vault, Redis, Cosmos DB, Service Bus
```

---

## Connectivity Requirements

### Connection Matrix

| Source Resource | Destination Resource | Protocol | Port | Method | Required For |
|----------------|---------------------|----------|------|--------|--------------|
| **AKS Pods** |
| AKS Pods | PostgreSQL | TCP | 5432 | VNet (service endpoint) | Database access |
| AKS Pods | Redis | TCP | 6379 | Private endpoint | Cache access |
| AKS Pods | Storage Account | HTTPS | 443 | Service endpoint | Blob storage |
| AKS Pods | Data Lake | HTTPS | 443 | Service endpoint | Data Lake access |
| AKS Pods | Key Vault | HTTPS | 443 | Service endpoint | Secrets access |
| AKS Pods | Cosmos DB | HTTPS | 443 | Private endpoint | MongoDB access |
| AKS Pods | Service Bus | HTTPS | 443 | Private endpoint | Messaging |
| **Azure Functions (Agents)** |
| Functions | PostgreSQL | TCP | 5432 | Public (firewall) or Private endpoint | Database access |
| Functions | Redis | TCP | 6379 | Private endpoint | Cache access |
| Functions | Storage Account | HTTPS | 443 | Service endpoint | Function storage |
| Functions | Key Vault | HTTPS | 443 | Service endpoint | Secrets access |
| Functions | Cosmos DB | HTTPS | 443 | Private endpoint | MongoDB access |
| Functions | Service Bus | HTTPS | 443 | Private endpoint | Messaging |
| Functions | Azure ML | HTTPS | 443 | Public (firewall) | Model access |
| **Azure Data Factory** |
| Data Factory | Storage Account | HTTPS | 443 | Private endpoint | Data ingestion |
| Data Factory | Data Lake | HTTPS | 443 | Private endpoint | Data Lake access |
| Data Factory | Key Vault | HTTPS | 443 | Private endpoint | Secrets access |
| Data Factory | Service Bus | HTTPS | 443 | Private endpoint | Messaging |
| Data Factory | PostgreSQL | TCP | 5432 | Private endpoint | Database access |
| **Azure ML** |
| ML Compute | Storage Account | HTTPS | 443 | Service endpoint | Training data |
| ML Compute | Data Lake | HTTPS | 443 | Service endpoint | Feature store |
| ML Compute | Key Vault | HTTPS | 443 | Service endpoint | Secrets access |
| ML Compute | PostgreSQL | TCP | 5432 | Service endpoint | MLflow backend |
| **API Management** |
| APIM | AKS (Backend API) | HTTPS | 443 | VNet (internal) | API routing |
| APIM | Functions | HTTPS | 443 | Public (with auth) | Agent endpoints |
| APIM | Static Web Apps | HTTPS | 443 | Public | Frontend |
| **Static Web Apps** |
| Frontend | APIM | HTTPS | 443 | Public | API calls |
| **External Access** |
| Developers | PostgreSQL | TCP | 5432 | Azure Bastion → VNet | Local development |
| Developers | Redis | TCP | 6379 | Azure Bastion → VNet | Local development |
| Developers | Key Vault | HTTPS | 443 | Public (network rules) | Secret management |
| Developers | Storage Account | HTTPS | 443 | Public (network rules) | Data access |
| Developers | Cosmos DB | HTTPS | 443 | Public (firewall rules) | MongoDB access |

---

## Connectivity Issues

### Issue 1: Functions Cannot Use VNet Integration (Consumption Plan)

**Problem:**
- All AI Agents are deployed on **Consumption plan** (confirmed from codebase)
- Consumption plan Functions **cannot** use VNet integration
- Functions need to access:
  - PostgreSQL (VNet-integrated, public access disabled)
  - Redis (private endpoint)
  - Cosmos DB (private endpoint)
  - Key Vault (network rules)
  - Service Bus (private endpoint)

**Impact:**
- Functions cannot directly access VNet-integrated resources
- Requires public access or private endpoints for all dependencies

**Solution:**
- **Dev:** Enable public access with firewall rules (IP allowlist)
- **Prod:** Use private endpoints for all Function dependencies

---

### Issue 2: PostgreSQL VNet Integration vs Private Endpoint

**Current Configuration:**
- PostgreSQL uses **VNet integration** (delegated subnet)
- `publicNetworkAccess: 'Disabled'`
- Requires `delegatedSubnetResourceId`

**Problem:**
- Functions (Consumption) cannot access VNet-integrated PostgreSQL
- External access requires Azure Bastion or VPN

**Solution:**
- **Dev:** Enable `publicNetworkAccess: 'Enabled'` with firewall rules
- **Prod:** Keep VNet integration + add private endpoint for Functions

---

### Issue 3: Static Web Apps Cannot Be Made Private

**Problem:**
- Static Web Apps are **always public** (Azure limitation)
- Cannot use private endpoints or VNet integration
- Frontend must be accessible from internet

**Solution:**
- Use **APIM with authentication** (Microsoft Entra ID) to protect backend APIs
- Static Web Apps → APIM (authenticated) → Backend APIs
- Frontend remains public, but APIs are protected

---

### Issue 4: Data Factory Managed VNet Connectivity

**Current Configuration:**
- Data Factory uses **Managed Virtual Network** with private endpoints
- Requires private endpoints for all linked services

**Problem:**
- Private endpoints must be created for:
  - Storage Account
  - Data Lake
  - Key Vault
  - Service Bus
  - PostgreSQL (if used)

**Solution:**
- **Dev:** Can use public access with firewall rules (simpler)
- **Prod:** Use Managed VNet with private endpoints (required)

---

### Issue 5: Cosmos DB (MongoDB) Network Access

**Current Configuration:**
- Cosmos DB has `publicNetworkAccess: 'Enabled'`
- `networkAclBypass: 'AzureServices'`

**Problem:**
- Functions need to access Cosmos DB
- Should use private endpoint for production

**Solution:**
- **Dev:** Keep public access with firewall rules
- **Prod:** Add private endpoint + disable public access

---

### Issue 6: Service Bus Network Access

**Current Configuration:**
- Service Bus Standard/Premium SKU
- Public access enabled by default

**Problem:**
- Functions and Data Factory need access
- Should use private endpoint for production

**Solution:**
- **Dev:** Keep public access with firewall rules
- **Prod:** Add private endpoint + disable public access

---

### Issue 7: Key Vault Network Rules

**Current Configuration:**
- Key Vault has `publicNetworkAccess: 'Enabled'`
- Network rules can be configured

**Problem:**
- Functions need access from internet (Consumption plan)
- Should restrict access in production

**Solution:**
- **Dev:** Allow all Azure services + developer IPs
- **Prod:** Use private endpoint + restrict to VNet only

---

### Issue 8: Storage Account Network Rules

**Current Configuration:**
- Storage Account has `defaultAction: 'Deny'`
- Virtual network rules configured
- Service endpoints enabled

**Problem:**
- Functions (Consumption) cannot use service endpoints
- Need public access or private endpoint

**Solution:**
- **Dev:** Add developer IPs to network rules
- **Prod:** Add private endpoint for Functions

---

### Issue 9: Developer Access to VNet Resources

**Problem:**
- 6 developers need access to:
  - PostgreSQL (VNet-integrated)
  - Redis (private endpoint)
  - Cosmos DB (private endpoint)
  - Storage Account (network rules)

**Solution:**
- **Azure Bastion** (recommended):
  - Create Bastion host in VNet
  - Developers connect via RDP/SSH through Bastion
  - No VPN required
- **Point-to-Site VPN** (alternative):
  - Azure VPN Gateway
  - Developers install VPN client
  - More complex setup

---

### Issue 10: AKS to Function Communication

**Problem:**
- AKS pods may need to call Functions
- Functions are public (Consumption plan)
- Should be authenticated

**Solution:**
- Use **Function Keys** or **Managed Identity** authentication
- APIM can proxy Function calls with authentication
- Functions should validate requests

---

### Issue 11: TLS 1.3 Platform Limitations

**Problem:**
- SoW requires TLS 1.3 for all communications
- However, some Azure services **do not support TLS 1.3**:
  - **Azure Redis Cache:** Only supports TLS 1.2 (platform limitation)
  - **Azure Service Bus:** Only supports TLS 1.2 (platform limitation)

**Impact:**
- Cannot achieve 100% TLS 1.3 compliance
- Redis and Service Bus connections will use TLS 1.2
- This is a **known Azure platform limitation**, not a configuration issue

**Solution:**
- **Document as exception:** TLS 1.2 for Redis and Service Bus is acceptable due to platform limitations
- **All other services:** Use TLS 1.3 where supported (Storage, Data Lake, PostgreSQL, etc.)
- **Compliance note:** Document this exception in security compliance documentation

**References:**
- See `project_documentation/Planning_phase/TLS_1.3_UPGRADE_MAPPING.md` for full analysis
- See `azure-infrastructure/docs/BICEP_CHANGELOG.md` sections 9 and 13 for deployment history

---

## Solutions by Environment

### Development Environment

**Goal:** Easy access for 6 developers, simplified networking

#### Network Configuration

1. **PostgreSQL:**
   ```bicep
   publicNetworkAccess: 'Enabled'
   firewallRules: [
     // Developer IPs
     // Azure services
   ]
   ```

2. **Redis:**
   ```bicep
   publicNetworkAccess: 'Enabled'
   firewallRules: [
     // Developer IPs
   ]
   ```

3. **Cosmos DB:**
   ```bicep
   publicNetworkAccess: 'Enabled'
   ipRules: [
     // Developer IPs
   ]
   ```

4. **Key Vault:**
   ```bicep
   publicNetworkAccess: 'Enabled'
   networkAcls: {
     defaultAction: 'Allow'
     bypass: 'AzureServices'
   }
   ```

5. **Storage Account:**
   ```bicep
   networkAcls: {
     defaultAction: 'Allow'
     bypass: 'AzureServices'
     virtualNetworkRules: [] // Optional
   }
   ```

6. **Service Bus:**
   ```bicep
   publicNetworkAccess: 'Enabled'
   // No firewall rules (allow all)
   ```

7. **Functions:**
   - Keep Consumption plan
   - Access all services via public endpoints (with firewall rules)

8. **Data Factory:**
   - Use public access (no Managed VNet)
   - Firewall rules for linked services

9. **Azure Bastion:**
   - Deploy Bastion host for developer access
   - Connect to VNet resources via Bastion

#### NSG Rules (More Permissive)

```bicep
// Dev NSG Rules - More permissive
rules: [
  {
    name: 'AllowHTTPS'
    priority: 100
    source: '*'
    destinationPort: 443
    access: 'Allow'
  }
  {
    name: 'AllowHTTP'
    priority: 110
    source: '*'
    destinationPort: 80
    access: 'Allow'
  }
  {
    name: 'AllowPostgres'
    priority: 120
    source: 'VirtualNetwork'
    destinationPort: 5432
    access: 'Allow'
  }
]
```

---

### Production Environment

**Goal:** Maximum security, private endpoints, network isolation

#### Network Configuration

1. **PostgreSQL:**
   ```bicep
   publicNetworkAccess: 'Disabled'
   delegatedSubnetResourceId: '<data-subnet-id>'
   privateDnsZoneId: '<private-dns-zone-id>'
   // Private endpoint for Functions
   ```

2. **Redis:**
   ```bicep
   publicNetworkAccess: 'Disabled'
   // Private endpoint required
   ```

3. **Cosmos DB:**
   ```bicep
   publicNetworkAccess: 'Disabled'
   // Private endpoint required
   ```

4. **Key Vault:**
   ```bicep
   publicNetworkAccess: 'Disabled'
   // Private endpoint required
   ```

5. **Storage Account:**
   ```bicep
   networkAcls: {
     defaultAction: 'Deny'
     virtualNetworkRules: [
       // VNet subnets only
     ]
   }
   // Private endpoint for Functions
   ```

6. **Service Bus:**
   ```bicep
   publicNetworkAccess: 'Disabled'
   // Private endpoint required
   ```

7. **Functions:**
   - Keep Consumption plan
   - Access all services via **private endpoints**
   - Cannot use VNet integration

8. **Data Factory:**
   - Use **Managed Virtual Network** with private endpoints
   - All linked services via private endpoints

9. **Azure Bastion:**
   - Deploy Bastion host for admin access
   - Restrict Bastion access to specific IPs

#### NSG Rules (Restrictive)

```bicep
// Prod NSG Rules - Deny by default
rules: [
  {
    name: 'AllowHTTPS'
    priority: 100
    source: 'AzureLoadBalancer'
    destinationPort: 443
    access: 'Allow'
  }
  {
    name: 'AllowK8sAPI'
    priority: 110
    source: 'VirtualNetwork'
    destinationPort: 6443
    access: 'Allow'
  }
  {
    name: 'DenyAllInbound'
    priority: 4096
    source: '*'
    access: 'Deny'
  }
]
```

---

## Implementation Steps

### Step 1: Deploy Azure Bastion (Both Environments)

**Bicep Template Addition:**

```bicep
// Add to networking/vnet.bicep

@description('Enable Azure Bastion')
param enableBastion bool = true

@description('Bastion subnet address prefix')
param bastionSubnetPrefix string = '10.0.8.0/27' // /27 = 32 IPs (minimum for Bastion)

// Bastion Subnet
resource bastionSubnet 'Microsoft.Network/virtualNetworks/subnets@2023-05-01' = if (enableBastion) {
  parent: vnet
  name: 'AzureBastionSubnet'
  properties: {
    addressPrefix: bastionSubnetPrefix
  }
}

// Public IP for Bastion
resource bastionPublicIp 'Microsoft.Network/publicIPAddresses@2023-05-01' = if (enableBastion) {
  name: '${namingPrefix}-bastion-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

// Azure Bastion
resource bastion 'Microsoft.Network/bastionHosts@2023-05-01' = if (enableBastion) {
  name: '${namingPrefix}-bastion'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'bastion-ipconfig'
        properties: {
          subnet: {
            id: bastionSubnet.id
          }
          publicIPAddress: {
            id: bastionPublicIp.id
          }
        }
      }
    ]
  }
}
```

**Deployment:**

```powershell
# Deploy Bastion
az deployment group create `
  --resource-group $RG_NETWORKING `
  --template-file bicep-templates/networking/vnet.bicep `
  --parameters enableBastion=true bastionSubnetPrefix="10.0.8.0/27"
```

---

### Step 2: Configure Development Environment

#### 2.1: Enable Public Access for PostgreSQL

**Update `data-services.bicep`:**

```bicep
@description('Enable public access (dev only)')
param enablePublicAccess bool = environment == 'dev'

resource postgresServer 'Microsoft.DBforPostgreSQL/flexibleServers@2022-12-01' = {
  // ... existing config ...
  properties: {
    publicNetworkAccess: enablePublicAccess ? 'Enabled' : 'Disabled'
    // ... rest of config ...
  }
}

// Add firewall rules for dev
resource postgresFirewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2022-12-01' = if (enablePublicAccess) {
  parent: postgresServer
  name: 'AllowAzureServices'
  properties: {
    startIpAddress: '0.0.0.0'
    endIpAddress: '0.0.0.0'
  }
}
```

#### 2.2: Enable Public Access for Redis

**Update `data-services.bicep`:**

```bicep
resource redisCache 'Microsoft.Cache/redis@2023-04-01' = {
  // ... existing config ...
  properties: {
    publicNetworkAccess: enablePublicAccess ? 'Enabled' : 'Disabled'
    // ... rest of config ...
  }
}
```

#### 2.3: Configure Cosmos DB Firewall

**Update `mongodb.bicep`:**

```bicep
resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  // ... existing config ...
  properties: {
    publicNetworkAccess: enablePublicAccess ? 'Enabled' : 'Disabled'
    networkAclBypass: 'AzureServices'
    ipRules: enablePublicAccess ? [
      // Add developer IPs here
    ] : []
  }
}
```

---

### Step 3: Configure Production Environment

#### 3.1: Add Private Endpoints for Functions

**Create `private-endpoints.bicep`:**

```bicep
// Private endpoints for Functions to access PaaS services

// Private Endpoint for PostgreSQL (for Functions)
resource postgresPrivateEndpointForFunctions 'Microsoft.Network/privateEndpoints@2023-05-01' = {
  name: '${postgresServerName}-pe-functions'
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
          groupIds: ['postgresqlServer']
        }
      }
    ]
  }
}

// Private Endpoint for Redis (for Functions)
resource redisPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = {
  name: '${redisName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${redisName}-connection'
        properties: {
          privateLinkServiceId: redisCache.id
          groupIds: ['redisCache']
        }
      }
    ]
  }
}

// Private Endpoint for Cosmos DB (for Functions)
resource cosmosPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = {
  name: '${cosmosAccountName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${cosmosAccountName}-connection'
        properties: {
          privateLinkServiceId: cosmosAccount.id
          groupIds: ['MongoDB']
        }
      }
    ]
  }
}

// Private Endpoint for Service Bus (for Functions)
resource serviceBusPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-05-01' = {
  name: '${serviceBusNamespaceName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: {
      id: privateEndpointsSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: '${serviceBusNamespaceName}-connection'
        properties: {
          privateLinkServiceId: serviceBusNamespace.id
          groupIds: ['namespace']
        }
      }
    ]
  }
}

// Private Endpoint for Storage Account (for Functions)
resource storagePrivateEndpointForFunctions 'Microsoft.Network/privateEndpoints@2023-05-01' = {
  name: '${storageAccountName}-pe-functions'
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
          groupIds: ['blob']
        }
      }
    ]
  }
}
```

#### 3.2: Configure Data Factory Managed VNet

**Update `data-factory.bicep`:**

```bicep
resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' = {
  // ... existing config ...
  properties: {
    publicNetworkAccess: environment == 'prod' ? 'Disabled' : 'Enabled'
    // ... rest of config ...
  }
}

// Enable Managed Virtual Network (prod only)
resource managedVNet 'Microsoft.DataFactory/factories/managedVirtualNetworks@2018-06-01' = if (environment == 'prod') {
  parent: dataFactory
  name: 'default'
  properties: {}
}

// Create private endpoints for Data Factory
// (Add private endpoint resources here)
```

---

### Step 4: Update Function App Configuration

**Functions need connection strings updated for private endpoints:**

```powershell
# For Production - Update Function App connection strings to use private endpoints

# PostgreSQL connection string (use private endpoint FQDN)
$POSTGRES_PRIVATE_FQDN = "<org>-<project>-<environment>-postgres.privatelink.postgres.database.azure.com"
$POSTGRES_CONNECTION_STRING = "postgresql://user:pass@$POSTGRES_PRIVATE_FQDN:5432/credit_scoring"

# Redis connection string (use private endpoint FQDN)
$REDIS_PRIVATE_FQDN = "<org>-<project>-<environment>-redis.redis.cache.windows.net"
$REDIS_CONNECTION_STRING = "$REDIS_PRIVATE_FQDN:6380,ssl=true"

# Cosmos DB connection string (use private endpoint FQDN)
$COSMOS_PRIVATE_FQDN = "<org>-<project>-<environment>-cosmos.mongo.cosmos.azure.com"
$COSMOS_CONNECTION_STRING = "mongodb://$COSMOS_PRIVATE_FQDN:10255/?ssl=true"

# Update Function App settings
az functionapp config appsettings set `
  --name $FUNCTION_APP_NAME `
  --resource-group $RG_AGENTS `
  --settings `
    POSTGRES_CONNECTION_STRING="$POSTGRES_CONNECTION_STRING" `
    REDIS_CONNECTION_STRING="$REDIS_CONNECTION_STRING" `
    MONGODB_CONNECTION_STRING="$COSMOS_CONNECTION_STRING"
```

**Note:** Functions on Consumption plan cannot resolve private endpoint FQDNs from internet. You need to:
1. Use **Azure DNS Private Zones** (already configured)
2. Functions will resolve via Azure's DNS (works for Consumption plan)
3. Or use **Azure Private DNS Resolver** (advanced)

---

### Step 5: Configure Static Web Apps with APIM Authentication

**Static Web Apps → APIM → Backend APIs**

**APIM Policy for Authentication:**

```xml
<!-- Add to APIM policy -->
<policies>
  <inbound>
    <base />
    <!-- Authenticate requests from Static Web Apps -->
    <validate-jwt header-name="Authorization" failed-validation-httpcode="401">
      <openid-config url="https://login.microsoftonline.com/{tenant-id}/v2.0/.well-known/openid-configuration" />
      <audiences>
        <audience>{client-id}</audience>
      </audiences>
      <issuers>
        <issuer>https://login.microsoftonline.com/{tenant-id}/v2.0</issuer>
      </issuers>
    </validate-jwt>
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
</policies>
```

**Static Web Apps Configuration:**

```json
{
  "routes": [
    {
      "route": "/api/*",
      "allowedRoles": ["authenticated"]
    }
  ],
  "navigationFallback": {
    "rewrite": "/index.html",
    "exclude": ["/api/*"]
  },
  "auth": {
    "identityProviders": {
      "azureActiveDirectory": {
        "registration": {
          "openIdIssuer": "https://login.microsoftonline.com/{tenant-id}/v2.0",
          "clientIdSettingName": "AZURE_CLIENT_ID",
          "clientSecretSettingName": "AZURE_CLIENT_SECRET"
        }
      }
    }
  }
}
```

---

## Testing Procedures

### Test 1: Developer Access via Bastion

```powershell
# Connect to PostgreSQL via Bastion
az network bastion ssh `
  --name $BASTION_NAME `
  --resource-group $RG_NETWORKING `
  --target-resource-id $VM_RESOURCE_ID `
  --auth-type password `
  --username $VM_USERNAME

# From VM, connect to PostgreSQL
psql -h $POSTGRES_FQDN -U $POSTGRES_USER -d credit_scoring
```

### Test 2: Function to PostgreSQL Connection

```powershell
# Test Function connectivity
az functionapp function invoke `
  --name $FUNCTION_APP_NAME `
  --resource-group $RG_AGENTS `
  --function-name TestPostgresConnection

# Check Function logs
az functionapp log tail `
  --name $FUNCTION_APP_NAME `
  --resource-group $RG_AGENTS
```

### Test 3: Data Factory Pipeline Execution

```powershell
# Trigger Data Factory pipeline
az datafactory pipeline create-run `
  --factory-name $DATA_FACTORY_NAME `
  --resource-group $RG_DATA `
  --pipeline-name "TestPipeline"

# Monitor pipeline run
az datafactory pipeline-run query-by-factory `
  --factory-name $DATA_FACTORY_NAME `
  --resource-group $RG_DATA `
  --last-updated-after (Get-Date).AddMinutes(-10) `
  --last-updated-before (Get-Date)
```

### Test 4: Private Endpoint Connectivity

```powershell
# Test private endpoint resolution
nslookup $POSTGRES_PRIVATE_FQDN
# Should resolve to private IP (10.0.7.x)

# Test connectivity from AKS pod
kubectl exec -it <pod-name> -n <namespace> -- nslookup $POSTGRES_PRIVATE_FQDN
```

---

## Summary of Changes Required

### Development Environment

1. ✅ Enable public access for PostgreSQL, Redis, Cosmos DB
2. ✅ Add firewall rules for developer IPs
3. ✅ Deploy Azure Bastion for VNet access
4. ✅ Relax NSG rules (allow HTTPS from internet)
5. ✅ Keep Functions on Consumption plan (public access)

### Production Environment

1. ✅ Keep PostgreSQL VNet-integrated
2. ✅ Add private endpoints for all Function dependencies
3. ✅ Configure Data Factory Managed VNet with private endpoints
4. ✅ Deploy Azure Bastion (restricted access)
5. ✅ Strict NSG rules (deny by default)
6. ✅ Configure Static Web Apps → APIM → Backend (with auth)

---

## Additional Clarification Questions

Before finalizing the implementation, please confirm:

1. **Developer IP Addresses:** Can you provide the public IP addresses of the 6 developers for firewall rules?

2. **Function Private Endpoint DNS Resolution:** 
   - Do you want to use Azure DNS Private Zones (recommended)?
   - Or use Azure Private DNS Resolver (more complex)?

3. **Static Web Apps Authentication:**
   - Use Microsoft Entra ID (Azure AD) for authentication?
   - Or use APIM subscription keys?

4. **Bastion Access Control:**
   - Restrict Bastion access to specific IPs in production?
   - Or allow from any IP (less secure)?

5. **Cost Considerations:**
   - Private endpoints cost ~$7.50/month each
   - Are you okay with ~$50-75/month for private endpoints in production?

---

**Document Version:** 1.0  
**Last Updated:** 2025-01-28  
**Author:** Infrastructure Analysis
