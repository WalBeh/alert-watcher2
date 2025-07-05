"""
Configuration management for Alert Watcher 2.

This module handles environment variable configuration and application settings
for the simplified alert watcher system.
"""

import os
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class Config(BaseSettings):
    """Application configuration loaded from environment variables."""
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    log_level: str = Field(default="INFO", description="Logging level")
    
    # Temporal Configuration
    temporal_host: str = Field(default="localhost", description="Temporal server host")
    temporal_port: int = Field(default=7233, description="Temporal server port")
    temporal_namespace: str = Field(default="default", description="Temporal namespace")
    temporal_task_queue: str = Field(default="alert-processing", description="Temporal task queue")
    
    # Workflow Configuration
    workflow_id: str = Field(default="alert-processor", description="Main workflow ID")
    workflow_timeout_seconds: int = Field(default=3600, description="Workflow timeout in seconds")
    activity_timeout_seconds: int = Field(default=300, description="Activity timeout in seconds")
    
    # Retry Configuration
    max_retries: int = Field(default=3, description="Maximum retry attempts")
    retry_backoff_seconds: int = Field(default=2, description="Retry backoff base seconds")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        
    @property
    def temporal_address(self) -> str:
        """Get the full Temporal server address."""
        return f"{self.temporal_host}:{self.temporal_port}"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.log_level.upper() == "DEBUG"


# Global configuration instance
config = Config()