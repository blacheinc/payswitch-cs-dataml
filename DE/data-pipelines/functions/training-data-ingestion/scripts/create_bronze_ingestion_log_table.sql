-- Create bronze_ingestion_log table for tracking file ingestion to bronze layer
-- This table provides detailed audit trail and tracking for Data Engineers

CREATE TABLE IF NOT EXISTS bronze_ingestion_log (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key to training_uploads table
    training_upload_id UUID NOT NULL REFERENCES training_uploads(id) ON DELETE CASCADE,
    
    -- Run ID for tracking the exact ingestion run
    run_id UUID NOT NULL,
    
    -- Source file information (from data container)
    source_blob_path TEXT NOT NULL,
    source_checksum_sha256 TEXT NOT NULL,
    source_file_size_bytes BIGINT NOT NULL,
    
    -- Bronze layer file information (destination)
    bronze_blob_path TEXT NOT NULL,
    bronze_checksum_sha256 TEXT NOT NULL,
    bronze_file_size_bytes BIGINT NOT NULL,
    
    -- Ingestion status
    ingestion_status TEXT NOT NULL CHECK (ingestion_status IN ('success', 'file_not_found', 'copy_failed', 'verification_failed')),
    
    -- Error details (if any)
    error_message TEXT,
    
    -- Timestamps
    ingested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_bronze_log_training_upload_id ON bronze_ingestion_log(training_upload_id);
CREATE INDEX IF NOT EXISTS idx_bronze_log_run_id ON bronze_ingestion_log(run_id);
CREATE INDEX IF NOT EXISTS idx_bronze_log_status ON bronze_ingestion_log(ingestion_status);
CREATE INDEX IF NOT EXISTS idx_bronze_log_ingested_at ON bronze_ingestion_log(ingested_at);

-- Add comment to table
COMMENT ON TABLE bronze_ingestion_log IS 'Audit log for training data file ingestion to bronze layer. Tracks source and destination file details, checksums, and ingestion status.';
COMMENT ON COLUMN bronze_ingestion_log.run_id IS 'UUID identifying the specific ingestion run. Used for tracking and correlating related operations.';
COMMENT ON COLUMN bronze_ingestion_log.ingestion_status IS 'Status of ingestion: success, file_not_found, copy_failed, or verification_failed';
