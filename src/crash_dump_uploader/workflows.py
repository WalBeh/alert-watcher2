"""
Crash dump upload workflow for CrateDB containers.

This module defines the main workflow for processing crash dump uploads
triggered by CrateDBContainerRestart alerts. It orchestrates the discovery,
compression, upload, verification, and cleanup of crash dump files.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List

import structlog
from temporalio import workflow
from temporalio.common import RetryPolicy

from ..file_uploader.models import (
    CrateDBPod,
    AWSCredentials,
    CompressedFile,
    S3UploadResult,
    S3VerificationResult,
    DeletionResult,
)
from ..file_uploader.utils import extract_pod_from_alert, standard_retry_policy
from ..file_uploader.activities import (
    compress_file,
    upload_file_to_s3,
    verify_s3_upload,
    safely_delete_file,
)

from .models import (
    CrashDumpDiscoveryResult,
    CrashDumpProcessingResult,
    CrashDumpUploadResult,
)
from .activities import discover_crash_dumps, get_upload_credentials

logger = structlog.get_logger(__name__)


@workflow.defn
class CrashDumpUploadWorkflow:
    """
    Main workflow for crash dump upload operations.
    
    This workflow is triggered by CrateDBContainerRestart alerts and handles
    the complete lifecycle of crash dump processing:
    1. Discovery of crash dump files
    2. Compression and upload to S3
    3. Verification of uploads
    4. Safe deletion of local files
    """

    def __init__(self):
        self.workflow_state = "initializing"
        self.processed_files = []
        self.errors = []

    @workflow.run
    async def run(self, alert_data: Dict[str, Any]) -> CrashDumpUploadResult:
        """
        Execute crash dump upload workflow for specific pod from alert.
        
        Args:
            alert_data: Alert data containing labels with namespace and pod info
            
        Returns:
            CrashDumpUploadResult with processing details
        """
        
        workflow_start_time = workflow.now()
        
        # Extract pod information directly from alert labels
        try:
            target_pod = extract_pod_from_alert(alert_data)
        except ValueError as e:
            workflow.logger.error(
                "Failed to extract pod info from alert",
                alert_data=alert_data,
                error=str(e)
            )
            return CrashDumpUploadResult(
                success=False,
                processed_pods=[],
                uploaded_files=[],
                processing_results=[],
                errors=[str(e)],
                message=f"Invalid alert data: {str(e)}",
                total_duration=timedelta(seconds=0),
                total_size_bytes=0
            )
        
        workflow.logger.info(
            "Starting crash dump upload workflow",
            workflow_id=workflow.info().workflow_id,
            run_id=workflow.info().run_id,
            pod_name=target_pod.name,
            namespace=target_pod.namespace,
            container=target_pod.container
        )
        
        try:
            # Step 1: Discover crash dumps (no credentials needed yet)
            self.workflow_state = "discovering_crash_dumps"
            
            discovery_result = await workflow.execute_activity(
                discover_crash_dumps,
                args=[target_pod],
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=2),
                retry_policy=standard_retry_policy()
            )
            
            if not discovery_result.requires_upload:
                workflow.logger.info(
                    "No crash dumps requiring upload",
                    pod_name=target_pod.name,
                    namespace=target_pod.namespace,
                    message=discovery_result.message
                )
                return CrashDumpUploadResult(
                    success=True,
                    processed_pods=[target_pod.name],
                    uploaded_files=[],
                    processing_results=[],
                    errors=[],
                    message=discovery_result.message,
                    total_duration=workflow.now() - workflow_start_time,
                    total_size_bytes=0
                )
            
            # Step 2: ONLY NOW get AWS credentials (crash dumps found)
            self.workflow_state = "getting_credentials"
            
            workflow.logger.critical(
                "CRASH DUMPS FOUND - Starting upload process",
                pod_name=target_pod.name,
                namespace=target_pod.namespace,
                crash_dump_count=len(discovery_result.crash_dumps),
                total_size_mb=round(discovery_result.total_size / (1024 * 1024), 2),
                has_java_pid1=discovery_result.has_java_pid1
            )
            
            credentials_dict = await workflow.execute_activity(
                get_upload_credentials,
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=standard_retry_policy()
            )
            
            aws_credentials = AWSCredentials(
                access_key_id=credentials_dict["access_key_id"],
                secret_access_key=credentials_dict["secret_access_key"],
                session_token=credentials_dict["session_token"],
                region=credentials_dict["region"],
                expiry=datetime.fromisoformat(credentials_dict["expiry"].replace('Z', '+00:00'))
            )
            
            # Step 3: Process each crash dump with full verification cycle
            self.workflow_state = "processing_crash_dumps"
            
            processing_results = await self._process_all_crash_dumps(
                target_pod,
                discovery_result.crash_dumps,
                aws_credentials
            )
            
            # Step 4: Generate final result
            self.workflow_state = "completed"
            
            return self._generate_final_result(
                target_pod,
                discovery_result,
                processing_results,
                workflow_start_time
            )
            
        except Exception as e:
            workflow.logger.error(
                "Crash dump upload workflow failed",
                pod_name=target_pod.name,
                namespace=target_pod.namespace,
                error=str(e),
                workflow_state=self.workflow_state
            )
            
            return CrashDumpUploadResult(
                success=False,
                processed_pods=[target_pod.name],
                uploaded_files=[],
                processing_results=[],
                errors=[str(e)],
                message=f"Workflow failed at {self.workflow_state}: {str(e)}",
                total_duration=workflow.now() - workflow_start_time,
                total_size_bytes=0
            )

    async def _process_all_crash_dumps(
        self,
        pod: CrateDBPod,
        crash_dumps: List,
        aws_credentials: AWSCredentials
    ) -> List[CrashDumpProcessingResult]:
        """Process all crash dumps with full verification cycle."""
        
        processing_results = []
        
        for i, crash_dump in enumerate(crash_dumps):
            workflow.logger.info(
                "Processing crash dump",
                pod_name=pod.name,
                file_path=crash_dump.file_path,
                file_size=crash_dump.file_size,
                file_type=crash_dump.file_type,
                progress=f"{i+1}/{len(crash_dumps)}"
            )
            
            try:
                result = await self._process_single_crash_dump(
                    pod,
                    crash_dump,
                    aws_credentials
                )
                processing_results.append(result)
                
                workflow.logger.info(
                    "Crash dump processing completed",
                    pod_name=pod.name,
                    file_path=crash_dump.file_path,
                    upload_success=result.upload_result.success,
                    verification_passed=result.verification_passed,
                    deletion_success=result.deletion_result.deleted if result.deletion_result else False,
                    s3_key=result.upload_result.s3_key if result.upload_result.success else None
                )
                
            except Exception as e:
                workflow.logger.error(
                    "Failed to process crash dump",
                    pod_name=pod.name,
                    file_path=crash_dump.file_path,
                    error=str(e)
                )
                
                # Create failed result
                failed_result = CrashDumpProcessingResult(
                    crash_dump=crash_dump,
                    compressed_size=0,
                    upload_result=S3UploadResult(
                        success=False,
                        s3_key="",
                        file_size=crash_dump.file_size,
                        upload_duration=timedelta(seconds=0),
                        error_message=str(e)
                    ),
                    verification_passed=False,
                    deletion_result=None
                )
                processing_results.append(failed_result)
        
        return processing_results

    async def _process_single_crash_dump(
        self,
        pod: CrateDBPod,
        crash_dump,
        aws_credentials: AWSCredentials
    ) -> CrashDumpProcessingResult:
        """Process a single crash dump through the complete pipeline."""
        
        # Step 1: Compress the crash dump
        file_to_upload = crash_dump.to_file_upload()
        
        compressed_file = await workflow.execute_activity(
            compress_file,
            args=[pod, file_to_upload, aws_credentials],
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=10),
                maximum_interval=timedelta(minutes=5),
                backoff_coefficient=2.0,
                maximum_attempts=2
            )
        )
        
        # Step 2: Upload to S3
        timestamp = int(time.time())
        file_extension = crash_dump.file_path.split('.')[-1]  # hprof
        s3_key = f"{pod.name}-{timestamp}.{file_extension}.gz"
        
        upload_result = await workflow.execute_activity(
            upload_file_to_s3,
            args=[pod, compressed_file, s3_key, aws_credentials],
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=10),
                backoff_coefficient=2.0,
                maximum_attempts=3
            )
        )
        
        verification_passed = False
        deletion_result = None
        
        if upload_result.success:
            # Step 3: CRITICAL - Verify S3 upload
            verification_result = await workflow.execute_activity(
                verify_s3_upload,
                args=[s3_key, compressed_file.compressed_size, aws_credentials],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(minutes=2),
                    backoff_coefficient=2.0,
                    maximum_attempts=5  # Extra retries for verification
                )
            )
            
            verification_passed = verification_result.verified
            
            # Step 4: ONLY delete if verification passed
            if verification_passed:
                deletion_result = await workflow.execute_activity(
                    safely_delete_file,
                    args=[pod, file_to_upload, compressed_file, verification_result],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        maximum_interval=timedelta(minutes=1),
                        backoff_coefficient=2.0,
                        maximum_attempts=2
                    )
                )
            else:
                workflow.logger.error(
                    "Skipping file deletion - S3 upload verification failed",
                    pod_name=pod.name,
                    file_path=crash_dump.file_path,
                    s3_key=s3_key,
                    verification_error=verification_result.error_message
                )
        
        return CrashDumpProcessingResult(
            crash_dump=crash_dump,
            compressed_size=compressed_file.compressed_size,
            upload_result=upload_result,
            verification_passed=verification_passed,
            deletion_result=deletion_result
        )

    def _generate_final_result(
        self,
        pod: CrateDBPod,
        discovery_result: CrashDumpDiscoveryResult,
        processing_results: List[CrashDumpProcessingResult],
        workflow_start_time: datetime
    ) -> CrashDumpUploadResult:
        """Generate the final workflow result."""
        
        # Collect all upload results
        upload_results = [result.upload_result for result in processing_results]
        
        # Collect errors
        all_errors = []
        for result in processing_results:
            if not result.upload_result.success and result.upload_result.error_message:
                all_errors.append(f"{result.crash_dump.file_path}: {result.upload_result.error_message}")
            if not result.verification_passed:
                all_errors.append(f"{result.crash_dump.file_path}: S3 verification failed")
            if result.deletion_result and not result.deletion_result.deleted and result.deletion_result.error_message:
                all_errors.append(f"{result.crash_dump.file_path}: Deletion failed - {result.deletion_result.error_message}")
        
        # Determine overall success
        successful_uploads = sum(1 for result in processing_results if result.upload_result.success)
        successful_verifications = sum(1 for result in processing_results if result.verification_passed)
        successful_deletions = sum(1 for result in processing_results if result.deletion_result and result.deletion_result.deleted)
        
        overall_success = successful_uploads == len(discovery_result.crash_dumps)
        
        # Generate summary message
        if overall_success:
            message = f"Successfully processed {len(discovery_result.crash_dumps)} crash dumps: {successful_uploads} uploaded, {successful_verifications} verified, {successful_deletions} safely deleted"
        else:
            message = f"Processed {len(discovery_result.crash_dumps)} crash dumps with {len(all_errors)} errors: {successful_uploads} uploaded, {successful_verifications} verified, {successful_deletions} safely deleted"
        
        workflow.logger.info(
            "Crash dump upload workflow completed",
            pod_name=pod.name,
            namespace=pod.namespace,
            overall_success=overall_success,
            crash_dump_count=len(discovery_result.crash_dumps),
            successful_uploads=successful_uploads,
            successful_verifications=successful_verifications,
            successful_deletions=successful_deletions,
            error_count=len(all_errors),
            total_duration=(workflow.now() - workflow_start_time).total_seconds()
        )
        
        return CrashDumpUploadResult(
            success=overall_success,
            processed_pods=[pod.name],
            uploaded_files=upload_results,
            processing_results=processing_results,
            errors=all_errors,
            message=message,
            total_duration=workflow.now() - workflow_start_time,
            total_size_bytes=discovery_result.total_size
        )

    @workflow.query
    def get_workflow_state(self) -> Dict[str, Any]:
        """Query current workflow state."""
        return {
            "state": self.workflow_state,
            "processed_files": len(self.processed_files),
            "errors": len(self.errors),
            "workflow_id": workflow.info().workflow_id,
            "run_id": workflow.info().run_id
        }

    @workflow.query
    def get_processing_status(self) -> Dict[str, Any]:
        """Query detailed processing status."""
        return {
            "workflow_state": self.workflow_state,
            "processed_files": self.processed_files,
            "errors": self.errors,
            "start_time": workflow.info().start_time.isoformat(),
            "workflow_id": workflow.info().workflow_id
        }