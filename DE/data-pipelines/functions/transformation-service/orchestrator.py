"""Compose parser, features, hard stops, rules, and quality into a single TransformResponse."""

from contracts import TransformDiagnostics, TransformRequest, TransformResponse
from interfaces import IFeatureBuilder, IHardStopEvaluator, IQualityScoreProvider, IRuleEngine, IXdsParser


class TransformationOrchestrator:
    """Run the full deterministic pipeline for one ``TransformRequest``."""

    def __init__(
        self,
        parser: IXdsParser,
        feature_builder: IFeatureBuilder,
        hard_stop_evaluator: IHardStopEvaluator,
        rule_engine: IRuleEngine,
        quality_provider: IQualityScoreProvider,
        transform_version: str = "v1",
        rule_version: str = "v1",
    ) -> None:
        self.parser = parser
        self.feature_builder = feature_builder
        self.hard_stop_evaluator = hard_stop_evaluator
        self.rule_engine = rule_engine
        self.quality_provider = quality_provider
        self.transform_version = transform_version
        self.rule_version = rule_version

    @staticmethod
    def _has_employer_detail(extracted: dict) -> bool:
        p45 = extracted.get("product45") or {}
        if p45:
            return bool(p45.get("has_employer_detail", 0))
        thin = extracted.get("thin_file_personal") or {}
        return bool(thin.get("has_employer_detail", 0))

    @staticmethod
    def _product_mix(diagnostics_dict: dict) -> str:
        f45 = diagnostics_dict.get("product45_available_flag", 0)
        f49 = diagnostics_dict.get("product49_available_flag", 0)
        if f45 and f49:
            return "45_and_49"
        if f45:
            return "45_only"
        if f49:
            return "49_only"
        return "none"

    def run(self, request: TransformRequest) -> TransformResponse:
        hit_status = self.parser.detect_hit_status(request)  # type: ignore[attr-defined]
        extracted = self.parser.parse(request)
        features, diagnostics_dict, enrichment = self.feature_builder.build(extracted, hit_status)
        self._validate_feature_contract(features)

        rule_features = dict(features)
        rule_features["applicant_age_years"] = enrichment.get("applicant_age_years")
        rule_features["debt_service_ratio_est"] = enrichment.get("monthly_dsr_est")
        hard_stop = self.hard_stop_evaluator.evaluate(rule_features)
        decision_package = self.rule_engine.decide(rule_features, hard_stop, hit_status)
        self._apply_inference_required_feature_fail_closed(
            request=request,
            decision_package=decision_package,
            diagnostics_dict=diagnostics_dict,
        )
        self._validate_decision_package(decision_package)

        data_quality_score = self.quality_provider.get_score(request)
        decision_package["data_quality_score"] = data_quality_score
        decision_package["request_id"] = request.request_id
        decision_package["applicant_age_at_application"] = enrichment.get("applicant_age_years")
        decision_package["credit_age_months_at_application"] = self._credit_age_months_from_feature(
            features.get("credit_age_months")
        )

        targets = self._build_targets(extracted=extracted, enrichment=enrichment, features=features)
        metadata = self._build_metadata(
            request=request,
            hit_status=hit_status,
            features=features,
            diagnostics_dict=diagnostics_dict,
            enrichment=enrichment,
            decision_package=decision_package,
            targets=targets,
        )

        diagnostics = TransformDiagnostics(
            missing_feature_list=diagnostics_dict.get("missing_feature_list", []),
            feature_coverage_ratio=diagnostics_dict.get("feature_coverage_ratio", 0.0),
            thin_file_flag=diagnostics_dict.get("thin_file_flag", 0),
            no_record_flag=diagnostics_dict.get("no_record_flag", 0),
            product45_available_flag=diagnostics_dict.get("product45_available_flag", 0),
            product49_available_flag=diagnostics_dict.get("product49_available_flag", 0),
            critical_field_missing_flag=diagnostics_dict.get("critical_field_missing_flag", 0),
        )

        return TransformResponse.create(
            request_id=request.request_id,
            bureau_hit_status=hit_status,
            features=features,
            feature_provenance=enrichment.get("feature_provenance", {}),
            metadata=metadata,
            targets=targets,
            decision_package=decision_package,
            diagnostics=diagnostics,
            transform_version=self.transform_version,
            rule_version=self.rule_version,
        )

    def _validate_feature_contract(self, features: dict) -> None:
        expected = getattr(self.feature_builder, "FEATURE_NAMES", ())
        if expected:
            missing = [name for name in expected if name not in features]
            if missing:
                raise ValueError(f"Feature contract violation. Missing features: {missing}")
            if len(features) != len(expected):
                raise ValueError(
                    f"Feature contract violation. Expected exactly {len(expected)} features, got {len(features)}."
                )

    def _validate_decision_package(self, decision_package: dict) -> None:
        required = (
            "hard_stop_triggered",
            "hard_stop_code",
            "credit_score",
            "score_grade",
            "risk_tier",
            "decision",
            "decision_reason_codes",
            "condition_applied",
        )
        missing = [key for key in required if key not in decision_package]
        if missing:
            raise ValueError(f"Decision package contract violation. Missing keys: {missing}")

    def _build_targets(self, extracted: dict, enrichment: dict, features: dict) -> dict:
        agreements = (enrichment.get("agreements") or []) + (enrichment.get("mobile_accounts") or [])
        default_flag, exclude_reason = self._derive_default_flag(agreements)
        max_successful_loan = self._derive_max_successful_loan(agreements)
        income_tier, income_confidence = self._derive_income_tier_proxy(
            monthly_dsr_est=enrichment.get("monthly_dsr_est"),
            applicant_age_years=enrichment.get("applicant_age_years", 0),
            has_employer_detail=self._has_employer_detail(extracted),
            product_source=enrichment.get("product_source", "NONE"),
            total_monthly_instalment_score=self._to_float(features.get("total_monthly_instalment_ghs")),
            utilisation_ratio_score=self._to_float(features.get("utilisation_ratio")),
        )
        return {
            "default_flag": default_flag,
            "default_flag_exclusion_reason": exclude_reason,
            "max_successful_loan_ghs": max_successful_loan,
            "income_tier": self._income_tier_to_int(income_tier),
            "income_tier_proxy": income_tier,
            "income_tier_proxy_confidence": income_confidence,
            "income_tier_proxy_source": "RULE_ONLY",
            "fraud_target": None,
        }

    def _build_metadata(
        self,
        request: TransformRequest,
        hit_status: str,
        features: dict,
        diagnostics_dict: dict,
        enrichment: dict,
        decision_package: dict,
        targets: dict,
    ) -> dict:
        return {
            "record_id": request.request_id,
            "product_source": enrichment.get("product_source", "NONE"),
            "product_mix": self._product_mix(diagnostics_dict),
            "bureau_hit_status": hit_status,
            "credit_score": decision_package.get("credit_score"),
            "score_grade": decision_package.get("score_grade"),
            "decision_label": decision_package.get("decision"),
            "data_quality_score": decision_package.get("data_quality_score"),
            "credit_age_months_at_application": self._credit_age_months_from_feature(
                features.get("credit_age_months")
            ),
            "bureau_hit_status_code": {"HIT": 2, "THIN_FILE": 1, "NO_RECORD": 0}.get(hit_status, 0),
            "thin_file_flag": diagnostics_dict.get("thin_file_flag", 0),
            "no_record_flag": diagnostics_dict.get("no_record_flag", 0),
            "feature_coverage_ratio": diagnostics_dict.get("feature_coverage_ratio", 0.0),
            "product45_available_flag": diagnostics_dict.get("product45_available_flag", 0),
            "product49_available_flag": diagnostics_dict.get("product49_available_flag", 0),
            "critical_field_missing_flag": diagnostics_dict.get("critical_field_missing_flag", 0),
            "required_non_imputable_missing_list": diagnostics_dict.get(
                "required_non_imputable_missing_list", []
            ),
            "required_non_imputable_missing_flag": diagnostics_dict.get(
                "required_non_imputable_missing_flag", 0
            ),
            "available_feature_count": enrichment.get("available_feature_count", 0),
            "available_features": enrichment.get("available_features", []),
            "feature_split": "30_features_plus_metadata_v2",
            "target_excluded": targets.get("default_flag") is None,
            "imputation_policy_version": enrichment.get("imputation_policy_version", "unknown"),
        }

    def _apply_inference_required_feature_fail_closed(
        self,
        request: TransformRequest,
        decision_package: dict,
        diagnostics_dict: dict,
    ) -> None:
        if request.flow_type != "inference":
            return
        required_missing = list(
            diagnostics_dict.get("required_non_imputable_missing_list", []) or []
        )
        if not required_missing:
            return
        decision_package["hard_stop_triggered"] = True
        decision_package["hard_stop_code"] = "FEATURE_VALIDATION_FAILED"
        decision_package["credit_score"] = 300
        decision_package["score_grade"] = "F"
        decision_package["risk_tier"] = "VERY_HIGH"
        decision_package["decision"] = "DECLINE"
        decision_package["decision_reason_codes"] = ["FEATURE_VALIDATION_FAILED"]
        decision_package["condition_applied"] = None

    def _derive_default_flag(self, agreements: list[dict]) -> tuple[int | None, str | None]:
        if not agreements:
            return None, "NO_ACCOUNTS"
        saw_default = False
        saw_non_default = False
        ambiguous_only = True
        for account in agreements:
            status = str((account or {}).get("accountStatusCode", "")).strip().upper()
            arrears = self._to_int((account or {}).get("monthsInArrears"))
            if status in {"D", "E", "RV"}:
                return None, f"EXCLUDED_STATUS_{status}"
            if status in {"W", "G", "L", "X"}:
                saw_default = True
                ambiguous_only = False
                continue
            if status == "A":
                if arrears >= 3:
                    saw_default = True
                    ambiguous_only = False
                elif arrears in (1, 2):
                    continue
                else:
                    saw_non_default = True
                    ambiguous_only = False
                continue
            if status in {"C", "P", "T"}:
                saw_non_default = True
                ambiguous_only = False
                continue
            if status:
                saw_non_default = True
                ambiguous_only = False
        if saw_default:
            return 1, None
        if ambiguous_only:
            return None, "AMBIGUOUS_ACTIVE_1_2_ARREARS"
        if saw_non_default:
            return 0, None
        return None, "UNMAPPED_STATUS"

    def _derive_max_successful_loan(self, agreements: list[dict]) -> float | None:
        values = []
        for account in agreements:
            status = str((account or {}).get("accountStatusCode", "")).strip().upper()
            if status not in {"C", "P"}:
                continue
            amount = self._to_float((account or {}).get("openingBalanceAmt"))
            if amount > 0:
                values.append(amount)
        if not values:
            return None
        return max(values)

    def _derive_income_tier_proxy(
        self,
        monthly_dsr_est: float | None,
        applicant_age_years: int | None,
        has_employer_detail: bool,
        product_source: str,
        total_monthly_instalment_score: float | None = None,
        utilisation_ratio_score: float | None = None,
    ) -> tuple[str | None, float]:
        age_years = applicant_age_years if isinstance(applicant_age_years, int) else 0
        if monthly_dsr_est is not None and monthly_dsr_est > 0:
            assumed_dsr = 0.35 if has_employer_detail else 0.30
            estimated_income = (1.0 / monthly_dsr_est) * assumed_dsr * 1000
            if estimated_income < 2000:
                tier = "LOW"
            elif estimated_income <= 10000:
                tier = "MID"
            elif estimated_income <= 25000:
                tier = "UPPER_MID"
            else:
                tier = "HIGH"
            confidence = 0.75
        else:
            # applicant_context is dropped; use XDS-only proxy signals.
            inst = float(total_monthly_instalment_score or 0.0)
            util = float(utilisation_ratio_score or 0.0)
            age_component = 0.0 if age_years <= 0 else min(age_years, 75) / 75.0
            proxy_score = (0.40 * inst) + (0.35 * util) + (0.25 * age_component)
            if has_employer_detail:
                proxy_score += 0.10
            if proxy_score < 0.35:
                tier = "LOW"
            elif proxy_score < 0.55:
                tier = "MID"
            elif proxy_score < 0.75:
                tier = "UPPER_MID"
            else:
                tier = "HIGH"
            confidence = 0.55
        if product_source == "NONE":
            confidence = 0.4
        elif product_source == "49":
            confidence = 0.55
        if has_employer_detail:
            confidence += 0.1
        if age_years <= 0:
            confidence -= 0.2
        return tier, round(min(max(confidence, 0.0), 1.0), 2)

    def _income_tier_to_int(self, income_tier: str | None) -> int | None:
        if income_tier is None:
            return None
        mapping = {"LOW": 0, "MID": 1, "UPPER_MID": 2, "HIGH": 3}
        return mapping.get(income_tier)

    def _credit_age_months_from_feature(self, feature_value: object) -> int:
        if feature_value is None:
            return 0
        try:
            score = float(feature_value)
        except (TypeError, ValueError):
            return 0
        if score >= 1.0:
            return 85
        if score >= 0.85:
            return 60
        if score >= 0.65:
            return 36
        if score >= 0.40:
            return 18
        return 6

    def _to_int(self, value: object) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0

    def _to_float(self, value: object) -> float:
        if value is None:
            return 0.0
        if isinstance(value, str):
            cleaned = value.replace(",", "").strip()
            if not cleaned:
                return 0.0
            try:
                return float(cleaned)
            except ValueError:
                return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
