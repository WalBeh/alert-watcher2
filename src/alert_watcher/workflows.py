"""
Temporal workflows for CrateDB alert processing.

This module defines the main workflow and sub-workflows for processing
CrateDB alerts. Each alert spawns its own sub-workflow with a unique name.
"""

import asyncio
from datetime import timedelta
from typing import Dict, List, Optional, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from .models import AlertProcessingSignal, ActivityResult


@workflow.defn
class CrateDBAlertSubWorkflow:
    """
    Sub-workflow for processing individual CrateDB alerts.

    This workflow is spawned for each alert and executes the hemako command
    specific to the alert type. The workflow name includes the alert name
    and namespace for easy identification.
    """

    def __init__(self):
        self.alert_processed = False

    @workflow.run
    async def run(self, alert_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single CrateDB alert.

        Args:
            alert_data: Dictionary containing alert information

        Returns:
            Dictionary with processing results
        """
        alert_name = alert_data.get("alert_name")
        namespace = alert_data.get("namespace")
        pod = alert_data.get("pod")
        alert_id = alert_data.get("alert_id")

        workflow.logger.info(
            "CrateDB alert sub-workflow started - workflow_id: %s, run_id: %s, alert_name: %s, namespace: %s, pod: %s, alert_id: %s",
            workflow.info().workflow_id,
            workflow.info().run_id,
            alert_name,
            namespace,
            pod,
            alert_id
        )

        try:
            # Execute the hemako command activity
            result_dict = await workflow.execute_activity(
                "execute_hemako_command",
                alert_data,
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )

            result = ActivityResult(**result_dict)

            if result.success:
                workflow.logger.info(
                    "CrateDB alert processed successfully - alert_name: %s, namespace: %s, pod: %s, alert_id: %s, message: %s",
                    alert_name,
                    namespace,
                    pod,
                    alert_id,
                    result.message
                )
                self.alert_processed = True
            else:
                workflow.logger.error(
                    "CrateDB alert processing failed - alert_name: %s, namespace: %s, pod: %s, alert_id: %s, error: %s",
                    alert_name,
                    namespace,
                    pod,
                    alert_id,
                    result.message
                )

            return {
                "status": "completed",
                "success": result.success,
                "alert_name": alert_name,
                "namespace": namespace,
                "pod": pod,
                "alert_id": alert_id,
                "message": result.message,
                "processed_at": "workflow_completed"
            }

        except Exception as e:
            workflow.logger.error(
                "CrateDB alert sub-workflow failed - alert_name: %s, namespace: %s, pod: %s, alert_id: %s, error: %s",
                alert_name,
                namespace,
                pod,
                alert_id,
                str(e)
            )

            return {
                "status": "failed",
                "success": False,
                "alert_name": alert_name,
                "namespace": namespace,
                "pod": pod,
                "alert_id": alert_id,
                "error": str(e),
                "failed_at": "workflow_failed"
            }


@workflow.defn
class AlertProcessingWorkflow:
    """
    Main workflow for processing CrateDB alerts.

    This workflow runs continuously and spawns sub-workflows for each
    incoming alert. Only processes CrateDBContainerRestart and
    CrateDBCloudNotResponsive alerts.
    """

    def __init__(self):
        self.processed_alerts: Dict[str, str] = {}  # alert_id -> sub_workflow_id
        self.is_running = True
        self.signal_queue: List[AlertProcessingSignal] = []
        self.processing_lock = asyncio.Lock()
        self.supported_alerts = {"CrateDBContainerRestart", "CrateDBCloudNotResponsive"}

    @workflow.run
    async def run(self) -> Dict[str, Any]:
        """
        Main workflow execution method.

        Continuously processes incoming alert signals by spawning
        sub-workflows for each supported alert type.
        """
        workflow.logger.info(
            "Main alert processing workflow started - workflow_id: %s, run_id: %s, supported_alerts: %s",
            workflow.info().workflow_id,
            workflow.info().run_id,
            list(self.supported_alerts)
        )

        # Main processing loop
        while self.is_running:
            try:
                # Process queued signals
                if self.signal_queue:
                    async with self.processing_lock:
                        if self.signal_queue:
                            signal_payload = self.signal_queue.pop(0)
                            await self.process_alert_signal(signal_payload)
                else:
                    # No signals, wait and perform maintenance
                    await workflow.sleep(30)
                    await self.perform_maintenance()

                # Continue as new to avoid history growth
                if await self.should_continue_as_new():
                    workflow.logger.info("Continuing workflow as new")
                    workflow.continue_as_new()

            except Exception as e:
                workflow.logger.error(
                    "Error in main workflow loop: %s",
                    str(e)
                )
                await workflow.sleep(5)

        return {
            "status": "completed",
            "processed_alerts": len(self.processed_alerts),
            "completion_time": "workflow_completed"
        }

    async def process_alert_signal(self, signal_payload: AlertProcessingSignal):
        """
        Process an alert signal by spawning a sub-workflow.

        Args:
            signal_payload: The alert signal data to process.
        """
        alert_name = signal_payload.alert_data.labels.alertname
        namespace = signal_payload.alert_data.labels.namespace
        pod = signal_payload.alert_data.labels.pod
        alert_id = signal_payload.alert_id

        # Check if this is a supported alert type
        if alert_name not in self.supported_alerts:
            workflow.logger.warning(
                "Unsupported alert type, skipping - alert_name: %s, namespace: %s, pod: %s, alert_id: %s, supported_alerts: %s",
                alert_name,
                namespace,
                pod,
                alert_id,
                list(self.supported_alerts)
            )
            return
        
        workflow.logger.info(
            "Processing supported alert signal - alert_name: %s, namespace: %s, pod: %s, alert_id: %s",
            alert_name,
            namespace,
            pod,
            alert_id
        )
        
        try:
            # Create sub-workflow ID with alert name and namespace
            sub_workflow_id = f"{alert_name}-{namespace}-{workflow.uuid4()}"
            
            # Prepare alert data for sub-workflow
            alert_data = {
                "alert_name": alert_name,
                "namespace": namespace,
                "pod": pod,
                "alert_id": alert_id,
                "processing_id": signal_payload.processing_id,
                "received_at": signal_payload.received_at.isoformat() + "Z",
                "status": signal_payload.alert_data.status.value,
                "labels": signal_payload.alert_data.labels.dict(),
                "annotations": signal_payload.alert_data.annotations.dict()
            }
            
            # Start sub-workflow
            sub_workflow_handle = await workflow.start_child_workflow(
                CrateDBAlertSubWorkflow.run,
                alert_data,
                id=sub_workflow_id,
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(minutes=1),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )
            
            # Track the sub-workflow
            self.processed_alerts[alert_id] = sub_workflow_id
            
            workflow.logger.info(
                "Sub-workflow started for alert - alert_name: %s, namespace: %s, pod: %s, alert_id: %s, sub_workflow_id: %s, total_processed: %d",
                alert_name,
                namespace,
                pod,
                alert_id,
                sub_workflow_id,
                len(self.processed_alerts)
            )
            
            # Don't wait for sub-workflow to complete - let it run independently
            
        except Exception as e:
            workflow.logger.error(
                "Failed to start sub-workflow for alert - alert_name: %s, namespace: %s, pod: %s, alert_id: %s, error: %s",
                alert_name,
                namespace,
                pod,
                alert_id,
                str(e)
            )
    
    async def perform_maintenance(self):
        """
        Perform periodic maintenance tasks.
        """
        try:
            # Clean up old processed alert IDs to prevent memory growth
            if len(self.processed_alerts) > 1000:
                # Keep only the most recent 500 alert IDs
                alert_items = list(self.processed_alerts.items())
                self.processed_alerts = dict(alert_items[-500:])
            
            workflow.logger.info(
                "Workflow maintenance completed - processed_alerts_count: %d, queue_size: %d, supported_alerts: %s",
                len(self.processed_alerts),
                len(self.signal_queue),
                list(self.supported_alerts)
            )
            
        except Exception as e:
            workflow.logger.error(
                "Maintenance task failed: %s",
                str(e)
            )
    
    async def should_continue_as_new(self) -> bool:
        """
        Determine if the workflow should continue as new.
        
        Returns:
            bool: True if the workflow should continue as new.
        """
        # Continue as new after 1000 processed alerts
        return len(self.processed_alerts) > 1000
    
    @workflow.signal
    async def alert_received(self, signal_data: dict):
        """Signal handler for incoming alerts."""
        try:
            signal_payload = AlertProcessingSignal(**signal_data)
            alert_name = signal_payload.alert_data.labels.alertname
            
            # Check if this is a supported alert type
            if alert_name not in self.supported_alerts:
                workflow.logger.warning(
                    "Received unsupported alert type, ignoring - alert_name: %s, supported_alerts: %s",
                    alert_name,
                    list(self.supported_alerts)
                )
                return
            
            # Check for duplicate alerts
            if signal_payload.alert_id in self.processed_alerts:
                workflow.logger.info(
                    "Duplicate alert signal received, skipping - alert_id: %s, alert_name: %s",
                    signal_payload.alert_id,
                    alert_name
                )
                return
            
            # Add to processing queue
            async with self.processing_lock:
                self.signal_queue.append(signal_payload)
            
            workflow.logger.info(
                "Alert signal received and queued - alert_id: %s, alert_name: %s, namespace: %s, pod: %s, queue_size: %d",
                signal_payload.alert_id,
                alert_name,
                signal_payload.alert_data.labels.namespace,
                signal_payload.alert_data.labels.pod,
                len(self.signal_queue)
            )
            
        except Exception as e:
            workflow.logger.error(
                "Failed to handle alert signal - error: %s, signal_data: %s",
                str(e),
                signal_data
            )
    
    @workflow.signal
    async def health_check(self, check_data: dict):
        """Signal handler for health checks."""
        workflow.logger.info(
            "Health check signal received - processed_count: %d, queue_size: %d, is_running: %s, supported_alerts: %s",
            len(self.processed_alerts),
            len(self.signal_queue),
            self.is_running,
            list(self.supported_alerts)
        )
    
    @workflow.signal
    async def shutdown(self, shutdown_data: dict):
        """Signal handler for graceful shutdown."""
        workflow.logger.info(
            "Shutdown signal received - reason: %s, force: %s",
            shutdown_data.get("reason", "unknown"),
            shutdown_data.get("force", False)
        )
        self.is_running = False