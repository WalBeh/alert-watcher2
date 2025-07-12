"""
Data models specific to crash dump upload functionality.

This module defines data structures used by the crash dump upload workflow,
extending the common file upload models for crash dump specific use cases.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Union

try:
    from ..file_uploader.models import FileToUpload, S3UploadResult, DeletionResult
except ImportError:
    from file_uploader.models import FileToUpload, S3UploadResult, DeletionResult


@dataclass
class CrashDumpFile:
    """Information about a crash dump file found in a pod."""
    pod_name: str
    file_path: str
    file_size: int
    last_modified: Optional[str]
    file_type: str  # "java_pid1.hprof", "additional_hprof", etc.
    
    def to_file_upload(self) -> FileToUpload:
        """Convert to generic FileToUpload model."""
        # Convert string back to datetime for FileToUpload model
        # Use current time if last_modified is None
        if self.last_modified:
            last_modified = datetime.fromisoformat(self.last_modified)
        else:
            last_modified = datetime.now()
        
        return FileToUpload(
            file_path=self.file_path,
            file_size=self.file_size,
            file_type="crash_dump",
            last_modified=last_modified,
            pod_name=self.pod_name
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "pod_name": self.pod_name,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "last_modified": self.last_modified,
            "file_type": self.file_type
        }


@dataclass
class CrashDumpDiscoveryResult:
    """Result of crash dump discovery operation."""
    crash_dumps: List[CrashDumpFile]
    requires_upload: bool
    message: str
    
    @property
    def total_size(self) -> int:
        """Total size of all crash dumps in bytes."""
        return sum(dump.file_size for dump in self.crash_dumps)
    
    @property
    def has_java_pid1(self) -> bool:
        """Check if java_pid1.hprof is present."""
        return any(dump.file_type == "java_pid1.hprof" for dump in self.crash_dumps)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "crash_dumps": [dump.to_dict() for dump in self.crash_dumps],
            "requires_upload": self.requires_upload,
            "message": self.message,
            "total_size": self.total_size,
            "has_java_pid1": self.has_java_pid1
        }


@dataclass
class CrashDumpProcessingResult:
    """Result of processing a single crash dump."""
    crash_dump: CrashDumpFile
    compressed_size: int
    upload_result: S3UploadResult
    verification_passed: bool
    deletion_result: Optional[DeletionResult] = None
    
    @property
    def success(self) -> bool:
        """Check if the entire processing was successful."""
        return (
            self.upload_result.success and
            self.verification_passed and
            (self.deletion_result is None or self.deletion_result.deleted)
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "crash_dump": self.crash_dump.to_dict(),
            "compressed_size": self.compressed_size,
            "upload_result": self.upload_result.to_dict(),
            "verification_passed": self.verification_passed,
            "deletion_result": self.deletion_result.to_dict() if self.deletion_result else None,
            "success": self.success
        }


@dataclass
class CrashDumpUploadResult:
    """Final result of crash dump upload workflow."""
    success: bool
    processed_pods: List[str]
    uploaded_files: List[S3UploadResult]
    processing_results: List[CrashDumpProcessingResult]
    errors: List[str]
    message: str
    total_duration_seconds: Optional[float]
    total_size_bytes: int
    
    @property
    def upload_count(self) -> int:
        """Number of successfully uploaded files."""
        return sum(1 for result in self.uploaded_files if result.success)
    
    @property
    def deletion_count(self) -> int:
        """Number of successfully deleted files."""
        return sum(
            1 for result in self.processing_results 
            if result.deletion_result and result.deletion_result.deleted
        )
    
    @property
    def total_uploaded_size(self) -> int:
        """Total size of successfully uploaded files."""
        return sum(
            result.upload_result.file_size 
            for result in self.processing_results 
            if result.upload_result.success
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "processed_pods": self.processed_pods,
            "uploaded_files": [result.to_dict() for result in self.uploaded_files],
            "processing_results": [result.to_dict() for result in self.processing_results],
            "errors": self.errors,
            "message": self.message,
            "total_duration_seconds": self.total_duration_seconds,
            "total_size_bytes": self.total_size_bytes,
            "upload_count": self.upload_count,
            "deletion_count": self.deletion_count,
            "total_uploaded_size": self.total_uploaded_size
        }