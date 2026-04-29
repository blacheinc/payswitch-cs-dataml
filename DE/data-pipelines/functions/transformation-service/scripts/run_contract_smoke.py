"""
Manual smoke runner for deterministic transformation contract.

Usage:
  python scripts/run_contract_smoke.py
"""

import sys
from pathlib import Path

# Ensure parent transformation-service directory is importable when run as a script.
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from contracts import TransformRequest
from feature_engineering import DeterministicFeatureBuilder
from orchestrator import TransformationOrchestrator
from quality_provider import System04QualityAdapter
from rule_engine import DeterministicRuleEngine, HardStopEvaluator
from xds_parsers import Product45Parser, Product49Parser, XdsParser


def _orchestrator() -> TransformationOrchestrator:
    return TransformationOrchestrator(
        parser=XdsParser(Product45Parser(), Product49Parser()),
        feature_builder=DeterministicFeatureBuilder(),
        hard_stop_evaluator=HardStopEvaluator(),
        rule_engine=DeterministicRuleEngine(),
        quality_provider=System04QualityAdapter(),
    )


def _payload_hit() -> dict:
    return {
        "flow_type": "inference",
        "request_id": "smoke-hit-001",
        "data_source_id": "xds",
        "source_system": "xds",
        "xds_payload": {
            "consumer_full_report_45": {
                "response": {"statusCode": 200},
                "personalDetailsSummary": {"birthDate": "10/01/1996", "nationalIDNo": "GHA123"},
                "highestDelinquencyRating": {"highestDelinquencyRating": "0"},
                "creditAccountSummary": {
                    "totalOutstandingdebtGHS": "12000.00",
                    "totalMonthlyInstalmentGHS": "700.00",
                    "totalActiveAccountsGHS": "2",
                    "totalNumberofAccountsGHS": "4",
                    "totalClosedAccountsGHS": "2",
                    "totalAccountInArrearGHS": "0",
                    "totalAmountInArrearGHS": "0.00",
                },
                "creditAgreementSummary": [],
                "accountMonthlyPaymentHistory": [],
                "enquiryHistory": [],
                "judgementSummary": [],
                "defaults": [],
                "adverseDetails": [],
            }
        },
        "applicant_context": {
            "loan_amount_requested": 15000,
            "loan_tenure_months": 12,
            "monthly_income": 4000,
            "identity_reference": "hash-1",
        },
    }


def _payload_thin_file() -> dict:
    payload = _payload_hit()
    payload["request_id"] = "smoke-thin-001"
    payload["xds_payload"] = {
        "consumer_mobile_report_49": {
            "response": {"statusCode": 200},
            "detailedFacilityInfo": [{}, {}, {}, {}, {}],
            "creditAccountSummary": {
                "highestAmountTaken": "3000",
                "totalOutstandingdebt": "1200",
                "totalMonthlyInstalment": "250",
            },
        }
    }
    return payload


def _payload_no_record() -> dict:
    payload = _payload_hit()
    payload["request_id"] = "smoke-none-001"
    payload["xds_payload"] = {}
    return payload


def main() -> None:
    orch = _orchestrator()
    for factory in (_payload_hit, _payload_thin_file, _payload_no_record):
        req = TransformRequest.from_dict(factory())
        result = orch.run(req).to_dict()
        print(
            f"{result['request_id']}: "
            f"status={result['bureau_hit_status']}, "
            f"decision={result['decision_package']['decision']}, "
            f"features={len(result['features'])}, "
            f"targets={list(result.get('targets', {}).keys())}, "
            f"contract={result['contract_version']}"
        )


if __name__ == "__main__":
    main()

