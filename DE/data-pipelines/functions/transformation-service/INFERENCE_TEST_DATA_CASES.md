# Inference Endpoint Test Data (Deployed Contract)

This file provides test inputs for all deployed inference endpoints:

- `POST /api/transform/inference`
- `POST /api/transform/inference/batch`
- `POST /api/transform/inference/batch/submit`

These cases match the currently deployed contract and runtime behavior.

---

## Quick usage notes

- Use function auth keys for each endpoint.
- Keep `source_system` as `xds` for valid cases.
- For `batch` endpoint, body must be UTF-8 JSONL (one JSON object per line).
- For `batch/submit`, each JSONL line must have:
  - `request_id`
  - `features` with exactly the 30 deterministic feature keys
  - `metadata` containing `data_source_id` and `source_system`

---

## Case summary

| Case ID | Endpoint | Type | Expected status | Expected outcome hit |
|---|---|---|---|---|
| INF-01 | `/transform/inference` | Happy path (Product 45, clean file) | 200 | `bureau_hit_status=HIT`, `decision_package` present |
| INF-02 | `/transform/inference` | Happy path (Product 49 thin-file style) | 200 | `bureau_hit_status` likely `THIN_FILE` or `HIT` depending parser fallback |
| INF-03 | `/transform/inference` | Edge (missing applicant_context) | 200 | still transforms; defaults applied |
| INF-04 | `/transform/inference` | Edge (no top-level request_id) | 200 | request handled with fallback id logic in pipeline |
| INF-05 | `/transform/inference` | Negative (unsupported source_system) | 400 | error contains `source_system must be one of ('xds',)` |
| INF-06 | `/transform/inference` | Negative (invalid xds_payload type) | 400 | error mentions `xds_payload` parse/type issue |
| BTH-01 | `/transform/inference/batch` | Happy path explicit request_id on all lines | 200 | `succeeded == total_lines`, `errors=[]` |
| BTH-02 | `/transform/inference/batch` | Happy path raw bureau lines (no request_id on any line) | 200 | success with derived ids (`inference-*`) |
| BTH-03 | `/transform/inference/batch` | Edge mixed valid+invalid lines | 200 | partial success; `errors` populated per bad line |
| BTH-04 | `/transform/inference/batch` | Negative mixed request_id style | 400 | error `JSONL request_id must be uniform` |
| BTH-05 | `/transform/inference/batch` | Negative missing query `data_source_id` | 400 | error `data_source_id is required` |
| BTH-06 | `/transform/inference/batch` | Negative empty body | 400 | error `Request body is empty` |
| BTH-07 | `/transform/inference/batch` | Negative too many lines | 400 | error `Too many lines` |
| BSM-01 | `/transform/inference/batch/submit` | Happy path inline delivery | 200 | `delivery_mode=inline`, `published_topic` set |
| BSM-02 | `/transform/inference/batch/submit` | Happy path blob-pointer delivery (above threshold) | 200 | `delivery_mode=blob_pointer`, blob path returned |
| BSM-03 | `/transform/inference/batch/submit` | Negative missing `job_id` query | 400 | error `job_id is required` |
| BSM-04 | `/transform/inference/batch/submit` | Negative duplicate request_id in same job | 400 | line-level duplicate request_id error |
| BSM-05 | `/transform/inference/batch/submit` | Negative feature key mismatch | 400 | line-level `features keys mismatch` error |
| BSM-06 | `/transform/inference/batch/submit` | Negative null feature value | 400 | line-level `features.<key> cannot be null` |
| BSM-07 | `/transform/inference/batch/submit` | Negative missing metadata.data_source_id/source_system | 400 | line-level metadata required error |

---

## Payloads

### INF-01: Single inference happy path (HIT)

```json
{
  "request_id": "inf-01-hit",
  "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
  "source_system": "xds",
  "models_to_run": ["risk"],
  "xds_payload": {
    "consumer_full_report_45": {
      "response": { "statusCode": 200 },
      "personalDetailsSummary": { "birthDate": "10/01/1996", "nationalIDNo": "GHA-ANON-001" },
      "highestDelinquencyRating": { "highestDelinquencyRating": "0" },
      "creditAccountSummary": {
        "totalOutstandingdebtGHS": "12000.00",
        "totalMonthlyInstalmentGHS": "700.00",
        "totalActiveAccountsGHS": "2",
        "totalNumberofAccountsGHS": "4",
        "totalClosedAccountsGHS": "2",
        "totalAccountInArrearGHS": "0",
        "totalAmountInArrearGHS": "0.00"
      },
      "creditAgreementSummary": [
        { "accountStatusCode": "C", "monthsInArrears": 0, "openingBalanceAmt": 1000 }
      ],
      "accountMonthlyPaymentHistory": [],
      "enquiryHistory": [],
      "judgementSummary": [],
      "defaults": [],
      "adverseDetails": []
    }
  },
  "applicant_context": {
    "loan_amount_requested": 15000,
    "loan_tenure_months": 12,
    "monthly_income": 4000,
    "identity_reference": "id-ref-inf-01"
  }
}
```

### INF-02: Single inference Product 49-first thin profile

```json
{
  "request_id": "inf-02-thin49",
  "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
  "source_system": "xds",
  "models_to_run": ["risk"],
  "xds_payload": {
    "consumer_mobile_report_49": {
      "response": { "statusCode": 200 },
      "detailedFacilityInfo": [{}, {}, {}],
      "creditAccountSummary": {
        "highestAmountTaken": "3000",
        "totalOutstandingdebt": "1200",
        "totalMonthlyInstalment": "250"
      }
    }
  },
  "applicant_context": {
    "loan_amount_requested": 2000,
    "loan_tenure_months": 6,
    "monthly_income": 1800,
    "identity_reference": "id-ref-inf-02"
  }
}
```

### INF-03: Missing applicant_context (valid edge)

```json
{
  "request_id": "inf-03-default-context",
  "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
  "source_system": "xds",
  "models_to_run": ["risk"],
  "xds_payload": {
    "consumer_full_report_45": {
      "response": { "statusCode": 200 },
      "personalDetailsSummary": { "birthDate": "15/06/1988" },
      "highestDelinquencyRating": { "highestDelinquencyRating": "1" },
      "creditAccountSummary": {
        "totalOutstandingdebtGHS": "8000.00",
        "totalMonthlyInstalmentGHS": "400.00",
        "totalActiveAccountsGHS": "1",
        "totalNumberofAccountsGHS": "3",
        "totalClosedAccountsGHS": "2",
        "totalAccountInArrearGHS": "0",
        "totalAmountInArrearGHS": "0.00"
      }
    }
  }
}
```

### INF-04: No top-level request_id (valid edge fallback)

```json
{
  "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
  "source_system": "xds",
  "models_to_run": ["risk"],
  "xds_payload": {
    "consumer_full_report_45": {
      "response": { "statusCode": 200 },
      "personalDetailsSummary": { "consumerID": "CID-INF-04", "birthDate": "1992-02-11" },
      "creditAccountSummary": { "totalOutstandingdebtGHS": "1000" }
    }
  }
}
```

### INF-05: Unsupported source_system (negative)

```json
{
  "request_id": "inf-05-bad-source",
  "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
  "source_system": "crb",
  "xds_payload": {
    "consumer_full_report_45": {
      "response": { "statusCode": 200 }
    }
  }
}
```

### INF-06: Invalid xds_payload type (negative)

```json
{
  "request_id": "inf-06-bad-xds-type",
  "data_source_id": "b4ed5120-65f4-46c5-b687-dc895a1d6bbf",
  "source_system": "xds",
  "xds_payload": "this should be an object, not a string"
}
```

---

### BTH-01: Batch JSONL happy path (all explicit request_id)

Query params: `?data_source_id=b4ed5120-65f4-46c5-b687-dc895a1d6bbf&source_system=xds&models_to_run=risk`

```jsonl
{"request_id":"bth-01-a","xds_payload":{"consumer_full_report_45":{"response":{"statusCode":200},"personalDetailsSummary":{"birthDate":"1988-06-15"},"creditAccountSummary":{"totalOutstandingdebtGHS":"8000.00"}}},"applicant_context":{"loan_amount_requested":5000,"loan_tenure_months":24,"monthly_income":2500,"identity_reference":"id-bth-01-a"}}
{"request_id":"bth-01-b","xds_payload":{"consumer_mobile_report_49":{"response":{"statusCode":200},"detailedFacilityInfo":[{},{}],"creditAccountSummary":{"highestAmountTaken":"2500"}}},"applicant_context":{"loan_amount_requested":2000,"loan_tenure_months":6,"monthly_income":1800,"identity_reference":"id-bth-01-b"}}
```

### BTH-02: Batch JSONL happy path (raw bureau lines, no request_id lines)

Query params: `?data_source_id=b4ed5120-65f4-46c5-b687-dc895a1d6bbf&source_system=xds`

```jsonl
{"consumer_full_report_45":{"response":{"statusCode":200},"personalDetailsSummary":{"consumerID":"CID-BTH-02-1"},"creditAccountSummary":{"totalOutstandingdebtGHS":"1400.00"}}}
{"consumer_mobile_report_49":{"response":{"statusCode":200},"subjectList":[{"uniqueID":"UID-BTH-02-2"}],"detailedFacilityInfo":[{}]}}
```

### BTH-03: Batch partial success (one malformed line)

Expected: HTTP 200 with one success and one entry in `errors`.

```jsonl
{"request_id":"bth-03-a","xds_payload":{"consumer_full_report_45":{"response":{"statusCode":200}}}}
not-a-json-object-line
```

### BTH-04: Batch invalid mixed request_id style

Expected: HTTP 400 (`JSONL request_id must be uniform`).

```jsonl
{"request_id":"bth-04-a","xds_payload":{"consumer_full_report_45":{"response":{"statusCode":200}}}}
{"consumer_full_report_45":{"response":{"statusCode":200},"personalDetailsSummary":{"consumerID":"CID-BTH-04-2"}}}
```

### BTH-05: Batch missing query param `data_source_id`

Use any valid JSONL body, but omit `data_source_id` query param.

### BTH-06: Batch empty body

Send zero-byte body with required query params.

### BTH-07: Batch too many lines

Send JSONL with lines greater than `INFERENCE_BATCH_MAX_LINES` (default 100).

---

### BSM-01: Batch submit happy path (inline mode)

Query params: `?job_id=bsm-01-inline&reprocess=true`

```jsonl
{"request_id":"bsm-01-a","features":{"highest_delinquency_rating":0.85,"months_on_time_24m":0.9,"worst_arrears_24m":1.0,"current_streak_on_time":0.9,"has_active_arrears":1.0,"total_arrear_amount_ghs":1.0,"total_outstanding_debt_ghs":0.8,"utilisation_ratio":0.8,"num_active_accounts":0.85,"total_monthly_instalment_ghs":0.7,"credit_age_months":0.7,"num_accounts_total":0.8,"num_closed_accounts_good":0.9,"product_diversity_score":0.8,"mobile_loan_history_count":0.6,"mobile_max_loan_ghs":0.7,"has_judgement":1.0,"has_written_off":1.0,"has_charged_off":1.0,"has_legal_handover":1.0,"num_bounced_cheques":1.0,"has_adverse_default":1.0,"num_enquiries_3m":0.9,"num_enquiries_12m":0.9,"enquiry_reason_flags":0.8,"applicant_age":0.7,"identity_verified":1.0,"num_dependants":0.8,"has_employer_detail":1.0,"address_stability":0.8},"metadata":{"data_source_id":"b4ed5120-65f4-46c5-b687-dc895a1d6bbf","source_system":"xds"}}
{"request_id":"bsm-01-b","features":{"highest_delinquency_rating":0.7,"months_on_time_24m":0.8,"worst_arrears_24m":0.9,"current_streak_on_time":0.8,"has_active_arrears":1.0,"total_arrear_amount_ghs":0.9,"total_outstanding_debt_ghs":0.75,"utilisation_ratio":0.7,"num_active_accounts":0.75,"total_monthly_instalment_ghs":0.65,"credit_age_months":0.6,"num_accounts_total":0.7,"num_closed_accounts_good":0.8,"product_diversity_score":0.75,"mobile_loan_history_count":0.5,"mobile_max_loan_ghs":0.6,"has_judgement":1.0,"has_written_off":1.0,"has_charged_off":1.0,"has_legal_handover":1.0,"num_bounced_cheques":1.0,"has_adverse_default":1.0,"num_enquiries_3m":0.8,"num_enquiries_12m":0.8,"enquiry_reason_flags":0.7,"applicant_age":0.65,"identity_verified":1.0,"num_dependants":0.7,"has_employer_detail":1.0,"address_stability":0.7},"metadata":{"data_source_id":"b4ed5120-65f4-46c5-b687-dc895a1d6bbf","source_system":"xds"}}
```

### BSM-02: Batch submit blob-pointer mode (above threshold)

- Same line shape as `BSM-01`, but send rows greater than `BATCH_SCORE_INLINE_THRESHOLD` (default 50).
- Query example: `?job_id=bsm-02-blob&reprocess=true`.
- Expected response contains `delivery_mode=blob_pointer`, `container`, `blob_path`.

### BSM-03: Batch submit missing job_id (negative)

Expected HTTP 400 with `job_id is required`.

### BSM-04: Batch submit duplicate request_id (negative)

```jsonl
{"request_id":"dup-id","features":{"highest_delinquency_rating":0.8,"months_on_time_24m":0.8,"worst_arrears_24m":0.8,"current_streak_on_time":0.8,"has_active_arrears":1.0,"total_arrear_amount_ghs":0.8,"total_outstanding_debt_ghs":0.8,"utilisation_ratio":0.8,"num_active_accounts":0.8,"total_monthly_instalment_ghs":0.8,"credit_age_months":0.8,"num_accounts_total":0.8,"num_closed_accounts_good":0.8,"product_diversity_score":0.8,"mobile_loan_history_count":0.8,"mobile_max_loan_ghs":0.8,"has_judgement":1.0,"has_written_off":1.0,"has_charged_off":1.0,"has_legal_handover":1.0,"num_bounced_cheques":1.0,"has_adverse_default":1.0,"num_enquiries_3m":0.8,"num_enquiries_12m":0.8,"enquiry_reason_flags":0.8,"applicant_age":0.8,"identity_verified":1.0,"num_dependants":0.8,"has_employer_detail":1.0,"address_stability":0.8},"metadata":{"data_source_id":"b4ed5120-65f4-46c5-b687-dc895a1d6bbf","source_system":"xds"}}
{"request_id":"dup-id","features":{"highest_delinquency_rating":0.7,"months_on_time_24m":0.7,"worst_arrears_24m":0.7,"current_streak_on_time":0.7,"has_active_arrears":1.0,"total_arrear_amount_ghs":0.7,"total_outstanding_debt_ghs":0.7,"utilisation_ratio":0.7,"num_active_accounts":0.7,"total_monthly_instalment_ghs":0.7,"credit_age_months":0.7,"num_accounts_total":0.7,"num_closed_accounts_good":0.7,"product_diversity_score":0.7,"mobile_loan_history_count":0.7,"mobile_max_loan_ghs":0.7,"has_judgement":1.0,"has_written_off":1.0,"has_charged_off":1.0,"has_legal_handover":1.0,"num_bounced_cheques":1.0,"has_adverse_default":1.0,"num_enquiries_3m":0.7,"num_enquiries_12m":0.7,"enquiry_reason_flags":0.7,"applicant_age":0.7,"identity_verified":1.0,"num_dependants":0.7,"has_employer_detail":1.0,"address_stability":0.7},"metadata":{"data_source_id":"b4ed5120-65f4-46c5-b687-dc895a1d6bbf","source_system":"xds"}}
```

### BSM-05: Batch submit features keys mismatch (negative)

```jsonl
{"request_id":"bsm-05-bad-keys","features":{"highest_delinquency_rating":0.8,"months_on_time_24m":0.8},"metadata":{"data_source_id":"b4ed5120-65f4-46c5-b687-dc895a1d6bbf","source_system":"xds"}}
```

### BSM-06: Batch submit null feature value (negative)

```jsonl
{"request_id":"bsm-06-null-feature","features":{"highest_delinquency_rating":null,"months_on_time_24m":0.8,"worst_arrears_24m":0.8,"current_streak_on_time":0.8,"has_active_arrears":1.0,"total_arrear_amount_ghs":0.8,"total_outstanding_debt_ghs":0.8,"utilisation_ratio":0.8,"num_active_accounts":0.8,"total_monthly_instalment_ghs":0.8,"credit_age_months":0.8,"num_accounts_total":0.8,"num_closed_accounts_good":0.8,"product_diversity_score":0.8,"mobile_loan_history_count":0.8,"mobile_max_loan_ghs":0.8,"has_judgement":1.0,"has_written_off":1.0,"has_charged_off":1.0,"has_legal_handover":1.0,"num_bounced_cheques":1.0,"has_adverse_default":1.0,"num_enquiries_3m":0.8,"num_enquiries_12m":0.8,"enquiry_reason_flags":0.8,"applicant_age":0.8,"identity_verified":1.0,"num_dependants":0.8,"has_employer_detail":1.0,"address_stability":0.8},"metadata":{"data_source_id":"b4ed5120-65f4-46c5-b687-dc895a1d6bbf","source_system":"xds"}}
```

### BSM-07: Batch submit missing metadata fields (negative)

```jsonl
{"request_id":"bsm-07-missing-meta","features":{"highest_delinquency_rating":0.8,"months_on_time_24m":0.8,"worst_arrears_24m":0.8,"current_streak_on_time":0.8,"has_active_arrears":1.0,"total_arrear_amount_ghs":0.8,"total_outstanding_debt_ghs":0.8,"utilisation_ratio":0.8,"num_active_accounts":0.8,"total_monthly_instalment_ghs":0.8,"credit_age_months":0.8,"num_accounts_total":0.8,"num_closed_accounts_good":0.8,"product_diversity_score":0.8,"mobile_loan_history_count":0.8,"mobile_max_loan_ghs":0.8,"has_judgement":1.0,"has_written_off":1.0,"has_charged_off":1.0,"has_legal_handover":1.0,"num_bounced_cheques":1.0,"has_adverse_default":1.0,"num_enquiries_3m":0.8,"num_enquiries_12m":0.8,"enquiry_reason_flags":0.8,"applicant_age":0.8,"identity_verified":1.0,"num_dependants":0.8,"has_employer_detail":1.0,"address_stability":0.8},"metadata":{"source_system":"xds"}}
```

---

## Recommended run order

1. `INF-01`, `INF-02`, `INF-03`
2. `BTH-01`, `BTH-02`, `BTH-03`
3. `BSM-01`
4. Negative suites (`INF-05..06`, `BTH-04..07`, `BSM-03..07`)
5. Optional load test: `BSM-02` with rows > threshold

