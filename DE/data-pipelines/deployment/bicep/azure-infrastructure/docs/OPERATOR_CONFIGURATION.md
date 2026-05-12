# Operator configuration — what to fill before running scripts

This repo does **not** embed a real organization or project in templates. You choose one **canonical parameter file** for subscription infrastructure, edit it, then point scripts at it (or load values into your shell).

## Canonical source: `main.*.parameters.json`

**Path:** `bicep-templates/main.parameters.json` and `bicep-templates/main.prod.parameters.json`.

| Parameter | What to put |
|-----------|-------------|
| `orgName` | Short org segment for Azure **names** and usually `tags.Owner` — lowercase, no spaces (hyphens OK). Replace placeholder `YOUR_ORG_SLUG`. |
| `projectName` | Short project segment; with `environment` forms the prefix **`<org>-<project>-<environment>`**. Replace `YOUR_PROJECT_SLUG`. |
| `environment` | `dev`, `staging`, or `prod`. Must match the file you intend to deploy and any Day 2 / Phase 2 paths you use. |
| `primaryLocation` / `secondaryLocation` | Azure regions; must stay consistent with Phase 2 `location` when you deploy data ingestion. |
| `tags` | Full tag object **from your file only** (the template has no default). Keep `tags.Environment` aligned with `environment`. Set `Owner` to the same string as `orgName` unless policy says otherwise. |
| `adminEmail` | Real contact for alerts; replace `admin@example.com` (or empty in prod file until you set it securely). |
| Feature flags | `privateNetworkMode`, `enableOpenAI`, jump box passwords in prod file, etc. — per runbook. |

After this file reflects your org, **resource naming** in Azure follows **`orgName` + `projectName` + `environment`** (see deployment outputs / runbooks).

## Which main template to deploy

- `bicep-templates/main.default.bicep` -> default/non-private posture (`privateNetworkMode=false`)
- `bicep-templates/main.private.bicep` -> private posture (`privateNetworkMode=true`)

Both wrappers call `main.bicep` and keep the same outputs for downstream scripts.

## Load the same values into your shell (optional)

So `destroy`, testing scripts, and other tools see `ORG_NAME` / `PROJECT_NAME` / `ENVIRONMENT` / `NAMING_PREFIX` without retyping:

**PowerShell** (from `azure-infrastructure/scripts`; dot-source so variables stay in your session):

```powershell
. .\Sync-EnvFromMainParameters.ps1
# or a specific file:
. .\Sync-EnvFromMainParameters.ps1 -ParametersPath ..\bicep-templates\main.prod.parameters.json
```

**Bash** (requires `jq`):

```bash
cd data-pipelines/deployment/bicep/azure-infrastructure/scripts
source ./sync-env-from-main-parameters.sh
# or:
source ./sync-env-from-main-parameters.sh ../bicep-templates/main.prod.parameters.json
```

## After `main.bicep` is deployed: ARM outputs

To load **deployment outputs** (storage names, resource groups, etc.) by deployment name, use **`scripts/set-vars-from-main-deployment.ps1`** (see that script’s comment block). That is separate from the parameter file; it runs **after** a successful subscription deployment.

## Other files you may need before “full” platform work

Order depends on your path; the map is in **`HOW_DEPLOYMENT_FITS_TOGETHER.md`**.

1. **Phase 2 (data ingestion)** — JSON under `phase2-data-ingestion/` (see Phase 2 `parameters/README.md` and `DEPLOYMENT_GUIDE.md`).
2. **Day 2 updates** — JSON under `day2-updates/parameters/<environment>/` (match your `environment` value).
3. **Function apps** — copy `local.settings.json.example` → `local.settings.json` (gitignored) per function; never commit secrets.
4. **Azure DevOps** — variable group fields documented in **`azure-devops/README.md`** (`azureServiceConnection`, `infraOrgSlug`, `infraProjectSlug`, `approvalNotifyEmails`, `deploymentPrimaryLocation`).

## Placeholder tokens in `main.parameters.json`

Replace them with your real identifiers before any production or long‑lived subscription:

| Token in JSON | Meaning |
|---------------|---------|
| `YOUR_ORG_SLUG` | Same value you will use for `orgName`: short org segment for Azure names and typically `tags.Owner` (lowercase, no spaces; hyphens OK). |
| `YOUR_PROJECT_SLUG` | Same value as `projectName`: short project segment in `<org>-<project>-<environment>`. |
| `admin@example.com` | Replace with a real operations contact for `adminEmail`. |

Keep **`tags.Environment`** equal to the **`environment`** parameter value in the same file.

## Placeholders must be replaced before real deploy

If you deploy with placeholders still in the file, Azure will accept the deployment but resources will carry the wrong **logical** identity. Replace tokens first.
