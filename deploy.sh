#!/usr/bin/env bash
#
# Deploy PaySwitch Credit Scoring Function Apps to Azure.
#
# Copies shared/ into each app directory before deploying (Azure Functions
# deploys each app in isolation — sibling directories aren't available).
# Cleans up after deployment, whether it succeeds or fails.
#
# Prerequisites:
#   - Azure Functions Core Tools v4 (func --version)
#   - Azure CLI logged in (az login)
#   - Git Bash or WSL on Windows
#
# Usage:
#   ./deploy.sh orchestrator
#   ./deploy.sh credit-risk
#   ./deploy.sh all
#   ./deploy.sh local orchestrator    # local func start (copies shared/, runs, cleans up)
#
set -euo pipefail

# ── Azure Function App Names (edit to match your resources) ──────────────────

ORCHESTRATOR_APP="payswitch-cs-orchestrator"
CREDIT_RISK_APP="payswitch-cs-credit-risk"
FRAUD_DETECTION_APP="payswitch-cs-fraud-detection"
LOAN_AMOUNT_APP="payswitch-cs-loan-amount"
INCOME_VERIFICATION_APP="payswitch-cs-income-verification"

# ── App directory mapping ────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

declare -A APP_DIRS=(
    [orchestrator]="orchestrator"
    [credit-risk]="training-agents/credit-risk-agent"
    [fraud-detection]="training-agents/fraud-detection-agent"
    [loan-amount]="training-agents/loan-amount-agent"
    [income-verification]="training-agents/income-verification-agent"
)

declare -A APP_NAMES=(
    [orchestrator]="$ORCHESTRATOR_APP"
    [credit-risk]="$CREDIT_RISK_APP"
    [fraud-detection]="$FRAUD_DETECTION_APP"
    [loan-amount]="$LOAN_AMOUNT_APP"
    [income-verification]="$INCOME_VERIFICATION_APP"
)

ALL_APPS=(orchestrator credit-risk fraud-detection loan-amount income-verification)

# Default ports for local dev (each app needs a unique port)
declare -A APP_PORTS=(
    [orchestrator]="7071"
    [credit-risk]="7072"
    [fraud-detection]="7073"
    [loan-amount]="7074"
    [income-verification]="7075"
)

# ── Deploy function ──────────────────────────────────────────────────────────

deploy_one() {
    local app_key="$1"
    local app_dir="${SCRIPT_DIR}/${APP_DIRS[$app_key]}"
    local app_name="${APP_NAMES[$app_key]}"
    local shared_dest="${app_dir}/shared"

    echo ""
    echo "════════════════════════════════════════════════════════════"
    echo "  Deploying: ${app_key} → ${app_name}"
    echo "  Directory: ${APP_DIRS[$app_key]}"
    echo "════════════════════════════════════════════════════════════"

    # Verify app directory exists
    if [ ! -d "$app_dir" ]; then
        echo "  ERROR: Directory not found: $app_dir"
        return 1
    fi

    # Copy shared/ into app directory
    echo "  [1/3] Copying shared/ → ${APP_DIRS[$app_key]}/shared/"
    cp -r "${SCRIPT_DIR}/shared" "$shared_dest"

    # Deploy (always clean up after, even on failure)
    local deploy_exit=0
    echo "  [2/3] Running: func azure functionapp publish ${app_name} --python"
    (cd "$app_dir" && func azure functionapp publish "$app_name" --python) || deploy_exit=$?

    # Clean up
    echo "  [3/3] Cleaning up ${APP_DIRS[$app_key]}/shared/"
    rm -rf "$shared_dest"

    if [ $deploy_exit -ne 0 ]; then
        echo "  FAILED: ${app_key} deployment failed (exit code ${deploy_exit})"
        return 1
    fi

    echo "  SUCCESS: ${app_key} deployed to ${app_name}"
}

# ── Local dev function ─────────────────────────────────────────────────────

local_start() {
    local app_key="$1"
    local app_dir="${SCRIPT_DIR}/${APP_DIRS[$app_key]}"
    local shared_dest="${app_dir}/shared"
    local port="${APP_PORTS[$app_key]}"

    if [ ! -d "$app_dir" ]; then
        echo "ERROR: Directory not found: $app_dir"
        return 1
    fi

    # Copy shared/ into app directory
    echo "Copying shared/ → ${APP_DIRS[$app_key]}/shared/"
    cp -r "${SCRIPT_DIR}/shared" "$shared_dest"

    # Run func start (clean up on exit, regardless of how it stops)
    trap "echo ''; echo 'Cleaning up ${APP_DIRS[$app_key]}/shared/'; rm -rf '$shared_dest'" EXIT INT TERM

    echo "Starting: func start --port ${port} in ${APP_DIRS[$app_key]}/"
    echo ""
    (cd "$app_dir" && func start --port "$port")
}

# ── Main ─────────────────────────────────────────────────────────────────────

usage() {
    echo "Usage: ./deploy.sh <app|all|local>"
    echo ""
    echo "Deploy:"
    echo "  orchestrator          Deploy orchestrator Function App"
    echo "  credit-risk           Deploy credit risk agent"
    echo "  fraud-detection       Deploy fraud detection agent"
    echo "  loan-amount           Deploy loan amount agent"
    echo "  income-verification   Deploy income verification agent"
    echo "  all                   Deploy all 5 Function Apps"
    echo ""
    echo "Local dev:"
    echo "  local <app>           Copy shared/, run func start, clean up on exit"
    echo "                        e.g. ./deploy.sh local orchestrator"
}

if [ $# -eq 0 ]; then
    usage
    exit 1
fi

case "$1" in
    local)
        if [ -z "${2:-}" ]; then
            echo "ERROR: Specify which app to run locally."
            echo "Usage: ./deploy.sh local <app>"
            exit 1
        fi
        if [ -z "${APP_DIRS[$2]+x}" ]; then
            echo "ERROR: Unknown app '$2'"
            exit 1
        fi
        local_start "$2"
        ;;
    orchestrator|credit-risk|fraud-detection|loan-amount|income-verification)
        deploy_one "$1"
        ;;
    all)
        failed=()
        for app in "${ALL_APPS[@]}"; do
            deploy_one "$app" || failed+=("$app")
        done
        echo ""
        echo "════════════════════════════════════════════════════════════"
        if [ ${#failed[@]} -eq 0 ]; then
            echo "  ALL DEPLOYMENTS SUCCEEDED"
        else
            echo "  FAILED: ${failed[*]}"
            exit 1
        fi
        echo "════════════════════════════════════════════════════════════"
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "ERROR: Unknown app '$1'"
        echo ""
        usage
        exit 1
        ;;
esac
