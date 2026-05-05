# Transformation service — PowerShell runbook

Run from **`transformation-service`** (folder with `function_app.py`).

**Azure deploy:** run `.\deploy.ps1` from this folder (`func azure functionapp publish` only). The entire `scripts/` tree is excluded from publish via `.funcignore` and **ignored by Git** (operator helpers only; not required at runtime). Clone fresh repos will not contain `scripts/` until you add files locally.

**Config:** see `config/README.md` for `de_imputation_policy.json` (bootstrap imputation policy and live contract behaviour).

**HTTP (local):** `POST http://localhost:7071/api/transform/training` and `.../transform/inference`  
**Service Bus:** topic **`schema-mapping-service`**, subscription **`mapping-complete`** (silver handoff from schema mapping).

---

## 0. Deploy with `deploy.ps1`

Run from this folder:

```powershell
Set-Location "<your-repo>\data-pipelines\functions\transformation-service"
```

Deploy with explicit parameters:

```powershell
.\deploy.ps1 -ResourceGroupName "<rg>" -FunctionAppName "<app>" -Location "eastus2"
```

Quick post-deploy check:

```powershell
az functionapp function list -g "<rg>" -n "<app>" -o table
```

---

## 1. Load `local.settings.json` into the environment

```powershell
Set-Location "<your-repo>\data-pipelines\functions\transformation-service"
$cfg = Get-Content ".\local.settings.json" -Raw | ConvertFrom-Json
foreach ($p in $cfg.Values.PSObject.Properties) {
    Set-Item -Path "Env:$($p.Name)" -Value ([string]$p.Value)
}
```

Same window is fine for helper scripts below.

---

## 2. Discover subscription names on `training-data-ready`

The peek/receive helper needs the **real** subscription name (not hardcoded in repo).

```powershell
$env:SB_CONN = $env:TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING
# optional if not already in Values:
$env:TRAINING_DATA_READY_TOPIC = "training-data-ready"
python .\scripts\list_service_bus_topic_subscriptions.py
```

Pick a name, then:

```powershell
$env:TRAINING_DATA_READY_SUBSCRIPTION = "<name-from-output>"
```

---

## 3. Run the Function locally

```powershell
func start
```

If you rely on **`mapping-complete`**, pause the **deployed** transformation Function in Azure when testing locally on the same namespace.

---

## 4. HTTP — training

```powershell
$uri = "http://localhost:7071/api/transform/training"
$body = Get-Content ".\payload_training_hit.json" -Raw | ConvertFrom-Json
Invoke-RestMethod -Uri $uri -Method POST -Body ($body | ConvertTo-Json -Depth 25) -ContentType "application/json"
```

Use your real payload consistent with `INFERENCE_TEST_DATA_CASES.md` in this service and the schema-mapping contract used in production. If the host uses **function auth**, add `?code=<key>` to the URL.

---

## 5. HTTP — inference

**Sample payloads (repo):**

- One applicant: `payload_inference_1_sample.json`
- Several applicants (posted as separate HTTP calls): `payload_inference_multiple_samples.json` (`samples` array)

**Python helper** (one request per applicant; handles `?code=`):

```powershell
python .\scripts\post_inference_samples.py --payload .\payload_inference_1_sample.json
python .\scripts\post_inference_samples.py --payload .\payload_inference_multiple_samples.json --code "<function-key>"
```

**PowerShell** (single request):

```powershell
$body = Get-Content ".\payload_inference_1_sample.json" -Raw | ConvertFrom-Json
Invoke-RestMethod -Uri "http://localhost:7071/api/transform/inference?code=<function-key>" -Method POST -Body ($body | ConvertTo-Json -Depth 25) -ContentType "application/json"
```

Before `func start`, set **`ML_ENGINEER_HTTP_ENDPOINT`** in `local.settings.json` to a URL that accepts multipart POSTs (for example `https://httpbin.org/post` for smoke tests). The default `https://example.com/ml/inference` will fail at runtime.

---

## 6. Receive **one** message from `training-data-ready` (completes it)

```powershell
Set-Location "<your-repo>\data-pipelines\functions\transformation-service"
# Ensure sections 1 and 2 set SB_CONN / subscription
python .\scripts\sb_receive_training.py
```

**Warning:** this **completes** the first message — use a non-prod subscription when possible.

---

## 7. Inference Service Bus smoke check (`inference-request`)

Use this after posting `/api/transform/inference` (or batch) while
`ML_ENGINEER_HTTP_ENDPOINT` is unset/placeholder. This verifies the current handoff mode
is Service Bus with inline `features` + `metadata`.

```powershell
Set-Location "<your-repo>\data-pipelines\functions\transformation-service"
$env:SB_CONN = $env:TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING
# Discover the real subscription name in Azure Portal for topic inference-request.
$env:INFERENCE_REQUEST_SUBSCRIPTION = "<real-subscription-name>"
python .\scripts\sb_receive_inference.py
```

Expected body keys include:

- `request_id`
- `timestamp`
- `features`
- `metadata`
- `models_to_run`

---

## 8. Optional: in-process contract smoke (no Azure)

Does **not** hit Storage or Service Bus:

```powershell
python .\scripts\run_contract_smoke.py
```

Use only for quick parser/orchestrator sanity, not integration.

---

## 9. Pipeline position

Upstream:

- [training-data-ingestion RUNBOOK_POWERSHELL.md](../training-data-ingestion/RUNBOOK_POWERSHELL.md)
- [schema-mapping-service RUNBOOK_POWERSHELL.md](../schema-mapping-service/RUNBOOK_POWERSHELL.md)

---

## Deprecated / non-runbook scripts

See `scripts/deprecated/` for archived utilities (not part of the canonical flow).
