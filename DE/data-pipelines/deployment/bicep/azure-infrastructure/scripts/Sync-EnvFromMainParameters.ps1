<#
.SYNOPSIS
  Reads org/project/environment (and related fields) from main.*.parameters.json and sets process environment variables.

.DESCRIPTION
  Use this before running destroy, testing scripts, or other tooling that expects ORG_NAME / PROJECT_NAME / ENVIRONMENT / NAMING_PREFIX.
  The canonical file operators edit for subscription deploy is bicep-templates/main.parameters.json (or a copy you pass with -ParametersPath).

.EXAMPLE
  . .\Sync-EnvFromMainParameters.ps1
  . .\Sync-EnvFromMainParameters.ps1 -ParametersPath ..\bicep-templates\main.prod.parameters.json
#>
param(
    [string]$ParametersPath = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($ParametersPath)) {
    $ParametersPath = Join-Path $PSScriptRoot "..\bicep-templates\main.parameters.json"
}

if (-not (Test-Path $ParametersPath)) {
    throw "Parameter file not found: $ParametersPath"
}

$doc = Get-Content -LiteralPath $ParametersPath -Raw | ConvertFrom-Json
$p = $doc.parameters
if ($null -eq $p) {
    throw "Invalid parameters file (missing 'parameters' object): $ParametersPath"
}

function Get-ParamText([object]$node) {
    if ($null -eq $node) { return "" }
    return [string]$node.value
}

$org = Get-ParamText $p.orgName
$proj = Get-ParamText $p.projectName
$envName = Get-ParamText $p.environment
$loc = Get-ParamText $p.primaryLocation
$email = Get-ParamText $p.adminEmail

if ([string]::IsNullOrWhiteSpace($org) -or [string]::IsNullOrWhiteSpace($proj) -or [string]::IsNullOrWhiteSpace($envName)) {
    throw "orgName, projectName, and environment must be non-empty in $ParametersPath"
}

$env:ORG_NAME = $org
$env:PROJECT_NAME = $proj
$env:ENVIRONMENT = $envName
$env:NAMING_PREFIX = "$org-$proj-$envName"
if (-not [string]::IsNullOrWhiteSpace($loc)) {
    $env:PRIMARY_LOCATION = $loc
}
if (-not [string]::IsNullOrWhiteSpace($email)) {
    $env:ADMIN_EMAIL = $email
}

Write-Host "Loaded from $ParametersPath" -ForegroundColor Green
Write-Host "  ORG_NAME=$($env:ORG_NAME)  PROJECT_NAME=$($env:PROJECT_NAME)  ENVIRONMENT=$($env:ENVIRONMENT)  NAMING_PREFIX=$($env:NAMING_PREFIX)" -ForegroundColor Gray
