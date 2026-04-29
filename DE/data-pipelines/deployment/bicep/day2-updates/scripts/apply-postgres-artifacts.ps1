param(
    [Parameter(Mandatory = $true)]
    [string]$PostgresHost,
    [Parameter(Mandatory = $true)]
    [string]$PostgresDatabase,
    [Parameter(Mandatory = $true)]
    [string]$PostgresUser,
    [Parameter(Mandatory = $true)]
    [string]$PostgresPassword,
    [string]$SqlArtifactsFolder = ""
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($SqlArtifactsFolder)) {
    $SqlArtifactsFolder = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\artifacts\day2\sql")) ""
}

if (-not (Test-Path $SqlArtifactsFolder)) {
    throw "SQL artifacts folder not found: $SqlArtifactsFolder"
}

$sqlFiles = Get-ChildItem -Path $SqlArtifactsFolder -Filter "*.sql" | Sort-Object Name
if ($sqlFiles.Count -eq 0) {
    throw "No .sql files found in $SqlArtifactsFolder"
}

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    throw "psql is required but not found in PATH. Install PostgreSQL client tools first."
}

$env:PGPASSWORD = $PostgresPassword
try {
    foreach ($file in $sqlFiles) {
        Write-Host "Applying SQL artifact: $($file.Name)" -ForegroundColor Cyan
        & psql `
            --host $PostgresHost `
            --port 5432 `
            --username $PostgresUser `
            --dbname $PostgresDatabase `
            --set ON_ERROR_STOP=1 `
            --single-transaction `
            --file "$($file.FullName)"

        if ($LASTEXITCODE -ne 0) {
            throw "Failed while applying $($file.Name)"
        }
    }
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}

Write-Host "PostgreSQL SQL artifacts applied successfully." -ForegroundColor Green
