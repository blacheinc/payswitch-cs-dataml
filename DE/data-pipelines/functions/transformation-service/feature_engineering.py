from datetime import datetime, timezone
from typing import Any, Dict, Tuple

from imputation_contract import resolve_effective_policy

from contracts import BureauHitStatus


class DeterministicFeatureBuilder:
    FEATURE_NAMES = (
        "highest_delinquency_rating",
        "months_on_time_24m",
        "worst_arrears_24m",
        "current_streak_on_time",
        "has_active_arrears",
        "total_arrear_amount_ghs",
        "total_outstanding_debt_ghs",
        "utilisation_ratio",
        "num_active_accounts",
        "total_monthly_instalment_ghs",
        "credit_age_months",
        "num_accounts_total",
        "num_closed_accounts_good",
        "product_diversity_score",
        "mobile_loan_history_count",
        "mobile_max_loan_ghs",
        "has_judgement",
        "has_written_off",
        "has_charged_off",
        "has_legal_handover",
        "num_bounced_cheques",
        "has_adverse_default",
        "num_enquiries_3m",
        "num_enquiries_12m",
        "enquiry_reason_flags",
        "applicant_age",
        "identity_verified",
        "num_dependants",
        "has_employer_detail",
        "address_stability",
    )

    # Contract-aligned defaults for NO_RECORD (no bureau profile).
    # Source: "Default Feature Values — NO_RECORD Applicants" in
    # Payswitch Credit Score Multi-Model AI Development.md
    NO_RECORD_DEFAULTS = {
        "highest_delinquency_rating": 0.00,
        "months_on_time_24m": 0.00,
        "worst_arrears_24m": 0.00,
        "current_streak_on_time": 0.20,
        "has_active_arrears": 0.00,
        "total_arrear_amount_ghs": 1.00,
        "total_outstanding_debt_ghs": 1.00,
        "utilisation_ratio": 1.00,
        "num_active_accounts": 0.15,
        "total_monthly_instalment_ghs": 1.00,
        "credit_age_months": 0.15,
        "num_accounts_total": 0.00,
        "num_closed_accounts_good": 0.10,
        "product_diversity_score": 0.30,
        "mobile_loan_history_count": 0.20,
        "mobile_max_loan_ghs": 0.00,
        "has_judgement": 0.00,
        "has_written_off": 0.00,
        "has_charged_off": 0.00,
        "has_legal_handover": 0.00,
        "num_bounced_cheques": 0.00,
        "has_adverse_default": 0.00,
        "num_enquiries_3m": 1.00,
        "num_enquiries_12m": 1.00,
        "enquiry_reason_flags": 0.00,
    }
    _POLICY_CACHE: Dict[str, Any] | None = None

    def build(
        self, extracted: Dict[str, Any], hit_status: BureauHitStatus
    ) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        p45 = extracted.get("product45", {}) or {}
        p49 = extracted.get("product49", {}) or {}
        enquiry_history = list(extracted.get("enquiry_history") or [])
        thin_personal = extracted.get("thin_file_personal") or {}
        thin_overrides = extracted.get("thin_file_overrides") or {}
        agreements = p45.get("credit_agreements", []) or []

        features: Dict[str, Any] = {name: None for name in self.FEATURE_NAMES}
        provenance: Dict[str, str] = {name: "missing" for name in self.FEATURE_NAMES}
        missing = []

        if hit_status == "NO_RECORD":
            self._apply_no_record_defaults(features, provenance)

        payment_metrics = self._payment_metrics_24m(p45.get("payment_history", []), agreements)
        if hit_status == "HIT":
            self._set(features, provenance, "months_on_time_24m", self._bin_months_on_time(payment_metrics["months_on_time"]), "p45")
            self._set(features, provenance, "worst_arrears_24m", self._bin_worst_arrears(payment_metrics["worst_arrears"]), "p45")
            self._set(features, provenance, "current_streak_on_time", self._bin_current_streak(payment_metrics["current_streak"]), "p45")
            if p45.get("has_highest_delinquency_input", False):
                self._set(
                    features,
                    provenance,
                    "highest_delinquency_rating",
                    self._bin_delinquency_rating(p45.get("highest_delinquency_rating_raw", 0)),
                    "p45",
                )
            if p45.get("has_total_account_in_arrear_input", False):
                has_active_arrears = 1 if p45.get("total_account_in_arrear_ghs", 0) > 0 else 0
                self._set(features, provenance, "has_active_arrears", 1.0 if has_active_arrears == 0 else 0.0, "p45")
            self._set(features, provenance, "total_arrear_amount_ghs", self._bin_total_arrear_amount(p45.get("total_arrear_amount_ghs", 0)), "p45")
            self._set(features, provenance, "total_outstanding_debt_ghs", self._bin_total_outstanding_debt(p45.get("total_outstanding_debt_ghs", 0)), "p45")
            self._set(features, provenance, "num_active_accounts", self._bin_num_active_accounts(p45.get("num_active_accounts", 0)), "p45")
            self._set(features, provenance, "num_accounts_total", self._bin_num_accounts_total(p45.get("num_accounts_total", 0)), "p45")
            self._set(features, provenance, "credit_age_months", self._bin_credit_age_months(self._credit_age_months(agreements)), "p45")
            self._set(features, provenance, "num_closed_accounts_good", self._bin_closed_accounts_good(self._count_closed_good_accounts(agreements)), "p45")
            self._set(features, provenance, "product_diversity_score", self._bin_product_diversity(self._product_diversity_count(agreements)), "p45")
            if p45.get("has_judgement_input", False):
                self._set(features, provenance, "has_judgement", float(p45.get("has_judgement", 0)), "p45")
            self._set(features, provenance, "has_adverse_default", float(p45.get("has_adverse_default", 0)), "p45")
            self._set(features, provenance, "num_bounced_cheques", self._bin_bounced_cheques(float(p45.get("num_bounced_cheques", 0))), "p45")
            self._set(features, provenance, "num_dependants", self._bin_dependants(p45.get("dependants", 0)), "p45")
            self._set(features, provenance, "has_employer_detail", 1.0 if p45.get("has_employer_detail", 0) else 0.6, "p45")
            self._set(features, provenance, "address_stability", self._bin_address_stability(self._distinct_address_count(p45.get("address_history", []))), "p45")

        if hit_status == "THIN_FILE" and thin_overrides:
            self._set(
                features,
                provenance,
                "highest_delinquency_rating",
                self._bin_delinquency_rating(thin_overrides.get("highest_delinquency_rating_raw", 0)),
                "p49",
            )

        if hit_status == "THIN_FILE" and thin_personal:
            self._set(
                features,
                provenance,
                "num_dependants",
                self._bin_dependants(thin_personal.get("dependants", 0)),
                "p49",
            )
            self._set(
                features,
                provenance,
                "has_employer_detail",
                1.0 if thin_personal.get("has_employer_detail") else 0.6,
                "p49",
            )

        if p49:
            self._set(features, provenance, "mobile_loan_history_count", self._bin_mobile_history_count(p49.get("mobile_loan_history_count", 0)), "p49")
            self._set(features, provenance, "mobile_max_loan_ghs", self._bin_mobile_max_loan(p49.get("mobile_max_loan_ghs", 0)), "p49")

        total_monthly_inst = float(p45.get("total_monthly_instalment_ghs", 0)) + float(p49.get("mobile_total_monthly_instalment_ghs", 0))
        if p45 or p49:
            src = "p45+p49" if p45 and p49 else ("p45" if p45 else "p49")
            self._set(features, provenance, "total_monthly_instalment_ghs", self._bin_total_monthly_instalment(total_monthly_inst), src)
            if hit_status == "HIT":
                self._set(
                    features,
                    provenance,
                    "utilisation_ratio",
                    self._bin_utilisation_ratio(self._utilisation_ratio_from_agreements(agreements)),
                    "p45",
                )

        status_flags = self._status_code_flags(agreements + (p49.get("mobile_accounts", []) or []))
        if p45 or p49:
            src = "p45+p49" if p45 and p49 else ("p45" if p45 else "p49")
            if p49 or p45.get("has_credit_agreements_input", False):
                self._set(features, provenance, "has_written_off", float(status_flags["has_written_off"]), src)
            self._set(features, provenance, "has_charged_off", float(status_flags["has_charged_off"]), src)
            self._set(features, provenance, "has_legal_handover", float(status_flags["has_legal_handover"]), src)

        if p45:
            if p45.get("has_national_id_input", False):
                self._set(
                    features,
                    provenance,
                    "identity_verified",
                    self._identity_verified(p45.get("national_id_no")),
                    "p45",
                )

        birth_date = p45.get("birth_date")
        age = self._age_from_birth_date(birth_date)
        if age > 0:
            self._set(features, provenance, "applicant_age", self._bin_age(age), "p45")
        if age <= 0:
            missing.append("applicant_age")
        if p45:
            eh_list = list(p45.get("enquiry_history") or [])
            enq3, enq12 = self._enquiry_bins(eh_list)
            self._set(features, provenance, "num_enquiries_3m", enq3, "p45")
            self._set(features, provenance, "num_enquiries_12m", enq12, "p45")
            # Single scalar: 1.0 if any bureau enquiry row exists (after 45/49 merge on HIT).
            # Per-enquiry `enquiryReason` text is not encoded (see docs); ML needs a non-null float.
            self._set(
                features,
                provenance,
                "enquiry_reason_flags",
                1.0 if len(eh_list) > 0 else 0.0,
                "p45",
            )
        elif hit_status == "THIN_FILE":
            eh_list = list(enquiry_history)
            enq3, enq12 = self._enquiry_bins(eh_list)
            self._set(features, provenance, "num_enquiries_3m", enq3, "p49")
            self._set(features, provenance, "num_enquiries_12m", enq12, "p49")
            self._set(
                features,
                provenance,
                "enquiry_reason_flags",
                1.0 if len(eh_list) > 0 else 0.0,
                "p49",
            )

        # DE-owned policy imputation for documented product-gap fields only.
        policy = self._load_de_imputation_policy()
        self._apply_policy_imputation(features, provenance, hit_status, p49, policy)

        missing.extend(self._collect_missing(features))
        required_non_imputable_missing = self._required_non_imputable_missing(features, policy)
        feature_coverage_ratio = self._coverage(features, missing)
        product_source = "45+49" if hit_status == "HIT" and p49 else ("45" if hit_status == "HIT" else ("49" if hit_status == "THIN_FILE" else "NONE"))
        critical_field_missing_flag = 1 if age <= 0 else 0
        available_features = [name for name in self.FEATURE_NAMES if features.get(name) is not None]
        # applicant_context is no longer required for deterministic features.
        monthly_dsr_est = None

        diagnostics = {
            "missing_feature_list": sorted(set(missing)),
            "feature_coverage_ratio": feature_coverage_ratio,
            "thin_file_flag": 1 if hit_status == "THIN_FILE" else 0,
            "no_record_flag": 1 if hit_status == "NO_RECORD" else 0,
            "product45_available_flag": 1 if hit_status == "HIT" else 0,
            "product49_available_flag": 1 if p49 else 0,
            "critical_field_missing_flag": critical_field_missing_flag,
            "required_non_imputable_missing_list": required_non_imputable_missing,
            "required_non_imputable_missing_flag": 1 if required_non_imputable_missing else 0,
        }
        enrichment = {
            "feature_provenance": provenance,
            "product_source": product_source,
            "feature_coverage_ratio": feature_coverage_ratio,
            "available_feature_count": len(available_features),
            "available_features": available_features,
            "monthly_dsr_est": monthly_dsr_est,
            "applicant_age_years": age if age > 0 else None,
            "critical_field_missing_flag": critical_field_missing_flag,
            "agreements": agreements,
            "mobile_accounts": p49.get("mobile_accounts", []) or [],
            "imputation_policy_version": policy.get("policy_version", "unknown"),
        }
        return features, diagnostics, enrichment

    def _set(self, features: Dict[str, Any], provenance: Dict[str, str], key: str, value: Any, source: str) -> None:
        features[key] = value
        provenance[key] = source

    def _apply_no_record_defaults(self, features: Dict[str, Any], provenance: Dict[str, str]) -> None:
        for name, value in self.NO_RECORD_DEFAULTS.items():
            self._set(features, provenance, name, value, "no_record_default")

    def _load_de_imputation_policy(self) -> Dict[str, Any]:
        if self._POLICY_CACHE is not None:
            return self._POLICY_CACHE
        self._POLICY_CACHE = resolve_effective_policy()
        return self._POLICY_CACHE

    def _apply_policy_imputation(
        self,
        features: Dict[str, Any],
        provenance: Dict[str, str],
        hit_status: str,
        p49: Dict[str, Any],
        policy: Dict[str, Any],
    ) -> None:
        feature_strategies = policy.get("feature_strategies", {}) or {}
        applies_to = policy.get("applies_to", {}) or {}
        feature_list: list[str] = []

        # Product 45-only path (HIT without mobile payload) -> impute product49-only fields.
        if hit_status == "HIT" and not p49:
            feature_list = list(applies_to.get("product_source_45", []) or [])
        # Product 49-only path -> impute product45-only fields.
        elif hit_status == "THIN_FILE":
            feature_list = list(applies_to.get("product_source_49", []) or [])

        for name in feature_list:
            if features.get(name) is not None:
                continue
            cfg = feature_strategies.get(name, {}) or {}
            value = cfg.get("value")
            strategy = str(cfg.get("strategy", "UNKNOWN")).upper()
            if value is None:
                continue
            source = "imputed_zero" if strategy == "ZERO" else "imputed_median"
            self._set(features, provenance, name, float(value), source)

    def _required_non_imputable_missing(self, features: Dict[str, Any], policy: Dict[str, Any]) -> list[str]:
        required = list(policy.get("required_non_imputable_features", []) or [])
        return [name for name in required if features.get(name) is None]

    def _bin_age(self, age: int) -> float:
        if age < 18 or age > 75:
            return 0.0
        if age <= 25:
            return 0.70
        if age <= 40:
            return 1.00
        if age <= 60:
            return 0.90
        return 0.65

    def _age_from_birth_date(self, birth_date: Any) -> int:
        if not birth_date or not isinstance(birth_date, str):
            return 0
        try:
            dt = datetime.strptime(birth_date.split()[0], "%d/%m/%Y")
            today = datetime.utcnow()
            return today.year - dt.year - ((today.month, today.day) < (dt.month, dt.day))
        except ValueError:
            return 0

    def _utilisation_ratio(self, outstanding: float, requested: float) -> float:
        base = requested if requested > 0 else 1.0
        ratio = outstanding / base
        return min(max(ratio, 0.0), 1.0)

    def _utilisation_ratio_from_agreements(self, agreements: list[dict]) -> float:
        ratios = []
        for agreement in agreements:
            opening = self._to_float(agreement.get("openingBalanceAmt"))
            current = self._to_float(agreement.get("currentBalanceAmt"))
            if opening > 0:
                ratios.append(current / opening)
        if not ratios:
            return 0.0
        avg = sum(ratios) / len(ratios)
        return min(max(avg, 0.0), 1.2)

    def _payment_metrics_24m(self, histories: list[dict], agreements: list[dict]) -> Dict[str, int]:
        months_on_time = 0
        current_streak = 0
        streak_open = True
        worst_arrears = 0

        for history in histories:
            for month in range(1, 25):
                key = f"m{month:02d}"
                value = str(history.get(key, "")).strip()
                if value == "0":
                    months_on_time += 1
                    if streak_open:
                        current_streak += 1
                elif value in ("", "#", "C", "P", "T", "RV"):
                    streak_open = False
                else:
                    try:
                        arrears = int(value)
                        worst_arrears = max(worst_arrears, arrears)
                    except ValueError:
                        pass
                    streak_open = False

        for agreement in agreements:
            try:
                worst_arrears = max(worst_arrears, int(float(agreement.get("monthsInArrears", 0))))
            except (TypeError, ValueError):
                continue

        return {
            "months_on_time": months_on_time,
            "current_streak": current_streak,
            "worst_arrears": worst_arrears,
        }

    def _credit_age_months(self, agreements: list[dict]) -> int:
        oldest = None
        for agreement in agreements:
            dt = self._parse_date(agreement.get("dateAccountOpened"))
            if dt and (oldest is None or dt < oldest):
                oldest = dt
        if oldest is None:
            return 0
        now = datetime.now(timezone.utc)
        return max(0, (now.year - oldest.year) * 12 + (now.month - oldest.month))

    def _count_closed_good_accounts(self, agreements: list[dict]) -> int:
        bad_codes = {"W", "G", "L", "X", "D"}
        count = 0
        for agreement in agreements:
            status = str(agreement.get("accountStatusCode", "")).upper().strip()
            closed = bool(agreement.get("closedDate"))
            if closed and status not in bad_codes:
                count += 1
        return count

    def _product_diversity_count(self, agreements: list[dict]) -> int:
        seen = set()
        for agreement in agreements:
            raw = (
                agreement.get("accountType")
                or agreement.get("loanType")
                or agreement.get("subscriberName")
                or ""
            )
            value = str(raw).strip().lower()
            if value:
                seen.add(value)
        return len(seen)

    def _distinct_address_count(self, addresses: list[dict]) -> int:
        seen = set()
        for item in addresses:
            if isinstance(item, dict):
                addr = (
                    item.get("address")
                    or item.get("residentialAddress")
                    or item.get("postalAddress")
                    or ""
                )
            else:
                addr = str(item)
            addr = str(addr).strip().lower()
            if addr:
                seen.add(addr)
        return len(seen)

    def _status_code_flags(self, agreements: list[dict]) -> Dict[str, int]:
        has_written_off = 0
        has_charged_off = 0
        has_legal_handover = 0
        for agreement in agreements:
            status = str(agreement.get("accountStatusCode", "")).upper().strip()
            if status == "W":
                has_written_off = 1
            elif status == "G":
                has_charged_off = 1
            elif status == "L":
                has_legal_handover = 1
        return {
            "has_written_off": has_written_off,
            "has_charged_off": has_charged_off,
            "has_legal_handover": has_legal_handover,
        }

    def _enquiry_bins(self, enquiries: list[dict]) -> tuple[float, float]:
        now = datetime.now(timezone.utc)
        count_3m = 0
        count_12m = 0
        for enquiry in enquiries:
            dt = self._parse_date(enquiry.get("dateRequested"))
            if not dt:
                continue
            days = (now - dt).days
            if days <= 365:
                count_12m += 1
            if days <= 90:
                count_3m += 1
        return self._bin_enquiries_3m(count_3m), self._bin_enquiries_12m(count_12m)

    def _identity_verified(self, national_id: Any) -> float:
        if not national_id:
            return 0.0
        return 1.0

    def _to_float(self, value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _parse_date(self, value: Any) -> datetime | None:
        if not value:
            return None
        raw = str(value).strip()
        if not raw:
            return None
        token = raw.split()[0]
        for fmt in ("%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d"):
            try:
                return datetime.strptime(token, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _bin_delinquency_rating(self, rating: float) -> float:
        mapping = {0: 1.00, 1: 0.50, 2: 0.70, 3: 0.85, 4: 0.00}
        return mapping.get(int(rating), 0.0)

    def _bin_months_on_time(self, value: int) -> float:
        if value >= 20:
            return 1.00
        if value >= 15:
            return 0.80
        if value >= 10:
            return 0.55
        if value >= 5:
            return 0.25
        return 0.00

    def _bin_worst_arrears(self, value: int) -> float:
        if value <= 0:
            return 1.00
        if value == 1:
            return 0.70
        if value == 2:
            return 0.40
        if value <= 5:
            return 0.15
        return 0.00

    def _bin_current_streak(self, value: int) -> float:
        if value >= 12:
            return 1.00
        if value >= 6:
            return 0.75
        if value >= 3:
            return 0.45
        return 0.20

    def _bin_total_arrear_amount(self, amount: float) -> float:
        if amount <= 0:
            return 1.00
        if amount <= 500:
            return 0.70
        if amount <= 2000:
            return 0.35
        if amount <= 10000:
            return 0.10
        return 0.00

    def _bin_total_outstanding_debt(self, amount: float) -> float:
        if amount <= 0:
            return 1.00
        if amount <= 10000:
            return 0.80
        if amount <= 50000:
            return 0.60
        if amount <= 150000:
            return 0.30
        return 0.05

    def _bin_utilisation_ratio(self, ratio: float) -> float:
        if ratio <= 0.25:
            return 1.00
        if ratio <= 0.50:
            return 0.80
        if ratio <= 0.75:
            return 0.50
        if ratio <= 0.90:
            return 0.20
        return 0.05

    def _bin_num_active_accounts(self, value: float) -> float:
        count = int(value)
        if count <= 1:
            return 0.85
        if count <= 3:
            return 1.00
        if count <= 5:
            return 0.55
        return 0.15

    def _bin_total_monthly_instalment(self, amount: float) -> float:
        if amount <= 500:
            return 1.00
        if amount <= 2000:
            return 0.85
        if amount <= 5000:
            return 0.60
        if amount <= 15000:
            return 0.30
        return 0.05

    def _bin_credit_age_months(self, months: int) -> float:
        if months > 84:
            return 1.00
        if months >= 48:
            return 0.85
        if months >= 24:
            return 0.65
        if months >= 12:
            return 0.40
        return 0.15

    def _bin_num_accounts_total(self, value: float) -> float:
        count = int(value)
        if count >= 10:
            return 1.00
        if count >= 5:
            return 0.80
        if count >= 3:
            return 0.55
        if count >= 1:
            return 0.30
        return 0.00

    def _bin_closed_accounts_good(self, value: int) -> float:
        if value >= 5:
            return 1.00
        if value >= 3:
            return 0.75
        if value >= 1:
            return 0.45
        return 0.10

    def _bin_product_diversity(self, value: int) -> float:
        if value >= 4:
            return 1.00
        if value == 3:
            return 0.80
        if value == 2:
            return 0.55
        if value == 1:
            return 0.30
        return 0.00

    def _bin_mobile_history_count(self, value: float) -> float:
        count = int(value)
        if count >= 20:
            return 1.00
        if count >= 10:
            return 0.95
        if count >= 5:
            return 0.85
        if count >= 1:
            return 0.60
        return 0.20

    def _bin_enquiries_3m(self, value: int) -> float:
        if value <= 1:
            return 1.00
        if value <= 3:
            return 0.75
        if value <= 5:
            return 0.35
        return 0.05

    def _bin_enquiries_12m(self, value: int) -> float:
        if value <= 2:
            return 1.00
        if value <= 5:
            return 0.80
        if value <= 10:
            return 0.40
        return 0.10

    def _bin_dependants(self, value: float) -> float:
        dep = int(value)
        if dep == 0:
            return 1.00
        if dep <= 2:
            return 0.85
        if dep <= 4:
            return 0.65
        return 0.40

    def _bin_address_stability(self, distinct_addresses: int) -> float:
        if distinct_addresses <= 1:
            return 1.00
        if distinct_addresses == 2:
            return 0.75
        return 0.40

    def _bin_mobile_max_loan(self, value: float) -> float:
        amount = self._to_float(value)
        if amount <= 0:
            return 0.20
        if amount <= 500:
            return 0.40
        if amount <= 2000:
            return 0.60
        if amount <= 5000:
            return 0.80
        return 1.00

    def _bin_bounced_cheques(self, value: float) -> float:
        count = int(self._to_float(value))
        if count <= 0:
            return 1.00
        if count == 1:
            return 0.70
        if count == 2:
            return 0.35
        return 0.05

    def _collect_missing(self, features: Dict[str, Any]) -> list[str]:
        missing = []
        for key, value in features.items():
            if value is None:
                missing.append(key)
        return missing

    def _coverage(self, features: Dict[str, Any], missing: list[str]) -> float:
        non_meta = list(features.keys())
        if not non_meta:
            return 0.0
        missing_set = set(missing)
        available = sum(1 for k in non_meta if k not in missing_set)
        return round(available / len(non_meta), 4)

