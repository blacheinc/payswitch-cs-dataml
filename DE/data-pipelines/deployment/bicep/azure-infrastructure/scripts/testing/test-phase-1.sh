#!/bin/bash
# ==================================================
# Phase 1 Infrastructure Tests
# Data Layer: PostgreSQL, Redis, Data Lake Gen2
# ==================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration — pass naming-prefix as second arg, or set NAMING_PREFIX / ORG_NAME+PROJECT_NAME
ENVIRONMENT="${1:-}"
if [ -z "${ENVIRONMENT}" ]; then
  echo "Usage: $0 <dev|staging|prod> [naming-prefix]"
  exit 1
fi
if [ -n "${2:-}" ]; then
  NAMING_PREFIX="${2}"
elif [ -n "${NAMING_PREFIX:-}" ]; then
  :
elif [ -n "${ORG_NAME:-}" ] && [ -n "${PROJECT_NAME:-}" ]; then
  NAMING_PREFIX="${ORG_NAME}-${PROJECT_NAME}-${ENVIRONMENT}"
else
  echo "Provide naming-prefix as second argument, or set NAMING_PREFIX, or set ORG_NAME and PROJECT_NAME."
  exit 1
fi
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
echo -e "${BLUE}Phase 1 Infrastructure Tests${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}========================================${NC}"

# ==================================================
# PostgreSQL Tests
# ==================================================

echo -e "\n${BLUE}=== PostgreSQL ===${NC}"

run_test "PostgreSQL Server Exists" "
    az postgres flexible-server list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "PostgreSQL Server Running" "
    SERVER_NAME=\$(az postgres flexible-server list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STATE=\$(az postgres flexible-server show --name \"\${SERVER_NAME}\" --query state -o tsv)
    [ \"\${STATE}\" == \"Ready\" ] || [ \"\${STATE}\" == \"Stopped\" ]
"

run_test "PostgreSQL Databases Created" "
    SERVER_NAME=\$(az postgres flexible-server list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    DB_COUNT=\$(az postgres flexible-server db list --resource-group \$(az postgres flexible-server show --name \"\${SERVER_NAME}\" --query resourceGroup -o tsv) --server-name \"\${SERVER_NAME}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${DB_COUNT}\" -ge 1 ]
"

# Note: Actual connection test requires credentials from Key Vault
run_test "PostgreSQL Connection String Available" "
    VAULT_NAME=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"postgres-connection-string\" --query value -o tsv >/dev/null 2>&1 || \
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"PostgresConnectionString\" --query value -o tsv >/dev/null 2>&1
" || echo -e "${YELLOW}⚠ Connection string not in Key Vault (may be set later)${NC}"

# ==================================================
# Redis Tests
# ==================================================

echo -e "\n${BLUE}=== Redis Cache ===${NC}"

run_test "Redis Cache Exists" "
    az redis list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Redis Cache Running" "
    REDIS_NAME=\$(az redis list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STATE=\$(az redis show --name \"\${REDIS_NAME}\" --query provisioningState -o tsv)
    [ \"\${STATE}\" == \"Succeeded\" ]
"

run_test "Redis Connection String Available" "
    VAULT_NAME=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"redis-connection-string\" --query value -o tsv >/dev/null 2>&1 || \
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"RedisConnectionString\" --query value -o tsv >/dev/null 2>&1
" || echo -e "${YELLOW}⚠ Connection string not in Key Vault (may be set later)${NC}"

# ==================================================
# Data Lake Gen2 Tests
# ==================================================

echo -e "\n${BLUE}=== Data Lake Gen2 ===${NC}"

run_test "Data Lake Storage Account Exists" "
    az storage account list --query \"[?contains(name, '${NAMING_PREFIX}') && properties.isHnsEnabled == \`true\`].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Data Lake Hierarchical Namespace Enabled" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}') && properties.isHnsEnabled == \`true\`].name\" -o tsv | head -1)
    IS_HNS=\$(az storage account show --name \"\${STORAGE_NAME}\" --query \"properties.isHnsEnabled\" -o tsv)
    [ \"\${IS_HNS}\" == \"true\" ]
"

run_test "Data Lake File Systems Created" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}') && properties.isHnsEnabled == \`true\`].name\" -o tsv | head -1)
    STORAGE_KEY=\$(az storage account keys list --account-name \"\${STORAGE_NAME}\" --query \"[0].value\" -o tsv)
    FS_COUNT=\$(az storage fs list --account-name \"\${STORAGE_NAME}\" --account-key \"\${STORAGE_KEY}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${FS_COUNT}\" -ge 1 ]
"

run_test "Data Lake Raw Container Exists" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}') && properties.isHnsEnabled == \`true\`].name\" -o tsv | head -1)
    STORAGE_KEY=\$(az storage account keys list --account-name \"\${STORAGE_NAME}\" --query \"[0].value\" -o tsv)
    az storage fs show --name \"raw\" --account-name \"\${STORAGE_NAME}\" --account-key \"\${STORAGE_KEY}\" --query name -o tsv >/dev/null
"

run_test "Data Lake Folder Structure Created" "
    STORAGE_NAME=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}') && properties.isHnsEnabled == \`true\`].name\" -o tsv | head -1)
    STORAGE_KEY=\$(az storage account keys list --account-name \"\${STORAGE_NAME}\" --query \"[0].value\" -o tsv)
    az storage fs directory exists --name \"raw/credit-bureau\" --file-system \"raw\" --account-name \"\${STORAGE_NAME}\" --account-key \"\${STORAGE_KEY}\" --query exists -o tsv >/dev/null 2>&1 || \
    az storage fs directory exists --name \"raw/banking\" --file-system \"raw\" --account-name \"\${STORAGE_NAME}\" --account-key \"\${STORAGE_KEY}\" --query exists -o tsv >/dev/null 2>&1 || \
    az storage fs directory exists --name \"raw/telco\" --file-system \"raw\" --account-name \"\${STORAGE_NAME}\" --account-key \"\${STORAGE_KEY}\" --query exists -o tsv >/dev/null 2>&1
" || echo -e "${YELLOW}⚠ Folder structure not created yet (may be created by ADF)${NC}"

# ==================================================
# Summary
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 1 Test Summary${NC}"
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
    echo -e "\n${GREEN}✓ All Phase 1 tests PASSED${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some Phase 1 tests FAILED${NC}"
    exit 1
fi
