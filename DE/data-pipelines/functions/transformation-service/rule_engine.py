from typing import Any, Dict

from contracts import BureauHitStatus


def _safe_int(features: Dict[str, Any], key: str, default: int = 0) -> int:
    v = features.get(key, default)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _safe_float(features: Dict[str, Any], key: str, default: float = 0.0) -> float:
    v = features.get(key, default)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class HardStopEvaluator:
    def evaluate(self, features: Dict[str, Any]) -> Dict[str, Any]:
        if self._age_ineligible(features):
            return {"triggered": True, "code": "AGE_INELIGIBLE", "decision": "DECLINE"}
        if self._fraud_high(features):
            return {"triggered": True, "code": "FRAUD_HIGH", "decision": "FRAUD_HOLD"}
        if self._identity_fail(features):
            return {"triggered": True, "code": "KYC_FAIL", "decision": "DECLINE"}
        if self._judgement_present(features):
            return {"triggered": True, "code": "LEGAL_HOLD", "decision": "DECLINE"}
        if self._written_off_recent(features):
            return {"triggered": True, "code": "WRITE_OFF_HISTORY", "decision": "DECLINE"}
        if self._delinquency_critical(features):
            return {"triggered": True, "code": "DELINQUENCY_CRITICAL", "decision": "DECLINE"}
        if self._multiple_arrears(features):
            return {"triggered": True, "code": "MULTIPLE_ARREARS", "decision": "DECLINE"}
        return {"triggered": False, "code": None, "decision": None}

    def _age_ineligible(self, features: Dict[str, Any]) -> bool:
        raw_age = features.get("applicant_age_years")
        if raw_age is None:
            return False
        try:
            age = int(float(raw_age))
        except (TypeError, ValueError):
            return False
        return age < 18 or age > 75

    def _fraud_high(self, features: Dict[str, Any]) -> bool:
        # Reserved hook; no model-owned fraud signal in this deterministic v1.
        return False

    def _identity_fail(self, features: Dict[str, Any]) -> bool:
        if features.get("identity_verified") is None:
            return False
        return _safe_int(features, "identity_verified", 0) == 0

    def _judgement_present(self, features: Dict[str, Any]) -> bool:
        return _safe_int(features, "has_judgement", 0) == 1

    def _written_off_recent(self, features: Dict[str, Any]) -> bool:
        return _safe_int(features, "has_written_off", 0) == 1

    def _delinquency_critical(self, features: Dict[str, Any]) -> bool:
        return _safe_float(features, "highest_delinquency_rating", 0.0) >= 4

    def _multiple_arrears(self, features: Dict[str, Any]) -> bool:
        return _safe_int(features, "multiple_arrears_flag", 0) == 1


class DeterministicRuleEngine:
    def decide(
        self, features: Dict[str, Any], hard_stop: Dict[str, Any], hit_status: BureauHitStatus
    ) -> Dict[str, Any]:
        if hard_stop.get("triggered"):
            return {
                "hard_stop_triggered": True,
                "hard_stop_code": hard_stop.get("code"),
                "credit_score": 300,
                "score_grade": "F",
                "risk_tier": "VERY_HIGH",
                "decision": hard_stop.get("decision"),
                "decision_reason_codes": [hard_stop.get("code")],
                "condition_applied": None,
            }

        score = self._score(features)
        grade = self._grade(score)
        tier = self._risk_tier(score)
        decision = self._matrix_decision(grade, hit_status)
        condition = self._apply_conditions(decision, features)
        reason_codes = self._reason_codes(features, decision)

        return {
            "hard_stop_triggered": False,
            "hard_stop_code": None,
            "credit_score": score,
            "score_grade": grade,
            "risk_tier": tier,
            "decision": decision,
            "decision_reason_codes": reason_codes,
            "condition_applied": condition,
        }

    def _score(self, features: Dict[str, Any]) -> int:
        group_a = self._avg(
            features.get("highest_delinquency_rating", 0),
            features.get("months_on_time_24m", 0),
            features.get("worst_arrears_24m", 0),
            features.get("current_streak_on_time", 0),
            features.get("has_active_arrears", 0),
            features.get("total_arrear_amount_ghs", 0),
        )
        group_b = self._avg(
            features.get("total_outstanding_debt_ghs", 0),
            features.get("utilisation_ratio", 0),
            features.get("num_active_accounts", 0),
            features.get("total_monthly_instalment_ghs", 0),
        )
        group_c = self._avg(
            features.get("credit_age_months", 0),
            features.get("num_accounts_total", 0),
            features.get("num_closed_accounts_good", 0),
            features.get("product_diversity_score", 0),
            features.get("mobile_loan_history_count", 0),
        )
        group_d = self._group_d_score(features)
        group_e = self._avg(
            features.get("num_enquiries_3m", 0),
            features.get("num_enquiries_12m", 0),
        )
        group_f = self._avg(
            self._age_bin(features.get("applicant_age_years", 0)),
            features.get("identity_verified", 0),
            features.get("num_dependants", 0),
            features.get("has_employer_detail", 0),
            features.get("address_stability", 0),
        )

        weighted_ensemble = (
            0.35 * group_a
            + 0.25 * group_b
            + 0.15 * group_c
            + 0.15 * group_d
            + 0.05 * group_e
            + 0.05 * group_f
        )
        weighted_ensemble = min(max(weighted_ensemble, 0.0), 1.0)
        return int(round(300 + (550 * weighted_ensemble)))

    def _grade(self, credit_score: int) -> str:
        if credit_score >= 750:
            return "A"
        if credit_score >= 700:
            return "B"
        if credit_score >= 650:
            return "C"
        if credit_score >= 600:
            return "D"
        if credit_score >= 520:
            return "E"
        return "F"

    def _risk_tier(self, credit_score: int) -> str:
        if credit_score >= 750:
            return "VERY_LOW"
        if credit_score >= 700:
            return "LOW"
        if credit_score >= 600:
            return "MEDIUM"
        if credit_score >= 520:
            return "HIGH"
        return "VERY_HIGH"

    def _matrix_decision(self, grade: str, hit_status: BureauHitStatus) -> str:
        if hit_status == "NO_RECORD":
            return "REFER"
        if hit_status == "THIN_FILE":
            if grade in ("A", "B", "C", "D"):
                return "CONDITIONAL_APPROVE"
            if grade == "E":
                return "REFER"
            return "DECLINE"
        if grade in ("A", "B", "C"):
            return "APPROVE"
        if grade == "D":
            return "CONDITIONAL_APPROVE"
        if grade == "E":
            return "REFER"
        return "DECLINE"

    def _apply_conditions(self, decision: str, features: Dict[str, Any]) -> str | None:
        if decision != "CONDITIONAL_APPROVE":
            return None
        if _safe_float(features, "debt_service_ratio_est", 0.0) > 0.5:
            return "CA-01"
        if int(features.get("applicant_age_years", 0) or 0) > 65:
            return "CA-02"
        return "CA-05"

    def _reason_codes(self, features: Dict[str, Any], decision: str) -> list[str]:
        reasons = []
        if _safe_float(features, "highest_delinquency_rating", 1.0) < 0.5:
            reasons.append("R01")
        if _safe_float(features, "utilisation_ratio", 1.0) < 0.5:
            reasons.append("R02")
        if _safe_float(features, "feature_coverage_ratio", 1.0) < 0.6:
            reasons.append("R03")
        if _safe_float(features, "total_outstanding_debt_ghs", 1.0) < 0.35:
            reasons.append("R04")
        if _safe_float(features, "num_enquiries_3m", 1.0) <= 0.35:
            reasons.append("R05")
        if _safe_float(features, "has_active_arrears", 1.0) < 1.0:
            reasons.append("R06")
        if _safe_float(features, "debt_service_ratio_est", 0.0) > 0.5:
            reasons.append("R10")
        if not reasons and decision == "APPROVE":
            reasons.append("R09")
        return reasons[:5]

    def _group_d_score(self, features: Dict[str, Any]) -> float:
        score = 1.0
        if _safe_int(features, "has_charged_off", 0) == 1:
            score -= 120 / 550
        if _safe_int(features, "has_legal_handover", 0) == 1:
            score -= 80 / 550
        if _safe_int(features, "has_adverse_default", 0) == 1:
            score -= 100 / 550

        bounced = int(_safe_float(features, "num_bounced_cheques", 0.0))
        if bounced == 1:
            score -= 20 / 550
        elif bounced == 2:
            score -= 50 / 550
        elif bounced >= 3:
            score -= 100 / 550
        return min(max(score, 0.0), 1.0)

    def _age_bin(self, age_value: Any) -> float:
        try:
            age = int(float(age_value if age_value is not None else 0))
        except (TypeError, ValueError):
            return 0.0
        if age < 18 or age > 75:
            return 0.0
        if age <= 25:
            return 0.70
        if age <= 40:
            return 1.00
        if age <= 60:
            return 0.90
        return 0.65

    def _avg(self, *values: Any) -> float:
        nums = []
        for value in values:
            try:
                nums.append(float(value))
            except (TypeError, ValueError):
                nums.append(0.0)
        if not nums:
            return 0.0
        return min(max(sum(nums) / len(nums), 0.0), 1.0)

