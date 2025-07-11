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
) -> CompressedFile:
    """
    Generic file compression activity.
    Works for both .hprof and .jfr files.
    """
    
    compressed_path = f"{file_info.file_path}.gz"
    
    # Use gzip to compress the file
    compress_command = ["gzip", "-c", file_info.file_path]
    redirect_command = ["sh", "-c", f"gzip -c '{file_info.file_path}' > '{compressed_path}'"]
    
    activity.logger.info(
        "Starting file compression",
        pod=pod.name,
        file_path=file_info.file_path,
        compressed_path=compressed_path,
        original_size=file_info.file_size
    )
    
    start_time = time.time()
    last_heartbeat = start_time
    heartbeat_interval = 60  # seconds
    
    try:
        # Execute compression command
        result = await execute_command_in_pod_simple(
            pod=pod,
            command=redirect_command,
            timeout=timedelta(minutes=30)
        )
        
        if result.exit_code != 0:
            raise RuntimeError(f"Compression failed: {result.stderr}")
        
        # Send heartbeat during compression
        current_time = time.time()
        if current_time - last_heartbeat >= heartbeat_interval:
            activity.heartbeat({
                "status": "compressing",
                "elapsed_seconds": current_time - start_time,
                "file_path": file_info.file_path
            })
            last_heartbeat = current_time
        
        # Get compressed file info
        compressed_info = await get_file_info_in_pod(pod, compressed_path)
        
        compression_ratio = compressed_info.size / file_info.file_size if file_info.file_size > 0 else 0
        
        activity.logger.info(
            "File compression completed",
            pod=pod.name,
            original_size=file_info.file_size,
            compressed_size=compressed_info.size,
            compression_ratio=compression_ratio,
            duration=time.time() - start_time
        )
        
        return CompressedFile(
            original_path=file_info.file_path,
            compressed_path=compressed_path,
            original_size=file_info.file_size,
            compressed_size=compressed_info.size,
            compression_ratio=compression_ratio
        )
        
    except Exception as e:
        activity.logger.error(
            "File compression failed",
            pod=pod.name,
            file_path=file_info.file_path,
            error=str(e)
        )
        raise


@activity.defn(name="upload_file_to_s3")
async def upload_file_to_s3(
    pod: CrateDBPod,
    compressed_file: CompressedFile,
    s3_key: str,
    aws_credentials: AWSCredentials
) -> S3UploadResult:
    """
    Generic S3 upload activity using flanker.py.
    Executes flanker.py inside the pod where the file is located.
    """
    
    activity.logger.info(
        "Starting S3 upload",
        pod=pod.name,
        file_path=compressed_file.compressed_path,
        s3_key=s3_key,
        file_size=compressed_file.compressed_size
    )
    
    start_time = time.time()
    
    try:
        # Copy flanker.py to pod
        flanker_script = get_flanker_script()
        flanker_path = "/tmp/flanker.py"
        
        if not await copy_script_to_pod(pod, flanker_script, flanker_path):
            raise RuntimeError("Failed to copy flanker.py to pod")
        
        # Prepare environment variables for AWS credentials
        env_vars = {
            "AWS_ACCESS_KEY_ID": aws_credentials.access_key_id,
            "AWS_SECRET_ACCESS_KEY": aws_credentials.secret_access_key,
            "AWS_SESSION_TOKEN": aws_credentials.session_token,
            "AWS_DEFAULT_REGION": aws_credentials.region
        }
        
        # Execute flanker.py inside the pod
        flanker_command = [
            "python3", flanker_path,
            compressed_file.compressed_path,
            "--bucket", "cratedb-cloud-heapdumps",
            "--key", s3_key,
            "--region", "us-east-1",
            "--verbose",
            "--logfolder", "/resource/heapdump"
        ]
        
        # Execute with progress monitoring
        result = await execute_command_in_pod_with_progress(
            pod=pod,
            command=flanker_command,
            env_vars=env_vars,
            timeout=timedelta(hours=2),
            heartbeat_interval=timedelta(minutes=1)
        )
        
        success = result.exit_code == 0
        
        if success:
            activity.logger.info(
                "S3 upload completed successfully",
                pod=pod.name,
                s3_key=s3_key,
                file_size=compressed_file.compressed_size,
                duration=time.time() - start_time
            )
        else:
            activity.logger.error(
                "S3 upload failed",
                pod=pod.name,
                s3_key=s3_key,
                error=result.stderr,
                stdout=result.stdout
            )
        
        return S3UploadResult(
            success=success,
            s3_key=s3_key,
            file_size=compressed_file.compressed_size,
            upload_duration=result.duration,
            error_message=result.stderr if not success else None
        )
        
    except Exception as e:
        activity.logger.error(
            "S3 upload failed with exception",
            pod=pod.name,
            s3_key=s3_key,
            error=str(e)
        )
        
        return S3UploadResult(
            success=False,
            s3_key=s3_key,
            file_size=compressed_file.compressed_size,
            upload_duration=timedelta(seconds=time.time() - start_time),
            error_message=str(e)
        )


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
    s3_key: str,
    expected_size: int,
    aws_credentials: AWSCredentials
) -> S3VerificationResult:
    """
    CRITICAL: Verify that the file was successfully uploaded to S3.
    This must pass before allowing file deletion.
    S3 bucket has versioning enabled for additional safety.
    """
    
    activity.logger.info(
        "Starting S3 upload verification",
        s3_key=s3_key,
        expected_size=expected_size
    )
    
    try:
        # Create S3 client with temporary credentials
        s3_client = boto3.client(
            's3',
            region_name=aws_credentials.region,
            aws_access_key_id=aws_credentials.access_key_id,
            aws_secret_access_key=aws_credentials.secret_access_key,
            aws_session_token=aws_credentials.session_token
        )
        
        # Get object metadata
        response = s3_client.head_object(
            Bucket="cratedb-cloud-heapdumps",
            Key=s3_key
        )
        
        # Verify object exists and has expected size
        s3_size = response.get('ContentLength', 0)
        etag = response.get('ETag', '').strip('"')
        last_modified = response.get('LastModified')
        storage_class = response.get('StorageClass', 'STANDARD')
        version_id = response.get('VersionId')
        
        # Size verification (allow for compression differences)
        size_match = abs(s3_size - expected_size) < (expected_size * 0.1)  # 10% tolerance
        
        if not size_match:
            activity.logger.error(
                "S3 upload size mismatch",
                s3_key=s3_key,
                expected_size=expected_size,
                actual_size=s3_size,
                size_difference=abs(s3_size - expected_size)
            )
            return S3VerificationResult(
                verified=False,
                s3_key=s3_key,
                error_message=f"Size mismatch: expected ~{expected_size}, got {s3_size}"
            )
        
        # Additional verification - list object versions to ensure it's really there
        versions_response = s3_client.list_object_versions(
            Bucket="cratedb-cloud-heapdumps",
            Prefix=s3_key,
            MaxKeys=1
        )
        
        versions = versions_response.get('Versions', [])
        if not versions:
            activity.logger.error(
                "S3 object not found in versions list",
                s3_key=s3_key
            )
            return S3VerificationResult(
                verified=False,
                s3_key=s3_key,
                error_message="Object not found in S3 versions list"
            )
        
        activity.logger.info(
            "S3 upload verification successful",
            s3_key=s3_key,
            s3_size=s3_size,
            expected_size=expected_size,
            etag=etag,
            version_id=version_id,
            storage_class=storage_class,
            last_modified=last_modified
        )
        
        return S3VerificationResult(
            verified=True,
            s3_key=s3_key,
            s3_size=s3_size,
            etag=etag,
            version_id=version_id,
            storage_class=storage_class,
            last_modified=last_modified
        )
        
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        
        activity.logger.error(
            "S3 verification failed - client error",
            s3_key=s3_key,
            error_code=error_code,
            error_message=error_message
        )
        
        return S3VerificationResult(
            verified=False,
            s3_key=s3_key,
            error_message=f"S3 Error {error_code}: {error_message}"
        )
        
    except Exception as e:
        activity.logger.error(
            "S3 verification failed - unexpected error",
            s3_key=s3_key,
            error=str(e)
        )
        
        return S3VerificationResult(
            verified=False,
            s3_key=s3_key,
            error_message=f"Verification failed: {str(e)}"
        )


@activity.defn(name="safely_delete_file")
async def safely_delete_file(
    pod: CrateDBPod,
    file_info: FileToUpload,
    compressed_file: CompressedFile,
    verification_result: S3VerificationResult
) -> DeletionResult:
    """
    CRITICAL: Safely delete files ONLY after S3 upload verification.
    This activity will REFUSE to delete files if S3 upload is not verified.
    """
    
    if not verification_result.verified:
        activity.logger.error(
            "REFUSING to delete files - S3 upload not verified",
            pod=pod.name,
            file_path=file_info.file_path,
            verification_error=verification_result.error_message
        )
        return DeletionResult(
            deleted=False,
            files=[file_info.file_path, compressed_file.compressed_path],
            error_message=f"S3 upload not verified: {verification_result.error_message}"
        )
    
    # Double-check files still exist before deletion
    files_to_delete = [file_info.file_path, compressed_file.compressed_path]
    existing_files = []
    
    for file_path in files_to_delete:
        if await file_exists_in_pod(pod, file_path):
            existing_files.append(file_path)
    
    if not existing_files:
        activity.logger.info(
            "Files already deleted or not found",
            pod=pod.name,
            files=files_to_delete
        )
        return DeletionResult(
            deleted=True,
            files=files_to_delete,
            message="Files already deleted or not found"
        )
    
    # Get current file info to ensure it's the same file we uploaded
    try:
        current_file_info = await get_file_info_in_pod(pod, file_info.file_path)
        
        # Safety check - ensure file hasn't changed since upload
        if current_file_info.size != file_info.file_size:
            activity.logger.error(
                "REFUSING to delete file - file size changed since upload",
                pod=pod.name,
                file_path=file_info.file_path,
                original_size=file_info.file_size,
                current_size=current_file_info.size
            )
            return DeletionResult(
                deleted=False,
                files=files_to_delete,
                error_message=f"File size changed: {file_info.file_size} -> {current_file_info.size}"
            )
    except Exception as e:
        activity.logger.warning(
            "Could not verify file info before deletion",
            pod=pod.name,
            file_path=file_info.file_path,
            error=str(e)
        )
    
    # Final safety check - log critical information
    activity.logger.critical(
        "PROCEEDING with file deletion - ALL VERIFICATIONS PASSED",
        pod=pod.name,
        files=existing_files,
        file_size=file_info.file_size,
        s3_key=verification_result.s3_key,
        s3_version_id=verification_result.version_id,
        s3_etag=verification_result.etag
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
                    "File deleted successfully",
                    pod=pod.name,
                    file_path=file_path
                )
            else:
                deletion_errors.append(f"{file_path}: {delete_result.stderr}")
                activity.logger.error(
                    "Failed to delete file",
                    pod=pod.name,
                    file_path=file_path,
                    error=delete_result.stderr
                )
        except Exception as e:
            deletion_errors.append(f"{file_path}: {str(e)}")
            activity.logger.error(
                "Exception while deleting file",
                pod=pod.name,
                file_path=file_path,
                error=str(e)
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
            "All files successfully deleted from pod",
            pod=pod.name,
            deleted_files=verified_deletions,
            s3_backup=verification_result.s3_key
        )
        
        return DeletionResult(
            deleted=True,
            files=verified_deletions,
            message=f"Successfully deleted {len(verified_deletions)} files - backed up to {verification_result.s3_key}"
        )
    else:
        activity.logger.error(
            "Some files could not be deleted",
            pod=pod.name,
            deleted_files=verified_deletions,
            errors=deletion_errors
        )
        
        return DeletionResult(
            deleted=False,
            files=files_to_delete,
            error_message=f"Deletion errors: {'; '.join(deletion_errors)}"
        )