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


@dataclass
class FileToUpload:
    """Generic file to upload model."""
    file_path: str
    file_size: int
    file_type: str  # "crash_dump", "jfr", etc.
    last_modified: datetime
    pod_name: str


@dataclass
class CompressedFile:
    """Compressed file information."""
    original_path: str
    compressed_path: str
    original_size: int
    compressed_size: int
    compression_ratio: float


@dataclass
class AWSCredentials:
    """AWS temporary credentials."""
    access_key_id: str
    secret_access_key: str
    session_token: str
    region: str
    expiry: datetime


@dataclass
class S3UploadResult:
    """Result of S3 upload operation."""
    success: bool
    s3_key: str
    file_size: int
    upload_duration: timedelta
    error_message: Optional[str] = None
    etag: Optional[str] = None


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


@dataclass
class DeletionResult:
    """Result of file deletion operation."""
    deleted: bool
    files: List[str]
    error_message: Optional[str] = None
    message: Optional[str] = None


@dataclass
class CommandExecutionResult:
    """Result of command execution in pod."""
    exit_code: int
    stdout: str
    stderr: str
    duration: timedelta


@dataclass
class FileInfo:
    """File information from stat command."""
    size: int
    modified_time: datetime