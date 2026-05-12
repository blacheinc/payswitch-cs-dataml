#!/bin/bash
# ==================================================
# Master Test Orchestrator
# Runs all phase tests in sequence
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
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

PHASES_PASSED=0
PHASES_FAILED=0
FAILED_PHASES=()

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Master Test Orchestrator${NC}"
echo -e "${BLUE}Environment: ${ENVIRONMENT}${NC}"
echo -e "${BLUE}Naming Prefix: ${NAMING_PREFIX}${NC}"
echo -e "${BLUE}========================================${NC}"

# Function to run phase test
run_phase_test() {
    local phase=$1
    local phase_name=$2
    
    echo -e "\n${BLUE}========================================${NC}"
    echo -e "${BLUE}Running Phase ${phase} Tests: ${phase_name}${NC}"
    echo -e "${BLUE}========================================${NC}"
    
    if bash "${SCRIPT_DIR}/test-phase-${phase}.sh" "${ENVIRONMENT}" "${NAMING_PREFIX}"; then
        echo -e "\n${GREEN}✓ Phase ${phase} tests PASSED${NC}"
        ((PHASES_PASSED++))
        return 0
    else
        echo -e "\n${RED}✗ Phase ${phase} tests FAILED${NC}"
        ((PHASES_FAILED++))
        FAILED_PHASES+=("Phase ${phase}: ${phase_name}")
        return 1
    fi
}

# Run all phase tests
run_phase_test 0 "Core Infrastructure"
run_phase_test 1 "Data Layer"
run_phase_test 2 "Data Ingestion"
run_phase_test 3 "ML Foundation"
run_phase_test 4 "API Gateway"
run_phase_test 5 "Full System"

# Summary
echo -e "\n${BLUE}========================================${NC}"
echo -e "${BLUE}Master Test Summary${NC}"
echo -e "${BLUE}========================================${NC}"

TOTAL_PHASES=$((PHASES_PASSED + PHASES_FAILED))

echo -e "\nTotal Phases:   ${TOTAL_PHASES}"
echo -e "${GREEN}Passed:         ${PHASES_PASSED}${NC}"

if [ ${PHASES_FAILED} -gt 0 ]; then
    echo -e "${RED}Failed:         ${PHASES_FAILED}${NC}"
    echo -e "\nFailed Phases:"
    for phase in "${FAILED_PHASES[@]}"; do
        echo -e "${RED}  - ${phase}${NC}"
    done
else
    echo -e "Failed:         ${PHASES_FAILED}"
fi

PASS_RATE=$((PHASES_PASSED * 100 / TOTAL_PHASES))
echo -e "Pass Rate:      ${PASS_RATE}%"

if [ ${PHASES_FAILED} -eq 0 ]; then
    echo -e "\n${GREEN}✓ All phase tests PASSED${NC}"
    exit 0
else
    echo -e "\n${RED}✗ Some phase tests FAILED${NC}"
    exit 1
fi
