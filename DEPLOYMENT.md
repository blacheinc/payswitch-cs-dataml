# Deployment Guide — PaySwitch Credit Scoring ML

**Audience:** Developer deploying this repository to a new Azure subscription.
**Outcome:** Six live Function Apps, a trained model registry, and smoke-tested HTTP + Service Bus endpoints ready to hand off to Backend and Data Engineering.

---

## Table of contents

0. [What you're deploying](#0-what-youre-deploying)
1. [Prerequisites](#1-prerequisites)
2. [Naming decisions](#2-naming-decisions)
3. [Provision Azure resources](#3-provision-azure-resources)
4. [Managed identity & RBAC](#4-managed-identity--rbac)
5. [App settings & secrets](#5-app-settings--secrets)
6. [Deploy the code](#6-deploy-the-code)
7. [First training run](#7-first-training-run)
8. [Smoke tests](#8-smoke-tests)
9. [Hand off to Backend & Data Engineering](#9-hand-off-to-backend--data-engineering)
10. [Troubleshooting](#10-troubleshooting)

---

## 0. What you're deploying

Six Azure Function Apps that together form the Credit Scoring ML system:

- `orchestrator` — routes training + inference requests, runs the decision engine, persists audit records, exposes two HTTP endpoints
- Four **training agents** — `credit-risk`, `fraud-detection`, `loan-amount`, `income-verification` (each trains and serves one model type)
- `customer-service` — HTTP endpoint that answers natural-language questions about decisions using Azure OpenAI

```
Data Engineer publishes to Service Bus
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│  ORCHESTRATOR                                                    │
│  - Receives training/inference requests                          │
│  - Preprocesses data (imputation, validation)                    │
│  - Fans out to model agents via Service Bus                      │
│  - Collects results, runs decision engine                        │
│  - Persists audit record to blob, publishes to Backend           │
└─────────────────────────────────────────────────────────────────┘
         │ fans out to:
         ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Credit Risk  │  │ Fraud        │  │ Loan Amount  │  │ Income       │
│ Agent        │  │ Detection    │  │ Agent        │  │ Verification │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘

         ┌──────────────┐
         │ Customer     │ ← HTTP POST /v1/explain (Azure OpenAI)
         │ Service      │
         └──────────────┘
```

Supporting services: Azure Service Bus (18 topics), Azure Blob Storage (2 containers: `curated`, `model-artifacts`), Azure ML Workspace (model registry), Azure OpenAI (LLM for the explain endpoint).

---

## 1. Prerequisites

### Local tooling

| Tool | Version | Check |
|---|---|---|
| Python | `>=3.11` (pinned in `pyproject.toml`) | `python --version` |
| Azure Functions Core Tools | v4 | `func --version` |
| Azure CLI | 2.x | `az --version` |
| uv | any recent | `uv --version` |
| Shell | Bash 4+ (Git Bash or WSL on Windows; Linux bash; macOS users must `brew install bash` — the default macOS bash is 3.2 and lacks the `declare -A` associative arrays that `deploy.sh` requires) | `bash --version` |

Install the Azure CLI ML extension once:

```bash
az extension add --name ml
```

### Azure subscription

- **Role:** Owner or User Access Administrator on the target subscription — you'll be creating resources *and* assigning roles.
- **Azure OpenAI access:** Some tenants require a separate approval. Apply via `https://aka.ms/oai/access` before starting.
- **Quota:** 6 Consumption-plan Function Apps, 1 Azure ML Workspace, 1 Azure OpenAI resource with ≥10 TPM capacity for GlobalStandard.
- **Your own CLI user needs ML workspace access.** The `refresh_champion_snapshot` path (Section 7) authenticates as you via `DefaultAzureCredential`, so your user needs `AzureML Data Scientist` (or higher) on the workspace. If you're a Subscription Owner, this is inherited automatically.
- **ABAC warning:** If your CLI account has an Attribute-Based Access Control condition (common in orgs with conditional-access policies), **role assignments may silently fail**. If `az role assignment create` returns `AuthorizationFailed`, route the assignment to a Subscription Owner — don't try to work around it. We hit this with the orchestrator's `AzureML Data Scientist` role.

### Region

This guide uses `eastus2`. If you deploy to a different region, make sure it supports Azure OpenAI, Azure ML, and Consumption-plan Function Apps.

---

## 2. Naming decisions

Before running any `az` commands, pick your own names for every resource below. **Do this first** — the rest of the guide assumes you've set these as shell variables.

| Component | Example (ours) | Your name |
|---|---|---|
| Data resource group | `blache-cdtscr-dev-data-rg` | `<DATA_RG>` |
| ML resource group | `blache-cdtscr-dev-ml-rg` | `<ML_RG>` |
| Storage account (data + artifacts) | `blachedly27jgavel2x32` | `<STORAGE>` — globally unique, 3–24 lowercase alphanumeric |
| Storage account (Functions runtime) | `payswitchcsfuncstore` | `<FUNCSTORE>` — globally unique |
| Service Bus namespace | `blache-cdtscr-dev-sb-y27jgavel2x32` | `<SB_NS>` — globally unique |
| Azure ML workspace | `credit-score` | `<WORKSPACE>` |
| Azure OpenAI resource | `payswitch-cs-openai` | `<OPENAI>` |
| Orchestrator Function App | `payswitch-cs-orchestrator` | `<APP_ORCH>` |
| Credit risk agent | `payswitch-cs-credit-risk` | `<APP_RISK>` |
| Fraud detection agent | `payswitch-cs-fraud-detection` | `<APP_FRAUD>` |
| Loan amount agent | `payswitch-cs-loan-amount` | `<APP_LOAN>` |
| Income verification agent | `payswitch-cs-income-verification` | `<APP_INCOME>` |
| Customer service agent | `payswitch-cs-customer-service` | `<APP_CS>` |

Export them once so every command below works:

```bash
export SUBSCRIPTION_ID="<your-subscription-guid>"
export REGION="eastus2"

export DATA_RG="<your-data-rg>"
export ML_RG="<your-ml-rg>"

export STORAGE="<your-storage>"
export FUNCSTORE="<your-funcstore>"
export SB_NS="<your-sb>"
export WORKSPACE="<your-workspace>"
export OPENAI="<your-openai>"

export APP_ORCH="<your-orchestrator>"
export APP_RISK="<your-credit-risk>"
export APP_FRAUD="<your-fraud-detection>"
export APP_LOAN="<your-loan-amount>"
export APP_INCOME="<your-income-verification>"
export APP_CS="<your-customer-service>"

az account set --subscription "$SUBSCRIPTION_ID"
```

You will also **edit `deploy.sh`** to reference your Function App names before running it. Open the file and update these six variables near the top (they're the first assignments in the file):

```bash
ORCHESTRATOR_APP="<your-orchestrator>"
CREDIT_RISK_APP="<your-credit-risk>"
FRAUD_DETECTION_APP="<your-fraud-detection>"
LOAN_AMOUNT_APP="<your-loan-amount>"
INCOME_VERIFICATION_APP="<your-income-verification>"
CUSTOMER_SERVICE_APP="<your-customer-service>"
```

Everything else is consumed via environment variables.

---

## 3. Provision Azure resources

### 3.1 Resource groups

```bash
az group create --name "$DATA_RG" --location "$REGION"
az group create --name "$ML_RG"   --location "$REGION"
```

### 3.2 Storage — data + artifacts

```bash
# Data storage account
az storage account create \
  --name "$STORAGE" \
  --resource-group "$DATA_RG" \
  --location "$REGION" \
  --sku Standard_LRS \
  --kind StorageV2

# Containers
STORAGE_KEY=$(az storage account keys list --account-name "$STORAGE" --resource-group "$DATA_RG" --query "[0].value" -o tsv)

az storage container create --name curated         --account-name "$STORAGE" --account-key "$STORAGE_KEY"
az storage container create --name model-artifacts --account-name "$STORAGE" --account-key "$STORAGE_KEY"

# Functions runtime storage (separate account, required by Azure Functions)
az storage account create \
  --name "$FUNCSTORE" \
  --resource-group "$ML_RG" \
  --location "$REGION" \
  --sku Standard_LRS \
  --kind StorageV2
```

### 3.3 Service Bus — namespace + 18 topics + subscriptions

```bash
az servicebus namespace create \
  --name "$SB_NS" \
  --resource-group "$DATA_RG" \
  --location "$REGION" \
  --sku Standard
```

Create all 18 topics and their subscriptions by iterating [`infrastructure/service_bus_topics.json`](infrastructure/service_bus_topics.json). From the repo root:

```bash
python - <<'PY'
import json, subprocess, os

rg = os.environ["DATA_RG"]
ns = os.environ["SB_NS"]

with open("infrastructure/service_bus_topics.json") as f:
    spec = json.load(f)

for topic in spec["topics"]:
    subprocess.run([
        "az", "servicebus", "topic", "create",
        "--resource-group", rg,
        "--namespace-name", ns,
        "--name", topic["name"],
    ], check=True)
    for sub in topic.get("subscriptions", []):
        subprocess.run([
            "az", "servicebus", "topic", "subscription", "create",
            "--resource-group", rg,
            "--namespace-name", ns,
            "--topic-name", topic["name"],
            "--name", sub["name"],
        ], check=True)
PY
```

Verify all 18 topics exist:

```bash
az servicebus topic list \
  --resource-group "$DATA_RG" \
  --namespace-name "$SB_NS" \
  --query "length(@)"
# Expected output: 18
```

### 3.4 Azure ML workspace

```bash
az ml workspace create \
  --name "$WORKSPACE" \
  --resource-group "$ML_RG" \
  --location "$REGION"
```

> This command auto-creates **three dependent resources** in `$ML_RG` if they don't exist: a storage account, a key vault, and an Application Insights instance (all named with a prefix derived from the workspace name). This is expected. If you want to use existing resources, pass `--storage-account`, `--key-vault`, `--application-insights`.

### 3.5 Azure OpenAI + gpt-4.1-mini deployment

```bash
az cognitiveservices account create \
  --name "$OPENAI" \
  --resource-group "$ML_RG" \
  --location "$REGION" \
  --kind OpenAI \
  --sku S0

az cognitiveservices account deployment create \
  --resource-group "$ML_RG" \
  --name "$OPENAI" \
  --deployment-name "gpt-4-1-mini" \
  --model-name "gpt-4.1-mini" \
  --model-version "2025-04-14" \
  --model-format OpenAI \
  --sku-capacity 10 \
  --sku-name "GlobalStandard"
```

> **Do not use** `gpt-4o-mini` version `2024-07-18` — it was deprecated on 2026-03-31. We hit this during our deploy; `gpt-4.1-mini` is the drop-in replacement.

### 3.6 Six Function Apps

```bash
for app in "$APP_ORCH" "$APP_RISK" "$APP_FRAUD" "$APP_LOAN" "$APP_INCOME" "$APP_CS"; do
  az functionapp create \
    --resource-group "$ML_RG" \
    --consumption-plan-location "$REGION" \
    --runtime python --runtime-version 3.11 \
    --functions-version 4 \
    --name "$app" \
    --storage-account "$FUNCSTORE" \
    --os-type Linux
done
```

---

## 4. Managed identity & RBAC

Enable a system-assigned managed identity on each Function App and capture its principal ID:

```bash
for app in "$APP_ORCH" "$APP_RISK" "$APP_FRAUD" "$APP_LOAN" "$APP_INCOME" "$APP_CS"; do
  az functionapp identity assign --name "$app" --resource-group "$ML_RG"
done

export PID_ORCH=$(az functionapp identity show   --name "$APP_ORCH"   --resource-group "$ML_RG" --query principalId -o tsv)
export PID_RISK=$(az functionapp identity show   --name "$APP_RISK"   --resource-group "$ML_RG" --query principalId -o tsv)
export PID_FRAUD=$(az functionapp identity show  --name "$APP_FRAUD"  --resource-group "$ML_RG" --query principalId -o tsv)
export PID_LOAN=$(az functionapp identity show   --name "$APP_LOAN"   --resource-group "$ML_RG" --query principalId -o tsv)
export PID_INCOME=$(az functionapp identity show --name "$APP_INCOME" --resource-group "$ML_RG" --query principalId -o tsv)
export PID_CS=$(az functionapp identity show     --name "$APP_CS"     --resource-group "$ML_RG" --query principalId -o tsv)
```

### 4.1 Required roles (ML workspace)

These are the role assignments we actually used in production. **Storage, Service Bus, and Azure OpenAI are authenticated via connection strings and API keys** (set in Section 5 as app settings), so they don't require managed identity RBAC in the default deployment.

| Function App | Resource | Role | Why |
|---|---|---|---|
| Each training agent (×4) | Azure ML workspace | `Contributor` | Registers models (uploads artifacts, creates model versions) |
| Orchestrator | Azure ML workspace | `AzureML Data Scientist` | Queries model registry to build `champions/current.json` after each training run |

Scope:

```bash
export SCOPE_ML="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$ML_RG/providers/Microsoft.MachineLearningServices/workspaces/$WORKSPACE"
```

Assign:

```bash
# Training agents — Contributor on ML workspace
for pid in "$PID_RISK" "$PID_FRAUD" "$PID_LOAN" "$PID_INCOME"; do
  az role assignment create --assignee "$pid" --role "Contributor" --scope "$SCOPE_ML"
done

# Orchestrator — AzureML Data Scientist on ML workspace
az role assignment create --assignee "$PID_ORCH" --role "AzureML Data Scientist" --scope "$SCOPE_ML"
```

The customer service agent does **not** need any role on the ML workspace — it reads champion metadata from blob storage, not the ML registry directly.

### 4.2 Optional — switching to managed identity auth

If you want to eliminate the connection strings / API key in Section 5 and use managed identity end-to-end, also grant the roles below and remove the corresponding env vars. This is more secure but requires app code changes to use `DefaultAzureCredential` for Service Bus and Storage (not configured by default in this repo).

| Function App | Resource | Role | Replaces env var |
|---|---|---|---|
| Orchestrator + training agents | Storage `model-artifacts` | `Storage Blob Data Contributor` | `STORAGE_CONNECTION` |
| Customer service | Storage `model-artifacts` | `Storage Blob Data Reader` | `STORAGE_CONNECTION` |
| Orchestrator + training agents | Service Bus namespace | `Azure Service Bus Data Owner` | `SERVICE_BUS_CONNECTION` |
| Customer service | Azure OpenAI resource | `Cognitive Services OpenAI User` | `AZURE_OPENAI_API_KEY` |

### 4.3 ABAC gotcha

If `az role assignment create` fails with `AuthorizationFailed ... ABAC condition that is not fulfilled`, your CLI account is restricted by a conditional-access policy. Route the assignment to a Subscription Owner — do not try to work around it. Until the orchestrator has `AzureML Data Scientist`, `champions/current.json` will not refresh after training (see Section 7 for the backfill workaround).

---

## 5. App settings & secrets

Collect connection strings:

```bash
export SB_CONN=$(az servicebus namespace authorization-rule keys list \
  --resource-group "$DATA_RG" --namespace-name "$SB_NS" \
  --name RootManageSharedAccessKey --query primaryConnectionString -o tsv)

export STORAGE_CONN=$(az storage account show-connection-string \
  --name "$STORAGE" --resource-group "$DATA_RG" \
  --query connectionString -o tsv)

export OPENAI_ENDPOINT=$(az cognitiveservices account show \
  --name "$OPENAI" --resource-group "$ML_RG" \
  --query properties.endpoint -o tsv)

export OPENAI_KEY=$(az cognitiveservices account keys list \
  --name "$OPENAI" --resource-group "$ML_RG" \
  --query key1 -o tsv)
```

Per-app env var requirements:

| Env var | Orchestrator | Training agents (×4) | Customer service |
|---|:-:|:-:|:-:|
| `SERVICE_BUS_CONNECTION` | ✓ | ✓ |   |
| `STORAGE_CONNECTION` | ✓ | ✓ | ✓ |
| `AZURE_ML_SUBSCRIPTION_ID` | ✓ | ✓ |   |
| `AZURE_ML_RESOURCE_GROUP` | ✓ | ✓ |   |
| `AZURE_ML_WORKSPACE_NAME` | ✓ | ✓ |   |
| `MLFLOW_TRACKING_URI` |   | ✓ |   |
| `ENABLE_HYPERPARAMETER_TUNING` |   | ✓ |   |
| `AZURE_OPENAI_ENDPOINT` |   |   | ✓ |
| `AZURE_OPENAI_DEPLOYMENT` |   |   | ✓ |
| `AZURE_OPENAI_API_KEY` |   |   | ✓ |
| `AZURE_OPENAI_API_VERSION` |   |   | ✓ |

Apply them:

```bash
# Orchestrator
az functionapp config appsettings set --name "$APP_ORCH" --resource-group "$ML_RG" --settings \
  SERVICE_BUS_CONNECTION="$SB_CONN" \
  STORAGE_CONNECTION="$STORAGE_CONN" \
  AZURE_ML_SUBSCRIPTION_ID="$SUBSCRIPTION_ID" \
  AZURE_ML_RESOURCE_GROUP="$ML_RG" \
  AZURE_ML_WORKSPACE_NAME="$WORKSPACE"

# Training agents (loop)
for app in "$APP_RISK" "$APP_FRAUD" "$APP_LOAN" "$APP_INCOME"; do
  az functionapp config appsettings set --name "$app" --resource-group "$ML_RG" --settings \
    SERVICE_BUS_CONNECTION="$SB_CONN" \
    STORAGE_CONNECTION="$STORAGE_CONN" \
    AZURE_ML_SUBSCRIPTION_ID="$SUBSCRIPTION_ID" \
    AZURE_ML_RESOURCE_GROUP="$ML_RG" \
    AZURE_ML_WORKSPACE_NAME="$WORKSPACE" \
    MLFLOW_TRACKING_URI="sqlite:////tmp/mlflow.db" \
    ENABLE_HYPERPARAMETER_TUNING="true"
done

# Customer service
az functionapp config appsettings set --name "$APP_CS" --resource-group "$ML_RG" --settings \
  STORAGE_CONNECTION="$STORAGE_CONN" \
  AZURE_OPENAI_ENDPOINT="$OPENAI_ENDPOINT" \
  AZURE_OPENAI_DEPLOYMENT="gpt-4-1-mini" \
  AZURE_OPENAI_API_KEY="$OPENAI_KEY" \
  AZURE_OPENAI_API_VERSION="2024-10-21"
```

For local development, copy `.env.example` → `.env` and fill in the same values.

---

## 6. Deploy the code

```bash
# 1. Clone + install deps
git clone <this-repo>
cd payswitch-cs-dataml
uv sync

# 2. Run tests against your local environment
uv run pytest
# ~240 tests should pass. Any failure here means your Python environment
# is off — fix before deploying.

# 3. Edit the 6 APP variables at the top of deploy.sh with your own
#    Function App names (see Section 2).

# 4. Deploy all 6 apps
./deploy.sh all
```

`deploy.sh` copies `shared/` into each app directory before publishing (Azure Functions deploys each app in isolation — sibling directories aren't available), runs `func azure functionapp publish <app> --python`, and cleans up `shared/` after.

Verify each app registered its functions:

```bash
for app in "$APP_ORCH" "$APP_RISK" "$APP_FRAUD" "$APP_LOAN" "$APP_INCOME" "$APP_CS"; do
  echo "=== $app ==="
  az functionapp function list --name "$app" --resource-group "$ML_RG" --output table
done
```

Expected: orchestrator shows 6+ functions (training/inference orchestrators, result collectors, `api_evaluate_rules`, `batch_score_orchestrator`). Each training agent shows 2 functions (train, predict). Customer service shows 1 (`api_explain`).

---

## 7. First training run

The Backend endpoint `GET /v1/models/current` reads from `model-artifacts/champions/current.json`. This blob doesn't exist until a training run completes. In production, the **Data Engineer** will trigger this by publishing to `training-data-ready` with real data. For your deployment smoke test, you can trigger it yourself with the synthetic data the repo ships.

### 7.1 Generate synthetic training data

```bash
uv run python dummy_data/generate_datasets.py
```

This writes `dummy_data/clean_50k.parquet` (and two variants) locally. Parquet files are gitignored, so they're regenerated on demand.

### 7.2 Trigger training

Save this as `trigger_training.py` at the repo root and run it. Populate your local `.env` first (copy from `.env.example`, fill in `SERVICE_BUS_CONNECTION` and `STORAGE_CONNECTION`).

```python
"""Upload a training parquet to blob and publish to training-data-ready."""
import json, os, uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.storage.blob import BlobServiceClient

load_dotenv()
SB_CONN = os.environ["SERVICE_BUS_CONNECTION"]
STORAGE_CONN = os.environ["STORAGE_CONNECTION"]

parquet_path = Path("dummy_data/clean_50k.parquet")
now = datetime.now(timezone.utc)
training_id = f"TRAIN-{now.strftime('%Y%m%d-%H%M%S')}"
blob_path = f"ml-training/{training_id}/dataset.parquet"

df = pd.read_parquet(parquet_path)
blob_client = BlobServiceClient.from_connection_string(STORAGE_CONN)
container = blob_client.get_container_client("curated")
with open(parquet_path, "rb") as f:
    container.get_blob_client(blob_path).upload_blob(f.read(), overwrite=True)
print(f"Uploaded {parquet_path.name} to curated/{blob_path}")

message = {
    "training_id": training_id,
    "training_upload_id": str(uuid.uuid4()),
    "timestamp": now.isoformat(),
    "data_location": {"container": "curated", "blob_path": blob_path},
    "record_count": len(df),
    "dataset_version": "smoke-test-v1",
    "product_distribution": {},
    "models_to_train": ["all"],
}
with ServiceBusClient.from_connection_string(SB_CONN) as sb:
    with sb.get_topic_sender("training-data-ready") as sender:
        sender.send_messages(ServiceBusMessage(json.dumps(message)))
print(f"Published training-data-ready for {training_id}")
```

Run it:

```bash
uv run python trigger_training.py
```

This uploads the parquet and publishes to `training-data-ready`. The orchestrator fans out to all 4 training agents. End-to-end takes ~30–60 min with hyperparameter tuning on.

### 7.3 Verify the champion snapshot

```bash
az storage blob show \
  --account-name "$STORAGE" \
  --container-name model-artifacts \
  --name champions/current.json \
  --account-key "$STORAGE_KEY" \
  --query "{size: properties.contentLength, updated: properties.lastModified}"
```

### 7.4 Fallback — backfill without retraining

If models were registered but `champions/current.json` never appeared (e.g., orchestrator was missing `AzureML Data Scientist` at training time), you can backfill the snapshot using your own CLI identity. Save this as `refresh_champion_snapshot.py` at the repo root:

```python
"""One-off: query Azure ML for champion models and write champions/current.json."""
import os, sys
from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.abspath("orchestrator"))
sys.path.insert(0, os.path.abspath("."))

from modules.champion_store import build_champion_snapshot, save_champion_snapshot

ml_client = MLClient(
    credential=DefaultAzureCredential(),
    subscription_id=os.environ["AZURE_ML_SUBSCRIPTION_ID"],
    resource_group_name=os.environ["AZURE_ML_RESOURCE_GROUP"],
    workspace_name=os.environ["AZURE_ML_WORKSPACE_NAME"],
)
blob_client = BlobServiceClient.from_connection_string(os.environ["STORAGE_CONNECTION"])

snapshot = build_champion_snapshot(ml_client)
for entry in snapshot["models"]:
    status = entry["status"]
    suffix = f" v{entry['version']}" if status == "CHAMPION" else f" — {entry.get('error', '')}"
    print(f"  {entry['model_type']:24s} {status}{suffix}")

path = save_champion_snapshot(blob_client, snapshot)
print(f"\nSaved to model-artifacts/{path}")
```

Run it:

```bash
uv run python refresh_champion_snapshot.py
```

This reuses `orchestrator/modules/champion_store.py` (which is committed), so your `.env` needs `AZURE_ML_*` and `STORAGE_CONNECTION` populated. Your CLI user must have `AzureML Data Scientist` on the workspace (per Section 1 prerequisites).

---

## 8. Smoke tests

Retrieve function keys:

```bash
export KEY_ORCH=$(az functionapp function keys list \
  --name "$APP_ORCH" --resource-group "$ML_RG" \
  --function-name api_evaluate_rules --query default -o tsv)

export KEY_CS=$(az functionapp function keys list \
  --name "$APP_CS" --resource-group "$ML_RG" \
  --function-name api_explain --query default -o tsv)
```

### 8.1 Rules sandbox (orchestrator HTTP)

```bash
curl -X POST "https://$APP_ORCH.azurewebsites.net/api/v1/rules/evaluate" \
  -H "Content-Type: application/json" \
  -H "x-functions-key: $KEY_ORCH" \
  -d '{"probability_of_default": 0.05, "score_grade": "A"}'
```

Expected: `200` with `"decision": "APPROVE"` and `"sandbox": true`.

### 8.2 Customer service explain (customer service HTTP)

```bash
curl -X POST "https://$APP_CS.azurewebsites.net/api/v1/explain" \
  -H "Content-Type: application/json" \
  -H "x-functions-key: $KEY_CS" \
  -d '{"question": "What models are currently deployed?"}'
```

Expected: `200` with an `"answer"` string and `"provider": "azure_openai"`.

### 8.3 End-to-end inference (Service Bus → decision audit)

This smoke test only works **after** Section 7 training has completed and models are registered. It confirms the full pipeline: Data Engineer publishes → orchestrator scores → audit record lands in blob.

Save this as `trigger_inference.py` at the repo root:

```python
"""Publish a test applicant to inference-request and verify the audit blob."""
import json, os, uuid
from datetime import datetime, timezone
from dotenv import load_dotenv
from azure.servicebus import ServiceBusClient, ServiceBusMessage

load_dotenv()
SB_CONN = os.environ["SERVICE_BUS_CONNECTION"]

now = datetime.now(timezone.utc)
request_id = f"REQ-{now.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"

# Grade B borrower, Product 45+49 — all 30 features with valid values
features = {
    "highest_delinquency_rating": 1.00, "months_on_time_24m": 0.80,
    "worst_arrears_24m": 1.00, "current_streak_on_time": 0.75,
    "has_active_arrears": 0.00, "total_arrear_amount_ghs": 0.00,
    "total_outstanding_debt_ghs": 0.30, "utilisation_ratio": 0.20,
    "num_active_accounts": 0.55, "total_monthly_instalment_ghs": 0.40,
    "credit_age_months": 0.85, "num_accounts_total": 0.80,
    "num_closed_accounts_good": 0.75, "product_diversity_score": 0.55,
    "mobile_loan_history_count": 0.65, "mobile_max_loan_ghs": 0.50,
    "has_judgement": 0.00, "has_written_off": 0.00,
    "has_charged_off": 0.00, "has_legal_handover": 0.00,
    "num_bounced_cheques": 0.00, "has_adverse_default": 0.00,
    "num_enquiries_3m": 0.75, "num_enquiries_12m": 0.80,
    "enquiry_reason_flags": 0.60, "applicant_age": 1.00,
    "identity_verified": 1.00, "num_dependants": 0.85,
    "has_employer_detail": 1.00, "address_stability": 0.75,
}
metadata = {
    "credit_score": 720, "score_grade": "B", "decision_label": "APPROVE",
    "data_quality_score": 0.95, "bureau_hit_status": "HIT",
    "product_source": "45+49", "applicant_age_at_application": 32,
    "credit_age_months_at_application": 60,
}
message = {
    "request_id": request_id,
    "timestamp": now.isoformat(),
    "features": features,
    "metadata": metadata,
    "models_to_run": ["all"],
}
with ServiceBusClient.from_connection_string(SB_CONN) as sb:
    with sb.get_topic_sender("inference-request") as sender:
        sender.send_messages(ServiceBusMessage(json.dumps(message)))
print(f"Published inference-request for {request_id}")
```

Run it:

```bash
uv run python trigger_inference.py
```

Within ~60 seconds, a new blob should appear under `model-artifacts/decisions/<today>/REQ-*.json` — the immutable audit record.

```bash
az storage blob list \
  --account-name "$STORAGE" \
  --container-name model-artifacts \
  --prefix "decisions/$(date +%Y-%m-%d)/" \
  --account-key "$STORAGE_KEY" \
  --output table
```

---

## 9. Hand off to Backend & Data Engineering

### 9.1 Secrets to share (via secure channel)

```bash
# Orchestrator function key → Backend (for /api/v1/rules/evaluate)
az functionapp function keys list \
  --name "$APP_ORCH" --resource-group "$ML_RG" \
  --function-name api_evaluate_rules --query default -o tsv

# Customer service function key → Backend (for /api/v1/explain)
az functionapp function keys list \
  --name "$APP_CS" --resource-group "$ML_RG" \
  --function-name api_explain --query default -o tsv
```

### 9.2 RBAC grants for the downstream teams

Get their managed identity principal IDs first, then:

```bash
# Scopes
ARTIFACTS_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$DATA_RG/providers/Microsoft.Storage/storageAccounts/$STORAGE/blobServices/default/containers/model-artifacts"
CURATED_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$DATA_RG/providers/Microsoft.Storage/storageAccounts/$STORAGE/blobServices/default/containers/curated"
SB_SCOPE="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$DATA_RG/providers/Microsoft.ServiceBus/namespaces/$SB_NS"

# Backend — read access to results
az role assignment create --assignee "<BACKEND_PID>" \
  --role "Storage Blob Data Reader" \
  --scope "$ARTIFACTS_SCOPE"

az role assignment create --assignee "<BACKEND_PID>" \
  --role "Azure Service Bus Data Receiver" \
  --scope "$SB_SCOPE/topics/batch-score-complete"

# Data Engineer — write access for data ingestion
az role assignment create --assignee "<DATA_ENG_PID>" \
  --role "Storage Blob Data Contributor" \
  --scope "$CURATED_SCOPE"

az role assignment create --assignee "<DATA_ENG_PID>" \
  --role "Azure Service Bus Data Sender" \
  --scope "$SB_SCOPE"
```

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `az role assignment create` fails with `AuthorizationFailed ... ABAC condition` | Your CLI account has an ABAC conditional-access policy | Route the role assignment to a Subscription Owner |
| `champions/current.json` never appears after training | Orchestrator missing `AzureML Data Scientist` on workspace | Grant the role, then run `refresh_champion_snapshot.py` to backfill |
| Orchestrator logs `Feature validation failed: missing 'mobile_loan_history_count'` on inference | Sender omitted feature keys instead of sending them as `null` | Every request must include all 30 feature keys. 10 of them are imputable and may be `null` (8 are Product 45-only: `months_on_time_24m`, `worst_arrears_24m`, `current_streak_on_time`, `product_diversity_score`, `has_judgement`, `num_bounced_cheques`, `has_adverse_default`, `address_stability`; 2 are Product 49-only: `mobile_loan_history_count`, `mobile_max_loan_ghs`). The other 20 must have real values |
| Customer service returns `"Client.__init__() got an unexpected keyword argument 'proxies'"` | `openai` / `httpx` version drift | **Do not change** the pins in `customer-service-agent/requirements.txt`: `openai==1.68.2`, `httpx==0.27.2` |
| Training agent crashes with `__sklearn_tags__` error | scikit-learn 1.6+ breaks XGBoost 2.1.3 model loading | Pin `scikit-learn==1.5.2` — this is already in the agent `requirements.txt`; don't upgrade |
| Training agent crashes with `marshmallow._T` import error | `azure-ai-ml` needs pinned marshmallow | Keep `marshmallow==3.23.2` in the requirements |
| Training agent crashes on `pd.read_parquet` | Missing pyarrow | Keep `pyarrow==14.0.2` pinned |
| MLflow fails with `Read-only file system` | Consumption plan `/home/site/wwwroot/` is read-only | MLflow must write to `/tmp/`. Already configured in each agent's `registry.py` — don't change `MLFLOW_TRACKING_URI` away from `/tmp/` paths |
| `gpt-4o-mini` deployment returns `ServiceModelDeprecated` | Model deprecated 2026-03-31 | Use `gpt-4.1-mini` version `2025-04-14` instead |
| `func azure functionapp publish` fails with "No job functions found" | Running `func` from the wrong directory | Use `./deploy.sh` — it handles `cd` correctly. Manual `func publish` must run from inside the app directory |
| Orchestrator doesn't trigger on Service Bus message | Subscription `orchestrator-sub` missing on the topic | Re-run the topic provisioning script from Section 3.3 |
