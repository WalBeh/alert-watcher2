"""
Temporal workflows for alert processing.

This module defines the main workflow for processing CrateDB alerts.
Simplified to just log the alert data structure.
"""

import asyncio
from datetime import timedelta
from typing import Dict, List, Optional, Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from .models import AlertProcessingSignal, ActivityResult


@workflow.defn
class AlertProcessingWorkflow:
    """
    Main workflow for processing CrateDB alerts.
    
    This workflow runs continuously and processes alert signals received
    from the webhook server. It only logs the alert data structure.
    """
    
    def __init__(self):
        self.processed_alerts: Dict[str, bool] = {}
        self.is_running = True
        self.signal_queue: List[AlertProcessingSignal] = []
        self.processing_lock = asyncio.Lock()
        self.processed_alert_ids: set = set()
        
    @workflow.run
    async def run(self) -> Dict[str, Any]:
        """
        Main workflow execution method.
        
        This method runs continuously, waiting for alert signals and
        processing them by logging the alert data structure.
        """
        workflow.logger.info(
            "Alert processing workflow started - workflow_id: %s, run_id: %s",
            workflow.info().workflow_id,
            workflow.info().run_id
        )
        
        # Main processing loop
        while self.is_running:
            try:
                # Wait for incoming alert signals with timeout
                if self.signal_queue:
                    # Process queued signals
                    async with self.processing_lock:
                        if self.signal_queue:
                            signal_payload = self.signal_queue.pop(0)
                            await self.process_alert_signal(signal_payload)
                else:
                    # No signals, wait for a bit and perform maintenance
                    await workflow.sleep(30)
                    await self.perform_maintenance()
                
                # Check if we should continue as new to avoid history growth
                if await self.should_continue_as_new():
                    workflow.logger.info("Continuing workflow as new")
                    workflow.continue_as_new()
                    
            except Exception as e:
                workflow.logger.error(
                    "Error in main workflow loop: %s",
                    str(e)
                )
                # Continue processing other alerts even if one fails
                await workflow.sleep(5)
        
        # Return final workflow result
        return {
            "status": "completed",
            "processed_alerts": len(self.processed_alerts),
            "workflow_duration": 0,  # Remove non-deterministic datetime calculation
            "completion_time": "workflow_completed"
        }
    
    async def process_alert_signal(self, signal_payload: AlertProcessingSignal):
        """
        Process an individual alert signal by logging it.
        
        Args:
            signal_payload: The alert signal data to process.
        """
        alert_id = signal_payload.alert_id
        alert_data = signal_payload.alert_data
        
        workflow.logger.info(
            "Processing alert signal - alert_id: %s, alert_name: %s, namespace: %s, pod: %s, processing_id: %s",
            alert_id,
            alert_data.labels.alertname,
            alert_data.labels.namespace,
            alert_data.labels.pod,
            signal_payload.processing_id
        )
        
        try:
            # Just log the alert - this is the only step now
            log_result = await self.log_alert_step(signal_payload)
            
            if not log_result.success:
                workflow.logger.error(
                    "Failed to log alert - alert_id: %s, error: %s",
                    alert_id,
                    log_result.message
                )
                return
            
            # Mark signal as processed
            self.processed_alerts[alert_id] = True
            self.processed_alert_ids.add(alert_id)
            
            workflow.logger.info(
                "Alert processing completed - alert_id: %s, log_success: %s, total_processed: %d",
                alert_id,
                log_result.success,
                len(self.processed_alerts)
            )
            
        except Exception as e:
            workflow.logger.error(
                "Failed to process alert signal - alert_id: %s, error: %s",
                alert_id,
                str(e)
            )
            # Don't let one failed alert stop the workflow
    
    async def log_alert_step(self, signal_payload: AlertProcessingSignal) -> ActivityResult:
        """
        Execute the alert logging activity.
        
        Args:
            signal_payload: The alert signal data.
            
        Returns:
            ActivityResult: Result of the logging activity.
        """
        # Get the alert name for dynamic activity naming
        alert_name = signal_payload.alert_data.labels.alertname.lower()
        activity_name = f"log_{alert_name}_alert"
        
        # List of pre-defined activities (without the "log_" prefix and "_alert" suffix)
        predefined_activities = {"cratedb", "prometheus", "node", "pod", "service"}
        
        # Check if we have a pre-defined activity for this alert type
        if alert_name in predefined_activities:
            # Use the pre-defined activity
            final_activity_name = activity_name
        else:
            # Use generic log_alert for unknown alert types
            final_activity_name = "log_alert"
            workflow.logger.info(
                f"No specific activity for alert '{alert_name}', using generic log_alert activity"
            )
        
        result_dict = await workflow.execute_activity(
            final_activity_name,
            signal_payload.dict(),
            start_to_close_timeout=timedelta(seconds=30),
            heartbeat_timeout=timedelta(seconds=10),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=10),
                backoff_coefficient=2.0,
                maximum_attempts=3
            )
        )
        return ActivityResult(**result_dict)
    
    async def perform_maintenance(self):
        """
        Perform periodic maintenance tasks.
        """
        try:
            # Clean up old processed alert IDs to prevent memory growth
            if len(self.processed_alert_ids) > 1000:
                # Keep only the most recent 500 alert IDs
                self.processed_alert_ids = set(list(self.processed_alert_ids)[-500:])
            
            # Log current statistics
            workflow.logger.info(
                "Workflow maintenance completed - processed_alerts_count: %d, processed_alert_ids_count: %d, queue_size: %d",
                len(self.processed_alerts),
                len(self.processed_alert_ids),
                len(self.signal_queue)
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
    
    # Signal handler methods
    @workflow.signal
    async def alert_received(self, signal_data: dict):
        """Signal handler for incoming alerts."""
        try:
            signal_payload = AlertProcessingSignal(**signal_data)
            
            # Check for duplicate alerts
            if signal_payload.alert_id in self.processed_alert_ids:
                workflow.logger.info(
                    "Duplicate alert signal received, skipping - alert_id: %s, alert_name: %s",
                    signal_payload.alert_id,
                    signal_payload.alert_data.labels.alertname
                )
                return
            
            # Add to processing queue
            async with self.processing_lock:
                self.signal_queue.append(signal_payload)
            
            workflow.logger.info(
                "Alert signal received and queued - alert_id: %s, alert_name: %s, namespace: %s, pod: %s, processing_id: %s, queue_size: %d",
                signal_payload.alert_id,
                signal_payload.alert_data.labels.alertname,
                signal_payload.alert_data.labels.namespace,
                signal_payload.alert_data.labels.pod,
                signal_payload.processing_id,
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
            "Health check signal received - processed_count: %d, queue_size: %d, is_running: %s",
            len(self.processed_alerts),
            len(self.signal_queue),
            self.is_running
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