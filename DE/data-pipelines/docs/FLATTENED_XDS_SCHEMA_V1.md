# flattened_xds_schema_v1

## Purpose

Defines the strict flattened schema for JSON/JSONL XDS inputs before anonymization.

## Silver storage contract (training)

- Silver training parquet must contain **only** flat anonymized columns aligned with this schema (plus any agreed non-nested metadata). Do **not** persist a nested `xds_payload` blob column for training rows.
- If a legacy `xds_payload` column exists with **non-null** values, the transformation service **fails the batch** so bad data is not silently mixed with flat rows. An all-null / NaN-only `xds_payload` column (e.g. schema drift from old pipelines) is ignored.
- In-memory, the transformation service may wrap a flat row as `TransformRequest.xds_payload["__flat_row__"]` for parser compatibility; that wrapper is **not** a silver column.

## When applied

- Apply only when source format is `json` or `jsonl`.
- Do not apply to `csv`, `tsv`, `excel`, `parquet`, or `txt` sources.

## Rules

1. One row per applicant.
2. Nested arrays must be reduced to a single record using latest-by-date selection.
3. Flatten nested object keys into dot-notation columns.
4. Fail fast if required columns are missing (see OR rule below).

## Required columns (OR rule)

A row is valid if **either**:

**A. Product 45 path** — `consumer_full_report_45.response.statusCode` is `200` **and** these agreement fields are present (non-empty):

- `consumer_full_report_45.response.statusCode`
- `consumer_full_report_45.creditAgreementSummary.accountStatusCode`
- `consumer_full_report_45.creditAgreementSummary.monthsInArrears`
- `consumer_full_report_45.creditAgreementSummary.openingBalanceAmt`

**B. Product 49 path** — `consumer_mobile_report_49.response.statusCode` is `200` (no requirement for `detailedFacilityInfo` scalars when the consumer has no mobile facilities).

If **neither** path is satisfied, validation fails.

## Date precedence for latest selection

Use the first parseable date from:

1. `dateRequested`
2. `dateAccountOpened`
3. `closedDate`
4. `updatedAt`
5. `createdAt`

If no parseable dates are present in an array, use the last array element as fallback.

