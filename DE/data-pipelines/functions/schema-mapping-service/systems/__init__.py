"""
System classes implementing business logic
"""

# Only import what exists to avoid import errors
try:
    from .file_introspector import FileIntrospector
except ImportError:
    FileIntrospector = None

try:
    from .schema_detector import SchemaDetector
except ImportError:
    SchemaDetector = None

try:
    from .data_sampler import DataSampler
except ImportError:
    DataSampler = None

try:
    from .data_analyzer import DataAnalyzer
except ImportError:
    DataAnalyzer = None

try:
    from .dataset_anonymizer import DatasetAnonymizer
    from .pii_detector import PIIDetector
    from .pii_anonymizer import PIIAnonymizer
except ImportError:
    DatasetAnonymizer = None
    PIIDetector = None
    PIIAnonymizer = None

__all__ = [
    "FileIntrospector",
    "SchemaDetector",
    "DataSampler",
    "DataAnalyzer",
    "DatasetAnonymizer",
    "PIIDetector",
    "PIIAnonymizer",
]
