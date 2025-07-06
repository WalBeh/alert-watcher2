#!/bin/bash

# Alert Watcher 2 - Deploy Script
# This script deploys to Kubernetes (Docker build handled by Makefile)

set -e

# Configuration
IMAGE_NAME="cloud.registry.cr8.net/alert-manager2"
TAG="${1:-latest}"
NAMESPACE="${2:-default}"
FULL_IMAGE="$IMAGE_NAME:$TAG"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "deployment.yaml" ]; then
    echo_error "deployment.yaml not found. Please run this script from the deploy/ directory."
    exit 1
fi

echo_info "Deploying Alert Watcher 2 to Kubernetes"
echo_info "Image: $FULL_IMAGE (must be pre-built with: make build-push)"
echo_info "Namespace: $NAMESPACE"

# Update deployment image
echo_info "Updating deployment image to $FULL_IMAGE"
sed -i.bak "s|image: cloud.registry.cr8.net/alert-manager2:.*|image: $FULL_IMAGE|" deployment.yaml
rm -f deployment.yaml.bak

# Show deployment commands (no kubectl execution)
echo_info "Ready to deploy! Run these commands:"
echo ""
echo "# Apply manifests:"
echo "kubectl apply -f rbac.yaml -n $NAMESPACE"
echo "kubectl apply -f deployment.yaml -n $NAMESPACE"
echo "kubectl apply -f service.yaml -n $NAMESPACE"
echo "kubectl apply -f pdb.yaml -n $NAMESPACE"
echo "kubectl apply -f networkpolicy.yaml -n $NAMESPACE"
echo ""
echo "# Wait for deployment:"
echo "kubectl wait --for=condition=available --timeout=300s deployment/alert-watcher2 -n $NAMESPACE"
echo ""
echo "# Check status:"
echo "kubectl get deployments alert-watcher2 -n $NAMESPACE"
echo "kubectl get pods -l app=alert-watcher2 -n $NAMESPACE"
echo "kubectl get svc alert-watcher2 -n $NAMESPACE"
echo ""
echo "# Access the application:"
echo "kubectl port-forward svc/alert-watcher2 8000:80 -n $NAMESPACE"
echo ""
echo_info "Deployment configuration updated successfully!"
echo_info "Note: Build Docker image first with: make build-push"
