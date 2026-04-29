# Blob + ADLS Layout (Prod)

## Containers / filesystems
- `bronze`
- `silver`
- `curated`

## Required paths
- `bronze/training`
- `silver/training`
- `curated/ml-training`
- `curated/models`

## IAM target
- All Azure Functions except checksum calculator:
  - Blob Data Contributor on blob storage
  - Blob Data Contributor on data lake storage
