"""
Normalize alternate XDS JSON shapes (e.g. snake_case bureau exports) to the camelCase
keys expected by flattening, validation, and Product45Parser.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Mapping


def _empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str) and not str(v).strip():
        return True
    return False


def _apply_key_aliases(obj: Dict[str, Any], canonical_to_aliases: Mapping[str, List[str]]) -> Dict[str, Any]:
    out = dict(obj)
    for canon, aliases in canonical_to_aliases.items():
        if not _empty(out.get(canon)):
            continue
        for alt in aliases:
            if alt in out and not _empty(out.get(alt)):
                out[canon] = out[alt]
                break
    return out


# Product 45 credit agreement: flat validation + parsers expect camelCase XDS names.
_AGREEMENT_ALIASES: Dict[str, List[str]] = {
    "accountStatusCode": ["status_code", "account_status_code"],
    "monthsInArrears": ["months_in_arrears"],
    "openingBalanceAmt": ["opening_balance_amt", "openingBalanceAmt", "credit_limit"],
    "currentBalanceAmt": ["current_balance", "current_balance_amt"],
    "dateAccountOpened": ["date_opened", "dateOpened", "date_account_opened"],
    "closedDate": ["closed_date", "closedDate"],
    "subscriberName": ["subscriber_name"],
    "accountNo": ["account_no", "accountNo"],
    "accountType": ["facility_type", "account_type", "accountType"],
    "loanType": ["loan_type", "facility_type", "loanType"],
    "creditLimit": ["credit_limit", "creditLimit"],
}

_PERSONAL_ALIASES: Dict[str, List[str]] = {
    "birthDate": ["birth_date", "birthDate"],
    "consumerID": ["consumer_id", "consumerID"],
    "firstName": ["first_name", "firstName"],
    "surname": ["surname", "last_name", "lastName"],
    "otherNames": ["other_names", "otherNames"],
    "nationalIDNo": ["national_id", "nationalIDNo"],
    "employerDetail": ["employer", "employerDetail"],
    "dependants": ["dependants"],
    "gender": ["gender"],
    "phone": ["phone", "phoneNumber"],
    "email": ["email"],
    "address": ["address", "residentialAddress"],
    "maritalStatus": ["marital_status", "maritalStatus"],
}

# Parser / feature layer field names (mixed casing matches Product45Parser).
_SUMMARY_ALIASES: Dict[str, List[str]] = {
    "totalOutstandingdebtGHS": ["total_outstanding_debt_ghs", "totalOutstandingdebtGHS"],
    "totalMonthlyInstalmentGHS": [
        "total_monthly_instalment_ghs",
        "totalMonthlyInstalmentGHS",
    ],
    "totalActiveAccountsGHS": [
        "total_accounts_good_standing",
        "total_active_accounts_ghs",
        "totalActiveAccountsGHS",
    ],
    "totalNumberofAccountsGHS": [
        "total_accounts",
        "total_number_of_accounts_ghs",
        "totalNumberofAccountsGHS",
    ],
    "totalClosedAccountsGHS": ["total_closed_accounts_ghs", "totalClosedAccountsGHS"],
    "totalNumberofDishonouredGHS": [
        "total_dishonoured_cheques",
        "total_numberof_dishonoured_ghs",
        "totalNumberofDishonouredGHS",
    ],
    "totalAccountInArrearGHS": [
        "total_accounts_in_arrear",
        "total_account_in_arrear_ghs",
        "totalAccountInArrearGHS",
    ],
    "totalAmountInArrearGHS": [
        "total_arrear_amount_ghs",
        "total_amount_in_arrear_ghs",
        "totalAmountInArrearGHS",
    ],
    "highestDelinquencyRating": ["delinquency_rating", "highestDelinquencyRating"],
}


def _normalize_report_45(report: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(report)
    if "personalDetailsSummary" in out and isinstance(out["personalDetailsSummary"], dict):
        out["personalDetailsSummary"] = _apply_key_aliases(out["personalDetailsSummary"], _PERSONAL_ALIASES)
    if "creditAccountSummary" in out and isinstance(out["creditAccountSummary"], dict):
        out["creditAccountSummary"] = _apply_key_aliases(out["creditAccountSummary"], _SUMMARY_ALIASES)
    raw_agreements = out.get("creditAgreementSummary")
    if isinstance(raw_agreements, list):
        normalized: List[Dict[str, Any]] = []
        for item in raw_agreements:
            if isinstance(item, dict):
                normalized.append(_apply_key_aliases(item, _AGREEMENT_ALIASES))
            else:
                normalized.append(item)  # type: ignore[arg-type]
        out["creditAgreementSummary"] = normalized
    return out


def normalize_nested_xds_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a shallow-deep copy of payload with known snake_case sections promoted to
    camelCase where the transformation service expects XDS-native names.
    """
    if not payload:
        return payload
    out = copy.deepcopy(payload)
    r45 = out.get("consumer_full_report_45")
    if isinstance(r45, dict):
        out["consumer_full_report_45"] = _normalize_report_45(r45)
    r49 = out.get("consumer_mobile_report_49")
    if r49 is not None and isinstance(r49, dict):
        # Thin-file mobile report sometimes uses the same personal/summary aliases.
        inner = copy.deepcopy(r49)
        if "personalDetailsSummary" in inner and isinstance(inner["personalDetailsSummary"], dict):
            inner["personalDetailsSummary"] = _apply_key_aliases(
                inner["personalDetailsSummary"], _PERSONAL_ALIASES
            )
        if "creditAccountSummary" in inner and isinstance(inner["creditAccountSummary"], dict):
            inner["creditAccountSummary"] = _apply_key_aliases(
                inner["creditAccountSummary"], _SUMMARY_ALIASES
            )
        facilities = inner.get("detailedFacilityInfo")
        if isinstance(facilities, list):
            inner["detailedFacilityInfo"] = [
                _apply_key_aliases(x, _AGREEMENT_ALIASES) if isinstance(x, dict) else x
                for x in facilities
            ]
        out["consumer_mobile_report_49"] = inner
    return out
