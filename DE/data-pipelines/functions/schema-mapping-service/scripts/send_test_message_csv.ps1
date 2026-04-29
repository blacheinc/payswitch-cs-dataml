# Quick script to send test message for CSV file
# Usage: .\send_test_message_csv.ps1

$keyVaultUrl = "https://blachekvruhclai6km.vault.azure.net/"
$trainingUploadId = [guid]::NewGuid().ToString()
$bankId = "bank-digital-001"
$bronzeBlobPath = "bronze/training/bank-digital-001/2026-03-04/test_data_with_pii.csv"

Write-Host "`n=== Sending Test Message ===" -ForegroundColor Cyan
Write-Host "Training Upload ID: $trainingUploadId" -ForegroundColor White
Write-Host "Bank ID: $bankId" -ForegroundColor White
Write-Host "File Path: $bronzeBlobPath" -ForegroundColor White
Write-Host ""

# Activate virtual environment and run Python script
cd $PSScriptRoot\..
.\schema-mapping-env\Scripts\Activate.ps1
python -c @"
import sys
sys.path.insert(0, '.')
from scripts.send_test_message import send_test_message
import uuid

test_id = '$trainingUploadId'
print(f'\n=== SENDING TEST MESSAGE ===')
print(f'Training Upload ID: {test_id}')
print(f'Bank ID: $bankId')
print(f'File Path: $bronzeBlobPath')
print()
send_test_message('$keyVaultUrl', test_id, '$bankId', '$bronzeBlobPath')
"@

Write-Host "`n=== Message Sent ===" -ForegroundColor Green
Write-Host "Check the Azure Function logs to see if it processes the message." -ForegroundColor Yellow
