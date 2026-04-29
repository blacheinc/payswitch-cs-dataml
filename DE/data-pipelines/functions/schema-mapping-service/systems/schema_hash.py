"""
Schema Hash Utility
Calculates hash of column names and types for artifact reuse
"""
import hashlib
from typing import Dict, List


def calculate_schema_hash(column_names: List[str], column_types: Dict[str, str]) -> str:
    """
    Calculate SHA-256 hash of schema (column names + types)
    
    Args:
        column_names: List of column names
        column_types: Dictionary mapping column names to types
    
    Returns:
        Hex digest of SHA-256 hash (64 characters)
    
    Example:
        >>> column_names = ["name", "age", "email"]
        >>> column_types = {"name": "string", "age": "integer", "email": "string"}
        >>> hash_value = calculate_schema_hash(column_names, column_types)
        >>> len(hash_value)
        64
    """
    # Sort column names alphabetically for consistent hashing
    sorted_columns = sorted(column_names)
    
    # Create string representation: "col1:type1|col2:type2|..."
    schema_string_parts = []
    for col in sorted_columns:
        col_type = column_types.get(col, "string")  # Default to "string" if type not found
        schema_string_parts.append(f"{col}:{col_type}")
    
    schema_string = "|".join(schema_string_parts)
    
    # Calculate SHA-256 hash
    hash_obj = hashlib.sha256(schema_string.encode('utf-8'))
    hash_hex = hash_obj.hexdigest()
    
    return hash_hex
