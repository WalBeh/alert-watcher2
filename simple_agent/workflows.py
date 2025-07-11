"""
Simple Kubernetes Workflows for Temporal.

This module provides clean, simple workflows that orchestrate Kubernetes operations
using activities. The workflows are designed to be straightforward and avoid
complex patterns that can lead to context bleeding issues.
"""

import asyncio
from datetime import timedelta
from typing import Dict, Any, List

from temporalio import workflow
from temporalio.common import RetryPolicy

from .k8s_activities import get_nodes, get_pods, execute_kubectl_command


@workflow.defn
class KubernetesWorkflow:
    """
    Simple Kubernetes workflow that executes operations on a cluster.
    
    This workflow demonstrates:
    - Simple activity execution
    - Proper error handling
    - Clean separation between workflow and activity logic
    """
    
    def __init__(self):
        self.results = []
        self.errors = []
    
    @workflow.run
    async def run(self, cluster_context: str, operations: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Execute a series of Kubernetes operations on a cluster.
        
        Args:
            cluster_context: The cluster context to use
            operations: List of operations to execute
            
        Returns:
            Dictionary containing execution results
        """
        workflow.logger.info(f"Starting Kubernetes operations on cluster: {cluster_context}")
        
        self.results = []
        self.errors = []
        
        for i, operation in enumerate(operations):
            try:
                workflow.logger.info(f"Executing operation {i+1}/{len(operations)}: {operation}")
                
                # Execute the operation based on type
                if operation.get("type") == "get_nodes":
                    result = await workflow.execute_activity(
                        get_nodes,
                        cluster_context,
                        start_to_close_timeout=timedelta(minutes=5),
                        heartbeat_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=1),
                            maximum_interval=timedelta(seconds=30),
                            backoff_coefficient=2.0,
                            maximum_attempts=3
                        )
                    )
                    
                elif operation.get("type") == "get_pods":
                    namespace = operation.get("namespace", "default")
                    result = await workflow.execute_activity(
                        get_pods,
                        cluster_context,
                        namespace,
                        start_to_close_timeout=timedelta(minutes=5),
                        heartbeat_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=1),
                            maximum_interval=timedelta(seconds=30),
                            backoff_coefficient=2.0,
                            maximum_attempts=3
                        )
                    )
                    
                elif operation.get("type") == "kubectl_command":
                    command = operation.get("command", "get nodes")
                    namespace = operation.get("namespace", "default")
                    result = await workflow.execute_activity(
                        execute_kubectl_command,
                        cluster_context,
                        command,
                        namespace,
                        start_to_close_timeout=timedelta(minutes=5),
                        heartbeat_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(
                            initial_interval=timedelta(seconds=1),
                            maximum_interval=timedelta(seconds=30),
                            backoff_coefficient=2.0,
                            maximum_attempts=3
                        )
                    )
                    
                else:
                    result = {
                        "success": False,
                        "error": f"Unknown operation type: {operation.get('type')}",
                        "error_type": "UnknownOperation"
                    }
                
                self.results.append(result)
                
                if result.get("success"):
                    workflow.logger.info(f"Operation {i+1} completed successfully")
                else:
                    workflow.logger.error(f"Operation {i+1} failed: {result.get('error')}")
                    self.errors.append(result)
                    
            except Exception as e:
                error_result = {
                    "success": False,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "operation": operation
                }
                self.errors.append(error_result)
                workflow.logger.error(f"Operation {i+1} failed with exception: {str(e)}")
        
        # Return summary
        successful_ops = len([r for r in self.results if r.get("success")])
        failed_ops = len(self.errors)
        
        workflow.logger.info(f"Completed {len(operations)} operations: {successful_ops} successful, {failed_ops} failed")
        
        return {
            "cluster_context": cluster_context,
            "total_operations": len(operations),
            "successful_operations": successful_ops,
            "failed_operations": failed_ops,
            "results": self.results,
            "errors": self.errors,
            "completed_at": workflow.now().isoformat()
        }

    @workflow.signal
    async def add_operation(self, operation: Dict[str, Any]):
        """Add a new operation to execute."""
        workflow.logger.info(f"Added operation: {operation}")
        # In a real implementation, you might queue this operation
        # For now, just log it
        
    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Get current workflow status."""
        return {
            "results_count": len(self.results),
            "errors_count": len(self.errors),
            "last_results": self.results[-3:] if self.results else []
        }


@workflow.defn
class SimpleAgentWorkflow:
    """
    Simple agent workflow that can execute Kubernetes operations.
    
    This is a minimal implementation that demonstrates how to properly
    separate workflow logic from activity execution.
    """
    
    def __init__(self):
        self.is_running = True
        self.operations_executed = 0
        
    @workflow.run
    async def run(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the simple agent.
        
        Args:
            config: Configuration dictionary
            
        Returns:
            Dictionary containing execution summary
        """
        workflow.logger.info("Starting Simple Agent Workflow")
        
        cluster_context = config.get("cluster_context", "default")
        
        # Execute a test operation
        test_operation = {
            "type": "get_nodes"
        }
        
        try:
            result = await workflow.execute_activity(
                get_nodes,
                cluster_context,
                start_to_close_timeout=timedelta(minutes=2),
                heartbeat_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=30),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )
            
            self.operations_executed += 1
            
            workflow.logger.info(f"Test operation completed: {result.get('success')}")
            
            return {
                "success": True,
                "cluster_context": cluster_context,
                "operations_executed": self.operations_executed,
                "test_result": result,
                "completed_at": workflow.now().isoformat()
            }
            
        except Exception as e:
            workflow.logger.error(f"Test operation failed: {str(e)}")
            return {
                "success": False,
                "cluster_context": cluster_context,
                "error": str(e),
                "error_type": type(e).__name__,
                "completed_at": workflow.now().isoformat()
            }
    
    @workflow.signal
    async def execute_command(self, command_data: Dict[str, Any]):
        """Execute a command signal."""
        workflow.logger.info(f"Received command: {command_data}")
        # In a real implementation, you would queue this command
        # For now, just log it
        
    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Get current status."""
        return {
            "is_running": self.is_running,
            "operations_executed": self.operations_executed
        }