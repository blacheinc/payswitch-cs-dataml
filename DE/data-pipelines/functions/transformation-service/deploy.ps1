# Transformation service - Azure Function (Python 3.11, Linux, Functions v4)

param(
    [Parameter(Mandatory = $false)]
    [string]$ResourceGroupName = "",

    [Parameter(Mandatory = $false)]
    [string]$FunctionAppName = "",

    [Parameter(Mandatory = $false)]
    [string]$Location = ""
)

$ErrorActionPreference = "Stop"
$ResourceGroupName = if ($ResourceGroupName) { $ResourceGroupName } else { $env:RESOURCE_GROUP_NAME }
$FunctionAppName = if ($FunctionAppName) { $FunctionAppName } else { $env:FUNCTION_APP_NAME }
$Location = if ($Location) { $Location } else { $env:AZURE_LOCATION }
if (-not $Location) { $Location = "eastus2" }

if (-not $FunctionAppName) {
    Write-Host "ERROR: Missing FunctionAppName. Pass -FunctionAppName or set FUNCTION_APP_NAME." -ForegroundColor Red
    exit 1
}
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "Transformation service - deploy" -ForegroundColor Cyan
Write-Host "  FunctionAppName: $FunctionAppName" -ForegroundColor Yellow
Write-Host "  Public URL:      https://${FunctionAppName}.azurewebsites.net" -ForegroundColor Yellow
Write-Host ""

if (-not (Get-Command func -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: Azure Functions Core Tools (func) not found." -ForegroundColor Red
    exit 1
}

Write-Host "Publishing: func azure functionapp publish $FunctionAppName --python" -ForegroundColor Yellow
func azure functionapp publish $FunctionAppName --python
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
Write-Host "Publish finished." -ForegroundColor Green
