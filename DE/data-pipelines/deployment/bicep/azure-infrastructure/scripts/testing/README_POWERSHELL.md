# Infrastructure Testing Suite - PowerShell Version

**Purpose:** PowerShell (.ps1) versions of all test scripts for Windows users.

**Paths:** All `cd …` examples assume your current directory is the **repository root** (the folder that contains `data-pipelines/`).

**Destroy-only:** See **[../../docs/TEARDOWN.md](../../docs/TEARDOWN.md)** for `destroy.ps1` / `destroy.sh` without the test-and-teardown flow.

**Naming:** Use your real **`<environment>`** and **`<org>-<project>-<environment>`** (same as `main.*.parameters.json`). See **[../../docs/OPERATOR_CONFIGURATION.md](../../docs/OPERATOR_CONFIGURATION.md)**.

## Overview

This directory contains **PowerShell (.ps1)** versions of all test scripts, designed to work natively on Windows without requiring WSL, Git Bash, or bash.

## Test Scripts (PowerShell)

| Script | Phase | Resources Tested |
|--------|-------|------------------|
| `test-phase-0.ps1` | Phase 0 | Key Vault, Azure Monitor, VNet, Storage Account |
| `test-phase-1.ps1` | Phase 1 | PostgreSQL, Redis, Data Lake Gen2 |
| `test-phase-2.ps1` | Phase 2 | Service Bus, Data Factory, Cosmos DB, Azure Functions |
| `test-phase-3.ps1` | Phase 3 | Azure ML Workspace, AKS, Container Registry |
| `test-phase-4.ps1` | Phase 4 | API Management, Static Web Apps, Azure AD B2C |
| `test-phase-5.ps1` | Phase 5 | Full system, end-to-end connectivity |

### Orchestrator Scripts

| Script | Purpose |
|--------|---------|
| `test-all-phases.ps1` | Run all phase tests in sequence |
| `test-and-teardown.ps1` | Deploy → Test → Teardown workflow |

## Prerequisites

1. **PowerShell 5.1+** (Windows 10/11 includes PowerShell 5.1)
   ```powershell
   $PSVersionTable.PSVersion
   ```

2. **Azure CLI** installed and configured
   ```powershell
   az --version  # Should be 2.50+
   az login
   az account set --subscription "YOUR_SUBSCRIPTION_ID"
   ```

3. **Execution Policy** (may need to be set)
   ```powershell
   # Check current policy
   Get-ExecutionPolicy
   
   # If Restricted, set to RemoteSigned (for local scripts)
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

4. **Permissions:**
   - Owner or Contributor role on Azure subscription
   - Ability to create/delete resource groups

## Usage

### Option 1: Test Single Phase

```powershell
cd data-pipelines\deployment\bicep\azure-infrastructure\scripts\testing

# Test Phase 0 (Core Infrastructure)
.\test-phase-0.ps1 -Environment '<environment>' -NamingPrefix '<org>-<project>-<environment>'

# Test Phase 1 (Data Layer)
.\test-phase-1.ps1 -Environment '<environment>' -NamingPrefix '<org>-<project>-<environment>'

# Test Phase 2 (Data Ingestion)
.\test-phase-2.ps1 -Environment '<environment>' -NamingPrefix '<org>-<project>-<environment>'
```

**Parameters:**
- `-Environment`: Environment name (**required**; `dev`, `staging`, or `prod`)
- `-NamingPrefix`: Naming prefix (optional if `$env:NAMING_PREFIX` or both `$env:ORG_NAME` and `$env:PROJECT_NAME` are set)

### Option 2: Test All Phases

```powershell
cd data-pipelines\deployment\bicep\azure-infrastructure\scripts\testing

# Run all phase tests
.\test-all-phases.ps1 -Environment '<environment>' -NamingPrefix '<org>-<project>-<environment>'
```

### Option 3: Deploy → Test → Teardown

**Note:** The `test-and-teardown.ps1` script requires `bash` (for deploy.sh and destroy.sh). If you don't have bash, you'll need to:

1. **Install WSL or Git Bash**, OR
2. **Deploy manually** using Azure CLI, then run tests

```powershell
cd data-pipelines\deployment\bicep\azure-infrastructure\scripts\testing

# Deploy Phase 0, test it, then tear it down
.\test-and-teardown.ps1 -Environment '<environment>' -Phase 0 -NamingPrefix '<org>-<project>-<environment>' -Teardown yes

# Deploy Phase 1, test it, keep resources (no teardown)
.\test-and-teardown.ps1 -Environment '<environment>' -Phase 1 -NamingPrefix '<org>-<project>-<environment>' -Teardown no
```

**Parameters:**
- `-Environment`: Environment name (**required**; `dev`, `staging`, or `prod`)
- `-Phase`: Phase number (0-5, default: `0`)
- `-NamingPrefix`: Naming prefix (optional if `$env:NAMING_PREFIX` or both `$env:ORG_NAME` and `$env:PROJECT_NAME` are set)
- `-Teardown`: Teardown after tests (`yes` or `no`, default: `yes`)

## Manual Deployment (if bash not available)

If you don't have bash/WSL/Git Bash, deploy manually:

```powershell
cd data-pipelines\deployment\bicep\azure-infrastructure\bicep-templates

# Validate deployment
az deployment sub validate `
  --location eastus `
  --template-file main.bicep `
  --parameters @main.parameters.json `
  --parameters environment=dev

# Deploy
az deployment sub create `
  --location eastus `
  --template-file main.bicep `
  --parameters @main.parameters.json `
  --parameters environment=dev `
  --name "creditscore-dev-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
```

Then run tests:

```powershell
cd ..\scripts\testing
.\test-phase-0.ps1 -Environment '<environment>' -NamingPrefix '<org>-<project>-<environment>'
```

## Test Results

### Output Format

Each test script outputs:
- **Test name** - What is being tested
- **Pass/Fail status** - ✓ or ✗ with color coding
- **Summary** - Total tests, passed, failed, pass rate

### Exit Codes

- `0` - All tests passed
- `1` - Some tests failed

### Example Output

```
========================================
Phase 0 Infrastructure Tests
Environment: dev
Naming Prefix: <org>-<project>-<environment>
========================================

=== Resource Groups ===

[TEST] Resource Groups Created
✓ PASSED: Resource Groups Created

=== Key Vault ===

[TEST] Key Vault Exists
✓ PASSED: Key Vault Exists

...

========================================
Phase 0 Test Summary
========================================

Total Tests:    12
Passed:         12
Failed:         0
Pass Rate:      100%

✓ All Phase 0 tests PASSED
```

## Troubleshooting

### Error: "Execution Policy Restriction"

**Error:** `cannot be loaded because running scripts is disabled on this system`

**Solution:**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### Error: "az: command not found"

**Error:** Azure CLI not found

**Solution:**
1. Install Azure CLI: https://aka.ms/installazurecliwindows
2. Restart PowerShell after installation
3. Verify: `az --version`

### Error: "Not logged in to Azure"

**Error:** `Please run 'az login' first`

**Solution:**
```powershell
az login
az account set --subscription "YOUR_SUBSCRIPTION_ID"
az account show  # Verify
```

### Test Fails: "Resource not found"

**Cause:** Resource not deployed yet or naming mismatch

**Solution:**
1. Verify deployment completed successfully
2. Check naming prefix: `az group list --query "[?contains(name, '<org>-<project>-<environment>')].name"`
3. Verify resource exists: `az <service> list --query "[?contains(name, '<org>-<project>-<environment>')].name"`

### Test-and-Teardown: "bash not found"

**Error:** `bash not found` when running test-and-teardown.ps1

**Solution:**
- **Option 1:** Install Git Bash (includes bash)
- **Option 2:** Install WSL (Windows Subsystem for Linux)
- **Option 3:** Deploy and destroy manually using Azure CLI, then run tests separately

## Differences from Bash Version

1. **File Extensions:** `.ps1` instead of `.sh`
2. **Execution:** Run with `.\script.ps1` instead of `./script.sh`
3. **Parameters:** Use `-Parameter value` instead of positional arguments
4. **Error Handling:** PowerShell try/catch instead of bash `set -e`
5. **Arrays:** PowerShell arrays `@()` instead of bash arrays
6. **String Matching:** PowerShell `-match` instead of `grep`

## Best Practices

1. **Test Before Development:**
   - Run tests after each phase deployment
   - Verify all tests pass before proceeding to next phase

2. **Use Teardown for Testing:**
   - Use `test-and-teardown.ps1` to avoid leaving test resources running
   - Only skip teardown if you need to inspect resources manually

3. **Test Incrementally:**
   - Test Phase 0 first, then Phase 1, etc.
   - Don't skip phases - each phase depends on previous ones

4. **Review Failed Tests:**
   - Check failed test names in output
   - Verify resources exist in Azure Portal
   - Check deployment logs for errors

## Related Documentation

- [Bash Version README](./README.md) - For Linux/WSL/Git Bash users
- [Phased Deployment Plan](../../../../project_documentation/Planning_phase/PHASED_DEPLOYMENT_PLAN_DEV.md)
- [Infrastructure Deployment Guide](../README.md)
