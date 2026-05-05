# Training Data Ingestion - PowerShell Runbook

Run all commands from `data-pipelines/functions/training-data-ingestion`.

## 1) Session setup

```powershell
Set-Location "<your-repo>\data-pipelines\functions\training-data-ingestion"
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Load `local.settings.json` values into environment variables for the current shell:

```powershell
$cfg = Get-Content ".\local.settings.json" -Raw | ConvertFrom-Json
foreach ($p in $cfg.Values.PSObject.Properties) {
    Set-Item -Path "Env:$($p.Name)" -Value ([string]$p.Value)
}
```

## 2) Functional test flow (local ingestion path)

1. Create and upload a test raw file:
   - `python .\scripts\create_and_upload_test_file.py`
2. Insert `training_uploads` record:
   - `python .\scripts\insert_training_upload_record.py`
3. Send ingestion message:
   - `python .\scripts\send_test_ingestion_message_v2.py`
4. Process message locally:
   - `python .\scripts\run_training_ingestion.py`
5. Validate result:
   - `python .\scripts\validate_pipeline_results.py <training_upload_id>`
   - `python .\scripts\check_training_upload_status.py <training_upload_id>`

## 3) ADF route (optional)

Use the same script 1 + 2 outputs, then send with ADF routing:

- `python .\scripts\send_test_ingestion_message_v2.py --adf`

Do not run `run_training_ingestion.py` for that same upload.

## 4) Useful troubleshooting

- Reset upload status for rerun:
  - `python .\scripts\reset_training_upload_status.py <training_upload_id>`
- Inspect subscription filter:
  - `.\scripts\check_subscription.ps1`
- Check enum values / DB shape:
  - `python .\scripts\check_database_enum_values.py`

Deprecated artifacts are archived under `scripts/deprecated/` and are intentionally outside the active runbook flow.

## 5) Deployment

Deploy with `deploy.ps1`:

```powershell
.\deploy.ps1 -ResourceGroupName "<rg>" -FunctionAppName "<app>" -KeyVaultName "<kv>"
```

Required values (parameter or environment variable):

- `ResourceGroupName` or `RESOURCE_GROUP_NAME`
- `FunctionAppName` or `FUNCTION_APP_NAME`
- `KeyVaultName` or `KEY_VAULT_NAME`

Optional:

- `Location` or `AZURE_LOCATION` (defaults to `eastus2`)
