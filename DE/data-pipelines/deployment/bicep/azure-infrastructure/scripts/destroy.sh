#!/bin/bash

# ==================================================
# Azure Infrastructure Cleanup Script
# Credit Scoring + Agentic AI Platform
# ==================================================
# Resolves ENVIRONMENT, ORG_NAME, PROJECT_NAME from the environment; if any
# are unset, prompts interactively (same names as DEPLOYMENT_GUIDE.md session).

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Same names as deployment session / TEARDOWN.md (export after DEPLOYMENT_GUIDE §1, or pass inline)
if [ -z "${ENVIRONMENT}" ]; then
    read -r -p "Environment (dev/staging/prod) — same as \$ENVIRONMENT in DEPLOYMENT_GUIDE: " input
    ENVIRONMENT="${input}"
fi

while [ -z "${ORG_NAME}" ]; do
    read -r -p "Org name (required) — same as orgName / ORG_NAME in main.parameters.json: " ORG_NAME
done

while [ -z "${PROJECT_NAME}" ]; do
    read -r -p "Project name (required) — same as projectName / PROJECT_NAME in main.parameters.json: " PROJECT_NAME
done

NAMING_PREFIX="${ORG_NAME}-${PROJECT_NAME}-${ENVIRONMENT}"

case "${ENVIRONMENT}" in
    dev|staging|prod) ;;
    *)
        log_error "ENVIRONMENT must be dev, staging, or prod (got: ${ENVIRONMENT})"
        exit 1
        ;;
esac

list_resource_groups() {
    log_info "Finding resource groups for environment: $ENVIRONMENT"
    log_info "Naming prefix: $NAMING_PREFIX"

    az group list \
        --query "[?contains(name, '${NAMING_PREFIX}')].name" \
        -o tsv
}

delete_resource_groups() {
    local resource_groups
    resource_groups=$(list_resource_groups)

    if [ -z "$resource_groups" ]; then
        log_warn "No resource groups found matching: ${NAMING_PREFIX}"
        return 0
    fi

    log_info "Resource groups to be deleted:"
    echo "$resource_groups"
    echo ""

    log_warn "This will DELETE all resources in these resource groups!"
    read -p "Are you absolutely sure? Type 'DELETE' to confirm: " -r
    echo ""

    if [[ ! $REPLY == "DELETE" ]]; then
        log_warn "Deletion cancelled by user"
        exit 0
    fi

    for rg in $resource_groups; do
        log_info "Deleting resource group: $rg"
        az group delete --name "$rg" --yes --no-wait
    done

    log_info "Deletion initiated for all resource groups (running in background)"
}

main() {
    echo ""
    log_info "========================================"
    log_info "Azure Infrastructure Cleanup"
    log_info "Credit Scoring + Agentic AI Platform"
    log_info "========================================"
    echo ""

    delete_resource_groups

    echo ""
    log_info "========================================"
    log_info "Cleanup initiated successfully!"
    log_info "Use 'az group list' to monitor progress"
    log_info "========================================"
    echo ""
}

main "$@"
