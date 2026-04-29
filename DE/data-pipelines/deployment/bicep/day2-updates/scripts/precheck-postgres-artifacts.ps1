param(
    [Parameter(Mandatory = $true)]
    [string]$PostgresHost,
    [Parameter(Mandatory = $true)]
    [string]$PostgresDatabase,
    [Parameter(Mandatory = $true)]
    [string]$PostgresUser,
    [Parameter(Mandatory = $true)]
    [string]$PostgresPassword,
    [switch]$SkipWriteProbe
)

$ErrorActionPreference = "Stop"

if (-not (Get-Command psql -ErrorAction SilentlyContinue)) {
    throw "psql is required but not found in PATH. Install PostgreSQL client tools first."
}

$env:PGPASSWORD = $PostgresPassword
try {
    Write-Host "Postgres precheck: connectivity/auth..." -ForegroundColor Cyan
    & psql `
        --host $PostgresHost `
        --port 5432 `
        --username $PostgresUser `
        --dbname $PostgresDatabase `
        --set ON_ERROR_STOP=1 `
        --command "SELECT current_user AS current_user, current_database() AS current_database, version() AS server_version;"
    if ($LASTEXITCODE -ne 0) { throw "Failed connectivity/auth check." }

    Write-Host "Postgres precheck: required extension probe (pgcrypto)..." -ForegroundColor Cyan
    & psql `
        --host $PostgresHost `
        --port 5432 `
        --username $PostgresUser `
        --dbname $PostgresDatabase `
        --set ON_ERROR_STOP=1 `
        --command "SELECT extname FROM pg_extension WHERE extname = 'pgcrypto';"
    if ($LASTEXITCODE -ne 0) { throw "Failed extension probe." }

    Write-Host "Postgres precheck: schema visibility (public)..." -ForegroundColor Cyan
    & psql `
        --host $PostgresHost `
        --port 5432 `
        --username $PostgresUser `
        --dbname $PostgresDatabase `
        --set ON_ERROR_STOP=1 `
        --command "SELECT nspname FROM pg_namespace WHERE nspname='public';"
    if ($LASTEXITCODE -ne 0) { throw "Failed schema visibility check." }

    if (-not $SkipWriteProbe) {
        Write-Host "Postgres precheck: write probe in rollback transaction..." -ForegroundColor Cyan
        & psql `
            --host $PostgresHost `
            --port 5432 `
            --username $PostgresUser `
            --dbname $PostgresDatabase `
            --set ON_ERROR_STOP=1 `
            --command "BEGIN; CREATE TABLE IF NOT EXISTS public.__day2_precheck_probe(id int); DROP TABLE IF EXISTS public.__day2_precheck_probe; ROLLBACK;"
        if ($LASTEXITCODE -ne 0) {
            throw "Write probe failed. User likely lacks CREATE privilege on schema public."
        }
    } else {
        Write-Host "Skipped write probe (-SkipWriteProbe)." -ForegroundColor Yellow
    }

    Write-Host "Postgres precheck passed." -ForegroundColor Green
}
finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
