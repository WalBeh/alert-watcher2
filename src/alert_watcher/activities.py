"""
Temporal activities for alert processing.

This module defines the activities that are executed by Temporal workflows
to process CrateDB alerts. Currently just logs the alert data structure.
"""

import json
import logging
import time
from datetime import datetime
from typing import Dict, Any

import structlog
from temporalio import activity

from .models import ActivityResult


# Configure structured logging
logger = structlog.get_logger(__name__)


@activity.defn(name="log_alert")
async def log_alert(signal_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Log the alert data structure to understand the format.
    
    This activity receives the alert signal and logs the complete
    JSON structure so we can understand how the labels look.
    
    Args:
        signal_data: The alert signal data dictionary
        
    Returns:
        ActivityResult dictionary with success status and message
    """
    try:
        # Parse the signal data
        from .models import AlertProcessingSignal
        signal_payload = AlertProcessingSignal(**signal_data)
        alert_data = signal_payload.alert_data
        alert_name = alert_data.labels.alertname
        
        # Create a comprehensive log entry with all alert data
        current_time = datetime.fromtimestamp(time.time())
        log_entry = {
            "timestamp": current_time.isoformat() + "Z",
            "event": f"{alert_name}_alert_received",
            "alert_id": signal_payload.alert_id,
            "processing_id": signal_payload.processing_id,
            "alert_data": {
                "status": alert_data.status,
                "labels": alert_data.labels.dict(),
                "annotations": alert_data.annotations.dict(),
                "startsAt": alert_data.startsAt.isoformat() + "Z",
                "endsAt": alert_data.endsAt.isoformat() + "Z" if alert_data.endsAt else None,
                "generatorURL": alert_data.generatorURL,
                "fingerprint": alert_data.fingerprint
            }
        }
        
        # Log the complete alert structure with alert name prominently featured
        logger.info(
            f"{alert_name} alert received and logged",
            alert_id=signal_payload.alert_id,
            processing_id=signal_payload.processing_id,
            alert_name=alert_name,
            namespace=alert_data.labels.namespace,
            pod=alert_data.labels.pod,
            full_alert_data=log_entry
        )
        
        # Also log as pretty-printed JSON for easy reading
        print("\n" + "="*80)
        print(f"{alert_name.upper()} ALERT DATA STRUCTURE:")
        print("="*80)
        print(json.dumps(log_entry, indent=2, default=str))
        print("="*80 + "\n")
        
        return ActivityResult.success_result(
            message=f"{alert_name} alert {signal_payload.alert_id} logged successfully",
            data={
                "alert_id": signal_payload.alert_id,
                "alert_name": alert_name,
                "namespace": alert_data.labels.namespace,
                "pod": alert_data.labels.pod,
                "logged_at": current_time.isoformat() + "Z"
            }
        ).dict()
        
    except Exception as e:
        error_msg = f"Failed to log alert: {str(e)}"
        logger.error(
            "Alert logging failed",
            error=error_msg,
            signal_data=signal_data,
            exc_info=True
        )
        
        return ActivityResult.error_result(
            message=error_msg,
            data={"error_type": type(e).__name__}
        ).dict()


# Dynamic activity factory for creating alert-specific activities
def create_alert_activity(alert_name: str):
    """
    Create a dynamically named activity for a specific alert type.
    
    Args:
        alert_name: The name of the alert type
        
    Returns:
        An activity function named after the alert
    """
    @activity.defn(name=f"log_{alert_name.lower()}_alert")
    async def log_specific_alert(signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log a specific alert type.
        
        Args:
            signal_data: The alert signal data dictionary
            
        Returns:
            ActivityResult dictionary with success status and message
        """
        return await log_alert(signal_data)
    
    return log_specific_alert


# Pre-create some common alert activities
log_cratedb_alert = create_alert_activity("CrateDB")
log_prometheus_alert = create_alert_activity("Prometheus")
log_node_alert = create_alert_activity("Node")
log_pod_alert = create_alert_activity("Pod")
log_service_alert = create_alert_activity("Service")