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

from file_uploader.models import (
    CrateDBPod,
    AWSCredentials,
    CompressedFile,
    S3UploadResult,
    S3VerificationResult,
    DeletionResult,
)
from file_uploader.utils import extract_pod_from_alert, extract_statefulset_pods_from_alert, standard_retry_policy
from file_uploader.activities import (
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
    async def run(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute crash dump upload workflow for specific pod from alert.
        
        Args:
            alert_data: Alert data containing labels with namespace and pod info
            
        Returns:
            Dict with processing details
        """
        
        workflow_start_time = workflow.now()
        
        # Extract all StatefulSet pods from alert labels
        try:
            statefulset_pods = extract_statefulset_pods_from_alert(alert_data)
        except ValueError as e:
            workflow.logger.error(
                f"Failed to extract StatefulSet pods from alert - alert_data: {alert_data}, error: {str(e)}"
            )
            return {
                "success": False,
                "processed_pods": [],
                "uploaded_files": [],
                "processing_results": [],
                "errors": [str(e)],
                "message": f"Invalid alert data: {str(e)}",
                "total_duration_seconds": 0.0,
                "total_size_bytes": 0,
                "upload_count": 0,
                "deletion_count": 0,
                "total_uploaded_size": 0
            }
        
        workflow.logger.info(
            f"Starting crash dump upload workflow for StatefulSet - workflow_id: {workflow.info().workflow_id}, "
            f"run_id: {workflow.info().run_id}, pods: {[pod.name for pod in statefulset_pods]}, "
            f"namespace: {statefulset_pods[0].namespace}, container: {statefulset_pods[0].container}"
        )
        
        try:
            # Step 1: Discover crash dumps from all StatefulSet pods
            self.workflow_state = "discovering_crash_dumps"
            
            all_discovery_results = []
            all_processed_pods = []
            total_crash_dumps = 0
            
            # Process each pod in the StatefulSet
            for pod in statefulset_pods:
                workflow.logger.info(
                    f"Discovering crash dumps for pod: {pod.name}, namespace: {pod.namespace}"
                )
                
                discovery_result = await workflow.execute_activity(
                    discover_crash_dumps,
                    args=[pod],
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(minutes=2),
                    retry_policy=standard_retry_policy()
                )
                
                all_discovery_results.append((pod, discovery_result))
                all_processed_pods.append(pod.name)
                
                if discovery_result.requires_upload:
                    total_crash_dumps += len(discovery_result.crash_dumps)
                    workflow.logger.info(
                        f"Found {len(discovery_result.crash_dumps)} crash dumps in pod: {pod.name}"
                    )
            
            # Check if any pods have crash dumps requiring upload
            if total_crash_dumps == 0:
                workflow.logger.info(
                    f"No crash dumps requiring upload found in any StatefulSet pods - "
                    f"pods: {all_processed_pods}, namespace: {statefulset_pods[0].namespace}"
                )
                return {
                    "success": True,
                    "processed_pods": all_processed_pods,
                    "uploaded_files": [],
                    "processing_results": [],
                    "errors": [],
                    "message": f"No crash dumps found in any of the {len(statefulset_pods)} pods",
                    "total_duration_seconds": (workflow.now() - workflow_start_time).total_seconds(),
                    "total_size_bytes": 0,
                    "upload_count": 0,
                    "deletion_count": 0,
                    "total_uploaded_size": 0
                }
            
            # Step 2: ONLY NOW get AWS credentials (crash dumps found)
            self.workflow_state = "getting_credentials"
            
            workflow.logger.critical(
                f"CRASH DUMPS FOUND - Starting upload process for StatefulSet - "
                f"pods: {all_processed_pods}, namespace: {statefulset_pods[0].namespace}, "
                f"total_crash_dump_count: {total_crash_dumps}, "
                f"pods_with_dumps: {[pod.name for pod, result in all_discovery_results if result.requires_upload]}"
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
            
            # Step 3: Process crash dumps from all StatefulSet pods
            self.workflow_state = "processing_crash_dumps"
            
            all_processing_results = []
            all_upload_results = []
            total_size_bytes = 0
            
            # Process crash dumps from each pod that has them
            for pod, discovery_result in all_discovery_results:
                if discovery_result.requires_upload:
                    workflow.logger.info(
                        f"Processing {len(discovery_result.crash_dumps)} crash dumps from pod: {pod.name}"
                    )
                    
                    processing_results = await self._process_all_crash_dumps(
                        pod,
                        discovery_result.crash_dumps,
                        aws_credentials
                    )
                    
                    all_processing_results.extend(processing_results)
                    total_size_bytes += discovery_result.total_size
                    
                    # Extract upload results
                    for result in processing_results:
                        if result.upload_result:
                            all_upload_results.append(result.upload_result)
            
            # Step 4: Generate final result for StatefulSet
            self.workflow_state = "completed"
            
            return self._generate_statefulset_final_result(
                all_processed_pods,
                all_processing_results,
                all_upload_results,
                total_size_bytes,
                workflow_start_time
            )
            
        except Exception as e:
            workflow.logger.error(
                f"Crash dump upload workflow failed for StatefulSet - "
                f"pods: {[pod.name for pod in statefulset_pods]}, "
                f"namespace: {statefulset_pods[0].namespace}, error: {str(e)}, "
                f"workflow_state: {self.workflow_state}"
            )
            
            return {
                "success": False,
                "processed_pods": [pod.name for pod in statefulset_pods],
                "uploaded_files": [],
                "processing_results": [],
                "errors": [str(e)],
                "message": f"Crash dump upload workflow failed: {str(e)}",
                "total_duration_seconds": (workflow.now() - workflow_start_time).total_seconds(),
                "total_size_bytes": 0,
                "upload_count": 0,
                "deletion_count": 0,
                "total_uploaded_size": 0
            }

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
                f"Processing crash dump - pod: {pod.name}, file_path: {crash_dump.file_path}, "
                f"file_size: {crash_dump.file_size}, file_type: {crash_dump.file_type}, "
                f"progress: {i+1}/{len(crash_dumps)}"
            )
            
            try:
                result = await self._process_single_crash_dump(
                    pod,
                    crash_dump,
                    aws_credentials
                )
                processing_results.append(result)
                
                workflow.logger.info(
                    f"Crash dump processing completed - pod: {pod.name}, "
                    f"file_path: {crash_dump.file_path}, "
                    f"upload_success: {result.upload_result.success}, "
                    f"verification_passed: {result.verification_passed}, "
                    f"deletion_success: {result.deletion_result.deleted if result.deletion_result else False}, "
                    f"file_size_mb: {round(crash_dump.file_size / (1024 * 1024), 2)}, "
                    f"s3_key: {result.upload_result.s3_key if result.upload_result else None}"
                )
                
            except Exception as e:
                workflow.logger.error(
                    f"Failed to process crash dump file - file_path: {crash_dump.file_path}, "
                    f"error: {str(e)}"
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
        
        compressed_file_dict = await workflow.execute_activity(
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
        
        # Reconstruct CompressedFile object from dict
        compressed_file = CompressedFile(
            original_path=compressed_file_dict['original_path'],
            compressed_path=compressed_file_dict['compressed_path'],
            original_size=compressed_file_dict['original_size'],
            compressed_size=compressed_file_dict['compressed_size'],
            compression_ratio=compressed_file_dict['compression_ratio']
        )
        
        # Step 2: Upload to S3
        # Generate S3 key based on file type, matching standalone script convention
        if crash_dump.file_type == "java_pid1.hprof":
            # Crash heap-dump (critical): {pod_name}-java_pid1.hprof.gz
            s3_key = f"{pod.name}-java_pid1.hprof.gz"
        elif crash_dump.file_type == "additional_hprof":
            # Regular heap-dump: {pod_name}.hprof.gz
            s3_key = f"{pod.name}.hprof.gz"
        elif crash_dump.file_type == "jfr":
            # JFR files: {pod_name}.jfr (no compression for JFR)
            s3_key = f"{pod.name}.jfr"
        else:
            # Fallback for unknown types
            file_extension = crash_dump.file_path.split('.')[-1]
            s3_key = f"{pod.name}.{file_extension}.gz"
        
        upload_result_dict = await workflow.execute_activity(
            upload_file_to_s3,
            args=[pod, compressed_file_dict, s3_key, aws_credentials],
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=30),
                maximum_interval=timedelta(minutes=10),
                backoff_coefficient=2.0,
                maximum_attempts=3
            )
        )
        
        # Reconstruct S3UploadResult object from dict
        upload_result = S3UploadResult(
            success=upload_result_dict['success'],
            s3_key=upload_result_dict['s3_key'],
            file_size=upload_result_dict['file_size'],
            upload_duration=timedelta(seconds=upload_result_dict['upload_duration_seconds']),
            error_message=upload_result_dict.get('error_message'),
            etag=upload_result_dict.get('etag')
        )
        
        verification_passed = False
        deletion_result = None
        
        if upload_result.success:
            # Step 3: CRITICAL - Verify S3 upload
            verification_result_dict = await workflow.execute_activity(
                verify_s3_upload,
                args=[pod, upload_result_dict, aws_credentials],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=5),
                    maximum_interval=timedelta(minutes=2),
                    backoff_coefficient=2.0,
                    maximum_attempts=5  # Extra retries for verification
                )
            )
            
            # Use verification result directly from flanker.py
            verification_result = verification_result_dict
            
            verification_passed = verification_result.get('verified', False)
            
            # Step 4: ONLY delete if verification passed
            if verification_passed:
                deletion_result_dict = await workflow.execute_activity(
                    safely_delete_file,
                    args=[pod, file_to_upload, compressed_file_dict, verification_result_dict],
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=5),
                        maximum_interval=timedelta(minutes=1),
                        backoff_coefficient=2.0,
                        maximum_attempts=2
                    )
                )
                
                # Reconstruct DeletionResult object from dict
                deletion_result = DeletionResult(
                    deleted=deletion_result_dict['deleted'],
                    files=deletion_result_dict['files'],
                    error_message=deletion_result_dict.get('error_message'),
                    message=deletion_result_dict.get('message')
                )
            else:
                workflow.logger.error(
                    f"Skipping file deletion - S3 upload verification failed - pod: {pod.name}, "
                    f"file_path: {crash_dump.file_path}, s3_key: {s3_key}, "
                    f"verification_error: {verification_result.error_message}"
                )
                deletion_result = None
        
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
    ) -> Dict[str, Any]:
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
            f"Crash dump upload workflow completed - pod: {pod.name}, "
            f"namespace: {pod.namespace}, overall_success: {overall_success}, "
            f"crash_dump_count: {len(discovery_result.crash_dumps)}, "
            f"successful_uploads: {successful_uploads}, "
            f"successful_verifications: {successful_verifications}, "
            f"successful_deletions: {successful_deletions}, "
            f"error_count: {len(all_errors)}, "
            f"total_duration: {(workflow.now() - workflow_start_time).total_seconds()}"
        )
        
        return {
            "success": overall_success,
            "processed_pods": [pod.name],
            "uploaded_files": [result.to_dict() for result in upload_results],
            "processing_results": [result.to_dict() for result in processing_results],
            "errors": all_errors,
            "message": message,
            "total_duration_seconds": (workflow.now() - workflow_start_time).total_seconds(),
            "total_size_bytes": discovery_result.total_size,
            "upload_count": len([r for r in upload_results if r.success]),
            "deletion_count": sum(
                1 for result in processing_results 
                if result.deletion_result and result.deletion_result.deleted
            ),
            "total_uploaded_size": sum(
                result.upload_result.file_size 
                for result in processing_results 
                if result.upload_result.success
            )
        }
    
    def _generate_statefulset_final_result(
        self,
        processed_pods: List[str],
        processing_results: List[CrashDumpProcessingResult],
        upload_results: List[S3UploadResult],
        total_size_bytes: int,
        workflow_start_time: datetime
    ) -> Dict[str, Any]:
        """Generate final result for StatefulSet processing."""
        
        # Determine overall success
        overall_success = all(
            result.upload_result and result.upload_result.success
            for result in processing_results
            if result.upload_result
        )
        
        # Collect all errors
        all_errors = []
        for result in processing_results:
            if not result.upload_result.success:
                all_errors.append(result.upload_result.error_message or "S3 upload failed")
        
        # Generate summary message
        successful_uploads = len([r for r in upload_results if r.success])
        total_files = len(processing_results)
        
        if overall_success:
            message = f"Successfully processed crash dumps from {len(processed_pods)} pods - uploaded {successful_uploads}/{total_files} files"
        else:
            message = f"Partially processed crash dumps from {len(processed_pods)} pods - uploaded {successful_uploads}/{total_files} files with errors"
        
        workflow.logger.info(
            f"StatefulSet crash dump processing completed - "
            f"pods: {processed_pods}, success: {overall_success}, "
            f"uploaded_files: {successful_uploads}/{total_files}, "
            f"total_size_mb: {round(total_size_bytes / (1024 * 1024), 2)}"
        )
        
        return {
            "success": overall_success,
            "processed_pods": processed_pods,
            "uploaded_files": [result.to_dict() for result in upload_results],
            "processing_results": [result.to_dict() for result in processing_results],
            "errors": all_errors,
            "message": message,
            "total_duration_seconds": (workflow.now() - workflow_start_time).total_seconds(),
            "total_size_bytes": total_size_bytes,
            "upload_count": len([r for r in upload_results if r.success]),
            "deletion_count": sum(
                1 for result in processing_results 
                if result.deletion_result and result.deletion_result.deleted
            ),
            "total_uploaded_size": sum(
                result.upload_result.file_size 
                for result in processing_results 
                if result.upload_result.success
            )
        }

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