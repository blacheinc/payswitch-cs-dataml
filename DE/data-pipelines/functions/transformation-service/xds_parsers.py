"""XDS Product 45/49 parsing: extract bureau fields, merge histories, set hit status."""

from typing import Any, Dict, List, Tuple

from contracts import BureauHitStatus, TransformRequest


def _safe_float(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, str):
        value = value.replace(",", "").strip()
        if not value:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _enquiry_dedupe_key(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    eid = str(entry.get("subscriberEnquiryResultID") or "").strip()
    if eid:
        return ("id", eid)
    raw_dt = entry.get("dateRequested")
    dt_norm = str(raw_dt).strip().split()[0] if raw_dt else ""
    sub = str(entry.get("subscriberName") or "").strip().lower()
    return ("fb", dt_norm, sub)


def merge_enquiry_histories(seq45: List[Any], seq49: List[Any]) -> List[Dict[str, Any]]:
    """45-first merge with deduplication; same key keeps the Product 45 row."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for item in seq45 + seq49:
        if not isinstance(item, dict):
            continue
        k = _enquiry_dedupe_key(item)
        if k in seen:
            continue
        seen.add(k)
        out.append(item)
    return out


def _has_product_hit(report: Dict[str, Any]) -> bool:
    if not report:
        return False
    return (report.get("response") or {}).get("statusCode") == 200


def personal_from_49_report(report49: Dict[str, Any]) -> Dict[str, Any]:
    """F-group fields aligned with Product45Parser output keys (thin-file only)."""
    personal = report49.get("personalDetailsSummary", {}) or {}
    return {
        "birth_date": personal.get("birthDate"),
        "dependants": _safe_float(personal.get("dependants")),
        "has_employer_detail": 1 if personal.get("employerDetail") else 0,
        "national_id_no": personal.get("nationalIDNo"),
    }


def thin_file_credit_overrides_from_49(report49: Dict[str, Any]) -> Dict[str, Any]:
    highest = report49.get("highestDelinquencyRating", {}) or {}
    return {
        "highest_delinquency_rating_raw": _safe_float(highest.get("highestDelinquencyRating")),
    }


class Product45Parser:
    """Extract Product 45 (consumer full report) sections from nested or flat payloads."""
    def parse(self, report45: Dict[str, Any]) -> Dict[str, Any]:
        personal = report45.get("personalDetailsSummary", {}) or {}
        highest = report45.get("highestDelinquencyRating", {}) or {}
        summary = report45.get("creditAccountSummary", {}) or {}
        agreements = report45.get("creditAgreementSummary", []) or []
        monthly = report45.get("accountMonthlyPaymentHistory", []) or []
        enquiries = report45.get("enquiryHistory", []) or []
        defaults = report45.get("defaults", []) or []
        judgements = report45.get("judgementSummary", []) or []
        bounced = report45.get("dudCheqEventSummary", []) or []
        adverse = report45.get("adverseDetails", []) or []
        address_history = report45.get("addressHistory", []) or []
        has_birth_date_input = bool(str(personal.get("birthDate") or "").strip())
        has_national_id_input = bool(str(personal.get("nationalIDNo") or "").strip())
        has_highest_delinquency_input = bool(
            str(highest.get("highestDelinquencyRating") or "").strip()
        )
        has_total_account_in_arrear_input = bool(
            str(summary.get("totalAccountInArrearGHS") or "").strip()
        )
        has_judgement_input = "judgementSummary" in report45
        has_credit_agreements_input = "creditAgreementSummary" in report45

        return {
            "birth_date": personal.get("birthDate"),
            "has_birth_date_input": has_birth_date_input,
            "dependants": _safe_float(personal.get("dependants")),
            "has_employer_detail": 1 if personal.get("employerDetail") else 0,
            "national_id_no": personal.get("nationalIDNo"),
            "has_national_id_input": has_national_id_input,
            "highest_delinquency_rating_raw": _safe_float(
                highest.get("highestDelinquencyRating")
            ),
            "has_highest_delinquency_input": has_highest_delinquency_input,
            "total_outstanding_debt_ghs": _safe_float(summary.get("totalOutstandingdebtGHS")),
            "total_monthly_instalment_ghs": _safe_float(
                summary.get("totalMonthlyInstalmentGHS")
            ),
            "num_active_accounts": _safe_float(summary.get("totalActiveAccountsGHS")),
            "num_accounts_total": _safe_float(summary.get("totalNumberofAccountsGHS")),
            "num_closed_accounts_total": _safe_float(summary.get("totalClosedAccountsGHS")),
            "num_dishonoured_total": _safe_float(summary.get("totalNumberofDishonouredGHS")),
            "total_account_in_arrear_ghs": _safe_float(summary.get("totalAccountInArrearGHS")),
            "has_total_account_in_arrear_input": has_total_account_in_arrear_input,
            "total_arrear_amount_ghs": _safe_float(summary.get("totalAmountInArrearGHS")),
            "num_bounced_cheques": int(
                _safe_float(summary.get("totalNumberofDishonouredGHS")) or len(bounced)
            ),
            "has_judgement": 1 if judgements else 0,
            "has_judgement_input": has_judgement_input,
            "has_adverse_default": 1 if (defaults or adverse) else 0,
            "credit_agreements": agreements,
            "has_credit_agreements_input": has_credit_agreements_input,
            "payment_history": monthly,
            "enquiry_history": enquiries,
            "address_history": address_history,
        }


class Product49Parser:
    """Extract Product 49 (mobile) report fields for thin-file and supplement paths."""
    def parse(self, report49: Dict[str, Any]) -> Dict[str, Any]:
        facility = report49.get("detailedFacilityInfo", []) or []
        summary = report49.get("creditAccountSummary", {}) or {}
        mobile_accounts = []
        for item in facility:
            if not isinstance(item, dict):
                continue
            mobile_accounts.append(
                {
                    "accountStatusCode": item.get("accountStatusCode"),
                    "monthsInArrears": item.get("monthsInArrears"),
                    "openingBalanceAmt": item.get("openingBalanceAmt"),
                }
            )
        return {
            "mobile_loan_history_count": len(facility),
            "mobile_max_loan_ghs": _safe_float(summary.get("highestAmountTaken")),
            "mobile_total_outstanding_ghs": _safe_float(summary.get("totalOutstandingdebt")),
            "mobile_total_monthly_instalment_ghs": _safe_float(
                summary.get("totalMonthlyInstalment")
            ),
            "mobile_accounts": mobile_accounts,
        }


class XdsParser:
    """Facade: nested JSON, flat training rows, and hit/thin-file status from XDS payloads."""
    def __init__(self, p45: Product45Parser, p49: Product49Parser) -> None:
        self.p45 = p45
        self.p49 = p49

    def detect_hit_status(self, request: TransformRequest) -> BureauHitStatus:
        payload = request.xds_payload or {}
        if "__flat_row__" in payload:
            status = payload.get("__flat_row__", {}).get(
                "consumer_full_report_45.response.statusCode"
            )
            if int(_safe_float(status)) == 200:
                return "HIT"
            status49 = payload.get("__flat_row__", {}).get(
                "consumer_mobile_report_49.response.statusCode"
            )
            if int(_safe_float(status49)) == 200:
                return "THIN_FILE"
            return "NO_RECORD"
        r45 = payload.get("consumer_full_report_45")
        r49 = payload.get("consumer_mobile_report_49")

        has_45 = bool(r45 and (r45.get("response", {}) or {}).get("statusCode") == 200)
        has_49 = bool(r49 and (r49.get("response", {}) or {}).get("statusCode") == 200)

        if has_45:
            return "HIT"
        if has_49:
            return "THIN_FILE"
        return "NO_RECORD"

    def _assemble_extracted(
        self,
        request: TransformRequest,
        has_45: bool,
        has_49: bool,
        report45: Dict[str, Any],
        report49: Dict[str, Any],
    ) -> Dict[str, Any]:
        product45 = self.p45.parse(report45) if has_45 else {}
        product49 = self.p49.parse(report49) if has_49 else {}

        enquiries_45 = list(product45.get("enquiry_history") or []) if has_45 else []
        enquiries_49_raw = list(report49.get("enquiryHistory") or []) if has_49 else []
        enquiry_history = merge_enquiry_histories(enquiries_45, enquiries_49_raw)
        if has_45:
            product45["enquiry_history"] = enquiry_history

        thin_file_personal: Dict[str, Any] = {}
        thin_file_overrides: Dict[str, Any] = {}
        if not has_45 and has_49:
            thin_file_personal = personal_from_49_report(report49)
            thin_file_overrides = thin_file_credit_overrides_from_49(report49)

        return {
            "product45": product45,
            "product49": product49,
            "applicant_context": {
                "loan_amount_requested": request.applicant_context.loan_amount_requested,
                "loan_tenure_months": request.applicant_context.loan_tenure_months,
                "monthly_income": request.applicant_context.monthly_income,
                "identity_reference": request.applicant_context.identity_reference,
            },
            "enquiry_history": enquiry_history,
            "thin_file_personal": thin_file_personal,
            "thin_file_overrides": thin_file_overrides,
        }

    def parse(self, request: TransformRequest) -> Dict[str, Any]:
        payload = request.xds_payload or {}
        if "__flat_row__" in payload:
            row = payload.get("__flat_row__", {}) or {}
            status45 = int(_safe_float(row.get("consumer_full_report_45.response.statusCode")))
            status49 = int(_safe_float(row.get("consumer_mobile_report_49.response.statusCode")))
            has_45 = status45 == 200
            has_49 = status49 == 200

            report45: Dict[str, Any] = {}
            if has_45:
                report45 = {
                    "response": {
                        "statusCode": int(
                            _safe_float(row.get("consumer_full_report_45.response.statusCode"))
                        )
                    },
                    "personalDetailsSummary": {
                        "birthDate": row.get(
                            "consumer_full_report_45.personalDetailsSummary.birthDate"
                        ),
                        "dependants": row.get(
                            "consumer_full_report_45.personalDetailsSummary.dependants"
                        ),
                        "employerDetail": row.get(
                            "consumer_full_report_45.personalDetailsSummary.employerDetail"
                        ),
                        "nationalIDNo": row.get(
                            "consumer_full_report_45.personalDetailsSummary.nationalIDNo"
                        ),
                    },
                    "highestDelinquencyRating": {
                        "highestDelinquencyRating": row.get(
                            "consumer_full_report_45.highestDelinquencyRating.highestDelinquencyRating"
                        )
                    },
                    "creditAccountSummary": {
                        "totalOutstandingdebtGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalOutstandingdebtGHS"
                        ),
                        "totalMonthlyInstalmentGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalMonthlyInstalmentGHS"
                        ),
                        "totalActiveAccountsGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalActiveAccountsGHS"
                        ),
                        "totalNumberofAccountsGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalNumberofAccountsGHS"
                        ),
                        "totalNumberofDishonouredGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalNumberofDishonouredGHS"
                        ),
                        "totalAccountInArrearGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalAccountInArrearGHS"
                        ),
                        "totalAmountInArrearGHS": row.get(
                            "consumer_full_report_45.creditAccountSummary.totalAmountInArrearGHS"
                        ),
                    },
                    "creditAgreementSummary": [
                        {
                            "accountStatusCode": row.get(
                                "consumer_full_report_45.creditAgreementSummary.accountStatusCode"
                            ),
                            "monthsInArrears": row.get(
                                "consumer_full_report_45.creditAgreementSummary.monthsInArrears"
                            ),
                            "openingBalanceAmt": row.get(
                                "consumer_full_report_45.creditAgreementSummary.openingBalanceAmt"
                            ),
                            "currentBalanceAmt": row.get(
                                "consumer_full_report_45.creditAgreementSummary.currentBalanceAmt"
                            ),
                            "dateAccountOpened": row.get(
                                "consumer_full_report_45.creditAgreementSummary.dateAccountOpened"
                            ),
                            "closedDate": row.get(
                                "consumer_full_report_45.creditAgreementSummary.closedDate"
                            ),
                            "accountType": row.get(
                                "consumer_full_report_45.creditAgreementSummary.accountType"
                            ),
                            "loanType": row.get(
                                "consumer_full_report_45.creditAgreementSummary.loanType"
                            ),
                            "subscriberName": row.get(
                                "consumer_full_report_45.creditAgreementSummary.subscriberName"
                            ),
                        }
                    ],
                    "accountMonthlyPaymentHistory": [
                        {
                            f"m{i:02d}": row.get(
                                f"consumer_full_report_45.accountMonthlyPaymentHistory.m{i:02d}"
                            )
                            for i in range(1, 25)
                        }
                    ],
                    "enquiryHistory": [
                        {
                            "subscriberEnquiryResultID": row.get(
                                "consumer_full_report_45.enquiryHistory.subscriberEnquiryResultID"
                            ),
                            "dateRequested": row.get(
                                "consumer_full_report_45.enquiryHistory.dateRequested"
                            ),
                            "enquiryReason": row.get(
                                "consumer_full_report_45.enquiryHistory.enquiryReason"
                            ),
                            "subscriberName": row.get(
                                "consumer_full_report_45.enquiryHistory.subscriberName"
                            ),
                        }
                    ],
                    "judgementSummary": []
                    if row.get("consumer_full_report_45.judgementSummary") is None
                    else [row.get("consumer_full_report_45.judgementSummary")],
                    "defaults": []
                    if row.get("consumer_full_report_45.defaults") is None
                    else [row.get("consumer_full_report_45.defaults")],
                    "adverseDetails": []
                    if row.get("consumer_full_report_45.adverseDetails") is None
                    else [row.get("consumer_full_report_45.adverseDetails")],
                    "dudCheqEventSummary": []
                    if row.get("consumer_full_report_45.dudCheqEventSummary") is None
                    else [row.get("consumer_full_report_45.dudCheqEventSummary")],
                    "addressHistory": [
                        {
                            "address": row.get(
                                "consumer_full_report_45.addressHistory.address"
                            ),
                            "residentialAddress": row.get(
                                "consumer_full_report_45.addressHistory.residentialAddress"
                            ),
                            "postalAddress": row.get(
                                "consumer_full_report_45.addressHistory.postalAddress"
                            ),
                        }
                    ],
                }

            report49: Dict[str, Any] = {}
            if has_49:
                report49 = {
                    "response": {
                        "statusCode": int(
                            _safe_float(row.get("consumer_mobile_report_49.response.statusCode"))
                        )
                    },
                    "personalDetailsSummary": {
                        "birthDate": row.get(
                            "consumer_mobile_report_49.personalDetailsSummary.birthDate"
                        ),
                        "dependants": row.get(
                            "consumer_mobile_report_49.personalDetailsSummary.dependants"
                        ),
                        "employerDetail": row.get(
                            "consumer_mobile_report_49.personalDetailsSummary.employerDetail"
                        ),
                        "nationalIDNo": row.get(
                            "consumer_mobile_report_49.personalDetailsSummary.nationalIDNo"
                        ),
                    },
                    "highestDelinquencyRating": {
                        "highestDelinquencyRating": row.get(
                            "consumer_mobile_report_49.highestDelinquencyRating.highestDelinquencyRating"
                        )
                    },
                    "detailedFacilityInfo": [
                        {
                            "accountStatusCode": row.get(
                                "consumer_mobile_report_49.detailedFacilityInfo.accountStatusCode"
                            ),
                            "monthsInArrears": row.get(
                                "consumer_mobile_report_49.detailedFacilityInfo.monthsInArrears"
                            ),
                            "openingBalanceAmt": row.get(
                                "consumer_mobile_report_49.detailedFacilityInfo.openingBalanceAmt"
                            ),
                        }
                    ],
                    "creditAccountSummary": {
                        "highestAmountTaken": row.get(
                            "consumer_mobile_report_49.creditAccountSummary.highestAmountTaken"
                        ),
                        "totalOutstandingdebt": row.get(
                            "consumer_mobile_report_49.creditAccountSummary.totalOutstandingdebt"
                        ),
                        "totalMonthlyInstalment": row.get(
                            "consumer_mobile_report_49.creditAccountSummary.totalMonthlyInstalment"
                        ),
                    },
                    "enquiryHistory": [
                        {
                            "subscriberEnquiryResultID": row.get(
                                "consumer_mobile_report_49.enquiryHistory.subscriberEnquiryResultID"
                            ),
                            "dateRequested": row.get(
                                "consumer_mobile_report_49.enquiryHistory.dateRequested"
                            ),
                            "enquiryReason": row.get(
                                "consumer_mobile_report_49.enquiryHistory.enquiryReason"
                            ),
                            "subscriberName": row.get(
                                "consumer_mobile_report_49.enquiryHistory.subscriberName"
                            ),
                        }
                    ],
                }

            extracted = self._assemble_extracted(request, has_45, has_49, report45, report49)
            extracted["applicant_context"] = {}
            return extracted

        report45 = payload.get("consumer_full_report_45", {}) or {}
        report49 = payload.get("consumer_mobile_report_49", {}) or {}
        has_45 = _has_product_hit(report45)
        has_49 = _has_product_hit(report49)
        extracted = self._assemble_extracted(request, has_45, has_49, report45, report49)
        return extracted
