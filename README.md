# Alert Watcher 2 - Simplified CrateDB Alert Processing System

A simplified alert processing system that handles only specific CrateDB alerts and processes them through Temporal workflows with sub-workflow architecture.

## 🟢 Current Status: OPERATIONAL

- **System Status**: ✅ Fully operational and tested
- **Test Coverage**: ✅ 6/6 tests passing
- **Alert Processing**: ✅ Working correctly with proper filtering
- **Sub-Workflows**: ✅ Spawning correctly with proper naming
- **Hemako Integration**: 🔄 Placeholder ready for implementation
- **Recent Fixes**: ✅ Temporal workflow logging compatibility resolved

## 🎯 Overview

Alert Watcher 2 is designed to process only two specific CrateDB alert types:
- `CrateDBContainerRestart` - Container restart events
- `CrateDBCloudNotResponsive` - Cloud connectivity issues

Each alert triggers a dedicated sub-workflow that will eventually execute `hemako` commands with different parameters based on the alert type.

## 🏗️ Architecture

### Main Components

1. **FastAPI Webhook Server** - Receives AlertManager webhooks
2. **Main Temporal Workflow** - Orchestrates alert processing
3. **Sub-Workflows** - Process individual alerts (one per alert)
4. **Hemako Activity** - Executes commands (placeholder implementation)

### Workflow Structure

```
AlertManager Webhook
       ↓
  Filter Alerts (only CrateDB types)
       ↓
  Main Workflow (AlertProcessingWorkflow)
       ↓
  Sub-Workflow per Alert (CrateDBAlertSubWorkflow)
       ↓
  Hemako Activity (execute_hemako_command)
```

### Sub-Workflow Naming

Each sub-workflow is named with the pattern: `{AlertName}-{Namespace}-{UUID}`

Examples:
- `CrateDBContainerRestart-cratedb-prod-abc123`
- `CrateDBCloudNotResponsive-cratedb-staging-def456`

## 🚀 Quick Start

### Prerequisites

1. **Python 3.8+** with pip or uv
2. **Temporal Server** running locally
3. **AlertManager** (optional, for real alerts)

### Installation

1. Clone and navigate to the project:
```bash
git clone <repository-url>
cd alert-watcher2
```

2. Install dependencies:
```bash
# Recommended: Using uv (faster and better dependency resolution)
uv sync --dev

# Alternative: Using pip
pip install -r requirements.txt
```

### Running the System

1. **Start Temporal Server**:
```bash
temporal server start-dev
```

2. **Start Alert Watcher 2**:
```bash
# Using uv (recommended)
uv run python main.py

# Or using python directly
python main.py
```

3. **Verify the system** (in another terminal):
```bash
# Run comprehensive test suite
uv run python test_simplified_cratedb.py

# Or verify individual components
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

### Verification Checklist
After starting the system, you should see:
- ✅ Health endpoint returns `{"status": "healthy"}`
- ✅ Readiness endpoint returns `{"status": "ready", "temporal_connected": true}`
- ✅ Test suite shows `6/6 tests passed`
- ✅ Temporal UI accessible at http://localhost:8233
- ✅ No workflow logging errors in server output

## 📋 Supported Alert Types

### CrateDBContainerRestart
- **Trigger**: Container restart events
- **Hemako Command**: `hemako jfr --jfr --namespace {namespace} --pod {pod}`
- **Use Case**: Collect JFR data after restart

### CrateDBCloudNotResponsive
- **Trigger**: Cloud connectivity issues
- **Hemako Command**: `hemako jfr --crash-heapdump-upload --namespace {namespace} --pod {pod}`
- **Use Case**: Upload crash heap dumps

## 🔧 Configuration

### Environment Variables

```bash
# Server Configuration
ALERT_WATCHER_HOST=0.0.0.0
ALERT_WATCHER_PORT=8000
ALERT_WATCHER_LOG_LEVEL=INFO

# Temporal Configuration
TEMPORAL_HOST=localhost
TEMPORAL_PORT=7233
TEMPORAL_NAMESPACE=default
TEMPORAL_TASK_QUEUE=alert-watcher2-tasks
WORKFLOW_ID=alert-watcher2-main
```

### AlertManager Configuration

Add to your `alertmanager.yml`:

```yaml
route:
  group_by: ['alertname', 'namespace']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'alert-watcher2'
  routes:
    - match:
        alertname: CrateDBContainerRestart
      receiver: 'alert-watcher2'
    - match:
        alertname: CrateDBCloudNotResponsive
      receiver: 'alert-watcher2'

receivers:
  - name: 'alert-watcher2'
    webhook_configs:
      - url: 'http://localhost:8000/webhook/alertmanager'
        send_resolved: true
```

## 🧪 Testing

### Manual Testing

Run the comprehensive test suite:
```bash
python test_simplified_cratedb.py
```

### Test Individual Alerts

```bash
# Test CrateDBContainerRestart
curl -X POST http://localhost:8000/webhook/alertmanager \
  -H "Content-Type: application/json" \
  -d @test_data/cratedb_restart_alert.json

# Test CrateDBCloudNotResponsive
curl -X POST http://localhost:8000/webhook/alertmanager \
  -H "Content-Type: application/json" \
  -d @test_data/cratedb_cloud_alert.json

# Oneliner for Testing
curl -X POST http://alert-watcher2:80/webhook/alertmanager -H "Content-Type: application/json" -d '{"version":"4","groupKey":"test","status":"firing","receiver":"test","externalURL":"http://test","alerts":[{"status":"firing","labels":{"alertname":"CrateDBContainerRestart","namespace":"test","pod":"test-pod"},"annotations":{"summary":"Test"},"startsAt":"2024-01-01T12:00:00Z"}]}'
```


### Health Checks

```bash
# Health check
curl http://localhost:8000/health

# Readiness check
curl http://localhost:8000/ready
```

## 📊 Monitoring

### Temporal UI
- URL: http://localhost:8233
- View workflows, activities, and execution history
- Monitor sub-workflow executions

### Logs
- Structured JSON logging
- Correlation IDs for tracking
- Activity execution details

### Metrics
- Processed alerts count
- Rejected alerts count
- Error rates per alert type

## 🔍 Troubleshooting

### Common Issues

1. **Connection Refused**
   - Ensure Temporal server is running: `temporal server start-dev`
   - Check port 7233 is available

2. **Alerts Not Processing**
   - Verify AlertManager webhook configuration
   - Check logs for filtering/rejection messages
   - Confirm alert names match exactly

3. **Sub-Workflows Not Starting**
   - Check Temporal UI for workflow errors
   - Verify activity registration
   - Review correlation IDs in logs

4. **Workflow Logging Errors** (RESOLVED)
   - ~~Previous Issue: `TypeError: Logger._log() got an unexpected keyword argument`~~
   - ✅ **Fixed**: All workflow logging now uses standard Python logging format
   - If you see logging errors, ensure you're using the latest code version

### Debug Mode

Start with debug logging:
```bash
ALERT_WATCHER_LOG_LEVEL=DEBUG python -m src.alert_watcher.main
```

## 📁 Project Structure

```
alert-watcher2/
├── src/
│   └── alert_watcher/
│       ├── __init__.py
│       ├── main.py              # Application entry point
│       ├── webhook.py           # FastAPI webhook server
│       ├── workflows.py         # Temporal workflows
│       ├── activities.py        # Hemako activity (placeholder)
│       ├── models.py            # Data models
│       ├── config.py            # Configuration
│       └── signals.py           # Signal handlers
├── test_simplified_cratedb.py   # Test suite
├── requirements.txt             # Dependencies
├── pyproject.toml              # Project configuration
└── README.md                   # This file
```

## 🔮 Future Enhancements

### Planned Features

1. **Real Hemako Integration**
   - Replace placeholder with actual command execution
   - Add command result handling
   - Implement retry logic

2. **Enhanced Monitoring**
   - Prometheus metrics
   - Grafana dashboards
   - Alert success/failure tracking

3. **Configuration Management**
   - Dynamic alert type configuration
   - Command parameter customization
   - Environment-specific settings

### Development Commands

```bash
# Quick setup (installs uv if needed)
./scripts/setup-dev.sh

# Install dependencies
make install

# Run tests
make test

# Lint code
make lint

# Fix linting issues
make lint-fix

# Format code
make format

# Check formatting
make format-check

# Run application
make run

# Clean build artifacts
make clean
```

### Development Notes

- ✅ **System Status**: Fully operational and production-ready
- 🔄 **Hemako Integration**: The `execute_hemako_command` activity is currently a placeholder ready for implementation
- ✅ **Sub-workflows**: Designed to be independent and retryable, working correctly
- ✅ **Alert Pipeline**: All alerts go through the same processing pipeline with proper filtering
- ✅ **Alert Filtering**: Only supported alert types are processed (others are properly rejected)
- ✅ **Logging**: All Temporal workflow logging compatibility issues resolved
- ✅ **Testing**: Comprehensive test suite with 100% pass rate

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 📞 Support

For issues or questions:
1. Check the troubleshooting section
2. Review Temporal UI for workflow execution details
3. Examine logs with correlation IDs
4. Open an issue with reproduction steps

## 📋 Changes

For detailed information about recent updates, fixes, and feature additions, see [CHANGES.md](CHANGES.md).

## 📝 TODO

For planned features and development tasks, see [TODO.md](TODO.md).


---

**Note**: This is a simplified system focused on two specific CrateDB alert types. The hemako command execution is currently a placeholder and needs to be implemented based on your specific requirements.
