// Bastion host + private jump VM for VNet-only troubleshooting (via Azure Bastion).

targetScope = 'resourceGroup'

@description('Azure region for deployment')
param location string

@description('Naming prefix for resources')
param namingPrefix string

@description('Subnet ID for AzureBastionSubnet')
param bastionSubnetId string

@description('Subnet ID for the jump VM NIC')
param jumpSubnetId string

@description('Windows admin username')
param jumpVmAdminUsername string

@secure()
@description('Windows admin password for jump VM')
param jumpVmAdminPassword string

@description('Jump VM size')
param jumpVmSize string

@description('Resource tags')
param tags object

@description('When false, no Bastion/jump resources are created (outputs remain empty strings).')
param deploy bool = true

resource bastionPublicIp 'Microsoft.Network/publicIPAddresses@2023-09-01' = if (deploy) {
  name: '${namingPrefix}-bastion-pip'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
  }
}

resource bastionHost 'Microsoft.Network/bastionHosts@2023-09-01' = if (deploy) {
  name: '${namingPrefix}-bastion'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  properties: {
    ipConfigurations: [
      {
        name: 'bastion-ip-config'
        properties: {
          publicIPAddress: {
            id: bastionPublicIp.id
          }
          subnet: {
            id: bastionSubnetId
          }
        }
      }
    ]
  }
}

resource jumpNic 'Microsoft.Network/networkInterfaces@2023-09-01' = if (deploy) {
  name: '${namingPrefix}-jump-nic'
  location: location
  tags: tags
  properties: {
    ipConfigurations: [
      {
        name: 'ipconfig1'
        properties: {
          subnet: {
            id: jumpSubnetId
          }
          privateIPAllocationMethod: 'Dynamic'
        }
      }
    ]
  }
}

resource jumpVm 'Microsoft.Compute/virtualMachines@2024-07-01' = if (deploy) {
  name: '${namingPrefix}-jump-vm'
  location: location
  tags: tags
  properties: {
    hardwareProfile: {
      vmSize: jumpVmSize
    }
    storageProfile: {
      imageReference: {
        publisher: 'MicrosoftWindowsServer'
        offer: 'WindowsServer'
        sku: '2022-datacenter-azure-edition'
        version: 'latest'
      }
      osDisk: {
        name: '${namingPrefix}-jump-os'
        caching: 'ReadWrite'
        createOption: 'FromImage'
        managedDisk: {
          storageAccountType: 'StandardSSD_LRS'
        }
      }
    }
    osProfile: {
      computerName: 'jumpvmwin'
      adminUsername: jumpVmAdminUsername
      adminPassword: jumpVmAdminPassword
      windowsConfiguration: {
        provisionVMAgent: true
        enableAutomaticUpdates: true
      }
    }
    networkProfile: {
      networkInterfaces: [
        {
          id: jumpNic.id
          properties: {
            primary: true
          }
        }
      ]
    }
  }
}

output bastionHostName string = deploy ? bastionHost.name : ''
output jumpVmName string = deploy ? jumpVm.name : ''
