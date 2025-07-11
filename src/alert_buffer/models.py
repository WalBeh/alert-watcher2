"""
Data models for alert buffering functionality.

This module defines data structures used to buffer alerts when the main
alert watcher agent is not running, ensuring no alerts are lost during downtime.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import json
import uuid


class AlertBufferStatus(Enum):
    """Status of buffered alerts."""
    BUFFERED = "buffered"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class BufferedAlert:
    """A buffered alert with metadata."""
    
    # Core alert data
    alert_id: str
    alert_name: str
    namespace: str
    pod: str
    region: str
    cluster_context: str
    
    # Alert details
    alert_labels: Dict[str, str]
    alert_annotations: Dict[str, str]
    
    # Processing metadata
    correlation_id: str
    command_type: str = "kubectl_test"
    
    # Buffer metadata
    buffer_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    buffered_at: datetime = field(default_factory=datetime.now)
    status: AlertBufferStatus = AlertBufferStatus.BUFFERED
    retry_count: int = 0
    last_retry_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    
    # Expiration
    expires_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Set expiration time if not provided."""
        if self.expires_at is None:
            # Default expiration: 24 hours from buffer time
            self.expires_at = self.buffered_at + timedelta(hours=24)
    
    @property
    def is_expired(self) -> bool:
        """Check if the alert has expired."""
        return datetime.now() > self.expires_at
    
    @property
    def age(self) -> timedelta:
        """Get the age of the buffered alert."""
        return datetime.now() - self.buffered_at
    
    @property
    def can_retry(self) -> bool:
        """Check if the alert can be retried."""
        return (
            self.status in [AlertBufferStatus.FAILED, AlertBufferStatus.BUFFERED] and
            not self.is_expired and
            self.retry_count < 3
        )
    
    def to_command_data(self) -> Dict[str, Any]:
        """Convert to command data for the agent coordinator."""
        return {
            'alert_id': self.alert_id,
            'alert_name': self.alert_name,
            'namespace': self.namespace,
            'pod': self.pod,
            'region': self.region,
            'alert_labels': self.alert_labels,
            'alert_annotations': self.alert_annotations,
            'cluster_context': self.cluster_context,
            'command_type': self.command_type,
            'processing_id': self.correlation_id,
            'correlation_id': self.correlation_id,
            'buffered_alert_id': self.buffer_id,
            'retry_count': self.retry_count
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'alert_id': self.alert_id,
            'alert_name': self.alert_name,
            'namespace': self.namespace,
            'pod': self.pod,
            'region': self.region,
            'cluster_context': self.cluster_context,
            'alert_labels': self.alert_labels,
            'alert_annotations': self.alert_annotations,
            'correlation_id': self.correlation_id,
            'command_type': self.command_type,
            'buffer_id': self.buffer_id,
            'buffered_at': self.buffered_at.isoformat(),
            'status': self.status.value,
            'retry_count': self.retry_count,
            'last_retry_at': self.last_retry_at.isoformat() if self.last_retry_at else None,
            'processed_at': self.processed_at.isoformat() if self.processed_at else None,
            'error_message': self.error_message,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BufferedAlert':
        """Create BufferedAlert from dictionary."""
        # Parse datetime fields
        buffered_at = datetime.fromisoformat(data['buffered_at'])
        last_retry_at = datetime.fromisoformat(data['last_retry_at']) if data.get('last_retry_at') else None
        processed_at = datetime.fromisoformat(data['processed_at']) if data.get('processed_at') else None
        expires_at = datetime.fromisoformat(data['expires_at']) if data.get('expires_at') else None
        
        return cls(
            alert_id=data['alert_id'],
            alert_name=data['alert_name'],
            namespace=data['namespace'],
            pod=data['pod'],
            region=data.get('region', ''),
            cluster_context=data['cluster_context'],
            alert_labels=data['alert_labels'],
            alert_annotations=data['alert_annotations'],
            correlation_id=data['correlation_id'],
            command_type=data.get('command_type', 'kubectl_test'),
            buffer_id=data['buffer_id'],
            buffered_at=buffered_at,
            status=AlertBufferStatus(data['status']),
            retry_count=data.get('retry_count', 0),
            last_retry_at=last_retry_at,
            processed_at=processed_at,
            error_message=data.get('error_message'),
            expires_at=expires_at
        )
    
    @classmethod
    def from_webhook_data(cls, command_data: Dict[str, Any]) -> 'BufferedAlert':
        """Create BufferedAlert from webhook command data."""
        return cls(
            alert_id=command_data['alert_id'],
            alert_name=command_data['alert_name'],
            namespace=command_data['namespace'],
            pod=command_data['pod'],
            region=command_data.get('region', ''),
            cluster_context=command_data['cluster_context'],
            alert_labels=command_data['alert_labels'],
            alert_annotations=command_data['alert_annotations'],
            correlation_id=command_data['correlation_id'],
            command_type=command_data.get('command_type', 'kubectl_test')
        )
    
    def mark_processing(self):
        """Mark the alert as being processed."""
        self.status = AlertBufferStatus.PROCESSING
        self.last_retry_at = datetime.now()
    
    def mark_processed(self):
        """Mark the alert as successfully processed."""
        self.status = AlertBufferStatus.PROCESSED
        self.processed_at = datetime.now()
    
    def mark_failed(self, error_message: str):
        """Mark the alert as failed."""
        self.status = AlertBufferStatus.FAILED
        self.error_message = error_message
        self.retry_count += 1
        self.last_retry_at = datetime.now()
    
    def mark_expired(self):
        """Mark the alert as expired."""
        self.status = AlertBufferStatus.EXPIRED


@dataclass
class AlertBufferConfig:
    """Configuration for alert buffering."""
    
    # Storage configuration
    storage_path: str = "/tmp/alert_buffer"
    max_buffer_size: int = 1000
    max_file_age_hours: int = 24
    
    # Retry configuration
    max_retries: int = 3
    retry_delay_seconds: int = 30
    exponential_backoff: bool = True
    
    # Cleanup configuration
    cleanup_interval_minutes: int = 60
    cleanup_expired_alerts: bool = True
    cleanup_processed_alerts: bool = True
    keep_processed_alerts_hours: int = 2
    
    # Buffer flush configuration
    flush_interval_seconds: int = 10
    max_flush_batch_size: int = 10
    
    def __post_init__(self):
        """Validate configuration."""
        if self.max_buffer_size <= 0:
            raise ValueError("max_buffer_size must be positive")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.retry_delay_seconds < 1:
            raise ValueError("retry_delay_seconds must be at least 1")


@dataclass
class AlertBufferStats:
    """Statistics about the alert buffer."""
    
    total_alerts: int = 0
    buffered_alerts: int = 0
    processing_alerts: int = 0
    processed_alerts: int = 0
    failed_alerts: int = 0
    expired_alerts: int = 0
    
    oldest_alert_age: Optional[timedelta] = None
    newest_alert_age: Optional[timedelta] = None
    
    total_retries: int = 0
    success_rate: float = 0.0
    
    last_flush_at: Optional[datetime] = None
    last_cleanup_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'total_alerts': self.total_alerts,
            'buffered_alerts': self.buffered_alerts,
            'processing_alerts': self.processing_alerts,
            'processed_alerts': self.processed_alerts,
            'failed_alerts': self.failed_alerts,
            'expired_alerts': self.expired_alerts,
            'oldest_alert_age_seconds': self.oldest_alert_age.total_seconds() if self.oldest_alert_age else None,
            'newest_alert_age_seconds': self.newest_alert_age.total_seconds() if self.newest_alert_age else None,
            'total_retries': self.total_retries,
            'success_rate': self.success_rate,
            'last_flush_at': self.last_flush_at.isoformat() if self.last_flush_at else None,
            'last_cleanup_at': self.last_cleanup_at.isoformat() if self.last_cleanup_at else None
        }


@dataclass
class AlertBufferOperation:
    """Result of a buffer operation."""
    
    success: bool
    operation: str
    alert_id: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging."""
        return {
            'success': self.success,
            'operation': self.operation,
            'alert_id': self.alert_id,
            'message': self.message,
            'error': self.error,
            'timestamp': self.timestamp.isoformat()
        }