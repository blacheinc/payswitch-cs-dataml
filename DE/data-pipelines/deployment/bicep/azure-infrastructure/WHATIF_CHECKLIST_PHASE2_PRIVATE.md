# What-If Checklist (Phase 2 Private)

Run these checks before any apply deployment.

## 1) Service Bus contract + private posture

```powershell
az deployment group what-if `
  --resource-group blache-cdtscr-dev-data-rg `
  --template-file credit-scoring/phase2-data-ingestion/service-bus/service-bus.bicep `
  --parameters @credit-scoring/phase2-data-ingestion/service-bus/parameters/dev.parameters.json
```

## 2) Data Factory contract alignment

```powershell
az deployment group what-if `
  --resource-group blache-cdtscr-dev-data-rg `
  --template-file credit-scoring/phase2-data-ingestion/azure-data-factory/data-factory.bicep `
  --parameters @credit-scoring/phase2-data-ingestion/azure-data-factory/parameters/dev.parameters.json
```

## 3) Private endpoints + private DNS

```powershell
az deployment group what-if `
  --resource-group blache-cdtscr-dev-data-rg `
  --template-file credit-scoring/phase2-data-ingestion/private-network/private-endpoints.bicep `
  --parameters @credit-scoring/phase2-data-ingestion/private-network/parameters/dev.parameters.json
```

## 4) Premium Functions

```powershell
az deployment group what-if `
  --resource-group blache-cdtscr-dev-data-rg `
  --template-file credit-scoring/phase2-data-ingestion/functions/functions-premium.bicep `
  --parameters @credit-scoring/phase2-data-ingestion/functions/parameters/dev.parameters.json
```

## 5) Optional hardening checks (core templates also updated)

```powershell
az deployment group what-if `
  --resource-group blache-cdtscr-dev-data-rg `
  --template-file credit-scoring/azure-infrastructure/bicep-templates/data/data-services.bicep `
  --parameters privateNetworkMode=true
```

```powershell
az deployment group what-if `
  --resource-group blache-cdtscr-dev-security-rg `
  --template-file credit-scoring/azure-infrastructure/bicep-templates/security/keyvault.bicep `
  --parameters privateNetworkMode=true
```

## One-command helper

Use:

`credit-scoring/azure-infrastructure/scripts/whatif-phase2-private.ps1`
