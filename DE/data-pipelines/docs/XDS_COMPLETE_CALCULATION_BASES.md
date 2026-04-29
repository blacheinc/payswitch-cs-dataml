# XDS Complete Calculation Bases (Deterministic v1)

## Purpose

Single-source reference for how deterministic transformation computes engineered features and decision package fields.

Primary basis documents:

- `project execution artifacts/Credit_Scoring_Engine_Model_Parameters_and_Decisioning_Rules.md`
- `data-pipelines/docs/XDS_DETERMINISTIC_POLICY_V1.md`
- `data-pipelines/docs/BACKEND_TO_ML_TRANSFORMATION_FLOW.md`

---

## 1) Input Source Sections

### Product 45 (primary)

- `personalDetailsSummary`
- `highestDelinquencyRating`
- `creditAccountSummary`
- `creditAgreementSummary`
- `accountMonthlyPaymentHistory`
- `enquiryHistory`
- `adverseDetails`, `defaults`, `judgementSummary`, `dudCheqEventSummary`
- `addressHistory`

### Product 49 (thin-file/mobile)

- `detailedFacilityInfo`
- `creditAccountSummary`
- `enquiryHistory`

### Applicant Context (backend-provided)

- `loan_amount_requested`
- `loan_tenure_months`
- `monthly_income`
- `identity_reference`

---

## 2) Engineered Feature Calculation Bases

Feature groups follow the model-parameters document (A-F) with bin-to-weight mapping in `[0,1]`.

### Group A: Delinquency & Payment History (35%)

- `highest_delinquency_rating`
  - Source: `highestDelinquencyRating.highestDelinquencyRating`
  - Bins: `0->1.00, 1->0.50, 2->0.70, 3->0.85, 4->0.00`

- `months_on_time_24m`
  - Source: `accountMonthlyPaymentHistory.m01..m24` where value is `"0"`
  - Bins: `20-24->1.00, 15-19->0.80, 10-14->0.55, 5-9->0.25, 0-4->0.00`

- `worst_arrears_24m`
  - Source: max of numeric `m01..m24` and `creditAgreementSummary.monthsInArrears`
  - Bins: `0->1.00, 1->0.70, 2->0.40, 3-5->0.15, >5->0.00`

- `current_streak_on_time`
  - Source: consecutive `"0"` from `m01` backwards
  - Bins: `>=12->1.00, 6-11->0.75, 3-5->0.45, <3->0.20`

- `has_active_arrears`
  - Source: `creditAccountSummary.totalAccountInArrearGHS > 0`
  - Mapping: `No->1.00, Yes->0.00`

- `total_arrear_amount_ghs`
  - Source: `creditAccountSummary.totalAmountInArrearGHS`
  - Bins: `0->1.00, 1-500->0.70, 501-2000->0.35, 2001-10000->0.10, >10000->0.00`

### Group B: Credit Exposure & Utilisation (25%)

- `total_outstanding_debt_ghs`
  - Source: `creditAccountSummary.totalOutstandingdebtGHS`
  - Bins: `0->1.00, 1-10k->0.80, 10k-50k->0.60, 50k-150k->0.30, >150k->0.05`

- `utilisation_ratio`
  - Source: average over agreements of `currentBalanceAmt / openingBalanceAmt`
  - Bins: `0-25%->1.00, 26-50%->0.80, 51-75%->0.50, 76-90%->0.20, >90%->0.05`

- `num_active_accounts`
  - Source: `creditAccountSummary.totalActiveAccountsGHS`
  - Bins: `1->0.85, 2-3->1.00, 4-5->0.55, >5->0.15`

- `total_monthly_instalment_ghs`
  - Source: `product45.totalMonthlyInstalmentGHS + product49.totalMonthlyInstalment`
  - Bins: `0-500->1.00, 501-2000->0.85, 2001-5000->0.60, 5001-15000->0.30, >15000->0.05`

### Group C: Credit History Depth (15%)

- `credit_age_months`
  - Source: months since oldest `dateAccountOpened`
  - Bins: `>84->1.00, 48-84->0.85, 24-47->0.65, 12-23->0.40, <12->0.15`

- `num_accounts_total`
  - Source: `creditAccountSummary.totalNumberofAccountsGHS`
  - Bins: `>=10->1.00, 5-9->0.80, 3-4->0.55, 1-2->0.30, 0->0.00`

- `num_closed_accounts_good`
  - Source: count of closed agreements excluding bad status codes (`W,G,L,X,D`)
  - Bins: `>=5->1.00, 3-4->0.75, 1-2->0.45, 0->0.10`

- `product_diversity_score`
  - Source: distinct account-type proxies from agreement fields
  - Bins: `>=4->1.00, 3->0.80, 2->0.55, 1->0.30, 0->0.00`

- `mobile_loan_history_count`
  - Source: `len(product49.detailedFacilityInfo)`
  - Bins: `>=20->1.00, 10-19->0.95, 5-9->0.85, 1-4->0.60, 0->0.20`

### Group D: Adverse Records (15%)

- `has_judgement` from `judgementSummary`
- `has_written_off` from agreement `accountStatusCode == 'W'`
- `has_charged_off` from agreement `accountStatusCode == 'G'`
- `has_legal_handover` from agreement `accountStatusCode == 'L'`
- `num_bounced_cheques` from `totalNumberofDishonouredGHS`/summary
- `has_adverse_default` from `adverseDetails/defaults`

Scoring treatment:

- `has_judgement`: hard-stop
- `has_written_off`: hard-stop
- `has_charged_off`: `-120` points
- `has_legal_handover`: `-80` points
- `num_bounced_cheques`: `1->-20`, `2->-50`, `>=3->refer-level penalty`
- `has_adverse_default`: `-100` points

### Group E: Enquiry Behaviour (5%)

- `num_enquiries_3m`
  - Source: enquiry count with `dateRequested <= 90 days`
  - Bins: `0-1->1.00, 2-3->0.75, 4-5->0.35, >5->0.05`

- `num_enquiries_12m`
  - Source: enquiry count with `dateRequested <= 365 days`
  - Bins: `0-2->1.00, 3-5->0.80, 6-10->0.40, >10->0.10`

- `enquiry_reason_flags`
  - Source: `enquiryReason` presence/flags
  - v1 mapping: binary indicator for reason availability.

### Group F: Identity & Demographics (5%)

- `applicant_age`
  - Source: `birthDate`
  - Bins: `<18 or >75 -> 0.00, 18-25->0.70, 26-40->1.00, 41-60->0.90, 61-75->0.65`

- `identity_verified`
  - Source: `nationalIDNo` + backend identity reference
  - Mapping: `confirmed->1.00 else 0.00`

- `num_dependants`
  - Source: `dependants`
  - Bins: `0->1.00, 1-2->0.85, 3-4->0.65, >=5->0.40`

- `has_employer_detail`
  - Source: `employerDetail`
  - Mapping: `yes->1.00, no->0.60`

- `address_stability`
  - Source: distinct addresses in `addressHistory`
  - Bins: `1->1.00, 2->0.75, >=3->0.40`

---

## 3) Score Construction Basis

1. Compute per-group scores in `[0,1]`:
   - A, B, C, E, F: mean of constituent binned features.
   - D: starts at `1.0`, then adverse penalties reduce score.
2. Weighted ensemble:
   - `0.35*A + 0.25*B + 0.15*C + 0.15*D + 0.05*E + 0.05*F`
3. Credit score:
   - `credit_score = 300 + (550 * weighted_ensemble)`
   - clamp weighted ensemble to `[0,1]`
4. Grade mapping:
   - `A: 750-850, B: 700-749, C: 650-699, D: 600-649, E: 520-599, F: <520`
5. Risk tier mapping:
   - `VERY_LOW, LOW, MEDIUM, HIGH, VERY_HIGH` by grade/score bands.

---

## 4) Hard-Stop and Decision Basis

Hard-stop priority order:

1. Age ineligible
2. Fraud high
3. Identity fail
4. Court judgement
5. Written-off history (36m)
6. Critical delinquency
7. Multiple arrears

If hard-stop triggered:
- set hard-stop code and terminal decision.

If no hard-stop:
- decision matrix by grade and hit status.
- `NO_RECORD` default policy: `REFER` in v1.
- `THIN_FILE` policy: tightened approvals (conditional for A-D, refer/decline for lower grades).

Conditional approval code basis:
- `CA-01`: debt-service/high cap
- `CA-02`: age-driven tenor reduction
- `CA-05`: income verification request

---

## 5) Data Quality Score Basis

- `data_quality_score` is sourced from Systems 0-4 aggregated quality score (`s0_s4_v1`) when available.
- If unavailable, value is null and recorded in diagnostics path.

---

## 6) Trace/Audit Basis

Every output includes:

- `request_id`
- `bureau_hit_status`
- `hard_stop_triggered`
- `hard_stop_code`
- `scoring_timestamp`
- `transform_version`
- `rule_version`

