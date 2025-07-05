# Alert Watcher 2 - Simplified

A dramatically simplified alert processing system that receives AlertManager webhooks and logs the alert data structure.

## Overview

This system implements a minimal pipeline:
**Alertmanager → Webhook → Signal → Workflow → Activity (log JSON)**

The goal is to understand how AlertManager labels look for CrateDB alerts by logging the complete JSON data structure.

## What was removed

- Complex S3 upload logic
- Complex JFR collection with `hemako` commands
- Alert type validation and filtering
- Complex retry logic and error handling
- Performance monitoring and metrics
- Test infrastructure

## What remains

- FastAPI webhook server to receive AlertManager webhooks
- Temporal workflow to process alerts
- Simple activity that logs the complete alert JSON structure
- Basic health/readiness endpoints

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   AlertManager  │───▶│   Webhook       │───▶│   Temporal      │
│                 │    │   (FastAPI)     │    │   Workflow      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │   log_alert     │
                                              │   Activity      │
                                              └─────────────────┘
```

## Quick Start

1. **Install dependencies:**
   ```bash
   uv sync
   ```

2. **Start Temporal server** (if not already running):
   ```bash
   # Using Docker
   docker run -p 7233:7233 -p 8233:8233 temporalio/auto-setup:latest
   ```

3. **Run the application:**
   ```bash
   uv run python -m src.alert_watcher.main
   ```

4. **Test with sample data:**
   ```bash
   uv run python test_simplified.py
   ```

## Configuration

Environment variables:
- `HOST`: Server host (default: 0.0.0.0)
- `PORT`: Server port (default: 8000)
- `LOG_LEVEL`: Logging level (default: INFO)
- `TEMPORAL_HOST`: Temporal server host (default: localhost)
- `TEMPORAL_PORT`: Temporal server port (default: 7233)

## Endpoints

- `GET /health` - Health check
- `GET /ready` - Readiness check (includes Temporal connection)
- `POST /webhook/alertmanager` - AlertManager webhook endpoint
- `POST /test/alert` - Test endpoint for manual testing

## Sample AlertManager Webhook

The system expects standard AlertManager webhook payloads like:

```json
{
  "version": "4",
  "groupKey": "{}:{alertname=\"CrateDBCloudNotResponsive\"}",
  "status": "firing",
  "receiver": "webhook",
  "alerts": [
    {
      "status": "firing",
      "labels": {
        "alertname": "CrateDBCloudNotResponsive",
        "namespace": "cratedb-cloud",
        "pod": "crate-data-0",
        "kube_context": "prod-cluster-1",
        "sts": "crate-data",
        "severity": "critical"
      },
      "annotations": {
        "summary": "CrateDB Cloud instance is not responsive",
        "description": "Instance is not responding to health checks"
      },
      "startsAt": "2024-01-01T12:00:00Z"
    }
  ]
}
```

## What gets logged

When an alert is received, the system logs the complete alert structure including:
- Alert metadata (status, timestamps, fingerprint)
- All labels (alertname, namespace, pod, kube_context, etc.)
- All annotations (summary, description, runbook_url, etc.)
- Processing metadata (alert_id, processing_id, timestamps)

Example log output:
```json
{
  "timestamp": "2024-01-01T12:00:00Z",
  "event": "alert_received",
  "alert_id": "CrateDBCloudNotResponsive-cratedb-cloud-crate-data-0-uuid",
  "processing_id": "correlation-uuid",
  "alert_data": {
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
      "description": "Instance is not responding to health checks",
      "runbook_url": "https://docs.cratedb.com/troubleshooting/not-responsive"
    },
    "startsAt": "2024-01-01T12:00:00Z",
    "endsAt": null,
    "generatorURL": "http://prometheus:9090/...",
    "fingerprint": "abc123def456"
  }
}
```

## Development

The system is intentionally simple for easy understanding and modification:

- `webhook.py` - FastAPI server and webhook handling
- `workflows.py` - Temporal workflow (just calls log activity)
- `activities.py` - Single activity that logs alert data
- `models.py` - Pydantic models for AlertManager webhooks
- `config.py` - Configuration management
- `main.py` - Application entry point

## Next Steps

Once you understand the alert label structure from the logs, you can:
1. Add back specific alert type filtering
2. Implement `hemako jfr collect` commands based on the labels
3. Add proper error handling and retry logic
4. Implement S3 upload for JFR files
5. Add monitoring and metrics

The current system provides a clean foundation for understanding AlertManager webhook structure and building upon it incrementally.

## Development with uv

This project uses [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
# Install dependencies
uv sync

# Run the application
uv run python -m src.alert_watcher.main

# Run tests
uv run python test_simplified.py
uv run python run_example.py
```