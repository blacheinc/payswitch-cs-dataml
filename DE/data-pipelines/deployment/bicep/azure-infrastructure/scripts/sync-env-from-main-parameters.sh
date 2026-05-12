#!/usr/bin/env bash
# Reads org/project/environment from main.*.parameters.json and exports ORG_NAME, PROJECT_NAME, ENVIRONMENT, NAMING_PREFIX.
# Requires jq. Usage:
#   source ./sync-env-from-main-parameters.sh
#   source ./sync-env-from-main-parameters.sh /path/to/main.prod.parameters.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARAMS="${1:-${SCRIPT_DIR}/../bicep-templates/main.parameters.json}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required (https://stedolan.github.io/jq/)." >&2
  return 2 2>/dev/null || exit 2
fi

if [[ ! -f "${PARAMS}" ]]; then
  echo "Parameter file not found: ${PARAMS}" >&2
  return 1 2>/dev/null || exit 1
fi

export ORG_NAME="$(jq -r '.parameters.orgName.value // empty' "${PARAMS}")"
export PROJECT_NAME="$(jq -r '.parameters.projectName.value // empty' "${PARAMS}")"
export ENVIRONMENT="$(jq -r '.parameters.environment.value // empty' "${PARAMS}")"
export PRIMARY_LOCATION="$(jq -r '.parameters.primaryLocation.value // empty' "${PARAMS}")"
export ADMIN_EMAIL="$(jq -r '.parameters.adminEmail.value // empty' "${PARAMS}")"

if [[ -z "${ORG_NAME}" || -z "${PROJECT_NAME}" || -z "${ENVIRONMENT}" ]]; then
  echo "orgName, projectName, and environment must be non-empty in ${PARAMS}" >&2
  return 1 2>/dev/null || exit 1
fi

export NAMING_PREFIX="${ORG_NAME}-${PROJECT_NAME}-${ENVIRONMENT}"

echo "Loaded from ${PARAMS}"
echo "  ORG_NAME=${ORG_NAME}  PROJECT_NAME=${PROJECT_NAME}  ENVIRONMENT=${ENVIRONMENT}  NAMING_PREFIX=${NAMING_PREFIX}"
