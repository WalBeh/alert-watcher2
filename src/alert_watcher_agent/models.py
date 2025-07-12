"""
Alert Watcher Agent Data Models.

This module provides data models for the Alert Watcher Agent with proper
typing, validation, and serialization support optimized for Temporal workflows.
"""

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from enum import Enum


class CommandType(Enum):
    """Types of commands that can be executed by the agent."""
    KUBECTL_TEST = "kubectl_test"
    HEMAKO_JFR = "hemako_jfr"
    HEMAKO_CRASH_HEAPDUMP = "hemako_crash_heapdump"


class CommandStatus(Enum):
    """Status of command execution."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class CommandRequest:
    """Request model for agent command execution."""
    
    # Required fields
    alert_id: str
    cluster_context: str
    alert_name: str
    namespace: str
    pod: str
    
    # Optional fields with defaults
    command_type: CommandType = CommandType.KUBECTL_TEST
    correlation_id: str = ""
    created_at: Optional[datetime] = None
    
    # Alert metadata
    alert_labels: Dict[str, str] = field(default_factory=dict)
    alert_annotations: Dict[str, str] = field(default_factory=dict)
    
    # Execution parameters
    timeout_minutes: int = 25
    priority: int = 0  # Higher number = higher priority
    
    def __post_init__(self):
        """Validate request after initialization."""
        if not self.alert_id:
            raise ValueError("alert_id is required")
        if not self.cluster_context:
            raise ValueError("cluster_context is required")
        if not self.alert_name:
            raise ValueError("alert_name is required")
        if not self.namespace:
            raise ValueError("namespace is required")
        if not self.pod:
            raise ValueError("pod is required")
        
        # Convert string command_type to enum if needed
        if isinstance(self.command_type, str):
            self.command_type = CommandType(self.command_type)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "alert_id": self.alert_id,
            "cluster_context": self.cluster_context,
            "alert_name": self.alert_name,
            "namespace": self.namespace,
            "pod": self.pod,
            "command_type": self.command_type.value,
            "correlation_id": self.correlation_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "alert_labels": self.alert_labels,
            "alert_annotations": self.alert_annotations,
            "timeout_minutes": self.timeout_minutes,
            "priority": self.priority
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandRequest":
        """Create from dictionary."""
        # Handle datetime conversion
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elif created_at is None:
            # Don't set a default here - let the workflow set it with workflow.now()
            created_at = None
        
        # Use processing_id as correlation_id if correlation_id not provided
        correlation_id = data.get("correlation_id", data.get("processing_id", ""))
        
        return cls(
            alert_id=data["alert_id"],
            cluster_context=data["cluster_context"],
            alert_name=data["alert_name"],
            namespace=data["namespace"],
            pod=data["pod"],
            command_type=CommandType(data.get("command_type", "kubectl_test")),
            correlation_id=correlation_id,
            created_at=created_at,
            alert_labels=data.get("alert_labels", {}),
            alert_annotations=data.get("alert_annotations", {}),
            timeout_minutes=data.get("timeout_minutes", 25),
            priority=data.get("priority", 0)
        )


@dataclass
class CommandResponse:
    """Response model for agent command execution."""
    
    # Required fields
    success: bool
    message: str
    cluster_context: str
    alert_id: str
    
    # Execution metadata
    correlation_id: str = ""
    status: CommandStatus = CommandStatus.COMPLETED
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_duration_seconds: Optional[float] = None
    
    # Command output
    command_executed: str = ""
    stdout: str = ""
    stderr: str = ""
    return_code: Optional[int] = None
    
    # Kubernetes-specific data
    pod_count: Optional[int] = None
    namespace_info: Dict[str, Any] = field(default_factory=dict)
    
    # Simulation data
    simulation_sleep_minutes: Optional[int] = None
    heartbeat_count: int = 0
    
    # Error information
    error_type: Optional[str] = None
    error_details: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Calculate duration if both timestamps are available."""
        # Don't set completed_at automatically - let the caller set it
        # Calculate duration if both timestamps are available
        if self.started_at and self.completed_at:
            duration = self.completed_at - self.started_at
            self.execution_duration_seconds = duration.total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "success": self.success,
            "message": self.message,
            "cluster_context": self.cluster_context,
            "alert_id": self.alert_id,
            "correlation_id": self.correlation_id,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "execution_duration_seconds": self.execution_duration_seconds,
            "command_executed": self.command_executed,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "return_code": self.return_code,
            "pod_count": self.pod_count,
            "namespace_info": self.namespace_info,
            "simulation_sleep_minutes": self.simulation_sleep_minutes,
            "heartbeat_count": self.heartbeat_count,
            "error_type": self.error_type,
            "error_details": self.error_details
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CommandResponse":
        """Create from dictionary."""
        # Handle datetime conversion
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        
        completed_at = data.get("completed_at")
        if isinstance(completed_at, str):
            completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        
        return cls(
            success=data["success"],
            message=data["message"],
            cluster_context=data["cluster_context"],
            alert_id=data["alert_id"],
            correlation_id=data.get("correlation_id", ""),
            status=CommandStatus(data.get("status", "completed")),
            started_at=started_at,
            completed_at=completed_at,
            execution_duration_seconds=data.get("execution_duration_seconds"),
            command_executed=data.get("command_executed", ""),
            stdout=data.get("stdout", ""),
            stderr=data.get("stderr", ""),
            return_code=data.get("return_code"),
            pod_count=data.get("pod_count"),
            namespace_info=data.get("namespace_info", {}),
            simulation_sleep_minutes=data.get("simulation_sleep_minutes"),
            heartbeat_count=data.get("heartbeat_count", 0),
            error_type=data.get("error_type"),
            error_details=data.get("error_details", {})
        )
    
    @classmethod
    def success_response(
        cls,
        alert_id: str,
        cluster_context: str,
        message: str,
        correlation_id: str = "",
        **kwargs
    ) -> "CommandResponse":
        """Create a successful response."""
        return cls(
            success=True,
            message=message,
            cluster_context=cluster_context,
            alert_id=alert_id,
            correlation_id=correlation_id,
            status=CommandStatus.COMPLETED,
            **kwargs
        )
    
    @classmethod
    def error_response(
        cls,
        alert_id: str,
        cluster_context: str,
        message: str,
        error_type: str = "ExecutionError",
        correlation_id: str = "",
        **kwargs
    ) -> "CommandResponse":
        """Create an error response."""
        return cls(
            success=False,
            message=message,
            cluster_context=cluster_context,
            alert_id=alert_id,
            correlation_id=correlation_id,
            status=CommandStatus.FAILED,
            error_type=error_type,
            **kwargs
        )


@dataclass
class ClusterStatus:
    """Status information for a cluster worker."""
    
    cluster_context: str
    is_active: bool
    queue_size: int
    currently_executing: Optional[str] = None  # alert_id of current execution
    total_processed: int = 0
    total_failed: int = 0
    last_execution_at: Optional[datetime] = None
    last_error: Optional[str] = None
    worker_started_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "cluster_context": self.cluster_context,
            "is_active": self.is_active,
            "queue_size": self.queue_size,
            "currently_executing": self.currently_executing,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "last_execution_at": self.last_execution_at.isoformat() if self.last_execution_at else None,
            "last_error": self.last_error,
            "worker_started_at": self.worker_started_at.isoformat() if self.worker_started_at else None,
            "uptime_seconds": 0  # Uptime calculation moved to avoid workflow restrictions
        }


@dataclass
class AgentStatus:
    """Overall status of the agent."""
    
    agent_id: str
    is_running: bool
    started_at: datetime
    supported_clusters: List[str]
    cluster_statuses: Dict[str, ClusterStatus] = field(default_factory=dict)
    total_commands_processed: int = 0
    total_commands_failed: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "agent_id": self.agent_id,
            "is_running": self.is_running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "uptime_seconds": 0,  # Uptime calculation moved to avoid workflow restrictions
            "supported_clusters": self.supported_clusters,
            "cluster_statuses": {
                cluster: status.to_dict() 
                for cluster, status in self.cluster_statuses.items()
            },
            "total_commands_processed": self.total_commands_processed,
            "total_commands_failed": self.total_commands_failed,
            "success_rate": (
                (self.total_commands_processed - self.total_commands_failed) / 
                max(self.total_commands_processed, 1)
            ) * 100
        }


@dataclass
class QueuedCommand:
    """Represents a command in the cluster queue."""
    
    request: CommandRequest
    queued_at: Optional[datetime] = None
    position: int = 0
    estimated_wait_minutes: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request": self.request.to_dict(),
            "queued_at": self.queued_at.isoformat() if self.queued_at else None,
            "position": self.position,
            "estimated_wait_minutes": self.estimated_wait_minutes
        }


# Utility functions for working with models

def create_command_request_from_alert(
    alert_id: str,
    cluster_context: str,
    alert_name: str,
    namespace: str,
    pod: str,
    alert_labels: Optional[Dict[str, str]] = None,
    alert_annotations: Optional[Dict[str, str]] = None,
    command_type: Union[str, CommandType] = CommandType.KUBECTL_TEST
) -> CommandRequest:
    """Create a CommandRequest from alert data."""
    
    # Convert string to enum if needed
    if isinstance(command_type, str):
        command_type = CommandType(command_type)
    
    return CommandRequest(
        alert_id=alert_id,
        cluster_context=cluster_context,
        alert_name=alert_name,
        namespace=namespace,
        pod=pod,
        command_type=command_type,
        alert_labels=alert_labels or {},
        alert_annotations=alert_annotations or {}
    )


def determine_command_type(alert_name: str) -> CommandType:
    """Determine command type based on alert name."""
    if alert_name == "CrateDBContainerRestart":
        return CommandType.HEMAKO_CRASH_HEAPDUMP
    elif alert_name == "CrateDBCloudNotResponsive":
        return CommandType.HEMAKO_JFR
    else:
        return CommandType.KUBECTL_TEST


def calculate_priority(alert_name: str, namespace: str) -> int:
    """Calculate priority based on alert characteristics."""
    priority = 0
    
    # Higher priority for production namespaces
    if "prod" in namespace.lower():
        priority += 10
    elif "staging" in namespace.lower():
        priority += 5
    
    # Higher priority for certain alert types
    if alert_name == "CrateDBCloudNotResponsive":
        priority += 20
    elif alert_name == "CrateDBContainerRestart":
        priority += 10
    
    return priority