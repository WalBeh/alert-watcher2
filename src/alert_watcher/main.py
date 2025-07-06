"""
Main application entry point for Alert Watcher 2.

This module provides the main entry point for the simplified alert watcher application.
"""

import asyncio
import logging
import signal
import sys
from typing import Optional

import structlog
import uvicorn
from temporalio.client import Client as TemporalClient
from temporalio.worker import Worker

from .config import config
from .webhook import app
from .workflows import AlertProcessingWorkflow
from .activities import execute_hemako_command


# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class AlertWatcherApp:
    """Main application class for Alert Watcher 2."""

    def __init__(self):
        self.temporal_client: TemporalClient | None = None
        self.worker: Worker | None = None
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.server: uvicorn.Server | None = None

    async def initialize(self):
        """Initialize the application components."""
        try:
            # Configure logging level
            logging.basicConfig(
                level=getattr(logging, config.log_level.upper()),
                format='%(message)s'
            )

            logger.info(
                "Initializing Alert Watcher 2",
                version="0.1.0",
                temporal_address=config.temporal_address,
                webhook_host=config.host,
                webhook_port=config.port
            )

            # Connect to Temporal
            self.temporal_client = await TemporalClient.connect(config.temporal_address)
            logger.info("Connected to Temporal server")

            # Create and start Temporal worker
            await self.start_temporal_worker()
            logger.info("Temporal worker started")

            # Setup signal handlers
            self.setup_signal_handlers()

            # Start the main workflow
            await self.start_main_workflow()

            logger.info("Application initialization completed")

        except Exception as e:
            logger.error(
                "Failed to initialize application",
                error=str(e),
                exc_info=True
            )
            raise

    async def start_temporal_worker(self):
        """Start the Temporal worker for processing workflows and activities."""
        try:
            # Create worker with hemako activity and both workflows
            from .workflows import CrateDBAlertSubWorkflow
            
            if self.temporal_client is None:
                raise RuntimeError("Temporal client not initialized")
            
            self.worker = Worker(
                self.temporal_client,
                task_queue=config.temporal_task_queue,
                workflows=[AlertProcessingWorkflow, CrateDBAlertSubWorkflow],
                activities=[execute_hemako_command]
            )

            # Start worker in background
            asyncio.create_task(self.worker.run())
            
            logger.info(
                "Temporal worker started",
                task_queue=config.temporal_task_queue,
                activities=["execute_hemako_command"],
                workflows=["AlertProcessingWorkflow", "CrateDBAlertSubWorkflow"]
            )

        except Exception as e:
            logger.error(
                "Failed to start Temporal worker",
                error=str(e),
                exc_info=True
            )
            raise

    async def start_main_workflow(self):
        """Start the main alert processing workflow."""
        try:
            from .workflows import AlertProcessingWorkflow
            
            workflow_id = config.workflow_id
            
            if self.temporal_client is None:
                raise RuntimeError("Temporal client not initialized")
            
            # Check if workflow already exists
            try:
                workflow_handle = self.temporal_client.get_workflow_handle(workflow_id)
                workflow_info = await workflow_handle.describe()
                
                if workflow_info.status.name in ["COMPLETED", "FAILED", "CANCELED", "TERMINATED"]:
                    logger.info(
                        "Existing workflow is in terminal state, starting new one",
                        workflow_id=workflow_id,
                        status=workflow_info.status.name
                    )
                    raise Exception("Need to start new workflow")
                else:
                    logger.info(
                        "Main workflow already running",
                        workflow_id=workflow_id,
                        status=workflow_info.status.name
                    )
                    return
                    
            except Exception:
                # Workflow doesn't exist or is terminated, start a new one
                logger.info("Starting main alert processing workflow", workflow_id=workflow_id)
                
                workflow_handle = await self.temporal_client.start_workflow(
                    AlertProcessingWorkflow.run,
                    id=workflow_id,
                    task_queue=config.temporal_task_queue
                )
                
                logger.info(
                    "Main workflow started successfully",
                    workflow_id=workflow_id,
                    run_id=workflow_handle.result_run_id
                )
                
        except Exception as e:
            logger.error(
                "Failed to start main workflow",
                error=str(e),
                exc_info=True
            )
            raise

    def setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(
                "Received shutdown signal",
                signal=signum
            )
            self.shutdown_event.set()
            if self.server:
                self.server.should_exit = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    async def run_webhook_server(self):
        """Run the webhook server."""
        try:
            # Update the global temporal client in the webhook module
            from . import webhook as webhook_module
            webhook_module.temporal_client = self.temporal_client

            # Create uvicorn server
            server_config = uvicorn.Config(
                app,
                host=config.host,
                port=config.port,
                log_level=config.log_level.lower(),
                access_log=True
            )

            self.server = uvicorn.Server(server_config)

            logger.info(
                "Starting webhook server",
                host=config.host,
                port=config.port
            )

            # Run server until shutdown
            await self.server.serve()

        except Exception as e:
            logger.error(
                "Webhook server error",
                error=str(e),
                exc_info=True
            )
            raise

    async def run(self):
        """Run the complete application."""
        try:
            await self.initialize()
            self.running = True

            logger.info("Alert Watcher 2 is running")

            # Run webhook server (this will block until shutdown)
            await self.run_webhook_server()

        except Exception as e:
            logger.error(
                "Application error",
                error=str(e),
                exc_info=True
            )
            raise
        finally:
            await self.cleanup()

    async def shutdown(self):
        """Graceful shutdown of the application."""
        logger.info("Starting graceful shutdown")

        self.running = False
        self.shutdown_event.set()

        # Stop webhook server
        if self.server:
            logger.info("Stopping webhook server")
            self.server.should_exit = True

        # Stop Temporal worker with timeout
        if self.worker:
            logger.info("Stopping Temporal worker")
            try:
                await asyncio.wait_for(self.worker.shutdown(), timeout=5.0)
            except TimeoutError:
                logger.warning("Temporal worker shutdown timed out")

        # Close Temporal client
        if self.temporal_client:
            logger.info("Closing Temporal client")
            # Temporal client doesn't have a close method in this version
            self.temporal_client = None

        logger.info("Graceful shutdown completed")

    async def cleanup(self):
        """Clean up resources."""
        if self.temporal_client:
            # Temporal client doesn't have a close method in this version
            self.temporal_client = None
        
        logger.info("Cleanup completed")


async def main():
    """Main application entry point."""
    app_instance = AlertWatcherApp()

    try:
        # Run the application
        server_task = asyncio.create_task(app_instance.run())
        
        # Wait for either the server to complete or shutdown signal
        done, pending = await asyncio.wait(
            [server_task, asyncio.create_task(app_instance.shutdown_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # If shutdown was triggered, perform cleanup
        if app_instance.shutdown_event.is_set():
            logger.info("Shutdown signal received, stopping application")
            await app_instance.shutdown()
            
        # Cancel any pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
                
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        await app_instance.shutdown()
    except Exception as e:
        logger.error(
            "Application failed",
            error=str(e),
            exc_info=True
        )
        await app_instance.shutdown()
        sys.exit(1)


def cli():
    """Command-line interface entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Alert Watcher 2 - Simplified CrateDB Alert Processing System"
    )
    parser.add_argument(
        "--host",
        default=config.host,
        help="Server host (default: %(default)s)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=config.port,
        help="Server port (default: %(default)s)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=config.log_level,
        help="Log level (default: %(default)s)"
    )
    parser.add_argument(
        "--temporal-host",
        default=config.temporal_host,
        help="Temporal server host (default: %(default)s)"
    )
    parser.add_argument(
        "--temporal-port",
        type=int,
        default=config.temporal_port,
        help="Temporal server port (default: %(default)s)"
    )

    args = parser.parse_args()

    # Update config with command-line arguments
    config.host = args.host
    config.port = args.port
    config.log_level = args.log_level
    config.temporal_host = args.temporal_host
    config.temporal_port = args.temporal_port

    # Run the application
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
    except Exception as e:
        print(f"Application failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()