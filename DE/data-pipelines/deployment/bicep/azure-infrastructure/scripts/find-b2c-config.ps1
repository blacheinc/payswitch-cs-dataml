<#
.SYNOPSIS
    Helper script to identify Azure AD B2C tenant configuration for APIM deployment.

.DESCRIPTION
    This script helps you find your B2C tenant name, domain, and policy name
    so you can configure APIM deployment correctly.

.PARAMETER TenantName
    Optional: If you know your B2C tenant name, provide it to test the configuration.

.EXAMPLE
    .\find-b2c-config.ps1

.EXAMPLE
    .\find-b2c-config.ps1 -TenantName "blache-creditscore-b2c"
#>

param(
    [string]$TenantName = ""
)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Azure AD B2C Configuration Finder" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Method 1: Try to list B2C tenants (requires appropriate permissions)
Write-Host "Method 1: Querying Azure AD for B2C tenants..." -ForegroundColor Yellow
try {
    $tenants = az ad tenant list --query "[?contains(displayName, 'b2c') || contains(displayName, 'B2C')].{Name:displayName, Domain:defaultDomain, TenantId:tenantId}" -o json 2>$null | ConvertFrom-Json
    
    if ($tenants -and $tenants.Count -gt 0) {
        Write-Host "Found B2C tenants:" -ForegroundColor Green
        foreach ($tenant in $tenants) {
            Write-Host "  - Name: $($tenant.Name)" -ForegroundColor White
            Write-Host "    Domain: $($tenant.Domain)" -ForegroundColor Gray
            Write-Host "    Tenant ID: $($tenant.TenantId)" -ForegroundColor Gray
            Write-Host ""
        }
    } else {
        Write-Host "  No B2C tenants found via Azure AD query." -ForegroundColor Yellow
        Write-Host "  (This is normal if you don't have permissions or B2C is in a different tenant)" -ForegroundColor Gray
    }
} catch {
    Write-Host "  Could not query Azure AD tenants. This is normal if you don't have permissions." -ForegroundColor Yellow
}

Write-Host ""

# Method 2: Test a known tenant name
if ($TenantName) {
    Write-Host "Method 2: Testing provided tenant name: $TenantName" -ForegroundColor Yellow
    
    # Try common policy names
    $commonPolicies = @("B2C_1_SignUpSignIn", "B2C_1_SignUp", "B2C_1_SignIn", "B2C_1_DefaultSignUpSignIn")
    
    foreach ($policy in $commonPolicies) {
        $testUrl = "https://$TenantName.b2clogin.com/$TenantName.onmicrosoft.com/v2.0/.well-known/openid-configuration?p=$policy"
        Write-Host "  Testing: $testUrl" -ForegroundColor Gray
        
        try {
            $response = Invoke-WebRequest -Uri $testUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                Write-Host "  ✅ SUCCESS! Valid B2C configuration found:" -ForegroundColor Green
                Write-Host "     Tenant Name: $TenantName" -ForegroundColor White
                Write-Host "     Tenant Domain: $TenantName.onmicrosoft.com" -ForegroundColor White
                Write-Host "     Policy Name: $policy" -ForegroundColor White
                Write-Host ""
                Write-Host "  Use these values in your deployment:" -ForegroundColor Cyan
                Write-Host "    `$B2C_TENANT_NAME = `"$TenantName`"" -ForegroundColor Yellow
                Write-Host "    `$B2C_TENANT_DOMAIN = `"$TenantName.onmicrosoft.com`"" -ForegroundColor Yellow
                Write-Host "    `$B2C_POLICY_NAME = `"$policy`"" -ForegroundColor Yellow
                Write-Host ""
                return
            }
        } catch {
            Write-Host "    ❌ Failed (Status: $($_.Exception.Response.StatusCode.value__))" -ForegroundColor Red
        }
    }
    
    Write-Host "  No valid configuration found for tenant: $TenantName" -ForegroundColor Yellow
    Write-Host ""
}

# Method 3: Manual instructions
Write-Host "Method 3: Manual Configuration Steps" -ForegroundColor Yellow
Write-Host ""
Write-Host "If automatic detection didn't work, follow these steps:" -ForegroundColor White
Write-Host ""
Write-Host "1. Go to Azure Portal: https://portal.azure.com" -ForegroundColor Cyan
Write-Host "2. Search for 'Azure AD B2C' in the top search bar" -ForegroundColor Cyan
Write-Host "3. Select your B2C tenant" -ForegroundColor Cyan
Write-Host "4. Note the tenant name from the URL or Overview page:" -ForegroundColor Cyan
Write-Host "   Example: If URL is 'https://portal.azure.com/#@blache-creditscore-b2c.onmicrosoft.com'" -ForegroundColor Gray
Write-Host "   Then tenant name is: 'blache-creditscore-b2c'" -ForegroundColor Gray
Write-Host "   And domain is: 'blache-creditscore-b2c.onmicrosoft.com'" -ForegroundColor Gray
Write-Host ""
Write-Host "5. Go to 'User flows' (or 'User flows (legacy)') in the left menu" -ForegroundColor Cyan
Write-Host "6. Note the policy/user flow name (e.g., 'B2C_1_SignUpSignIn')" -ForegroundColor Cyan
Write-Host ""
Write-Host "6. Test the OpenID configuration URL in your browser:" -ForegroundColor Cyan
Write-Host "   https://YOUR-TENANT-NAME.b2clogin.com/YOUR-TENANT-DOMAIN/v2.0/.well-known/openid-configuration?p=YOUR-POLICY-NAME" -ForegroundColor Yellow
Write-Host ""
Write-Host "   If you see JSON output, the configuration is valid!" -ForegroundColor Green
Write-Host "   If you see 404 or error, double-check the tenant name, domain, and policy name." -ForegroundColor Red
Write-Host ""

# Method 4: Try to infer from naming prefix
Write-Host "Method 4: Inferring from naming prefix..." -ForegroundColor Yellow
$namingPrefix = $env:NAMING_PREFIX
if (-not $namingPrefix) {
    $namingPrefix = Read-Host "Enter your naming prefix (e.g., 'blache-creditscore-dev')"
}

if ($namingPrefix) {
    # Extract org name (first part before hyphen)
    $orgName = ($namingPrefix -split '-')[0]
    $possibleTenant = "$orgName-creditscore-b2c"
    
    Write-Host "  Based on naming prefix '$namingPrefix', possible B2C tenant: $possibleTenant" -ForegroundColor Gray
    Write-Host "  Testing..." -ForegroundColor Gray
    
    $testUrl = "https://$possibleTenant.b2clogin.com/$possibleTenant.onmicrosoft.com/v2.0/.well-known/openid-configuration?p=B2C_1_SignUpSignIn"
    try {
        $response = Invoke-WebRequest -Uri $testUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            Write-Host "  ✅ SUCCESS! Found valid configuration:" -ForegroundColor Green
            Write-Host "     Tenant Name: $possibleTenant" -ForegroundColor White
            Write-Host "     Tenant Domain: $possibleTenant.onmicrosoft.com" -ForegroundColor White
            Write-Host "     Policy Name: B2C_1_SignUpSignIn" -ForegroundColor White
            Write-Host ""
            Write-Host "  Use these values:" -ForegroundColor Cyan
            Write-Host "    `$B2C_TENANT_NAME = `"$possibleTenant`"" -ForegroundColor Yellow
            Write-Host "    `$B2C_TENANT_DOMAIN = `"$possibleTenant.onmicrosoft.com`"" -ForegroundColor Yellow
            Write-Host "    `$B2C_POLICY_NAME = `"B2C_1_SignUpSignIn`"" -ForegroundColor Yellow
            Write-Host ""
            return
        }
    } catch {
        Write-Host "  ❌ Not found. Try manual configuration steps above." -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Next Steps:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Once you have your B2C configuration, set these variables before deploying APIM:" -ForegroundColor White
Write-Host ""
Write-Host '  $B2C_TENANT_NAME = "your-b2c-tenant-name"' -ForegroundColor Yellow
Write-Host '  $B2C_TENANT_DOMAIN = "your-b2c-tenant.onmicrosoft.com"' -ForegroundColor Yellow
Write-Host '  $B2C_POLICY_NAME = "B2C_1_SignUpSignIn"  # or your actual policy name' -ForegroundColor Yellow
Write-Host ""
Write-Host "Then run the APIM deployment from the deployment guide." -ForegroundColor White
Write-Host ""
