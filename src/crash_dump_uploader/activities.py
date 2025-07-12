"""
Crash dump specific activities for Temporal workflows.

This module provides activities for discovering crash dump files in CrateDB pods,
focusing on java_pid1.hprof and other heap dump files generated during container crashes.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import List, Optional

import os
import boto3
import botocore.exceptions
import structlog
from temporalio import activity

from file_uploader.models import CrateDBPod, FileInfo
from file_uploader.utils import (
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
    3. If found, looks for additional .hprof and .jfr files (uncompressed only)
    4. Returns discovery result with upload requirements

    Args:
        pod: Pod information where to look for crash dumps

    Returns:
        CrashDumpDiscoveryResult indicating if uploads are needed
    """

    activity.logger.info(
        f"Starting crash dump discovery - pod: {pod.name}, "
        f"namespace: {pod.namespace}, container: {pod.container}"
    )
    
    # Debug: Log the exact pod information
    activity.logger.info(
        f"DEBUG: Crash dump discovery details - pod_name: '{pod.name}', "
        f"namespace: '{pod.namespace}', container: '{pod.container}'"
    )

    # Send initial heartbeat
    activity.heartbeat({
        "stage": "discovery_start",
        "pod": pod.name,
        "namespace": pod.namespace
    })

    try:
        # Check the heapdump directory
        heapdump_dir = "/resource/heapdump"
        
        activity.logger.info(
            f"DEBUG: About to check heapdump directory - pod: {pod.name}, directory: {heapdump_dir}"
        )
        
        dir_check_result = await _check_heapdump_directory(pod, heapdump_dir)

        activity.logger.info(
            f"Heapdump directory check - pod: {pod.name}, directory: {heapdump_dir}, "
            f"exists: {dir_check_result['exists']}, contents: {dir_check_result.get('contents', 'N/A')}"
        )
        
        # Debug: Log the raw directory check result
        activity.logger.info(
            f"DEBUG: Raw directory check result - pod: {pod.name}, result: {dir_check_result}"
        )

        if not dir_check_result["exists"]:
            activity.logger.warning(
                f"Heapdump directory not found - no crash dumps possible - pod: {pod.name}, "
                f"directory: {heapdump_dir}, error: {dir_check_result.get('error')}"
            )
            return CrashDumpDiscoveryResult(
                crash_dumps=[],
                requires_upload=False,
                message="Heapdump directory not found - no crash dumps possible"
            )

        # Check for java_pid1.hprof (most critical file)
        java_pid1_path = f"{heapdump_dir}/java_pid1.hprof"
        
        activity.logger.info(
            f"DEBUG: About to check java_pid1.hprof existence - pod: {pod.name}, file_path: {java_pid1_path}"
        )
        
        java_pid1_exists = await file_exists_in_pod(pod, java_pid1_path)

        activity.logger.info(
            f"java_pid1.hprof existence check - pod: {pod.name}, file_path: {java_pid1_path}, "
            f"exists: {java_pid1_exists}, directory_contents: {dir_check_result.get('contents', 'N/A')}"
        )
        
        # Debug: Log detailed existence check
        activity.logger.info(
            f"DEBUG: File existence check result - pod: {pod.name}, "
            f"file_path: '{java_pid1_path}', exists: {java_pid1_exists}"
        )

        if not java_pid1_exists:
            activity.logger.info(
                f"No java_pid1.hprof found - container restart not caused by heap exhaustion - "
                f"pod: {pod.name}, namespace: {pod.namespace}, checked_path: {java_pid1_path}"
            )
            return CrashDumpDiscoveryResult(
                crash_dumps=[],
                requires_upload=False,
                message="No java_pid1.hprof found - container restart not caused by heap exhaustion"
            )

        # Get detailed info for java_pid1.hprof
        java_pid1_info = await get_file_info_in_pod(pod, java_pid1_path)
        
        # java_pid1.hprof exists - this is critical!
        activity.logger.critical(
            f"CRITICAL: java_pid1.hprof found - heap exhaustion crash dump detected - "
            f"pod: {pod.name}, namespace: {pod.namespace}, file_path: {java_pid1_path}, "
            f"size_bytes: {java_pid1_info.size}, size_mb: {round(java_pid1_info.size / (1024 * 1024), 2)}"
        )

        # Send heartbeat with critical finding
        activity.heartbeat({
            "stage": "java_pid1_found",
            "pod": pod.name,
            "critical": True,
            "file_path": java_pid1_path,
            "file_size": java_pid1_info.size
        })

        crash_dumps = [CrashDumpFile(
            pod_name=pod.name,
            file_path=java_pid1_path,
            file_size=java_pid1_info.size,
            last_modified=java_pid1_info.modified_time.isoformat() if java_pid1_info.modified_time else None,
            file_type="java_pid1.hprof"
        )]

        # Look for additional .hprof and .jfr files (uncompressed only)
        additional_dumps = await _find_additional_crash_dump_files(pod, heapdump_dir, java_pid1_path)
        crash_dumps.extend(additional_dumps)

        # Log details about all found crash dumps
        for dump in crash_dumps:
            activity.logger.info(
                f"Crash dump file details - pod: {pod.name}, namespace: {pod.namespace}, "
                f"file_path: {dump.file_path}, file_size: {dump.file_size}, "
                f"modified_time: {dump.last_modified}, size_mb: {round(dump.file_size / (1024 * 1024), 2)}, "
                f"file_type: {dump.file_type}"
            )

        # Final discovery result
        total_size = sum(dump.file_size for dump in crash_dumps)
        total_size_mb = round(total_size / (1024 * 1024), 2)

        activity.logger.info(
            f"Crash dump discovery completed - pod: {pod.name}, namespace: {pod.namespace}, "
            f"crash_dump_count: {len(crash_dumps)}, total_size_bytes: {total_size}, "
            f"total_size_mb: {total_size_mb}, crash_dump_files: {[dump.file_path for dump in crash_dumps]}"
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
            f"Failed to discover crash dumps - pod: {pod.name}, namespace: {pod.namespace}, "
            f"error: {str(e)}", exc_info=True
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

        activity.logger.info(
            f"DEBUG: Executing directory check command - pod: {pod.name}, "
            f"command: {check_dir_command}, directory: {heapdump_dir}"
        )

        result = await execute_command_in_pod_simple(
            pod=pod,
            command=check_dir_command,
            timeout=timedelta(minutes=2)
        )

        activity.logger.info(
            f"DEBUG: Directory check command result - pod: {pod.name}, "
            f"exit_code: {result.exit_code}, stdout: '{result.stdout}', stderr: '{result.stderr}'"
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
        activity.logger.error(
            f"DEBUG: Exception in directory check - pod: {pod.name}, "
            f"directory: {heapdump_dir}, error: {str(e)}"
        )
        return {
            "exists": False,
            "contents": "",
            "error": str(e)
        }


async def _find_additional_crash_dump_files(
    pod: CrateDBPod,
    heapdump_dir: str,
    exclude_path: str
) -> List[CrashDumpFile]:
    """Find additional .hprof and .jfr files (uncompressed only) in the heapdump directory."""
    try:
        # Use find to locate all .hprof and .jfr files, but exclude .gz files
        find_command = ["find", heapdump_dir, "-type", "f", "(", "-name", "*.hprof", "-o", "-name", "*.jfr", ")", "!", "-name", "*.gz"]

        result = await execute_command_in_pod_simple(
            pod=pod,
            command=find_command,
            timeout=timedelta(minutes=2)
        )

        if result.exit_code != 0:
            activity.logger.warning(
                f"Failed to find additional crash dump files - pod: {pod.name}, "
                f"directory: {heapdump_dir}, error: {result.stderr}"
            )
            return []

        # Parse found files
        additional_dumps = []
        if result.stdout.strip():
            crash_dump_files = result.stdout.strip().split('\n')

            for crash_dump_file in crash_dump_files:
                crash_dump_file = crash_dump_file.strip()

                # Skip the java_pid1.hprof we already processed
                if crash_dump_file == exclude_path:
                    continue

                # Skip empty lines
                if not crash_dump_file:
                    continue

                try:
                    # Get file info
                    file_info = await get_file_info_in_pod(pod, crash_dump_file)

                    # Determine file type based on extension
                    if crash_dump_file.endswith('.hprof'):
                        file_type = "additional_hprof"
                    elif crash_dump_file.endswith('.jfr'):
                        file_type = "jfr"
                    else:
                        file_type = "unknown"

                    additional_dumps.append(CrashDumpFile(
                        pod_name=pod.name,
                        file_path=crash_dump_file,
                        file_size=file_info.size,
                        last_modified=file_info.modified_time.isoformat() if file_info.modified_time else None,
                        file_type=file_type
                    ))

                    activity.logger.info(
                        f"Found additional crash dump file - pod: {pod.name}, file_path: {crash_dump_file}, "
                        f"file_size: {file_info.size}, size_mb: {round(file_info.size / (1024 * 1024), 2)}, "
                        f"file_type: {file_type}"
                    )

                except Exception as e:
                    activity.logger.warning(
                        f"Failed to get info for additional crash dump file - pod: {pod.name}, "
                        f"file_path: {crash_dump_file}, error: {str(e)}"
                    )
                    continue

        return additional_dumps

    except Exception as e:
        activity.logger.warning(
            f"Exception while finding additional crash dump files - pod: {pod.name}, "
            f"directory: {heapdump_dir}, error: {str(e)}"
        )
        return []


async def _find_all_crash_dump_files(pod: CrateDBPod, heapdump_dir: str) -> List[CrashDumpFile]:
    """Find all .hprof and .jfr files (uncompressed only) in the heapdump directory."""
    try:
        # Use find to locate all .hprof and .jfr files, but exclude .gz files
        find_command = ["find", heapdump_dir, "-type", "f", "(", "-name", "*.hprof", "-o", "-name", "*.jfr", ")", "!", "-name", "*.gz"]

        result = await execute_command_in_pod_simple(
            pod=pod,
            command=find_command,
            timeout=timedelta(minutes=2)
        )

        if result.exit_code != 0:
            activity.logger.warning(
                f"Failed to find all crash dump files - pod: {pod.name}, "
                f"directory: {heapdump_dir}, error: {result.stderr}"
            )
            return []

        # Parse found files
        all_dumps = []
        if result.stdout.strip():
            crash_dump_files = result.stdout.strip().split('\n')

            for crash_dump_file in crash_dump_files:
                crash_dump_file = crash_dump_file.strip()

                # Skip empty lines
                if not crash_dump_file:
                    continue

                try:
                    # Get file info
                    file_info = await get_file_info_in_pod(pod, crash_dump_file)

                    # Determine file type based on filename and extension
                    if crash_dump_file.endswith("java_pid1.hprof"):
                        file_type = "java_pid1.hprof"
                    elif crash_dump_file.endswith('.hprof'):
                        file_type = "additional_hprof"
                    elif crash_dump_file.endswith('.jfr'):
                        file_type = "jfr"
                    else:
                        file_type = "unknown"

                    all_dumps.append(CrashDumpFile(
                        pod_name=pod.name,
                        file_path=crash_dump_file,
                        file_size=file_info.size,
                        last_modified=file_info.modified_time.isoformat() if file_info.modified_time else None,
                        file_type=file_type
                    ))

                    activity.logger.info(
                        f"Found crash dump file - pod: {pod.name}, file_path: {crash_dump_file}, "
                        f"file_size: {file_info.size}, size_mb: {round(file_info.size / (1024 * 1024), 2)}, "
                        f"file_type: {file_type}"
                    )

                except Exception as e:
                    activity.logger.warning(
                        f"Failed to get info for crash dump file - pod: {pod.name}, "
                        f"file_path: {crash_dump_file}, error: {str(e)}"
                    )
                    continue

        return all_dumps

    except Exception as e:
        activity.logger.warning(
            f"Exception while finding all crash dump files - pod: {pod.name}, "
            f"directory: {heapdump_dir}, error: {str(e)}"
        )
        return []


@activity.defn(name="get_upload_credentials")
async def get_upload_credentials(
    role_session_name: str = "crash-dump-upload-session",
    duration_seconds: int = 3600
) -> dict:
    """
    Get AWS credentials for S3 upload by assuming the heapdump upload role.
    
    This activity uses the current user's AWS credentials to assume an STS role
    that has permissions to upload files to the S3 bucket.

    Args:
        role_session_name: Identifier for the STS session
        duration_seconds: Duration of the session in seconds (max 3600)

    Returns:
        Dictionary with AWS credentials:
            - access_key_id: AWS access key ID
            - secret_access_key: AWS secret access key  
            - session_token: AWS session token
            - region: AWS region
            - expiry: Expiration timestamp (ISO format)

    Raises:
        Exception: If role assumption fails
    """

    activity.logger.info(
        f"Getting AWS upload credentials via STS role assumption - "
        f"session_name: {role_session_name}, duration: {duration_seconds}s"
    )

    # Role ARN for the upload role - configurable via environment variable
    role_arn = os.getenv(
        "AWS_HEAPDUMP_UPLOAD_ROLE_ARN", 
        "arn:aws:iam::538162834475:role/heapdump-upload-role"
    )

    try:
        # Create an STS client using current AWS credentials
        session = boto3.Session()
        sts_client = session.client("sts")

        activity.logger.info(f"Assuming AWS role: {role_arn}")

        # Send heartbeat before role assumption
        activity.heartbeat({
            "stage": "assuming_role",
            "role_arn": role_arn,
            "session_name": role_session_name
        })

        # Assume the role
        response = sts_client.assume_role(
            RoleArn=role_arn,
            RoleSessionName=role_session_name,
            DurationSeconds=duration_seconds,
        )

        # Extract credentials from response
        credentials = response["Credentials"]

        # Log success (without exposing sensitive data)
        expiry_time = credentials["Expiration"]
        current_time = datetime.now(expiry_time.tzinfo)
        hours_valid = (expiry_time - current_time).total_seconds() / 3600

        activity.logger.info(
            f"Successfully obtained AWS STS credentials - "
            f"valid_until: {expiry_time.isoformat()}, "
            f"hours_remaining: {hours_valid:.2f}, "
            f"access_key_id: {credentials['AccessKeyId'][:8]}..."
        )

        # Send success heartbeat
        activity.heartbeat({
            "stage": "credentials_obtained",
            "expiry": expiry_time.isoformat(),
            "hours_valid": round(hours_valid, 2)
        })

        # Get AWS region from environment or use default
        aws_region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        
        # Return credentials in the expected format
        return {
            "access_key_id": credentials["AccessKeyId"],
            "secret_access_key": credentials["SecretAccessKey"],
            "session_token": credentials["SessionToken"],
            "region": aws_region,
            "expiry": expiry_time.isoformat()
        }

    except botocore.exceptions.ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "Unknown")
        error_message = str(e)

        activity.logger.error(
            f"Failed to assume AWS role - "
            f"role_arn: {role_arn}, "
            f"error_code: {error_code}, "
            f"error: {error_message}"
        )

        # Send error heartbeat
        activity.heartbeat({
            "stage": "credentials_failed",
            "error_code": error_code,
            "error": error_message
        })

        # Handle specific error cases
        if "MultiFactorAuthentication" in error_message:
            raise Exception(f"MFA is required for role assumption: {role_arn}")
        elif "AccessDenied" in error_code:
            raise Exception(f"Access denied when assuming role: {role_arn}. Check IAM permissions.")
        elif "InvalidUserID.NotFound" in error_code:
            raise Exception(f"AWS user not found. Check AWS credentials configuration.")
        else:
            raise Exception(f"AWS role assumption failed ({error_code}): {error_message}")

    except Exception as e:
        activity.logger.error(
            f"Unexpected error during AWS credential generation - error: {str(e)}"
        )

        # Send error heartbeat
        activity.heartbeat({
            "stage": "credentials_failed",
            "error": str(e)
        })

        raise Exception(f"Failed to get AWS upload credentials: {str(e)}")
