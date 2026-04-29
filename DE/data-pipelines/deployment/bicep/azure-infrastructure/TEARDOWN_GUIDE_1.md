# Dev Teardown Guide

This guide destroys the full dev environment created by `main.bicep`.

It deletes every resource group returned by the deployment output `resourceGroupNames`:
- core
- networking
- data
- compute
- ml
- security
- monitoring
- agents

## 1) Set session variables

```powershell
$WORKSPACE = "C:\Users\olanr\Desktop\blache"
$SCRIPTS = Join-Path $WORKSPACE "data-pipelines\deployment\bicep\azure-infrastructure\scripts"

# Optional
$SUBSCRIPTION_ID = ""

# Use your original successful main deployment name
$DEPLOYMENT_NAME_MAIN = az deployment sub list `
  --query "[?starts_with(name, 'main-dev-') && properties.provisioningState=='Succeeded'] | sort_by(@, &properties.timestamp) | [-1].name" `
  -o tsv

"DEPLOYMENT_NAME_MAIN = $DEPLOYMENT_NAME_MAIN"
```

If `$DEPLOYMENT_NAME_MAIN` is empty, list deployments manually and set it:

```powershell
az deployment sub list --query "[].{Name:name,State:properties.provisioningState,Time:properties.timestamp}" -o table
```

## 2) Run teardown (safe confirmation mode)

```powershell
cd $SCRIPTS

.\teardown-dev.ps1 `
  -DeploymentName $DEPLOYMENT_NAME_MAIN `
  -SubscriptionId $SUBSCRIPTION_ID
```

The script will print all resolved resource groups and require exact confirmation text:

`DESTROY DEV`

## 3) Optional non-interactive mode

```powershell
cd $SCRIPTS

.\teardown-dev.ps1 `
  -DeploymentName $DEPLOYMENT_NAME_MAIN `
  -SubscriptionId $SUBSCRIPTION_ID `
  -Force
```

## 4) Verify deletions

```powershell
az group list --query "[?contains(name, 'dev')].{name:name,location:location}" -o table
```

If any target resource group remains, run:

```powershell
az group delete --name "<remaining-rg-name>" --yes
```
