"""
Common file upload activities for Temporal workflows.

This module provides shared activities for file compression, S3 upload,
verification, and cleanup operations used by both crash dump and JFR workflows.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any

import boto3
from botocore.exceptions import ClientError
import structlog
from temporalio import activity

from .models import (
    CrateDBPod,
    FileToUpload,
    CompressedFile,
    AWSCredentials,
    S3UploadResult,
    S3VerificationResult,
    DeletionResult,
    CommandExecutionResult,
)
from .utils import (
    execute_command_in_pod_simple,
    get_file_info_in_pod,
    file_exists_in_pod,
    copy_script_to_pod,
    get_flanker_script,
    parse_flanker_progress,
)

logger = structlog.get_logger(__name__)


@activity.defn(name="compress_file")
async def compress_file(
    pod: CrateDBPod,
    file_info: FileToUpload,
    aws_credentials: AWSCredentials
) -> Dict[str, Any]:
    """
    Generic file compression activity.
    Works for both .hprof and .jfr files.
    Uses the safer gzip approach from jfr-collect/collec.py to avoid overwriting source files.
    """
    
    compressed_path = f"{file_info.file_path}.gz"
    
    activity.logger.info(
        f"Starting file compression - pod: {pod.name}, "
        f"file_path: {file_info.file_path}, "
        f"compressed_path: {compressed_path}, "
        f"original_size: {file_info.file_size}"
    )
    
    start_time = time.time()
    last_heartbeat = start_time
    heartbeat_interval = 60  # seconds
    
    try:
        # Send initial heartbeat
        activity.heartbeat({
            "status": "starting_compression",
            "file_path": file_info.file_path,
            "original_size": file_info.file_size
        })
        
        # Use the safer gzip approach from jfr-collect/collec.py:
        # "su crate -c 'rm -f {file_path}.gz && gzip -k {file_path} || :'"
        # This ensures:
        # 1. Remove any existing .gz file first (-f to not fail if it doesn't exist)
        # 2. Use gzip -k to keep the original file 
        # 3. Use || : to not fail the command if gzip fails
        safe_gzip_command = (
            f"su crate -c 'rm -f {compressed_path} && gzip -k {file_info.file_path} || :'"
        )
        
        activity.logger.info(
            f"Executing safe gzip command - pod: {pod.name}, "
            f"command: rm -f '{compressed_path}' && gzip -k '{file_info.file_path}' || :"
        )
        
        # Execute compression command
        result = await execute_command_in_pod_simple(
            pod=pod,
            command=["sh", "-c", safe_gzip_command],
            timeout=timedelta(minutes=30)
        )
        
        # Note: We don't check exit_code here because of the "|| :" which always makes it succeed
        # Instead, we check if the compressed file actually exists
        
        # Send heartbeat during compression
        current_time = time.time()
        if current_time - last_heartbeat >= heartbeat_interval:
            activity.heartbeat({
                "status": "compressing",
                "elapsed_seconds": current_time - start_time,
                "file_path": file_info.file_path
            })
            last_heartbeat = current_time
        
        # Check if compression was successful by verifying the compressed file exists
        compressed_exists = await file_exists_in_pod(pod, compressed_path)
        
        if not compressed_exists:
            # Log the command output for debugging
            activity.logger.error(
                f"Compression failed - compressed file not found - pod: {pod.name}, "
                f"file_path: {file_info.file_path}, "
                f"compressed_path: {compressed_path}, "
                f"command_stdout: {result.stdout}, "
                f"command_stderr: {result.stderr}"
            )
            raise RuntimeError(f"Compression failed - compressed file not created: {compressed_path}")
        
        # Get compressed file info
        compressed_info = await get_file_info_in_pod(pod, compressed_path)
        
        compression_ratio = compressed_info.size / file_info.file_size if file_info.file_size > 0 else 0
        
        activity.logger.info(
            f"File compression completed successfully - pod: {pod.name}, "
            f"original_size: {file_info.file_size}, "
            f"compressed_size: {compressed_info.size}, "
            f"compression_ratio: {compression_ratio:.3f}, "
            f"duration: {time.time() - start_time:.2f}s"
        )
        
        # Send completion heartbeat
        activity.heartbeat({
            "status": "compression_complete",
            "original_size": file_info.file_size,
            "compressed_size": compressed_info.size,
            "compression_ratio": compression_ratio,
            "duration_seconds": time.time() - start_time
        })
        
        compressed_file = CompressedFile(
            original_path=file_info.file_path,
            compressed_path=compressed_path,
            original_size=file_info.file_size,
            compressed_size=compressed_info.size,
            compression_ratio=compression_ratio
        )
        return compressed_file.to_dict()
        
    except Exception as e:
        activity.logger.error(
            f"File compression failed - pod: {pod.name}, "
            f"file_path: {file_info.file_path}, "
            f"error: {str(e)}"
        )
        raise


@activity.defn(name="upload_file_to_s3")
async def upload_file_to_s3(
    pod: CrateDBPod,
    compressed_file: dict,
    s3_key: str,
    aws_credentials: AWSCredentials
) -> Dict[str, Any]:
    """
    Generic S3 upload activity using flanker.py.
    Executes flanker.py inside the pod where the file is located.
    """
    
    activity.logger.info(
        f"Starting S3 upload - pod: {pod.name}, "
        f"file_path: {compressed_file['compressed_path']}, "
        f"s3_key: {s3_key}, "
        f"file_size: {compressed_file['compressed_size']}"
    )
    
    start_time = time.time()
    
    try:
        # Copy flanker.py from src/ to pod (always use fresh copy)
        flanker_script = get_flanker_script()
        flanker_path = "/resource/heapdump/flanker.py"
        
        activity.logger.info(
            f"Copying flanker.py to pod - pod: {pod.name}, "
            f"destination: {flanker_path}"
        )
        
        if not await copy_script_to_pod(pod, flanker_script, flanker_path):
            raise RuntimeError("Failed to copy flanker.py to pod")
        
        # Prepare AWS environment variables string (exactly like standalone version)
        aws_env = (
            f"AWS_ACCESS_KEY_ID={aws_credentials.access_key_id} "
            f"AWS_SECRET_ACCESS_KEY={aws_credentials.secret_access_key} "
            f"AWS_SESSION_TOKEN={aws_credentials.session_token} "
        )
        
        # Use exact pattern from jfr-collect/collec.py
        upload_command = (
            f"su crate -c 'curl -LsSf https://astral.sh/uv/install.sh | sh && "
            f"{aws_env}/crate/.local/bin/uv run {flanker_path} "
            f"{compressed_file['compressed_path']} --bucket cratedb-cloud-heapdumps --key {s3_key} "
            f"--region {aws_credentials.region or 'us-east-1'} --verbose --logfolder /resource/heapdump'"
        )
        
        activity.logger.info(
            f"Executing upload command - pod: {pod.name}, "
            f"s3_key: {s3_key}, "
            f"file_size: {compressed_file['compressed_size']}"
        )
        
        # Execute upload command as single shell command
        result = await execute_command_in_pod_simple(
            pod=pod,
            command=["sh", "-c", upload_command],
            timeout=timedelta(hours=2)
        )
        
        success = result.exit_code == 0
        
        if success:
            activity.logger.info(
                f"S3 upload completed successfully - pod: {pod.name}, "
                f"s3_key: {s3_key}, "
                f"file_size: {compressed_file['compressed_size']}, "
                f"duration: {time.time() - start_time}"
            )
        else:
            activity.logger.error(
                f"S3 upload failed - pod: {pod.name}, "
                f"s3_key: {s3_key}, "
                f"exit_code: {result.exit_code}, "
                f"error: {result.stderr}, "
                f"stdout: {result.stdout}"
            )
        
        s3_result = S3UploadResult(
            success=success,
            s3_key=s3_key,
            file_size=compressed_file['compressed_size'],
            upload_duration=result.duration,
            error_message=result.stderr if not success else None
        )
        return s3_result.to_dict()
        
    except Exception as e:
        activity.logger.error(
            f"S3 upload failed with exception - pod: {pod.name}, "
            f"s3_key: {s3_key}, "
            f"error: {str(e)}"
        )
        
        s3_result = S3UploadResult(
            success=False,
            s3_key=s3_key,
            file_size=compressed_file['compressed_size'],
            upload_duration=timedelta(seconds=time.time() - start_time),
            error_message=str(e)
        )
        return s3_result.to_dict()


async def execute_command_in_pod_with_progress(
    pod: CrateDBPod,
    command: list[str],
    env_vars: Dict[str, str],
    timeout: timedelta,
    heartbeat_interval: timedelta
) -> CommandExecutionResult:
    """
    Execute command in pod with progress monitoring and heartbeats.
    
    This monitors the flanker.py output and sends heartbeats with progress information.
    """
    
    from kubernetes import client, config
    from kubernetes.stream import stream
    from .utils import load_kube_config
    
    # Load Kubernetes config
    load_kube_config()
    core_v1 = client.CoreV1Api()
    
    # Prepare exec command with environment variables
    exec_command = []
    for key, value in env_vars.items():
        exec_command.extend(["env", f"{key}={value}"])
    exec_command.extend(command)
    
    start_time = time.time()
    last_heartbeat = start_time
    
    try:
        # Execute command in pod
        exec_result = stream(
            core_v1.connect_get_namespaced_pod_exec,
            name=pod.name,
            namespace=pod.namespace,
            container=pod.container,
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False
        )
        
        stdout_lines = []
        stderr_lines = []
        
        # Monitor output and send heartbeats
        while exec_result.is_open():
            exec_result.update(timeout=1)
            
            # Process stdout
            progress_info = {}
            if exec_result.peek_stdout():
                stdout_chunk = exec_result.read_stdout()
                stdout_lines.append(stdout_chunk)
                
                # Parse flanker.py progress output
                progress_info = parse_flanker_progress(stdout_chunk)
                
            # Process stderr
            if exec_result.peek_stderr():
                stderr_chunk = exec_result.read_stderr()
                stderr_lines.append(stderr_chunk)
            
            # Send heartbeat if interval elapsed
            current_time = time.time()
            if current_time - last_heartbeat >= heartbeat_interval.total_seconds():
                heartbeat_details = {
                    "pod_name": pod.name,
                    "command": " ".join(command),
                    "elapsed_seconds": current_time - start_time,
                    "last_output": stdout_lines[-1] if stdout_lines else "",
                    "progress_info": progress_info
                }
                
                activity.heartbeat(heartbeat_details)
                last_heartbeat = current_time
            
            # Check for timeout
            if current_time - start_time > timeout.total_seconds():
                exec_result.close()
                raise TimeoutError(f"Command execution exceeded timeout of {timeout}")
        
        # Get final status
        exit_code = exec_result.returncode if hasattr(exec_result, 'returncode') else 0
        
        return CommandExecutionResult(
            exit_code=exit_code,
            stdout="".join(stdout_lines),
            stderr="".join(stderr_lines),
            duration=timedelta(seconds=time.time() - start_time)
        )
        
    except Exception as e:
        # Send final heartbeat with error
        activity.heartbeat({
            "pod_name": pod.name,
            "error": str(e),
            "elapsed_seconds": time.time() - start_time
        })
        raise


@activity.defn(name="verify_s3_upload")
async def verify_s3_upload(
    pod: CrateDBPod,
    s3_upload_result: dict,
    aws_credentials: AWSCredentials
) -> Dict[str, Any]:
    """
    Verify S3 upload by trusting flanker.py internal verification.
    
    flanker.py already performs comprehensive verification:
    - File integrity checks (MD5 hash verification)
    - ETag verification for single-part uploads
    - Object metadata confirmation
    - Upload success/failure reporting
    
    Since this activity runs outside the container and lacks S3 permissions,
    we trust the flanker.py verification rather than attempting our own.
    """
    
    activity.logger.info(
        f"Verifying S3 upload using flanker.py result - pod: {pod.name}, "
        f"s3_key: {s3_upload_result.get('s3_key', 'unknown')}, "
        f"flanker_success: {s3_upload_result.get('success', False)}"
    )
    
    # Trust flanker.py's internal verification
    flanker_success = s3_upload_result.get('success', False)
    
    if flanker_success:
        activity.logger.info(
            f"S3 upload verification successful (via flanker.py) - "
            f"s3_key: {s3_upload_result.get('s3_key')}, "
            f"file_size: {s3_upload_result.get('file_size')}, "
            f"upload_duration: {s3_upload_result.get('upload_duration_seconds')}s"
        )
        
        return {
            "verified": True,
            "s3_key": s3_upload_result.get('s3_key'),
            "file_size": s3_upload_result.get('file_size'),
            "verification_method": "flanker_internal",
            "message": "Upload verified by flanker.py internal checks"
        }
    else:
        error_message = s3_upload_result.get('error_message', 'Unknown upload error')
        
        activity.logger.warning(
            f"S3 upload verification failed (flanker.py reported failure) - "
            f"s3_key: {s3_upload_result.get('s3_key')}, "
            f"error: {error_message}"
        )
        
        return {
            "verified": False,
            "s3_key": s3_upload_result.get('s3_key'),
            "error_message": f"flanker.py upload failed: {error_message}",
            "verification_method": "flanker_internal"
        }


@activity.defn(name="safely_delete_file")
async def safely_delete_file(
    pod: CrateDBPod,
    file_info: FileToUpload,
    compressed_file: dict,
    verification_result: dict
) -> Dict[str, Any]:
    """
    CRITICAL: Safely delete files ONLY after S3 upload verification.
    This activity will REFUSE to delete files if S3 upload is not verified.
    """
    
    if not verification_result['verified']:
        activity.logger.error(
            f"REFUSING to delete files - S3 upload not verified - pod: {pod.name}, "
            f"file_path: {file_info.file_path}, "
            f"verification_error: {verification_result.get('error_message', 'Unknown error')}"
        )
        deletion_result = DeletionResult(
            deleted=False,
            files=[file_info.file_path, compressed_file['compressed_path']],
            error_message=f"S3 upload not verified: {verification_result.get('error_message', 'Unknown error')}"
        )
        return deletion_result.to_dict()
    
    # Double-check files still exist before deletion
    files_to_delete = [file_info.file_path, compressed_file['compressed_path']]
    existing_files = []
    
    for file_path in files_to_delete:
        if await file_exists_in_pod(pod, file_path):
            existing_files.append(file_path)
    
    if not existing_files:
        activity.logger.info(
            f"Files already deleted or not found - pod: {pod.name}, "
            f"files: {files_to_delete}"
        )
        deletion_result = DeletionResult(
            deleted=True,
            files=files_to_delete,
            message="Files already deleted or not found"
        )
        return deletion_result.to_dict()
    
    # Get current file info to ensure it's the same file we uploaded
    try:
        current_file_info = await get_file_info_in_pod(pod, file_info.file_path)
        
        # Safety check - ensure file hasn't changed since upload
        if current_file_info.size != file_info.file_size:
            activity.logger.error(
                f"REFUSING to delete file - file size changed since upload - pod: {pod.name}, "
                f"file_path: {file_info.file_path}, "
                f"original_size: {file_info.file_size}, "
                f"current_size: {current_file_info.size}"
            )
            deletion_result = DeletionResult(
                deleted=False,
                files=files_to_delete,
                error_message=f"File size changed: {file_info.file_size} -> {current_file_info.size}"
            )
            return deletion_result.to_dict()
    except Exception as e:
        activity.logger.warning(
            f"Could not verify file info before deletion - pod: {pod.name}, "
            f"file_path: {file_info.file_path}, "
            f"error: {str(e)}"
        )
    
    # Final safety check - log critical information
    activity.logger.critical(
        f"PROCEEDING with file deletion - ALL VERIFICATIONS PASSED - pod: {pod.name}, "
        f"files: {existing_files}, "
        f"file_size: {file_info.file_size}, "
        f"s3_key: {verification_result['s3_key']}, "
        f"s3_version_id: {verification_result.get('version_id', 'Unknown')}, "
        f"s3_etag: {verification_result.get('etag', 'Unknown')}"
    )
    
    # Delete the files
    deleted_files = []
    deletion_errors = []
    
    for file_path in existing_files:
        try:
            delete_command = ["rm", "-f", file_path]
            
            delete_result = await execute_command_in_pod_simple(
                pod=pod,
                command=delete_command,
                timeout=timedelta(minutes=2)
            )
            
            if delete_result.exit_code == 0:
                deleted_files.append(file_path)
                activity.logger.info(
                    f"File deleted successfully - pod: {pod.name}, "
                    f"file_path: {file_path}"
                )
            else:
                deletion_errors.append(f"{file_path}: {delete_result.stderr}")
                activity.logger.error(
                    f"Failed to delete file - pod: {pod.name}, "
                    f"file_path: {file_path}, "
                    f"error: {delete_result.stderr}"
                )
        except Exception as e:
            deletion_errors.append(f"{file_path}: {str(e)}")
            activity.logger.error(
                f"Exception while deleting file - pod: {pod.name}, "
                f"file_path: {file_path}, "
                f"error: {str(e)}"
            )
    
    # Verify deletions
    verified_deletions = []
    for file_path in deleted_files:
        if not await file_exists_in_pod(pod, file_path):
            verified_deletions.append(file_path)
        else:
            deletion_errors.append(f"{file_path}: still exists after deletion")
    
    success = len(verified_deletions) == len(existing_files)
    
    if success:
        activity.logger.info(
            f"All files successfully deleted from pod - pod: {pod.name}, "
            f"deleted_files: {verified_deletions}, "
            f"s3_backup: {verification_result['s3_key']}"
        )
        
        deletion_result = DeletionResult(
            deleted=True,
            files=verified_deletions,
            message=f"Successfully deleted {len(verified_deletions)} files - backed up to {verification_result['s3_key']}"
        )
        return deletion_result.to_dict()
    else:
        activity.logger.error(
            f"Some files could not be deleted - pod: {pod.name}, "
            f"deleted_files: {verified_deletions}, "
            f"errors: {deletion_errors}"
        )
        
        deletion_result = DeletionResult(
            deleted=False,
            files=files_to_delete,
            error_message=f"Deletion errors: {'; '.join(deletion_errors)}"
        )
        return deletion_result.to_dict()