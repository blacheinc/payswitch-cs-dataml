-- Migration 001: Create schema_registry schema
-- This schema will contain all schema registry tables

CREATE SCHEMA IF NOT EXISTS schema_registry;

COMMENT ON SCHEMA schema_registry IS 'Schema registry for storing schema detection results, data analysis results, and anonymization mappings';
