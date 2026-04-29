# Service Bus Subscription Rules (Prod)

## Topic: data-awaits-ingestion
- `adf-trigger-subscription` -> `ADFProcessingSystemFilter`: `processing_system = 'ADF'`
- `temp-peek-subscription` -> `CheckTrainingUploadID`: `processing_system = 'ADF'`

## Topic: data-ingested
- `quality_report` -> `quality_report_filter`: `run_id IS NOT NULL AND subscription = 'quality_report'`
- `start-transformation` -> `RunIDCheck`:
  - `subscription = 'start-transformation'`
  - `AND run_id IS NOT NULL`
  - `AND training_upload_id IS NOT NULL`
  - `AND bank_id IS NOT NULL`
  - `AND bronze_blob_path IS NOT NULL`
  - `AND (status IS NULL OR status <> 'ERROR')`
- `transformed` -> `transformed_filter`:
  - `subscription = 'transformed'`
  - `AND status = 'TRANSFORMED'`
  - `AND run_id IS NOT NULL`
  - `AND transformed_file_path IS NOT NULL`

## Topic: schema-mapping-service
- `analysis-complete` -> `analysis_filter`: `run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'analysis-complete'`
- `anonymization-complete` -> `anonymization_filter`: `run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'anonymization-complete'`
- `failed` -> `failed_filter`: `run_id IS NOT NULL AND subscription = 'failed'`
- `introspection-complete` -> `introspection_filter`: `run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'introspection-complete'`
- `mapping-complete` -> `mapping_complete_filter`: `status = 'MAPPING_COMPLETE' AND subscription = 'mapping-complete'`
- `sampling-complete` -> `sampling_filter`: `run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'sampling-complete'`
- `schema-detected` -> `schema_detected_filter`: `run_id IS NOT NULL AND training_upload_id IS NOT NULL AND subscription = 'schema-detected'`
