# Transformation service - Azure Function (Python 3.11, Linux, Functions v4)

param(
    [Parameter(Mandatory = $false)]
    [string]$ResourceGroupName = "blache-cdtscr-dev-data-rg",

    [Parameter(Mandatory = $false)]
    [string]$FunctionAppName = "blache-cdtscr-dev-transform-y27jgavel2x32",

    [Parameter(Mandatory = $false)]
    [string]$Location = "eastus2"
)

$ErrorActionPreference = "Stop"
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
