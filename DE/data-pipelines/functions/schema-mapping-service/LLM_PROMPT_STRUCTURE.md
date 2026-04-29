# LLM Coder Prompt Structure

**Date:** February 18, 2026  
**Purpose:** Detailed structure of information passed to LLM Coder (System 5)  
**Status:** Final

---

## Overview

The LLM Coder receives comprehensive context from all previous systems (0-4) to generate accurate transformation code. This document describes each piece of information and why it's needed.

---

## Complete Prompt Structure

```python
LLMCoderRequest = {
    # ============================================================
    # File Information (From Service Bus Message + System 0)
    # ============================================================
    "file_metadata": {
        "file_path": "bronze/training/bank-digital-001/2026-02-16/c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b.csv",
        "file_name": "c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b.csv",
        "file_size_bytes": 1048576,
        "file_format": "csv",
        "encoding": "utf-8",
        "description": "Source file metadata - helps LLM understand data origin, file size constraints, and format-specific parsing requirements. File path indicates bank, date, and upload context."
    },
    
    # ============================================================
    # System 0: File Introspection Results
    # ============================================================
    "introspection_result": {
        "container_type": None,  # "zip", "tar", "gzip", None
        "compression_type": None,  # "gzip", "bz2", "xz", None
        "encoding": "utf-8",
        "has_bom": False,
        "newline_type": "\n",
        "file_size_bytes": 1048576,
        "magic_bytes": b"...",
        "format_hints": {
            "possible_csv": True,
            "delimiter_hints": [",", ";", "\t"],
            "quote_char_hints": ['"', "'"],
            "has_header": True
        },
        "io_hints": {
            "streaming_recommended": False,
            "chunk_size": 8192
        },
        "description": "File structure hints from cheap probes (8KB sample) - helps LLM understand compression, encoding, format signatures, and I/O strategy. Format hints provide delimiter/quoting information for CSV parsing."
    },
    
    # ============================================================
    # System 1: Schema Detection Results
    # ============================================================
    "schema_detection": {
        "format": "csv",
        "encoding": "utf-8",
        "delimiter": ",",
        "has_header": True,
        "column_count": 25,
        "row_count": 10000,
        "nested_structure": False,
        "sheets": None,
        "column_names": [
            "customer_id", "customer_name", "age", "annual_salary", 
            "employment_years", "account_balance", "loan_amount", ...
        ],
        "column_types": {
            "customer_id": "string",
            "customer_name": "string",
            "age": "integer",
            "annual_salary": "float",
            "employment_years": "integer",
            "account_balance": "float",
            "loan_amount": "float",
            ...
        },
        "confidence": 0.95,
        "evidence": [
            "File extension is '.csv'",
            "Comma delimiter detected",
            "Header row present",
            "Consistent column count across rows"
        ],
        "metadata": {
            "quote_char": '"',
            "escape_char": None,
            "skip_initial_space": False
        },
        "description": "Detected schema structure - provides column names and types for field mapping decisions. Evidence helps LLM understand detection confidence. Metadata provides format-specific parsing details (quoting, escaping)."
    },
    
    # ============================================================
    # System 2: Data Sampling Results (Metadata Only)
    # ============================================================
    "sampling_result": {
        "format": "csv",
        "encoding": "utf-8",
        "total_row_count": 10000,
        "column_count": 25,
        "sampling_strategy": "full_dataset",  # or "resampled"
        "sample_count": 1,  # or 3 if resampled
        "sample_sizes": [10000],  # or [10000, 10000, 10000] if resampled
        "metadata": {
            "file_path": "bronze/training/bank-digital-001/2026-02-16/...",
            "max_sample_size": 10000,
            "n_resamples": 3
        },
        "description": "Data sampling information - indicates data size, sampling approach (full dataset vs resampled), and number of samples. Helps LLM understand data volume and sampling strategy used for analysis. NOTE: Actual DataFrames are NOT included - only metadata to avoid sending PII."
    },
    
    # ============================================================
    # System 3: Data Analysis Results
    # ============================================================
    "data_analysis": {
        # Per-column data types (detailed)
        "data_types": {
            "customer_id": "string",
            "customer_name": "string",
            "age": "integer",
            "annual_salary": "float",
            "employment_years": "integer",
            "account_balance": "float",
            "loan_amount": "float",
            "date_of_birth": "datetime",
            ...
        },
        
        # Missing data patterns
        "missing_data": {
            "customer_id": {
                "null_count": 0,
                "completeness_pct": 100.0,
                "total_rows": 10000,
                "pattern": "complete"
            },
            "annual_salary": {
                "null_count": 50,
                "completeness_pct": 99.5,
                "total_rows": 10000,
                "pattern": "random"
            },
            ...
        },
        
        # Data distributions
        "distributions": {
            "age": {
                "min": 18,
                "max": 75,
                "mean": 35.5,
                "median": 34,
                "std": 12.3,
                "outliers": [17, 76],  # Z-score > 1.96 or < -1.96
                "unique_count": 58
            },
            "annual_salary": {
                "min": 0,
                "max": 1200000,
                "mean": 240000,
                "median": 180000,
                "std": 150000,
                "outliers": [1500000, 2000000],
                "unique_count": 8500
            },
            ...
        },
        
        # Date formats detected
        "formats": {
            "date_of_birth": {
                "format_type": "date",
                "detected_formats": ["YYYY-MM-DD", "DD/MM/YYYY"],  # Multiple patterns detected
                "examples": ["1990-01-15", "15/01/1990"],
                "pattern": "YYYY-MM-DD",  # Most common
                "confidence": 0.85
            },
            ...
        },
        
        # Number formats detected
        "number_formats": {
            "annual_salary": {
                "format_type": "currency",
                "has_thousands_separator": True,
                "decimal_places": 2,
                "currency_symbol": "GHS",
                "examples": ["240,000.00", "1,200,000.50"]
            },
            ...
        },
        
        # Text patterns detected
        "text_patterns": {
            "customer_id": {
                "patterns": ["UUID", "alphanumeric"],
                "examples": ["c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b", "CUST001"]
            },
            ...
        },
        
        # Nested structures (JSON only)
        "nested_structures": {
            "nested_paths": [],  # e.g., ["customer.address.city"] for JSON
            "array_fields": []  # e.g., ["transactions"] for JSON
        },
        
        "description": "Comprehensive data analysis - provides detailed metadata about data quality, types, formats, and distributions. Helps LLM understand the source data structure and make accurate field mapping decisions. Outlier detection uses Z-score with 95% confidence (Z > 1.96 or Z < -1.96)."
    },
    
    # ============================================================
    # System 4: PII Detection Results
    # ============================================================
    "pii_detection": {
        "pii_fields": {
            "names": ["customer_name", "applicant_name"],
            "emails": ["email_address"],
            "phones": ["phone_number", "mobile_number"],
            "ids": ["national_id", "passport_number"],
            "addresses": ["home_address", "billing_address"],
            "other": []
        },
        "anonymization_method": "hash",  # "hash", "tokenize", "generalize"
        "description": "PII field detection results - indicates which fields contain PII (already anonymized in data). Helps LLM understand which fields were anonymized and should not be used for mapping. LLM should focus on non-PII fields for schema mapping."
    },
    
    # ============================================================
    # Internal Schema Definitions
    # ============================================================
    "internal_schemas": {
        "v1": {
            "version": "v1",
            "description": "Internal Schema Version 1: Minimal schema with int types and ISO dates. Best for banks with simple, clean data structures. Requires 12-18 fields total (7 mandatory + 5-11 optional).",
            "mandatory_fields": [
                {"name": "approved", "type": "int", "range": [0, 1], "description": "Loan approval status (TARGET VARIABLE)"},
                {"name": "age", "type": "int", "range": [18, 80], "description": "Applicant age in years (DEMOGRAPHIC SIGNAL)"},
                {"name": "monthly_income", "type": "int", "range": [0, 100000], "description": "Monthly income in GHS (AFFORDABILITY)"},
                {"name": "loan_amount_requested", "type": "int", "range": [0, 500000], "description": "Loan amount requested in GHS (WHAT THEY WANT)"},
                {"name": "loan_tenure_months", "type": "int", "range": [1, 360], "description": "Loan tenure in months (REPAYMENT PERIOD)"},
                {"name": "existing_loans_balance", "type": "int", "range": [0, 500000], "description": "Existing loans balance in GHS (DEBT BURDEN, can impute 0)"},
                {"name": "monthly_loan_repayment", "type": "int", "range": [0, 100000], "description": "Monthly loan repayment in GHS (DEBT SERVICEABILITY, can impute 0)"}
            ],
            "optional_fields": [
                {"name": "employment_years", "type": "int", "range": [0, 50]},
                {"name": "employment_type", "type": "EmploymentType", "values": ["Salaried", "Self-Employed", "Government"]},
                {"name": "account_balance", "type": "int", "range": [0, 1000000]},
                # ... more optional fields
            ],
            "field_count_range": [12, 18],
            "data_type_preference": "int"
        },
        "v2": {
            "version": "v2",
            "description": "Internal Schema Version 2: Comprehensive schema with float types and custom date formats. Best for banks with rich data and custom date formats. Requires 12-18 fields total (7 mandatory + 5-11 optional).",
            "mandatory_fields": [...],
            "optional_fields": [...],
            "field_count_range": [12, 18],
            "data_type_preference": "float"
        },
        "v3": {
            "version": "v3",
            "description": "Internal Schema Version 3: Decimal schema for financial precision. Best for banks requiring exact decimal precision. Requires 12-18 fields total (7 mandatory + 5-11 optional).",
            "mandatory_fields": [...],
            "optional_fields": [...],
            "field_count_range": [12, 18],
            "data_type_preference": "Decimal"
        },
        "description": "Available internal schema versions - LLM must select one version and map source fields to target fields. Each version has different data type preferences (int vs float vs Decimal) and field requirements. LLM should analyze the source data structure and select the version that best matches the available data and data type preferences."
    },
    
    # ============================================================
    # Context Information
    # ============================================================
    "context": {
        "bank_id": "bank-digital-001",
        "upload_id": "c8f6e7cf-8fc4-4c58-9cb3-ee5b6d89da7b",
        "date": "2026-02-16",
        "description": "Context information for tracking and logging - helps identify which bank and upload this mapping is for."
    },
    
    # ============================================================
    # Instructions for LLM
    # ============================================================
    "instructions": {
        "task": "Generate Python transformation code that maps source data (from schema_detection) to one of the internal schema versions (v1, v2, or v3).",
        "requirements": [
            "Analyze source data structure and select the internal schema version (v1, v2, or v3) that best matches available data and data type preferences",
            "Map all 7 mandatory fields first (priority 1), then optional fields (priority 2)",
            "Map as many fields as possible (minimum 12, maximum 18)",
            "Handle type conversions (e.g., annual_salary / 12 → monthly_income)",
            "Handle date format conversions (e.g., DD/MM/YYYY → ISO format)",
            "Handle missing data (impute 0 for existing_loans_balance and monthly_loan_repayment if missing)",
            "Validate output: ensure at least 12 fields are present",
            "If data cannot conform to any schema version, flag as NEEDS_HUMAN_INPUT",
            "Code must be directly testable in Azure Container Instance"
        ],
        "output_format": {
            "code": "Python function string",
            "execution_plan": "JSON with field mappings and transformations",
            "reasoning": "JSON explaining schema version selection and field mappings",
            "field_mappings": "Dict mapping source_field → target_field",
            "confidence_scores": "Dict with confidence per field (0.0-1.0)",
            "completeness_score": "Float (0.0-1.0) - calculated based on rules below",
            "target_schema_version": "Selected version (v1, v2, or v3)"
        },
        "completeness_score_rules": {
            "description": "Rules for calculating completeness score (0.0-1.0) for the selected schema version",
            "calculation_method": "LLM must calculate this score based on how well source data maps to target schema",
            "rules": [
                {
                    "rule": "Mandatory Fields Weight",
                    "description": "All 7 mandatory fields must be mapped. Each unmapped mandatory field reduces score by 0.14 (1/7). If all 7 mandatory fields are mapped, base score is 0.5 (50%)."
                },
                {
                    "rule": "Optional Fields Weight",
                    "description": "Each optional field mapped adds to the score. Maximum optional fields vary by version (5-11 fields). Calculate: (mapped_optional_fields / max_optional_fields) * 0.5. This gives up to 0.5 additional points."
                },
                {
                    "rule": "Minimum Field Count",
                    "description": "At least 12 fields must be mapped (7 mandatory + 5 optional minimum). If fewer than 12 fields are mapped, completeness_score = 0.0 and flag as NEEDS_HUMAN_INPUT."
                },
                {
                    "rule": "Data Type Compatibility",
                    "description": "If mapped fields have incompatible data types (e.g., source is string but target requires int, and no conversion logic provided), reduce score by 0.1 per incompatible field (max reduction: 0.3)."
                },
                {
                    "rule": "Field Derivation",
                    "description": "Fields that can be derived (e.g., monthly_income from annual_salary / 12) count as mapped if derivation logic is provided in code. Fields that can be imputed (existing_loans_balance, monthly_loan_repayment) count as mapped if imputation logic is provided."
                },
                {
                    "rule": "Final Score Calculation",
                    "description": "completeness_score = (mandatory_fields_mapped / 7) * 0.5 + (optional_fields_mapped / max_optional_fields) * 0.5 - type_incompatibility_penalty. Final score must be between 0.0 and 1.0. If < 12 fields mapped, completeness_score = 0.0 and flag as NEEDS_HUMAN_INPUT."
                },
                {
                    "rule": "Score Interpretation & Human Intervention Thresholds",
                    "description": "0.9-1.0: Excellent mapping, all or nearly all fields mapped correctly. No human intervention required. 0.7-0.9: Good mapping, most fields mapped. No human intervention required. 0.5-0.7: Requires human intervention - mapping meets minimum but needs review before approval. Flag as NEEDS_HUMAN_INPUT. Below 0.5: Worse state - insufficient mapping quality. Flag as NEEDS_HUMAN_INPUT with higher priority; may require significant rework or indicate data cannot conform to schema."
                }
            ],
            "example_calculation": {
                "scenario": "Selected V1 schema, mapped 7 mandatory + 8 optional fields (out of 11 max), 1 type incompatibility",
                "calculation": "Mandatory: 7/7 * 0.5 = 0.5. Optional: 8/11 * 0.5 = 0.364. Type penalty: -0.1. Total: 0.5 + 0.364 - 0.1 = 0.764",
                "result": "completeness_score = 0.764"
            }
        }
    }
}
```

---

## Why Each Piece of Information Is Needed

### File Metadata
- **Why:** LLM needs to know file format, size, encoding to generate correct parsing code
- **Example:** CSV vs JSON requires different parsing logic

### Introspection Results
- **Why:** Format hints (delimiters, quoting) help LLM generate correct CSV parsing code
- **Example:** Semicolon-delimited CSV requires different code than comma-delimited

### Schema Detection
- **Why:** Column names and types are essential for field mapping
- **Example:** LLM needs to know "annual_salary" exists to map to "monthly_income"

### Sampling Results (Metadata Only)
- **Why:** Data size helps LLM understand data volume (but actual data not needed)
- **Example:** Large datasets may require different transformation strategies

### Data Analysis
- **Why:** Comprehensive metadata helps LLM make accurate mapping decisions
- **Example:** Date format detection helps LLM generate correct date parsing code

### PII Detection
- **Why:** LLM should not use PII fields for mapping (already anonymized)
- **Example:** "customer_name" is PII, should not be mapped to any internal field

### Internal Schemas
- **Why:** LLM needs to know target schema structure to generate mapping code
- **Example:** LLM needs to know V1 uses int types, V2 uses float types

---

**Document Version:** 1.0  
**Last Updated:** February 18, 2026  
**Status:** Final
