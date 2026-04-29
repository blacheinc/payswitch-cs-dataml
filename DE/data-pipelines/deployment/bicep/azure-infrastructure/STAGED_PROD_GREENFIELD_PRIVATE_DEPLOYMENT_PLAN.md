# Staged Prod Greenfield Deployment Plan (Private Networking, Single Subscription, `eastus2`)

This document describes a **safe, staged (“wave”) deployment** for production infrastructure using the Bicep under `data-pipelines/deployment/bicep`. It is written in plain English and is meant to be operated by running **PowerShell driver scripts** (you want minimal/no manual Azure CLI typing).

It aligns with these decisions you provided:

- **Single VNet** (no hub/spoke requirement for now)
- **Region**: `eastus2`
- **Naming (Data Engineering)**: **`blache-cdtscr-<env>-…`** for infra and DE-owned Function Apps (example prod RGs below)
- **Naming (ML / backend)**: separate convention (**`payswitch-cs-*`**) — those apps are **not** deployed by DE; same subscription/VNet/core messaging patterns may still apply
- **Prod isolation**: **one Azure subscription**, **multiple resource groups**
- **Compliance stance**: **public network access may remain enabled temporarily**, then disabled **after staged validation**
- **Operators**: troubleshooting via **Azure Bastion + jump VM** (provisioned from `main.bicep` via RG-scoped module; **username/password** required for the Windows jump VM)
- **Functions (DE prod v1)**: **all 5** Premium apps in one Bicep loop — **file checksum is private** like the others (`privateNetworkMode=true`)
- **ADF**: **Managed VNet** + **Managed IR** (`integrationRuntime1`) + training pipeline JSON from **`deployment/adf/live-export/`** (latest full `pipeline-training-data-ingestion`); linked services/datasets/trigger still from **`deployment/adf/support-live/`**
- **AKS / AML workspace**: **deferred** in prod v1 (`main.bicep` gates via `deployAks` / `deployMlWorkspace`; defaults off for `prod`)
- **AI Foundry**: **ML engineer scope** — does not need to be wired into DE Functions/ADF for v1; OpenAI/PE can follow the ML track when needed
- **Scale**: low daily traffic; large payloads are mostly **JSONL processed line-by-line later** (reduces memory risk vs loading full 100MB JSON into RAM)

---

## How to read this document

You will deploy in **waves**. Each wave:

1. Deploys a **defined subset** of infrastructure (via Bicep)
2. Runs **automated smoke checks**
3. Runs **manual Bastion VM checks** when needed
4. Only then moves to the next wave

This matches your idea “deploy one module, then two modules…” without requiring awkward manual commenting inside templates on every run.

---

## Critical repo reality checks (please read)

These are not criticisms — they prevent surprises during deployment week.

### A) Your repo currently has **two major Bicep tracks**

1. **`azure-infrastructure/bicep-templates/main.bicep` (subscription scope)**  
   Deploys multiple resource groups and core modules such as networking, Key Vault, data services, AKS, ML workspace, monitoring.

2. **`phase2-data-ingestion/*` modules (resource-group scope)**  
   Deploys Service Bus, ADF, private endpoints/DNS patterns, premium Function Apps.

A full production platform typically uses **both tracks**, but **not everyone wants AKS/ML workspace in prod v1**. You must decide whether **Wave 1** includes the entire `main.bicep` stack or only a subset.

### B) **ADF: Managed VNet + Managed IR are in Phase 2 Bicep**

`phase2-data-ingestion/azure-data-factory/data-factory.bicep` deploys:

- **`Microsoft.DataFactory/factories/managedVirtualNetworks`** (`default`, from `support-live`)
- **`Microsoft.DataFactory/factories/integrationRuntimes`** (**Managed** IR `integrationRuntime1`, from `support-live`)
- **`pipeline-training-data-ingestion`** built from **`deployment/adf/live-export/pipeline-pipeline-training-data-ingestion.json`** (full factory export — activities/parameters/variables match the latest pipeline design)

Linked services, datasets, and the blob trigger continue to load from **`deployment/adf/support-live/`**, with parameter substitution for Key Vault URL, storage endpoints, Postgres host, and blob-trigger storage scope.

**Remaining gap (optional hardening):** **managed private endpoints** for ADF to reach Storage/KV/SB through the Managed VNet are **not** fully enumerated in this doc — add when you lock private-only data paths for ADF copy activities.

**Security note:** the live-export pipeline may embed **dev default parameters** (e.g. checksum function URL/key). For prod, **clear or override** those in ADF after deploy, or extend Bicep to strip/replace defaults.

### C) **Five DE Function Apps in one template (all private)**

`phase2-data-ingestion/functions/functions-premium.bicep` defines **five** name tokens: schema mapping, transformation, training ingestion, adf trigger, and **`file-checksum-func`**, on one Premium plan with **per-app private endpoints** when `privateNetworkMode=true`.

**ML/backend** Function Apps using the **`payswitch-cs-*`** naming are **out of this Bicep file** — track them in runbooks/RBAC separately (see **Service Bus & naming** below).

---

## Service Bus topology & naming (agreed)

Use this as the **authoritative reference** when validating Wave 6 and when mapping **which Function App** subscribes to which **topic / subscription**. Subscriptions and filter rules are **not** all defined in Bicep today — many are **app config**; the list below is the **intended topology** to verify in the namespace after deploy.

### Topic / subscription map (summary)

| Topic | Subscriptions (names) |
|--------|-------------------------|
| `batch-score-complete` | `backend-sub` |
| `batch-score-request` | `orchestrator-sub` |
| `credit-risk-predict` | `credit-risk-sub` |
| `credit-risk-train` | `credit-risk-sub` |
| `data-awaits-ingestion` | `adf-trigger-subscription`, `temp-peek-subscription` |
| `data-ingested` | `cs-backend`, `data-quality-agent-sub`, `error`, `quality_report`, `start-transformation`, `transformed` |
| `data-quality-checked` | `ai-training-sub`, `feature-engineering-agent-sub` |
| `decision-made` | `compliance-agent-sub`, `risk-monitoring-agent-sub` |
| `drift-detected` | `model-training-agent-drift-sub`, `risk-monitoring-agent-drift-sub` |
| `features-engineered` | `decision-agent-sub`, `model-training-agent-sub` |
| `fraud-detect-predict` | `fraud-detection-sub` |
| `fraud-detection-train` | `fraud-detection-sub` |
| `income-verification-train` | `income-verification-sub` |
| `income-verify-predict` | `income-verification-sub` |
| `inference-request` | `orchestrator-sub` |
| `loan-amount-predict` | `loan-amount-sub` |
| `loan-amount-train` | `loan-amount-sub` |
| `model-deployed` | `compliance-agent-model-update-sub`, `decision-agent-model-update-sub` |
| `model-training-complete` | `orchestrator-sub` (**topic A** — distinct name) |
| `model-training-completed` | `orchestrator-sub` (**topic B** — distinct name; not a duplicate topic) |
| `model-training-started` | `backend-sub`, `cs-backend` |
| `prediction-complete` | `orchestrator-sub` |
| `schema-mapping-service` | `analysis-complete`, `anonymization-complete`, `failed`, `introspection-complete`, `mapping-complete`, `sampling-complete`, `schema-detected` |
| `scoring-complete` | `backend-sub` |
| `training-data-ready` | `orchestrator-sub`, `transformation-complete-training-sub` |

**Clarifications already confirmed:**

- **`model-training-complete`** and **`model-training-completed`** are **two different topics** (do not merge).
- **`schema-mapping-service`** is a **topic**; the short names above are **subscriptions** on that topic.
- Spelling: **`sampling-complete`** (not “sampliing”).
- Subscriptions listed under **`data-ingested`** are **subscriptions on that single topic**.

### Two families of Function Apps

| Family | Naming | Owned by | In DE Bicep `functions-premium.bicep`? |
|--------|--------|----------|----------------------------------------|
| Data Engineering (this plan) | `blache-cdtscr-<env>-…-func` | DE | **Yes** — five apps |
| ML / backend | `payswitch-cs-*` (e.g. credit-risk, orchestrator, …) | ML + backend | **No** — different pipeline; same Service Bus namespace may still apply |

**Implication:** RBAC, Key Vault secret names, and `host.json` / Service Bus trigger wiring for **`payswitch-cs-*`** apps are **out of scope** for the DE phase-2 module — coordinate with those owners using the table above.

### Functions **runtime** storage (one account vs many)

Each Function App **requires** a storage account for the **Functions host** (state, packages, etc.). You can:

- **Share one storage account** across several apps (lower cost, shared blast radius and quotas), or  
- **Use one storage account per app** (stronger isolation, common in production).

This plan does not mandate one model; **record the choice** in Wave 9 parameters (`functionsStorageAccountName` in `functions-premium` parameters).

---

## What “Private Endpoint + Private DNS + RBAC proven” lets you actually do?

### Private Endpoint (PE)

**Plain English:** it creates a **private front door** to an Azure service inside your VNet (a NIC with a private IP). Traffic to the service can avoid the public internet **for that access pattern**.

### Private DNS

**Plain English:** Azure services normally have **public DNS names** (`*.blob.core.windows.net`, `*.vault.azure.net`, etc.). Private DNS zones make those names resolve to **private IPs** inside your VNet when Private Link is in play.

Without correct Private DNS, you often get confusing failures:

- apps still trying public routes,
- intermittent failures depending on resolver,
- “works on my machine” symptoms.

### RBAC

**Plain English:** RBAC answers **authorization**: “this identity is allowed to perform this action on this resource.”

Authentication still happens via identities:

- Function App **managed identity**
- human user accounts
- deployment identities (later)

### Together

When PE + DNS + RBAC are proven for a resource, you can perform **real private data-plane actions**:

- read/write blobs using managed identity,
- fetch secrets from Key Vault privately,
- publish/consume Service Bus privately,
- call AI endpoints privately **if** those endpoints are reachable via Private Link + DNS from your compute.

---

## What NSGs do

**Plain English:** NSGs are **firewall rules at subnet/NIC scope inside the VNet**.

They allow/deny traffic by IP ranges, ports, and direction. They complement Private Link but do not replace it.

Typical uses:

- restrict which subnets can reach the **private endpoints subnet**
- restrict admin access paths
- reduce lateral movement if something is compromised

---

## Recommended wave design (safe bootstrap)

This is the mental model you approved, expanded into concrete waves.

### Wave 0 — Preconditions (no Azure resources yet)

Goal: avoid dead ends before spending money.

Decide and record:

- Subscription ID
- Owner for break-glass access
- Tagging standard (CostCenter, Environment, Owner)
- Whether **AKS + ML workspace** from `main.bicep` are in prod v1 or deferred

### Wave 1 — Identity scaffolding in Azure (subscription + RGs)

Goal: create the empty “folders” (resource groups) you will deploy into.

Example prod naming (your pattern):

- `blache-cdtscr-prod-network-rg`
- `blache-cdtscr-prod-security-rg`
- `blache-cdtscr-prod-data-rg`
- `blache-cdtscr-prod-monitoring-rg` (if used)
- `blache-cdtscr-prod-compute-rg` (if AKS is in scope)
- `blache-cdtscr-prod-ml-rg` (if ML workspace is in scope)

**Stop gate**

- RGs exist in `eastus2`

### Wave 2 — Networking (single VNet + subnets)

Goal: establish the network home for everything else.

Minimum subnets (aligned with **`networking/vnet.bicep`** today):

- **`AzureBastionSubnet`** (`/26`) — Azure Bastion host only (reserved name)
- **`jump-subnet`** — NIC for the Windows jump VM (no public IP; access via Bastion)
- **`functions-subnet`** — delegated to Function App / Premium plan VNet integration
- **`private-endpoints-subnet`** — Private Endpoint NICs (policies disabled as required)
- plus existing `data-subnet`, `ml-subnet`, `aks-subnet`, etc. per template

**Stop gate**

- VNet exists
- subnets exist with correct delegations where required

### Wave 3 — Private DNS zones (foundational)

Goal: prevent DNS surprises before you start disabling public access.

You typically link Private DNS zones to the VNet for services you will private-link:

- Storage (`privatelink.blob.core.windows.net`, `privatelink.dfs.core.windows.net`, sometimes queue/table)
- Key Vault (`privatelink.vaultcore.azure.net`)
- Service Bus (`privatelink.servicebus.windows.net`)
- Azure Monitor / App Insights private endpoints (if used)
- Azure OpenAI / AI Foundry private endpoints (names vary by exact resource shape)

**Stop gate (Bastion VM)**

- You can resolve key private DNS names and see **private IP answers** (not public)

### Wave 4 — Key Vault (security RG) + RBAC baseline

Goal: establish secret storage that later modules can reference.

**Stop gate**

- Key Vault exists
- PE + DNS path works from Bastion VM (not necessarily from Functions yet)
- RBAC assignments exist for break-glass admin + deployment identity (even if deployment identity is “your user” for now)

### Wave 5 — Core data plane services (data RG): Storage + DB/cache pieces your templates create

Goal: create the durable stores pipelines need.

This wave depends heavily on what `data-services.bicep` creates in your environment.

**Stop gate**

- Storage accounts exist
- Private endpoints exist for storage + DNS validated
- Managed identities can read/write test blobs (smoke)

### Wave 6 — Service Bus namespace (data RG) + private posture

Goal: messaging backbone for Functions + ADF integration patterns.

**Stop gate**

- Namespace exists
- Topics and subscription **names** match **Service Bus topology & naming** (filters/rules are app-level — verify in code/Portal)
- PE + DNS validated
- test send/receive from Bastion or a diagnostic client

### Wave 7 — Azure Data Factory factory + identity plumbing

Goal: deploy ADF **before** Functions if that is your preference.

**Compatibility note:** `phase2-data-ingestion/azure-data-factory/data-factory.bicep` deploys Managed VNet + Managed IR from **`deployment/adf/support-live/`**, and **`pipeline-training-data-ingestion`** from **`deployment/adf/live-export/pipeline-pipeline-training-data-ingestion.json`**. Parameter file uses **`deploymentEnvironment`** (not `environment`) for the factory global parameter.

Wave 7 split:

- **7a:** deploy ADF (`deploy-phase2-private.ps1` or equivalent) with `privateNetworkMode=true` when endpoints are ready
- **7b:** **sanitize pipeline parameters** in the factory for prod (remove dev defaults for checksum URL/key, etc.) + add **managed private endpoints** if ADF must reach Storage/KV/SB only via Managed VNet

**Stop gate**

- ADF can authenticate to linked services in a controlled way
- If Managed VNet IR is enabled: managed private endpoints show as created/pending approval as expected

### Wave 8 — Private endpoints “mesh” for remaining services

Goal: ensure every service that must be private has PE + DNS + approvals complete.

### Wave 9 — Premium Function Apps (5 apps)

All five apps are deployed from the same `functions-premium.bicep` loop (single Premium plan + per-app private endpoints).

Per your requirement:

- **Most apps**: private posture (`publicNetworkAccess` disabled when `privateNetworkMode=true` in that template)
- **Checksum app**: intentionally more public (likely requires **template support** to not inherit “disable public access for all apps” behavior)

**Stop gate**

- Each Function App can reach:
  - Key Vault (private)
  - Storage (private)
  - Service Bus (private)
  - AI endpoint (private) — see Wave 10

### Wave 10 — Azure OpenAI / AI (optional for DE v1)

Goal (if DE Functions call models): prove **private** inference paths.

For **prod v1**, Foundry may be **ML-engineer-only** — skip this wave for DE if no DE app calls OpenAI/Foundry. ML/backend can own their PE/DNS when they connect apps to Foundry.

**Stop gate** (when in scope)

- From Bastion VM and from a Function that must call AI, HTTPS succeeds via private path where required

### Wave 11 — Hardening: disable public network access everywhere it should be off

Goal: meet compliance stance **after** proof.

Do this **service-by-service** with rollback:

- Storage accounts
- Key Vault
- Service Bus namespace
- any remaining public surfaces

**Stop gate**

- Repeat the same smoke tests after each toggle

---

## How “incremental deployment” should work without you running Azure CLI manually

### What you want

A parameterized PowerShell entrypoint, for example:

- `deploy-wave.ps1 -SubscriptionId … -Environment prod -Wave 3`

Internally it runs `az deployment …` commands.

### Important truth

Even if you never type Azure CLI yourself, **the automation still uses Azure CLI or Az PowerShell under the hood**. That is normal.

### Idempotency

Bicep deployments are **idempotent**: rerunning the same template with the same parameters generally updates to desired state.

Your “wave” approach should be implemented as:

- **Wave N deploys superset** of modules up to N (safe reruns), **or**
- separate templates per wave (also common)

---

## Smoke tests (automated) — what to run after each wave

Minimum recommended automated checks:

- `az deployment … what-if` before apply for risky waves
- DNS resolution checks from Bastion VM (scripted)
- data-plane smoke tests:
  - upload/download blob with MI
  - get secret from KV with MI
  - send/receive SB test message

## Manual Bastion checks — what humans verify that automation misses

- Portal visibility / RBAC mistakes
- Private endpoint **pending approval** states
- Actual application behavior under real Identity + DNS conditions

---

## Open items (not blocking “start”)

- **Service Bus rules/filters** per subscription (SQL filters, correlation IDs) — document per app in the ML/backend/DE repos; the table above is **names only**.
- **Managed private endpoints for ADF** (if you require copy/lookup activities to use only Managed VNet egress) — add in a follow-up wave after baseline PE for Storage/KV/SB on the VNet.
- **Foundry** — ML engineer defines project + PE when they connect training/inference; **omit for DE v1** if DE apps do not call Foundry.

---

## Beginning deployment — start here (Wave 0 → Wave 2)

Complete these in order; then proceed through waves 3+ using `what-if` before risky applies.

### Wave 0 — Preconditions

1. **Subscription ID** and **tenant** confirmed; you have **Owner** or equivalent on subscription or target RGs.
2. **`eastus2`** quotas OK for Premium Functions, Bastion Standard, SB, PEs (request increases if needed).
3. **Tags** scheme agreed (Environment, Owner, CostCenter, Project).
4. **Jump VM admin password**: provide a strong password interactively and pass it as **`jumpVmAdminPassword`** (`main.bicep`) at deployment time. Do not commit the password.
5. **Decisions recorded**:
   - AKS + AML workspace: **deferred** for prod v1 (leave `deployAks=false`, `deployMlWorkspace=false` unless you explicitly override).
   - Functions **runtime** storage: shared vs **one account per app** — fill `REPLACE_PROD_FUNCTIONS_STORAGE` (and related) in phase-2 parameter files accordingly.

### Wave 1 — Subscription deployment (`main.bicep`)

Deploy `azure-infrastructure/bicep-templates/main.bicep` at **subscription scope** with prod parameters (you maintain a `prod.parameters.json` or inline parameters). Ensure:

- Resource groups exist for network, security, data, monitoring, compute, ML, etc.
- **`deployJumpBox`**: default is **true** for `environment=prod` — provide **`jumpVmAdminPassword`** or the Bastion/jump module deployment will fail for the Windows VM.

### Wave 2 — Confirm network

After deploy, verify in portal or CLI:

- VNet and subnets including **`AzureBastionSubnet`** and **`jump-subnet`**.
- Bastion and (if key provided) jump VM in **network RG**.

### Phase 2 track (DE) — when RGs and data RG exist

Use existing scripts as a baseline (extend with prod parameter files):

- `data-pipelines/deployment/bicep/azure-infrastructure/scripts/deploy-phase2-private.ps1`  
  Deploys Service Bus → ADF → private endpoints → **functions-premium** (five apps).

**Before first prod phase-2 deploy:** edit `phase2-data-ingestion/*/parameters/prod.parameters.json` — replace all `REPLACE_*` placeholders (subnet IDs, storage account names, ADF storage, KV, SB, Postgres FQDN, optional `sourceStorageSubscriptionId` / `sourceStorageResourceGroupName` for blob trigger scope).

---

## Automation follow-ups (optional hardening)

- Add **`deploy-wave.ps1`** (or **`deploy-prod-staged.ps1`**) that maps wave numbers to `az deployment sub create` / `az deployment group create` with authored parameter files (no hydration from live dev).
- Expand **managed private endpoints** for ADF when the network team signs off on approval workflow.
