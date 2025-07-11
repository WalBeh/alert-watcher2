"""
Temporal activities for CrateDB alert processing.

This module defines activities for processing CrateDB alerts that will trigger
hemako commands with different parameters based on the alert type.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from .models import ActivityResult


# Configure structured logging
logger = structlog.get_logger(__name__)


@activity.defn(name="execute_hemako_command")
async def execute_hemako_command(alert_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute hemako command based on alert type.
    
    For CrateDBContainerRestart alerts, this triggers the crash dump upload workflow.
    For CrateDBCloudNotResponsive alerts, this will handle JFR collection (future).
    
    Args:
        alert_data: Dictionary containing alert information including:
                   - alert_name: The alert name (CrateDBContainerRestart or CrateDBCloudNotResponsive)
                   - labels: Alert labels containing namespace, pod, etc.
                   - other alert metadata
        
    Returns:
        ActivityResult dictionary with success status and message
    """
    try:
        alert_name = alert_data.get("alert_name")
        labels = alert_data.get("labels", {})
        namespace = labels.get("namespace")
        pod = labels.get("pod")
        
        logger.info(
            "Executing hemako command",
            alert_name=alert_name,
            namespace=namespace,
            pod=pod
        )
        
        if alert_name == "CrateDBContainerRestart":
            # Start crash dump upload workflow
            from crash_dump_uploader.workflows import CrashDumpUploadWorkflow
            
            crash_dump_result = await workflow.execute_child_workflow(
                CrashDumpUploadWorkflow.run,
                alert_data,
                id=f"crash-dump-upload-{alert_data.get('alert_id')}-{workflow.uuid4()}",
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=30),
                    maximum_interval=timedelta(minutes=5),
                    backoff_coefficient=2.0,
                    maximum_attempts=2
                )
            )
            
            return ActivityResult.success_result(
                message=f"Crash dump upload workflow completed: {crash_dump_result.message}",
                data={
                    "alert_name": alert_name,
                    "namespace": namespace,
                    "pod": pod,
                    "workflow_result": {
                        "success": crash_dump_result.success,
                        "processed_pods": crash_dump_result.processed_pods,
                        "uploaded_files_count": len(crash_dump_result.uploaded_files),
                        "total_size_bytes": crash_dump_result.total_size_bytes,
                        "upload_count": crash_dump_result.upload_count,
                        "deletion_count": crash_dump_result.deletion_count,
                        "duration_seconds": crash_dump_result.total_duration.total_seconds()
                    },
                    "executed_at": datetime.fromtimestamp(time.time()).isoformat() + "Z"
                }
            ).dict()
            
        elif alert_name == "CrateDBCloudNotResponsive":
            # TODO: Implement JFR upload workflow
            logger.info(
                "CrateDBCloudNotResponsive alert - JFR upload not yet implemented",
                alert_name=alert_name,
                namespace=namespace,
                pod=pod
            )
            
            return ActivityResult.success_result(
                message="CrateDBCloudNotResponsive alert received - JFR upload not yet implemented",
                data={
                    "alert_name": alert_name,
                    "namespace": namespace,
                    "pod": pod,
                    "status": "jfr_upload_pending_implementation",
                    "executed_at": datetime.fromtimestamp(time.time()).isoformat() + "Z"
                }
            ).dict()
            
        else:
            raise ValueError(f"Unsupported alert type: {alert_name}")
        
    except Exception as e:
        error_msg = f"Failed to execute hemako command: {str(e)}"
        logger.error(
            "Hemako command execution failed",
            error=error_msg,
            alert_data=alert_data,
            exc_info=True
        )
        
        return ActivityResult.error_result(
            message=error_msg,
            data={"error_type": type(e).__name__}
        ).dict()