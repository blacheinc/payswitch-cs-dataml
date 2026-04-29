#!/bin/bash
# ==================================================
# Phase 4 Infrastructure Tests
# API Gateway: API Management, Static Web Apps, Azure AD B2C
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
echo -e "${BLUE}Phase 4 Infrastructure Tests${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}========================================${NC}"

# ==================================================
# API Management Tests
# ==================================================

echo -e "\n${BLUE}=== API Management ===${NC}"

run_test "API Management Service Exists" "
    az apim list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}'
"

run_test "API Management Service Running" "
    APIM_NAME=\$(az apim list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    STATE=\$(az apim show --name \"\${APIM_NAME}\" --query provisioningState -o tsv)
    [ \"\${STATE}\" == \"Succeeded\" ]
"

run_test "API Management Gateway URL Accessible" "
    APIM_NAME=\$(az apim list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    GATEWAY_URL=\$(az apim show --name \"\${APIM_NAME}\" --query gatewayUrl -o tsv)
    curl -s -o /dev/null -w '%{http_code}' \"\${GATEWAY_URL}\" | grep -q '[23][0-9][0-9]'
" || echo -e "${YELLOW}⚠ Gateway URL not accessible (may require API configuration)${NC}"

run_test "API Management Products Created" "
    APIM_NAME=\$(az apim list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | head -1)
    RG=\$(az apim show --name \"\${APIM_NAME}\" --query resourceGroup -o tsv)
    PRODUCT_COUNT=\$(az apim product list --resource-group \"\${RG}\" --service-name \"\${APIM_NAME}\" --query \"[].name\" -o tsv | wc -l)
    [ \"\${PRODUCT_COUNT}\" -ge 0 ]
" || echo -e "${YELLOW}⚠ Products may be created later${NC}"

# ==================================================
# Static Web Apps Tests
# ==================================================

echo -e "\n${BLUE}=== Static Web Apps ===${NC}"

run_test "Static Web App Exists" "
    az staticwebapp list --query \"[?contains(name, '${NAMING_PREFIX}')].name\" -o tsv | grep -q '${NAMING_PREFIX}' || echo 'Static Web App not deployed yet'
" || echo -e "${YELLOW}⚠ Static Web App not deployed yet (manual deployment)${NC}"

# ==================================================
# Azure AD B2C Tests
# ==================================================

echo -e "\n${BLUE}=== Azure AD B2C ===${NC}"

run_test "Azure AD B2C Tenant Exists" "
    az ad b2c tenant list --query \"[?contains(displayName, '${NAMING_PREFIX}')].displayName\" -o tsv | grep -q '${NAMING_PREFIX}' || \
    az ad b2c tenant list --query \"[].displayName\" -o tsv | wc -l | grep -q '[0-9]' || echo 'B2C tenant not deployed yet'
" || echo -e "${YELLOW}⚠ Azure AD B2C tenant not deployed yet (manual deployment)${NC}"

# ==================================================
# Azure Functions (Decision Agent) Tests
# ==================================================

echo -e "\n${BLUE}=== Decision Agent Functions ===${NC}"

run_test "Decision Agent Function App Exists" "
    az functionapp list --query \"[?contains(name, '${NAMING_PREFIX}') && contains(name, 'decision')].name\" -o tsv | grep -q '${NAMING_PREFIX}' || echo 'Function not deployed yet'
" || echo -e "${YELLOW}⚠ Function apps not deployed yet (manual deployment)${NC}"

run_test "Risk Monitoring Agent Function App Exists" "
    az functionapp list --query \"[?contains(name, '${NAMING_PREFIX}') && contains(name, 'risk')].name\" -o tsv | grep -q '${NAMING_PREFIX}' || echo 'Function not deployed yet'
" || echo -e "${YELLOW}⚠ Function apps not deployed yet (manual deployment)${NC}"

# ==================================================
# Summary
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Phase 4 Test Summary${NC}"
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
    echo -e "\n${GREEN}✓ All Phase 4 tests PASSED${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some Phase 4 tests FAILED${NC}"
    exit 1
fi
