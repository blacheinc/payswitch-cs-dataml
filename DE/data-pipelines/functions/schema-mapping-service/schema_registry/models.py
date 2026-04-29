"""
SQLAlchemy Models for Schema Registry
"""
from sqlalchemy import Column, String, Integer, DateTime, JSON, Text, Float, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()


class SchemaDetectionResult(Base):
    """Schema Detection Results Table"""
    __tablename__ = 'schema_detection_results'
    __table_args__ = (
        Index('idx_schema_detection_bank_hash', 'bank_id', 'schema_hash'),
        {'schema': 'schema_registry'}
    )
    
    id = Column(String(36), primary_key=True)  # UUID as string
    bank_id = Column(String(100), nullable=False, index=True)
    schema_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hex digest
    result_json = Column(JSON, nullable=False)  # Serialized SchemaDetectionResult
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class DataAnalysisResult(Base):
    """Data Analysis Results Table"""
    __tablename__ = 'data_analysis_results'
    __table_args__ = (
        Index('idx_data_analysis_bank_hash', 'bank_id', 'schema_hash'),
        {'schema': 'schema_registry'}
    )
    
    id = Column(String(36), primary_key=True)  # UUID as string
    bank_id = Column(String(100), nullable=False, index=True)
    schema_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hex digest
    result_json = Column(JSON, nullable=False)  # Serialized DataAnalysisResult
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)


class AnonymizationMapping(Base):
    """Anonymization Mappings Table"""
    __tablename__ = 'anonymization_mappings'
    __table_args__ = (
        Index('idx_anonymization_bank_hash', 'bank_id', 'schema_hash'),
        {'schema': 'schema_registry'}
    )
    
    id = Column(String(36), primary_key=True)  # UUID as string
    bank_id = Column(String(100), nullable=False, index=True)
    schema_hash = Column(String(64), nullable=False, index=True)  # SHA-256 hex digest
    mapping_version = Column(String(20), nullable=False)  # e.g., "1.0", "2.0"
    mini_version = Column(Integer, default=0, nullable=False)  # For minor updates
    anonymization_methods = Column(JSON, nullable=False)  # Dict[str, str] - column -> method
    created_at = Column(DateTime, default=func.now(), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now(), nullable=False)
