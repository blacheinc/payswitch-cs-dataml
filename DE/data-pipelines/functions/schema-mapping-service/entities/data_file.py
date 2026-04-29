"""
DataFile entity class
Represents a dataset/file with derived attributes
"""

from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime


class DataFile:
    """
    Represents a data file with derived attributes
    
    Attributes:
        file_path: Full path to the file
        bank_id: Bank identifier
        upload_id: Upload identifier
        date: Date of upload
        file_name: Name of the file
        file_size_bytes: Size of file in bytes
        format: Detected file format (csv, json, parquet, etc.)
        encoding: Detected encoding (utf-8, utf-16, etc.)
        container_type: Container type if applicable (zip, tar, etc.)
        compression_type: Compression type if applicable (gzip, bz2, etc.)
        created_at: Timestamp when file was created/uploaded
        metadata: Additional metadata dictionary
    """
    
    def __init__(
        self,
        file_path: str,
        bank_id: str,
        upload_id: str,
        date: str,
        file_name: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        format: Optional[str] = None,
        encoding: Optional[str] = None,
        container_type: Optional[str] = None,
        compression_type: Optional[str] = None,
        created_at: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.file_path = file_path
        self.bank_id = bank_id
        self.upload_id = upload_id
        self.date = date
        self.file_name = file_name or Path(file_path).name
        self.file_size_bytes = file_size_bytes
        self.format = format
        self.encoding = encoding
        self.container_type = container_type
        self.compression_type = compression_type
        self.created_at = created_at or datetime.utcnow()
        self.metadata = metadata or {}
    
    @property
    def file_extension(self) -> str:
        """Get file extension"""
        return Path(self.file_name).suffix.lower()
    
    @property
    def is_compressed(self) -> bool:
        """Check if file is compressed"""
        return self.compression_type is not None
    
    @property
    def is_container(self) -> bool:
        """Check if file is a container (zip, tar, etc.)"""
        return self.container_type is not None
    
    @property
    def bronze_path(self) -> str:
        """Get bronze layer path"""
        return f"bronze/raw/{self.bank_id}/{self.date}/{self.upload_id}{self.file_extension}"
    
    @property
    def staging_internal_path(self) -> str:
        """Get staging layer path for internal schema"""
        return f"staging/internal/{self.bank_id}/{self.date}/{self.upload_id}.parquet"
    
    @property
    def staging_features_path(self) -> str:
        """Get staging layer path for ML features"""
        return f"staging/features/{self.bank_id}/{self.date}/{self.upload_id}.parquet"
    
    @property
    def silver_path(self) -> str:
        """Get silver layer path"""
        return f"silver/{self.bank_id}/{self.date}/{self.upload_id}.parquet"
    
    @property
    def gold_path(self) -> str:
        """Get gold layer path"""
        return f"gold/{self.bank_id}/{self.date}/{self.upload_id}.parquet"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "file_path": self.file_path,
            "bank_id": self.bank_id,
            "upload_id": self.upload_id,
            "date": self.date,
            "file_name": self.file_name,
            "file_size_bytes": self.file_size_bytes,
            "format": self.format,
            "encoding": self.encoding,
            "container_type": self.container_type,
            "compression_type": self.compression_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DataFile":
        """Create from dictionary"""
        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])
        
        return cls(
            file_path=data["file_path"],
            bank_id=data["bank_id"],
            upload_id=data["upload_id"],
            date=data["date"],
            file_name=data.get("file_name"),
            file_size_bytes=data.get("file_size_bytes"),
            format=data.get("format"),
            encoding=data.get("encoding"),
            container_type=data.get("container_type"),
            compression_type=data.get("compression_type"),
            created_at=created_at,
            metadata=data.get("metadata", {})
        )
