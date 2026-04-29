# Schema mapping service — PowerShell runbook

Run hosts and most commands from **`schema-mapping-service`** (the folder that contains `function_app.py`), **not** from `scripts/` alone.

**Service Bus entry:** topic **`data-ingested`**, subscription **`start-transformation`**.  
**Internal progress:** topic **`schema-mapping-service`** (multiple subscriptions).  
**Handoff to transformation:** topic **`schema-mapping-service`**, subscription **`mapping-complete`**.

**`scripts/` is excluded from Function zip deploy** (`.funcignore`) — these are dev/ops tools.

---

## Deploy to Azure

From **`schema-mapping-service`** (the folder that contains `deploy.ps1` and `function_app.py`):

```powershell
Set-Location "<your-repo>\data-pipelines\functions\schema-mapping-service"
```

- **First create:** `.\deploy.ps1 -CreateResources`  
  Optional `-DataLakeStorageAccountName "<adls-account>"` for **Storage Blob Data Contributor** on the ADLS account; if omitted, the script uses Key Vault secret **`DataLakeStorageAccountName`** (same as MI-based reads).
- **Routine deploy (code + refresh settings):** `.\deploy.ps1`
- **App settings only:** `.\deploy.ps1 -SkipPublish`
- **MI-only for ADLS at runtime** (no connection string on the app): `.\deploy.ps1 -SkipDatalakeConnectionStringAppSetting`

Use `-FunctionAppName`, `-ResourceGroupName`, `-KeyVaultName` if yours differ. The app name must be **globally unique** in Azure.

**Key Vault:** **`ServiceBusConnectionString`**, **`DataLakeStorageAccountName`**. For **shared-key ADLS** (same as local `DATALAKE_STORAGE_CONNECTION_STRING`), store the connection string under one of **`StorageConnectionString`** (same as training-data-ingestion deploy), **`DataLakeStorageConnectionString`**, or **`DataLakeConnectionString`** — deploy copies the first one found into app setting **`DATALAKE_STORAGE_CONNECTION_STRING`**.

**Dual auth behavior:** The orchestrator uses **`DATALAKE_STORAGE_CONNECTION_STRING`** when that app setting is non-empty; otherwise it uses **Managed Identity** + **`DataLakeStorageAccountName`**. The script still grants **Key Vault Secrets User** and **Storage Blob Data Contributor** on the ADLS account so both paths work; use **`-SkipDatalakeConnectionStringAppSetting`** if you want Azure to run **MI-only** (remove or never set the connection string app setting).

---

## 1. Load `local.settings.json` into the environment

```powershell
Set-Location "<your-repo>\data-pipelines\functions\schema-mapping-service"
$cfg = Get-Content ".\local.settings.json" -Raw | ConvertFrom-Json
foreach ($p in $cfg.Values.PSObject.Properties) {
    Set-Item -Path "Env:$($p.Name)" -Value ([string]$p.Value)
}
```

For **`run_pipeline_from_service_bus.py`** you also need a **`.env`** in **`schema-mapping-service`** with the variables that script lists (`REQUIRED_ENV_VARS` in the Python file). `local.settings.json` alone is not enough for that runner.

---

## 2. Run the Function locally

**Window A:**

```powershell
Set-Location "<your-repo>\data-pipelines\functions\schema-mapping-service"
func start
```

Wait until the host is up. **Disable or pause the deployed** schema-mapping Function in Azure if you use the **same** `start-transformation` subscription, or messages may go to Azure only.

---

## 3. Send a test message onto `data-ingested`

**Bronze path:** must match the object in the **bronze** container. Training ingestion usually writes  
`bronze/training/<data_source_id>/<YYYY-MM-DD>/<file_stem>.<ext>` where `<file_stem>` is the upload’s `file_name` without extension (e.g. `test_ingestion_1`), **or** `{training_upload_id}` depending on metadata. Confirm with **`bronze_ingestion_log.bronze_blob_path`** or **`training_uploads.bronze_blob_path`** in Postgres if unsure.

**Payload:** the orchestrator requires **`run_id`** in the JSON body. Prefer **`send_test_message_json.py`** (always includes `run_id` + subscription filter properties).

| Script | When to use |
|--------|-------------|
| `python .\scripts\send_test_message_json.py --bank-id <data_source_uuid> --training-upload-id <upload_uuid> --bronze-blob-path "bronze/training/..."` | **Recommended** for real bronze files after ingestion. Loads SB from env / Key Vault like the other scripts. |
| `python .\scripts\send_test_message_simple.py` | Fastest: reads **`ServiceBusConnectionString`** from **`local.settings.json`** only; random upload id; **edit default `bronze_blob_path` in the file** if your bronze file differs. |
| `python .\scripts\send_test_message.py` | Key Vault or env; includes **`run_id`** (auto-generated) and filter properties. Edit **`__main__`** or import `send_test_message(..., run_id=...)`. **`bank_id` = `data_source_id`** (same UUID) per team convention. |
| `python .\scripts\send_test_message_with_upload_id.py` etc. | Variants for specific payload shapes — open each file’s docstring. |

**Window B** (while `func start` is running):

```powershell
Set-Location "<your-repo>\data-pipelines\functions\schema-mapping-service"
python .\scripts\send_test_message_simple.py
```

---

## 4. Peek / inspect Service Bus (no consume)

```powershell
python .\scripts\peek_subscription_messages.py
```

Uses a **hardcoded Key Vault URL** inside the script unless you changed it — align with your vault or copy the pattern to use `$env:KEY_VAULT_URL`.

---

## 5. Consume messages (destructive)

```powershell
python .\scripts\read_subscription_messages.py
```

**Removes** messages from **`start-transformation`**. Use a dev subscription or accept loss of queued work.

---

## 6. Check orchestrator output on internal + backend topics

```powershell
python .\scripts\check_function_output.py
```

Hardcoded `kv_url` in file — edit for your environment if needed.

---

## 7. Full Systems 0–4 **without** `func start`

Uses **real** Bronze/Silver/Key Vault/Service Bus; receives **one** message from a subscription you configure in `.env`.

1. Create/update **`schema-mapping-service\.env`** per `run_pipeline_from_service_bus.py` header (`SERVICEBUS_TOPIC_NAME=data-ingested`, `SERVICEBUS_SUBSCRIPTION_NAME=start-transformation`, etc.).

2. `az login` (uses CLI credential when `ENVIRONMENT=local`).

3. Run:

```powershell
Set-Location "<your-repo>\data-pipelines\functions\schema-mapping-service"
python .\scripts\run_pipeline_from_service_bus.py
```

---

## 8. PowerShell helpers in `scripts\`

Several `.ps1` files automate subscription counts, filters, or sending (e.g. `send_and_verify_message.ps1`, `diagnose_subscription.ps1`). **Open each file first** — many contain **machine-specific `cd` paths**; fix the path to your clone before running.

Optional orchestration: `.\scripts\start_and_test_local.ps1` starts `func` as a **job** and prints instructions (you still send from another window).

---

## 9. After mapping completes

Start **transformation-service** locally and/or confirm **`mapping-complete`** messages — see [transformation-service/scripts/README_POWERSHELL_RUNBOOK.md](../../transformation-service/scripts/README_POWERSHELL_RUNBOOK.md).
