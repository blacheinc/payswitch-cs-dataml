"""
Internal Schema Definitions using Pydantic
Multiple schema versions to support different data type preferences
"""

from pydantic import BaseModel, Field, validator
from typing import Optional, Literal
from decimal import Decimal
from datetime import datetime, date
from enum import Enum


# ============================================================
# ML Engineer's Target Features (18 Features)
# ============================================================
# Reference: UNIFIED_TRAINING_DATA_INGESTION_ARCHITECTURE.md lines 48-67
#
# 1. age (Float, 18-70)
# 2. monthly_income (Float, 0-100,000 GHS)
# 3. employment_years (Float, 0-50)
# 4. employment_type (String: Salaried/Self-Employed/Government)
# 5. account_balance (Float, 0-1,000,000 GHS)
# 6. savings_balance (Float, 0-1,000,000 GHS)
# 7. average_monthly_balance (Float, 0-1,000,000 GHS)
# 8. account_age_months (Integer, 0-600)
# 9. monthly_transactions_count (Integer, 0-500)
# 10. existing_loans_balance (Float, 0-500,000 GHS)
# 11. num_existing_loans (Integer, 0-20)
# 12. monthly_loan_repayment (Float, 0-100,000 GHS)
# 13. credit_history_months (Integer, 0-360)
# 14. num_credit_inquiries (Integer, 0-20)
# 15. num_late_payments (Integer, 0-50)
# 16. loan_amount_requested (Float, 0-500,000 GHS)
# 17. loan_tenure_months (Integer, 1-360)
# 18. debt_to_income_ratio (Float, 0.0-1.0, Optional/Calculated)
#
# Target Variable: approved (Integer: 0 or 1) - MANDATORY


# ============================================================
# Enums
# ============================================================

class EmploymentType(str, Enum):
    """Employment type enumeration"""
    SALARIED = "Salaried"
    SELF_EMPLOYED = "Self-Employed"
    GOVERNMENT = "Government"


# ============================================================
# Internal Schema Version 1: Minimal (Int Types, ISO Dates)
# ============================================================
# Purpose: Simplest schema, integer types for numeric fields, ISO date format
# Use Case: Banks with simple, clean data structures
#
# Schema Requirements:
# - 12-18 fields total (flexible based on available source data)
# - 7 mandatory fields (5 non-imputable + 2 imputable)
# - 5-11 optional fields (mapped from remaining 11 ML features)
# - LLM Coder will map as many fields as possible from source data

class InternalSchemaV1(BaseModel):
    """Internal Schema Version 1: Minimal schema with int types and ISO dates (12-18 fields)"""
    
    # ============================================================
    # 5 Non-Imputable Mandatory Fields (Cannot assume 0 or impute)
    # ============================================================
    approved: int = Field(..., ge=0, le=1, description="Loan approval status (0=rejected, 1=approved) - TARGET VARIABLE")
    age: int = Field(..., ge=18, le=80, description="Applicant age in years - DEMOGRAPHIC SIGNAL")
    monthly_income: int = Field(..., ge=0, le=100000, description="Monthly income in GHS - AFFORDABILITY")
    loan_amount_requested: int = Field(..., ge=0, le=500000, description="Loan amount requested in GHS - WHAT THEY WANT")
    loan_tenure_months: int = Field(..., ge=1, le=360, description="Loan tenure in months - REPAYMENT PERIOD")
    
    # ============================================================
    # 2 Imputable Mandatory Fields (Can impute 0 for first-time borrowers)
    # ============================================================
    existing_loans_balance: int = Field(..., ge=0, le=500000, description="Existing loans balance in GHS - DEBT BURDEN (can impute 0)")
    monthly_loan_repayment: int = Field(..., ge=0, le=100000, description="Monthly loan repayment in GHS - DEBT SERVICEABILITY (can impute 0)")
    
    # ============================================================
    # Optional Fields (5-11 fields, mapped from remaining 11 ML features)
    # LLM Coder will map as many as available in source data
    # Minimum 5 required to reach 12 total, maximum 11 to reach 18 total
    # ============================================================
    employment_years: Optional[int] = Field(None, ge=0, le=50, description="Years of employment")
    employment_type: Optional[EmploymentType] = Field(None, description="Type of employment")
    account_balance: Optional[int] = Field(None, ge=0, le=1000000, description="Account balance in GHS")
    savings_balance: Optional[int] = Field(None, ge=0, le=1000000, description="Savings balance in GHS")
    average_monthly_balance: Optional[int] = Field(None, ge=0, le=1000000, description="Average monthly balance in GHS")
    account_age_months: Optional[int] = Field(None, ge=0, le=600, description="Account age in months")
    monthly_transactions_count: Optional[int] = Field(None, ge=0, le=500, description="Monthly transaction count")
    num_existing_loans: Optional[int] = Field(None, ge=0, le=20, description="Number of existing loans")
    credit_history_months: Optional[int] = Field(None, ge=0, le=360, description="Credit history in months")
    num_credit_inquiries: Optional[int] = Field(None, ge=0, le=20, description="Number of credit inquiries")
    num_late_payments: Optional[int] = Field(None, ge=0, le=50, description="Number of late payments")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            date: lambda v: v.isoformat() if v else None,
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================
# Internal Schema Version 2: Comprehensive (Float Types, Custom Dates)
# ============================================================
# Purpose: More precise numeric types, supports custom date formats
# Use Case: Banks with detailed financial data, custom date formats
#
# Schema Requirements:
# - 12-18 fields total (flexible based on available source data)
# - 7 mandatory fields (5 non-imputable + 2 imputable)
# - 5-11 optional fields (mapped from remaining 11 ML features)
# - LLM Coder will map as many fields as possible from source data

class InternalSchemaV2(BaseModel):
    """Internal Schema Version 2: Comprehensive schema with float types and custom date formats (12-18 fields)"""
    
    # ============================================================
    # 5 Non-Imputable Mandatory Fields (Cannot assume 0 or impute)
    # ============================================================
    approved: int = Field(..., ge=0, le=1, description="Loan approval status (0=rejected, 1=approved) - TARGET VARIABLE")
    age: float = Field(..., ge=18.0, le=80.0, description="Applicant age in years (can include months) - DEMOGRAPHIC SIGNAL")
    monthly_income: float = Field(..., ge=0.0, le=100000.0, description="Monthly income in GHS - AFFORDABILITY")
    loan_amount_requested: float = Field(..., ge=0.0, le=500000.0, description="Loan amount requested in GHS - WHAT THEY WANT")
    loan_tenure_months: int = Field(..., ge=1, le=360, description="Loan tenure in months - REPAYMENT PERIOD")
    
    # ============================================================
    # 2 Imputable Mandatory Fields (Can impute 0 for first-time borrowers)
    # ============================================================
    existing_loans_balance: float = Field(..., ge=0.0, le=500000.0, description="Existing loans balance in GHS - DEBT BURDEN (can impute 0)")
    monthly_loan_repayment: float = Field(..., ge=0.0, le=100000.0, description="Monthly loan repayment in GHS - DEBT SERVICEABILITY (can impute 0)")
    
    # ============================================================
    # Optional Fields (5-11 fields, mapped from remaining 11 ML features)
    # LLM Coder will map as many as available in source data
    # Minimum 5 required to reach 12 total, maximum 11 to reach 18 total
    # ============================================================
    employment_years: Optional[float] = Field(None, ge=0.0, le=50.0, description="Years of employment (can include months)")
    employment_type: Optional[EmploymentType] = Field(None, description="Type of employment")
    account_balance: Optional[float] = Field(None, ge=0.0, le=1000000.0, description="Account balance in GHS")
    savings_balance: Optional[float] = Field(None, ge=0.0, le=1000000.0, description="Savings balance in GHS")
    average_monthly_balance: Optional[float] = Field(None, ge=0.0, le=1000000.0, description="Average monthly balance in GHS")
    account_age_months: Optional[int] = Field(None, ge=0, le=600, description="Account age in months")
    monthly_transactions_count: Optional[int] = Field(None, ge=0, le=500, description="Monthly transaction count")
    num_existing_loans: Optional[int] = Field(None, ge=0, le=20, description="Number of existing loans")
    credit_history_months: Optional[int] = Field(None, ge=0, le=360, description="Credit history in months")
    num_credit_inquiries: Optional[int] = Field(None, ge=0, le=20, description="Number of credit inquiries")
    num_late_payments: Optional[int] = Field(None, ge=0, le=50, description="Number of late payments")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            date: lambda v: v.isoformat() if v else None,
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================
# Internal Schema Version 3: Decimal (Financial Precision)
# ============================================================
# Purpose: High precision for financial calculations, Decimal types
# Use Case: Banks requiring exact financial precision, currency calculations
#
# Schema Requirements:
# - 12-18 fields total (flexible based on available source data)
# - 7 mandatory fields (5 non-imputable + 2 imputable)
# - 5-11 optional fields (mapped from remaining 11 ML features)
# - LLM Coder will map as many fields as possible from source data

class InternalSchemaV3(BaseModel):
    """Internal Schema Version 3: Decimal schema for financial precision (12-18 fields)"""
    
    # ============================================================
    # 5 Non-Imputable Mandatory Fields (Cannot assume 0 or impute)
    # ============================================================
    approved: int = Field(..., ge=0, le=1, description="Loan approval status (0=rejected, 1=approved) - TARGET VARIABLE")
    age: Decimal = Field(..., ge=Decimal("18"), le=Decimal("80"), description="Applicant age in years - DEMOGRAPHIC SIGNAL")
    monthly_income: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100000"), description="Monthly income in GHS - AFFORDABILITY")
    loan_amount_requested: Decimal = Field(..., ge=Decimal("0"), le=Decimal("500000"), description="Loan amount requested in GHS - WHAT THEY WANT")
    loan_tenure_months: int = Field(..., ge=1, le=360, description="Loan tenure in months - REPAYMENT PERIOD")
    
    # ============================================================
    # 2 Imputable Mandatory Fields (Can impute 0 for first-time borrowers)
    # ============================================================
    existing_loans_balance: Decimal = Field(..., ge=Decimal("0"), le=Decimal("500000"), description="Existing loans balance in GHS - DEBT BURDEN (can impute 0)")
    monthly_loan_repayment: Decimal = Field(..., ge=Decimal("0"), le=Decimal("100000"), description="Monthly loan repayment in GHS - DEBT SERVICEABILITY (can impute 0)")
    
    # ============================================================
    # Optional Fields (5-11 fields, mapped from remaining 11 ML features)
    # LLM Coder will map as many as available in source data
    # Minimum 5 required to reach 12 total, maximum 11 to reach 18 total
    # ============================================================
    employment_years: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("50"), description="Years of employment")
    employment_type: Optional[EmploymentType] = Field(None, description="Type of employment")
    account_balance: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("1000000"), description="Account balance in GHS")
    savings_balance: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("1000000"), description="Savings balance in GHS")
    average_monthly_balance: Optional[Decimal] = Field(None, ge=Decimal("0"), le=Decimal("1000000"), description="Average monthly balance in GHS")
    account_age_months: Optional[int] = Field(None, ge=0, le=600, description="Account age in months")
    monthly_transactions_count: Optional[int] = Field(None, ge=0, le=500, description="Monthly transaction count")
    num_existing_loans: Optional[int] = Field(None, ge=0, le=20, description="Number of existing loans")
    credit_history_months: Optional[int] = Field(None, ge=0, le=360, description="Credit history in months")
    num_credit_inquiries: Optional[int] = Field(None, ge=0, le=20, description="Number of credit inquiries")
    num_late_payments: Optional[int] = Field(None, ge=0, le=50, description="Number of late payments")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            Decimal: lambda v: str(v) if v else None,
            date: lambda v: v.isoformat() if v else None,
            datetime: lambda v: v.isoformat() if v else None
        }


# ============================================================
# Schema Version Type Union
# ============================================================

InternalSchema = InternalSchemaV1 | InternalSchemaV2 | InternalSchemaV3

SchemaVersion = Literal["v1", "v2", "v3"]


# ============================================================
# Schema Factory
# ============================================================

def get_schema_class(version: SchemaVersion) -> type[BaseModel]:
    """Get the schema class for a given version"""
    schema_map = {
        "v1": InternalSchemaV1,
        "v2": InternalSchemaV2,
        "v3": InternalSchemaV3
    }
    return schema_map[version]


# ============================================================
# Transformation to ML Features
# ============================================================

def validate_internal_schema(
    internal_data: InternalSchema,
    min_fields: int = 12
) -> tuple[bool, int, Optional[str]]:
    """
    Validate that internal schema has at least min_fields (default 12)
    and that the number of data types matches exactly
    
    Args:
        internal_data: Internal schema instance
        min_fields: Minimum number of fields required (default: 12)
    
    Returns:
        Tuple of (is_valid, field_count, error_message)
    """
    data_dict = internal_data.dict(exclude_none=True)
    field_count = len([v for v in data_dict.values() if v is not None])
    
    # Validate minimum field count
    if field_count < min_fields:
        return (
            False,
            field_count,
            f"Internal schema must have at least {min_fields} fields, but only {field_count} fields are present. "
            f"Required: 7 mandatory fields (5 non-imputable + 2 imputable) + at least {min_fields - 7} optional fields."
        )
    
    # Validate that number of data types matches exactly
    # Each field should have exactly one data type, and the count should match field count
    schema_fields = internal_data.__fields__
    non_none_fields = {k: v for k, v in data_dict.items() if v is not None}
    
    # Count unique data types in the actual data
    actual_type_count = len(set(type(v).__name__ for v in non_none_fields.values()))
    
    # Count unique data types expected in schema (for non-None fields)
    expected_types = set()
    for field_name, field_info in schema_fields.items():
        if field_name in non_none_fields:
            field_type = field_info.type_
            # Handle Optional types
            if hasattr(field_type, '__origin__') and hasattr(field_type, '__args__'):
                # Extract non-None types from Optional
                non_none_types = [t for t in field_type.__args__ if t is not type(None)]
                if non_none_types:
                    expected_types.add(non_none_types[0].__name__)
                else:
                    expected_types.add(field_type.__name__)
            else:
                expected_types.add(field_type.__name__)
    
    expected_type_count = len(expected_types)
    
    # Validate that the number of unique data types matches
    # This ensures each field has exactly one type, and we have the right number of types
    if actual_type_count != expected_type_count:
        return (
            False,
            field_count,
            f"Data type count mismatch: Expected {expected_type_count} unique data types for {field_count} fields, "
            f"but found {actual_type_count} unique types. Each field must have exactly one data type matching the schema."
        )
    
    return (True, field_count, None)


def transform_internal_to_ml_features(
    internal_data: InternalSchema,
    version: SchemaVersion
) -> dict:
    """
    Deterministic transformation from internal schema (12-18 fields) to ML engineer's 18 features
    
    Note: Internal schema contains 12-18 fields (7 mandatory + 5-11 optional).
    This function maps all available fields to the ML engineer's feature set, with remaining
    features set to None or calculated if possible.
    
    Args:
        internal_data: Internal schema instance (12-18 fields)
        version: Schema version used
    
    Returns:
        Dictionary with ML engineer's 18 features (some may be None if not in internal schema)
    """
    # Convert to dict and extract features
    data_dict = internal_data.dict(exclude_none=True)
    
    # Helper to safely convert to float (handles Decimal, int, float)
    def to_float(val):
        if val is None:
            return None
        if isinstance(val, Decimal):
            return float(val)
        return float(val)
    
    # Helper to safely convert to int
    def to_int(val):
        if val is None:
            return None
        return int(val)
    
    # Map internal schema fields (12-18 fields) to ML engineer's 18 features
    # All fields that may be present in internal schema (7 mandatory + 11 optional):
    ml_features = {
        # Mandatory fields (7 total - 5 non-imputable + 2 imputable)
        "approved": to_int(data_dict.get("approved", 0)),
        "age": to_float(data_dict.get("age", 0)),
        "monthly_income": to_float(data_dict.get("monthly_income", 0)),
        "loan_amount_requested": to_float(data_dict.get("loan_amount_requested", 0)),
        "loan_tenure_months": to_int(data_dict.get("loan_tenure_months", 0)),
        "existing_loans_balance": to_float(data_dict.get("existing_loans_balance", 0)),
        "monthly_loan_repayment": to_float(data_dict.get("monthly_loan_repayment", 0)),
        
        # Optional fields from internal schema (may be present, 5-11 fields)
        "employment_years": to_float(data_dict.get("employment_years")) if data_dict.get("employment_years") is not None else None,
        "employment_type": data_dict.get("employment_type"),  # May be present
        "account_balance": to_float(data_dict.get("account_balance")) if data_dict.get("account_balance") is not None else None,
        "savings_balance": to_float(data_dict.get("savings_balance")) if data_dict.get("savings_balance") is not None else None,
        "average_monthly_balance": to_float(data_dict.get("average_monthly_balance")) if data_dict.get("average_monthly_balance") is not None else None,
        "account_age_months": to_int(data_dict.get("account_age_months")) if data_dict.get("account_age_months") is not None else None,
        "monthly_transactions_count": to_int(data_dict.get("monthly_transactions_count")) if data_dict.get("monthly_transactions_count") is not None else None,
        "num_existing_loans": to_int(data_dict.get("num_existing_loans")) if data_dict.get("num_existing_loans") is not None else None,
        "credit_history_months": to_int(data_dict.get("credit_history_months")) if data_dict.get("credit_history_months") is not None else None,
        "num_credit_inquiries": to_int(data_dict.get("num_credit_inquiries")) if data_dict.get("num_credit_inquiries") is not None else None,
        "num_late_payments": to_int(data_dict.get("num_late_payments")) if data_dict.get("num_late_payments") is not None else None,
        "debt_to_income_ratio": None  # Calculated field, computed below if possible
    }
    
    # Calculate debt_to_income_ratio if we have the required fields
    monthly_income = ml_features.get("monthly_income")
    monthly_loan_repayment = ml_features.get("monthly_loan_repayment")
    if monthly_income and monthly_income > 0 and monthly_loan_repayment is not None:
        ml_features["debt_to_income_ratio"] = monthly_loan_repayment / monthly_income
    
    return ml_features
