"""
Alert Watcher Agent Main Entry Point.

This module provides the main entry point for the Alert Watcher Agent with optimal
Temporal worker setup, graceful shutdown handling, and comprehensive monitoring.
"""

import asyncio
import logging
import signal
import sys
from datetime import timedelta
from typing import Dict, Optional, Any
import time

import structlog
from temporalio.client import Client
from temporalio.service import TLSConfig
from temporalio.worker import Worker
from temporalio.exceptions import WorkflowAlreadyStartedError

from .config import AgentConfig, load_config
from .workflows import AgentCoordinatorWorkflow, ClusterWorkerWorkflow, KubectlTestWorkflow, HemakoJfrWorkflow, HemakoCrashHeapdumpWorkflow
from .activities import execute_kubectl_command


class AlertWatcherAgent:
    """
    Main Alert Watcher Agent class with optimal Temporal worker management.
    
    This class demonstrates:
    - Multi-worker setup for different task queues
    - Graceful shutdown handling
    - Health monitoring and status reporting
    - Proper resource cleanup
    - Configuration management
    - Connection resilience and workflow health monitoring
    """
    
    def __init__(self, config: Optional[AgentConfig] = None):
        self.config = config or load_config()
        self.temporal_client: Optional[Client] = None
        self.coordinator_worker: Optional[Worker] = None
        self.cluster_workers: Dict[str, Worker] = {}
        self.is_running = False
        self.shutdown_event = asyncio.Event()
        
        # Connection resilience
        self.connection_retry_count = 0
        self.max_connection_retries = 10
        self.connection_retry_delay = 5  # seconds
        
        # Workflow health monitoring
        self.workflow_health_check_interval = 30  # seconds
        self.workflow_health_task: Optional[asyncio.Task] = None
        
        # Setup logging
        self._setup_logging()
        self.logger = structlog.get_logger(__name__)
        
        # Setup signal handlers
        self._setup_signal_handlers()
    
    def _setup_logging(self):
        """Setup structured logging with optimal configuration."""
        # Configure standard logging
        logging.basicConfig(
            level=getattr(logging, self.config.log_level),
            format="%(message)s"
        )
        
        # Configure structlog
        processors = [
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            # Note: TimeStamper removed to avoid time.localtime restrictions in workflows
        ]
        
        if self.config.enable_correlation_ids:
            processors.append(
                structlog.processors.CallsiteParameterAdder(
                    parameters=[structlog.processors.CallsiteParameter.FILENAME,
                               structlog.processors.CallsiteParameter.LINENO]
                )
            )
        
        if self.config.log_format == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.dev.ConsoleRenderer())
        
        structlog.configure(
            processors=processors,
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            self.logger.info(
                "Shutdown signal received",
                signal=signal.Signals(signum).name
            )
            self.shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def start(self):
        """Start the Alert Watcher Agent."""
        self.logger.info(
            "Starting Alert Watcher Agent",
            config=self.config.to_dict()
        )
        
        try:
            # Initialize Temporal client
            await self._initialize_temporal_client()
            
            # Test cluster connectivity
            await self._test_cluster_connectivity()
            
            # Start workers
            await self._start_coordinator_worker()
            await self._start_cluster_workers()
            
            # Start coordinator workflow
            await self._start_coordinator_workflow()
            
            self.is_running = True
            
            # Start workflow health monitoring
            self.workflow_health_task = asyncio.create_task(self._monitor_workflow_health())
            
            self.logger.info(
                "Alert Watcher Agent started successfully",
                coordinator_worker=bool(self.coordinator_worker),
                cluster_workers=len(self.cluster_workers),
                supported_clusters=self.config.supported_clusters,
                workflow_health_monitoring=True
            )
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
            # Perform shutdown
            await self.shutdown("signal_received")
            
        except Exception as e:
            self.logger.error(
                "Failed to start Alert Watcher Agent",
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )
            raise
    
    async def _initialize_temporal_client(self):
        """Initialize Temporal client with connection resilience."""
        while self.connection_retry_count < self.max_connection_retries:
            try:
                self.logger.info(
                    "Initializing Temporal client",
                    temporal_address=self.config.get_temporal_address(),
                    namespace=self.config.temporal_namespace,
                    tls_enabled=self.config.temporal_tls_enabled,
                    attempt=self.connection_retry_count + 1,
                    max_attempts=self.max_connection_retries
                )
                
                # Setup TLS if enabled
                tls_config = TLSConfig() if self.config.temporal_tls_enabled else False
                
                # Create client
                self.temporal_client = await Client.connect(
                    target_host=self.config.get_temporal_address(),
                    namespace=self.config.temporal_namespace,
                    tls=tls_config,
                    identity=self.config.temporal_identity
                )
                
                self.logger.info(
                    "Temporal client initialized successfully",
                    identity=self.config.temporal_identity,
                    namespace=self.config.temporal_namespace
                )
                
                # Reset retry count on successful connection
                self.connection_retry_count = 0
                return
                
            except Exception as e:
                self.connection_retry_count += 1
                self.logger.warning(
                    "Failed to initialize Temporal client",
                    error=str(e),
                    temporal_address=self.config.get_temporal_address(),
                    attempt=self.connection_retry_count,
                    max_attempts=self.max_connection_retries
                )
                
                if self.connection_retry_count >= self.max_connection_retries:
                    self.logger.error(
                        "Max connection retries exceeded",
                        max_retries=self.max_connection_retries
                    )
                    raise
                
                # Wait before retry
                await asyncio.sleep(self.connection_retry_delay)
    
    async def _test_cluster_connectivity(self):
        """Test connectivity to all configured clusters."""
        self.logger.info(
            "Testing cluster connectivity",
            clusters=self.config.supported_clusters
        )
        
        # For now, skip detailed connectivity testing to avoid workflow sandbox issues
        # This is a placeholder that logs the configured clusters
        self.logger.info(
            "Connectivity test skipped - assuming clusters are accessible",
            clusters=self.config.supported_clusters,
            note="Detailed connectivity testing will be implemented in activities"
        )
        
        # In a real implementation, connectivity would be tested in activities
        # during actual command execution, not during startup
    
    async def _start_coordinator_worker(self):
        """Start the coordinator worker."""
        if self.temporal_client is None:
            raise RuntimeError("Temporal client not initialized")
            
        self.logger.info(
            "Starting coordinator worker",
            task_queue=self.config.coordinator_task_queue
        )
        
        try:
            self.coordinator_worker = Worker(
                self.temporal_client,
                task_queue=self.config.coordinator_task_queue,
                workflows=[AgentCoordinatorWorkflow],
                activities=[],  # Coordinator doesn't execute activities directly
                max_concurrent_workflow_tasks=self.config.max_concurrent_workflow_tasks,
                max_concurrent_activities=1  # Minimal for coordinator
            )
            
            # Start worker in background
            asyncio.create_task(self.coordinator_worker.run())
            
            self.logger.info(
                "Coordinator worker started",
                task_queue=self.config.coordinator_task_queue
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to start coordinator worker",
                error=str(e),
                task_queue=self.config.coordinator_task_queue
            )
            raise
    
    async def _start_cluster_workers(self):
        """Start workers for each cluster."""
        for cluster_context in self.config.supported_clusters:
            await self._start_cluster_worker(cluster_context)
            await self._start_cluster_activity_worker(cluster_context)
    
    async def _start_cluster_worker(self, cluster_context: str):
        """Start a workflow worker for a cluster."""
        if self.temporal_client is None:
            raise RuntimeError("Temporal client not initialized")
            
        task_queue = self.config.get_cluster_task_queue(cluster_context)
        
        self.logger.info(
            "Starting cluster worker",
            cluster_context=cluster_context,
            task_queue=task_queue
        )
        
        try:
            # Create workflow-only worker
            cluster_worker = Worker(
                self.temporal_client,
                task_queue=task_queue,
                workflows=[ClusterWorkerWorkflow, KubectlTestWorkflow, HemakoJfrWorkflow, HemakoCrashHeapdumpWorkflow],
                activities=[],  # No activities on workflow worker
                max_concurrent_workflow_tasks=self.config.max_concurrent_workflow_tasks,
                max_concurrent_activities=0  # No activities
            )
            
            self.cluster_workers[cluster_context] = cluster_worker
            
            # Start worker in background
            asyncio.create_task(cluster_worker.run())
            
            self.logger.info(
                "Cluster workflow worker started",
                cluster_context=cluster_context,
                task_queue=task_queue
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to start cluster workflow worker",
                cluster_context=cluster_context,
                error=str(e)
            )
            raise

    async def _start_cluster_activity_worker(self, cluster_context: str):
        """Start a dedicated activity worker for a cluster."""
        if self.temporal_client is None:
            raise RuntimeError("Temporal client not initialized")
            
        task_queue = self.config.get_task_queues()[cluster_context]
        
        self.logger.info(
            "Starting cluster activity worker",
            cluster_context=cluster_context,
            task_queue=task_queue
        )
        
        try:
            # Create activity-only worker
            activity_worker = Worker(
                self.temporal_client,
                task_queue=task_queue,
                workflows=[],  # No workflows on activity worker
                activities=[execute_kubectl_command],
                max_concurrent_workflow_tasks=0,  # No workflows
                max_concurrent_activities=self.config.max_concurrent_activities,
                max_concurrent_local_activities=0
            )
            
            # Store activity worker separately
            activity_worker_key = f"{cluster_context}_activities"
            self.cluster_workers[activity_worker_key] = activity_worker
            
            # Start activity worker in background
            asyncio.create_task(activity_worker.run())
            
            self.logger.info(
                "Cluster activity worker started",
                cluster_context=cluster_context,
                task_queue=task_queue,
                max_concurrent_activities=self.config.max_concurrent_activities
            )
            
        except Exception as e:
            self.logger.error(
                "Failed to start cluster activity worker",
                cluster_context=cluster_context,
                error=str(e)
            )
            raise
            # Continue with other clusters even if one fails
    
    async def _start_coordinator_workflow(self):
        """Start the coordinator workflow with retry logic."""
        if self.temporal_client is None:
            raise RuntimeError("Temporal client not initialized")
            
        workflow_id = "alert-watcher-agent-coordinator"
        
        self.logger.info(
            "Starting coordinator workflow",
            workflow_id=workflow_id
        )
        
        try:
            # Start coordinator workflow
            await self.temporal_client.start_workflow(
                AgentCoordinatorWorkflow.run,
                args=[self.config.to_dict()],
                id=workflow_id,
                task_queue=self.config.coordinator_task_queue,
                execution_timeout=timedelta(hours=self.config.workflow_execution_timeout_hours),
                run_timeout=timedelta(hours=self.config.workflow_run_timeout_hours)
            )
            
            self.logger.info(
                "Coordinator workflow started",
                workflow_id=workflow_id
            )
            
        except WorkflowAlreadyStartedError:
            self.logger.info(
                "Coordinator workflow already running",
                workflow_id=workflow_id
            )
        except Exception as e:
            self.logger.error(
                "Failed to start coordinator workflow",
                workflow_id=workflow_id,
                error=str(e)
            )
            raise
    
    async def _monitor_workflow_health(self):
        """Monitor workflow health and restart if needed."""
        while self.is_running:
            try:
                await asyncio.sleep(self.workflow_health_check_interval)
                
                if not self.is_running:
                    break
                
                # Check coordinator workflow health
                await self._check_coordinator_workflow_health()
                
            except Exception as e:
                self.logger.error(
                    "Error in workflow health monitoring",
                    error=str(e)
                )
                await asyncio.sleep(self.workflow_health_check_interval)
    
    async def _check_coordinator_workflow_health(self):
        """Check if coordinator workflow is running and restart if needed."""
        if self.temporal_client is None:
            return
            
        workflow_id = "alert-watcher-agent-coordinator"
        
        try:
            # Get workflow handle
            handle = self.temporal_client.get_workflow_handle(workflow_id)
            
            # Check if workflow is running
            try:
                result = await handle.describe()
                if result.status.name in ["COMPLETED", "FAILED", "CANCELLED", "TERMINATED"]:
                    self.logger.warning(
                        "Coordinator workflow not running, restarting",
                        workflow_id=workflow_id,
                        status=result.status.name
                    )
                    await self._start_coordinator_workflow()
                else:
                    self.logger.debug(
                        "Coordinator workflow health check passed",
                        workflow_id=workflow_id,
                        status=result.status.name
                    )
            except Exception as e:
                # If describe fails, workflow might not exist
                self.logger.warning(
                    "Coordinator workflow not found, restarting",
                    workflow_id=workflow_id,
                    error=str(e)
                )
                await self._start_coordinator_workflow()
                
        except Exception as e:
            self.logger.error(
                "Error checking coordinator workflow health",
                workflow_id=workflow_id,
                error=str(e)
            )
    
    async def shutdown(self, reason: str = "manual"):
        """Gracefully shutdown the agent."""
        if not self.is_running:
            return
        
        self.logger.info(
            "Shutting down Alert Watcher Agent",
            reason=reason
        )
        
        self.is_running = False
        
        try:
            # Stop workflow health monitoring
            if self.workflow_health_task:
                self.workflow_health_task.cancel()
                try:
                    await self.workflow_health_task
                except asyncio.CancelledError:
                    pass
                self.logger.info("Stopped workflow health monitoring")
            
            # Terminate all workflows to ensure clean shutdown
            if self.temporal_client:
                # Terminate coordinator workflow
                try:
                    coordinator_handle = self.temporal_client.get_workflow_handle(
                        "alert-watcher-agent-coordinator"
                    )
                    await coordinator_handle.terminate(reason=f"Agent shutdown: {reason}")
                    self.logger.info("Terminated coordinator workflow")
                except Exception as e:
                    self.logger.warning(
                        "Failed to terminate coordinator workflow",
                        error=str(e)
                    )
                
                # Terminate all cluster worker workflows
                for cluster_context in self.config.supported_clusters:
                    try:
                        worker_workflow_id = f"cluster-worker-{cluster_context}-alert-watcher-agent-coordinator"
                        worker_handle = self.temporal_client.get_workflow_handle(worker_workflow_id)
                        await worker_handle.terminate(reason=f"Agent shutdown: {reason}")
                        self.logger.info(
                            "Terminated cluster worker workflow",
                            cluster_context=cluster_context,
                            workflow_id=worker_workflow_id
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Failed to terminate cluster worker workflow",
                            cluster_context=cluster_context,
                            error=str(e)
                        )
            
            # Give workflows time to terminate
            await asyncio.sleep(3)
            
            # Shutdown workers with proper timeout handling
            shutdown_tasks = []
            
            if self.coordinator_worker:
                shutdown_tasks.append(self.coordinator_worker.shutdown())
            
            for cluster_context, worker in self.cluster_workers.items():
                shutdown_tasks.append(worker.shutdown())
            
            if shutdown_tasks:
                try:
                    # Wait for workers to shutdown with timeout
                    await asyncio.wait_for(
                        asyncio.gather(*shutdown_tasks, return_exceptions=True),
                        timeout=10.0
                    )
                    self.logger.info("All workers shut down successfully")
                except asyncio.TimeoutError:
                    self.logger.warning("Worker shutdown timed out, forcing shutdown")
                except Exception as e:
                    self.logger.error(
                        "Error during worker shutdown",
                        error=str(e)
                    )
            
            # Close Temporal client
            if self.temporal_client:
                self.logger.info("Shutting down Temporal client")
                try:
                    # Temporal client doesn't need explicit cleanup in most cases
                    # Setting to None allows garbage collection
                    self.temporal_client = None
                except Exception as e:
                    self.logger.error(f"Error shutting down Temporal client: {e}")
                    # Continue with shutdown anyway
                    pass
                    self.temporal_client = None
            
            self.logger.info(
                "Alert Watcher Agent shutdown complete",
                reason=reason
            )
            
        except Exception as e:
            self.logger.error(
                "Error during shutdown",
                error=str(e),
                exc_info=True
            )
        finally:
            self.shutdown_event.set()
    
    async def get_status(self) -> Dict[str, Any]:
        """Get current agent status."""
        status = {
            "is_running": self.is_running,
            "coordinator_worker": bool(self.coordinator_worker),
            "cluster_workers": len(self.cluster_workers),
            "supported_clusters": self.config.supported_clusters,
            "temporal_connected": bool(self.temporal_client),
            "config": self.config.to_dict()
        }
        
        # Try to get coordinator status
        if self.temporal_client:
            try:
                coordinator_handle = self.temporal_client.get_workflow_handle(
                    "alert-watcher-agent-coordinator"
                )
                coordinator_status = await coordinator_handle.query("get_agent_status")
                status["coordinator_status"] = coordinator_status
            except Exception as e:
                status["coordinator_status"] = {"error": str(e)}
        
        return status


async def main():
    """Main entry point for the Alert Watcher Agent."""
    agent = AlertWatcherAgent()
    
    try:
        await agent.start()
    except KeyboardInterrupt:
        await agent.shutdown("keyboard_interrupt")
    except Exception as e:
        agent.logger.error(
            "Fatal error in main",
            error=str(e),
            exc_info=True
        )
        await agent.shutdown("fatal_error")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())