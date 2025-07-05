# Alert Watcher 2 - Product Requirements Document

## Overview

Alert Watcher 2 is a Kubernetes-native webhook service that receives Prometheus AlertManager notifications and processes them through Temporal workflows. The system is designed to handle alert events reliably with proper retry mechanisms, logging, and file upload capabilities.

## Architecture

```
Prometheus AlertManager -> Webhook Server -> Temporal Signal -> Long-running Workflow -> S3 Upload
```

### Signal-Based Flow

The system follows the recommended Temporal pattern for webhook integration:

| Step | Component | Action |
|---|---|---|
| 1 | Prometheus AlertManager | Sends webhook (HTTP POST) on alert |
| 2 | Webhook Server | Receives webhook, validates payload |
| 3 | Signal Forwarder | Checks if target workflow exists |
| 4 | Temporal Client | Sends signal to workflow (`workflow.signal("alertReceived", alertData)`) |
| 5 | Long-running Workflow | Handles signal, processes alert through activities |
| 6 | Activities | Execute logging, file processing, S3 upload |

**Key Benefits:**
- **Reliability**: Temporal signals are durable and guaranteed delivery
- **Idempotency**: Duplicate signals can be handled gracefully
- **Persistence**: Workflows maintain state across multiple alert events
- **Retry Logic**: AlertManager retries failed webhooks, Temporal handles activity retries

### Key Components

1. **Webhook Server**: FastAPI-based HTTP server that receives AlertManager webhooks
2. **Temporal Signal Forwarder**: Converts webhook events into Temporal signals
3. **Long-running Workflow**: Persistent workflow that waits for and processes alert signals
4. **Activities**: Individual tasks like logging, file processing, and S3 uploads
5. **Kubernetes Deployment**: Containerized deployment with Temporal dev-mode

## Technical Stack

- **Language**: Python 3.12+
- **Package Manager**: astral.sh uv
- **Web Framework**: FastAPI
- **Workflow Engine**: Temporal
- **Container**: Docker
- **Orchestration**: Kubernetes
- **Storage**: AWS S3
- **Monitoring**: Prometheus AlertManager

## Feature Requirements

### Core Features

1. **Webhook Receiver**
   - Accept POST requests from Prometheus AlertManager
   - Validate webhook payload structure
   - Return appropriate HTTP status codes
   - Handle concurrent requests

2. **Temporal Signal Integration**
   - Forward webhook events as signals to long-running workflows
   - Ensure target workflows exist before signaling (start if needed)
   - Handle workflow lifecycle management
   - Implement signal deduplication and idempotency
   - Configure retry policies with exponential backoff
   - Handle workflow failures gracefully
   - Process multiple concurrent signals within same workflow

3. **Event Processing**
   - Log received alerts with structured logging
   - Extract relevant alert metadata for supported alert types
   - Process alerts through signal-driven workflow execution
   - Handle duplicate signals gracefully
   - Maintain workflow state across multiple alert events
   - Support specific alert types: `CrateDBCloudNotResponsive`, `CrateDBContainerRestart`

4. **JFR Collection and Upload Activity**
   - Execute JFR collection command via `hemako jfr collect`
   - Mock S3 upload functionality for collected JFR files
   - Extract pod, namespace, and context information from alerts
   - Implement proper error handling for command execution
   - Support retry mechanism for failed collections and uploads

5. **Monitoring & Testing**
   - Create test alerts for `CrateDBCloudNotResponsive` and `CrateDBContainerRestart`
   - Health check endpoints
   - Metrics collection

## Non-Functional Requirements

- **Reliability**: 99.9% uptime with proper error handling and signal delivery
- **Scalability**: Handle up to 100 concurrent alert events per workflow
- **Observability**: Comprehensive logging and metrics for signals and workflows
- **Security**: Validate webhook signatures (future enhancement)
- **Idempotency**: Handle duplicate alerts and signals gracefully

## Actionable Task List

### Phase 1: Project Setup & Dependencies

- [ ] **Task 1.1**: Update `pyproject.toml` with required dependencies
  - Add FastAPI, Uvicorn, Temporal SDK, boto3, pydantic, structlog
  - Configure development dependencies (pytest, black, ruff)

- [ ] **Task 1.2**: Create project structure
  - Create `src/alert_watcher/` package structure
  - Add `__init__.py` files
  - Create modules: `webhook.py`, `workflows.py`, `activities.py`, `config.py`

- [ ] **Task 1.3**: Setup configuration management
  - Create `Config` class with environment variables
  - Add Temporal server connection settings
  - Configure logging levels and formats

### Phase 2: Webhook Server Implementation

- [ ] **Task 2.1**: Implement FastAPI webhook receiver
  - Create `/webhook/alertmanager` endpoint
  - Add request validation using Pydantic models
  - Implement basic error handling and logging

- [ ] **Task 2.2**: Add AlertManager payload models
  - Create Pydantic models for AlertManager webhook structure
  - Add validation for required fields (namespace, pod, kube_context)
  - Handle different alert states (firing, resolved)
  - Add specific models for `CrateDBCloudNotResponsive` and `CrateDBContainerRestart`

- [ ] **Task 2.3**: Implement Temporal signal forwarding
  - Create signal forwarding logic in webhook endpoint
  - Handle workflow existence checks
  - Implement signal deduplication logic
  - Add error handling for signal failures

- [ ] **Task 2.4**: Add health check endpoint
  - Create `/health` endpoint for Kubernetes probes
  - Add `/ready` endpoint for readiness checks
  - Include basic system status information

### Phase 3: Temporal Workflow Implementation

- [ ] **Task 3.1**: Create long-running Temporal workflow
  - Implement `AlertProcessingWorkflow` as a persistent workflow
  - Add signal handlers for different alert types
  - Configure workflow to run continuously and wait for signals
  - Implement workflow lifecycle management

- [ ] **Task 3.2**: Implement signal handling
  - Create signal methods for alert processing
  - Add signal deduplication logic within workflow
  - Handle multiple concurrent signals
  - Implement signal-to-activity mapping

- [ ] **Task 3.3**: Implement workflow activities
  - Create `LogAlertActivity` for structured logging
  - Implement `JFRCollectionActivity` with hemako command execution
  - Add `S3UploadActivity` with mocked upload functionality
  - Add proper activity decorators and error handling

- [ ] **Task 3.4**: Configure retry and backoff policies
  - Set exponential backoff for activities
  - Configure maximum retry attempts
  - Add custom retry policies for different failure types

- [ ] **Task 3.5**: Add heartbeat mechanism
  - Implement heartbeat in long-running activities
  - Configure heartbeat timeout settings
  - Add heartbeat logging for monitoring

- [ ] **Task 3.6**: Implement workflow management
  - Add logic to start workflows if they don't exist
  - Handle workflow termination and restart scenarios
  - Implement workflow health monitoring

### Phase 4: Activity Implementation

- [ ] **Task 4.1**: Implement alert logging activity
  - Create structured logging with alert metadata
  - Add timestamp, severity, source information, and extracted parameters
  - Store logs in JSON format for better parsing
  - Include pod, namespace, kube_context, and alert_name in logs

- [ ] **Task 4.2**: Create JFR collection activity (mocked)
  - Implement mocked `hemako jfr collect` command execution
  - Extract parameters from alert: namespace, pod, kube_context
  - Generate mock JFR collection command with proper flags
  - Add error simulation for testing retry logic
  - Mock file generation for S3 upload testing

- [ ] **Task 4.3**: Create S3 upload activity (mocked)
  - Implement mock S3 upload functionality for JFR files
  - Add placeholder for actual S3 integration
  - Include error simulation for testing retry logic

- [ ] **Task 4.4**: Add activity monitoring
  - Log activity start/completion times
  - Add metrics for activity success/failure rates
  - Implement activity-specific error handling
  - Monitor JFR collection command execution times

### Phase 5: Testing & Validation

- [ ] **Task 5.1**: Create test alert configurations
  - Design sample Prometheus rules for `CrateDBCloudNotResponsive` and `CrateDBContainerRestart`
  - Create AlertManager configuration for webhook
  - Add test alert payloads with required fields (namespace, pod, kube_context)
  - Include STS identifier in test payloads

- [ ] **Task 5.2**: Implement unit tests
  - Test webhook endpoint validation for supported alert types
  - Test workflow execution paths for both alert types
  - Test activity retry mechanisms
  - Test JFR command parameter extraction and validation

- [ ] **Task 5.3**: Add integration tests
  - Test end-to-end alert processing
  - Verify Temporal workflow execution
  - Test error scenarios and recovery

### Phase 6: Containerization

- [ ] **Task 6.1**: Create Dockerfile
  - Use Python 3.12 slim base image
  - Install uv and dependencies
  - Configure proper entrypoint and health checks

- [ ] **Task 6.2**: Create docker-compose for development
  - Include Temporal server in dev-mode
  - Add sqllite for Temporal persistence
  - Configure networking between services

- [ ] **Task 6.3**: Build and test Docker image
  - Create multi-stage build for optimization
  - Test image locally with docker-compose
  - Verify all dependencies are included

### Phase 7: Kubernetes Deployment

- [ ] **Task 7.1**: Create Kubernetes manifests
  - Create Deployment for alert-watcher service
  - Add Service for webhook exposure
  - Create ConfigMap for application configuration

- [ ] **Task 7.2**: Deploy Temporal in dev-mode
  - Create Temporal server Deployment
  - Add Temporal UI Service
  - Configure persistent storage (if needed)

- [ ] **Task 7.3**: Add Kubernetes health checks
  - Configure liveness and readiness probes
  - Set resource limits and requests
  - Add proper labels and annotations

### Phase 8: Monitoring & Observability

- [ ] **Task 8.1**: Add structured logging
  - Use structlog for JSON-formatted logs
  - Add correlation IDs for request tracking
  - Configure log levels and rotation

- [ ] **Task 8.2**: Add metrics collection
  - Implement Prometheus metrics endpoints
  - Add custom metrics for alert processing
  - Monitor workflow execution times

- [ ] **Task 8.3**: Create monitoring dashboards
  - Design Grafana dashboard for key metrics
  - Add alerting rules for system health
  - Document monitoring setup

## File Structure

```
alert-watcher2/
├── src/
│   └── alert_watcher/
│       ├── __init__.py
│       ├── main.py
│       ├── webhook.py
│       ├── workflows.py
│       ├── activities.py
│       ├── signals.py
│       ├── workflow_manager.py
│       ├── config.py
│       └── models.py
├── tests/
│   ├── __init__.py
│   ├── test_webhook.py
│   ├── test_workflows.py
│   └── test_activities.py
├── k8s/
│   ├── deployment.yaml
│   ├── service.yaml
│   ├── configmap.yaml
│   └── temporal-dev.yaml
├── docker/
│   └── Dockerfile
├── prometheus/
│   ├── alerts.yaml
│   ├── alertmanager.yaml
│   └── test-alerts.yaml
├── pyproject.toml
├── README.md
└── PRD.md
```

## Success Criteria

1. **Functional**: System successfully receives webhooks and forwards them as signals
2. **Reliability**: Long-running workflows handle signals with proper deduplication
3. **Durability**: Temporal signals are delivered reliably to persistent workflows
4. **Observability**: Comprehensive logging and monitoring in place
5. **Deployment**: Successfully deployed and running in Kubernetes
6. **Testing**: All test scenarios pass including signal handling and idempotency

## Timeline

- **Phase 1-2**: 3 days (Setup and webhook with signal forwarding)
- **Phase 3-4**: 4 days (Temporal signal-based workflows and activities)
- **Phase 5**: 2 days (Testing and validation)
- **Phase 6-7**: 2 days (Containerization and K8s deployment)
- **Phase 8**: 1 day (Monitoring and documentation)

**Total Estimated Time**: 12 days

## Dependencies

- Temporal server (dev-mode deployment)
- Prometheus AlertManager configuration
- AWS S3 credentials (for future real implementation)
- Kubernetes cluster for deployment

## Supported Alert Types

### CrateDBCloudNotResponsive
- **Trigger**: When CrateDB cluster becomes unresponsive
- **Action**: Collect JFR data for diagnostics
- **Required Fields**: namespace, pod, kube_context, sts

### CrateDBContainerRestart
- **Trigger**: When CrateDB container restarts unexpectedly
- **Action**: Collect JFR data before restart cleanup
- **Required Fields**: namespace, pod, kube_context, sts

## JFR Collection Command Structure

```json
{
  "command": "hemako jfr collect --kube-context us-west-2 --namespace 4cc4dc86-b624-4947-87c8-b5f5a2607536 --pod crate-data-hot-12345 --duration 30s --approve",
  "alert_name": "CrateDBCloudNotResponsive",
  "namespace": "4cc4dc86-b624-4947-87c8-b5f5a2607536",
  "pod": "crate-data-hot-12345",
  "sts": "5ccc5dc86-b624-4555-xxxx-xxxxxxx",
  "kube_context": "us-west-2"
}
```

## Future Enhancements

1. Real hemako JFR collection implementation
2. Real S3 file upload implementation
3. Webhook signature validation
4. Alert deduplication logic
5. Support for additional CrateDB alert types
6. Integration with additional notification systems
7. Advanced signal filtering and aggregation
8. Multi-tenant workflow isolation
9. Signal-based workflow orchestration for complex alert chains
10. Temporal visibility integration for workflow monitoring
11. Dynamic JFR collection parameters based on alert severity
