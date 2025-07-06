"""
Pydantic models for AlertManager webhook payloads and internal data structures.

This module defines the simplified data models used for alert processing.
"""

from datetime import datetime, timezone
import time
from typing import Dict, List, Optional, Any, Callable
from pydantic import BaseModel, Field
from enum import Enum


def _utcnow() -> datetime:
    """Get current UTC time - isolated function for Temporal compatibility."""
    return datetime.now(timezone.utc)


class AlertStatus(str, Enum):
    """Alert status enumeration."""
    FIRING = "firing"
    RESOLVED = "resolved"


class AlertLabel(BaseModel):
    """Alert labels from Prometheus."""
    alertname: str = Field(..., description="Name of the alert")
    namespace: Optional[str] = Field(None, description="Kubernetes namespace")
    pod: Optional[str] = Field(None, description="Pod name")
    kube_context: Optional[str] = Field(None, description="Kubernetes context")
    sts: Optional[str] = Field(None, description="StatefulSet identifier")
    severity: Optional[str] = Field(None, description="Alert severity")
    instance: Optional[str] = Field(None, description="Instance identifier")
    job: Optional[str] = Field(None, description="Job name")
    
    class Config:
        extra = "allow"  # Allow additional labels


class AlertAnnotation(BaseModel):
    """Alert annotations from Prometheus."""
    summary: Optional[str] = Field(None, description="Alert summary")
    description: Optional[str] = Field(None, description="Alert description")
    runbook_url: Optional[str] = Field(None, description="Runbook URL")
    
    class Config:
        extra = "allow"  # Allow additional annotations


class Alert(BaseModel):
    """Individual alert from AlertManager."""
    status: AlertStatus = Field(..., description="Alert status")
    labels: AlertLabel = Field(..., description="Alert labels")
    annotations: AlertAnnotation = Field(..., description="Alert annotations")
    startsAt: datetime = Field(..., description="Alert start time")
    endsAt: Optional[datetime] = Field(None, description="Alert end time")
    generatorURL: Optional[str] = Field(None, description="Generator URL")
    fingerprint: Optional[str] = Field(None, description="Alert fingerprint")


class AlertManagerWebhook(BaseModel):
    """AlertManager webhook payload."""
    version: str = Field(..., description="AlertManager version")
    groupKey: str = Field(..., description="Group key")
    truncatedAlerts: int = Field(default=0, description="Number of truncated alerts")
    status: AlertStatus = Field(..., description="Group status")
    receiver: str = Field(..., description="Receiver name")
    groupLabels: Dict[str, str] = Field(default_factory=dict, description="Group labels")
    commonLabels: Dict[str, str] = Field(default_factory=dict, description="Common labels")
    commonAnnotations: Dict[str, str] = Field(default_factory=dict, description="Common annotations")
    externalURL: str = Field(..., description="AlertManager external URL")
    alerts: List[Alert] = Field(..., description="List of alerts")


class AlertProcessingSignal(BaseModel):
    """Signal payload for alert processing workflow."""
    alert_id: str = Field(..., description="Unique alert identifier")
    alert_data: Alert = Field(..., description="Alert data")
    received_at: datetime = Field(default_factory=_utcnow, description="Signal received timestamp")
    processing_id: Optional[str] = Field(None, description="Processing correlation ID")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat() + "Z"
        }


class ActivityResult(BaseModel):
    """Result of activity execution."""
    success: bool = Field(..., description="Whether activity succeeded")
    message: str = Field(..., description="Result message")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional result data")
    execution_time_ms: Optional[int] = Field(None, description="Execution time in milliseconds")
    
    @classmethod
    def success_result(cls, message: str, data: Optional[Dict[str, Any]] = None, 
                      execution_time_ms: Optional[int] = None) -> "ActivityResult":
        """Create a success result."""
        return cls(
            success=True,
            message=message,
            data=data,
            execution_time_ms=execution_time_ms
        )
    
    @classmethod
    def error_result(cls, message: str, data: Optional[Dict[str, Any]] = None,
                    execution_time_ms: Optional[int] = None) -> "ActivityResult":
        """Create an error result."""
        return cls(
            success=False,
            message=message,
            data=data,
            execution_time_ms=execution_time_ms
        )