# PaySwitch Credit Scoring ML System

ML training and inference system for PaySwitch's Credit Scoring Engine. Trains 4 models on XDS credit bureau data (Ghana) and serves predictions via Azure Functions + Azure Service Bus.

## Architecture

```
Data Engineer publishes to Service Bus
         |
         v
+----------------------------------------------------------+
|  ORCHESTRATOR (Azure Function App)                       |
|  - Preprocessing (imputation, validation)                |
|  - Fan-out to model agents via Service Bus               |
|  - Result collection + Decision Engine                   |
|  - Final response assembly                               |
+----------------------------------------------------------+
         | fans out to:
         v
+--------------+  +--------------+  +--------------+  +--------------+
| Credit Risk  |  | Fraud        |  | Loan Amount  |  | Income       |
| XGBoost      |  | Isolation    |  | LightGBM +   |  | LightGBM    |
| Binary       |  | Forest       |  | Ridge + XGB  |  | Multiclass   |
+--------------+  +--------------+  +--------------+  +--------------+
```

**Inference flow:** Two-phase. Phase 1 (always): Credit Risk + Fraud Detection. Phase 2 (conditional): Income Verification + Loan Amount. Decision Engine assembles the final response.

**Selective execution:** Both training and inference support running specific model subsets via `models_to_train` / `models_to_run` fields.

## Prerequisites

- **Python 3.11+**
- **uv** (package manager): `pip install uv`
- **Azure Functions Core Tools v4**: [Install guide](https://learn.microsoft.com/en-us/azure/azure-functions/functions-run-local)
- **Azure CLI**: `az login` (for Azure ML model registry)
- **Git Bash** (Windows) or any Unix shell

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd payswitch-cs-dataml
uv sync
```

### 2. Create `.env` file

Create a `.env` file in the project root with your Azure credentials:

```env
# Azure Service Bus
SERVICE_BUS_CONNECTION="Endpoint=sb://<namespace>.servicebus.windows.net/;SharedAccessKeyName=...;SharedAccessKey=..."

# Azure Blob Storage
STORAGE_CONNECTION="DefaultEndpointsProtocol=https;AccountName=<account>;AccountKey=...;EndpointSuffix=core.windows.net"

# Azure ML (for model registry)
AZURE_ML_SUBSCRIPTION_ID="<subscription-id>"
AZURE_ML_RESOURCE_GROUP="<resource-group>"
AZURE_ML_WORKSPACE_NAME="<workspace-name>"

# MLflow (local experiment tracking)
MLFLOW_TRACKING_URI="sqlite:///mlflow.db"

# Training config
ENABLE_HYPERPARAMETER_TUNING="false"   # Set "true" for production training
```

### 3. Create `local.settings.json` for each Function App

Each app needs a `local.settings.json` (already in `.gitignore`). Create one in `orchestrator/` and each agent directory:

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "<STORAGE_CONNECTION>",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "SERVICE_BUS_CONNECTION": "<SERVICE_BUS_CONNECTION>",
    "STORAGE_CONNECTION": "<STORAGE_CONNECTION>",
    "MLFLOW_TRACKING_URI": "sqlite:///mlflow.db",
    "AZURE_ML_SUBSCRIPTION_ID": "<subscription-id>",
    "AZURE_ML_RESOURCE_GROUP": "<resource-group>",
    "AZURE_ML_WORKSPACE_NAME": "<workspace-name>",
    "ENABLE_HYPERPARAMETER_TUNING": "false"
  }
}
```

### 4. Generate dummy datasets

```bash
python dummy_data/generate_datasets.py
```

Creates three parquet files for testing:
- `clean_50k.parquet` -- 50k clean records, no nulls
- `missing_10k.parquet` -- 10k records with product gaps (for imputation testing)
- `broken_1k.parquet` -- 1k records with validation errors

## Running Locally

Use `deploy.sh` to run any Function App locally. It copies `shared/` into the app directory, starts `func`, and cleans up on exit.

```bash
# Start the orchestrator (port 7071)
./deploy.sh local orchestrator

# Start a model agent (each on its own port)
./deploy.sh local credit-risk          # port 7072
./deploy.sh local fraud-detection      # port 7073
./deploy.sh local loan-amount          # port 7074
./deploy.sh local income-verification  # port 7075
```

Run from **Git Bash** (not CMD/PowerShell).

## Testing

### Unit tests

```bash
uv run pytest
```

### Integration tests (against Azure)

Requires the orchestrator and relevant agent(s) running locally, plus Azure Service Bus and Blob Storage configured.

**Training:**
```bash
# Trigger training for a specific model
python temp_files/tests/trigger_training.py missing --models credit_risk

# Verify results
python temp_files/tests/verify_training.py TRAIN-<id>
```

**Inference:**
```bash
# Trigger inference for a specific model
python temp_files/tests/trigger_inference.py --models credit_risk

# Verify results
python temp_files/tests/verify_inference.py REQ-<id>
```

**Supported `--models` values:**
- `all` (default) -- all models
- `credit_risk` -- Credit Risk only
- `fraud_detection` -- Fraud Detection only
- `credit_risk,fraud_detection` -- Phase 1 only
- Any comma-separated combination of: `credit_risk`, `fraud_detection`, `loan_amount`, `income_verification`

## Deploying to Azure

```bash
# Deploy a single app
./deploy.sh orchestrator
./deploy.sh credit-risk

# Deploy all 5 apps
./deploy.sh all
```

The script copies `shared/` into each app directory before running `func azure functionapp publish`, then cleans up. Requires `az login` and Azure Functions Core Tools v4.

Azure Function App names are configured at the top of `deploy.sh`.

## Project Structure

```
payswitch-cs-dataml/
├── orchestrator/                     # Azure Function App - central coordinator
│   ├── function_app.py              # Training + inference orchestrators, result collectors
│   ├── modules/
│   │   ├── preprocessing.py         # Validation, imputation
│   │   ├── decision_engine.py       # Section 4.2 + 5.4 decisioning
│   │   ├── risk_mapping.py          # PD -> risk tier
│   │   └── message_schemas.py       # Service Bus message wrappers
│   ├── requirements.txt             # Azure deployment deps
│   └── host.json
│
├── training-agents/
│   ├── credit-risk-agent/           # XGBoost binary classifier
│   ├── fraud-detection-agent/       # Isolation Forest (unsupervised)
│   ├── loan-amount-agent/           # LightGBM + Ridge + XGBoost ensemble
│   └── income-verification-agent/   # LightGBM multiclass (4 classes)
│   # Each agent has: function_app.py, modules/{trainer,validator,registry}.py
│
├── shared/                          # Shared code (copied into each app at deploy)
│   ├── constants.py                 # Enums, thresholds, mappings
│   ├── schemas/
│   │   ├── feature_schema.py        # 30 feature definitions
│   │   ├── message_schemas.py       # Service Bus contracts
│   │   └── response_schema.py       # Final scoring response format
│   └── utils.py
│
├── tests/                           # Unit tests (pytest)
├── dummy_data/                      # Synthetic test datasets
├── infrastructure/                  # Service Bus topic definitions
├── temp_files/tests/                # Integration test scripts
├── deploy.sh                        # Deploy + local dev script
└── pyproject.toml                   # Dependencies + pytest config
```

## Service Bus Topics

| Topic | Direction | Phase |
|-------|-----------|-------|
| `training-data-ready` | Data Engineer -> Orchestrator | Training |
| `model-training-started` | Orchestrator -> Backend | Training |
| `credit-risk-train` | Orchestrator -> Credit Risk Agent | Training |
| `fraud-detection-train` | Orchestrator -> Fraud Agent | Training |
| `loan-amount-train` | Orchestrator -> Loan Agent | Training |
| `income-verification-train` | Orchestrator -> Income Agent | Training |
| `model-training-complete` | Each Agent -> Orchestrator | Training |
| `model-training-completed` | Orchestrator -> Backend | Training |
| `inference-request` | Data Engineer -> Orchestrator | Inference |
| `credit-risk-predict` | Orchestrator -> Credit Risk Agent | Inference |
| `fraud-detect-predict` | Orchestrator -> Fraud Agent | Inference |
| `loan-amount-predict` | Orchestrator -> Loan Agent | Inference |
| `income-verify-predict` | Orchestrator -> Income Agent | Inference |
| `prediction-complete` | Each Agent -> Orchestrator | Inference |
| `scoring-complete` | Orchestrator -> Backend | Inference |

## Azure Resources

| Resource | Purpose |
|----------|---------|
| Service Bus namespace | Message routing between components |
| Storage Account | Training data (curated container), model artifacts, imputation params |
| ML Workspace | Model registry (azure-ai-ml SDK) |

## Key Design Decisions

1. **Separate Azure Function Apps** per model -- independent deployment, scaling, billing
2. **Service Bus fan-out** -- not Durable Functions
3. **Orchestrator owns the final decision** -- not individual models
4. **Two-phase inference** -- Phase 1 always (Risk + Fraud), Phase 2 conditional (Income + Loan)
5. **Selective execution** -- `models_to_train`/`models_to_run` fields control which models run
6. **Imputation in orchestrator** -- model agents receive complete data with no nulls
7. **azure-ai-ml for model registry** -- MLflow for local tracking only
8. **deploy.sh copies shared/** -- each Function App is isolated, shared code copied at deploy time
