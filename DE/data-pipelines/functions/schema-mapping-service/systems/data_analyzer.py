"""
System 3: Data Analysis System
Generates comprehensive metadata for LLM context by analyzing sampled data
"""

import logging
import traceback
import re
from typing import Dict, Any, Optional, List
import pandas as pd
import numpy as np

try:
    from system_interfaces import (
        IDataAnalysisSystem,
        DataAnalysisResult,
        DataSamplingResult,
        SchemaDetectionResult
    )
    from utils.service_bus_parser import parse_data_ingested_message
    from utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from systems.schema_hash import calculate_schema_hash
    from schema_registry.data_analysis_store import DataAnalysisStore
except ImportError:
    from ..system_interfaces import (
        IDataAnalysisSystem,
        DataAnalysisResult,
        DataSamplingResult,
        SchemaDetectionResult
    )
    from ..utils.service_bus_parser import parse_data_ingested_message
    from ..utils.service_bus_writer import ServiceBusWriter, InternalStatus, ServiceBusClientError
    from ..systems.schema_hash import calculate_schema_hash
    from ..schema_registry.data_analysis_store import DataAnalysisStore

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    # Forward references for type hints
    pass

from .format_analyzers.date_format_detector import DateFormatDetector

logger = logging.getLogger(__name__)


class DataAnalyzer(IDataAnalysisSystem):
    """
    Data Analysis System
    Analyzes sampled data to generate comprehensive metadata for LLM context
    """
    
    # Z-score threshold for 95% confidence (two-tailed)
    Z_SCORE_THRESHOLD = 1.96
    
    def __init__(
        self,
        service_bus_writer: Optional[ServiceBusWriter] = None,
        key_vault_url: Optional[str] = None,
        run_id: Optional[str] = None,
        state_tracker = None
    ):
        """
        Initialize Data Analyzer
        
        Args:
            service_bus_writer: Optional Service Bus writer (if None, will create one)
            key_vault_url: Optional Key Vault URL for Service Bus connection string
            run_id: Run ID for tracking and filtering
            state_tracker: Optional PipelineStateTracker instance
        """
        self.service_bus_writer = service_bus_writer
        self.key_vault_url = key_vault_url
        self.run_id = run_id
        self.state_tracker = state_tracker
        self.date_format_detector = DateFormatDetector()
        self._message_context: Optional[Dict[str, Any]] = None
    
    def _get_service_bus_writer(self) -> Optional[ServiceBusWriter]:
        """Get or create Service Bus writer"""
        if self.service_bus_writer:
            return self.service_bus_writer
        
        if self.key_vault_url:
            try:
                return ServiceBusWriter(key_vault_url=self.key_vault_url)
            except Exception as e:
                logger.warning(f"Failed to create Service Bus writer: {e}")
                return None
        
        return None
    
    def _publish_error(
        self,
        error: Exception,
        system_name: str = "System 3: Data Analysis"
    ) -> None:
        """Publish error to Service Bus (both internal and backend)"""
        writer = self._get_service_bus_writer()
        if not writer or not self._message_context:
            return
        
        try:
            training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown')
            bank_id = self._message_context.get('bank_id', 'unknown')
            error_type = type(error).__name__
            error_message = str(error)
            stack_trace = traceback.format_exc()
            
            # Internal error (detailed)
            writer.publish_system_failed(
                training_upload_id=training_upload_id,
                bank_id=bank_id,
                system_name=system_name,
                error={
                    "message": error_message,
                    "type": error_type,
                    "stack_trace": stack_trace,
                    "bronze_blob_path": self._message_context.get('bronze_blob_path')
                },
                run_id=self.run_id
            )
            
            # Backend error (user-friendly)
            writer.publish_backend_error(
                training_upload_id=training_upload_id,
                error_type=error_type,
                error_message=error_message,
                system_name=system_name,
                stack_trace=stack_trace,
                run_id=self.run_id
            )
        except Exception as e:
            logger.error(f"[run_id={self.run_id}] Failed to publish error to Service Bus: {e}")
    
    def analyze(
        self,
        sampling_result: 'DataSamplingResult',
        schema_result: Optional['SchemaDetectionResult'] = None,
        parsed_message: Optional[Dict[str, Any]] = None
    ) -> DataAnalysisResult:
        """
        Run comprehensive analysis on sampled data
        
        Args:
            sampling_result: DataSamplingResult from System 2
            schema_result: Optional SchemaDetectionResult from System 1
            parsed_message: Optional parsed Service Bus message
            
        Returns:
            DataAnalysisResult with all analysis results
        """
        system_name = "System 3: Data Analysis"
        
        try:
            # Store message context
            bank_id = None
            if parsed_message:
                self._message_context = parsed_message
                bank_id = parsed_message.get('bank_id')
                # Get run_id from parsed_message if not set in __init__
                if not self.run_id:
                    self.run_id = parsed_message.get('run_id')
            
            # bank_id is mandatory for artifact reuse
            if not bank_id:
                raise ValueError("bank_id is mandatory and must be provided in parsed_message. Cannot proceed with data analysis without bank_id.")
            
            # Check deduplication before processing
            system_name_short = "analysis"
            if self.state_tracker and self.run_id and self._message_context:
                try:
                    if self.state_tracker.check_system_already_completed(self.run_id, system_name_short):
                        logger.warning(f"[run_id={self.run_id}] System {system_name_short} already completed. Skipping.")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to check deduplication: {e}. Continuing.")
            
            # Record system start in state tracker
            if self.state_tracker and self.run_id and self._message_context:
                try:
                    training_upload_id = self._message_context.get('training_upload_id') or self._message_context.get('upload_id')
                    self.state_tracker.start_system(
                        run_id=self.run_id,
                        training_upload_id=training_upload_id,
                        system_name=system_name_short
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system start: {system_name_short}")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system start: {e}")
            
            # Publish system starting
            writer = self._get_service_bus_writer()
            if writer and self._message_context:
                try:
                    writer.publish_system_starting(
                        training_upload_id=self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        run_id=self.run_id
                    )
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to publish system starting message: {e}")
            
            # Get samples from sampling result
            samples = sampling_result.samples
            
            if not samples:
                raise ValueError("No samples provided in sampling_result")
            
            # Analyze each sample
            all_analyses = []
            for i, sample_df in enumerate(samples):
                try:
                    analysis = self._analyze_single_sample(sample_df, schema_result)
                    all_analyses.append(analysis)
                except Exception as e:
                    logger.error(f"Error analyzing sample {i}: {e}")
                    self._publish_error(e)
                    raise
            
            # Aggregate insights from all samples
            aggregated = self._aggregate_insights(all_analyses)
            
            # Build result
            result = DataAnalysisResult(
                data_types=aggregated.get('data_types', {}),
                missing_data=aggregated.get('missing_data', {}),
                distributions=aggregated.get('distributions', {}),
                formats=aggregated.get('formats', {}),
                text_patterns=aggregated.get('text_patterns', {}),
                nested_structures=aggregated.get('nested_structures', {}),
                aggregated_insights=aggregated
            )
            
            # Option B: Always perform full analysis, then calculate hash and check/store cache
            if schema_result and schema_result.column_names and result.data_types:
                try:
                    # Calculate schema hash from schema_result (column names) and data_types from result
                    schema_hash = calculate_schema_hash(schema_result.column_names, result.data_types)
                    
                    # Check cache (Redis then PostgreSQL)
                    cached_result = DataAnalysisStore.get(bank_id, schema_hash)
                    if cached_result:
                        logger.info(f"Returning cached DataAnalysisResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
                        result = cached_result
                    
                    # Store result in cache
                    try:
                        DataAnalysisStore.store(bank_id, schema_hash, result)
                        logger.info(f"Stored DataAnalysisResult for bank_id: {bank_id}, schema_hash: {schema_hash}")
                    except Exception as e:
                        logger.warning(f"Failed to store DataAnalysisResult in cache: {e}. Continuing with result.")
                except Exception as e:
                    logger.warning(f"Error during artifact reuse check for DataAnalysisResult: {e}. Continuing with result.")
            
            # Record system completion in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.complete_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        metadata={
                            "column_count": len(result.data_types),
                            "total_columns_analyzed": len(result.missing_data),
                            "has_distributions": bool(result.distributions),
                            "has_formats": bool(result.formats)
                        }
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system completion: {system_name_short}")
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system completion: {e}")
            
            # Publish system complete
            if writer and self._message_context:
                try:
                    # Extract top-level insights for the message payload
                    overall_completeness = 100.0
                    columns_with_missing_data = []
                    if result.missing_data:
                        completeness_scores = []
                        for col, info in result.missing_data.items():
                            comp = info.get('completeness_pct', 100.0)
                            completeness_scores.append(comp)
                            if comp < 100.0:
                                columns_with_missing_data.append(col)
                        if completeness_scores:
                            overall_completeness = sum(completeness_scores) / len(completeness_scores)
                            
                    detected_text_patterns = {}
                    if result.text_patterns:
                        for col, info in result.text_patterns.items():
                            patterns = info.get('patterns', [])
                            if patterns:
                                detected_text_patterns[col] = patterns[0]  # Take primary pattern
                                
                    writer.publish_system_complete(
                        training_upload_id=self._message_context.get('training_upload_id') or self._message_context.get('upload_id', 'unknown'),
                        bank_id=self._message_context.get('bank_id', 'unknown'),
                        system_name=system_name,
                        status=InternalStatus.ANALYSIS_COMPLETE,
                        result={
                            "column_count": len(result.data_types),
                            "overall_completeness_pct": round(overall_completeness, 2),
                            "columns_with_missing_data": columns_with_missing_data,
                            "detected_text_patterns": detected_text_patterns,
                            "total_columns_analyzed": len(result.missing_data)
                        },
                        run_id=self.run_id
                    )
                except Exception as e:
                    logger.warning(f"[run_id={self.run_id}] Failed to publish system complete message: {e}")
            
            return result
            
        except Exception as e:
            # Record system failure in state tracker
            if self.state_tracker and self.run_id:
                try:
                    self.state_tracker.fail_system(
                        run_id=self.run_id,
                        system_name=system_name_short,
                        error_message=str(e)
                    )
                    logger.debug(f"[run_id={self.run_id}] Recorded system failure: {system_name_short}")
                except Exception as state_error:
                    logger.warning(f"[run_id={self.run_id}] Failed to record system failure: {state_error}")
            
            logger.error(f"[run_id={self.run_id}] Error in comprehensive analysis: {e}")
            self._publish_error(e, system_name)
            raise
    
    def _analyze_single_sample(
        self,
        df: pd.DataFrame,
        schema_result: Optional[SchemaDetectionResult] = None
    ) -> Dict[str, Any]:
        """Analyze a single sample DataFrame"""
        return {
            'data_types': self.analyze_data_types(df),
            'missing_data': self.analyze_missing_data(df),
            'distributions': self.analyze_data_distributions(df),
            'formats': self.analyze_data_formats(df),
            'text_patterns': self.analyze_text_patterns(df),
            'nested_structures': self.detect_nested_structures(df) if schema_result and schema_result.format == 'json' else {}
        }
    
    def analyze_data_types(self, df: pd.DataFrame) -> Dict[str, str]:
        """
        Analyze column data types
        
        Returns:
            Dict mapping column_name -> detected_type
        """
        type_mapping = {}
        
        for col in df.columns:
            dtype = df[col].dtype
            
            # Map pandas dtypes to Python types
            if pd.api.types.is_integer_dtype(dtype):
                type_mapping[col] = "integer"
            elif pd.api.types.is_float_dtype(dtype):
                type_mapping[col] = "float"
            elif pd.api.types.is_bool_dtype(dtype):
                type_mapping[col] = "boolean"
            elif pd.api.types.is_datetime64_any_dtype(dtype):
                type_mapping[col] = "datetime"
            elif pd.api.types.is_object_dtype(dtype):
                # Check if it's actually numeric
                try:
                    pd.to_numeric(df[col].dropna().head(100))
                    type_mapping[col] = "string_numeric"  # String that looks numeric
                except (ValueError, TypeError):
                    type_mapping[col] = "string"
            else:
                type_mapping[col] = "string"
        
        return type_mapping
    
    def analyze_missing_data(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Count nulls, calculate completeness %
        
        Returns:
            Dict mapping column_name -> {null_count, completeness_pct, total_rows}
        """
        result = {}
        total_rows = len(df)
        
        for col in df.columns:
            null_count = df[col].isna().sum()
            completeness_pct = ((total_rows - null_count) / total_rows * 100) if total_rows > 0 else 0.0
            
            result[col] = {
                'null_count': int(null_count),
                'completeness_pct': round(completeness_pct, 2),
                'total_rows': total_rows,
                'pattern': 'random' if null_count > 0 and null_count < total_rows else ('complete' if null_count == 0 else 'all_null')
            }
        
        return result
    
    def analyze_data_distributions(
        self,
        df: pd.DataFrame
    ) -> Dict[str, Dict[str, Any]]:
        """
        Min/max/mean/median, detect outliers using Z-score (95% confidence)
        
        Returns:
            Dict mapping column_name -> {min, max, mean, median, std, outliers}
        """
        result = {}
        
        for col in df.columns:
            col_data = df[col]
            
            # Only analyze numeric columns
            if not pd.api.types.is_numeric_dtype(col_data):
                continue
            
            # Remove NaN values for calculations
            numeric_data = col_data.dropna()
            
            if len(numeric_data) == 0:
                continue
            
            # Basic statistics
            stats = {
                'min': float(numeric_data.min()),
                'max': float(numeric_data.max()),
                'mean': float(numeric_data.mean()),
                'median': float(numeric_data.median()),
                'std': float(numeric_data.std()) if len(numeric_data) > 1 else 0.0,
                'unique_count': int(numeric_data.nunique())
            }
            
            # Detect outliers using Z-score (95% confidence, Z > 1.96 or Z < -1.96)
            outliers = []
            if stats['std'] > 0:
                z_scores = np.abs((numeric_data - stats['mean']) / stats['std'])
                outlier_mask = z_scores > self.Z_SCORE_THRESHOLD
                outlier_values = numeric_data[outlier_mask].tolist()
                
                # Limit to reasonable number of outliers for reporting
                if len(outlier_values) > 100:
                    outlier_values = outlier_values[:100]
                
                outliers = [float(v) for v in outlier_values]
            
            stats['outliers'] = outliers
            result[col] = stats
        
        return result
    
    def analyze_data_formats(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Detect date formats, number formats, text patterns
        
        Returns:
            Dict mapping column_name -> {format_type, examples, pattern}
        """
        result = {}
        
        for col in df.columns:
            col_data = df[col]
            
            # Skip if all null
            if col_data.isna().all():
                continue
            
            # Check if column might be dates
            if pd.api.types.is_datetime64_any_dtype(col_data):
                # Already datetime, extract format
                result[col] = {
                    'format_type': 'datetime',
                    'pattern': 'ISO',
                    'examples': col_data.dropna().head(3).dt.strftime('%Y-%m-%d').tolist()
                }
            elif pd.api.types.is_object_dtype(col_data) or pd.api.types.is_string_dtype(col_data):
                # Check for date strings (object or StringDtype)
                sample_values = col_data.dropna().head(100).astype(str).tolist()
                date_format_result = self.date_format_detector.detect_formats_from_column(sample_values)
                
                if date_format_result['pattern']:
                    result[col] = {
                        'format_type': 'date',
                        'detected_formats': date_format_result['detected_formats'],
                        'examples': date_format_result['examples'],
                        'pattern': date_format_result['pattern'],
                        'pattern_name': date_format_result.get('pattern_name'),
                        'confidence': date_format_result['confidence']
                    }
                else:
                    # Check for number formats
                    numeric_sample = col_data.dropna().head(10)
                    try:
                        numeric_values = pd.to_numeric(numeric_sample)
                        # Check for currency, thousands separator, etc.
                        sample_str = numeric_sample.astype(str).iloc[0] if len(numeric_sample) > 0 else ""
                        
                        has_comma = ',' in sample_str
                        has_dot = '.' in sample_str
                        has_currency = any(symbol in sample_str for symbol in ['$', '€', '£', 'GHS', '₵'])
                        
                        result[col] = {
                            'format_type': 'number',
                            'has_thousands_separator': has_comma,
                            'has_decimal_separator': has_dot,
                            'has_currency_symbol': has_currency,
                            'examples': numeric_sample.head(3).tolist()
                        }
                    except (ValueError, TypeError):
                        # Text pattern
                        result[col] = {
                            'format_type': 'text',
                            'examples': col_data.dropna().head(3).tolist()
                        }
            elif pd.api.types.is_numeric_dtype(col_data):
                # Numeric column
                result[col] = {
                    'format_type': 'number',
                    'examples': col_data.dropna().head(3).tolist()
                }
        
        return result
    
    def analyze_text_patterns(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """
        Detect text patterns in string columns (email, phone, UUID, etc.)
        
        Returns:
            Dict mapping column_name -> {patterns: List[str], examples: List[str]}
        """
        result = {}
        
        # Pattern definitions
        patterns = {
            'email': re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
            'phone': re.compile(r'^[\+]?[(]?[0-9]{1,4}[)]?[-\s\.]?[(]?[0-9]{1,4}[)]?[-\s\.]?[0-9]{1,9}$'),
            'uuid': re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE),
            'guid': re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE),
            'national_id': re.compile(r'^[A-Z0-9]{6,20}$'),  # Common national ID formats
            'credit_card': re.compile(r'^[0-9]{13,19}$'),  # Credit card numbers
            'alphanumeric': re.compile(r'^[A-Z0-9]+$', re.IGNORECASE),  # Alphanumeric only
            'numeric': re.compile(r'^[0-9]+$'),  # Numeric only
            'date_string': re.compile(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}'),  # Date-like strings
        }
        
        for col in df.columns:
            col_data = df[col]
            
            # Skip if all null
            if col_data.isna().all():
                continue
            
            # Only analyze string/object columns
            if not (pd.api.types.is_object_dtype(col_data) or pd.api.types.is_string_dtype(col_data)):
                continue
            
            # Sample values for pattern detection (up to 100 non-null values)
            sample_values = col_data.dropna().head(100).astype(str).tolist()
            
            if not sample_values:
                continue
            
            detected_patterns = []
            examples = []
            
            # Check each pattern
            for pattern_name, pattern_regex in patterns.items():
                matches = 0
                pattern_examples = []
                
                for val in sample_values:
                    val_str = str(val).strip()
                    if pattern_regex.match(val_str):
                        matches += 1
                        if len(pattern_examples) < 3:  # Keep up to 3 examples per pattern
                            pattern_examples.append(val_str[:50])  # Truncate long values
                
                # If more than 50% of samples match, consider it a pattern
                if matches > len(sample_values) * 0.5:
                    detected_patterns.append(pattern_name.upper())
                    examples.extend(pattern_examples[:2])  # Add examples
            
            # Additional heuristics
            # Check for alphanumeric with dashes/underscores (common in IDs)
            if not detected_patterns:
                dash_underscore_count = sum(1 for v in sample_values[:10] 
                                          if re.match(r'^[A-Z0-9_-]+$', str(v).strip(), re.IGNORECASE))
                if dash_underscore_count >= 5:
                    detected_patterns.append('ALPHANUMERIC_WITH_SEPARATORS')
                    examples.extend([str(v)[:50] for v in sample_values[:2]])
            
            # If no specific patterns detected but it's a string column, mark as generic text
            if not detected_patterns and len(sample_values) > 0:
                # Check if it's mostly unique (might be IDs or codes)
                unique_ratio = len(set(sample_values)) / len(sample_values)
                if unique_ratio > 0.9:
                    detected_patterns.append('UNIQUE_TEXT')
                else:
                    detected_patterns.append('TEXT')
                examples.extend([str(v)[:50] for v in sample_values[:3]])
            
            if detected_patterns:
                result[col] = {
                    'patterns': detected_patterns,
                    'examples': list(set(examples))[:5]  # Unique examples, max 5
                }
        
        return result
    
    def detect_nested_structures(self, data: Any) -> Dict[str, List[str]]:
        """
        If JSON, detect nested objects/arrays (JSON only)
        
        Returns:
            Dict with nested_paths and array_fields
        """
        # This will be implemented by JSON-specific analyzer
        # For now, return empty structure
        return {
            'nested_paths': [],
            'array_fields': []
        }
    
    def _aggregate_insights(
        self,
        all_analyses: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Aggregate insights from multiple resamples
        
        Strategy:
        - Numeric metrics: Average
        - Patterns: Union (all unique values)
        - Most common: Mode
        """
        if not all_analyses:
            return {}
        
        # Aggregate data types (most common across samples)
        data_types = {}
        type_votes = {}
        for analysis in all_analyses:
            for col, dtype in analysis.get('data_types', {}).items():
                if col not in type_votes:
                    type_votes[col] = []
                type_votes[col].append(dtype)
        
        for col, votes in type_votes.items():
            # Most common type
            data_types[col] = max(set(votes), key=votes.count)
        
        # Aggregate missing data (average completeness)
        missing_data = {}
        missing_votes = {}
        for analysis in all_analyses:
            for col, stats in analysis.get('missing_data', {}).items():
                if col not in missing_votes:
                    missing_votes[col] = {'completeness': [], 'null_count': [], 'total_rows': []}
                missing_votes[col]['completeness'].append(stats.get('completeness_pct', 0))
                missing_votes[col]['null_count'].append(stats.get('null_count', 0))
                missing_votes[col]['total_rows'].append(stats.get('total_rows', 0))
        
        for col, votes in missing_votes.items():
            missing_data[col] = {
                'null_count': int(np.mean(votes['null_count'])),
                'completeness_pct': round(np.mean(votes['completeness']), 2),
                'total_rows': int(np.mean(votes['total_rows']))
            }
        
        # Aggregate distributions (average statistics)
        distributions = {}
        dist_votes = {}
        for analysis in all_analyses:
            for col, stats in analysis.get('distributions', {}).items():
                if col not in dist_votes:
                    dist_votes[col] = {'min': [], 'max': [], 'mean': [], 'median': [], 'std': [], 'outliers': []}
                dist_votes[col]['min'].append(stats.get('min'))
                dist_votes[col]['max'].append(stats.get('max'))
                dist_votes[col]['mean'].append(stats.get('mean'))
                dist_votes[col]['median'].append(stats.get('median'))
                dist_votes[col]['std'].append(stats.get('std'))
                dist_votes[col]['outliers'].extend(stats.get('outliers', []))
        
        for col, votes in dist_votes.items():
            distributions[col] = {
                'min': float(np.mean(votes['min'])),
                'max': float(np.mean(votes['max'])),
                'mean': float(np.mean(votes['mean'])),
                'median': float(np.mean(votes['median'])),
                'std': float(np.mean(votes['std'])),
                'outliers': list(set(votes['outliers']))[:100]  # Unique outliers, limit to 100
            }
        
        # Aggregate formats (most common pattern)
        formats = {}
        format_votes = {}
        for analysis in all_analyses:
            for col, format_info in analysis.get('formats', {}).items():
                if col not in format_votes:
                    format_votes[col] = []
                format_votes[col].append(format_info)
        
        for col, votes in format_votes.items():
            # Most common format (by pattern)
            pattern_counts = {}
            for format_info in votes:
                pattern = format_info.get('pattern', 'unknown')
                pattern_counts[pattern] = pattern_counts.get(pattern, 0) + 1
            
            most_common_format = max(pattern_counts.items(), key=lambda x: x[1])[0] if pattern_counts else None
            
            # Find format info with most common pattern
            for format_info in votes:
                if format_info.get('pattern') == most_common_format:
                    formats[col] = format_info
                    break
        
        # Aggregate text patterns (union of patterns and examples)
        text_patterns = {}
        pattern_votes = {}
        for analysis in all_analyses:
            for col, pattern_info in analysis.get('text_patterns', {}).items():
                if col not in pattern_votes:
                    pattern_votes[col] = {'patterns': set(), 'examples': set()}
                pattern_votes[col]['patterns'].update(pattern_info.get('patterns', []))
                pattern_votes[col]['examples'].update(pattern_info.get('examples', []))
        
        for col, votes in pattern_votes.items():
            text_patterns[col] = {
                'patterns': sorted(list(votes['patterns'])),  # Sort for consistency
                'examples': list(votes['examples'])[:5]  # Limit to 5 unique examples
            }
        
        # Aggregate nested structures (union)
        nested_structures = {'nested_paths': [], 'array_fields': []}
        for analysis in all_analyses:
            nested = analysis.get('nested_structures', {})
            nested_structures['nested_paths'].extend(nested.get('nested_paths', []))
            nested_structures['array_fields'].extend(nested.get('array_fields', []))
        
        nested_structures['nested_paths'] = list(set(nested_structures['nested_paths']))
        nested_structures['array_fields'] = list(set(nested_structures['array_fields']))
        
        return {
            'data_types': data_types,
            'missing_data': missing_data,
            'distributions': distributions,
            'formats': formats,
            'text_patterns': text_patterns,
            'nested_structures': nested_structures,
            'sample_count': len(all_analyses)
        }
