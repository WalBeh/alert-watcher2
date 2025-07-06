# Alert Watcher 2 - Simplification Summary

## 🎯 Overview

This document summarizes the major simplification of the Alert Watcher 2 system to focus exclusively on processing two specific CrateDB alert types with a clean sub-workflow architecture.

## 📋 Key Requirements Implemented

### 1. Alert Type Filtering
- **ONLY** processes two specific events:
  - `CrateDBContainerRestart`
  - `CrateDBCloudNotResponsive`
- All other alert types are rejected with clear messaging
- Webhook endpoint validates alert types before processing

### 2. Hemako Command Placeholder
- Created `execute_hemako_command` activity as placeholder
- Different CLI parameters based on alert type:
  - `CrateDBContainerRestart` → `--jfr` parameter
  - `CrateDBCloudNotResponsive` → `--crash-heapdump-upload` parameter
- Command format: `hemako jfr {param} --namespace {namespace} --pod {pod}`

### 3. Sub-Workflow Architecture
- Each incoming alert spawns a dedicated sub-workflow
- Sub-workflow naming pattern: `{AlertName}-{Namespace}-{UUID}`
- Examples:
  - `CrateDBContainerRestart-cratedb-prod-abc123`
  - `CrateDBCloudNotResponsive-cratedb-staging-def456`

### 4. Code Simplification
- Removed all unnecessary activities and complex logic
- Streamlined workflow processing
- Eliminated unused test files and deprecated functionality

## 🗑️ What Was Removed

### Activities
- `log_alert` (generic logging)
- `log_cratedb_alert` (specific alert logging)
- `log_prometheus_alert` (Prometheus alerts)
- `log_node_alert` (Node alerts)
- `log_pod_alert` (Pod alerts)
- `log_service_alert` (Service alerts)
- All dynamic activity factories

### Workflows
- Complex alert processing logic
- Multiple activity execution paths
- Generic alert handling fallbacks
- Activity name resolution logic

### Test Files
- `test_webhook_alerts.py`
- `test_activity_fallback.py`
- `test_cratedb_container_restart.py`
- `test_naming_changes.py`
- `test_shutdown.py`
- `test_shutdown_simple.py`
- `test_simplified.py`
- `test_temporal_events.py`
- `test_temporal_minimal.py`

### Features
- Complex S3 upload logic
- JFR collection with multiple commands
- Performance monitoring and metrics
- Multi-alert type validation
- Complex retry and error handling

## 🏗️ New Architecture

### Main Components

1. **AlertProcessingWorkflow** (Main)
   - Continuously runs and receives alert signals
   - Filters for supported alert types only
   - Spawns sub-workflows for each valid alert

2. **CrateDBAlertSubWorkflow** (Sub-Workflow)
   - Processes individual alerts
   - Named with alert type and namespace
   - Executes hemako command activity

3. **execute_hemako_command** (Activity)
   - Placeholder for hemako command execution
   - Determines parameters based on alert type
   - Simulates command execution (2-second delay)

### Data Flow

```
AlertManager → Webhook → Filter → Main Workflow → Sub-Workflow → Hemako Activity
```

### Alert Processing Logic

```python
# Webhook filtering
if alert_name not in SUPPORTED_ALERTS:
    reject_alert()
    return

# Main workflow
sub_workflow_id = f"{alert_name}-{namespace}-{uuid}"
start_child_workflow(CrateDBAlertSubWorkflow, sub_workflow_id)

# Sub-workflow
if alert_name == "CrateDBContainerRestart":
    param = "--jfr"
elif alert_name == "CrateDBCloudNotResponsive":
    param = "--crash-heapdump-upload"

execute_activity("execute_hemako_command", {
    "alert_name": alert_name,
    "namespace": namespace,
    "pod": pod,
    "command_param": param
})
```

## 📊 File Changes Summary

### Modified Files
- `src/alert_watcher/activities.py` - Simplified to single hemako activity
- `src/alert_watcher/workflows.py` - Added sub-workflow architecture
- `src/alert_watcher/main.py` - Updated worker registration
- `src/alert_watcher/webhook.py` - Added alert type filtering
- `README.md` - Completely rewritten for simplified system

### New Files
- `test_simplified_cratedb.py` - Comprehensive test suite
- `SIMPLIFICATION_SUMMARY.md` - This document

### Deleted Files
- 9 old test files (listed above)
- Various documentation files for removed features

## 🧪 Testing Strategy

### Test Coverage
- Health and readiness endpoints
- Supported alert processing
- Unsupported alert rejection
- Batch alert processing
- Sub-workflow spawning

### Test Script Features
- Realistic AlertManager webhook payloads
- Correlation ID tracking
- Success/failure reporting
- Clear test output with emojis

## 🔧 Configuration

### Environment Variables
```bash
# Only essential configuration remains
ALERT_WATCHER_HOST=0.0.0.0
ALERT_WATCHER_PORT=8000
ALERT_WATCHER_LOG_LEVEL=INFO
TEMPORAL_HOST=localhost
TEMPORAL_PORT=7233
WORKFLOW_ID=alert-watcher2-main
```

### Supported Alerts
```python
SUPPORTED_ALERTS = {
    "CrateDBContainerRestart",
    "CrateDBCloudNotResponsive"
}
```

## 🚀 Benefits of Simplification

### 1. Clarity
- Clear separation of concerns
- One alert type = one sub-workflow
- Easy to understand and debug

### 2. Maintainability
- Minimal code surface area
- Single responsibility per component
- Easy to extend for new alert types

### 3. Reliability
- Isolated alert processing
- Independent sub-workflow execution
- Clear error boundaries

### 4. Observability
- Named sub-workflows for easy identification
- Correlation IDs throughout the pipeline
- Structured logging with context

## 🔮 Future Development

### Immediate Next Steps
1. Implement actual hemako command execution
2. Add error handling and retry logic
3. Test with real AlertManager integration

### Planned Enhancements
1. Add more CrateDB alert types
2. Implement command result handling
3. Add monitoring and metrics
4. Create deployment configuration

## 📝 Usage Instructions

### Starting the System
```bash
# Terminal 1: Start Temporal
temporal server start-dev

# Terminal 2: Start Alert Watcher 2
python -m src.alert_watcher.main

# Terminal 3: Run tests
python test_simplified_cratedb.py
```

### Monitoring
- Temporal UI: http://localhost:8233
- Health: http://localhost:8000/health
- API docs: http://localhost:8000/docs

## ✅ Verification Checklist

- [x] Only processes CrateDBContainerRestart and CrateDBCloudNotResponsive
- [x] Rejects all other alert types
- [x] Creates sub-workflows with alert name + namespace
- [x] Hemako command placeholder with correct parameters
- [x] Removed all unnecessary code
- [x] Comprehensive test suite
- [x] Updated documentation
- [x] Clean project structure

## 🎉 Conclusion

The Alert Watcher 2 system has been successfully simplified to focus exclusively on the two required CrateDB alert types. The new architecture provides:

- **Clear separation** between main workflow and alert processing
- **Isolated execution** through sub-workflows
- **Easy identification** through descriptive naming
- **Extensible design** for future enhancements
- **Comprehensive testing** with realistic scenarios

The system is now ready for hemako command implementation and production deployment.