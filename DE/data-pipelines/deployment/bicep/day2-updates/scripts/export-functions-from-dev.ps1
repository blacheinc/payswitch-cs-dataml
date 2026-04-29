param(
    [Parameter(Mandatory = $true)]
    [string]$SubscriptionId,
    [Parameter(Mandatory = $true)]
    [string[]]$FunctionAppNames,
    [string]$OutputDirectory = "",
    [switch]$ExportHostKeys,
    [switch]$TemporarilyEnableScmBasicAuth
)

$ErrorActionPreference = "Stop"

function Get-HttpErrorSummary {
    param([Parameter(Mandatory = $true)]$ErrorRecord)
    try {
        $resp = $ErrorRecord.Exception.Response
        if ($null -ne $resp) {
            $statusCode = [int]$resp.StatusCode
            $statusText = [string]$resp.StatusDescription
            return "HTTP $statusCode $statusText"
        }
    }
    catch {
    }
    return $ErrorRecord.Exception.Message
}

function Get-HttpStatusCode {
    param([Parameter(Mandatory = $true)]$ErrorRecord)
    try {
        $resp = $ErrorRecord.Exception.Response
        if ($null -ne $resp) { return [int]$resp.StatusCode }
    }
    catch {
    }
    return -1
}

function Try-DownloadFromKudu {
    param(
        [Parameter(Mandatory = $true)][string]$ScmHost,
        [Parameter(Mandatory = $true)][hashtable]$Headers,
        [Parameter(Mandatory = $true)][string]$DestinationFile
    )

    # Primary: zip entire wwwroot
    $zipUrl = "https://$ScmHost/api/zip/site/wwwroot/"
    try {
        Invoke-WebRequest -Uri $zipUrl -Headers $Headers -OutFile $DestinationFile
        return $true
    }
    catch {
        $status = Get-HttpStatusCode -ErrorRecord $_
        if ($status -ne 404) {
            throw
        }
    }

    # Fallback: pull package from SitePackages (common on zip-deployed function apps)
    $sitePackagesUrl = "https://$ScmHost/api/vfs/data/SitePackages/"
    $items = Invoke-RestMethod -Uri $sitePackagesUrl -Headers $Headers -Method Get
    if ($null -eq $items) { return $false }

    $zipItems = @($items | Where-Object { $_.name -like "*.zip" })
    if ($zipItems.Count -eq 0) { return $false }

    $latest = $zipItems | Sort-Object { [datetime]$_.mtime } -Descending | Select-Object -First 1
    $downloadUrl = [string]$latest.href
    if ([string]::IsNullOrWhiteSpace($downloadUrl)) {
        $downloadUrl = "$sitePackagesUrl$($latest.name)"
    }

    Invoke-WebRequest -Uri $downloadUrl -Headers $Headers -OutFile $DestinationFile
    return $true
}

function Download-KuduZip {
    param(
        [Parameter(Mandatory = $true)][string]$AppName,
        [Parameter(Mandatory = $true)][string]$ResourceGroup,
        [Parameter(Mandatory = $true)][string]$DestinationFile
    )

    $scmHost = "$AppName.scm.azurewebsites.net"

    # Preferred: publishing credentials API (works reliably for Kudu basic auth)
    $publishingCreds = $null
    $credential401 = $false
    try {
        $publishingCreds = az webapp deployment list-publishing-credentials -g $ResourceGroup -n $AppName -o json | ConvertFrom-Json
    }
    catch {
        Write-Warning "Could not fetch publishing credentials for ${AppName}: $(Get-HttpErrorSummary -ErrorRecord $_)"
    }

    if ($null -ne $publishingCreds -and -not [string]::IsNullOrWhiteSpace([string]$publishingCreds.publishingUserName)) {
        $user = [string]$publishingCreds.publishingUserName
        $pass = [string]$publishingCreds.publishingPassword
        $pair = "$user`:$pass"
        $bytes = [System.Text.Encoding]::ASCII.GetBytes($pair)
        $encoded = [System.Convert]::ToBase64String($bytes)
        $headers = @{ Authorization = "Basic $encoded" }

        try {
            $downloaded = Try-DownloadFromKudu -ScmHost $scmHost -Headers $headers -DestinationFile $DestinationFile
            if (-not $downloaded) { throw "No downloadable zip found in Kudu endpoints." }
            return $true
        }
        catch {
            $msg = Get-HttpErrorSummary -ErrorRecord $_
            if ($msg -match "HTTP 401") { $credential401 = $true }
            Write-Warning "Kudu zip with publishing credentials failed for ${AppName}: $msg"
        }
    }

    # Fallback: publishing profile credentials
    try {
        $profilesJson = az webapp deployment list-publishing-profiles -g $ResourceGroup -n $AppName --xml
        [xml]$profiles = $profilesJson
        $msdeployProfile = $profiles.publishData.publishProfile | Where-Object { $_.publishMethod -eq "MSDeploy" } | Select-Object -First 1
        if ($null -eq $msdeployProfile) {
            Write-Warning "No MSDeploy publishing profile found for $AppName."
            return $false
        }

        $user = [string]$msdeployProfile.userName
        $pass = [string]$msdeployProfile.userPWD
        $pair = "$user`:$pass"
        $bytes = [System.Text.Encoding]::ASCII.GetBytes($pair)
        $encoded = [System.Convert]::ToBase64String($bytes)
        $headers = @{ Authorization = "Basic $encoded" }
        $downloaded = Try-DownloadFromKudu -ScmHost $scmHost -Headers $headers -DestinationFile $DestinationFile
        if (-not $downloaded) { throw "No downloadable zip found in Kudu endpoints." }
        return $true
    }
    catch {
        $msg = Get-HttpErrorSummary -ErrorRecord $_
        if ($msg -match "HTTP 401") { $credential401 = $true }
        Write-Warning "Kudu zip with publishing profile failed for ${AppName}: $msg"
        if ($credential401) {
            Write-Warning "SCM basic auth may be disabled on ${AppName}. Enable temporarily with:"
            Write-Warning "az resource update --resource-group $ResourceGroup --namespace Microsoft.Web --resource-type basicPublishingCredentialsPolicies --parent sites/$AppName --name scm --set properties.allow=true"
        }
        return $false
    }
}

function Set-ScmBasicAuthPolicy {
    param(
        [Parameter(Mandatory = $true)][string]$ResourceGroup,
        [Parameter(Mandatory = $true)][string]$AppName,
        [Parameter(Mandatory = $true)][bool]$Allow
    )
    $allowValue = if ($Allow) { "true" } else { "false" }

    az resource update `
      --resource-group $ResourceGroup `
      --namespace Microsoft.Web `
      --resource-type basicPublishingCredentialsPolicies `
      --parent "sites/$AppName" `
      --name scm `
      --set "properties.allow=$allowValue" | Out-Null

    $policyJson = az resource show `
      --resource-group $ResourceGroup `
      --namespace Microsoft.Web `
      --resource-type basicPublishingCredentialsPolicies `
      --parent "sites/$AppName" `
      --name scm `
      -o json
    $policy = $policyJson | ConvertFrom-Json
    $actual = [bool]$policy.properties.allow
    if ($actual -ne $Allow) {
        throw "SCM policy verification failed for $AppName. Expected allow=$Allow but got allow=$actual."
    }
}

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\artifacts\day2\functions")) "dev-export"
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

az account set --subscription $SubscriptionId | Out-Null

foreach ($appName in $FunctionAppNames) {
    Write-Host "Exporting function app: $appName" -ForegroundColor Cyan

    $rg = az functionapp list --query "[?name=='$appName'].resourceGroup | [0]" -o tsv
    if ([string]::IsNullOrWhiteSpace($rg)) {
        Write-Warning "Function app not found in current subscription: $appName"
        continue
    }

    $appDir = Join-Path $OutputDirectory $appName
    New-Item -ItemType Directory -Force -Path $appDir | Out-Null

    az functionapp show -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "functionapp-show.json")
    az functionapp identity show -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "identity.json")
    try {
        az functionapp config appsettings list -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "appsettings.json")
    }
    catch {
        Write-Warning "App settings export failed via functionapp command for ${appName}: $(Get-HttpErrorSummary -ErrorRecord $_)"
        try {
            az webapp config appsettings list -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "appsettings.json")
        }
        catch {
            Write-Warning "App settings export failed via webapp fallback for ${appName}: $(Get-HttpErrorSummary -ErrorRecord $_)"
        }
    }
    az webapp config access-restriction show -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "access-restrictions.json")
    az functionapp function list -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "functions.json")

    if ($ExportHostKeys) {
        try {
            az functionapp keys list -g $rg -n $appName -o json | Out-File -Encoding utf8 (Join-Path $appDir "host-keys.json")
        }
        catch {
            Write-Warning "Host keys export failed for ${appName}: $(Get-HttpErrorSummary -ErrorRecord $_)"
        }
    }

    $runFromPackage = az functionapp config appsettings list -g $rg -n $appName --query "[?name=='WEBSITE_RUN_FROM_PACKAGE'].value | [0]" -o tsv
    if (-not [string]::IsNullOrWhiteSpace($runFromPackage) -and ($runFromPackage.StartsWith("http://") -or $runFromPackage.StartsWith("https://"))) {
        Write-Host "Downloading package from WEBSITE_RUN_FROM_PACKAGE URL..." -ForegroundColor Yellow
        try {
            Invoke-WebRequest -Uri $runFromPackage -OutFile (Join-Path $appDir "functionapp-package.zip")
            "source=WEBSITE_RUN_FROM_PACKAGE_URL" | Out-File -Encoding utf8 (Join-Path $appDir "package-source.txt")
            continue
        }
        catch {
            Write-Warning "Failed WEBSITE_RUN_FROM_PACKAGE download for ${appName}: $(Get-HttpErrorSummary -ErrorRecord $_)"
        }
    }

    Write-Host "Downloading package from Kudu /api/zip/site/wwwroot/..." -ForegroundColor Yellow
    $tempEnabled = $false
    if ($TemporarilyEnableScmBasicAuth) {
        try {
            Set-ScmBasicAuthPolicy -ResourceGroup $rg -AppName $appName -Allow $true
            $tempEnabled = $true
            Write-Host "Temporarily enabled SCM basic auth for $appName" -ForegroundColor Yellow
        }
        catch {
            Write-Warning "Could not enable SCM basic auth for ${appName}: $(Get-HttpErrorSummary -ErrorRecord $_)"
        }
    }
    $downloaded = Download-KuduZip -AppName $appName -ResourceGroup $rg -DestinationFile (Join-Path $appDir "functionapp-package.zip")
    if ($downloaded) {
        "source=KUDU_ZIP_API" | Out-File -Encoding utf8 (Join-Path $appDir "package-source.txt")
    } else {
        Write-Warning "Failed to download Kudu zip for $appName after all methods."
    }

    if ($tempEnabled) {
        try {
            Set-ScmBasicAuthPolicy -ResourceGroup $rg -AppName $appName -Allow $false
            Write-Host "Restored SCM basic auth policy to disabled for $appName" -ForegroundColor Yellow
        }
        catch {
            Write-Warning "Could not restore SCM basic auth policy for ${appName}. Please set it back manually."
        }
    }
}

Write-Host "Function export completed. Output: $OutputDirectory" -ForegroundColor Green
