# Alert Watcher 2 - Simplification Summary

## Overview

This document summarizes the dramatic simplification of the Alert Watcher 2 system, reducing it from a complex multi-step pipeline to a simple logging system that captures AlertManager webhook data structures.

## What Was Removed

### 1. Complex S3 Upload Logic (~550 lines)
- **Removed**: `S3UploadActivity` class with comprehensive upload strategies
- **Removed**: Multi-part uploads, retry logic, caching
- **Removed**: S3 configuration (bucket, region, credentials)
- **Removed**: Upload quality scoring and performance metrics
- **Removed**: Cost estimation and retention policies

### 2. Complex JFR Collection Logic (~550 lines)
- **Removed**: `JFRCollectionActivity` class with enhanced collection
- **Removed**: `hemako jfr collect` command generation
- **Removed**: Collection strategies (deep_profiling, startup_analysis, standard)
- **Removed**: JFR validation, duplicate detection, and caching
- **Removed**: Collection quality scoring and analysis recommendations

### 3. Complex Validation and Error Handling
- **Removed**: Alert type validation and filtering
- **Removed**: Required field validation (namespace, pod, kube_context)
- **Removed**: Supported alert type enumeration
- **Removed**: Complex retry policies and error recovery
- **Removed**: Activity monitoring and performance tracking

### 4. Workflow Orchestration Complexity
- **Removed**: Multi-step workflow (log → JFR → S3)
- **Removed**: Workflow manager and lifecycle management
- **Removed**: Complex continue-as-new logic
- **Removed**: Activity result chaining and error propagation

### 5. Test Infrastructure
- **Removed**: Entire `tests/` directory (26 activity tests, 18 workflow tests, webhook tests)
- **Removed**: Complex mocking and test fixtures
- **Removed**: Integration test setup

### 6. Monitoring and Metrics
- **Removed**: `ActivityMonitor` class with performance tracking
- **Removed**: Health status reporting and statistics
- **Removed**: Performance recommendations and trend analysis
- **Removed**: Activity execution recording and reporting

## What Remains

### 1. Core Pipeline Components
- **FastAPI webhook server** (`webhook.py`) - Simplified to remove validation
- **Temporal workflow** (`workflows.py`) - Simplified to single activity call
- **Log activity** (`activities.py`) - Single function that logs JSON structure
- **Models** (`models.py`) - Basic AlertManager webhook models
- **Configuration** (`config.py`) - Minimal configuration management

### 2. Essential Endpoints
- `GET /health` - Basic health check
- `GET /ready` - Temporal connection check
- `POST /webhook/alertmanager` - Main webhook endpoint
- `POST /test/alert` - Simple test endpoint

### 3. Basic Functionality
- Receive AlertManager webhooks
- Parse webhook payloads
- Send signals to Temporal workflow
- Log complete alert data structure as JSON

## File Changes Summary

| File | Before | After | Change |
|------|--------|-------|---------|
| `activities.py` | 1,682 lines | 95 lines | -94% |
| `models.py` | 107 lines | 64 lines | -40% |
| `workflows.py` | 295 lines | 210 lines | -29% |
| `webhook.py` | 404 lines | 372 lines | -8% |
| `config.py` | 65 lines | 45 lines | -31% |
| `main.py` | 346 lines | 273 lines | -21% |
| `tests/` | 3 files | 0 files | -100% |
| `workflow_manager.py` | 1 file | 0 files | -100% |

## Architecture Comparison

### Before (Complex)
```
AlertManager → Webhook → Signal → Workflow → [Log Activity → JFR Activity → S3 Activity]
                                            ↓
                                  [Validation, Retry, Monitoring, Caching]
```

### After (Simple)
```
AlertManager → Webhook → Signal → Workflow → Log Activity
                                            ↓
                                    [JSON Structure Output]
```

## Key Benefits of Simplification

### 1. **Understandability**
- Clear, linear flow from webhook to log output
- Minimal code paths and decision points
- Easy to trace and debug

### 2. **Maintainability**
- ~1,400 fewer lines of code
- No complex state management
- Reduced dependency surface area

### 3. **Focus on Core Goal**
- Primary objective: Understand AlertManager label structure
- No distracting complexity or premature optimization
- Clear path to incremental enhancement

### 4. **Faster Development**
- Quick to modify and test
- No complex mocking or test infrastructure
- Direct feedback through log output

## What the System Does Now

1. **Receives** AlertManager webhooks via HTTP POST
2. **Parses** the webhook payload into structured data
3. **Forwards** alerts as signals to Temporal workflow
4. **Logs** the complete alert data structure including:
   - Alert metadata (status, timestamps, fingerprint)
   - All labels (alertname, namespace, pod, kube_context, severity, etc.)
   - All annotations (summary, description, runbook_url, etc.)
   - Processing metadata (alert_id, processing_id, timestamps)

## Sample Output

When an alert is received, the system outputs:

```json
{
  "timestamp": "2025-01-01T12:00:00Z",
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
    "startsAt": "2025-01-01T12:00:00Z",
    "endsAt": null,
    "generatorURL": "http://prometheus:9090/...",
    "fingerprint": "abc123def456"
  }
}
```

## Next Steps for Enhancement

Once the AlertManager label structure is understood, you can incrementally add back:

1. **Alert Type Filtering**: Add back specific alert type validation
2. **JFR Collection**: Implement `hemako jfr collect` based on understood labels
3. **Error Handling**: Add proper retry logic and error recovery
4. **S3 Upload**: Add file upload capabilities for JFR data
5. **Monitoring**: Add back performance metrics and health monitoring
6. **Testing**: Implement focused test suite for core functionality

## Success Metrics

The simplification achieves:
- ✅ **Primary Goal**: Clear visibility into AlertManager webhook structure
- ✅ **Reduced Complexity**: 94% reduction in core activity code
- ✅ **Maintainability**: Single responsibility per component
- ✅ **Debuggability**: Clear log output for understanding data flow
- ✅ **Extensibility**: Clean foundation for incremental feature addition

This simplified system provides the essential foundation for understanding AlertManager webhooks while maintaining the flexibility to add back complexity as needed.

## Usage with uv

This project uses [uv](https://docs.astral.sh/uv/) for dependency management:

```bash
# 1. Install dependencies
uv sync

# 2. Start Temporal server
temporal server start-dev

# 3. Run the simplified system
uv run python -m src.alert_watcher.main

# 4. Send test alerts
uv run python test_simplified.py
# or
uv run python run_example.py
```