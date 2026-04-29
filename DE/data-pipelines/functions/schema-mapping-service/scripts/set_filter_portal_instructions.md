# Set Filter via Azure Portal (No Azure CLI Required)

Since Azure CLI is not working, use Azure Portal to set the filter manually.

## Step-by-Step Instructions

### 1. Open Azure Portal
- Go to: https://portal.azure.com
- Sign in with your Azure account

### 2. Navigate to Service Bus Subscription
1. In the search bar at the top, type: `blache-cdtscr-dev-sb-y27jgavel2x32`
2. Click on the Service Bus namespace
3. In the left menu, click **"Topics"**
4. Click on **"data-ingested"**
5. In the left menu, click **"Subscriptions"**
6. Click on **"start-transformation"**

### 3. Check Existing Rules
1. In the subscription page, look for **"Rules"** or **"Filters"** in the left menu
2. Click on it to see existing rules
3. If you see a rule named **"$Default"** or a rule with filter `1=1`:
   - Click on it
   - Click **"Delete"** button
   - Confirm deletion

### 4. Create New Filter Rule
1. Click **"+ Add rule"** or **"Create rule"** button
2. Fill in the form:
   - **Rule name**: `ExcludeErrors`
   - **Filter type**: Select **"SQL Filter"**
   - **SQL Expression**: Enter exactly this:
     ```
     [status] IS NULL OR [status] != 'ERROR'
     ```
3. Click **"Create"** or **"Save"**

### 5. Verify
1. Go back to the Rules list
2. You should see the `ExcludeErrors` rule with the SQL expression
3. The subscription will now only receive messages that match this filter

## What This Filter Does

- ✅ **Allows** messages with no `status` property (normal transformation requests from ADF)
- ✅ **Allows** messages with `status != 'ERROR'`
- ❌ **Rejects** messages with `status = 'ERROR'` (these go to the `error` subscription)

## Next Steps

After setting the filter:
1. Clear old error messages from the subscription (use the Python script or Azure Portal)
2. Send a new test message: `python scripts\send_test_message.py`

## Alternative: Use Python Script

If you prefer automation, use the Python script that uses Azure SDK:
```powershell
python scripts\set_filter_python.py
```

This uses Azure SDK (not Azure CLI) and should work even if Azure CLI is broken.
