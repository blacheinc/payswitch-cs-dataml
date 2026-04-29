param(
    [Parameter(Mandatory = $true)]
    [string]$DataResourceGroup,
    [string]$Environment = "prod"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$paramsRoot = Join-Path $root "parameters\$Environment"
$modulesRoot = Join-Path $root "modules"

if (-not (Test-Path $paramsRoot)) {
  throw "Parameter folder not found for environment '$Environment': $paramsRoot"
}

Write-Host "Applying Service Bus updates..." -ForegroundColor Cyan
az deployment group create `
  --resource-group $DataResourceGroup `
  --template-file (Join-Path $modulesRoot "service-bus\main.update.bicep") `
  --parameters "@$(Join-Path $paramsRoot 'service-bus.update.parameters.json')" `
  --name "day2-sb-rules-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
if ($LASTEXITCODE -ne 0) { throw "Service Bus updates failed." }

Write-Host "Applying Storage updates..." -ForegroundColor Cyan
az deployment group create `
  --resource-group $DataResourceGroup `
  --template-file (Join-Path $modulesRoot "storage\main.update.bicep") `
  --parameters "@$(Join-Path $paramsRoot 'storage.update.parameters.json')" `
  --name "day2-storage-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
if ($LASTEXITCODE -ne 0) { throw "Storage updates failed." }

Write-Host "Applying Key Vault IAM updates..." -ForegroundColor Cyan
az deployment group create `
  --resource-group $DataResourceGroup `
  --template-file (Join-Path $modulesRoot "keyvault\main.update.bicep") `
  --parameters "@$(Join-Path $paramsRoot 'keyvault.update.parameters.json')" `
  --name "day2-kv-iam-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
if ($LASTEXITCODE -ne 0) { throw "Key Vault updates failed." }

Write-Host "Applying Functions IAM updates..." -ForegroundColor Cyan
$functionsIamScript = Join-Path $PSScriptRoot "apply-functions-iam-idempotent.ps1"
& $functionsIamScript `
  -ParameterFilePath (Join-Path $paramsRoot 'functions-iam.update.parameters.json')
if ($LASTEXITCODE -ne 0) { throw "Functions IAM updates failed." }

Write-Host "Day-2 updates completed." -ForegroundColor Green
