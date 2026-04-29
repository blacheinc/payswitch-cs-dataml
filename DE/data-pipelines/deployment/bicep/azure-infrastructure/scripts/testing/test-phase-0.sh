#!/bin/bash
# ==================================================
# Phase 0 Infrastructure Tests
# Core Infrastructure: Key Vault, Monitoring, VNet, Storage
# ==================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
ENVIRONMENT="${1:-dev}"
NAMING_PREFIX="${2:-blache-${ENVIRONMENT}}"
TIMEOUT=60

TESTS_PASSED=0
TESTS_FAILED=0
FAILED_TESTS=()

# Test function
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    echo -e "\n${YELLOW}[TEST]${NC} ${test_name}"
    
    if eval "$test_command" 2>/dev/null; then
        echo -e "${GREEN}✓ PASSED: ${test_name}${NC}"
        ((TESTS_PASSED++))
        return 0
    else
        echo -e "${RED}✗ FAILED: ${test_name}${NC}"
        ((TESTS_FAILED++))
        FAILED_TESTS+=("${test_name}")
        return 1
    fi
}

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 0 Infrastructure Tests${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}========================================${NC}"

# ==================================================
# Resource Group Tests
# ==================================================

echo -e "\n${BLUE}=== Resource Groups ===${NC}"

run_test "Resource Groups Created" "
    RG_COUNT=\$(az group list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    [ \"\${RG_COUNT}\" -ge 5 ]
"

# ==================================================
# Key Vault Tests
# ==================================================

echo -e "\n${BLUE}=== Key Vault ===${NC}"

run_test "Key Vault Exists" "
    az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Key Vault Accessible" "
    VAULT_NAME=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az keyvault show --name \"\${VAULT_NAME}\" --query id -o tsv >/dev/null
"

run_test "Key Vault Secrets Access" "
    VAULT_NAME=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az keyvault secret list --vault-name \"\${VAULT_NAME}\" --output tsv >/dev/null
"

# ==================================================
# Azure Monitor Tests
# ==================================================

echo -e "\n${BLUE}=== Azure Monitor ===${NC}"

run_test "Log Analytics Workspace Exists" "
    az monitor log-analytics workspace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Log Analytics Workspace Accessible" "
    WORKSPACE=\$(az monitor log-analytics workspace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az monitor log-analytics workspace show --workspace-name \"\${WORKSPACE}\" --query id -o tsv >/dev/null
"

# ==================================================
# Virtual Network Tests
# ==================================================

echo -e "\n${BLUE}=== Virtual Network ===${NC}"

run_test "Virtual Network Exists" "
    az network vnet list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Virtual Network Subnets Created" "
    VNET_NAME=\$(az network vnet list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    SUBNET_COUNT=\$(az network vnet subnet list --vnet-name \"\${VNET_NAME}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${SUBNET_COUNT}\" -ge 3 ]
"

run_test "Network Security Groups Created" "
    NSG_COUNT=\$(az network nsg list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    [ \"\${NSG_COUNT}\" -ge 1 ]
"

# ==================================================
# Storage Account Tests
# ==================================================

echo -e "\n${BLUE}=== Storage Account ===${NC}"

run_test "Storage Account Exists" "
    az storage account list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Storage Account Accessible" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az storage account show --name \"\${STORAGE_NAME}\" --query id -o tsv >/dev/null
"

run_test "Storage Account Blob Service Enabled" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az storage account blob-service-properties show --account-name \"\${STORAGE_NAME}\" --query id -o tsv >/dev/null
"

run_test "Storage Account Container Operations" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STORAGE_KEY=\$(az storage account keys list --account-name \"\${STORAGE_NAME}\" --query \"[0].value\" -o tsv)
    az storage container list --account-name \"\${STORAGE_NAME}\" --account-key \"\${STORAGE_KEY}\" --output tsv >/dev/null
"

# ==================================================
# Summary
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 0 Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"

TOTAL_TESTS=$((TESTS_PASSED + TESTS_FAILED))
PASS_RATE=$((TESTS_PASSED * 100 / TOTAL_TESTS))

echo -e "\nTotal Tests:    ${TOTAL_TESTS}"
echo -e "${GREEN}Passed:         ${TESTS_PASSED}${NC}"

if [ ${TESTS_FAILED} -gt 0 ]; then
    echo -e "${RED}Failed:         ${TESTS_FAILED}${NC}"
    echo -e "\nFailed Tests:"
    for test in "${FAILED_TESTS[@]}"; do
        echo -e "${RED}  - ${test}${NC}"
    done
else
    echo -e "Failed:         ${TESTS_FAILED}"
fi

echo -e "Pass Rate:      ${PASS_RATE}%"

if [ ${TESTS_FAILED} -eq 0 ]; then
    echo -e "\n${GREEN}✓ All Phase 0 tests PASSED${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some Phase 0 tests FAILED${NC}"
    exit 1
fi
