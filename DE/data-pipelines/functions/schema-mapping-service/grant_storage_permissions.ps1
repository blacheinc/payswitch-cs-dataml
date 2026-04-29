# PowerShell script to grant Storage Blob Data Reader role
# Run this as a user with Owner or User Access Administrator role

$storageAccountName = "blachedly27jgavel2x32"
$resourceGroup = "blache-cdtscr-dev-data-rg"
$userObjectId = "dd8231df-62ae-4209-b224-56a9f512211b"  # Object ID for olujare.olanrewaju@gmail.com

# Get storage account scope
$scope = az storage account show `
    --name $storageAccountName `
    --resource-group $resourceGroup `
    --query "id" `
    --output tsv

Write-Host "Granting 'Storage Blob Data Reader' role to user (Object ID: $userObjectId) on $storageAccountName..."
Write-Host "Scope: $scope"

# Grant the role
az role assignment create `
    --role "Storage Blob Data Reader" `
    --scope $scope `
    --assignee $userObjectId

Write-Host "`nRole assignment complete!"
Write-Host "Note: It may take a few minutes for permissions to propagate."
