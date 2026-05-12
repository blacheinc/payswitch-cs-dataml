# Infrastructure teardown (subscription resource groups)

This runbook describes how to **delete Azure resource groups** that were created by **`main.bicep`**, using the cleanup scripts next to the other operational scripts.

It does **not** replace the optional **test** workflow (`test-and-teardown` under `scripts/testing/`). For that, see `scripts/testing/README.md`.

## What the scripts do

Both scripts find every resource group in the **current subscription** whose **name contains** this string:

```text
<orgName>-<projectName>-<environment>
```

The naming prefix is always **`<orgName>-<projectName>-<environment>`** (same segments as in your `main.*.parameters.json`).

They then run **`az group delete --yes --no-wait`** on each match (async delete). Anything still outside those groups (other subscriptions, RGs with different naming) is untouched.

## Same values as the deployment session

These are the three values **`destroy.ps1`** and **`destroy.sh`** need. They match **`DEPLOYMENT_GUIDE.md` §1** and **`main.*.parameters.json`**:

| Teardown input | Deployment guide (PowerShell §1) | `main.parameters.json` field |
|----------------|-----------------------------------|--------------------------------|
| **Environment** | `$ENVIRONMENT` | `parameters.environment` |
| **Org name** | `$ORG_NAME` | `parameters.orgName` |
| **Project name** | `$PROJECT_NAME` | `parameters.projectName` |

### PowerShell: copy session variables into the process environment

A script **child process** does not see your `$ENVIRONMENT` / `$ORG_NAME` / `$PROJECT_NAME` unless you put them on **`$env:...`** (or pass parameters). After you set up §1 in **`DEPLOYMENT_GUIDE.md`**, run:

```powershell
$env:ENVIRONMENT   = $ENVIRONMENT
$env:ORG_NAME      = $ORG_NAME
$env:PROJECT_NAME  = $PROJECT_NAME

cd data-pipelines\deployment\bicep\azure-infrastructure\scripts
.\destroy.ps1
```

If any of **`$env:ENVIRONMENT`**, **`$env:ORG_NAME`**, or **`$env:PROJECT_NAME`** is still empty, **`destroy.ps1`** prompts until org and project are non-empty (no baked-in defaults).

You can still override on the command line:

```powershell
.\destroy.ps1 -Environment prod -OrgName YOUR_ORG -ProjectName YOUR_PROJECT
```

| Parameter | Notes |
|-----------|--------|
| `-Environment` | Optional if **`$env:ENVIRONMENT`** is set or you answer the prompt. |
| `-OrgName` | Optional if **`$env:ORG_NAME`** is set or you answer the prompt. |
| `-ProjectName` | Optional if **`$env:PROJECT_NAME`** is set or you answer the prompt. |
| `-Force` | Skips the final **`DELETE`** confirmation (automation only). |

### Bash: export the same names

```bash
export ENVIRONMENT=dev
export ORG_NAME=YOUR_ORG
export PROJECT_NAME=YOUR_PROJECT

cd data-pipelines/deployment/bicep/azure-infrastructure/scripts
./destroy.sh
```

If **`ENVIRONMENT`**, **`ORG_NAME`**, or **`PROJECT_NAME`** is unset, **`destroy.sh`** prompts until all three are set (no baked-in defaults for org/project).

## Before you run

1. **`az login`** and **`az account set --subscription …`** on the subscription you intend to clean.
2. Confirm the **naming prefix** matches what **`main.bicep`** used (`orgName`, `projectName`, `environment` in your parameter file).
3. Understand that this is **destructive**: all resources inside matching resource groups are removed.

## PowerShell — `scripts/destroy.ps1`

**Repo-relative path:** `data-pipelines/deployment/bicep/azure-infrastructure/scripts/destroy.ps1`

See **Same values as the deployment session** above for **`$env:...`** and prompts.

## Bash — `scripts/destroy.sh`

**Repo-relative path:** `data-pipelines/deployment/bicep/azure-infrastructure/scripts/destroy.sh`

See **Same values as the deployment session** above.

Inline example (no prior export):

```bash
cd data-pipelines/deployment/bicep/azure-infrastructure/scripts

ENVIRONMENT=dev ORG_NAME=YOUR_ORG PROJECT_NAME=YOUR_PROJECT ./destroy.sh
```

You will be prompted to type **`DELETE`** to confirm (there is no `-Force` flag in the shell script).

## After deletion

Deletion is **asynchronous** (`--no-wait`). Monitor with:

```bash
az group list --query "[?contains(name, '<org>-<project>-<environment>')].{Name:name, State:properties.provisioningState}" -o table
```

Adjust the substring to your real prefix.

## Related

- Deploy / private paths: `DEPLOYMENT_GUIDE.md`, `PRIVATE_DEPLOYMENT_GUIDE.md`
- Map of folders: `HOW_DEPLOYMENT_FITS_TOGETHER.md`
