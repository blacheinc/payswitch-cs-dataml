#!/bin/bash
# ==================================================
# Deploy → Test → Teardown Workflow
# Automated testing workflow for infrastructure validation
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
PHASE="${2:-0}"
NAMING_PREFIX="${3:-blache-${ENVIRONMENT}}"
TEARDOWN="${4:-yes}"

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
INFRA_DIR="$( cd "${SCRIPT_DIR}/../.." && pwd )"
DEPLOY_SCRIPT="${INFRA_DIR}/scripts/deploy.sh"
DESTROY_SCRIPT="${INFRA_DIR}/scripts/destroy.sh"
TEST_SCRIPT="${SCRIPT_DIR}/test-phase-${PHASE}.sh"

# Phase names
declare -A PHASE_NAMES=(
    [0]="Core Infrastructure"
    [1]="Data Layer"
    [2]="Data Ingestion"
    [3]="ML Foundation"
    [4]="API Gateway"
    [5]="Full System"
)

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Deploy → Test → Teardown Workflow${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Phase: ${PHASE} - ${PHASE_NAMES[$PHASE]}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}Teardown: ${TEARDOWN}${NC}"
echo -e "${BLUE}========================================${NC}"

# ==================================================
# Step 1: Deploy Infrastructure
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Step 1: Deploying Infrastructure${NC}"
echo -e "${BLUE}========================================${NC}"

if [ ! -f "${DEPLOY_SCRIPT}" ]; then
    echo -e "${RED}✗ Deploy script not found: ${DEPLOY_SCRIPT}${NC}"
    exit 1
fi

echo -e "${YELLOW}Running deployment script...${NC}"

# Note: deploy.sh expects to be run from its directory
cd "$(dirname "${DEPLOY_SCRIPT}")"

if bash "${DEPLOY_SCRIPT}" "${ENVIRONMENT}"; then
    echo -e "${GREEN}✓ Deployment completed successfully${NC}"
else
    echo -e "${RED}✗ Deployment failed${NC}"
    exit 1
fi

# Wait for resources to be ready
echo -e "\n${YELLOW}Waiting 30 seconds for resources to stabilize...${NC}"
sleep 30

# ==================================================
# Step 2: Run Tests
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Step 2: Running Tests${NC}"
echo -e "${BLUE}========================================${NC}"

if [ ! -f "${TEST_SCRIPT}" ]; then
    echo -e "${RED}✗ Test script not found: ${TEST_SCRIPT}${NC}"
    echo -e "${YELLOW}⚠ Skipping tests, proceeding to teardown...${NC}"
    TEST_RESULT=1
else
    if bash "${TEST_SCRIPT}" "${ENVIRONMENT}" "${NAMING_PREFIX}"; then
        echo -e "${GREEN}✓ All tests PASSED${NC}"
        TEST_RESULT=0
    else
        echo -e "${RED}✗ Some tests FAILED${NC}"
        TEST_RESULT=1
    fi
fi

# ==================================================
# Step 3: Teardown (if requested)
# ==================================================

if [ "${TEARDOWN}" == "yes" ]; then
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}Step 3: Teardown${NC}"
    echo -e "${BLUE}========================================${NC}"
    
    if [ ! -f "${DESTROY_SCRIPT}" ]; then
        echo -e "${RED}✗ Destroy script not found: ${DESTROY_SCRIPT}${NC}"
        exit 1
    fi
    
    echo -e "${YELLOW}This will DELETE all resources in resource groups matching: ${NAMING_PREFIX}${NC}"
    echo -e "${YELLOW}Press Ctrl+C within 10 seconds to cancel...${NC}"
    sleep 10
    
    cd "$(dirname "${DESTROY_SCRIPT}")"
    
    if bash "${DESTROY_SCRIPT}" "${ENVIRONMENT}"; then
        echo -e "${GREEN}✓ Teardown completed successfully${NC}"
    else
        echo -e "${RED}✗ Teardown failed${NC}"
        exit 1
    fi
else
    echo -e "\n${YELLOW}⚠ Teardown skipped (TEARDOWN=no)${NC}"
    echo -e "${YELLOW}Resources remain deployed for manual inspection${NC}"
fi

# ==================================================
# Final Summary
# ==================================================

echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Workflow Summary${NC}"
echo -e "${BLUE}========================================${NC}"

echo -e "\nDeployment:     ${GREEN}✓ Completed${NC}"

if [ ${TEST_RESULT} -eq 0 ]; then
    echo -e "Tests:          ${GREEN}✓ All PASSED${NC}"
else
    echo -e "Tests:          ${RED}✗ Some FAILED${NC}"
fi

if [ "${TEARDOWN}" == "yes" ]; then
    echo -e "Teardown:       ${GREEN}✓ Completed${NC}"
else
    echo -e "Teardown:       ${YELLOW}⚠ Skipped${NC}"
fi

if [ ${TEST_RESULT} -eq 0 ]; then
    echo -e "\n${GREEN}✓ Workflow completed successfully${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Workflow completed with test failures${NC}"
    exit 1
fi
