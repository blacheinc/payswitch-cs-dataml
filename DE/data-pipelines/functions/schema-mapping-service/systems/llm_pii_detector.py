"""
System 4.1: LLM-Based PII Detector
Uses Azure OpenAI to detect PII fields with full context from previous systems
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any, Callable

try:
    from openai import AzureOpenAI
    from azure.identity import DefaultAzureCredential, AzureCliCredential
    from azure.keyvault.secrets import SecretClient
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    AzureOpenAI = None
    DefaultAzureCredential = None
    AzureCliCredential = None
    SecretClient = None

try:
    from system_interfaces import (
        PIIDetectionResult,
        SchemaDetectionResult,
        DataAnalysisResult,
        FileIntrospectionResult
    )
except ImportError:
    from ..system_interfaces import (
        PIIDetectionResult,
        SchemaDetectionResult,
        DataAnalysisResult,
        FileIntrospectionResult
    )

logger = logging.getLogger(__name__)

# Default API version if not in Key Vault
DEFAULT_API_VERSION = "2024-12-01-preview"


def _runs_on_azure_app_service() -> bool:
    """True on Azure Functions / App Service / Container Apps style hosts (no Azure CLI)."""
    return bool(os.getenv("WEBSITE_INSTANCE_ID", "").strip() or os.getenv("CONTAINER_APP_NAME", "").strip())


def _key_vault_credential(env: str):
    """
    Pick a credential that works on the current host.

    DefaultAzureCredential tries AzureCliCredential first and logs noisy warnings on Azure;
    more importantly, app settings often set ENVIRONMENT=local on dev slots, which would
    force AzureCliCredential-only and break LLM secret retrieval entirely.
    """
    if _runs_on_azure_app_service():
        return DefaultAzureCredential(
            additionally_allowed_tenants=["*"],
            exclude_cli_credential=True,
            exclude_interactive_browser_credential=True,
        )
    if env == "local":
        return AzureCliCredential()
    return DefaultAzureCredential(
        additionally_allowed_tenants=["*"],
    )


# Secret names in Key Vault
SECRET_NAMES = {
    "endpoint": "AzureOpenAIEndpoint",
    "api_key": "AzureOpenAIKey",
    "deployment": "AzureOpenAIDeployment",
    "api_version": "AzureOpenAIApiVersion"
}


def get_azure_openai_secrets(key_vault_url: str, env: str = "production") -> Dict[str, str]:
    """
    Get Azure OpenAI secrets from Key Vault
    
    Args:
        key_vault_url: Key Vault URL
        env: Environment ("local" or "production")
    
    Returns:
        Dict with endpoint, api_key, deployment, api_version
    """
    if not OPENAI_AVAILABLE:
        raise ImportError("Azure OpenAI SDK not available. Install with: pip install openai azure-keyvault-secrets")

    credential = _key_vault_credential(env)
    client = SecretClient(vault_url=key_vault_url, credential=credential)
    
    secrets = {}
    for key, secret_name in SECRET_NAMES.items():
        try:
            secret_value = client.get_secret(secret_name).value
            secrets[key] = secret_value
            logger.debug(f"Retrieved {secret_name} from Key Vault")
        except Exception as e:
            if key == "api_version":
                # API version is optional, use default
                secrets[key] = DEFAULT_API_VERSION
                logger.warning(f"{secret_name} not found in Key Vault, using default: {DEFAULT_API_VERSION}")
            else:
                raise Exception(f"Failed to retrieve {secret_name} from Key Vault: {e}")
    
    return secrets


def create_llm_pii_detector_with_full_context(
    key_vault_url: str,
    env: str = "production"
) -> Callable:
    """
    Create LLM-based PII detector callback that takes full context from previous systems
    
    Args:
        key_vault_url: Key Vault URL for Azure OpenAI secrets
        env: Environment ("local" or "production")
    
    Returns:
        Callable that takes (column_names, column_types, schema_result, data_analysis_result, introspection_result) 
        and returns PIIDetectionResult
    """
    if not OPENAI_AVAILABLE:
        raise ImportError("Azure OpenAI SDK not available")
    
    # Get Azure OpenAI secrets
    secrets = get_azure_openai_secrets(key_vault_url, env)
    
    # Initialize Azure OpenAI client
    client = AzureOpenAI(
        api_version=secrets["api_version"],
        azure_endpoint=secrets["endpoint"],
        api_key=secrets["api_key"]
    )
    
    def llm_detect_pii_with_context(
        column_names: List[str],
        column_types: Dict[str, str],
        schema_result: Optional[SchemaDetectionResult] = None,
        data_analysis_result: Optional[DataAnalysisResult] = None,
        introspection_result: Optional[Dict[str, Any]] = None
    ) -> PIIDetectionResult:
        """
        LLM callback for PII detection with full context from previous systems
        
        Args:
            column_names: List of column names
            column_types: Dict mapping column name -> data type
            schema_result: Schema detection result from System 1
            data_analysis_result: Data analysis result from System 3
            introspection_result: File introspection result from System 0
        
        Returns:
            PIIDetectionResult with detected PII fields and anonymization methods
        """
        # Build comprehensive prompt with full context
        prompt_parts = []
        
        # System message
        prompt_parts.append("""You are a PII (Personally Identifiable Information) detection expert analyzing credit scoring data for a Ghanaian bank.

Your task is to identify which columns contain PII and determine the best anonymization method for each PII column.

**Context:**
- This is credit scoring training data from a Ghanaian bank
- Data will be used for ML model training
- PII must be anonymized before processing
- You have access to comprehensive metadata from previous analysis phases""")
        
        # Add file introspection context (System 0)
        if introspection_result:
            prompt_parts.append("\n**File Introspection Results (System 0):**")
            if introspection_result.get("format_hints"):
                hints = introspection_result["format_hints"]
                if hints.get("possible_csv"):
                    prompt_parts.append("- Format: CSV detected")
                if hints.get("delimiter_hints"):
                    prompt_parts.append(f"- Delimiter hints: {hints['delimiter_hints']}")
                if hints.get("has_header") is not None:
                    prompt_parts.append(f"- Has header: {hints['has_header']}")
            if introspection_result.get("encoding"):
                prompt_parts.append(f"- Encoding: {introspection_result['encoding']}")
            if introspection_result.get("file_size_bytes"):
                prompt_parts.append(f"- File size: {introspection_result['file_size_bytes']} bytes")
        
        # Add schema detection context (System 1)
        if schema_result:
            prompt_parts.append("\n**Schema Detection Results (System 1):**")
            prompt_parts.append(f"- Format: {schema_result.format}")
            prompt_parts.append(f"- Encoding: {schema_result.encoding}")
            if schema_result.delimiter:
                prompt_parts.append(f"- Delimiter: {schema_result.delimiter}")
            prompt_parts.append(f"- Has header: {schema_result.has_header}")
            prompt_parts.append(f"- Column count: {schema_result.column_count}")
            prompt_parts.append(f"- Row count: {schema_result.row_count}")
            if schema_result.confidence:
                prompt_parts.append(f"- Detection confidence: {schema_result.confidence}")
            if schema_result.evidence:
                prompt_parts.append(f"- Evidence: {', '.join(schema_result.evidence[:3])}")  # First 3 evidence items
        
        # Add data analysis context (System 3)
        if data_analysis_result:
            prompt_parts.append("\n**Data Analysis Results (System 3):**")
            
            # Data types
            if data_analysis_result.data_types:
                prompt_parts.append("\n**Data Types:**")
                for col, dtype in list(data_analysis_result.data_types.items())[:10]:  # First 10 columns
                    prompt_parts.append(f"  - {col}: {dtype}")
            
            # Missing data patterns
            if data_analysis_result.missing_data:
                prompt_parts.append("\n**Missing Data Patterns:**")
                for col, missing_info in list(data_analysis_result.missing_data.items())[:5]:  # First 5 columns
                    if missing_info.get("null_count", 0) > 0:
                        prompt_parts.append(f"  - {col}: {missing_info.get('null_count', 0)} nulls ({missing_info.get('completeness_pct', 0):.1f}% complete)")
            
            # Text patterns (important for PII detection)
            if data_analysis_result.text_patterns:
                prompt_parts.append("\n**Text Patterns Detected:**")
                for col, pattern_info in list(data_analysis_result.text_patterns.items())[:10]:  # First 10 columns
                    patterns = pattern_info.get("patterns", [])
                    examples = pattern_info.get("examples", [])
                    if patterns:
                        prompt_parts.append(f"  - {col}: {', '.join(patterns)}")
                        if examples:
                            prompt_parts.append(f"    Examples: {', '.join(str(ex)[:30] for ex in examples[:2])}")  # First 2 examples, truncated
            
            # Date formats
            if data_analysis_result.formats:
                prompt_parts.append("\n**Date Formats Detected:**")
                for col, format_info in list(data_analysis_result.formats.items())[:5]:  # First 5 columns
                    detected_formats = format_info.get("detected_formats", [])
                    if detected_formats:
                        prompt_parts.append(f"  - {col}: {', '.join(detected_formats)}")
            
            # Distributions (for numeric fields that might be PII)
            if data_analysis_result.distributions:
                prompt_parts.append("\n**Numeric Distributions (for context):**")
                for col, dist_info in list(data_analysis_result.distributions.items())[:5]:  # First 5 columns
                    unique_count = dist_info.get("unique_count", 0)
                    if unique_count > 0:
                        prompt_parts.append(f"  - {col}: {unique_count} unique values")
        
        # Add column information
        prompt_parts.append("\n**Column Names and Types:**")
        columns_info = []
        for col in column_names:
            col_type = column_types.get(col, "string")
            columns_info.append(f"  - {col} ({col_type})")
        prompt_parts.append("\n".join(columns_info))
        
        # Add anonymization methods
        prompt_parts.append("""
**Available Anonymization Methods:**
1. **hash** - SHA-256 hash (for exact matching needs, e.g., IDs, emails, phone numbers)
2. **tokenize** - Replace with tokens like PII_name_1, PII_name_2 (for preserving relationships, e.g., names)
3. **generalize** - Replace with placeholders like [REDACTED], [LOCATION] (for addresses, locations)

**Instructions:**
1. Analyze ALL available context (file format, schema, data patterns, text patterns) to identify PII fields
2. Use text patterns, data types, and column names to make informed decisions
3. Categorize each PII column into: names, emails, phones, ids, addresses, or other
4. Choose the best anonymization method for each PII column based on:
   - **hash**: For IDs, emails, phone numbers (when exact matching needed)
   - **tokenize**: For names (preserves relationships between records)
   - **generalize**: For addresses, locations (reduces specificity)
5. Consider data patterns: if a column has patterns like "UUID", "email", "phone", it's likely PII
6. Consider uniqueness: if a column has high uniqueness and is text-based, it might be PII

**Output Format (JSON):**
{
  "pii_fields": {
    "names": ["column1", "column2"],
    "emails": ["column3"],
    "phones": ["column4"],
    "ids": ["column5"],
    "addresses": ["column6"],
    "other": []
  },
  "anonymization_methods": {
    "column1": "tokenize",
    "column3": "hash",
    "column4": "hash",
    "column5": "hash",
    "column6": "generalize"
  },
  "confidence_scores": {
    "column1": 0.95,
    "column3": 0.99,
    "column4": 0.90,
    "column5": 0.85,
    "column6": 0.80
  },
  "reasons": {
    "column1": "Column explicitly contains full names of individuals based on column name and text patterns.",
    "column3": "Detected email patterns and column name suggests email address.",
    "column4": "Detected phone number patterns and high uniqueness.",
    "column5": "UUID pattern detected and column name indicates ID.",
    "column6": "Column contains address components like city, postal code, etc."
  }
}

Return ONLY valid JSON, no additional text.""")
        
        prompt = "\n".join(prompt_parts)
        
        try:
            logger.info("Calling Azure OpenAI for LLM-based PII detection with full context")
            
            # Call Azure OpenAI with structured output
            response = client.chat.completions.create(
                model=secrets["deployment"],
                messages=[
                    {"role": "system", "content": "You are a PII detection expert. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,  # Low temperature for consistent results
                response_format={"type": "json_object"}  # Structured output
            )
            
            # Parse response
            response_text = response.choices[0].message.content.strip()
            result_json = json.loads(response_text)
            
            names = result_json.get("pii_fields", {}).get("names", [])
            emails = result_json.get("pii_fields", {}).get("emails", [])
            phones = result_json.get("pii_fields", {}).get("phones", [])
            ids = result_json.get("pii_fields", {}).get("ids", [])
            addresses = result_json.get("pii_fields", {}).get("addresses", [])
            other = result_json.get("pii_fields", {}).get("other", [])
            
            anonymization_methods = result_json.get("anonymization_methods", {})
            
            # Ensure all keys in anonymization_methods are present in at least one category list
            all_categorized = set(names + emails + phones + ids + addresses + other)
            for col in anonymization_methods.keys():
                if col not in all_categorized:
                    other.append(col)
                    
            # Build PIIDetectionResult with anonymization_methods, confidence, and reasons
            pii_result = PIIDetectionResult(
                names=names,
                emails=emails,
                phones=phones,
                ids=ids,
                addresses=addresses,
                other=other,
                anonymization_methods=anonymization_methods,
                confidence_scores=result_json.get("confidence_scores", {}),
                reasons=result_json.get("reasons", {})
            )
            
            logger.info(
                f"LLM PII detection completed: "
                f"names={len(pii_result.names)}, emails={len(pii_result.emails)}, "
                f"phones={len(pii_result.phones)}, ids={len(pii_result.ids)}, "
                f"addresses={len(pii_result.addresses)}, other={len(pii_result.other)}"
            )
            
            return pii_result
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.error(f"Response text: {response_text[:500] if 'response_text' in locals() else 'N/A'}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
        except Exception as e:
            logger.error(f"LLM PII detection failed: {e}", exc_info=True)
            raise
    
    return llm_detect_pii_with_context
