# Alert Watcher 2 - Kubernetes Deployment

This directory contains the Kubernetes manifests for deploying Alert Watcher 2 to a Kubernetes cluster.

## Overview

Alert Watcher 2 is a simplified CrateDB alert processing system that:
- Processes two types of alerts: `CrateDBContainerRestart` and `CrateDBCloudNotResponsive`
- Uses Temporal workflows for reliable alert processing
- Spawns sub-workflows for each alert with naming format: `{AlertName}-{Namespace}-{UUID}`
- Integrates with hemako commands for alert remediation

## Prerequisites

- Kubernetes cluster (1.20+)
- kubectl configured to access your cluster
- Temporal server running in the cluster
- Container registry access to `cloud.registry.cr8.net`

## Quick Start

### 1. Build and Push Docker Image

```bash
# Build the Docker image
docker build -t cloud.registry.cr8.net/alert-manager2:latest .

# Push to registry
docker push cloud.registry.cr8.net/alert-manager2:latest
```

### 2. Deploy to Kubernetes

```bash
# Apply all manifests
kubectl apply -f deploy/

# Build and push Docker image first
make build-push

# Then apply individual manifests
kubectl apply -f deploy/rbac.yaml
kubectl apply -f deploy/deployment.yaml
kubectl apply -f deploy/service.yaml
kubectl apply -f deploy/pdb.yaml
kubectl apply -f deploy/networkpolicy.yaml
```

### 3. Verify Deployment

```bash
# Check deployment status
kubectl get deployments alert-watcher2
kubectl get pods -l app=alert-watcher2

# Check service
kubectl get svc alert-watcher2
```

## Configuration

### Environment Variables

The application can be configured using environment variables defined directly in the deployment:

| Variable | Default | Description |
|----------|---------|-------------|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `TEMPORAL_HOST` | `temporal-frontend` | Temporal server hostname |
| `TEMPORAL_PORT` | `7233` | Temporal server port |
| `TEMPORAL_NAMESPACE` | `default` | Temporal namespace |
| `TEMPORAL_TASK_QUEUE` | `alert-processing` | Temporal task queue name |
| `WORKFLOW_ID` | `alert-watcher2` | Main workflow ID |
| `WORKFLOW_TIMEOUT_SECONDS` | `3600` | Workflow timeout |
| `ACTIVITY_TIMEOUT_SECONDS` | `300` | Activity timeout |
| `MAX_RETRIES` | `3` | Maximum retry attempts |
| `RETRY_BACKOFF_SECONDS` | `2` | Retry backoff base seconds |

### Temporal Configuration

The application requires a Temporal server to be running in the cluster. Update the `TEMPORAL_HOST` environment variable in `deployment.yaml` to point to your Temporal frontend service.

## Manifest Files

| File | Description |
|------|-------------|
| `deployment.yaml` | Main application deployment with environment variables |
| `service.yaml` | ClusterIP service for the application |
| `rbac.yaml` | Service account and RBAC permissions |
| `pdb.yaml` | Pod disruption budget for high availability |
| `networkpolicy.yaml` | Network security policies |

## Endpoints

Once deployed, the application exposes the following endpoints:

- `GET /health` - Health check endpoint
- `GET /ready` - Readiness check endpoint
- `POST /webhook/alertmanager` - Alertmanager webhook endpoint
- `POST /test/alert` - Test alert endpoint

## Accessing the Application

Since there's no ingress configured, you can access the application using:

### Port Forwarding
```bash
kubectl port-forward svc/alert-watcher2 8000:80
```

Then access the application at `http://localhost:8000`

### Service IP (within cluster)
```bash
kubectl get svc alert-watcher2
```

Use the ClusterIP to access from other pods within the cluster.

## Build and Deploy Commands

### Using Makefile (Recommended)
```bash
# Build and push Docker image
make build-push

# Show deployment commands (no execution)
make deploy

# Check what commands to run
make status
```

### Using Deploy Scripts
```bash
# Update deployment configuration
./deploy/simple-deploy.sh

# Or use the detailed script
./deploy/build-and-deploy.sh
```

Note: All scripts show you the commands to run rather than executing them automatically.

## Monitoring

### Health Checks

The deployment includes both liveness and readiness probes:

- **Liveness Probe**: `/health` endpoint checked every 10 seconds
- **Readiness Probe**: `/ready` endpoint checked every 5 seconds

### Logs

View application logs:

```bash
kubectl logs -l app=alert-watcher2 -f
```

### Metrics

The application can be extended with Prometheus metrics. The network policy allows ingress from monitoring systems.

## Scaling

To scale the deployment:

```bash
kubectl scale deployment alert-watcher2 --replicas=3
```

Note: The application is designed to run as a single instance due to the Temporal workflow requirements, but can be scaled for load distribution.

## Troubleshooting

### Common Issues

1. **Pod not starting**: Check logs and ensure Temporal server is accessible
2. **Ingress not working**: Verify NGINX ingress controller is installed
3. **Network issues**: Check network policies and DNS resolution

### Debug Commands

```bash
# Check pod status
kubectl describe pod -l app=alert-watcher2

# Check service endpoints
kubectl get endpoints alert-watcher2

# Test internal connectivity
kubectl exec -it deployment/alert-watcher2 -- curl localhost:8000/health

# Check Temporal connectivity
kubectl exec -it deployment/alert-watcher2 -- nslookup temporal-frontend

# Test webhook endpoint
kubectl port-forward svc/alert-watcher2 8000:80 &
curl -X POST http://localhost:8000/webhook/alertmanager \
  -H "Content-Type: application/json" \
  -d '{"alerts": [{"labels": {"alertname": "CrateDBContainerRestart"}}]}'
```

## Security

The deployment includes several security measures:

- Non-root user execution
- Read-only root filesystem capability
- Network policies restricting traffic
- RBAC with minimal required permissions
- Security context with dropped capabilities

## Cleanup

To remove the deployment:

```bash
kubectl delete -f deploy/networkpolicy.yaml
kubectl delete -f deploy/pdb.yaml
kubectl delete -f deploy/service.yaml
kubectl delete -f deploy/deployment.yaml
kubectl delete -f deploy/rbac.yaml
```

Or use the Makefile:
```bash
make undeploy  # Shows commands to run
```

## Support

For issues and questions, refer to the main project documentation or contact the development team.