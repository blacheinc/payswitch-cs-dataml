# How deployment fits together

This document is the **map** for the Bicep deployment tree under `data-pipelines/deployment/`. Use it when you need to know **which folder applies which change**, and **which guide matches your environment**.

## Canonical operator guides (start here)

All live in this directory (`docs/`):

| Document | When to use |
|----------|-------------|
| `DEPLOYMENT_GUIDE.md` | Default **`dev`** path with an environment toggle pattern (`dev`/`prod`) for naming/parameter selection; for private prod hardening, follow `PRIVATE_DEPLOYMENT_GUIDE.md`. |
| `PRIVATE_DEPLOYMENT_GUIDE.md` | **`prod`** path: `main.bicep` with prod parameters, Phase 2 private stack, hydration scripts as documented. |
| `DAY2_UPDATES.md` | Day 2 incremental updates with `day2-updates/parameters/dev/*`. |
| `PRIVATE_DAY2_UPDATES.md` | Same Day 2 track for **`prod`** parameters under `day2-updates/parameters/prod/*`. |

This file (`HOW_DEPLOYMENT_FITS_TOGETHER.md`) explains relationships and folder layout; it does not replace the step-by-step commands in the guides above.

## Glossary

| Term | Meaning |
|------|---------|
| **`main.bicep`** | Subscription-scoped orchestration under `azure-infrastructure/bicep-templates/main.bicep`. Creates resource groups and deploys core platform modules (network, data, security, compute hooks, optional AKS, Azure ML when enabled, and so on). |
| **Phase 2** | The **`phase2-data-ingestion/`** Bicep stack: integrations that sit on top of the core platform (service-centric modules and parameters under `parameters/`). Deployed at resource-group scope after `main.bicep` outputs exist. |
| **Day 2 updates** | The **`day2-updates/`** templates and scripts: targeted deltas such as Service Bus rules, storage containers and paths, Key Vault IAM, Functions storage/key RBAC, and PostgreSQL artifact apply. Parameters are split under `day2-updates/parameters/dev/` and `day2-updates/parameters/prod/`. |
| **`deployMlWorkspace`** | `main.bicep` parameter; **defaults to `true`** so the Azure Machine Learning workspace module runs in normal deployments. Set `false` only for exceptional cases. |
| **`deployAks`** | `main.bicep` parameter; **optional** by design. AKS is not required for the default data-path deployment unless you turn it on. |
| **`set-vars-from-main-deployment.ps1`** | Script in `azure-infrastructure/scripts/` that reads outputs from a named subscription deployment and populates PowerShell variables (resource groups, storage account names, and so on) for Phase 2 and Day 2 commands. |

## Repository layout (deployment-focused)

```text
data-pipelines/deployment/
├── adf/                                      # Curated pipeline JSON (review/promotion); see README there
│   └── pipeline-training-data-ingestion/
└── bicep/
    ├── README.md                             # One-line index of the three main areas
    ├── azure-infrastructure/
    │   ├── bicep-templates/                  # main.bicep + platform modules
    │   ├── scripts/                          # set-vars, deploy helpers, …
    │   │   └── testing/                      # Optional phase test + teardown scripts (see scripts/testing/README.md)
    │   ├── docs/                             # CANONICAL runbooks (this folder)
    │   │   └── archive/                      # Retired deep analysis (e.g. network connectivity)
    │   └── azure-devops/                     # ADO pipeline YAML + setup notes
    ├── phase2-data-ingestion/              # Phase 2 Bicep + parameters; includes azure-data-factory/
    └── day2-updates/                        # Day 2 modules, parameters, scripts
```

## `azure-infrastructure/scripts/`

Holds the **operational** PowerShell and shell entrypoints you run from a workstation: loading subscription deployment outputs, ordered Phase 2 deploy/what-if for private environments, and various small utilities. The deployment guides reference these by name. This is the first place to look for **“how do I run the next step after `main.bicep`?”**

## `azure-infrastructure/scripts/testing/`

**Optional** quality gates: phase-oriented shell/PowerShell tests and teardown orchestration (`test-and-teardown.sh`, `test-and-teardown.ps1`, per-phase test scripts, and `README_POWERSHELL.md` for Windows usage). These help validate that a subscription or resource-group deployment **behaves** as expected; they are **not** the same as the product integration tests under `functions/`. See `scripts/testing/README.md` for script inventory and intended scope.

## `azure-infrastructure/azure-devops/`

Pipeline definitions and ADO setup notes for teams that deploy through Azure DevOps. The **source of truth for human-driven deploys** remains `docs/DEPLOYMENT_GUIDE.md` and `docs/PRIVATE_DEPLOYMENT_GUIDE.md`.

## Azure Data Factory: `deployment/adf` vs `phase2/.../azure-data-factory`

| Location | What it is | When to use it |
|----------|------------|----------------|
| **`data-pipelines/deployment/adf/`** (e.g. `pipeline-training-data-ingestion/`) | A **small, reviewable** pipeline JSON (and related manifest) kept in Git as the “golden” definition for that pipeline. | When you need a clean diff of **pipeline logic** for PR review or promotion between tenants. |
| **`phase2-data-ingestion/azure-data-factory/`** | **Infrastructure-as-code** for the Data Factory **resource**: Bicep (`data-factory.bicep`), parameter JSON per environment, **`live-export/`** snapshots from the portal, and helper scripts such as `export-live-adf-assets.ps1`. The Bicep module deploys the factory, managed VNet / IR wiring, and linked services; **canonical pipeline JSON is applied by the Phase 2 deployment flow** after that foundation exists (see comments in `data-factory.bicep`). | When you deploy or reconcile **factory infrastructure** and linked services—not a second copy of the golden pipeline folder. |

So this is **not** meaningless duplication: one path is **pipeline contract** in Git; the other is **factory + wiring + export history** for Bicep-driven deployment.

Details: [deployment/adf/README.md](../../../adf/README.md) and [phase2-data-ingestion/README.md](../../phase2-data-ingestion/README.md).

Completion checklist and dependency verification: [phase2-data-ingestion/azure-data-factory/ADF_COMPLETION_RUNBOOK.md](../../phase2-data-ingestion/azure-data-factory/ADF_COMPLETION_RUNBOOK.md).

## Archived analysis

`docs/archive/CONNECTIVITY_ANALYSIS.md` (if present) is **retired** reference material for network posture studies. Prefer current module behavior and the private deployment guide for production connectivity decisions.

## End-to-end flow

The platform expects a **repeatable sequence**: establish the subscription footprint, wire integration modules, then apply incremental Day 2 updates whenever contracts or RBAC need to change.

```mermaid
flowchart LR
  subgraph A [1. Core platform]
    M[main.bicep]
  end
  subgraph B [2. Phase 2]
    P2[phase2-data-ingestion]
  end
  subgraph C [3. Day 2]
    D2[day2-updates]
  end
  M --> P2 --> D2
```

## Environment matrix (`dev` vs `prod`)

Use **`dev`** when you are deploying the standard development subscription flow. Use **`prod`** when deploying the private production pattern (stricter networking, jump host option, and prod-tuned parameters).

```mermaid
flowchart TB
  subgraph devTrack [dev track]
    DG[docs/DEPLOYMENT_GUIDE.md]
    P2D[phase2: dev parameters]
    D2D[day2-updates/parameters/dev]
    DG --> P2D --> D2D
  end
  subgraph prodTrack [prod track]
    PDG[docs/PRIVATE_DEPLOYMENT_GUIDE.md]
    P2P[phase2: prod parameters + private scripts]
    D2P[day2-updates/parameters/prod]
    PDG --> P2P --> D2P
  end
```

| Concern | dev | prod |
|--------|-----|------|
| Main deployment guide | `DEPLOYMENT_GUIDE.md` | `PRIVATE_DEPLOYMENT_GUIDE.md` |
| Phase 2 parameter file | under `phase2-data-ingestion/parameters/` for dev | `parameters/prod.parameters.json` and related private flow in the private guide |
| Day 2 guide | `DAY2_UPDATES.md` | `PRIVATE_DAY2_UPDATES.md` |
| Day 2 parameters directory | `day2-updates/parameters/dev/` | `day2-updates/parameters/prod/` |

**Networking posture:** Production is deployed with a **private-by-default** posture (for example, private endpoints and controlled ingress) as described in the private deployment guide and Bicep modules. Development uses the **standard dev** posture for day-to-day engineering. The two tracks share the same **template families**; they differ by **parameter sets**, **scripts**, and **verification steps** appropriate to each environment.

## Phase 2 vs Day 2 (when to use which)

| Layer | Typical contents | When it runs |
|-------|------------------|--------------|
| **Phase 2** | Integration modules bundled under `phase2-data-ingestion/` (with environment-specific parameters) | After `main.bicep` completes and you have resource group names and storage/service identities from outputs. |
| **Day 2** | Smaller, frequent updates: Service Bus rules, storage layout, Key Vault and Function RBAC, SQL artifacts | After Phase 2 (or when operational changes require a delta without redeploying the entire Phase 2 stack). |

## Outputs you rely on across stages

`main.bicep` exposes outputs (including **`mlWorkspaceName`** when the ML module deploys) consumed by verification steps in the deployment guides. Phase 2 and Day 2 commands assume you have run **`set-vars-from-main-deployment.ps1`** (or equivalent) so `$DATA_RG`, `$SECURITY_RG`, storage account variables, and related names resolve correctly.

## Where superseded material lives (local only)

The repository’s **`.gitignore`** excludes `**/deprecated/**` under the deployment tree and `data-pipelines/docs/deprecated/`, so that content is not published to the remote. On a fresh clone, only the guides in this `docs/` folder (and the function- or service-local runbooks) define the product.

For any new work, use **`docs/DEPLOYMENT_GUIDE.md`**, **`docs/PRIVATE_DEPLOYMENT_GUIDE.md`**, **`docs/DAY2_UPDATES.md`**, **`docs/PRIVATE_DAY2_UPDATES.md`**, and **`HOW_DEPLOYMENT_FITS_TOGETHER.md`**.
