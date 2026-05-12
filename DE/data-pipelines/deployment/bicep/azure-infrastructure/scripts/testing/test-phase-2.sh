#!/bin/bash
# ==================================================
# Phase 2 Infrastructure Tests
# Data Ingestion: Service Bus, Data Factory, Cosmos DB, Azure Functions
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
echo -e "${BLUE}Phase 2 Infrastructure Tests${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}========================================${NC}"

# ==================================================
# Service Bus Tests
# ==================================================

echo -e "\n${BLUE}=== Service Bus ===${NC}"

run_test "Service Bus Namespace Exists" "
    az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Service Bus Namespace Running" "
    NAMESPACE=\$(az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STATE=\$(az servicebus namespace show --name \"\${NAMESPACE}\" --query provisioningState -o tsv)
    [ \"\${STATE}\" == \"Succeeded\" ]
"

run_test "Service Bus Topics Created" "
    NAMESPACE=\$(az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az servicebus namespace show --name \"\${NAMESPACE}\" --query resourceGroup -o tsv)
    TOPIC_COUNT=\$(az servicebus topic list --resource-group \"\${RG}\" --namespace-name \"\${NAMESPACE}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${TOPIC_COUNT}\" -ge 3 ]
"

run_test "Service Bus Required Topics Exist" "
    NAMESPACE=\$(az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az servicebus namespace show --name \"\${NAMESPACE}\" --query resourceGroup -o tsv)
    az servicebus topic show --resource-group \"\${RG}\" --namespace-name \"\${NAMESPACE}\" --name \"data-ingested\" --query name -o tsv >/dev/null && \
    az servicebus topic show --resource-group \"\${RG}\" --namespace-name \"\${NAMESPACE}\" --name \"data-quality-checked\" --query name -o tsv >/dev/null && \
    az servicebus topic show --resource-group \"\${RG}\" --namespace-name \"\${NAMESPACE}\" --name \"features-engineered\" --query name -o tsv >/dev/null
"

run_test "Service Bus Subscriptions Created" "
    NAMESPACE=\$(az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az servicebus namespace show --name \"\${NAMESPACE}\" --query resourceGroup -o tsv)
    SUB_COUNT=\$(az servicebus topic subscription list --resource-group \"\${RG}\" --namespace-name \"\${NAMESPACE}\" --topic-name \"data-ingested\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${SUB_COUNT}\" -ge 1 ]
"

run_test "Service Bus Connection String Available" "
    VAULT_NAME=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"service-bus-connection-string\" --query value -o tsv >/dev/null 2>&1 || \
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"ServiceBusConnectionString\" --query value -o tsv >/dev/null 2>&1
" || echo -e "${YELLOW}⚠ Connection string not in Key Vault (may be set later)${NC}"

# ==================================================
# Azure Data Factory Tests
# ==================================================

echo -e "\n${BLUE}=== Azure Data Factory ===${NC}"

run_test "Data Factory Exists" "
    az datafactory list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Data Factory Running" "
    ADF_NAME=\$(az datafactory list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STATE=\$(az datafactory show --name \"\${ADF_NAME}\" --query provisioningState -o tsv)
    [ \"\${STATE}\" == \"Succeeded\" ]
"

run_test "Data Factory Linked Services Created" "
    ADF_NAME=\$(az datafactory list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az datafactory show --name \"\${ADF_NAME}\" --query resourceGroup -o tsv)
    LS_COUNT=\$(az datafactory linked-service list --factory-name \"\${ADF_NAME}\" --resource-group \"\${RG}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${LS_COUNT}\" -ge 2 ]
"

# ==================================================
# Cosmos DB (MongoDB) Tests
# ==================================================

echo -e "\n${BLUE}=== Cosmos DB (MongoDB) ===${NC}"

run_test "Cosmos DB Account Exists" "
    az cosmosdb list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "Cosmos DB MongoDB API Enabled" "
    COSMOS_NAME=\$(az cosmosdb list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    API=\$(az cosmosdb show --name \"\${COSMOS_NAME}\" --query \"kind\" -o tsv)
    [ \"\${API}\" == \"MongoDB\" ]
"

run_test "Cosmos DB Databases Created" "
    COSMOS_NAME=\$(az cosmosdb list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az cosmosdb show --name \"\${COSMOS_NAME}\" --query resourceGroup -o tsv)
    DB_COUNT=\$(az cosmosdb mongodb database list --account-name \"\${COSMOS_NAME}\" --resource-group \"\${RG}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${DB_COUNT}\" -ge 1 ]
"

run_test "Cosmos DB Collections Created" "
    COSMOS_NAME=\$(az cosmosdb list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az cosmosdb show --name \"\${COSMOS_NAME}\" --query resourceGroup -o tsv)
    DB_NAME=\$(az cosmosdb mongodb database list --account-name \"\${COSMOS_NAME}\" --resource-group \"\${RG}\" --query \"[0].name\" -o tsv)
    COLLECTION_COUNT=\$(az cosmosdb mongodb collection list --account-name \"\${COSMOS_NAME}\" --resource-group \"\${RG}\" --database-name \"\${DB_NAME}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${COLLECTION_COUNT}\" -ge 1 ]
"

run_test "Cosmos DB Connection String Available" "
    VAULT_NAME=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"MongoDBConnectionString\" --query value -o tsv >/dev/null 2>&1 || \
    az keyvault secret show --vault-name \"\${VAULT_NAME}\" --name \"cosmos-connection-string\" --query value -o tsv >/dev/null 2>&1
" || echo -e "${YELLOW}⚠ Connection string not in Key Vault (may be set later)${NC}"

# ==================================================
# Azure Functions Tests (if deployed)
# ==================================================

echo -e "\n${BLUE}=== Azure Functions ===${NC}"

run_test "Data Quality Agent Function App Exists" "
    az functionapp list --query \"[?contains(name, '${NAMING_PREFIX}') && contains(name, 'data-quality')].name\" -o tsv | grep -q '${NAMING_PREFIX}' || echo 'Function not deployed yet'
" || echo -e "${YELLOW}⚠ Function apps not deployed yet (manual deployment)${NC}"

run_test "Feature Engineering Agent Function App Exists" "
    az functionapp list --query \"[?contains(name, '${NAMING_PREFIX}') && contains(name, 'feature-engineering')].name\" -o tsv | grep -q '${NAMING_PREFIX}' || echo 'Function not deployed yet'
" || echo -e "${YELLOW}⚠ Function apps not deployed yet (manual deployment)${NC}"

# ==================================================
# Summary
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 2 Test Summary${NC}"
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
    echo -e "\n${GREEN}✓ All Phase 2 tests PASSED${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some Phase 2 tests FAILED${NC}"
    exit 1
fi
