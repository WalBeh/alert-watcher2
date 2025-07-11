"""
Utility functions for file upload operations.

This module provides helper functions for Kubernetes operations, 
file management, and common tasks used across upload workflows.
"""

import os
import time
from datetime import datetime, timedelta
from typing import Optional

from kubernetes import client, config
from kubernetes.stream import stream
import structlog

from .models import (
    CrateDBPod,
    CommandExecutionResult,
    FileInfo,
    AWSCredentials,
)

logger = structlog.get_logger(__name__)


def load_kube_config(context: Optional[str] = None) -> None:
    """Load Kubernetes configuration."""
    try:
        if context:
            config.load_kube_config(context=context)
        else:
            config.load_kube_config()
    except Exception:
        # Try in-cluster config if local config fails
        config.load_incluster_config()


async def execute_command_in_pod_simple(
    pod: CrateDBPod,
    command: list[str],
    timeout: timedelta,
    env_vars: Optional[dict[str, str]] = None
) -> CommandExecutionResult:
    """
    Execute a simple command in a pod and return the result.
    
    Args:
        pod: Pod information
        command: Command to execute
        timeout: Command timeout
        env_vars: Optional environment variables
        
    Returns:
        CommandExecutionResult with exit code, stdout, stderr, and duration
    """
    start_time = time.time()
    
    try:
        # Load Kubernetes config
        load_kube_config()
        core_v1 = client.CoreV1Api()
        
        # Prepare command with environment variables
        exec_command = []
        if env_vars:
            for key, value in env_vars.items():
                exec_command.extend(["env", f"{key}={value}"])
        exec_command.extend(command)
        
        # Execute command
        exec_result = stream(
            core_v1.connect_get_namespaced_pod_exec,
            name=pod.name,
            namespace=pod.namespace,
            container=pod.container,
            command=exec_command,
            stderr=True,
            stdin=False,
            stdout=True,
            tty=False,
            _preload_content=False
        )
        
        stdout_content = []
        stderr_content = []
        
        # Read output
        while exec_result.is_open():
            exec_result.update(timeout=1)
            
            if exec_result.peek_stdout():
                stdout_content.append(exec_result.read_stdout())
            
            if exec_result.peek_stderr():
                stderr_content.append(exec_result.read_stderr())
            
            # Check timeout
            if time.time() - start_time > timeout.total_seconds():
                exec_result.close()
                raise TimeoutError(f"Command execution exceeded timeout of {timeout}")
        
        # Get exit code
        exit_code = exec_result.returncode if hasattr(exec_result, 'returncode') else 0
        
        return CommandExecutionResult(
            exit_code=exit_code,
            stdout="".join(stdout_content),
            stderr="".join(stderr_content),
            duration=timedelta(seconds=time.time() - start_time)
        )
        
    except Exception as e:
        logger.error(
            "Command execution failed",
            pod=pod.name,
            namespace=pod.namespace,
            command=command,
            error=str(e)
        )
        return CommandExecutionResult(
            exit_code=1,
            stdout="",
            stderr=str(e),
            duration=timedelta(seconds=time.time() - start_time)
        )


async def file_exists_in_pod(pod: CrateDBPod, file_path: str) -> bool:
    """Check if a file exists in the pod."""
    test_command = ["test", "-f", file_path]
    
    result = await execute_command_in_pod_simple(
        pod=pod,
        command=test_command,
        timeout=timedelta(minutes=1)
    )
    
    return result.exit_code == 0


async def get_file_info_in_pod(pod: CrateDBPod, file_path: str) -> FileInfo:
    """Get file information (size, modified time) from pod."""
    stat_command = ["stat", "-c", "%s %Y", file_path]
    
    result = await execute_command_in_pod_simple(
        pod=pod,
        command=stat_command,
        timeout=timedelta(minutes=1)
    )
    
    if result.exit_code != 0:
        raise RuntimeError(f"Failed to get file info: {result.stderr}")
    
    try:
        size_str, mtime_str = result.stdout.strip().split()
        return FileInfo(
            size=int(size_str),
            modified_time=datetime.fromtimestamp(int(mtime_str))
        )
    except (ValueError, IndexError) as e:
        raise RuntimeError(f"Failed to parse file info: {result.stdout}") from e


async def copy_script_to_pod(pod: CrateDBPod, script_content: str, destination_path: str) -> bool:
    """
    Copy a script file to a pod container.
    
    Args:
        pod: Pod information
        script_content: Content of the script to copy
        destination_path: Path where to save the script in the pod
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create the script file in the pod using a here-document
        create_file_command = [
            "sh", "-c", 
            f"cat > {destination_path} << 'SCRIPT_EOF'\n{script_content}\nSCRIPT_EOF"
        ]
        
        result = await execute_command_in_pod_simple(
            pod=pod,
            command=create_file_command,
            timeout=timedelta(minutes=2)
        )
        
        if result.exit_code != 0:
            logger.error(
                "Failed to copy script to pod",
                pod=pod.name,
                destination=destination_path,
                error=result.stderr
            )
            return False
        
        # Make script executable
        chmod_command = ["chmod", "+x", destination_path]
        chmod_result = await execute_command_in_pod_simple(
            pod=pod,
            command=chmod_command,
            timeout=timedelta(minutes=1)
        )
        
        if chmod_result.exit_code != 0:
            logger.error(
                "Failed to make script executable",
                pod=pod.name,
                destination=destination_path,
                error=chmod_result.stderr
            )
            return False
        
        logger.info(
            "Successfully copied script to pod",
            pod=pod.name,
            destination=destination_path
        )
        return True
        
    except Exception as e:
        logger.error(
            "Exception while copying script to pod",
            pod=pod.name,
            destination=destination_path,
            error=str(e)
        )
        return False


def get_flanker_script() -> str:
    """Get the flanker.py script content."""
    flanker_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 
        "flanker.py"
    )
    
    try:
        with open(flanker_path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"flanker.py not found at {flanker_path}")


def extract_pod_from_alert(alert_data: dict) -> CrateDBPod:
    """Extract pod information from alert data."""
    labels = alert_data.get("labels", {})
    namespace = labels.get("namespace")
    pod_name = labels.get("pod")
    container = labels.get("container", "crate")
    
    if not namespace or not pod_name:
        raise ValueError(f"Missing required labels: namespace={namespace}, pod={pod_name}")
    
    return CrateDBPod(
        name=pod_name,
        namespace=namespace,
        container=container
    )


def parse_flanker_progress(output: str) -> dict:
    """Parse flanker.py output for progress information."""
    progress_info = {}
    
    # Look for tqdm progress indicators
    import re
    if "%" in output and "MB/s" in output:
        # Extract progress percentage and speed
        # Example: "45%|████▌     | 450MB/900MB [01:23<01:45, 5.2MB/s]"
        progress_match = re.search(r'(\d+)%.*?(\d+\.\d+)MB/s', output)
        if progress_match:
            progress_info["progress_percent"] = int(progress_match.group(1))
            progress_info["upload_speed_mbps"] = float(progress_match.group(2))
    
    # Look for file size stability messages
    if "File size stable" in output:
        progress_info["file_stability"] = "stable"
    elif "File size changed" in output:
        progress_info["file_stability"] = "changing"
    
    # Look for upload completion
    if "Upload completed successfully" in output:
        progress_info["upload_status"] = "completed"
    elif "Upload failed" in output:
        progress_info["upload_status"] = "failed"
    
    return progress_info


def standard_retry_policy():
    """Get standard retry policy for activities."""
    from temporalio.common import RetryPolicy
    return RetryPolicy(
        initial_interval=timedelta(seconds=5),
        maximum_interval=timedelta(minutes=2),
        backoff_coefficient=2.0,
        maximum_attempts=3
    )