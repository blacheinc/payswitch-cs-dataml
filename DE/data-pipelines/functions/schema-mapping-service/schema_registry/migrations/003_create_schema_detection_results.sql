-- Migration 003: Create schema_detection_results table
-- Stores cached schema detection results

CREATE TABLE IF NOT EXISTS schema_registry.schema_detection_results (
    id VARCHAR(36) PRIMARY KEY,
    bank_id VARCHAR(100) NOT NULL,
    schema_hash VARCHAR(64) NOT NULL,
    result_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_schema_detection_bank_hash 
    ON schema_registry.schema_detection_results(bank_id, schema_hash);

CREATE INDEX IF NOT EXISTS idx_schema_detection_bank 
    ON schema_registry.schema_detection_results(bank_id);

CREATE INDEX IF NOT EXISTS idx_schema_detection_hash 
    ON schema_registry.schema_detection_results(schema_hash);

-- Comments
COMMENT ON TABLE schema_registry.schema_detection_results IS 'Cached schema detection results for artifact reuse';
COMMENT ON COLUMN schema_registry.schema_detection_results.schema_hash IS 'SHA-256 hash of column names and types';
COMMENT ON COLUMN schema_registry.schema_detection_results.result_json IS 'Serialized SchemaDetectionResult (JSON)';
