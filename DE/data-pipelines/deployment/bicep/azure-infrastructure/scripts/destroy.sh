#!/bin/bash

# ==================================================
# Azure Infrastructure Cleanup Script
# Credit Scoring + Agentic AI Platform
# ==================================================

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# ==================================================
# Configuration
# ==================================================

ENVIRONMENT="${ENVIRONMENT:-dev}"
ORG_NAME="${ORG_NAME:-payswitch}"
PROJECT_NAME="${PROJECT_NAME:-creditscore}"
NAMING_PREFIX="${ORG_NAME}-${PROJECT_NAME}-${ENVIRONMENT}"

# ==================================================
# Functions
# ==================================================

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

list_resource_groups() {
    log_info "Finding resource groups for environment: $ENVIRONMENT"

    az group list \
        --query "[?contains(name, '${NAMING_PREFIX}')].name" \
        -o tsv
}

delete_resource_groups() {
    local resource_groups=$(list_resource_groups)

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

# ==================================================
# Main Execution
# ==================================================

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

# Run main function
main "$@"
