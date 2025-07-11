"""
Crash dump uploader module for handling CrateDB crash dump uploads.

This module provides specialized functionality for discovering, uploading,
and managing CrateDB crash dump files (primarily java_pid1.hprof) triggered
by CrateDBContainerRestart alerts.
"""

from .models import (
    CrashDumpFile,
    CrashDumpDiscoveryResult,
    CrashDumpProcessingResult,
    CrashDumpUploadResult,
)

__all__ = [
    "CrashDumpFile",
    "CrashDumpDiscoveryResult", 
    "CrashDumpProcessingResult",
    "CrashDumpUploadResult",
]