"""
Data models specific to crash dump upload functionality.

This module defines data structures used by the crash dump upload workflow,
extending the common file upload models for crash dump specific use cases.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

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
    last_modified: datetime
    file_type: str  # "java_pid1.hprof", "additional_hprof", etc.
    
    def to_file_upload(self) -> FileToUpload:
        """Convert to generic FileToUpload model."""
        return FileToUpload(
            file_path=self.file_path,
            file_size=self.file_size,
            file_type="crash_dump",
            last_modified=self.last_modified,
            pod_name=self.pod_name
        )


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


@dataclass
class CrashDumpUploadResult:
    """Final result of crash dump upload workflow."""
    success: bool
    processed_pods: List[str]
    uploaded_files: List[S3UploadResult]
    processing_results: List[CrashDumpProcessingResult]
    errors: List[str]
    message: str
    total_duration: timedelta
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