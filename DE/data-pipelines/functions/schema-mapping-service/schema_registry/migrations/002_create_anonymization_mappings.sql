-- Migration 002: Create anonymization_mappings table
-- Stores PII anonymization mappings with versioning

CREATE TABLE IF NOT EXISTS schema_registry.anonymization_mappings (
    id VARCHAR(36) PRIMARY KEY,
    bank_id VARCHAR(100) NOT NULL,
    schema_hash VARCHAR(64) NOT NULL,
    mapping_version VARCHAR(20) NOT NULL,
    mini_version INTEGER NOT NULL DEFAULT 0,
    anonymization_methods JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_anonymization_bank_hash 
    ON schema_registry.anonymization_mappings(bank_id, schema_hash);

CREATE INDEX IF NOT EXISTS idx_anonymization_bank 
    ON schema_registry.anonymization_mappings(bank_id);

CREATE INDEX IF NOT EXISTS idx_anonymization_hash 
    ON schema_registry.anonymization_mappings(schema_hash);

-- Comments
COMMENT ON TABLE schema_registry.anonymization_mappings IS 'Stores PII anonymization mappings with versioning support';
COMMENT ON COLUMN schema_registry.anonymization_mappings.schema_hash IS 'SHA-256 hash of column names and types';
COMMENT ON COLUMN schema_registry.anonymization_mappings.mapping_version IS 'Major version (e.g., "1.0", "2.0")';
COMMENT ON COLUMN schema_registry.anonymization_mappings.mini_version IS 'Minor version for slight changes (incremented)';
COMMENT ON COLUMN schema_registry.anonymization_mappings.anonymization_methods IS 'JSON mapping: column_name -> method ("hash", "tokenize", "generalize")';
