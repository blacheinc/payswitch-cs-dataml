"""
Date Format Detection
Detects date formats in data (date only, no time components)
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass


@dataclass
class DateFormatPattern:
    """Represents a date format pattern"""
    name: str
    pattern: str  # Regex pattern
    format_string: str  # Python strftime format
    examples: List[str]
    description: str


class DateFormatDetector:
    """
    Detects date formats in data columns
    
    Supports common date formats (date only, no time):
    - ISO format: YYYY-MM-DD
    - US format: MM/DD/YYYY, MM-DD-YYYY
    - EU format: DD/MM/YYYY, DD-MM-YYYY
    - UK format: DD/MM/YYYY
    - Other formats: YYYY/MM/DD, DD.MM.YYYY, etc.
    """
    
    # Common date patterns (date only, no time)
    DATE_PATTERNS = [
        DateFormatPattern(
            name="ISO",
            pattern=r'^\d{4}-\d{2}-\d{2}$',
            format_string="%Y-%m-%d",
            examples=["2026-02-18", "2024-12-31"],
            description="ISO 8601 date format (YYYY-MM-DD)"
        ),
        DateFormatPattern(
            name="US_SLASH",
            pattern=r'^\d{1,2}/\d{1,2}/\d{4}$',
            format_string="%m/%d/%Y",
            examples=["2/18/2026", "12/31/2024"],
            description="US date format with slashes (MM/DD/YYYY)"
        ),
        DateFormatPattern(
            name="US_DASH",
            pattern=r'^\d{1,2}-\d{1,2}-\d{4}$',
            format_string="%m-%d-%Y",
            examples=["2-18-2026", "12-31-2024"],
            description="US date format with dashes (MM-DD-YYYY)"
        ),
        DateFormatPattern(
            name="EU_SLASH",
            pattern=r'^\d{1,2}/\d{1,2}/\d{4}$',
            format_string="%d/%m/%Y",
            examples=["18/02/2026", "31/12/2024"],
            description="European date format with slashes (DD/MM/YYYY)"
        ),
        DateFormatPattern(
            name="EU_DASH",
            pattern=r'^\d{1,2}-\d{1,2}-\d{4}$',
            format_string="%d-%m-%Y",
            examples=["18-02-2026", "31-12-2024"],
            description="European date format with dashes (DD-MM-YYYY)"
        ),
        DateFormatPattern(
            name="EU_DOT",
            pattern=r'^\d{1,2}\.\d{1,2}\.\d{4}$',
            format_string="%d.%m.%Y",
            examples=["18.02.2026", "31.12.2024"],
            description="European date format with dots (DD.MM.YYYY)"
        ),
        DateFormatPattern(
            name="YYYY_SLASH",
            pattern=r'^\d{4}/\d{2}/\d{2}$',
            format_string="%Y/%m/%d",
            examples=["2026/02/18", "2024/12/31"],
            description="Year-first format with slashes (YYYY/MM/DD)"
        ),
        DateFormatPattern(
            name="YYYY_DASH",
            pattern=r'^\d{4}-\d{2}-\d{2}$',
            format_string="%Y-%m-%d",
            examples=["2026-02-18", "2024-12-31"],
            description="Year-first format with dashes (YYYY-MM-DD) - same as ISO"
        ),
    ]
    
    def detect_format(
        self,
        date_string: str,
        sample_values: Optional[List[str]] = None
    ) -> Optional[DateFormatPattern]:
        """
        Detect date format from a single date string
        
        Args:
            date_string: Date string to analyze
            sample_values: Optional list of sample values for validation
            
        Returns:
            DateFormatPattern if detected, None otherwise
        """
        if not date_string or not isinstance(date_string, str):
            return None
        
        # Try each pattern
        for pattern in self.DATE_PATTERNS:
            if re.match(pattern.pattern, date_string.strip()):
                # Validate by trying to parse
                try:
                    datetime.strptime(date_string.strip(), pattern.format_string)
                    return pattern
                except ValueError:
                    continue
        
        return None
    
    def detect_formats_from_column(
        self,
        column_values: List[str],
        min_samples: int = 5
    ) -> Dict[str, Any]:
        """
        Detect date formats from a column of date strings
        
        Args:
            column_values: List of date strings (may include None/NaN)
            min_samples: Minimum number of valid samples needed
        
        Returns:
            Dict with:
            {
                "format_type": "date",
                "detected_formats": [{"name": "...", "pattern": "...", "confidence": 0.0-1.0}, ...],
                "examples": [...],
                "pattern": "...",  # Most common pattern
                "confidence": 0.0-1.0
            }
        """
        # Filter out None/NaN/empty values
        valid_values = [
            str(v).strip() for v in column_values
            if v is not None and str(v).strip() and str(v).strip().lower() != 'nan'
        ]
        
        if len(valid_values) < min_samples:
            return {
                "format_type": "date",
                "detected_formats": [],
                "examples": valid_values[:5],
                "pattern": None,
                "confidence": 0.0
            }
        
        # Count matches for each pattern
        pattern_counts: Dict[str, int] = {}
        pattern_examples: Dict[str, List[str]] = {}
        
        for value in valid_values:
            detected = self.detect_format(value)
            if detected:
                pattern_name = detected.name
                pattern_counts[pattern_name] = pattern_counts.get(pattern_name, 0) + 1
                if pattern_name not in pattern_examples:
                    pattern_examples[pattern_name] = []
                if len(pattern_examples[pattern_name]) < 3:
                    pattern_examples[pattern_name].append(value)
        
        if not pattern_counts:
            return {
                "format_type": "date",
                "detected_formats": [],
                "examples": valid_values[:5],
                "pattern": None,
                "confidence": 0.0
            }
        
        # Calculate confidence for each pattern
        total_valid = len(valid_values)
        detected_formats = []
        
        for pattern_name, count in pattern_counts.items():
            confidence = count / total_valid
            pattern_obj = next(p for p in self.DATE_PATTERNS if p.name == pattern_name)
            detected_formats.append({
                "name": pattern_name,
                "pattern": pattern_obj.pattern,
                "format_string": pattern_obj.format_string,
                "description": pattern_obj.description,
                "confidence": confidence,
                "examples": pattern_examples.get(pattern_name, [])
            })
        
        # Sort by confidence (descending)
        detected_formats.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Most common pattern
        most_common = detected_formats[0] if detected_formats else None
        
        return {
            "format_type": "date",
            "detected_formats": detected_formats,
            "examples": valid_values[:5],
            "pattern": most_common["format_string"] if most_common else None,
            "pattern_name": most_common["name"] if most_common else None,
            "confidence": most_common["confidence"] if most_common else 0.0
        }
    
    def validate_date_string(
        self,
        date_string: str,
        format_string: str
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate a date string against a format
        
        Args:
            date_string: Date string to validate
            format_string: Python strftime format string
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            datetime.strptime(date_string.strip(), format_string)
            return True, None
        except ValueError as e:
            return False, str(e)


class DateFormatValidator:
    """
    Validates date formats and provides conversion utilities
    """
    
    @staticmethod
    def can_parse(date_string: str, format_string: str) -> bool:
        """
        Check if date string can be parsed with given format
        
        Args:
            date_string: Date string to check
            format_string: Python strftime format string
            
        Returns:
            True if can be parsed, False otherwise
        """
        try:
            datetime.strptime(date_string.strip(), format_string)
            return True
        except (ValueError, AttributeError):
            return False
    
    @staticmethod
    def convert_to_iso(date_string: str, source_format: str) -> Optional[str]:
        """
        Convert date string from source format to ISO format (YYYY-MM-DD)
        
        Args:
            date_string: Date string in source format
            source_format: Python strftime format string of source
            
        Returns:
            ISO format date string (YYYY-MM-DD), or None if conversion fails
        """
        try:
            dt = datetime.strptime(date_string.strip(), source_format)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return None
