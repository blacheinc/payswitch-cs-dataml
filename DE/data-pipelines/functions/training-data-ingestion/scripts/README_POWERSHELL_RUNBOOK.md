# Training data ingestion — PowerShell runbook

Run everything from **`training-data-ingestion`** (the folder that contains `function_app.py` and `scripts/`). The Python files below **tell you the next step in their own output**; this page is the copy-paste order so you do not have to hunt.

---

## 0. Go to the module folder

```powershell
Set-Location "<your-repo>\data-pipelines\functions\training-data-ingestion"
```

---

## 1. Load `local.settings.json` into the environment (do this every new PowerShell window)

Your scripts expect `KEY_VAULT_URL`, `ServiceBusConnectionString`, blob settings, etc. The Function app already lists them in `local.settings.json`. Load them once per session:

```powershell
$cfg = Get-Content ".\local.settings.json" -Raw | ConvertFrom-Json
foreach ($p in $cfg.Values.PSObject.Properties) {
    Set-Item -Path "Env:$($p.Name)" -Value ([string]$p.Value)
}
```

**PostgreSQL:** The DB is not contacted until steps like **`generate_adf_test_data.py`** insert. If that step stalls after “Inserting…”, you are usually blocked on **Key Vault** (`PostgreSQLConnectionString`) or **Postgres TCP** (firewall/VPN). Put **`PostgreSQLConnectionString`** in `local.settings.json` under `Values` to skip KV for the DB URL. Optional env **`POSTGRES_CONNECT_TIMEOUT`** (default `20`) caps how long TCP connect waits.

Optional: activate a venv if you use one:

```powershell
# if you created venv here:
# .\venv\Scripts\Activate.ps1
```

Install deps if needed: `pip install -r requirements.txt` (and `pip install python-dotenv` if scripts warn about dotenv).

---

## 2. Track A — **Script 1 → 2 → 3** (blob + DB + Service Bus), then **local ingestion**

This is exactly what the file headers describe: **Script 1** creates the file, **Script 2** inserts `training_uploads`, **Script 3** sends to `data-awaits-ingestion`. Then you run the orchestrator locally (same logic as the Function, for `temp-peek-subscription`).

| Step | Command | What you need |
|------|---------|----------------|
| A1 | `python .\scripts\create_and_upload_test_file.py` | Prompts for a **`data_source_id` UUID that already exists** in `data_sources`. Writes a JSON **array of rows** shaped like XDS P45: each object is only `{ "consumer_full_report_45": <full P45 JSON> }` (no `applicant_context`—that is not in raw XDS). Row count: env **`XDS_TEST_NUM_RECORDS`** (default `10`). Prints values for A2/A3. |
| A2 | `python .\scripts\insert_training_upload_record.py` | Paste values from A1. Produces **`training_upload_id`**. |
| A3 | `python .\scripts\send_test_ingestion_message_v2.py` | Paste IDs/size/path from A1–A2. Sends to topic **`data-awaits-ingestion`** (properties for **`temp-peek-subscription`** — **omit** `processing_system=ADF`). |
| A4 | `python .\scripts\run_training_ingestion.py` | Uses `SERVICEBUS_SUBSCRIPTION_NAME` from env (your `local.settings.json` → **`temp-peek-subscription`**). Processes messages and updates DB / publishes `data-ingested`. Stop with **Ctrl+C** when done. |
| A5 | `python .\scripts\validate_pipeline_results.py <training_upload_id>` | Checks `training_uploads` + `bronze_ingestion_log`. |
| A5b | `python .\scripts\check_training_upload_status.py <training_upload_id>` | Quick row dump. |

### 2.1 Same blob + DB as Track A, but **ADF** moves raw → bronze

Use the **same** A1 and A2 as above. For the Service Bus step, route the message to **`adf-trigger-subscription`** so the deployed **adf-pipeline-trigger** Function starts **`pipeline-training-data-ingestion`** (instead of running **`run_training_ingestion.py`** locally).

| Step | Command | What you need |
|------|---------|----------------|
| A-ADF1 | *(same as A1)* | `create_and_upload_test_file.py` |
| A-ADF2 | *(same as A2)* | `insert_training_upload_record.py` |
| A-ADF3 | `python .\scripts\send_test_ingestion_message_v2.py --adf` | Same prompts as A3. Sets **`application_properties["processing_system"] = "ADF"`** so only the ADF trigger path consumes the message. |
| A-ADF4 | *(no local ingestion)* | Portal → **Data Factory** → **Monitor** → confirm **`pipeline-training-data-ingestion`** run succeeded (blob → bronze, checksum, etc., per your pipeline). |
| A-ADF5 | `python .\scripts\validate_pipeline_results.py <training_upload_id>` | Same validation as A5 once bronze / DB updates exist. |

**Do not** run **`run_training_ingestion.py`** after **`--adf`** for the same upload — that is the temp-peek / Function-ingestion path and would duplicate work or race ADF.

**If A4 says “no messages”:** subscription filter or wrong topic. From `scripts`:

```powershell
.\check_subscription.ps1
# Optional: -SubscriptionName "adf-trigger-subscription" to inspect the ADF path
```

---

## 3. Track B — **One-shot ADF test data** + **pipeline parameters JSON**

Use when you want a fresh blob + DB row + values suitable for **manual ADF trigger** in the portal.

| Step | Command | Output |
|------|---------|--------|
| B1 | `python .\scripts\generate_adf_test_data.py` | Loads **`local.settings.json`** into the environment (like other ingestion scripts). Uses **`BlobStorageConnectionString`**, then **`AzureWebJobsStorage`**, then **`DATALAKE_STORAGE_CONNECTION_STRING`** before calling Key Vault—avoids hanging on KV when your storage string is already in `local.settings.json`. Creates blob under container **`data`**, inserts/updates `training_uploads` with **`ingesting`**, prints IDs and paths. |
| B2 | `python .\scripts\generate_pipeline_parameters.py` | Prompts for IDs/file info (says to use B1 output). Writes **`scripts\pipeline_parameters.json`** and prints the same JSON. |

Then in **Azure Portal** → Data Factory → pipeline **`pipeline-training-data-ingestion`** → **Trigger now** → paste that JSON into **Parameters**.

**Important:** `generate_pipeline_parameters.py` has a **hardcoded `DATA_SOURCE_ID`** in the file (around line 56). It must match the UUID you use in `generate_adf_test_data.py` and an existing `data_sources` row. If they differ, edit that constant before B2.

---

## 4. Track C — Re-run the same upload ID

```powershell
python .\scripts\reset_training_upload_status.py <training_upload_id>
```

Then repeat A3 + A4 (or your ADF trigger) as needed.

---

## 5. Optional diagnostics

| Script | When |
|--------|------|
| `python .\scripts\check_database_enum_values.py` | DB enum / connectivity issues |
| `.\scripts\check_subscription.ps1` | Messages stuck; SQL filter on `data-awaits-ingestion` |

---

## 6. Scripts **not** recommended for routine use

| File | Why |
|------|-----|
| `send_test_ingestion_message.py` | **Hardcoded** `training_upload_id` / paths at the bottom of the file. Use **`send_test_ingestion_message_v2.py`** unless you edit the constants. |

---

## 7. Dependency on `schema-mapping-service` (Script 1 path only)

`create_and_upload_test_file.py` loads **`schema-mapping-service\utils\key_vault_reader.py`** via the repo layout. Keep the full **`data-pipelines/functions`** tree checked out so that path exists.

---

## 8. Other modules

Index of runbooks for **adf-pipeline-trigger**, **schema-mapping-service**, **transformation-service**, **file-checksum-calculator**:  
[data-pipelines/docs/FUNCTIONS_POWERSHELL_RUNBOOKS_INDEX.md](../../../docs/FUNCTIONS_POWERSHELL_RUNBOOKS_INDEX.md)

---

## 9. ADF triggered by Service Bus

After Script 1–2, prefer **`python .\scripts\send_test_ingestion_message_v2.py --adf`** (same body as Script 3, ADF routing). Alternatively, use **`adf-pipeline-trigger`** examples (`test_send_message.py --type adf`, `test_production_pipeline.py`) with **`ServiceBusConnectionString`** / **`SERVICEBUS_CONNECTION_STRING`** set — those must use the **same** `training_upload_id`, paths, and sizes as your `training_uploads` row.
