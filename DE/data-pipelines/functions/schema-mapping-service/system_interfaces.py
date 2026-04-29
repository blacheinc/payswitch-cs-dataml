"""
System Interfaces for Schema Mapping Service
Type definitions and interfaces for all systems
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from pydantic import BaseModel
import pandas as pd
from datetime import datetime

# Use absolute import for better compatibility with pytest
try:
    from internal_schemas import InternalSchema, SchemaVersion
except ImportError:
    # Fallback for relative import if running as package
    from .internal_schemas import InternalSchema, SchemaVersion


# ============================================================
# System 0: File Introspection System Interfaces
# ============================================================
# Runs BEFORE Schema Detection - performs cheap probes on file metadata

class FileIntrospectionResult(BaseModel):
    """Result from file introspection (cheap probes)"""
    container_type: Optional[str] = None  # "zip", "tar", "gzip", None
    compression_type: Optional[str] = None  # "gzip", "bz2", "xz", None
    encoding: Optional[str] = None  # "utf-8", "utf-16", "latin-1", etc.
    has_bom: bool = False
    newline_type: Optional[str] = None  # "\n", "\r\n", "\r"
    file_size_bytes: int
    magic_bytes: Optional[bytes] = None  # First few bytes for format detection
    format_hints: Dict[str, Any] = {}  # Format-specific hints (e.g., delimiter candidates)
    io_hints: Dict[str, Any] = {}  # How to read safely (streaming vs random access)


class IFileIntrospectionSystem(ABC):
    """Interface for File Introspection System (runs before schema detection)"""
    
    @abstractmethod
    def introspect_file(
        self,
        file_path: str,
        sample_bytes: int = 8192
    ) -> FileIntrospectionResult:
        """
        Perform cheap file introspection (read only small bytes/metadata)
        Detects: container/compression, encoding, format signatures, delimiter hints
        """
        pass
    
    @abstractmethod
    def detect_container_and_compression(
        self,
        file_path: str
    ) -> Dict[str, Any]:
        """Detect archive/compression wrappers (ZIP/TAR/GZIP/etc.)"""
        pass
    
    @abstractmethod
    def detect_text_encoding(
        self,
        file_path: str,
        sample_bytes: int = 8192
    ) -> Dict[str, Any]:
        """Identify encoding, BOM presence, and mixed-encoding risk"""
        pass
    
    @abstractmethod
    def estimate_record_boundaries(
        self,
        file_path: str,
        sample_bytes: int = 8192
    ) -> Dict[str, Any]:
        """Determine record boundaries (newline-delimited, fixed-width, etc.)"""
        pass


# ============================================================
# System 1: Data Sampling System Interfaces
# ============================================================
# Runs AFTER Schema Detection - samples data based on detected format

class DataSamplingResult(BaseModel):
    """Result from data sampling operation"""
    samples: List[Any]  # List of resampled DataFrames (using Any to avoid Pydantic DataFrame issues)
    metadata: Dict[str, Any]
    format: str
    encoding: str
    total_row_count: int
    column_count: int
    sampling_strategy: str  # "full_dataset", "reservoir", "stratified", etc.
    
    class Config:
        arbitrary_types_allowed = True


class IDataSamplingSystem(ABC):
    """Interface for Data Sampling System (runs after schema detection)"""
    
    @abstractmethod
    def load_and_sample_from_datalake(
        self,
        bronze_path: str,
        format: str,
        encoding: str,
        max_sample_size: int = 10000,
        n_resamples: int = 3
    ) -> DataSamplingResult:
        """
        Load and sample data from Data Lake Gen2 Bronze Layer
        - If total rows <= max_sample_size: use entire dataset, no resampling
        - If total rows > max_sample_size: sample max_sample_size rows, create n_resamples
        """
        pass
    
    @abstractmethod
    def resample_data(
        self,
        df: pd.DataFrame,
        n_samples: int = 3,
        sample_size: int = 10000
    ) -> List[pd.DataFrame]:
        """Resample data multiple times for cross-validation (only if data > sample_size)"""
        pass
    
    @abstractmethod
    def aggregate_insights(
        self,
        samples: List[pd.DataFrame]
    ) -> Dict[str, Any]:
        """Aggregate insights from multiple resamples"""
        pass


# ============================================================
# System 2: Schema Detection System Interfaces
# ============================================================
# Runs AFTER File Introspection - uses introspection hints for efficient detection

class SchemaDetectionResult(BaseModel):
    """Result from schema detection"""
    format: str  # "csv", "json", "parquet", "xlsx", "bai2", "mt940", etc.
    encoding: str
    delimiter: Optional[str] = None
    has_header: bool = True
    column_count: int = 0
    row_count: int = 0
    nested_structure: bool = False
    sheets: Optional[List[str]] = None
    column_names: Optional[List[str]] = None
    column_types: Optional[Dict[str, str]] = None
    confidence: float = 0.0  # 0.0 to 1.0
    evidence: List[str] = []  # Evidence for format detection
    metadata: Dict[str, Any] = {}
    format_conflict: bool = False
    fallback_format: Optional[str] = None


class ISchemaDetectionSystem(ABC):
    """Interface for Schema Detection System (runs after file introspection)"""
    
    @abstractmethod
    def detect_format(
        self,
        file_path: str,
        introspection_result: FileIntrospectionResult
    ) -> str:
        """
        Auto-detect file format using introspection hints
        Uses magic bytes, format-specific signatures, etc.
        """
        pass
    
    @abstractmethod
    def detect_schema(
        self,
        file_path: str,
        format: str,
        introspection_result: FileIntrospectionResult
    ) -> SchemaDetectionResult:
        """
        Detect complete schema structure
        Uses format-specific functions from deep-research-report.md
        """
        pass


# ============================================================
# System 3: Dataset Anonymizer System Interfaces
# ============================================================

class PIIDetectionResult(BaseModel):
    """Result from PII detection"""
    names: List[str] = []
    emails: List[str] = []
    phones: List[str] = []
    ids: List[str] = []
    addresses: List[str] = []
    other: List[str] = []
    anonymization_methods: Dict[str, str] = {}  # Maps column name -> method ("hash", "tokenize", "generalize")
    confidence_scores: Dict[str, float] = {}  # Maps column name -> confidence score (0.0 to 1.0)
    reasons: Dict[str, str] = {}  # Maps column name -> reasoning for PII classification


class AnonymizationResult(BaseModel):
    """Result from anonymization operation"""
    anonymized_data: Any  # pd.DataFrame
    anonymization_mappings: Dict[str, Dict[str, str]]
    pii_fields: PIIDetectionResult

    class Config:
        arbitrary_types_allowed = True


class IDatasetAnonymizerSystem(ABC):
    """Interface for Dataset Anonymizer System"""
    
    @abstractmethod
    def detect_pii(
        self,
        schema_result: 'SchemaDetectionResult',
        data_analysis_result: Optional['DataAnalysisResult'] = None
    ) -> PIIDetectionResult:
        """
        Detect PII fields using schema-only metadata (column names + types).
        SECURITY: NO DataFrames are passed to LLM - only schema metadata.
        
        Args:
            schema_result: Schema detection result from System 1
            data_analysis_result: Optional data analysis result from System 3 (preferred for types)
        
        Returns:
            PIIDetectionResult with detected PII fields and anonymization methods
        """
        pass
    
    @abstractmethod
    def anonymize_dataframe(
        self,
        df: pd.DataFrame,
        pii_fields: PIIDetectionResult,
        method: str = "hash"
    ) -> AnonymizationResult:
        """Anonymize PII in DataFrame"""
        pass


# ============================================================
# System 4: Data Analysis System Interfaces
# ============================================================

class DataAnalysisResult(BaseModel):
    """Result from data analysis"""
    data_types: Dict[str, str]
    missing_data: Dict[str, Dict[str, Any]]
    distributions: Dict[str, Dict[str, Any]]
    formats: Dict[str, Dict[str, Any]]
    text_patterns: Dict[str, Dict[str, Any]] = {}
    nested_structures: Dict[str, List[str]]
    aggregated_insights: Dict[str, Any]


class IDataAnalysisSystem(ABC):
    """Interface for Data Analysis System"""
    
    @abstractmethod
    def analyze_data_types(self, df: pd.DataFrame) -> Dict[str, str]:
        """Analyze column data types"""
        pass
    
    @abstractmethod
    def analyze_missing_data(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Count nulls, calculate completeness %"""
        pass
    
    @abstractmethod
    def analyze_data_distributions(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Min/max/mean/median, detect outliers"""
        pass
    
    @abstractmethod
    def analyze_data_formats(self, df: pd.DataFrame) -> Dict[str, Dict]:
        """Detect date formats, number formats, text patterns"""
        pass
    
    @abstractmethod
    def detect_nested_structures(self, data: Any) -> Dict[str, List]:
        """If JSON, detect nested objects/arrays"""
        pass
    
    @abstractmethod
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
        pass


# ============================================================
# System 5: Schema Mapping System (LLMs) Interfaces
# ============================================================

class LLMCoderRequest(BaseModel):
    """Request for LLM Coder"""
    # File metadata (from Service Bus message + System 0)
    file_metadata: Dict[str, Any]
    
    # System 0: File Introspection results
    introspection_result: FileIntrospectionResult
    
    # System 1: Schema Detection results
    schema_detection: SchemaDetectionResult
    
    # System 2: Data Sampling results (metadata only, no actual DataFrames)
    sampling_result: Dict[str, Any]  # Metadata: format, encoding, row_count, column_count, sampling_strategy
    
    # System 3: Data Analysis results
    data_analysis: DataAnalysisResult
    
    # System 4: PII Detection results
    pii_detection: PIIDetectionResult
    
    # Internal schema definitions (all versions)
    internal_schemas: Dict[str, Any]  # V1, V2, V3 schema definitions
    
    # Context
    bank_id: str
    upload_id: str
    date: str
    
    # Available functions for LLM function calling (optional)
    available_functions: Optional[Dict[str, Any]] = None
    
    class Config:
        arbitrary_types_allowed = True


class LLMCoderResponse(BaseModel):
    """Response from LLM Coder"""
    code: str
    execution_plan: Dict[str, Any]
    reasoning: Dict[str, Any]
    field_mappings: Dict[str, str]
    confidence_scores: Dict[str, float]
    completeness_score: float  # LLM-determined score (0.0-1.0) for selected schema version
    target_schema_version: SchemaVersion


class LLMJudgeRequest(BaseModel):
    """Request for LLM Judge"""
    code: str
    execution_result: Dict[str, Any]
    reasoning: Dict[str, Any]
    sample_data: Any  # pd.DataFrame (using Any to avoid Pydantic DataFrame issues)
    target_schema: InternalSchema
    target_schema_version: SchemaVersion
    execution_plan: Dict[str, Any]
    
    class Config:
        arbitrary_types_allowed = True


class LLMJudgeResponse(BaseModel):
    """Response from LLM Judge"""
    status: str  # "APPROVED" | "NEEDS_CORRECTION" | "REJECTED"
    confidence: float
    feedback: str
    reasoning: str
    issues: List[str] = []
    suggestions: List[str] = []


class ISchemaMappingSystem(ABC):
    """Interface for Schema Mapping System"""
    
    @abstractmethod
    def generate_transformation_code(
        self,
        request: LLMCoderRequest
    ) -> LLMCoderResponse:
        """Generate transformation code using LLM Coder"""
        pass
    
    @abstractmethod
    def correct_code(
        self,
        original_code: str,
        original_reasoning: Dict[str, Any],
        judge_feedback: str,
        execution_result: Dict[str, Any]
    ) -> LLMCoderResponse:
        """Correct code based on judge feedback"""
        pass
    
    @abstractmethod
    def review_code(
        self,
        request: LLMJudgeRequest
    ) -> LLMJudgeResponse:
        """Review generated code and outputs using LLM Judge"""
        pass


# ============================================================
# System 6: Schema Testing System Interfaces (Later Phase)
# ============================================================

class TestCase(BaseModel):
    """Edge case test case"""
    input_data: Dict[str, Any]
    expected_output: Dict[str, Any]
    test_type: str
    description: str


class TestExecutionResult(BaseModel):
    """Result from test execution"""
    passed: List[TestCase]
    failed: List[Tuple[TestCase, str]]  # (test_case, error_message)
    total: int
    passed_count: int
    failed_count: int


class ISchemaTestingSystem(ABC):
    """Interface for Schema Testing System (Later Phase)"""
    
    @abstractmethod
    def generate_edge_case_tests(
        self,
        code: str,
        execution_plan: Dict[str, Any],
        target_schema: InternalSchema,
        sample_data: pd.DataFrame
    ) -> List[TestCase]:
        """Generate edge case tests using LLM Tester"""
        pass
    
    @abstractmethod
    def execute_tests(
        self,
        code: str,
        test_cases: List[TestCase]
    ) -> TestExecutionResult:
        """Execute test cases in sandbox"""
        pass


# ============================================================
# System 7: Schema Registry System Interfaces
# ============================================================

class SchemaMappingRecord(BaseModel):
    """Schema mapping record"""
    id: str
    bank_id: str
    schema_id: str
    version: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]
    field_mappings: Dict[str, str]
    transformation_code: str
    execution_plan: Dict[str, Any]
    reasoning: Dict[str, Any]
    test_results: Optional[Dict[str, Any]] = None
    confidence_scores: Dict[str, float]
    completeness_score: float  # LLM-determined completeness score (0.0-1.0)
    status: str  # "approved" | "pending_review" | "failed"
    created_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None


class ISchemaRegistrySystem(ABC):
    """Interface for Schema Registry System"""
    
    @abstractmethod
    def store_mapping(
        self,
        bank_id: str,
        upload_id: str,
        field_mappings: Dict[str, str],
        transformation_code: str,
        execution_plan: Dict[str, Any],
        reasoning: Dict[str, Any],
        confidence_scores: Dict[str, float],
        completeness_score: float,  # LLM-determined completeness score (0.0-1.0)
        status: str,
        target_schema_version: SchemaVersion
    ) -> str:
        """Store schema mapping in PostgreSQL"""
        pass
    
    @abstractmethod
    def get_mapping(
        self,
        bank_id: str,
        schema_id: Optional[str] = None
    ) -> Optional[SchemaMappingRecord]:
        """Retrieve schema mapping from PostgreSQL"""
        pass
    
    @abstractmethod
    def cache_mapping(
        self,
        bank_id: str,
        schema_id: str,
        mapping_data: Dict[str, Any],
        ttl: int = 3600
    ) -> None:
        """Cache schema mapping in Redis"""
        pass
    
    @abstractmethod
    def get_cached_mapping(
        self,
        bank_id: str,
        schema_id: str
    ) -> Optional[Dict[str, Any]]:
        """Retrieve cached mapping from Redis"""
        pass
    
    @abstractmethod
    def check_existing_mapping(
        self,
        bank_id: str,
        current_columns: List[str]
    ) -> Optional[SchemaMappingRecord]:
        """Check if existing mapping matches current columns"""
        pass


# ============================================================
# System 8: Sandbox Execution System Interfaces
# ============================================================

class SandboxExecutionRequest(BaseModel):
    """Request for sandbox execution"""
    code: str
    sample_data: Any  # pd.DataFrame (using Any to avoid Pydantic DataFrame issues)
    timeout: int = 30
    memory_limit: int = 512
    
    class Config:
        arbitrary_types_allowed = True


class SandboxExecutionResult(BaseModel):
    """Result from sandbox execution"""
    success: bool
    output: Optional[Any] = None  # Optional[pd.DataFrame] (using Any to avoid Pydantic DataFrame issues)
    error: Optional[str] = None
    execution_trace: Optional[str] = None
    execution_time: float
    output_schema: Optional[Dict[str, Any]] = None
    
    class Config:
        arbitrary_types_allowed = True


class ISandboxExecutionSystem(ABC):
    """Interface for Sandbox Execution System"""
    
    @abstractmethod
    def execute_code(
        self,
        request: SandboxExecutionRequest
    ) -> SandboxExecutionResult:
        """Execute code in isolated environment"""
        pass
    
    @abstractmethod
    def validate_output_schema(
        self,
        output: pd.DataFrame,
        target_schema: InternalSchema
    ) -> Tuple[bool, List[str]]:
        """Validate output schema matches target"""
        pass


# ============================================================
# Cost Monitoring Interfaces
# ============================================================

class LLMCostRecord(BaseModel):
    """LLM API cost record"""
    bank_id: str
    upload_id: str
    service: str  # "llm_coder" | "llm_judge" | "llm_tester"
    model: str
    tokens_input: int
    tokens_output: int
    cost_usd: float
    timestamp: datetime


class ICostMonitoringSystem(ABC):
    """Interface for Cost Monitoring System"""
    
    @abstractmethod
    def record_llm_cost(
        self,
        bank_id: str,
        upload_id: str,
        service: str,
        model: str,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float
    ) -> None:
        """Record LLM API cost"""
        pass
    
    @abstractmethod
    def get_costs_by_bank(
        self,
        bank_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[LLMCostRecord]:
        """Get LLM costs for a specific bank"""
        pass
    
    @abstractmethod
    def get_total_cost(
        self,
        bank_id: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> float:
        """Get total LLM cost for a bank"""
        pass
