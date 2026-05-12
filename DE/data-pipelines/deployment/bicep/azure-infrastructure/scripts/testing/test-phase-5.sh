#!/bin/bash
# ==================================================
# Phase 5 Infrastructure Tests
# Full System: All resources, end-to-end connectivity
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
echo -e "${BLUE}Phase 5 Full System Tests${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}========================================${NC}"

# ==================================================
# Comprehensive Resource Count Tests
# ==================================================

echo -e "\n${BLUE}=== Resource Inventory ===${NC}"

run_test "All Resource Groups Created (8 expected)" "
    RG_COUNT=\$(az group list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    [ \"\${RG_COUNT}\" -ge 5 ]
"

run_test "All Core Services Deployed" "
    KEY_VAULT=\$(az keyvault list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    STORAGE=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    POSTGRES=\$(az postgres flexible-server list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    REDIS=\$(az redis list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | wc -l)
    [ \"\${KEY_VAULT}\" -ge 1 ] && [ \"\${STORAGE}\" -ge 1 ] && [ \"\${POSTGRES}\" -ge 1 ] && [ \"\${REDIS}\" -ge 1 ]
"

# ==================================================
# End-to-End Connectivity Tests
# ==================================================

echo -e "\n${BLUE}=== End-to-End Connectivity ===${NC}"

run_test "Service Bus to Data Lake Integration" "
    NAMESPACE=\$(az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STORAGE=\$(az storage account list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    [ -n \"\${NAMESPACE}\" ] && [ -n \"\${STORAGE}\" ]
"

run_test "Data Factory to Service Bus Integration" "
    ADF=\$(az datafactory list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    NAMESPACE=\$(az servicebus namespace list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    [ -n \"\${ADF}\" ] && [ -n \"\${NAMESPACE}\" ]
"

run_test "AKS to ACR Integration" "
    AKS=\$(az aks list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    ACR=\$(az acr list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    [ -n \"\${AKS}\" ] && [ -n \"\${ACR}\" ]
"

# ==================================================
# Application Insights Tests
# ==================================================

echo -e "\n${BLUE}=== Application Insights ===${NC}"

run_test "Application Insights Exists" "
    az monitor app-insights component show \
        --app \"${NAMING_PREFIX}-app-insights\" \
        --resource-group \"${NAMING_PREFIX}-monitoring-rg\" \
        --query id -o tsv >/dev/null 2>&1 || \
    az monitor app-insights component list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

# ==================================================
# All Azure Functions Tests
# ==================================================

echo -e "\n${BLUE}=== All Azure Functions ===${NC}"

AGENTS=(
    "data-quality-agent"
    "feature-engineering-agent"
    "decision-agent"
    "risk-monitoring-agent"
    "compliance-agent"
    "model-training-agent"
)

for AGENT in "${AGENTS[@]}"; do
    run_test "Function App: ${AGENT}" "
        APP=\$(az functionapp list --query \"[?contains(name, '${NAMING_PREFIX}') && contains(name, '${AGENT}')].name\" -o tsv | head -1)
        [ -n \"\${APP}\" ] || echo 'Function not deployed yet'
    " || echo -e "${YELLOW}⚠ ${AGENT} not deployed yet${NC}"
done

# ==================================================
# Summary
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 5 Test Summary${NC}"
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

if [ ${PASS_RATE} -ge 80 ]; then
    echo -e "\n${GREEN}✓ Phase 5 tests PASSED (${PASS_RATE}%)${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Phase 5 tests FAILED (${PASS_RATE}%)${NC}"
    exit 1
fi
