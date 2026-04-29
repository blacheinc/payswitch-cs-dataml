# Azure Infrastructure - Phase 1 Index

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [File Structure](#file-structure)
3. [Key Files](#key-files)
4. [Deployment Steps](#deployment-steps)
5. [What's Included](#whats-included)

## 🚀 Quick Start

**New to this project? Start here:**

1. Read [QUICKSTART.md](QUICKSTART.md) - Deploy in 15 minutes
2. Read [README.md](README.md) - Comprehensive guide
3. Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - Technical details

## 📁 File Structure

```
azure-infrastructure/
├── INDEX.md (this file)          # Navigation guide
├── README.md                     # Main documentation
├── QUICKSTART.md                 # 15-minute deployment guide
│
├── bicep-templates/              # Infrastructure as Code
│   ├── main.bicep               # Main orchestration template
│   ├── main.parameters.json     # Configuration parameters
│   │
│   ├── networking/
│   │   └── vnet.bicep           # Virtual Network, Subnets, NSGs
│   │
│   ├── security/
│   │   └── keyvault.bicep       # Key Vault, Managed Identities
│   │
│   ├── data/
│   │   └── data-services.bicep  # PostgreSQL, Redis, Storage, Data Lake
│   │
│   ├── compute/
│   │   ├── aks.bicep            # Azure Kubernetes Service
│   │   └── ml-workspace.bicep   # Azure ML Workspace
│   │
│   └── monitoring/
│       └── monitoring.bicep     # Log Analytics, Application Insights
│
├── scripts/                      # Automation scripts
│   ├── deploy.sh                # Automated deployment
│   └── destroy.sh               # Cleanup script
│
├── docs/                         # Documentation
│   └── ARCHITECTURE.md          # Detailed architecture guide
│
└── config/                       # Configuration files (future use)
```

## 🔑 Key Files

### For Deployment

| File | Purpose | When to Use |
|------|---------|-------------|
| [QUICKSTART.md](QUICKSTART.md) | Fast deployment guide | First-time deployment |
| [scripts/deploy.sh](scripts/deploy.sh) | Automated deployment script | Production deployments |
| [bicep-templates/main.parameters.json](bicep-templates/main.parameters.json) | Configuration | Customize settings |

### For Understanding

| File | Purpose | When to Read |
|------|---------|--------------|
| [README.md](README.md) | Complete guide | Comprehensive overview |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture details | Technical deep dive |
| [../AZURE_MIGRATION_PLAN.md](../AZURE_MIGRATION_PLAN.md) | Full project plan | Project planning |

### For Development

| File | Purpose | When to Edit |
|------|---------|--------------|
| [bicep-templates/main.bicep](bicep-templates/main.bicep) | Infrastructure orchestration | Major changes |
| [bicep-templates/networking/vnet.bicep](bicep-templates/networking/vnet.bicep) | Network configuration | Network changes |
| [bicep-templates/data/data-services.bicep](bicep-templates/data/data-services.bicep) | Data layer | Database changes |

## 📝 Deployment Steps

### Option 1: Quick Deploy (Recommended for Dev)

```bash
cd scripts
./deploy.sh
```

**Time:** 20-30 minutes

### Option 2: Step-by-Step (Recommended for Production)

```bash
# 1. Login
az login

# 2. Configure parameters
nano bicep-templates/main.parameters.json

# 3. Validate
az deployment sub validate \
  --location eastus \
  --template-file bicep-templates/main.bicep \
  --parameters @bicep-templates/main.parameters.json \
  --name creditscore-deployment

# 4. Deploy
az deployment sub create \
  --location eastus \
  --template-file bicep-templates/main.bicep \
  --parameters @bicep-templates/main.parameters.json \
  --name creditscore-deployment
```

**Time:** 20-30 minutes

## 📦 What's Included in Phase 1

### ✅ Completed

- [x] **Network Infrastructure**
  - Virtual Network with 7 subnets
  - Network Security Groups
  - Service endpoints

- [x] **Security Foundation**
  - Azure Key Vault (Premium)
  - Managed Identities
  - Secret placeholders

- [x] **Data Layer**
  - PostgreSQL Flexible Server (3 databases)
  - Azure Cache for Redis
  - Storage Account
  - Data Lake Gen2 (3 containers)

- [x] **Compute Infrastructure**
  - AKS Cluster (multi-AZ)
  - Azure Container Registry
  - GPU node pool (optional)

- [x] **ML Platform**
  - Azure ML Workspace (Enterprise)
  - CPU Compute Cluster
  - GPU Compute Cluster
  - Compute Instance

- [x] **Monitoring**
  - Log Analytics Workspace
  - Application Insights
  - Alert Action Groups
  - Custom workbooks

### 🔜 Coming in Phase 2 (Data Ingestion)

- [ ] Azure Data Factory pipelines
- [ ] Data Quality Agent (Azure Function)
- [ ] Feature Engineering Agent
- [ ] MongoDB deployment
- [ ] Service Bus for agent communication

### 🔜 Coming in Phase 3 (Agentic AI Core)

- [ ] 7 AI Agents deployed
- [ ] Agent orchestrator
- [ ] LangChain/LangGraph integration
- [ ] Azure OpenAI Service
- [ ] Model training pipelines

## 🎯 Quick Links

### Documentation
- [Main README](README.md) - Start here
- [Quick Start Guide](QUICKSTART.md) - Deploy in 15 min
- [Architecture Deep Dive](docs/ARCHITECTURE.md) - Technical details
- [Migration Plan](../AZURE_MIGRATION_PLAN.md) - Full roadmap

### Deployment
- [Deploy Script](scripts/deploy.sh) - Automated deployment
- [Destroy Script](scripts/destroy.sh) - Cleanup
- [Main Template](bicep-templates/main.bicep) - Infrastructure code
- [Parameters File](bicep-templates/main.parameters.json) - Configuration

### Azure Services
| Service | Purpose | Cost (Dev) |
|---------|---------|------------|
| AKS | Container orchestration | $140/mo |
| Azure ML | Model training | $50/mo |
| PostgreSQL | Relational database | $30/mo |
| Redis | Caching | $16/mo |
| Storage | Data Lake + Blob | $20/mo |
| Monitoring | Observability | $100/mo |

**Total Dev Environment:** ~$450/month

## 🔐 Security Highlights

- ✅ All data encrypted at rest (AES-256)
- ✅ All data encrypted in transit (TLS 1.2+)
- ✅ Managed identities (no passwords)
- ✅ Private network for databases
- ✅ Key Vault for secrets
- ✅ RBAC enabled
- ✅ Network Security Groups
- ✅ Diagnostic logging enabled

## 📊 Monitoring Highlights

- ✅ Application Insights for APM
- ✅ Log Analytics for logs
- ✅ Container Insights for AKS
- ✅ Email alerts configured
- ✅ 90-day log retention
- ✅ Custom dashboards ready

## 🆘 Need Help?

### Documentation
1. **Can't deploy?** → Read [QUICKSTART.md](QUICKSTART.md)
2. **Need details?** → Read [README.md](README.md)
3. **Architecture questions?** → Read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

### Commands
```bash
# Check deployment status
az deployment sub show --name creditscore-deployment

# List resources
az resource list --output table

# Get AKS credentials
az aks get-credentials --name <aks-name> --resource-group <rg-name>
```

### Support
- **PaySwitch:** ops@payswitch.com.gh
- **Blache:** support@blache.com
- **Azure:** https://portal.azure.com/#blade/Microsoft_Azure_Support/HelpAndSupportBlade

## 📈 What's Next?

After Phase 1 deployment is successful:

1. ✅ **Verify deployment** using [QUICKSTART.md verification section](QUICKSTART.md#verification-5-minutes)
2. ✅ **Review architecture** in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
3. ⏭️ **Proceed to Phase 2** - Data Ingestion & Feature Engineering
4. ⏭️ **Proceed to Phase 3** - Agentic AI Framework & ML Models

---

**Phase 1 Status:** ✅ Complete - Ready for Phase 2
**Last Updated:** 2025-11-12
**Maintained By:** Blache Ltd
