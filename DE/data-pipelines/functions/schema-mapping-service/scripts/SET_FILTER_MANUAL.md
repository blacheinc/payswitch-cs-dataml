# Manual Instructions: Set SQL Filter on start-transformation Subscription

If the PowerShell scripts are hanging or not working, you can set the filter manually using Azure Portal or Azure CLI.

## Option 1: Azure Portal (Easiest)

1. **Go to Azure Portal**: https://portal.azure.com
2. **Navigate to Service Bus**:
   - Resource Group: `blache-cdtscr-dev-data-rg`
   - Service Bus Namespace: `blache-cdtscr-dev-sb-y27jgavel2x32`
   - Topic: `data-ingested`
   - Subscription: `start-transformation`

3. **Set the Filter**:
   - Click on the `start-transformation` subscription
   - Go to **"Rules"** or **"Filters"** section
   - If there's a default rule (usually named `$Default`), delete it
   - Click **"Add rule"** or **"Create rule"**
   - Rule name: `ExcludeErrors`
   - Filter type: **SQL Filter**
   - SQL Expression: `[status] IS NULL OR [status] != 'ERROR'`
   - Click **Save**

## Option 2: Azure CLI (Single Command)

If Azure CLI is working, try this single command:

```powershell
az servicebus topic subscription rule create `
    --namespace-name "blache-cdtscr-dev-sb-y27jgavel2x32" `
    --resource-group "blache-cdtscr-dev-data-rg" `
    --topic-name "data-ingested" `
    --subscription-name "start-transformation" `
    --name "ExcludeErrors" `
    --filter-sql-expression "[status] IS NULL OR [status] != 'ERROR'"
```

**If the default rule exists**, delete it first:

```powershell
az servicebus topic subscription rule delete `
    --namespace-name "blache-cdtscr-dev-sb-y27jgavel2x32" `
    --resource-group "blache-cdtscr-dev-data-rg" `
    --topic-name "data-ingested" `
    --subscription-name "start-transformation" `
    --name "$Default"
```

## Option 3: Python Script (Using Azure SDK)

If Azure CLI is not working, use the Python script:

```powershell
python scripts\set_filter_python.py
```

## Verify the Filter

After setting the filter, verify it's working:

```powershell
az servicebus topic subscription rule show `
    --namespace-name "blache-cdtscr-dev-sb-y27jgavel2x32" `
    --resource-group "blache-cdtscr-dev-data-rg" `
    --topic-name "data-ingested" `
    --subscription-name "start-transformation" `
    --name "ExcludeErrors" `
    --query "filter.sqlFilter.sqlExpression" `
    --output tsv
```

Expected output: `[status] IS NULL OR [status] != 'ERROR'`

## What the Filter Does

- ✅ **Allows** messages with no `status` property (normal transformation requests)
- ✅ **Allows** messages with `status != 'ERROR'`
- ❌ **Rejects** messages with `status = 'ERROR'` (error messages go to `error` subscription)
