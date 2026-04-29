-- Migration 004: Create data_analysis_results table
-- Stores cached data analysis results

CREATE TABLE IF NOT EXISTS schema_registry.data_analysis_results (
    id VARCHAR(36) PRIMARY KEY,
    bank_id VARCHAR(100) NOT NULL,
    schema_hash VARCHAR(64) NOT NULL,
    result_json JSONB NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_data_analysis_bank_hash 
    ON schema_registry.data_analysis_results(bank_id, schema_hash);

CREATE INDEX IF NOT EXISTS idx_data_analysis_bank 
    ON schema_registry.data_analysis_results(bank_id);

CREATE INDEX IF NOT EXISTS idx_data_analysis_hash 
    ON schema_registry.data_analysis_results(schema_hash);

-- Comments
COMMENT ON TABLE schema_registry.data_analysis_results IS 'Cached data analysis results for artifact reuse';
COMMENT ON COLUMN schema_registry.data_analysis_results.schema_hash IS 'SHA-256 hash of column names and types';
COMMENT ON COLUMN schema_registry.data_analysis_results.result_json IS 'Serialized DataAnalysisResult (JSON)';
