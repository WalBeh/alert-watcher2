"""
Shared data models for file upload functionality.

This module defines common data structures used across crash dump and JFR upload workflows.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any


@dataclass
class CrateDBPod:
    """Information about a CrateDB pod."""
    name: str
    namespace: str
    container: str = "crate"
    cluster_context: str = ""


@dataclass
class FileToUpload:
    """Generic file to upload model."""
    file_path: str
    file_size: int
    file_type: str  # "crash_dump", "jfr", etc.
    last_modified: datetime
    pod_name: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "file_path": self.file_path,
            "file_size": self.file_size,
            "file_type": self.file_type,
            "last_modified": self.last_modified.isoformat(),
            "pod_name": self.pod_name
        }


@dataclass
class CompressedFile:
    """Compressed file information."""
    original_path: str
    compressed_path: str
    original_size: int
    compressed_size: int
    compression_ratio: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "original_path": self.original_path,
            "compressed_path": self.compressed_path,
            "original_size": self.original_size,
            "compressed_size": self.compressed_size,
            "compression_ratio": self.compression_ratio
        }


@dataclass
class AWSCredentials:
    """AWS temporary credentials."""
    access_key_id: str
    secret_access_key: str
    session_token: str
    region: str
    expiry: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "access_key_id": self.access_key_id,
            "secret_access_key": self.secret_access_key,
            "session_token": self.session_token,
            "region": self.region,
            "expiry": self.expiry.isoformat()
        }


@dataclass
class S3UploadResult:
    """Result of S3 upload operation."""
    success: bool
    s3_key: str
    file_size: int
    upload_duration: timedelta
    error_message: Optional[str] = None
    etag: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "s3_key": self.s3_key,
            "file_size": self.file_size,
            "upload_duration_seconds": self.upload_duration.total_seconds(),
            "error_message": self.error_message,
            "etag": self.etag
        }


@dataclass
class S3VerificationResult:
    """Result of S3 upload verification."""
    verified: bool
    s3_key: str
    s3_size: Optional[int] = None
    etag: Optional[str] = None
    version_id: Optional[str] = None
    storage_class: Optional[str] = None
    last_modified: Optional[datetime] = None
    error_message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "verified": self.verified,
            "s3_key": self.s3_key,
            "s3_size": self.s3_size,
            "etag": self.etag,
            "version_id": self.version_id,
            "storage_class": self.storage_class,
            "last_modified": self.last_modified.isoformat() if self.last_modified else None,
            "error_message": self.error_message
        }


@dataclass
class DeletionResult:
    """Result of file deletion operation."""
    deleted: bool
    files: List[str]
    error_message: Optional[str] = None
    message: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "deleted": self.deleted,
            "files": self.files,
            "error_message": self.error_message,
            "message": self.message
        }


@dataclass
class CommandExecutionResult:
    """Result of command execution in pod."""
    exit_code: int
    stdout: str
    stderr: str
    duration: timedelta
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "duration_seconds": self.duration.total_seconds()
        }


@dataclass
class FileInfo:
    """File information from stat command."""
    size: int
    modified_time: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "size": self.size,
            "modified_time": self.modified_time.isoformat()
        }