"""
FastAPI webhook server for receiving Prometheus AlertManager notifications.

This module implements a simplified HTTP server that receives AlertManager webhooks
and forwards them as signals to Temporal workflows for logging.
"""

import logging
import time
import uuid
from datetime import datetime
from typing import Dict, Any

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
    description="Simplified CrateDB Alert Processing System",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Global Temporal client (will be initialized on startup)
temporal_client: TemporalClient = None


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
    Receive AlertManager webhook and forward alerts as signals to Temporal workflows.

    This endpoint:
    1. Validates the webhook payload
    2. Forwards each alert as a signal to the Temporal workflow
    3. Handles workflow existence and error scenarios
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
    errors = []

    for alert in webhook.alerts:
        try:
            logger.info(
                "Processing individual alert",
                alert_name=alert.labels.alertname,
                correlation_id=correlation_id
            )

            # Create unique alert ID
            alert_id = f"{alert.labels.alertname}-{alert.labels.namespace}-{alert.labels.pod}-{correlation_id}"

            logger.info(
                "Created alert ID",
                alert_id=alert_id,
                correlation_id=correlation_id
            )

            # Create signal payload
            signal_payload = AlertProcessingSignal(
                alert_id=alert_id,
                alert_data=alert,
                processing_id=correlation_id
            )

            logger.info(
                "Created signal payload, about to forward",
                alert_id=signal_payload.alert_id,
                correlation_id=correlation_id
            )
            
            # Forward to Temporal workflow
            logger.info(
                "About to forward alert signal to Temporal",
                alert_id=signal_payload.alert_id,
                correlation_id=correlation_id
            )
            await forward_alert_signal(signal_payload, correlation_id)

            processed_alerts.append({
                "alert_id": alert_id,
                "alert_name": alert.labels.alertname,
                "namespace": alert.labels.namespace,
                "pod": alert.labels.pod,
                "status": "forwarded"
            })

            logger.info(
                "Alert forwarded to Temporal workflow",
                correlation_id=correlation_id,
                alert_id=alert_id,
                alert_name=alert.labels.alertname,
                namespace=alert.labels.namespace,
                pod=alert.labels.pod
            )

        except Exception as e:
            error_msg = f"Failed to start workflow for alert {alert.labels.alertname}: {str(e)}"
            errors.append(error_msg)

            logger.error(
                "Failed to process alert - detailed error",
                correlation_id=correlation_id,
                alert_name=alert.labels.alertname,
                error=str(e),
                error_type=type(e).__name__,
                exc_info=True
            )

    # Return response
    response_data = {
        "correlation_id": correlation_id,
        "processed_alerts": processed_alerts,
        "processed_count": len(processed_alerts),
        "error_count": len(errors),
        "timestamp": datetime.fromtimestamp(time.time()).isoformat() + "Z"
    }

    if errors:
        response_data["errors"] = errors
        logger.warning(
            "Webhook processing completed with errors",
            correlation_id=correlation_id,
            processed_count=len(processed_alerts),
            error_count=len(errors)
        )
        return JSONResponse(
            status_code=207,  # Multi-Status
            content=response_data
        )

    logger.info(
        "Webhook processing completed successfully",
        correlation_id=correlation_id,
        processed_count=len(processed_alerts)
    )

    return response_data


async def forward_alert_signal(signal_payload: AlertProcessingSignal, correlation_id: str):
    """
    Forward an alert signal to the Temporal workflow.
    
    This function sends an alert signal to the running Temporal workflow
    for processing. The workflow should already be running.
    """
    if not temporal_client:
        logger.error("Temporal client not initialized")
        raise RuntimeError("Temporal client not connected")

    workflow_id = config.workflow_id

    logger.info(
        "Sending alert signal to workflow",
        workflow_id=workflow_id,
        correlation_id=correlation_id,
        alert_id=signal_payload.alert_id
    )

    try:
        # Get workflow handle and send signal
        workflow_handle = temporal_client.get_workflow_handle(workflow_id)

        # Send signal to workflow
        await workflow_handle.signal(
            "alert_received",
            signal_payload.dict()
        )

        logger.info(
            "Signal sent to workflow successfully",
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            alert_id=signal_payload.alert_id,
            signal_name="alert_received"
        )

    except Exception as e:
        logger.error(
            "Failed to send signal to workflow",
            correlation_id=correlation_id,
            workflow_id=workflow_id,
            error=str(e),
            error_type=type(e).__name__,
            exc_info=True
        )
        raise RuntimeError(f"Failed to forward alert signal: {str(e)}")


# This function is no longer needed since the workflow is started at application startup
# async def start_workflow(correlation_id: str):
#     """
#     Start a new Temporal workflow instance.
#     This function is deprecated - workflow should be started at application startup.
#     """
#     pass




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


# Test endpoint for manual alert testing
@app.post("/test/alert")
async def test_alert_endpoint(alert_data: Dict[str, Any]):
    """Test endpoint for manual alert testing."""
    correlation_id = str(uuid.uuid4())

    logger.info(
        "Test alert received",
        correlation_id=correlation_id,
        alert_data=alert_data
    )

    return {
        "status": "received",
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
