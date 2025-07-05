"""
Temporal signals module for handling alert signals.

This module defines signal constants and utility functions for the alert processing workflow.
"""

import structlog
from .models import AlertProcessingSignal


logger = structlog.get_logger(__name__)


# Signal definitions for type safety
ALERT_RECEIVED_SIGNAL = "alert_received"
HEALTH_CHECK_SIGNAL = "health_check"
SHUTDOWN_SIGNAL = "shutdown"


def is_duplicate_alert(alert_id: str, processed_alert_ids: set) -> bool:
    """
    Check if an alert is a duplicate based on alert ID.
    
    Args:
        alert_id: The alert ID to check
        processed_alert_ids: Set of already processed alert IDs
        
    Returns:
        bool: True if the alert is a duplicate
    """
    return alert_id in processed_alert_ids


def create_alert_id(signal_payload: AlertProcessingSignal) -> str:
    """
    Create a unique alert ID from the signal payload.
    
    Args:
        signal_payload: The alert signal payload
        
    Returns:
        str: Unique alert ID
    """
    alert_data = signal_payload.alert_data
    return f"{alert_data.labels.alertname}-{alert_data.labels.namespace}-{alert_data.labels.pod}-{signal_payload.processing_id}"


def validate_alert_signal(signal_data: dict) -> AlertProcessingSignal:
    """
    Validate and parse alert signal data.
    
    Args:
        signal_data: Raw signal data dictionary
        
    Returns:
        AlertProcessingSignal: Parsed and validated signal payload
        
    Raises:
        ValueError: If signal data is invalid
    """
    try:
        return AlertProcessingSignal(**signal_data)
    except Exception as e:
        logger.error(
            "Failed to validate alert signal",
            error=str(e),
            signal_data=signal_data
        )
        raise ValueError(f"Invalid alert signal data: {str(e)}")