# Transformation service — PowerShell runbook

Run from **`transformation-service`** (folder with `function_app.py`).

**Azure deploy:** run `.\deploy.ps1` from this folder (`func publish` only). Inference anonymization is now local to this app; no schema-mapping bundle sync is required.

**HTTP (local):** `POST http://localhost:7071/api/transform/training` and `.../transform/inference`  
**Service Bus:** topic **`schema-mapping-service`**, subscription **`mapping-complete`** (silver handoff from schema mapping).

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

Use your real payload per [XDS_EXPECTED_INPUT_CONTRACT_FOR_FEATURES_AND_TARGETS.md](../../../docs/XDS_EXPECTED_INPUT_CONTRACT_FOR_FEATURES_AND_TARGETS.md). If the host uses **function auth**, add `?code=<key>` to the URL.

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

Script lives in the **module root**, not under `scripts/`:

```powershell
Set-Location "<your-repo>\data-pipelines\functions\transformation-service"
# Ensure §1 and §2 set SB_CONN / subscription
python .\sb_receive_training.py
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
python .\sb_receive_inference.py
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

Upstream: [training-data-ingestion/scripts/README_POWERSHELL_RUNBOOK.md](../../training-data-ingestion/scripts/README_POWERSHELL_RUNBOOK.md) and [schema-mapping-service/scripts/README_POWERSHELL_RUNBOOK.md](../../schema-mapping-service/scripts/README_POWERSHELL_RUNBOOK.md).
