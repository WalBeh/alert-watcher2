"""
Simple Worker for Kubernetes Operations with Temporal.

This module provides a clean, simple worker implementation that properly
separates workflow and activity execution to avoid context bleeding issues.
"""

import asyncio
import logging
from typing import Optional

from temporalio import Worker
from temporalio.client import Client

from .workflows import KubernetesWorkflow, SimpleAgentWorkflow
from .k8s_activities import get_nodes, get_pods, execute_kubectl_command


# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SimpleKubernetesWorker:
    """
    Simple worker for Kubernetes operations.
    
    This worker demonstrates the proper way to separate workflow and activity
    execution contexts to avoid the time.localtime restriction issues.
    """
    
    def __init__(self, temporal_client: Client, task_queue: str = "kubernetes-operations"):
        self.temporal_client = temporal_client
        self.task_queue = task_queue
        self.worker: Optional[Worker] = None
        self.is_running = False
        
    async def start(self):
        """Start the worker with both workflows and activities."""
        logger.info(f"Starting Kubernetes worker on task queue: {self.task_queue}")
        
        # Create worker with both workflows and activities
        self.worker = Worker(
            client=self.temporal_client,
            task_queue=self.task_queue,
            workflows=[KubernetesWorkflow, SimpleAgentWorkflow],
            activities=[get_nodes, get_pods, execute_kubectl_command],
            max_concurrent_activities=3,
            max_concurrent_workflow_tasks=10
        )
        
        self.is_running = True
        logger.info("Kubernetes worker started successfully")
        
        # Run the worker
        await self.worker.run()
        
    async def stop(self):
        """Stop the worker."""
        if self.worker and self.is_running:
            logger.info("Stopping Kubernetes worker...")
            self.worker.shutdown()
            self.is_running = False
            logger.info("Kubernetes worker stopped")


class SeparatedWorkers:
    """
    Worker setup with completely separated workflow and activity workers.
    
    This approach ensures that workflows and activities run in completely
    separate contexts to eliminate any possibility of context bleeding.
    """
    
    def __init__(self, temporal_client: Client):
        self.temporal_client = temporal_client
        self.workflow_worker: Optional[Worker] = None
        self.activity_worker: Optional[Worker] = None
        self.is_running = False
        
    async def start(self):
        """Start separated workflow and activity workers."""
        logger.info("Starting separated workflow and activity workers")
        
        # Create workflow-only worker
        self.workflow_worker = Worker(
            client=self.temporal_client,
            task_queue="k8s-workflows",
            workflows=[KubernetesWorkflow, SimpleAgentWorkflow],
            activities=[],  # No activities on workflow worker
            max_concurrent_workflow_tasks=10,
            max_concurrent_activities=0
        )
        
        # Create activity-only worker
        self.activity_worker = Worker(
            client=self.temporal_client,
            task_queue="k8s-activities",
            workflows=[],  # No workflows on activity worker
            activities=[get_nodes, get_pods, execute_kubectl_command],
            max_concurrent_workflow_tasks=0,
            max_concurrent_activities=5
        )
        
        self.is_running = True
        
        # Start both workers concurrently
        await asyncio.gather(
            self.workflow_worker.run(),
            self.activity_worker.run()
        )
        
    async def stop(self):
        """Stop both workers."""
        if self.is_running:
            logger.info("Stopping separated workers...")
            
            if self.workflow_worker:
                self.workflow_worker.shutdown()
                
            if self.activity_worker:
                self.activity_worker.shutdown()
                
            self.is_running = False
            logger.info("Separated workers stopped")


async def create_simple_worker(temporal_host: str = "localhost:7233", 
                             temporal_namespace: str = "default",
                             task_queue: str = "kubernetes-operations") -> SimpleKubernetesWorker:
    """
    Create and return a simple Kubernetes worker.
    
    Args:
        temporal_host: Temporal server address
        temporal_namespace: Temporal namespace
        task_queue: Task queue name
        
    Returns:
        Configured worker instance
    """
    # Create Temporal client
    client = await Client.connect(temporal_host, namespace=temporal_namespace)
    
    # Create worker
    worker = SimpleKubernetesWorker(client, task_queue)
    
    return worker


async def create_separated_workers(temporal_host: str = "localhost:7233",
                                 temporal_namespace: str = "default") -> SeparatedWorkers:
    """
    Create and return separated workflow and activity workers.
    
    Args:
        temporal_host: Temporal server address
        temporal_namespace: Temporal namespace
        
    Returns:
        Configured separated workers instance
    """
    # Create Temporal client
    client = await Client.connect(temporal_host, namespace=temporal_namespace)
    
    # Create separated workers
    workers = SeparatedWorkers(client)
    
    return workers


if __name__ == "__main__":
    async def main():
        """Main function to run the worker."""
        print("=== Simple Kubernetes Worker ===")
        print("Starting worker...")
        
        try:
            # Create and start simple worker
            worker = await create_simple_worker()
            await worker.start()
            
        except KeyboardInterrupt:
            print("\nShutting down worker...")
            if worker:
                await worker.stop()
            print("Worker stopped")
            
        except Exception as e:
            print(f"Error: {e}")
            if worker:
                await worker.stop()
    
    # Run the main function
    asyncio.run(main())