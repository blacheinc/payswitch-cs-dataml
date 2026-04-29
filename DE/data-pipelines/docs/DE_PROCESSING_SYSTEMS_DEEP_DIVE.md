# Data Engineering — Data Cleaning, Processing & Analysis (Deep Dive)

This document explains **what the DE system is designed to do**, in **maximum practical detail**, grounded in the current `data-pipelines/functions` implementation. It complements [DE_ARCHITECTURE_DIAGRAMS.md](./DE_ARCHITECTURE_DIAGRAMS.md).

**Scope**

- **Training path**: raw file → bronze (ADF / ingestion) → **Systems 0–4** (schema-mapping) → **deterministic transformation** (gold + Service Bus) → ML handoff.
- **Inference path**: HTTP (or JSONL batch) → **same deterministic transformation core** (without training targets in external inference contract) → Service Bus + optional ML HTTP.

Out of scope for line-by-line detail: ML model training code, credit-scoring `phase3` agents, unless they consume the SB topics produced here.

---

## Part A — Design goals (why this exists)

1. **Ingest credit-bureau-style (XDS) training files** safely: validate uploads, copy to **ADLS Gen2 bronze**, verify integrity, track status in **PostgreSQL**, and emit events.
2. **Profile and anonymize** training rows before general ML use: cheap **file introspection**, **schema detection**, **sampling**, **statistical / pattern analysis**, then **PII detection + anonymization** with optional **LLM-assisted** detection when Key Vault / Azure OpenAI secrets are available.
3. **Flatten nested XDS JSON** into a **strict column contract** (`flattened_xds_schema_v1`) so downstream code never re-parses arbitrary nested trees row-by-row in the hot ML path.
4. **Run one deterministic “credit decision prep” transformation** on each logical consumer: parse Product **45** / **49**, engineer **fixed-name features**, evaluate **hard stops**, run **rule engine**, attach **metadata + diagnostics**, write **Parquet** artifacts for training, and publish **canonical Service Bus messages** for orchestrators and ML.
5. **Serve real-time inference** with the **same transformation semantics** as training (minus persistence of targets to external consumers), including a **hard-stop fallback** publish to `scoring-complete` when rules short-circuit scoring.

---

## Part B — Storage layout and artifacts

### B.1 ADLS Gen2 filesystems (typical)

| Layer | Filesystem / container | Written by | Contents |
|-------|------------------------|------------|----------|
| Bronze | `bronze` | ADF / ingestion | Raw training file as uploaded (CSV/JSON/JSONL/… per pipeline). Path pattern includes `training/{bank_id}/{date}/{training_upload_id}.ext` (see ADF design doc). |
| Silver | `silver` | Schema-mapping orchestrator | **Anonymized** training sample as **Parquet**: `training/{bank_id}/{date}/{training_upload_id}/{run_id}/{training_upload_id}.parquet`. |
| Silver sidecar | `silver` | Same | **`systems04_context.json`** next to parquet: JSON aggregation of Systems 0–3 outputs + PII metadata for audit / ML context. |
| Gold / curated | `curated` (env: `GOLD_CONTAINER_NAME`) | Transformation service | Training **features** (+ targets) Parquet under prefix `GOLD_OUTPUT_PREFIX` (default `gold/training` in examples; your `local.settings` may use `ml-training`). **Batch path** writes separate **features** and **metadata** Parquet objects. |

### B.2 PostgreSQL (conceptual tables touched by DE functions)

- **`training_uploads`** (and related): statuses such as `ingesting`, `ingested`, `transforming`, `transformed`, … (see `TrainingUploadStatus` in `run_training_ingestion.py`).
- **`bronze_ingestion_log`**: per-run checksum / size / path / error reason.
- **Schema registry** tables (via `schema_registry/*_store.py`): cached **schema detection**, **data analysis**, **anonymization mappings** (PostgreSQL authoritative; Redis optional cache when `SCHEMA_REGISTRY_ENABLE_REDIS=1`).

---

## Part C — Training pipeline (step-by-step)

### C.0 Entry: upload and “data awaits ingestion”

1. **Client** (or internal tool) uploads a training file through **`services/training-data-upload`** (FastAPI): validates extension/size, stores blob under a **raw** path, inserts metadata in PostgreSQL, publishes a message to **`data-awaits-ingestion`** (see `ARCHITECTURE.md`).
2. Message payload is expected to carry identifiers the downstream **ADF** or **ingestion Function** uses: e.g. `training_upload_id`, `data_source_id` / `bank_id`, paths, etc. (exact JSON varies by producer; ingestion code is defensive).

### C.1 Path 1 — ADF pipeline (`adf-pipeline-trigger` + Data Factory)

1. **Service Bus trigger** on **`data-awaits-ingestion`** / subscription **`adf-trigger-subscription`** invokes `adf_pipeline_trigger` (`adf-pipeline-trigger/function_app.py`).
2. Validates **`KEY_VAULT_URL`** and ADF settings: `ADF_SUBSCRIPTION_ID`, `ADF_RESOURCE_GROUP`, `ADF_FACTORY_NAME`, `ADF_PIPELINE_NAME` (default pipeline name in local example: `pipeline-training-data-ingestion`).
3. **`trigger_adf_pipeline_from_message`** (`scripts/trigger_adf_pipeline.py`):
   - Builds **DataFactoryManagementClient** with `AzureCliCredential` locally or `DefaultAzureCredential` in Azure.
   - Reads **Key Vault** secrets: `ServiceBusNamespace`, `FileChecksumCalculatorFunctionBaseUrl`, `FileChecksumCalculatorFunctionKey`.
   - Constructs ADF pipeline parameters (upload id, checksum URL + key, etc.—see script body for the REST create-run call).
4. **ADF** runs activities described in `DATA_FACTORY_PIPELINE_DESIGN.md`: **lookup** upload metadata in PostgreSQL, **copy** blob → **ADLS bronze** path, **get metadata** (size / row count where applicable), **invoke checksum Function** over HTTP using the function key from Key Vault, compare checksums and sizes to expected, branch success/failure.
5. **Success** path typically publishes to **`data-ingested`** (and updates PostgreSQL bronze path + statuses). **Failure** publishes to failure topics / sets error state (see pipeline JSON and training-ingestion docs).

### C.2 Path 2 — `training-data-ingestion` Function (per-message)

1. **Service Bus trigger** on **`data-awaits-ingestion`** / **`temp-peek-subscription`** (`training-data-ingestion/function_app.py`).
2. Lazy-imports **`run_single_message_from_function`** from `scripts/run_training_ingestion.py` so **import-time** does not require secrets during host indexing.
3. **Runtime guard**: `KEY_VAULT_URL` must be set; otherwise the handler logs and returns (message completed without work—by design to avoid poison loops; verify this matches your operational expectation).
4. **`run_single_message_from_function`** (simplified narrative; see code for every branch):
   - Parses JSON body → expects `training_upload_id`, etc.
   - Ensures DB row exists with status **`ingesting`**; otherwise may no-op.
   - Uses **`TrainingKeyVaultReader`** / env to resolve **blob**, **ADLS**, **Service Bus**, **PostgreSQL** connection information (`_get_env_or_kv` pattern supports unresolved `@Microsoft.KeyVault(...)` placeholders by re-fetching via SDK).
   - **Checksum** source blob in raw storage; **copy** stream to bronze path; **re-checksum** bronze; verify size; insert **`bronze_ingestion_log`** row; update **`training_uploads`**; publish success to **`data-ingested`** using **`TrainingServiceBusWriter`**.
5. **Concurrency / locking**: Service Bus session semantics and `AutoLockRenewer` appear in batch orchestration paths in the same module family (see full `run_training_ingestion.py` for batch mode vs single-message mode).

### C.3 Schema-mapping service — Systems 0–4 (`schema-mapping-service`)

**Trigger**: `data-ingested` / `start-transformation` (`function_app.py`).

**Pre-filtering (critical)**:

- Skips messages with `status == "ERROR"` or containing `error_report`.
- **`_is_schema_mapping_trigger`**: rejects payloads that look like **post-transformation** notifications (`transformed_file_path`, `features_mapped`, `quality_report` keys).
- Requires **`bronze_blob_path`**, **`bank_id` or `data_source_id`**, **`training_upload_id` or `upload_id`** — prevents accidental invocation from unrelated publishers on the same topic.

**Orchestrator** (`orchestrator.py` → `SchemaMappingOrchestrator.run_pipeline`):

1. **`_validate_message`**: uses **`parse_data_ingested_message`** (`utils/service_bus_parser.py`) to normalize keys (`training_upload_id`, `bank_id`, `bronze_blob_path`, `run_id`, `date`, `source_system`, optional `applicant_context`, …). **Fails fast** with `ServiceBusMessageError` if contract not met.
2. **Requires `run_id`**: mapping-complete handoff to transformation is keyed by this run.
3. **Data Lake client**:
   - If `DATALAKE_STORAGE_CONNECTION_STRING` env is set → `DataLakeServiceClient.from_connection_string` (local / key-based dev).
   - Else → reads **`DataLakeStorageAccountName`** secret from Key Vault and uses **`DefaultAzureCredential`** against `https://{account}.dfs.core.windows.net` (production-style RBAC).
4. **System 0 — `FileIntrospector.introspect_file`** (`systems/file_introspector.py`):
   - **Cheap probes** on bronze file: existence, size, **magic bytes** (ZIP/GZIP/BZ2/TAR/XZ heuristics), **BOM** for UTF variants, **charset_normalizer** on a small byte window for encoding confidence, archive member sniffing where relevant.
   - Publishes **internal progress** / status via `ServiceBusWriter` when configured (see writer calls inside the class).
   - Returns a **`FileIntrospectionResult`**-compatible structure (dict-serialized into `systems04_context.json` later).
5. **System 1 — `SchemaDetector`** (`systems/schema_detector.py`):
   - **`detect_format`**: chooses among csv/tsv/json/jsonl/xlsx/… using introspection + heuristics; tracks **conflict** and **fallback** flags when multiple signals disagree.
   - **`detect_schema`**: column names, inferred dtypes, confidence, encoding, delimiter, header flags, etc.; persists via **`SchemaDetectionStore`** (Postgres + optional Redis cache).
6. **System 2 — `DataSampler.load_and_sample_from_datalake`** (`systems/data_sampler.py`):
   - Reads bronze through Data Lake file client using detected format/encoding.
   - Produces **one or more pandas `DataFrame` samples** (row windows) used by analysis + anonymization (not necessarily the full file if large—tune inside class).
7. **System 3 — `DataAnalyzer.analyze`** (`systems/data_analyzer.py`):
   - Computes descriptive stats: **missingness per column**, **data type** guesses, **numeric summaries**, **text pattern** frequencies, **date format** inference via `DateFormatDetector`, outlier-style signals using **z-score threshold** constant `Z_SCORE_THRESHOLD = 1.96`, etc.
   - Persists compact analysis via **`DataAnalysisStore`** (Postgres + optional Redis).
   - Emits `DataAnalysisResult` used by PII detection context and quality aggregation.
8. **System 4 — `DatasetAnonymizer`** (`systems/dataset_anonymizer.py` + helpers):
   - **`set_system_results`**: stitches introspection, schema, sampling, analysis, and parsed message for **quality report** publishing.
   - **`detect_pii`**:
     - Primary path may call **`create_llm_pii_detector_with_full_context`** when `use_llm=True` and `key_vault_url` set (`systems/llm_pii_detector.py`): loads Azure OpenAI credentials from Key Vault (`DefaultAzureCredential` chain differs for `ENVIRONMENT` local vs Azure worker detection via `WEBSITE_INSTANCE_ID`).
     - Fallback / supplement: **rule `PIIDetector`** (`systems/pii_detector.py`) for schema-aligned regex / column-name heuristics.
     - Output: `PIIDetectionResult` with categorized columns (names, emails, phones, ids, addresses, other).
   - **JSON / JSONL special phase** (`orchestrator.run_pipeline`):
     - If detected format ∈ `{json, jsonl}`, the orchestrator **replaces** the sample `DataFrame` with **`_flatten_xds_json_rows`**: expands nested dicts into **dotted column names**; for list-of-dicts fields picks **latest-by-date** heuristic (`_latest_by_date` helper) to mimic “newest tradeline / enquiry” style semantics.
     - Immediately validates **`_validate_flattened_xds_schema_v1`**: requires Product **45** “agreement quartet” columns when building training silver from bureau JSON:
       - `consumer_full_report_45.response.statusCode`
       - `consumer_full_report_45.creditAgreementSummary.accountStatusCode`
       - `consumer_full_report_45.creditAgreementSummary.monthsInArrears`
       - `consumer_full_report_45.creditAgreementSummary.openingBalanceAmt`
   - **`anonymize_dataframe`**: uses `PIIAnonymizer` with per-field methods guided by `PIIDetectionResult`; default hash-style fallback method in orchestrator call; consults **`AnonymizationMappingStore`** for bank/schema-hash-specific method maps (Postgres + optional Redis).
   - **Quality reporting**: `aggregate_quality_report` merges signals from all systems and may publish structured quality events via Service Bus writer (see `utils/quality_report_aggregator.py` usage in class).
9. **Silver write**:
   - Builds **`silver_path`**: `training/{bank_id}/{date}/{training_upload_id}/{run_id}/{training_upload_id}.parquet`.
   - Writes **Parquet bytes** with pyarrow engine.
10. **`systems04_context.json`**:
    - Path: `training/{bank_id}/{date}/{training_upload_id}/{run_id}/systems04_context.json`.
    - JSON includes: `run_id`, `training_upload_id`, `bank_id`, `pipeline_timestamp`, `anonymized_silver_path`, `bronze_source_path`, embedded introspection/schema/analysis/PII structures via `_to_jsonable`.
11. **Service Bus — mapping complete handoff**:
    - **Does not** publish backend **`TRANSFORMED`** status here (by explicit design comment): transformed status belongs to **final deterministic** transformation output.
    - Calls **`publish_mapping_complete_handoff`** on `ServiceBusWriter` with:
       - `anonymized_silver_path`, `analysis_context_path`, `request_id`, `run_id`, `source_system`, `flow_type="training"`, `applicant_context`, and a rich **`systems04_summary`** block (column counts, PII counts, flattening flags, schema template hints, etc.).

**Error handling**:

- Any exception maps to a **system name** (System 0–4) and calls **`_handle_error`**: publishes **internal failure** + **backend-friendly error** topics via `ServiceBusWriter` using `map_error_to_user_message`, then **re-raises** to allow Functions runtime retry policy (`host.json` retry section).

### C.4 Transformation service — training from silver (`transformation-service`)

**Service Bus trigger**: topic **`schema-mapping-service`**, subscription **`mapping-complete`** (`transformation_trigger`).

**Payload validation** (`_validate_mapping_complete_payload`):

- Requires `request_id` (defaults from `training_upload_id` if absent), `training_upload_id`, `anonymized_silver_path`, `analysis_context_path`.

**Execution** (`_transform_training_batch_from_silver`):

1. **Load sidecar JSON** from `analysis_context_path` via `silver_loader.load_silver_json` — must contain `run_id`, `training_upload_id`, `anonymized_silver_path`.
2. **Load silver Parquet** (`load_silver_parquet`) to `DataFrame`, iterate **each row** as a training consumer.
3. **Guards**:
   - Rejects rows that still carry a non-null **`xds_payload`** column (legacy shape) — forces flattened-only contract.
   - **`_validate_flat_row_schema_v1`** per row index (same Product 45 / 49 rules as inference).
4. For each row, builds a **`TransformRequest`** dict:
   - `flow_type="training"`, `request_id` unique per row, `data_source_id` / `bank_id`, `source_system`, `xds_payload={"__flat_row__": row}`, `run_id`, `training_upload_id`.
5. **`TransformationOrchestrator.run`** (`orchestrator.py`):
   - **`detect_hit_status`**: parser determines bureau hit / thin-file style flags.
   - **`parse`**: `XdsParser` with **`Product45Parser`**, **`Product49Parser`** extracts normalized structures + thin-file paths.
   - **`DeterministicFeatureBuilder.build`**: emits **fixed feature dict** + diagnostics (missing list, coverage ratio, product flags, thin-file flag, etc.).
   - **`_validate_feature_contract`**: ensures dict keys exactly match `FEATURE_NAMES` — prevents silent drift between training and inference.
   - **`HardStopEvaluator.evaluate`**: merges engineered features with **`applicant_age_years`** + **`debt_service_ratio_est`** for rule thresholds.
   - **`DeterministicRuleEngine.decide`**: produces **`decision_package`** with required keys validated by `_validate_decision_package`.
   - **`System04QualityAdapter.get_score`**: injects **`data_quality_score`** into decision package (adapter name reflects lineage to System 04 signals; implementation in `quality_provider.py`).
   - **`_build_targets`** / **`_build_metadata`**: training targets from extracted performance fields + rich metadata block (scores, grades, product mix, etc.).
6. **Batch write** (`write_training_batch_parquets`): two Parquet outputs (features+targets vs metadata/diagnostics per-row alignment) uploaded using `GOLD_STORAGE_CONNECTION_STRING` + `GOLD_CONTAINER_NAME` + `GOLD_OUTPUT_PREFIX`.
7. **Publishing** (`output_delivery.py`):
   - **`publish_backend_event`**: full JSON payload to `TRANSFORM_OUTPUT_TOPIC` (default `data-ingested`) with application properties marking pipeline output unless disabled by env `TRANSFORM_DISABLE_BACKEND_EVENT`.
   - **`publish_ml_messages`**:
     - For `flow_type=="training"` → **`training-data-ready`** topic (default) with data location container/blob path, record counts, dataset version, product distribution, models_to_train list.
   - **`publish_transformed_training_complete`**: synthetic **`TRANSFORMED`** status message compatible with schema-mapping subscription filters (uses `transformed_file_path`, `features_mapped`, `schema_template_id`, session id = `training_upload_id`, etc.) unless `TRANSFORM_DISABLE_PUBLISH_TRANSFORMED`.

**HTTP training route** (`POST /api/transform/training`):

- Wraps **`_transform_payload`** for a single JSON training payload (legacy “full JSON XDS” path still supported there via `TransformRequest.from_dict`), including **gold parquet** write for single-row training flows when env configured.

---

## Part D — Inference pipeline (step-by-step)

### D.1 HTTP single inference — `POST /api/transform/inference`

1. **Auth**: Azure Functions **function key** level.
2. **`_ensure_inference_publish_config`**: On deployed workers (`WEBSITE_INSTANCE_ID` present), **requires** `TRANSFORM_OUTPUT_SERVICE_BUS_CONNECTION_STRING` and `INFERENCE_REQUEST_TOPIC` so the function cannot return HTTP 200 while silently failing to notify ML.
3. **`_run_inference_pipeline`**:
   - Sets **`INFERENCE_SKIP_REDIS="1"`** for the duration of the call so schema-registry Redis + KV reads for Redis are skipped even if other routes enable Redis.
   - Parses `xds_payload` JSON, runs **`normalize_nested_xds_payload`** (`xds_payload_normalize.py`) to coerce shapes consistent with bureau quirks.
   - **`_flatten_xds_payload`**: depth-first flattening; for lists of dicts chooses **latest** element by scanning date-like fields (`dateRequested`, `dateAccountOpened`, …) — mirrors training flattening intent for nested arrays.
   - Validates **flat row** contract via **`_validate_flat_row_schema_v1`** at index 0:
     - If Product **45** `statusCode == 200` → requires the **four** agreement-related columns populated.
     - Else if Product **49** `statusCode == 200` → passes without the 45 agreement columns.
     - Else → **rejects** row (neither a hit nor acceptable thin mobile hit).
   - Builds a one-row **`DataFrame`**, calls **`anonymize_inference_dataframe`** (`inference_anonymize.py`):
     - Uses bundled schema-mapping **`DatasetAnonymizer`** when imports available; may use **`KEY_VAULT_URL`** for LLM parity; otherwise falls back to rules.
   - **`_restore_required_flat_45_fields_after_anonymize`**: if anonymizer blanks dotted columns, **copy originals** back for the four contract columns when 45 was a 200 hit (keeps ML contract stable).
   - Re-validates flat row after restore.
   - Builds **`TransformRequest`** with `flow_type="inference"` and `xds_payload={"__flat_row__": anonymized_row}`.
   - Calls **`_transform_payload(..., publish_outputs=False)`** to reuse orchestrator + gold-writer logic internally but **suppresses training publishes** inside that helper.
   - **Removes `targets`** key from result for inference consumers.
   - **Parallel external I/O** (`ThreadPoolExecutor` up to 3 workers if ML HTTP enabled):
     - Optional **`requests.post` multipart** file field `file` with tiny Parquet of engineered features to `ML_ENGINEER_HTTP_ENDPOINT`.
     - **`publish_backend_event(result)`** (unless globally disabled).
     - **`publish_ml_messages(result)`** → publishes **`inference-request`** topic message built by **`build_inference_request_message_body`** (features + selected metadata + models_to_run list).
     - **`publish_scoring_complete_hard_stop(result)`** → only if `decision_package.hard_stop_triggered` is true; builds null-model-shaped **`build_scoring_complete_hard_stop_body`** envelope.
   - **`finally`**: restores previous `INFERENCE_SKIP_REDIS` env var.

### D.2 HTTP batch inference — `POST /api/transform/inference/batch`

1. **Query params**: **`data_source_id` required**; `source_system` defaults `xds`; **`models_to_run`** optional (comma-separated list or JSON array string).
2. Body: **UTF-8 JSONL** — one JSON object per non-empty line.
3. **Line limit**: `INFERENCE_BATCH_MAX_LINES` env (default 100, clamped to `[1, 10000]`).
4. Each line:
   - Accepts either nested `xds_payload` object or top-level `consumer_full_report_45` / `consumer_mobile_report_49` or raw inner bureau JSON (see `_xds_payload_from_jsonl_object`).
5. **`_validate_jsonl_request_id_uniform`**: forbids mixing lines with explicit `request_id` and lines without — prevents ambiguous correlation for downstream systems.
6. **`_request_id_from_jsonl_object`**: prefers explicit `request_id`; else derives `inference-{consumerID}` / `inference-{uniqueID}` heuristics from nested personal details / subject list; else random suffix.
7. Per-line errors captured in **`errors`** array without failing entire batch unless parse-level failures accumulate separately.

---

## Part E — Cross-cutting “cleaning & analysis” concepts

### E.1 What “cleaning” means in this codebase

- **Physical / transport cleaning**: checksum verification, size checks, correct copy to bronze, logging to `bronze_ingestion_log`.
- **Schema cleaning**: delimiter/header detection, encoding fixes, dtype inference, JSON flattening, column naming normalization.
- **PII cleaning**: detection + anonymization/masking; optional LLM classification; restoration of **non-PII contract columns** after anonymization for inference parity.
- **ML contract cleaning**: strict feature-name sets, hard-stop short-circuit, removal of targets from inference publishes, deterministic metadata fields for orchestration.

### E.2 What “analysis” means

- **System 3 numeric/text/date** analysis feeding **LLM PII** context and **quality** scores.
- **Diagnostics** from **`DeterministicFeatureBuilder`**: missing feature list, coverage ratio, product availability flags, thin-file flag, etc., surfaced in `TransformDiagnostics` and metadata.

### E.3 Service Bus contracts (transformation output)

Refer to **`output_delivery.py`** functions for exact JSON shapes; highlights:

- **`publish_backend_event`**: subject `transformation_pipeline_output`, properties include `flow_type`, `source_system`, `contract_version`.
- **`publish_ml_messages` training**: `training_data_ready` message_type with `data_location.container` + `blob_path`.
- **`publish_ml_messages` inference**: `inference_request` message_type; session id derived from `request_id` unless disabled.
- **`publish_transformed_training_complete`**: mimics schema-mapping **transformed** subscription contract with `features_mapped` summary from `DeterministicFeatureBuilder.FEATURE_NAMES` presence count.

---

## Part F — Developer / ops entry points (non-Production)

| Script / entry | Purpose |
|----------------|---------|
| `schema-mapping-service/scripts/run_pipeline_from_service_bus.py` | Pulls messages from a subscription and runs the same orchestrator with rich CLI logging; requires extensive env (see `REQUIRED_ENV_VARS` in file). |
| `transformation-service/sb_receive_inference.py` | Utility receiver for inference topic debugging. |
| `training-data-ingestion/scripts/run_training_ingestion.py` | Batch/local ingestion driver with Key Vault integration. |

---

## Part G — Logging noise controls (recent)

- Function **`host.json`**: default **Warning**, `Host.Results` **Information**, Azure SDK categories **Warning**.
- Python **`logging.basicConfig(level=WARNING)`** in each `function_app.py` to suppress INFO-level chatter unless a module explicitly lowers the logger level.
- Schema-mapping / ADF / training function entry logs demoted or reduced to **one WARNING line per invocation** for success path summaries.

To temporarily re-enable verbose troubleshooting in Azure, set **`LOG_LEVEL=INFO`** (where honored) or adjust `host.json` / specific logger levels.

---

## Part H — Glossary (abbreviations used in logs and payloads)

| Term | Meaning |
|------|---------|
| XDS | Credit-bureau XML/JSON-style payload family consumed via parsers into internal dicts. |
| P45 / P49 | Product 45 (full consumer) vs Product 49 (mobile thin) parser branches. |
| `flattened_xds_schema_v1` | The strict flattened-column training/inference contract after JSON flatten + validation. |
| Hard stop | Rule engine short-circuit producing immediate decline-style decision without ML score. |
| `systems04_context.json` | Sidecar capturing Systems 0–4 outputs for traceability and downstream feature context. |

---

If you want this document split into **per-system PDF chapters** or a **single Lucidchart** export, say which audience (ops vs ML vs auditors) should be emphasized and we can reshape sections without changing the underlying pipeline facts.
