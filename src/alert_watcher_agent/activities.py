"""
Alert Watcher Agent Activities.

This module provides Temporal activities for executing kubectl commands
with optimal use of Temporal SDK features including heartbeats, cancellation,
and proper error handling for long-running operations.
"""

import asyncio
import random
import time
from datetime import datetime
from typing import Dict, Any, Optional

# import logging
from temporalio import activity
from temporalio.exceptions import CancelledError

from .config import AgentConfig
from .models import CommandRequest, CommandResponse, CommandStatus, CommandType

# Configure pass-through imports to avoid time.localtime restrictions
import temporalio.workflow
import difflib
import os
from pathlib import Path
from typing import List

# Temporarily disable all logging to isolate time.localtime issue
# logger = logging.getLogger(__name__)

class NoOpLogger:
    def info(self, msg, **kwargs):
        pass
    def error(self, msg, **kwargs):
        pass
    def warning(self, msg, **kwargs):
        pass
    def debug(self, msg, **kwargs):
        pass

logger = NoOpLogger()


class KubeConfigHandler:
    """Handler for Kubernetes configuration."""

    def __init__(self, kubeconfig: Optional[str] = None):
        """
        Initialize the KubeConfigHandler.

        Args:
            kubeconfig: Path to kubeconfig file. If None, use KUBECONFIG env var or default.
        """
        self.kubeconfig = self._resolve_kubeconfig_path(kubeconfig)
        self.available_contexts = self._get_available_contexts()

    def _resolve_kubeconfig_path(self, kubeconfig: Optional[str] = None) -> str:
        """
        Resolve kubeconfig path from specified path, KUBECONFIG env var, or default.

        Args:
            kubeconfig: Explicitly specified kubeconfig path

        Returns:
            Resolved kubeconfig path
        """
        if kubeconfig:
            return kubeconfig

        env_kubeconfig = os.environ.get("KUBECONFIG")
        if env_kubeconfig:
            # Handle colon-separated paths in KUBECONFIG
            paths = env_kubeconfig.split(":")
            for path in paths:
                if Path(path).exists():
                    logger.debug(f"Using kubeconfig from KUBECONFIG env var: {path}")
                    return path

            # If we get here, none of the paths in KUBECONFIG exist
            logger.warning(f"None of the kubeconfig paths in KUBECONFIG exist: {env_kubeconfig}")

        # Use default kubeconfig path
        default_path = os.path.expanduser("~/.kube/config")
        if Path(default_path).exists():
            logger.debug(f"Using default kubeconfig: {default_path}")
            return default_path

        raise FileNotFoundError("Could not find a valid kubeconfig file")

    def _get_available_contexts(self) -> List[str]:
        """
        Get list of available contexts from kubeconfig.

        Returns:
            List of context names
        """
        from kubernetes import config
        contexts, _ = config.list_kube_config_contexts(config_file=self.kubeconfig)
        if not contexts:
            logger.warning("No contexts found in kubeconfig")
            return []
        return [context["name"] for context in contexts]

    def load_context(self, context_name: Optional[str] = None) -> None:
        """
        Load the specified Kubernetes context.

        Args:
            context_name: Name of the context to load. If None, use current context.

        Raises:
            ValueError: If the specified context does not exist
        """
        from kubernetes import config
        if context_name is None:
            config.load_kube_config(config_file=self.kubeconfig)
            logger.debug("Loaded default Kubernetes context")
            return

        if context_name not in self.available_contexts:
            close_matches = difflib.get_close_matches(context_name, self.available_contexts, n=3, cutoff=0.6)
            suggestion_msg = f" Did you mean: {', '.join(close_matches)}?" if close_matches else ""
            # Only show up to 5 contexts in the error message to avoid verbosity
            contexts_sample = self.available_contexts[:5]
            contexts_more = f" and {len(self.available_contexts) - 5} more..." if len(self.available_contexts) > 5 else ""

            raise ValueError(
                f"Context '{context_name}' not found in kubeconfig.{suggestion_msg}\nAvailable contexts: {', '.join(contexts_sample)}{contexts_more}"
            )

        config.load_kube_config(config_file=self.kubeconfig, context=context_name)
        logger.debug(f"Loaded Kubernetes context: {context_name}")

    def get_current_context(self) -> str:
        """
        Get the current context name.

        Returns:
            Current context name
        """
        from kubernetes import config
        _, current_context = config.list_kube_config_contexts(config_file=self.kubeconfig)
        return current_context["name"]


class KubernetesClientManager:
    """Manages Kubernetes client connections with context switching."""
    
    def __init__(self, config: AgentConfig):
        self.config = config
        self._clients: Dict[str, Any] = {}
        self._validated_contexts: Dict[str, bool] = {}
    
    def get_client(self, cluster_context: str):
        """Get or create a Kubernetes client for the specified context."""
        from kubernetes import client
        
        if cluster_context not in self._clients:
            try:
                # Use KubeConfigHandler to properly load context
                kube_handler = KubeConfigHandler()
                kube_handler.load_context(cluster_context)
                self._clients[cluster_context] = client.CoreV1Api()
                self._validated_contexts[cluster_context] = True
                
                # logger.info(f"Kubernetes client created for cluster_context: {cluster_context}")
                pass
                
            except Exception as e:
                # logger.error(f"Failed to create Kubernetes client for cluster_context: {cluster_context}, error: {str(e)}")
                pass
                raise
        
        return self._clients[cluster_context]
    
    def validate_context(self, cluster_context: str) -> bool:
        """Validate that the cluster context is accessible."""
        if cluster_context in self._validated_contexts:
            return self._validated_contexts[cluster_context]
        
        try:
            # Test basic connectivity
            k8s_client = self.get_client(cluster_context)
            # Simple test - try to get default namespace
            k8s_client.read_namespace("default")
            self._validated_contexts[cluster_context] = True
            return True
        except Exception as e:
            # logger.error(f"Cluster context validation failed for cluster_context: {cluster_context}, error: {str(e)}")
            pass
            self._validated_contexts[cluster_context] = False
            return False


# Removed global client manager to avoid workflow context restrictions
# Client manager will be created per activity execution


@activity.defn(name="execute_kubectl_command")
async def execute_kubectl_command(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute kubectl command using Python Kubernetes client with optimal Temporal patterns.
    
    This activity demonstrates:
    - Proper heartbeat management for long-running operations
    - Graceful cancellation handling
    - Structured error handling and logging
    - Progress reporting
    - Resource cleanup
    
    Args:
        request_data: Dictionary containing CommandRequest data
        
    Returns:
        Dictionary containing CommandResponse data
    """
    # Parse request
    try:
        request = CommandRequest.from_dict(request_data)
    except Exception as e:
        # logger.error(f"Failed to parse command request, error: {str(e)}, request_data: {request_data}")
        pass
        return CommandResponse.error_response(
            alert_id=request_data.get("alert_id", "unknown"),
            cluster_context=request_data.get("cluster_context", "unknown"),
            message=f"Invalid request format: {str(e)}",
            error_type="RequestParseError"
        ).to_dict()
    
    # Initialize response
    response = CommandResponse(
        success=False,
        message="",
        cluster_context=request.cluster_context,
        alert_id=request.alert_id,
        correlation_id=request.correlation_id,
        status=CommandStatus.RUNNING,
        started_at=None  # Will be set by caller outside of restricted context
    )
    
    activity_logger = logger
    
    # activity_logger.info(f"Starting kubectl command execution - alert_id: {request.alert_id}, cluster_context: {request.cluster_context}, correlation_id: {request.correlation_id}, command_type: {request.command_type.value}")
    
    try:
        # Ultra-minimal test - skip all heartbeat, config loading and client manager creation
        # No external dependencies at all
        
        # Execute the appropriate command based on type
        if request.command_type == CommandType.KUBECTL_TEST:
            result = await _execute_kubectl_test(request, None, activity_logger)
        elif request.command_type == CommandType.HEMAKO_JFR:
            result = await _execute_hemako_jfr(request, None, activity_logger)
        elif request.command_type == CommandType.HEMAKO_CRASH_HEAPDUMP:
            result = await _execute_hemako_crash_heapdump(request, None, activity_logger)
        else:
            raise ValueError(f"Unsupported command type: {request.command_type}")
        
        # Update response with results
        response.success = result["success"]
        response.message = result["message"]
        response.command_executed = result.get("command_executed", "")
        response.stdout = result.get("stdout", "")
        response.stderr = result.get("stderr", "")
        response.return_code = result.get("return_code")
        response.pod_count = result.get("pod_count")
        response.namespace_info = result.get("namespace_info", {})
        response.simulation_sleep_minutes = result.get("simulation_sleep_minutes")
        response.heartbeat_count = result.get("heartbeat_count", 0)
        response.status = CommandStatus.COMPLETED
        
        # activity_logger.info(f"Kubectl command execution completed - success: {response.success}, execution_duration_seconds: {response.execution_duration_seconds}, pod_count: {response.pod_count}, simulation_sleep_minutes: {response.simulation_sleep_minutes}")
        pass
        
    except CancelledError:
        # activity_logger.warning("Activity was cancelled")
        pass
        response.success = False
        response.message = "Command execution was cancelled"
        response.status = CommandStatus.CANCELLED
        response.error_type = "CancelledError"
        
    except Exception as e:
        # activity_logger.error(f"Kubectl command execution failed - error: {str(e)}, error_type: {type(e).__name__}", exc_info=True)
        pass
        response.success = False
        response.message = f"Command execution failed: {str(e)}"
        response.status = CommandStatus.FAILED
        response.error_type = type(e).__name__
        response.error_details = {
            "exception": str(e),
            "exception_type": type(e).__name__
        }
    
    finally:
        # Completion timestamp will be set by caller outside of restricted context
        response.completed_at = None
        if response.started_at:
            # Duration calculation will be done by caller
            response.execution_duration_seconds = None
    
    return response.to_dict()


async def _execute_kubectl_test(
    request: CommandRequest,
    client_manager,  # Can be None for minimal test
    activity_logger
) -> Dict[str, Any]:
    """Execute kubectl test command (MINIMAL VERSION - no Kubernetes calls)."""
    
    try:
        # Simulate kubectl test without actual Kubernetes calls
        # Skip heartbeat to test if that's causing time.localtime issue
        # This is a minimal test to isolate the time.localtime issue
        pod_count = 3  # Simulated pod count
        namespace_data = {
            "name": request.namespace,
            "creation_timestamp": "2025-01-01T00:00:00Z",
            "uid": "simulated-namespace-uid",
            "labels": {"env": "test"},
            "annotations": {"test": "simulated"}
        }
        
        # Skip all config loading and random operations for ultra-minimal test
        sleep_minutes = 0
        heartbeat_count = 1

        return {
            "success": True,
            "message": "Ultra-minimal test completed",
            "command_executed": "simulated",
            "stdout": "simulated",
            "stderr": "",
            "return_code": 0,
            "pod_count": 3,
            "namespace_info": {"name": "test"},
            "simulation_sleep_minutes": 0,
            "heartbeat_count": 1
        }
        
    except Exception as e:
        # activity_logger.error(f"Unexpected error during kubectl test - error: {str(e)}", exc_info=True)
        pass
        raise


async def _execute_hemako_jfr(
    request: CommandRequest,
    client_manager,
    activity_logger
) -> Dict[str, Any]:
    """Execute hemako JFR command (placeholder for future implementation)."""
    
    # activity_logger.info("Executing hemako JFR command (placeholder)")
    pass
    
    # For now, this is a placeholder that simulates hemako JFR execution
    # In production, this would execute: hemako jfr --jfr --namespace {namespace} --pod {pod}
    
    await asyncio.sleep(2)  # Simulate setup time
    activity.heartbeat(f"Hemako JFR setup completed for {request.alert_id}")
    
    # Simulate long-running JFR collection
    from .config import load_config
    config = load_config()
    if config.simulate_long_running:
        sleep_minutes = random.randint(config.min_sleep_minutes, config.max_sleep_minutes)
        heartbeat_count = await _simulate_long_running_operation(
            sleep_minutes, 
            request.alert_id, 
            activity_logger
        )
    else:
        sleep_minutes = 0
        heartbeat_count = 1
    
    return {
        "success": True,
        "message": f"Hemako JFR command completed for {request.pod} in {request.namespace}",
        "command_executed": f"hemako jfr --jfr --namespace {request.namespace} --pod {request.pod}",
        "stdout": f"JFR data collected successfully from {request.pod}",
        "stderr": "",
        "return_code": 0,
        "simulation_sleep_minutes": sleep_minutes,
        "heartbeat_count": heartbeat_count
    }


async def _execute_hemako_crash_heapdump(
    request: CommandRequest,
    client_manager,
    activity_logger
) -> Dict[str, Any]:
    """Execute hemako crash heapdump command (placeholder for future implementation)."""
    
    # activity_logger.info("Executing hemako crash heapdump command (placeholder)")
    pass
    
    # For now, this is a placeholder that simulates hemako crash heapdump execution
    # In production, this would execute: hemako jfr --crash-heapdump-upload --namespace {namespace} --pod {pod}
    
    await asyncio.sleep(2)  # Simulate setup time
    activity.heartbeat(f"Hemako crash heapdump setup completed for {request.alert_id}")
    
    # Simulate long-running heapdump upload
    from .config import load_config
    config = load_config()
    if config.simulate_long_running:
        sleep_minutes = random.randint(config.min_sleep_minutes, config.max_sleep_minutes)
        heartbeat_count = await _simulate_long_running_operation(
            sleep_minutes, 
            request.alert_id, 
            activity_logger
        )
    else:
        sleep_minutes = 0
        heartbeat_count = 1
    
    return {
        "success": True,
        "message": f"Hemako crash heapdump command completed for {request.pod} in {request.namespace}",
        "command_executed": f"hemako jfr --crash-heapdump-upload --namespace {request.namespace} --pod {request.pod}",
        "stdout": f"Crash heapdump uploaded successfully from {request.pod}",
        "stderr": "",
        "return_code": 0,
        "simulation_sleep_minutes": sleep_minutes,
        "heartbeat_count": heartbeat_count
    }


async def _simulate_long_running_operation(
    duration_minutes: int,
    alert_id: str,
    activity_logger
) -> int:
    """
    Simulate a long-running operation with proper heartbeat management.
    
    Args:
        duration_minutes: How long to simulate the operation
        alert_id: Alert ID for heartbeat messages
        activity_logger: Logger instance
        
    Returns:
        Number of heartbeats sent
    """
    heartbeat_count = 0
    
    try:
        for minute in range(duration_minutes):
            # Check for cancellation
            if activity.is_cancelled():
                # activity_logger.info(f"Long-running operation cancelled - completed_minutes: {minute}, total_minutes: {duration_minutes}")
                pass
                raise CancelledError("Operation was cancelled")
            
            # Send heartbeat with progress information
            progress_message = f"Processing minute {minute + 1}/{duration_minutes} for {alert_id}"
            activity.heartbeat(progress_message)
            heartbeat_count += 1
            
            # activity_logger.debug(f"Long-running operation progress - minute: {minute + 1}, total_minutes: {duration_minutes}, progress_percent: {((minute + 1) / duration_minutes) * 100}")
            pass
            
            # Sleep for 1 minute (60 seconds)
            await asyncio.sleep(60)
        
        # activity_logger.info(f"Long-running operation completed - duration_minutes: {duration_minutes}, heartbeat_count: {heartbeat_count}")
        pass
        
    except CancelledError:
        # activity_logger.warning(f"Long-running operation was cancelled - completed_minutes: {minute if 'minute' in locals() else 0}, total_minutes: {duration_minutes}, heartbeat_count: {heartbeat_count}")
        pass
        raise
    
    return heartbeat_count


# Activity for testing connectivity to all clusters
@activity.defn(name="test_all_clusters_connectivity")
async def test_all_clusters_connectivity() -> Dict[str, Any]:
    """
    Test connectivity to all configured clusters.
    
    Returns:
        Dictionary with connectivity results for each cluster
    """
    # logger.info("Testing connectivity to all clusters")
    pass
    
    from .config import load_config
    config = load_config()
    # Create a minimal test without KubernetesClientManager to avoid import issues
    results = {}
    
    for cluster_context in config.supported_clusters:
        try:
            activity.heartbeat(f"Testing connectivity to {cluster_context}")
            
            # Use KubeConfigHandler to test connectivity
            kube_handler = KubeConfigHandler()
            
            # Check if context exists
            if cluster_context in kube_handler.available_contexts:
                # Try to load the context and create a client
                from kubernetes import client
                kube_handler.load_context(cluster_context)
                k8s_client = client.CoreV1Api()
                
                # Simple connectivity test - try to read default namespace
                namespace = k8s_client.read_namespace("default")
                
                results[cluster_context] = {
                    "accessible": True,
                    "namespace_name": namespace.metadata.name,
                    "namespace_uid": namespace.metadata.uid,
                    "error": None
                }
                
                # logger.info(f"Cluster connectivity test passed for {cluster_context}")
                pass
            else:
                results[cluster_context] = {
                    "accessible": False,
                    "error": f"Context '{cluster_context}' not found in kubeconfig"
                }
                
        except Exception as e:
            # logger.error(f"Cluster connectivity test failed for {cluster_context}: {str(e)}")
            pass
            results[cluster_context] = {
                "accessible": False,
                "error": str(e)
            }
    
    # Summary
    accessible_count = sum(1 for result in results.values() if result["accessible"])
    total_count = len(results)
    
    # logger.info(f"Cluster connectivity test completed: {accessible_count}/{total_count} accessible")
    pass
    
    return {
        "success": accessible_count > 0,
        "accessible_clusters": accessible_count,
        "total_clusters": total_count,
        "results": results
    }