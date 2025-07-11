"""
Simple Kubernetes Activities for Temporal Workflows.

This module provides clean, simple activities that execute Kubernetes operations
using the Python Kubernetes client library. The activities are designed to run
independently from workflows to avoid any context bleeding issues.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime

from temporalio import activity
from kubernetes import client, config
from kubernetes.client.rest import ApiException


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@activity.defn
async def get_nodes(cluster_context: str) -> Dict[str, Any]:
    """
    Get Kubernetes nodes from a specific cluster.
    
    Args:
        cluster_context: The cluster context to use
        
    Returns:
        Dictionary containing node information
    """
    activity.logger.info(f"Getting nodes from cluster: {cluster_context}")
    
    try:
        # Load kubeconfig
        config.load_kube_config(context=cluster_context)
        
        # Create API client
        v1 = client.CoreV1Api()
        
        # Send heartbeat
        activity.heartbeat(f"Connected to cluster {cluster_context}")
        
        # Get nodes
        nodes = v1.list_node()
        
        # Process node information
        node_info = []
        for node in nodes.items:
            node_data = {
                "name": node.metadata.name,
                "status": "Ready" if any(
                    condition.type == "Ready" and condition.status == "True" 
                    for condition in node.status.conditions
                ) else "NotReady",
                "version": node.status.node_info.kubelet_version,
                "os": node.status.node_info.operating_system,
                "arch": node.status.node_info.architecture,
                "created": node.metadata.creation_timestamp.isoformat() if node.metadata.creation_timestamp else None
            }
            node_info.append(node_data)
            
        activity.heartbeat(f"Retrieved {len(node_info)} nodes")
        
        result = {
            "success": True,
            "cluster_context": cluster_context,
            "node_count": len(node_info),
            "nodes": node_info,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Successfully retrieved {len(node_info)} nodes from {cluster_context}"
        }
        
        activity.logger.info(f"Successfully retrieved {len(node_info)} nodes from {cluster_context}")
        return result
        
    except ApiException as e:
        error_msg = f"Kubernetes API error: {e.status} - {e.reason}"
        activity.logger.error(error_msg)
        return {
            "success": False,
            "cluster_context": cluster_context,
            "error": error_msg,
            "error_type": "ApiException",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        activity.logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "cluster_context": cluster_context,
            "error": error_msg,
            "error_type": type(e).__name__,
            "timestamp": datetime.utcnow().isoformat()
        }


@activity.defn
async def get_pods(cluster_context: str, namespace: str = "default") -> Dict[str, Any]:
    """
    Get pods from a specific namespace in a cluster.
    
    Args:
        cluster_context: The cluster context to use
        namespace: The namespace to query (default: "default")
        
    Returns:
        Dictionary containing pod information
    """
    activity.logger.info(f"Getting pods from namespace '{namespace}' in cluster: {cluster_context}")
    
    try:
        # Load kubeconfig
        config.load_kube_config(context=cluster_context)
        
        # Create API client
        v1 = client.CoreV1Api()
        
        # Send heartbeat
        activity.heartbeat(f"Connected to cluster {cluster_context}")
        
        # Get pods
        pods = v1.list_namespaced_pod(namespace=namespace)
        
        # Process pod information
        pod_info = []
        for pod in pods.items:
            pod_data = {
                "name": pod.metadata.name,
                "namespace": pod.metadata.namespace,
                "status": pod.status.phase,
                "ready": sum(1 for condition in pod.status.conditions or [] 
                           if condition.type == "Ready" and condition.status == "True"),
                "restarts": sum(container.restart_count or 0 for container in pod.status.container_statuses or []),
                "node": pod.spec.node_name,
                "created": pod.metadata.creation_timestamp.isoformat() if pod.metadata.creation_timestamp else None
            }
            pod_info.append(pod_data)
            
        activity.heartbeat(f"Retrieved {len(pod_info)} pods")
        
        result = {
            "success": True,
            "cluster_context": cluster_context,
            "namespace": namespace,
            "pod_count": len(pod_info),
            "pods": pod_info,
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Successfully retrieved {len(pod_info)} pods from namespace '{namespace}' in {cluster_context}"
        }
        
        activity.logger.info(f"Successfully retrieved {len(pod_info)} pods from namespace '{namespace}' in {cluster_context}")
        return result
        
    except ApiException as e:
        error_msg = f"Kubernetes API error: {e.status} - {e.reason}"
        activity.logger.error(error_msg)
        return {
            "success": False,
            "cluster_context": cluster_context,
            "namespace": namespace,
            "error": error_msg,
            "error_type": "ApiException",
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        activity.logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "cluster_context": cluster_context,
            "namespace": namespace,
            "error": error_msg,
            "error_type": type(e).__name__,
            "timestamp": datetime.utcnow().isoformat()
        }


@activity.defn
async def execute_kubectl_command(cluster_context: str, command: str, namespace: str = "default") -> Dict[str, Any]:
    """
    Execute a kubectl command using the Python Kubernetes client.
    
    Args:
        cluster_context: The cluster context to use
        command: The kubectl command to execute (e.g., "get nodes", "get pods")
        namespace: The namespace to use (default: "default")
        
    Returns:
        Dictionary containing command execution results
    """
    activity.logger.info(f"Executing kubectl command '{command}' in cluster: {cluster_context}")
    
    try:
        # Parse command
        cmd_parts = command.strip().split()
        if len(cmd_parts) < 2 or cmd_parts[0] != "get":
            return {
                "success": False,
                "cluster_context": cluster_context,
                "command": command,
                "error": "Only 'get' commands are supported",
                "error_type": "UnsupportedCommand",
                "timestamp": datetime.utcnow().isoformat()
            }
        
        resource_type = cmd_parts[1]
        
        # Route to appropriate handler
        if resource_type == "nodes":
            return await get_nodes(cluster_context)
        elif resource_type == "pods":
            return await get_pods(cluster_context, namespace)
        else:
            return {
                "success": False,
                "cluster_context": cluster_context,
                "command": command,
                "error": f"Unsupported resource type: {resource_type}",
                "error_type": "UnsupportedResource",
                "timestamp": datetime.utcnow().isoformat()
            }
            
    except Exception as e:
        error_msg = f"Command execution error: {str(e)}"
        activity.logger.error(error_msg, exc_info=True)
        return {
            "success": False,
            "cluster_context": cluster_context,
            "command": command,
            "error": error_msg,
            "error_type": type(e).__name__,
            "timestamp": datetime.utcnow().isoformat()
        }