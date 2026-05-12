# Data Pipelines Start Here

This is the top-level execution map for both onboarding and release operations.

## End-to-end execution order

1. Core infrastructure deploy (`main.bicep`)
2. **Hydrate Phase 2 parameter JSON — pass 1** — script: `deployment/bicep/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1` (run from `$SCRIPTS`; pass `-SubscriptionDeploymentName` from step 1). Updates **all** Phase 2 modules’ parameter files under `deployment/bicep/phase2-data-ingestion/`, not only Functions. Do **not** commit tenant-filled JSON if policy forbids it.
3. Phase 2 deploy (Service Bus, ADF, private endpoints when used, Functions hosting)
4. **Hydrate Phase 2 parameter JSON — pass 2** — same script and deployment name; refreshes values that depend on Phase 2–created resources (for example Service Bus name for ADF). Same Git caution.
5. Day 2 updates (rules, storage paths, IAM, PostgreSQL artifacts)
6. Function app code deployments (in order):
   1. `file-checksum-calculator`
   2. `training-data-ingestion`
   3. `schema-mapping-service`
   4. `transformation-service`
   5. `adf-pipeline-trigger`
7. ADF completion runbook (dependency readiness + IAM verification + promotion steps)
8. Mandatory validation and smoke checks

## Environment paths

After setting **`$ENVIRONMENT`** in PowerShell (same variable as the deployment guides):

- **Default / non-private footprint:** `deployment/bicep/azure-infrastructure/docs/DEPLOYMENT_GUIDE.md` and `deployment/bicep/azure-infrastructure/docs/DAY2_UPDATES.md`
- **Private connectivity footprint:** `deployment/bicep/azure-infrastructure/docs/PRIVATE_DEPLOYMENT_GUIDE.md` and `deployment/bicep/azure-infrastructure/docs/PRIVATE_DAY2_UPDATES.md`

## Entity-to-doc matrix (required docs by execution entity)

| Execution entity | Required docs |
|---|---|
| Core infrastructure (`main.bicep`) | `deployment/bicep/azure-infrastructure/docs/DEPLOYMENT_GUIDE.md` or `deployment/bicep/azure-infrastructure/docs/PRIVATE_DEPLOYMENT_GUIDE.md` (pick one track; keep **`$ENVIRONMENT`** consistent), `deployment/bicep/azure-infrastructure/docs/HOW_DEPLOYMENT_FITS_TOGETHER.md` |
| Phase 2 parameter hydration (after `main.bicep` + after Phase 2) | `deployment/bicep/azure-infrastructure/scripts/hydrate-phase2-parameters.ps1`; same deployment guide you chose above, `deployment/bicep/phase2-data-ingestion/README.md`, `deployment/bicep/phase2-data-ingestion/functions/parameters/README.md` |
| Phase 2 (`phase2-data-ingestion` Bicep deploy) | same deployment guide above, `deployment/bicep/phase2-data-ingestion/README.md` |
| Day 2 updates | `deployment/bicep/azure-infrastructure/docs/DAY2_UPDATES.md` or `PRIVATE_DAY2_UPDATES.md` (match the deployment guide track), `deployment/bicep/day2-updates/README.md` |
| ADF completion and dependency checks | `deployment/bicep/phase2-data-ingestion/azure-data-factory/ADF_COMPLETION_RUNBOOK.md`, `deployment/adf/README.md`, `deployment/bicep/phase2-data-ingestion/azure-data-factory/live-export/README.md` |
| Function deployment + local runbooks | `functions/DEPLOYMENT_RUNBOOK.md`, `functions/training-data-ingestion/RUNBOOK_POWERSHELL.md`, `functions/schema-mapping-service/RUNBOOK_POWERSHELL.md`, `functions/transformation-service/RUNBOOK_POWERSHELL.md`, `functions/adf-pipeline-trigger/README.md`, `functions/file-checksum-calculator/README.md` |
| Config templates and secret naming conventions | `functions/CONFIG_EXAMPLES.md`, `deployment/artifacts/day2/kv/secret-manifest.prod.json` |

## Mandatory validation gates

Before sign-off, all are required:

1. Infra deployments show `Succeeded` for main + Phase 2 + Day 2.
2. Function apps are deployed and discoverable (`az functionapp function list`).
3. ADF dependencies pass exists/healthy checks in `ADF_COMPLETION_RUNBOOK.md`.
4. ADF IAM checks pass (Storage, Key Vault, Service Bus).
5. PostgreSQL artifact precheck + apply completed.
6. End-to-end smoke path succeeds:
   - ingestion message path
   - schema mapping handoff
   - transformation outputs/handoffs
