# Phase 2 Private Deployment Guide

This guide wires the updated modules for private networking and premium function hosting.

## Modules Covered

- `phase2-data-ingestion/service-bus/service-bus.bicep`
- `phase2-data-ingestion/azure-data-factory/data-factory.bicep`
- `phase2-data-ingestion/private-network/private-endpoints.bicep`
- `phase2-data-ingestion/functions/functions-premium.bicep`

## Parameter Files

Use environment-specific parameters in each module folder:

- `parameters/dev.parameters.json`
- `parameters/staging.parameters.json`
- `parameters/prod.parameters.json`

## Deployment Order

1. Service Bus (private mode)
2. Data Factory (private mode + live-linked-service compatibility)
3. Private Endpoints + private DNS
4. Premium Functions (plan + apps + private endpoints)

## Dry Run First

Run `credit-scoring/azure-infrastructure/scripts/whatif-phase2-private.ps1` before any deployment.

## Auto-hydrate Parameters

Populate environment parameter files from live Azure resources:

`credit-scoring/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1`

## Apply (When Ready)

Run `credit-scoring/azure-infrastructure/scripts/deploy-phase2-private.ps1`.

## Full Module-by-Module Command Guide

For all individual module commands (not using `main.bicep`), use:

`credit-scoring/azure-infrastructure/INDIVIDUAL_RESOURCE_DEPLOYMENT_GUIDE.md`
