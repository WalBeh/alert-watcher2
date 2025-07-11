"""
Alert Watcher Agent Configuration.

This module provides configuration management for the Alert Watcher Agent
with optimal Temporal SDK settings and proper environment variable support.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class AgentConfig:
    """Configuration for the Alert Watcher Agent with Temporal optimizations."""
    
    # Temporal Client Configuration
    temporal_host: str = field(default_factory=lambda: os.getenv("TEMPORAL_HOST", "localhost"))
    temporal_port: int = field(default_factory=lambda: int(os.getenv("TEMPORAL_PORT", "7233")))
    temporal_namespace: str = field(default_factory=lambda: os.getenv("TEMPORAL_NAMESPACE", "default"))
    temporal_tls_enabled: bool = field(default_factory=lambda: os.getenv("TEMPORAL_TLS_ENABLED", "false").lower() == "true")
    temporal_identity: str = field(default_factory=lambda: os.getenv("TEMPORAL_IDENTITY", "alert-watcher-agent"))
    
    # Task Queue Configuration (optimal for cluster isolation)
    coordinator_task_queue: str = field(default_factory=lambda: os.getenv("COORDINATOR_TASK_QUEUE", "alert-watcher-agent-coordinator"))
    cluster_task_queue_prefix: str = field(default_factory=lambda: os.getenv("CLUSTER_TASK_QUEUE_PREFIX", "alert-watcher-agent"))
    
    # Supported Clusters (hardcoded as requested)
    supported_clusters: List[str] = field(default_factory=lambda: [
        "aks1-eastus-dev",
        "eks1-us-east-1-dev",
        "clusterxy"
    ])
    
    # Worker Configuration (optimal for Temporal performance)
    max_concurrent_activities: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_ACTIVITIES", "1")))
    max_concurrent_workflow_tasks: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_WORKFLOWS", "10")))
    max_concurrent_local_activities: int = field(default_factory=lambda: int(os.getenv("MAX_CONCURRENT_LOCAL_ACTIVITIES", "5")))
    
    # Activity Timeout Configuration (optimized for long-running operations)
    activity_start_to_close_timeout_minutes: int = field(default_factory=lambda: int(os.getenv("ACTIVITY_START_TO_CLOSE_TIMEOUT_MINUTES", "25")))
    activity_heartbeat_timeout_minutes: int = field(default_factory=lambda: int(os.getenv("ACTIVITY_HEARTBEAT_TIMEOUT_MINUTES", "3")))
    activity_schedule_to_close_timeout_minutes: int = field(default_factory=lambda: int(os.getenv("ACTIVITY_SCHEDULE_TO_CLOSE_TIMEOUT_MINUTES", "30")))
    
    # Retry Policy Configuration (optimal for stability)
    retry_initial_interval_seconds: int = field(default_factory=lambda: int(os.getenv("RETRY_INITIAL_INTERVAL_SECONDS", "1")))
    retry_maximum_interval_seconds: int = field(default_factory=lambda: int(os.getenv("RETRY_MAXIMUM_INTERVAL_SECONDS", "60")))
    retry_backoff_coefficient: float = field(default_factory=lambda: float(os.getenv("RETRY_BACKOFF_COEFFICIENT", "2.0")))
    retry_maximum_attempts: int = field(default_factory=lambda: int(os.getenv("RETRY_MAXIMUM_ATTEMPTS", "3")))
    
    # Workflow Configuration (optimal for long-running coordinators)
    workflow_execution_timeout_hours: int = field(default_factory=lambda: int(os.getenv("WORKFLOW_EXECUTION_TIMEOUT_HOURS", "168")))  # 7 days
    workflow_run_timeout_hours: int = field(default_factory=lambda: int(os.getenv("WORKFLOW_RUN_TIMEOUT_HOURS", "24")))  # 1 day
    workflow_task_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("WORKFLOW_TASK_TIMEOUT_SECONDS", "10")))
    
    # Continue-as-new thresholds (optimal for memory management)
    continue_as_new_execution_threshold: int = field(default_factory=lambda: int(os.getenv("CONTINUE_AS_NEW_EXECUTION_THRESHOLD", "500")))
    continue_as_new_history_threshold: int = field(default_factory=lambda: int(os.getenv("CONTINUE_AS_NEW_HISTORY_THRESHOLD", "1000")))
    
    # Kubernetes Configuration
    kubeconfig_path: str = field(default_factory=lambda: os.getenv("KUBECONFIG_PATH", "/app/kubeconfig"))
    kubectl_timeout_seconds: int = field(default_factory=lambda: int(os.getenv("KUBECTL_TIMEOUT_SECONDS", "60")))
    
    # Simulation Configuration (for testing long-running operations)
    simulate_long_running: bool = field(default_factory=lambda: os.getenv("SIMULATE_LONG_RUNNING", "true").lower() == "true")
    min_sleep_minutes: int = field(default_factory=lambda: int(os.getenv("MIN_SLEEP_MINUTES", "5")))
    max_sleep_minutes: int = field(default_factory=lambda: int(os.getenv("MAX_SLEEP_MINUTES", "20")))
    
    # Logging Configuration
    log_level: str = field(default_factory=lambda: os.getenv("AGENT_LOG_LEVEL", "INFO"))
    log_format: str = field(default_factory=lambda: os.getenv("AGENT_LOG_FORMAT", "json"))
    enable_correlation_ids: bool = field(default_factory=lambda: os.getenv("ENABLE_CORRELATION_IDS", "true").lower() == "true")
    
    # Health Check Configuration
    health_check_port: int = field(default_factory=lambda: int(os.getenv("HEALTH_CHECK_PORT", "8080")))
    health_check_enabled: bool = field(default_factory=lambda: os.getenv("HEALTH_CHECK_ENABLED", "true").lower() == "true")
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        self._validate_configuration()
    
    def _validate_configuration(self):
        """Validate configuration values."""
        if not self.supported_clusters:
            raise ValueError("At least one cluster must be configured")
        
        if self.temporal_port <= 0 or self.temporal_port > 65535:
            raise ValueError("Temporal port must be between 1 and 65535")
        
        if self.max_concurrent_activities < 1:
            raise ValueError("Max concurrent activities must be at least 1")
        
        if self.activity_start_to_close_timeout_minutes < 1:
            raise ValueError("Activity start-to-close timeout must be at least 1 minute")
        
        if self.activity_heartbeat_timeout_minutes < 1:
            raise ValueError("Activity heartbeat timeout must be at least 1 minute")
        
        if self.retry_maximum_attempts < 1:
            raise ValueError("Retry maximum attempts must be at least 1")
        
        if self.min_sleep_minutes < 1 or self.max_sleep_minutes < 1:
            raise ValueError("Sleep minutes must be at least 1")
        
        if self.min_sleep_minutes > self.max_sleep_minutes:
            raise ValueError("Min sleep minutes cannot be greater than max sleep minutes")
        
        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            raise ValueError("Log level must be one of: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    
    def get_cluster_task_queue(self, cluster_context: str) -> str:
        """Get the task queue name for a specific cluster."""
        return f"{self.cluster_task_queue_prefix}-{cluster_context}"
    
    def get_task_queues(self) -> Dict[str, str]:
        """Get all task queues for supported clusters."""
        queues = {
            "coordinator": self.coordinator_task_queue
        }
        
        for cluster in self.supported_clusters:
            queues[cluster] = self.get_cluster_task_queue(cluster)
        
        return queues
    
    def get_temporal_address(self) -> str:
        """Get the complete Temporal server address."""
        return f"{self.temporal_host}:{self.temporal_port}"
    
    def to_dict(self) -> Dict:
        """Convert configuration to dictionary for logging."""
        return {
            "temporal_host": self.temporal_host,
            "temporal_port": self.temporal_port,
            "temporal_namespace": self.temporal_namespace,
            "temporal_tls_enabled": self.temporal_tls_enabled,
            "supported_clusters": self.supported_clusters,
            "task_queues": self.get_task_queues(),
            "max_concurrent_activities": self.max_concurrent_activities,
            "activity_timeouts": {
                "start_to_close_minutes": self.activity_start_to_close_timeout_minutes,
                "heartbeat_minutes": self.activity_heartbeat_timeout_minutes,
                "schedule_to_close_minutes": self.activity_schedule_to_close_timeout_minutes
            },
            "retry_policy": {
                "initial_interval_seconds": self.retry_initial_interval_seconds,
                "maximum_interval_seconds": self.retry_maximum_interval_seconds,
                "backoff_coefficient": self.retry_backoff_coefficient,
                "maximum_attempts": self.retry_maximum_attempts
            },
            "simulation": {
                "enabled": self.simulate_long_running,
                "min_sleep_minutes": self.min_sleep_minutes,
                "max_sleep_minutes": self.max_sleep_minutes
            },
            "log_level": self.log_level,
            "health_check_enabled": self.health_check_enabled
        }


def load_config() -> AgentConfig:
    """Load and validate agent configuration."""
    return AgentConfig()