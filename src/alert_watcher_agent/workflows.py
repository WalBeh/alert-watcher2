"""
Alert Watcher Agent Workflows.

This module provides Temporal workflows for the Alert Watcher Agent with optimal
use of Temporal SDK features including child workflows, signals, queries, and
proper lifecycle management for long-running coordinators.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# structlog removed due to workflow sandbox restrictions - use workflow.logger instead
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from .config import AgentConfig
from .models import (
    CommandRequest,
    CommandResponse,
    CommandStatus,
    CommandType,
    ClusterStatus,
    AgentStatus,
    QueuedCommand,
    determine_command_type,
    calculate_priority
)

# Configure structured logging - use workflow.logger in workflow contexts
# logger = structlog.get_logger(__name__)  # Removed due to sandbox restrictions


@workflow.defn
class AgentCoordinatorWorkflow:
    """
    Main coordinator workflow that manages cluster-specific worker workflows.

    This workflow demonstrates optimal Temporal patterns:
    - Long-running coordinator with continue-as-new
    - Child workflow management
    - Signal-based communication
    - Query support for monitoring
    - Proper error handling and recovery
    """

    def __init__(self):
        self.agent_id = workflow.info().workflow_id
        self.cluster_workflows: Dict[str, workflow.ChildWorkflowHandle] = {}
        self.supported_clusters: List[str] = []
        self.is_running = True
        self.started_at: Optional[datetime] = None
        self.total_commands_processed = 0
        self.total_commands_failed = 0
        self.command_history: List[Dict[str, Any]] = []
        self.config_dict: Optional[Dict[str, Any]] = None

    @workflow.run
    async def run(self, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main coordinator workflow execution.

        Args:
            config_dict: Configuration dictionary

        Returns:
            Final execution summary
        """
        # Initialize configuration
        self.config_dict = config_dict
        self.supported_clusters = config_dict.get("supported_clusters", [])
        self.started_at = workflow.now()

        workflow.logger.info(
            f"Agent coordinator workflow started - agent_id: {self.agent_id}, workflow_id: {workflow.info().workflow_id}, run_id: {workflow.info().run_id}, supported_clusters: {self.supported_clusters}"
        )

        try:
            # Start cluster worker workflows
            await self._start_cluster_workflows()

            # Main coordination loop
            while self.is_running:
                try:
                    # Monitor cluster workflows
                    await self._monitor_cluster_workflows()

                    # Perform maintenance tasks
                    await self._perform_maintenance()

                    # Check if we should continue as new
                    if await self._should_continue_as_new():
                        workflow.logger.info(
                            f"Continue-as-new triggered - agent_id: {self.agent_id}, total_commands_processed: {self.total_commands_processed}, history_size: {len(self.command_history)}"
                        )
                        workflow.continue_as_new(config_dict)

                    # Sleep before next iteration
                    await workflow.sleep(60)  # Check every minute

                except Exception as e:
                    workflow.logger.error(
                        f"Error in coordinator main loop - agent_id: {self.agent_id}, error: {str(e)}, error_type: {type(e).__name__}"
                    )
                    await workflow.sleep(30)  # Wait before retrying

            workflow.logger.info(
                f"Agent coordinator workflow completed - agent_id: {self.agent_id}, total_commands_processed: {self.total_commands_processed}, total_commands_failed: {self.total_commands_failed}"
            )

        except Exception as e:
            workflow.logger.error(
                f"Fatal error in coordinator workflow - agent_id: {self.agent_id}, error: {str(e)}, error_type: {type(e).__name__}"
            )
            raise

        return {
            "agent_id": self.agent_id,
            "total_commands_processed": self.total_commands_processed,
            "total_commands_failed": self.total_commands_failed,
            "supported_clusters": self.supported_clusters,
            "completion_time": workflow.now().isoformat()
        }

    async def _start_cluster_workflows(self):
        """Start worker workflows for each supported cluster."""
        # Start cluster worker workflows
        for cluster_context in self.supported_clusters:
            try:
                workflow_id = f"cluster-worker-{cluster_context}-{self.agent_id}"
                task_queue = self.config_dict.get("task_queues", {}).get(cluster_context, f"alert-watcher-agent-{cluster_context}")

                # Start child workflow with proper configuration
                handle = await workflow.start_child_workflow(
                    ClusterWorkerWorkflow.run,
                    args=[cluster_context, self.config_dict],
                    id=workflow_id,
                    task_queue=task_queue,
                    retry_policy=RetryPolicy(
                        initial_interval=timedelta(seconds=self.config_dict.get("retry_policy", {}).get("initial_interval_seconds", 1)),
                        maximum_interval=timedelta(seconds=self.config_dict.get("retry_policy", {}).get("maximum_interval_seconds", 60)),
                        backoff_coefficient=self.config_dict.get("retry_policy", {}).get("backoff_coefficient", 2.0),
                        maximum_attempts=self.config_dict.get("retry_policy", {}).get("maximum_attempts", 3)
                    )
                )

                self.cluster_workflows[cluster_context] = handle

                workflow.logger.info(
                    f"Cluster worker workflow started - cluster_context: {cluster_context}, workflow_id: {workflow_id}, task_queue: {task_queue}"
                )

            except Exception as e:
                workflow.logger.error(
                    f"Failed to start cluster worker workflow - cluster_context: {cluster_context}, error: {str(e)}, error_type: {type(e).__name__}"
                )
                # Continue with other clusters even if one fails
                continue

    async def _monitor_cluster_workflows(self):
        """Monitor health of cluster worker workflows."""
        for cluster_context, handle in self.cluster_workflows.items():
            try:
                # Check if workflow is still running by querying its status
                # Skip monitoring for now to avoid workflow sandbox issues
                # In production, this would use workflow queries to check health
                pass

            except Exception as e:
                workflow.logger.error(
                    f"Error monitoring cluster workflow - cluster_context: {cluster_context}, error: {str(e)}"
                )

    async def _perform_maintenance(self):
        """Perform periodic maintenance tasks."""
        try:
            # Clean up old command history if needed
            history_threshold = 1000  # Default threshold
            if len(self.command_history) > history_threshold:
                # Keep only the most recent entries
                keep_count = history_threshold // 2
                self.command_history = self.command_history[-keep_count:]

                workflow.logger.info(
                    f"Command history cleaned up - kept_entries: {len(self.command_history)}, agent_id: {self.agent_id}"
                )

            workflow.logger.debug(
                f"Maintenance completed - agent_id: {self.agent_id}, commands_processed: {self.total_commands_processed}, history_size: {len(self.command_history)}, active_clusters: {len(self.cluster_workflows)}"
            )

        except Exception as e:
            workflow.logger.error(
                f"Maintenance task failed - agent_id: {self.agent_id}, error: {str(e)}"
            )

    async def _should_continue_as_new(self) -> bool:
        """Determine if workflow should continue as new."""
        return (
            self.total_commands_processed > 1000 or  # Default threshold
            len(self.command_history) > 1000  # Default threshold
        )

    @workflow.signal
    async def execute_command(self, command_data: Dict[str, Any]):
        """
        Signal handler for executing commands.

        Args:
            command_data: Dictionary containing command request data
        """
        try:
            # Parse command request and set created_at using workflow.now()
            request = CommandRequest.from_dict(command_data)
            if request.created_at is None:
                request.created_at = workflow.now()

            # Validate cluster context
            if request.cluster_context not in self.supported_clusters:
                workflow.logger.error(
                    f"Command routed to unsupported cluster - cluster_context: {request.cluster_context}, alert_id: {request.alert_id}, supported_clusters: {self.supported_clusters}"
                )
                return

            # Route to appropriate cluster workflow
            if request.cluster_context in self.cluster_workflows:
                handle = self.cluster_workflows[request.cluster_context]
                await handle.signal("queue_command", command_data)

                # Track command
                self.total_commands_processed += 1
                self.command_history.append({
                    "alert_id": request.alert_id,
                    "cluster_context": request.cluster_context,
                    "command_type": request.command_type.value,
                    "routed_at": workflow.now().isoformat(),
                    "correlation_id": request.correlation_id
                })

                workflow.logger.info(
                    f"Command routed to cluster workflow - alert_id: {request.alert_id}, cluster_context: {request.cluster_context}, command_type: {request.command_type.value}, correlation_id: {request.correlation_id}"
                )
            else:
                workflow.logger.error(
                    f"Cluster workflow not found for command - cluster_context: {request.cluster_context}, alert_id: {request.alert_id}"
                )

        except Exception as e:
            workflow.logger.error(
                f"Failed to process execute_command signal - error: {str(e)}, error_type: {type(e).__name__}, command_data: {command_data}"
            )

    @workflow.signal
    async def command_completed(self, result_data: Dict[str, Any]):
        """
        Signal handler for command completion notifications.

        Args:
            result_data: Dictionary containing command result data
        """
        try:
            response = CommandResponse.from_dict(result_data)

            if not response.success:
                self.total_commands_failed += 1

            workflow.logger.info(
                f"Command completion notification received - alert_id: {response.alert_id}, cluster_context: {response.cluster_context}, success: {response.success}, correlation_id: {response.correlation_id}"
            )

        except Exception as e:
            workflow.logger.error(
                f"Failed to process command_completed signal - error: {str(e)}, result_data: {result_data}"
            )

    @workflow.signal
    async def shutdown(self, reason: str = "manual"):
        """
        Signal handler for graceful shutdown.

        Args:
            reason: Reason for shutdown
        """
        workflow.logger.info(
            f"Shutdown signal received - agent_id: {self.agent_id}, reason: {reason}"
        )
        self.is_running = False

    @workflow.query
    def get_agent_status(self) -> Dict[str, Any]:
        """Query handler for agent status."""
        return AgentStatus(
            agent_id=self.agent_id,
            is_running=self.is_running,
            started_at=self.started_at,
            supported_clusters=self.supported_clusters,
            total_commands_processed=self.total_commands_processed,
            total_commands_failed=self.total_commands_failed
        ).to_dict()

    @workflow.query
    def get_cluster_workflows(self) -> Dict[str, str]:
        """Query handler for active cluster workflows."""
        return {
            cluster: handle.id
            for cluster, handle in self.cluster_workflows.items()
        }


@workflow.defn
class ClusterWorkerWorkflow:
    """
    Worker workflow for processing commands for a specific cluster.

    This workflow demonstrates:
    - Sequential command processing per cluster
    - Queue management with priority support
    - Activity execution with proper timeouts
    - Continue-as-new for long-running workers
    """

    def __init__(self):
        self.cluster_context = ""
        self.command_queue: List[QueuedCommand] = []
        self.processing = False
        self.current_command: Optional[CommandRequest] = None
        self.total_processed = 0
        self.total_failed = 0
        self.last_execution_at: Optional[datetime] = None
        self.last_error: Optional[str] = None
        self.started_at: Optional[datetime] = None
        self.config_dict: Optional[Dict[str, Any]] = None
        self.is_running = True

    @workflow.run
    async def run(self, cluster_context: str, config_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main worker workflow execution.

        Args:
            cluster_context: Cluster context this worker handles
            config_dict: Configuration dictionary

        Returns:
            Final execution summary
        """
        self.cluster_context = cluster_context
        self.config_dict = config_dict
        self.started_at = workflow.now()

        workflow.logger.info(
            f"Cluster worker workflow started - cluster_context: {cluster_context}, workflow_id: {workflow.info().workflow_id}, run_id: {workflow.info().run_id}, task_queue: {config_dict.get('task_queues', {}).get(cluster_context, f'alert-watcher-agent-{cluster_context}')}"
        )

        try:
            # Main processing loop
            while self.is_running:
                try:
                    # Process queued commands
                    await self._process_command_queue()

                    # Check if we should continue as new
                    if await self._should_continue_as_new():
                        workflow.logger.info(
                            f"Continue-as-new triggered for cluster worker - cluster_context: {self.cluster_context}, total_processed: {self.total_processed}"
                        )
                        workflow.continue_as_new(cluster_context, config_dict)

                    # Sleep before next iteration
                    await workflow.sleep(10)  # Check every 10 seconds

                except Exception as e:
                    workflow.logger.error(
                        f"Error in cluster worker main loop - cluster_context: {self.cluster_context}, error: {str(e)}, error_type: {type(e).__name__}"
                    )
                    await workflow.sleep(30)  # Wait before retrying

            workflow.logger.info(
                f"Cluster worker workflow completed gracefully - cluster_context: {self.cluster_context}, total_processed: {self.total_processed}, total_failed: {self.total_failed}"
            )

        except Exception as e:
            workflow.logger.error(
                f"Fatal error in cluster worker workflow - cluster_context: {self.cluster_context}, error: {str(e)}, error_type: {type(e).__name__}"
            )
            raise

        return {
            "cluster_context": self.cluster_context,
            "total_processed": self.total_processed,
            "total_failed": self.total_failed,
            "completion_time": workflow.now().isoformat()
        }

    async def _process_command_queue(self):
        """Process commands from the queue sequentially."""
        if not self.command_queue or self.processing:
            return

        # Sort queue by priority (higher priority first)
        self.command_queue.sort(key=lambda x: x.request.priority, reverse=True)

        # Get next command
        queued_command = self.command_queue.pop(0)
        request = queued_command.request

        self.processing = True
        self.current_command = request

        try:
            workflow.logger.info(
                f"Starting command execution - cluster_context: {self.cluster_context}, alert_id: {request.alert_id}, command_type: {request.command_type.value}, queue_remaining: {len(self.command_queue)}, correlation_id: {request.correlation_id}"
            )

            # Start appropriate child workflow based on command type
            result_dict = await self._start_command_child_workflow(request)

            # Parse result
            response = CommandResponse.from_dict(result_dict)

            # Update statistics
            self.total_processed += 1
            self.last_execution_at = workflow.now()

            if response.success:
                workflow.logger.info(
                    f"Command executed successfully - cluster_context: {self.cluster_context}, alert_id: {request.alert_id}, command_type: {request.command_type.value}, execution_duration_seconds: {response.execution_duration_seconds}, correlation_id: {request.correlation_id}"
                )
                self.last_error = None
            else:
                self.total_failed += 1
                self.last_error = response.message
                workflow.logger.error(
                    f"Command execution failed - cluster_context: {self.cluster_context}, alert_id: {request.alert_id}, command_type: {request.command_type.value}, error: {response.message}, correlation_id: {request.correlation_id}"
                )

            # Notify coordinator of completion
            coordinator_handle = workflow.get_external_workflow_handle(
                workflow.info().parent.workflow_id
            )
            await coordinator_handle.signal("command_completed", result_dict)

        except Exception as e:
            self.total_failed += 1
            self.last_error = str(e)

            workflow.logger.error(
                f"Command execution failed with exception - cluster_context: {self.cluster_context}, alert_id: {request.alert_id}, command_type: {request.command_type.value}, error: {str(e)}, error_type: {type(e).__name__}, correlation_id: {request.correlation_id}"
            )

        finally:
            self.processing = False
            self.current_command = None

    async def _start_command_child_workflow(self, request: CommandRequest) -> Dict[str, Any]:
        """
        Start appropriate child workflow based on command type.

        Args:
            request: CommandRequest object

        Returns:
            Dictionary containing CommandResponse data
        """
        # Generate unique workflow ID for the child workflow
        child_workflow_id = f"kubectl-exec-{request.alert_id}-{request.command_type.value}-{workflow.now().timestamp()}"

        # Get timeout and retry configuration
        activity_timeouts = self.config_dict.get("activity_timeouts", {})

        # Start appropriate child workflow
        if request.command_type == CommandType.KUBECTL_TEST:
            result_dict = await workflow.execute_child_workflow(
                KubectlTestWorkflow.run,
                request.to_dict(),
                id=child_workflow_id,
                task_queue=self.config_dict.get("task_queues", {}).get(self.cluster_context, f"alert-watcher-agent-{self.cluster_context}"),
                execution_timeout=timedelta(minutes=activity_timeouts.get("schedule_to_close_minutes", 30)),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=60),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )
        elif request.command_type == CommandType.HEMAKO_JFR:
            result_dict = await workflow.execute_child_workflow(
                HemakoJfrWorkflow.run,
                request.to_dict(),
                id=child_workflow_id,
                task_queue=self.config_dict.get("task_queues", {}).get(self.cluster_context, f"alert-watcher-agent-{self.cluster_context}"),
                execution_timeout=timedelta(minutes=activity_timeouts.get("schedule_to_close_minutes", 30)),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=60),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )
        elif request.command_type == CommandType.HEMAKO_CRASH_HEAPDUMP:
            result_dict = await workflow.execute_child_workflow(
                HemakoCrashHeapdumpWorkflow.run,
                request.to_dict(),
                id=child_workflow_id,
                task_queue=self.config_dict.get("task_queues", {}).get(self.cluster_context, f"alert-watcher-agent-{self.cluster_context}"),
                execution_timeout=timedelta(minutes=activity_timeouts.get("schedule_to_close_minutes", 30)),
                retry_policy=RetryPolicy(
                    initial_interval=timedelta(seconds=1),
                    maximum_interval=timedelta(seconds=60),
                    backoff_coefficient=2.0,
                    maximum_attempts=3
                )
            )
        else:
            raise ValueError(f"Unsupported command type: {request.command_type}")

        workflow.logger.info(
            f"Child workflow completed - workflow_id: {child_workflow_id}, command_type: {request.command_type.value}, alert_id: {request.alert_id}"
        )

        return result_dict

    async def _should_continue_as_new(self) -> bool:
        """Determine if workflow should continue as new."""
        return self.total_processed > 1000  # Default threshold

    @workflow.signal
    async def queue_command(self, command_data: Dict[str, Any]):
        """
        Signal handler for queuing commands.

        Args:
            command_data: Dictionary containing command request data
        """
        try:
            request = CommandRequest.from_dict(command_data)

            # Check for duplicates
            if any(qc.request.alert_id == request.alert_id for qc in self.command_queue):
                workflow.logger.warning(
                    f"Duplicate command request ignored - cluster_context: {self.cluster_context}, alert_id: {request.alert_id}"
                )
                return

            # Add to queue
            queued_command = QueuedCommand(
                request=request,
                queued_at=workflow.now(),
                position=len(self.command_queue) + 1
            )

            self.command_queue.append(queued_command)

            workflow.logger.info(
                f"Command queued - cluster_context: {self.cluster_context}, alert_id: {request.alert_id}, command_type: {request.command_type.value}, queue_size: {len(self.command_queue)}, priority: {request.priority}, currently_processing: {self.current_command.alert_id if self.current_command else None}, correlation_id: {request.correlation_id}"
            )

        except Exception as e:
            workflow.logger.error(
                f"Failed to queue command - cluster_context: {self.cluster_context}, error: {str(e)}, command_data: {command_data}"
            )

    @workflow.query
    def get_cluster_status(self) -> Dict[str, Any]:
        """Query handler for cluster status."""
        return ClusterStatus(
            cluster_context=self.cluster_context,
            is_active=True,
            queue_size=len(self.command_queue),
            currently_executing=self.current_command.alert_id if self.current_command else None,
            total_processed=self.total_processed,
            total_failed=self.total_failed,
            last_execution_at=self.last_execution_at,
            last_error=self.last_error,
            worker_started_at=self.started_at
        ).to_dict()

    @workflow.query
    def get_queue_info(self) -> Dict[str, Any]:
        """Query handler for queue information."""
        return {
            "queue_size": len(self.command_queue),
            "processing": self.processing,
            "current_command": self.current_command.to_dict() if self.current_command else None,
            "queued_commands": [qc.to_dict() for qc in self.command_queue[:10]]  # First 10 for brevity
        }

    @workflow.query
    def get_queue_position(self, alert_id: str) -> Dict[str, Any]:
        """
        Query handler for getting position of an alert in the queue.

        Args:
            alert_id: Alert ID to find in queue

        Returns:
            Position information
        """
        for i, queued_command in enumerate(self.command_queue):
            if queued_command.request.alert_id == alert_id:
                return {
                    "found": True,
                    "position": i + 1,
                    "estimated_wait_minutes": (i + 1) * 15,  # Rough estimate
                    "priority": queued_command.request.priority
                }

        return {
            "found": False,
            "position": -1,
            "estimated_wait_minutes": 0,
            "priority": 0
        }

    @workflow.signal
    async def shutdown(self, reason: str = "manual"):
        """
        Signal handler for graceful shutdown.

        Args:
            reason: Reason for shutdown
        """
        workflow.logger.info(
            f"Shutdown signal received - cluster_context: {self.cluster_context}, reason: {reason}"
        )
        self.is_running = False


# Child Workflows for Individual Kubectl Executions
# These workflows provide better visibility and searchability in Temporal UI


@workflow.defn
class KubectlTestWorkflow:
    """
    Child workflow for kubectl test command execution.

    This workflow provides:
    - Searchable metadata in Temporal UI
    - Individual execution visibility
    - Dedicated retry and timeout policies
    """

    @workflow.run
    async def run(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute kubectl test command.

        Args:
            request_data: Dictionary containing CommandRequest data

        Returns:
            Dictionary containing CommandResponse data
        """
        # Parse request
        request = CommandRequest.from_dict(request_data)

        # Search attributes removed for easier development
        # Can be re-enabled when needed for production

        workflow.logger.info(
            f"Starting kubectl test execution - alert_id: {request.alert_id}, cluster_context: {request.cluster_context}, namespace: {request.namespace}, pod: {request.pod}"
        )

        # Import activity here to avoid import issues
        from .activities import execute_kubectl_command

        # Execute the activity with proper timeouts
        result_dict = await workflow.execute_activity(
            execute_kubectl_command,
            request.to_dict(),
            start_to_close_timeout=timedelta(minutes=25),
            schedule_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=60),
                backoff_coefficient=2.0,
                maximum_attempts=3
            )
        )

        # Parse result and log completion
        response = CommandResponse.from_dict(result_dict)
        workflow.logger.info(
            f"Kubectl test execution completed - alert_id: {request.alert_id}, success: {response.success}, duration: {response.execution_duration_seconds}s"
        )

        return result_dict


@workflow.defn
class HemakoJfrWorkflow:
    """
    Child workflow for Hemako JFR command execution.

    This workflow provides:
    - Searchable metadata in Temporal UI
    - Individual execution visibility
    - Dedicated retry and timeout policies
    """

    @workflow.run
    async def run(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Hemako JFR command.

        Args:
            request_data: Dictionary containing CommandRequest data

        Returns:
            Dictionary containing CommandResponse data
        """
        # Parse request
        request = CommandRequest.from_dict(request_data)

        # Search attributes removed for easier development
        # Can be re-enabled when needed for production

        workflow.logger.info(
            f"Starting Hemako JFR execution - alert_id: {request.alert_id}, cluster_context: {request.cluster_context}, namespace: {request.namespace}, pod: {request.pod}"
        )

        # Import activity here to avoid import issues
        from .activities import execute_kubectl_command

        # Execute the activity with proper timeouts (longer for JFR collection)
        result_dict = await workflow.execute_activity(
            execute_kubectl_command,
            request.to_dict(),
            start_to_close_timeout=timedelta(minutes=30),  # Longer timeout for JFR
            schedule_to_close_timeout=timedelta(minutes=35),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=60),
                backoff_coefficient=2.0,
                maximum_attempts=2  # Fewer retries for resource-intensive operations
            )
        )

        # Parse result and log completion
        response = CommandResponse.from_dict(result_dict)
        workflow.logger.info(
            f"Hemako JFR execution completed - alert_id: {request.alert_id}, success: {response.success}, duration: {response.execution_duration_seconds}s"
        )

        return result_dict


@workflow.defn
class HemakoCrashHeapdumpWorkflow:
    """
    Child workflow for Hemako crash heapdump command execution.

    This workflow provides:
    - Searchable metadata in Temporal UI
    - Individual execution visibility
    - Dedicated retry and timeout policies
    """

    @workflow.run
    async def run(self, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Hemako crash heapdump command.

        Args:
            request_data: Dictionary containing CommandRequest data

        Returns:
            Dictionary containing CommandResponse data
        """
        # Parse request
        request = CommandRequest.from_dict(request_data)

        # Search attributes removed for easier development
        # Can be re-enabled when needed for production

        workflow.logger.info(
            f"Starting Hemako crash heapdump execution for StatefulSet - alert_id: {request.alert_id}, cluster_context: {request.cluster_context}, namespace: {request.namespace}, alert_pod: {request.pod}"
        )

        # Import activity here to avoid import issues
        from .activities import execute_kubectl_command

        # Import crash dump upload workflow
        from crash_dump_uploader.workflows import CrashDumpUploadWorkflow
        
        # Create alert data for crash dump upload workflow
        alert_data = {
            "alert_id": request.alert_id,
            "alert_name": request.alert_name,
            "correlation_id": request.correlation_id,
            "labels": {
                "namespace": request.namespace,
                "pod": request.pod,
                "cluster_context": request.cluster_context,
                **request.alert_labels
            },
            "annotations": request.alert_annotations
        }
        
        # Execute crash dump upload workflow as child workflow
        crash_dump_result = await workflow.execute_child_workflow(
            CrashDumpUploadWorkflow.run,
            alert_data,
            id=f"crash-dump-upload-{request.alert_id}-{workflow.now().timestamp()}",
            task_queue=f"alert-watcher-agent-{request.cluster_context}",
            execution_timeout=timedelta(minutes=45),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=1),
                maximum_interval=timedelta(seconds=60),
                backoff_coefficient=2.0,
                maximum_attempts=2
            )
        )
        
        # Convert crash dump result to command response format
        result_dict = {
            "success": crash_dump_result["success"],
            "message": crash_dump_result["message"],
            "cluster_context": request.cluster_context,
            "alert_id": request.alert_id,
            "correlation_id": request.correlation_id,
            "status": "completed" if crash_dump_result["success"] else "failed",
            "execution_duration_seconds": crash_dump_result["total_duration_seconds"],
            "command_executed": f"Processed {len(crash_dump_result['processed_pods'])} pods, uploaded {crash_dump_result['upload_count']} files",
            "stdout": f"Processed {len(crash_dump_result['processed_pods'])} pods, uploaded {crash_dump_result['upload_count']} files",
            "stderr": None if crash_dump_result["success"] else crash_dump_result["message"],
            "metadata": {
                "processed_pods": crash_dump_result["processed_pods"],
                "uploaded_files": len(crash_dump_result["uploaded_files"]),
                "total_size_bytes": crash_dump_result["total_size_bytes"],
                "processing_results": len(crash_dump_result["processing_results"])
            }
        }

        # Parse result and log completion
        response = CommandResponse.from_dict(result_dict)
        workflow.logger.info(
            f"Hemako crash heapdump execution completed for StatefulSet - alert_id: {request.alert_id}, success: {response.success}, processed_pods: {len(crash_dump_result['processed_pods'])}, duration: {response.execution_duration_seconds}s"
        )

        return result_dict
