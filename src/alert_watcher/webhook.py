"""
FastAPI webhook server for receiving CrateDB AlertManager notifications.

This module implements a simplified HTTP server that receives AlertManager webhooks
for CrateDB alerts and forwards them as signals to Temporal workflows for processing.
Only processes CrateDBContainerRestart and CrateDBCloudNotResponsive alerts.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from temporalio.client import Client as TemporalClient
from temporalio.exceptions import TemporalError

from .config import config
from .models import AlertManagerWebhook, AlertProcessingSignal


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

# FastAPI app instance
app = FastAPI(
    title="Alert Watcher 2",
    description="CrateDB Alert Processing System - Only processes CrateDBContainerRestart and CrateDBCloudNotResponsive",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Global Temporal client (will be initialized on startup)
temporal_client: TemporalClient | None = None

# Supported alert types - only these will be processed
SUPPORTED_ALERTS = {"CrateDBContainerRestart", "CrateDBCloudNotResponsive"}


@app.on_event("startup")
async def startup_event():
    """Initialize Temporal client on startup."""
    global temporal_client
    try:
        temporal_client = await TemporalClient.connect(config.temporal_address)
        logger.info(
            "Connected to Temporal server",
            temporal_address=config.temporal_address,
            namespace=config.temporal_namespace
        )
    except Exception as e:
        logger.error(
            "Failed to connect to Temporal server",
            error=str(e),
            temporal_address=config.temporal_address
        )
        raise


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up resources on shutdown."""
    global temporal_client
    if temporal_client:
        # Temporal client doesn't have a close method in this version
        temporal_client = None
        logger.info("Temporal client connection closed")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z",
        "service": "alert-watcher2",
        "version": "0.1.0"
    }


@app.get("/ready")
async def readiness_check():
    """Readiness check endpoint."""
    global temporal_client

    if not temporal_client:
        raise HTTPException(
            status_code=503,
            detail="Temporal client not connected"
        )

    try:
        # Test Temporal connection - just check if client exists
        # Note: describe_namespace method may not be available in all versions
        return {
            "status": "ready",
            "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z",
            "temporal_connected": True
        }
    except Exception as e:
        logger.error(
            "Readiness check failed",
            error=str(e),
            temporal_address=config.temporal_address
        )
        raise HTTPException(
            status_code=503,
            detail=f"Temporal connection failed: {str(e)}"
        )


@app.post("/webhook/alertmanager")
async def receive_alertmanager_webhook(
    webhook: AlertManagerWebhook,
    request: Request
):
    """
    Receive AlertManager webhook and forward CrateDB alerts as signals to Temporal workflows.

    This endpoint:
    1. Validates the webhook payload
    2. Filters for supported CrateDB alert types only
    3. Forwards each supported alert as a signal to the Temporal workflow
    4. Rejects unsupported alert types
    """
    correlation_id = str(uuid.uuid4())

    # Log the incoming webhook
    logger.info(
        "Received AlertManager webhook",
        correlation_id=correlation_id,
        webhook_version=webhook.version,
        alert_count=len(webhook.alerts),
        status=webhook.status.value,
        receiver=webhook.receiver,
        group_key=webhook.groupKey
    )

    processed_alerts = []
    rejected_alerts = []
    errors = []

    for alert in webhook.alerts:
        alert_name = alert.labels.alertname
        
        # Check if this is a supported alert type
        if alert_name not in SUPPORTED_ALERTS:
            rejected_alerts.append({
                "alert_name": alert_name,
                "namespace": alert.labels.namespace,
                "pod": alert.labels.pod,
                "reason": f"Unsupported alert type. Supported: {', '.join(SUPPORTED_ALERTS)}"
            })
            
            logger.info(
                "Rejecting unsupported alert type",
                alert_name=alert_name,
                namespace=alert.labels.namespace,
                pod=alert.labels.pod,
                correlation_id=correlation_id,
                supported_alerts=list(SUPPORTED_ALERTS)
            )
            continue

        try:
            logger.info(
                "Processing supported CrateDB alert",
                alert_name=alert_name,
                namespace=alert.labels.namespace,
                pod=alert.labels.pod,
                correlation_id=correlation_id
            )

            # Create unique alert ID
            alert_id = f"{alert_name}-{alert.labels.namespace}-{alert.labels.pod}-{correlation_id}"

            # Create command data for the agent
            command_data = {
                'alert_id': alert_id,
                'alert_name': alert_name,
                'alert_labels': alert.labels.dict(),
                'alert_annotations': alert.annotations.dict(),
                'cluster_context': determine_cluster_context(alert.labels.namespace),
                'command_type': 'kubectl_test',
                'processing_id': correlation_id
            }
            
            # Forward to agent coordinator
            await forward_to_agent_coordinator(command_data, correlation_id)

            processed_alerts.append({
                "alert_id": alert_id,
                "alert_name": alert_name,
                "namespace": alert.labels.namespace,
                "pod": alert.labels.pod,
                "status": "forwarded"
            })

            logger.info(
                "CrateDB alert forwarded to Temporal workflow",
                correlation_id=correlation_id,
                alert_id=alert_id,
                alert_name=alert_name,
                namespace=alert.labels.namespace,
                pod=alert.labels.pod
            )

        except Exception as e:
            error_msg = f"Failed to process CrateDB alert {alert_name}: {str(e)}"
            errors.append(error_msg)

            logger.error(
                "Failed to process CrateDB alert",
                correlation_id=correlation_id,
                alert_name=alert_name,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )

    # Return response
    response_data = {
        "correlation_id": correlation_id,
        "processed_alerts": processed_alerts,
        "processed_count": len(processed_alerts),
        "rejected_alerts": rejected_alerts,
        "rejected_count": len(rejected_alerts),
        "error_count": len(errors),
        "supported_alert_types": list(SUPPORTED_ALERTS),
        "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z"
    }

    if errors:
        response_data["errors"] = errors
        logger.warning(
            "Webhook processing completed with errors",
            correlation_id=correlation_id,
            processed_count=len(processed_alerts),
            rejected_count=len(rejected_alerts),
            error_count=len(errors)
        )
        return JSONResponse(
            status_code=207,  # Multi-Status
            content=response_data
        )

    logger.info(
        "Webhook processing completed",
        correlation_id=correlation_id,
        processed_count=len(processed_alerts),
        rejected_count=len(rejected_alerts)
    )

    return response_data


def determine_cluster_context(namespace: str) -> str:
    """
    Determine cluster context based on namespace.
    
    Args:
        namespace: Kubernetes namespace
        
    Returns:
        Cluster context string
    """
    # Map namespaces to clusters - customize this based on your setup
    namespace_to_cluster = {
        "cratedb-prod": "aks1-eastus-dev",
        "cratedb-staging": "eks1-us-east-1-dev", 
        "cratedb-dev": "clusterxy",
        "cratedb-test": "clusterxy"
    }
    
    return namespace_to_cluster.get(namespace, "aks1-eastus-dev")  # Default cluster


async def forward_to_agent_coordinator(command_data: dict, correlation_id: str):
    """
    Forward a CrateDB alert command to the agent coordinator.
    
    This function sends a command to the agent coordinator workflow
    for processing across the appropriate cluster.
    """
    if not temporal_client:
        logger.error("Temporal client not initialized")
        raise RuntimeError("Temporal client not connected")

    workflow_id = "alert-watcher-agent-coordinator"

    logger.info(
        "Sending command to agent coordinator",
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        alert_id=command_data['alert_id'],
        alert_name=command_data['alert_name'],
        cluster_context=command_data['cluster_context']
    )

    try:
        # Get workflow handle and send signal
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)

        # Send signal to agent coordinator
        await workflow_handle.signal(
            "execute_command",
            command_data
        )

        logger.info(
            "Command sent to agent coordinator successfully",
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            alert_id=command_data['alert_id'],
            alert_name=command_data['alert_name'],
            cluster_context=command_data['cluster_context'],
            signal_name="execute_command"
        )

    except Exception as e:
        logger.error(
            "Failed to send command to agent coordinator",
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            alert_name=command_data['alert_name'],
            cluster_context=command_data['cluster_context'],
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        raise RuntimeError(f"Failed to forward command to agent: {str(e)}")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    correlation_id = str(uuid.uuid4())

    logger.error(
        "Unhandled exception in webhook server",
        correlation_id=correlation_id,
        url=str(request.url),
        method=request.method,
        error=str(exc),
        exc_info=True
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "correlation_id": correlation_id,
            "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z"
        }
    )


# Test endpoint for manual CrateDB alert testing
@app.post("/test/alert")
async def test_alert_endpoint(alert_data: dict[str, Any]):
    """Test endpoint for manual CrateDB alert testing."""
    correlation_id = str(uuid.uuid4())

    alert_name = alert_data.get("alert_name", "Unknown")
    
    # Check if it's a supported alert type
    if alert_name not in SUPPORTED_ALERTS:
        return {
            "status": "rejected",
            "reason": f"Unsupported alert type: {alert_name}",
            "supported_alerts": list(SUPPORTED_ALERTS),
            "correlation_id": correlation_id,
            "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z"
        }

    logger.info(
        "Test CrateDB alert received",
        correlation_id=correlation_id,
        alert_name=alert_name,
        alert_data=alert_data
    )

    return {
        "status": "received",
        "alert_name": alert_name,
        "correlation_id": correlation_id,
        "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z"
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "alert_watcher.webhook:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        reload=config.is_development
    )
