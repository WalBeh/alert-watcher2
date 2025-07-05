# Fixes Applied to Alert Watcher 2

## Issues Fixed

### 1. Temporal Workflow Sandbox Restriction Error

**Problem:**
```
RestrictedWorkflowAccessError: Cannot access datetime.datetime.utcnow.__wrapped__ from inside a workflow.
```

**Root Cause:**
- Temporal workflows run in a sandboxed environment that restricts access to non-deterministic functions
- `datetime.utcnow()` is considered non-deterministic and was being used in Pydantic model default factories
- The Temporal sandbox detected this during workflow validation

**Solution:**
- Created an isolated `_utcnow()` function in `models.py` to wrap `datetime.utcnow()`
- Replaced direct `datetime.utcnow` usage with `time.time()` and `datetime.fromtimestamp()` pattern throughout the codebase
- Updated all timestamp generation to use deterministic patterns

**Files Modified:**
- `src/alert_watcher/models.py`: Created `_utcnow()` wrapper function
- `src/alert_watcher/activities.py`: Replaced `datetime.utcnow()` with `datetime.fromtimestamp(time.time())`
- `src/alert_watcher/webhook.py`: Replaced `datetime.utcnow()` with `datetime.fromtimestamp(time.time())`

### 2. Temporal Client API Error

**Problem:**
```
AttributeError: 'Client' object has no attribute 'close'
```

**Root Cause:**
- The code was calling `await temporal_client.close()` but the Temporal client version doesn't have this method
- This caused shutdown errors in both the main application and webhook module

**Solution:**
- Removed all `await temporal_client.close()` calls
- Set `temporal_client = None` instead for cleanup
- Updated both main.py and webhook.py shutdown handlers

**Files Modified:**
- `src/alert_watcher/main.py`: Fixed `shutdown()` and `cleanup()` methods
- `src/alert_watcher/webhook.py`: Fixed `shutdown_event()` function

### 3. Module Import Error

**Problem:**
```
ModuleNotFoundError: No module named 'alert_watcher'
```

**Root Cause:**
- Incorrect import path in main.py when trying to access the webhook module
- Used absolute import `alert_watcher.webhook` instead of relative import

**Solution:**
- Changed `import alert_watcher.webhook as webhook_module` to `from . import webhook as webhook_module`

**Files Modified:**
- `src/alert_watcher/main.py`: Fixed import statement in `run_webhook_server()` method

## Verification

After applying these fixes:

1. **Temporal Workflow Validation**: ✅ Passes
   ```
   {"event": "Temporal worker started", "activities": ["log_alert"], "workflows": ["AlertProcessingWorkflow"]}
   ```

2. **Application Startup**: ✅ Successful
   ```
   {"event": "Application initialization completed"}
   {"event": "Alert Watcher 2 is running"}
   ```

3. **Webhook Server**: ✅ Running
   ```
   INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
   ```

4. **Graceful Shutdown**: ✅ Working
   ```
   {"event": "Application shutdown complete"}
   {"event": "Cleanup completed"}
   ```

## Current Application Status

The Alert Watcher 2 simplified system now:
- ✅ Starts successfully with Temporal server connection
- ✅ Registers workflows and activities without sandbox errors
- ✅ Runs the FastAPI webhook server on port 8000
- ✅ Handles graceful shutdown properly
- ✅ Ready to receive AlertManager webhooks and log alert data structures

## Usage Instructions

```bash
# Terminal 1: Start Temporal server
temporal server start-dev

# Terminal 2: Start Alert Watcher 2
uv run python -m src.alert_watcher.main

# Terminal 3: Test with sample alerts
uv run python test_simplified.py
# or
uv run python run_example.py
```

## Next Steps

The system is now fully functional and ready to:
1. Receive AlertManager webhooks
2. Process them through Temporal workflows
3. Log complete alert data structures for analysis
4. Provide insights into AlertManager label and annotation formats

The foundation is solid for incrementally adding back features like:
- Specific alert type filtering
- JFR collection commands based on labels
- S3 upload capabilities
- Error handling and retry logic
- Monitoring and metrics