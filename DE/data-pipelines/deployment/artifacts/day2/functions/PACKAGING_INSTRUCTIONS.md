# Function Packaging Instructions (ZIP Deploy)

Run these per function project.

```powershell
cd "C:\path\to\function-project"  # folder containing host.json
python -m pip install -r requirements.txt --target ".\.python_packages\lib\site-packages"
Compress-Archive -Path * -DestinationPath ".\functionapp-package.zip" -Force
```

Deploy:

```powershell
$RG_DATA = $DATA_RG
# Example: pick one app from the current resource group
$FUNC_APP = az functionapp list -g $RG_DATA --query "[0].name" -o tsv
az functionapp deployment source config-zip -g $RG_DATA -n $FUNC_APP --src ".\functionapp-package.zip"
az functionapp restart -g $RG_DATA -n $FUNC_APP
az functionapp function list -g $RG_DATA -n $FUNC_APP -o table
```
