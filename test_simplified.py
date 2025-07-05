#!/usr/bin/env python3
"""
Simple test script to validate the simplified alert processing system.

This script creates a sample AlertManager webhook payload and sends it to
the webhook endpoint to verify the system works correctly.

Usage:
    uv run python test_simplified.py
"""

import asyncio
import json
import sys
import time
from datetime import datetime, UTC
from typing import Dict, Any

import httpx
import structlog

# Configure simple logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


def create_sample_alertmanager_webhook() -> Dict[str, Any]:
    """Create a sample AlertManager webhook payload."""
    return {
        "version": "4",
        "groupKey": "{}:{alertname=\"CrateDBCloudNotResponsive\"}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "webhook",
        "groupLabels": {
            "alertname": "CrateDBCloudNotResponsive"
        },
        "commonLabels": {
            "alertname": "CrateDBCloudNotResponsive",
            "namespace": "cratedb-cloud",
            "severity": "critical"
        },
        "commonAnnotations": {
            "summary": "CrateDB Cloud instance is not responsive",
            "description": "The CrateDB instance in namespace cratedb-cloud is not responding to health checks"
        },
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "CrateDBCloudNotResponsive",
                    "namespace": "cratedb-cloud",
                    "pod": "crate-data-0",
                    "kube_context": "prod-cluster-1",
                    "sts": "crate-data",
                    "severity": "critical",
                    "instance": "crate-data-0.crate-data.cratedb-cloud.svc.cluster.local:4200",
                    "job": "cratedb-monitoring"
                },
                "annotations": {
                    "summary": "CrateDB Cloud instance is not responsive",
                    "description": "The CrateDB instance crate-data-0 in namespace cratedb-cloud is not responding to health checks for more than 5 minutes",
                    "runbook_url": "https://docs.cratedb.com/troubleshooting/not-responsive"
                },
                "startsAt": datetime.fromtimestamp(time.time()).isoformat() + "Z",
                "endsAt": None,
                "generatorURL": "http://prometheus:9090/graph?g0.expr=up%7Bjob%3D%22cratedb-monitoring%22%7D+%3D%3D+0&g0.tab=1",
                "fingerprint": "abc123def456"
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "CrateDBContainerRestart",
                    "namespace": "cratedb-cloud",
                    "pod": "crate-data-1",
                    "kube_context": "prod-cluster-1",
                    "sts": "crate-data",
                    "severity": "warning",
                    "instance": "crate-data-1.crate-data.cratedb-cloud.svc.cluster.local:4200",
                    "job": "cratedb-monitoring"
                },
                "annotations": {
                    "summary": "CrateDB container restarted",
                    "description": "The CrateDB container crate-data-1 in namespace cratedb-cloud has restarted unexpectedly",
                    "runbook_url": "https://docs.cratedb.com/troubleshooting/container-restart"
                },
                "startsAt": datetime.fromtimestamp(time.time()).isoformat() + "Z",
                "endsAt": None,
                "generatorURL": "http://prometheus:9090/graph?g0.expr=changes%28kube_pod_container_status_restarts_total%5B5m%5D%29+%3E+0&g0.tab=1",
                "fingerprint": "def456ghi789"
            }
        ]
    }


async def test_webhook_endpoint(webhook_url: str = "http://localhost:8000") -> bool:
    """Test the webhook endpoint with sample data."""
    try:
        # Create sample payload
        payload = create_sample_alertmanager_webhook()

        logger.info("Testing webhook endpoint", webhook_url=webhook_url)

        # Send webhook
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{webhook_url}/webhook/alertmanager",
                json=payload,
                timeout=30.0
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(
                    "Webhook test successful",
                    status_code=response.status_code,
                    processed_alerts=result.get("processed_count", 0),
                    correlation_id=result.get("correlation_id")
                )
                return True
            else:
                logger.error(
                    "Webhook test failed",
                    status_code=response.status_code,
                    response_text=response.text
                )
                return False

    except Exception as e:
        logger.error(
            "Error testing webhook",
            error=str(e),
            exc_info=True
        )
        return False


async def test_health_endpoints(base_url: str = "http://localhost:8000") -> bool:
    """Test the health endpoints."""
    try:
        async with httpx.AsyncClient() as client:
            # Test health endpoint
            health_response = await client.get(f"{base_url}/health", timeout=10.0)
            if health_response.status_code != 200:
                logger.error("Health endpoint failed", status_code=health_response.status_code)
                return False

            # Test readiness endpoint (might fail if Temporal is not running)
            ready_response = await client.get(f"{base_url}/ready", timeout=10.0)
            if ready_response.status_code not in [200, 503]:
                logger.error("Readiness endpoint failed", status_code=ready_response.status_code)
                return False

            logger.info(
                "Health endpoints test successful",
                health_status=health_response.status_code,
                ready_status=ready_response.status_code
            )
            return True

    except Exception as e:
        logger.error(
            "Error testing health endpoints",
            error=str(e),
            exc_info=True
        )
        return False


async def main():
    """Main test function."""
    logger.info("Starting simplified alert processing system test")

    # Test health endpoints first
    logger.info("Testing health endpoints...")
    health_ok = await test_health_endpoints()

    if not health_ok:
        logger.error("Health endpoints test failed")
        sys.exit(1)

    # Test webhook endpoint
    logger.info("Testing webhook endpoint...")
    webhook_ok = await test_webhook_endpoint()

    if not webhook_ok:
        logger.error("Webhook endpoint test failed")
        sys.exit(1)

    logger.info("All tests passed! 🎉")

    # Print sample alert data for reference
    sample_payload = create_sample_alertmanager_webhook()
    print("\n" + "="*80)
    print("SAMPLE ALERTMANAGER WEBHOOK PAYLOAD:")
    print("="*80)
    print(json.dumps(sample_payload, indent=2, default=str))
    print("="*80)

    print("\nThe simplified system should log alert data structures similar to the above payload.")
    print("Check the application logs to see the detailed alert information.")


if __name__ == "__main__":
    asyncio.run(main())
