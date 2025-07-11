"""
Crash dump specific activities for Temporal workflows.

This module provides activities for discovering crash dump files in CrateDB pods,
focusing on java_pid1.hprof and other heap dump files generated during container crashes.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Optional

import structlog
from temporalio import activity

from ..file_uploader.models import CrateDBPod, FileInfo
from ..file_uploader.utils import (
    execute_command_in_pod_simple,
    file_exists_in_pod,
    get_file_info_in_pod,
    standard_retry_policy,
)

from .models import CrashDumpFile, CrashDumpDiscoveryResult

logger = structlog.get_logger(__name__)


@activity.defn(name="discover_crash_dumps")
async def discover_crash_dumps(pod: CrateDBPod) -> CrashDumpDiscoveryResult:
    """
    Discover crash dump files in the specific pod container.
    
    This activity:
    1. First checks if java_pid1.hprof exists (most critical file)
    2. Returns early if no java_pid1.hprof - no upload needed
    3. If found, looks for additional .hprof files
    4. Returns discovery result with upload requirements
    
    Args:
        pod: Pod information where to look for crash dumps
        
    Returns:
        CrashDumpDiscoveryResult indicating if uploads are needed
    """
    
    activity.logger.info(
        "Starting crash dump discovery",
        pod=pod.name,
        namespace=pod.namespace,
        container=pod.container
    )
    
    # Send initial heartbeat
    activity.heartbeat({
        "stage": "discovery_start",
        "pod": pod.name,
        "namespace": pod.namespace
    })
    
    try:
        # First, check if heapdump directory exists
        heapdump_dir = "/resource/heapdump"
        dir_check_result = await _check_heapdump_directory(pod, heapdump_dir)
        
        if not dir_check_result["exists"]:
            activity.logger.info(
                "Heapdump directory not found - no crash dumps possible",
                pod=pod.name,
                directory=heapdump_dir,
                error=dir_check_result.get("error")
            )
            return CrashDumpDiscoveryResult(
                crash_dumps=[],
                requires_upload=False,
                message="Heapdump directory not found - no crash dumps possible"
            )
        
        # Check for java_pid1.hprof (most critical file)
        java_pid1_path = f"{heapdump_dir}/java_pid1.hprof"
        java_pid1_exists = await file_exists_in_pod(pod, java_pid1_path)
        
        if not java_pid1_exists:
            activity.logger.info(
                "No java_pid1.hprof found - container restart not caused by heap exhaustion",
                pod=pod.name,
                namespace=pod.namespace,
                checked_path=java_pid1_path,
                directory_contents=dir_check_result.get("contents", "")
            )
            return CrashDumpDiscoveryResult(
                crash_dumps=[],
                requires_upload=False,
                message="No java_pid1.hprof found - container restart not caused by heap exhaustion"
            )
        
        # java_pid1.hprof exists - this is critical!
        activity.logger.critical(
            "CRITICAL: java_pid1.hprof found - heap exhaustion crash dump detected",
            pod=pod.name,
            namespace=pod.namespace,
            file_path=java_pid1_path
        )
        
        # Send heartbeat with critical finding
        activity.heartbeat({
            "stage": "java_pid1_found",
            "pod": pod.name,
            "critical": True,
            "file_path": java_pid1_path
        })
        
        # Get detailed info for java_pid1.hprof
        java_pid1_info = await get_file_info_in_pod(pod, java_pid1_path)
        
        crash_dumps = [CrashDumpFile(
            pod_name=pod.name,
            file_path=java_pid1_path,
            file_size=java_pid1_info.size,
            last_modified=java_pid1_info.modified_time,
            file_type="java_pid1.hprof"
        )]
        
        activity.logger.info(
            "java_pid1.hprof details",
            pod=pod.name,
            file_path=java_pid1_path,
            file_size=java_pid1_info.size,
            modified_time=java_pid1_info.modified_time,
            size_mb=round(java_pid1_info.size / (1024 * 1024), 2)
        )
        
        # Look for additional .hprof files
        additional_dumps = await _find_additional_hprof_files(pod, heapdump_dir, java_pid1_path)
        crash_dumps.extend(additional_dumps)
        
        # Final discovery result
        total_size = sum(dump.file_size for dump in crash_dumps)
        total_size_mb = round(total_size / (1024 * 1024), 2)
        
        activity.logger.info(
            "Crash dump discovery completed",
            pod=pod.name,
            namespace=pod.namespace,
            crash_dump_count=len(crash_dumps),
            total_size_bytes=total_size,
            total_size_mb=total_size_mb,
            crash_dump_files=[dump.file_path for dump in crash_dumps]
        )
        
        # Send completion heartbeat
        activity.heartbeat({
            "stage": "discovery_complete",
            "pod": pod.name,
            "crash_dump_count": len(crash_dumps),
            "total_size_bytes": total_size,
            "requires_upload": True
        })
        
        return CrashDumpDiscoveryResult(
            crash_dumps=crash_dumps,
            requires_upload=True,
            message=f"Found {len(crash_dumps)} crash dump files requiring upload ({total_size_mb} MB total)"
        )
        
    except Exception as e:
        activity.logger.error(
            "Failed to discover crash dumps",
            pod=pod.name,
            namespace=pod.namespace,
            error=str(e),
            exc_info=True
        )
        
        # Send error heartbeat
        activity.heartbeat({
            "stage": "discovery_failed",
            "pod": pod.name,
            "error": str(e)
        })
        
        # Don't fail the workflow - just return empty result
        return CrashDumpDiscoveryResult(
            crash_dumps=[],
            requires_upload=False,
            message=f"Discovery failed: {str(e)}"
        )


async def _check_heapdump_directory(pod: CrateDBPod, heapdump_dir: str) -> dict:
    """Check if heapdump directory exists and is accessible."""
    try:
        # Use ls -la to check directory and get contents
        check_dir_command = ["ls", "-la", heapdump_dir]
        
        result = await execute_command_in_pod_simple(
            pod=pod,
            command=check_dir_command,
            timeout=timedelta(minutes=2)
        )
        
        if result.exit_code == 0:
            return {
                "exists": True,
                "contents": result.stdout,
                "error": None
            }
        else:
            return {
                "exists": False,
                "contents": "",
                "error": result.stderr
            }
            
    except Exception as e:
        return {
            "exists": False,
            "contents": "",
            "error": str(e)
        }


async def _find_additional_hprof_files(
    pod: CrateDBPod, 
    heapdump_dir: str, 
    exclude_path: str
) -> List[CrashDumpFile]:
    """Find additional .hprof files in the heapdump directory."""
    try:
        # Use find to locate all .hprof files
        find_command = ["find", heapdump_dir, "-name", "*.hprof", "-type", "f"]
        
        result = await execute_command_in_pod_simple(
            pod=pod,
            command=find_command,
            timeout=timedelta(minutes=2)
        )
        
        if result.exit_code != 0:
            activity.logger.warning(
                "Failed to find additional hprof files",
                pod=pod.name,
                directory=heapdump_dir,
                error=result.stderr
            )
            return []
        
        # Parse found files
        additional_dumps = []
        if result.stdout.strip():
            hprof_files = result.stdout.strip().split('\n')
            
            for hprof_file in hprof_files:
                hprof_file = hprof_file.strip()
                
                # Skip the java_pid1.hprof we already processed
                if hprof_file == exclude_path:
                    continue
                
                # Skip empty lines
                if not hprof_file:
                    continue
                
                try:
                    # Get file info
                    file_info = await get_file_info_in_pod(pod, hprof_file)
                    
                    additional_dumps.append(CrashDumpFile(
                        pod_name=pod.name,
                        file_path=hprof_file,
                        file_size=file_info.size,
                        last_modified=file_info.modified_time,
                        file_type="additional_hprof"
                    ))
                    
                    activity.logger.info(
                        "Found additional crash dump file",
                        pod=pod.name,
                        file_path=hprof_file,
                        file_size=file_info.size,
                        size_mb=round(file_info.size / (1024 * 1024), 2)
                    )
                    
                except Exception as e:
                    activity.logger.warning(
                        "Failed to get info for additional hprof file",
                        pod=pod.name,
                        file_path=hprof_file,
                        error=str(e)
                    )
                    continue
        
        return additional_dumps
        
    except Exception as e:
        activity.logger.warning(
            "Exception while finding additional hprof files",
            pod=pod.name,
            directory=heapdump_dir,
            error=str(e)
        )
        return []


@activity.defn(name="get_upload_credentials")
async def get_upload_credentials() -> dict:
    """
    Get AWS credentials for S3 upload.
    
    This is a placeholder activity - in the real implementation this would
    integrate with the existing AWS STS token generation from collec.py.
    
    Returns:
        Dictionary with AWS credentials
    """
    
    activity.logger.info("Getting AWS upload credentials")
    
    # TODO: Implement actual AWS STS token generation
    # This should integrate with the existing get_upload_credentials() function
    # from collec.py that handles AWS role assumption
    
    # For now, return a placeholder structure
    from datetime import datetime, timedelta
    
    return {
        "access_key_id": "PLACEHOLDER_ACCESS_KEY",
        "secret_access_key": "PLACEHOLDER_SECRET_KEY", 
        "session_token": "PLACEHOLDER_SESSION_TOKEN",
        "region": "us-east-1",
        "expiry": (datetime.now() + timedelta(hours=1)).isoformat()
    }