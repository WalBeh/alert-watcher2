# Alert Watcher 2 - Makefile
# Provides convenient commands for building, testing, and deploying

# Configuration
IMAGE_NAME := cloud.registry.cr8.net/alert-manager2
TAG := latest
NAMESPACE := default
FULL_IMAGE := $(IMAGE_NAME):$(TAG)

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[1;33m
NC := \033[0m

# Default target
.PHONY: help
help:
	@echo "Alert Watcher 2 - Available Commands"
	@echo ""
	@echo "Build Commands:"
	@echo "  build         Build Docker image"
	@echo "  push          Push Docker image to registry"
	@echo "  build-push    Build and push Docker image"
	@echo ""
	@echo "Development Commands:"
	@echo "  install       Install dependencies"
	@echo "  test          Run tests"
	@echo "  lint          Run linting with ruff"
	@echo "  lint-fix      Fix linting issues with ruff"
	@echo "  format        Format code with ruff"
	@echo "  format-check  Check code formatting"
	@echo "  run           Run application locally"
	@echo "  clean         Clean build artifacts"
	@echo ""
	@echo "Deployment Commands:"
	@echo "  deploy        Deploy to Kubernetes"
	@echo "  deploy-dev    Deploy to development environment"
	@echo "  deploy-prod   Deploy to production environment"
	@echo "  status        Show deployment status"
	@echo "  logs          Show application logs"
	@echo "  undeploy      Remove deployment from Kubernetes"
	@echo ""
	@echo "Utility Commands:"
	@echo "  shell         Open shell in running container"
	@echo "  port-forward  Forward port 8000 to local machine"
	@echo "  health        Check application health"
	@echo "  test-webhook  Test webhook endpoint"
	@echo ""
	@echo "Variables:"
	@echo "  IMAGE_NAME=$(IMAGE_NAME)"
	@echo "  TAG=$(TAG)"
	@echo "  NAMESPACE=$(NAMESPACE)"

# Build commands
.PHONY: build
build:
	@echo "$(GREEN)[INFO]$(NC) Building Docker image: $(FULL_IMAGE)"
	docker build -t $(FULL_IMAGE) .

.PHONY: push
push:
	@echo "$(GREEN)[INFO]$(NC) Pushing Docker image: $(FULL_IMAGE)"
	docker push $(FULL_IMAGE)

.PHONY: build-push
build-push: build push

# Development commands
.PHONY: install
install:
	@echo "$(GREEN)[INFO]$(NC) Installing dependencies with uv"
	@if command -v uv >/dev/null 2>&1; then \
		uv sync; \
	else \
		echo "$(YELLOW)[WARN]$(NC) uv not installed, falling back to pip"; \
		pip install -r requirements.txt; \
	fi

.PHONY: test
test:
	@echo "$(GREEN)[INFO]$(NC) Running tests"
	@if command -v uv >/dev/null 2>&1; then \
		uv run python -m pytest test_simplified_cratedb.py -v; \
	else \
		python -m pytest test_simplified_cratedb.py -v; \
	fi

.PHONY: lint
lint:
	@echo "$(GREEN)[INFO]$(NC) Running linting with ruff"
	@if command -v uv >/dev/null 2>&1; then \
		uv run ruff check src/; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff check src/; \
	else \
		echo "$(YELLOW)[WARN]$(NC) ruff not installed, skipping lint"; \
	fi

.PHONY: run
run:
	@echo "$(GREEN)[INFO]$(NC) Running application locally"
	@if command -v uv >/dev/null 2>&1; then \
		uv run python main.py; \
	else \
		python main.py; \
	fi

.PHONY: clean
clean:
	@echo "$(GREEN)[INFO]$(NC) Cleaning build artifacts"
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -name "*.log" -delete

# Deployment commands
.PHONY: deploy
deploy: build-push
	@echo "$(GREEN)[INFO]$(NC) Deploying to Kubernetes namespace: $(NAMESPACE)"
	cd deploy && sed -i.bak "s|image: cloud.registry.cr8.net/alert-manager2:.*|image: $(FULL_IMAGE)|" deployment.yaml && rm -f deployment.yaml.bak
	@echo "$(GREEN)[INFO]$(NC) Apply the following manifests manually:"
	@echo "kubectl apply -f deploy/rbac.yaml -n $(NAMESPACE)"
	@echo "kubectl apply -f deploy/deployment.yaml -n $(NAMESPACE)"
	@echo "kubectl apply -f deploy/service.yaml -n $(NAMESPACE)"
	#@echo "kubectl apply -f deploy/pdb.yaml -n $(NAMESPACE)"
	#@echo "kubectl apply -f deploy/networkpolicy.yaml -n $(NAMESPACE)"

.PHONY: deploy-dev
deploy-dev:
	@$(MAKE) deploy TAG=dev NAMESPACE=development

.PHONY: deploy-prod
deploy-prod:
	@$(MAKE) deploy TAG=latest NAMESPACE=production

.PHONY: status
status:
	@echo "$(GREEN)[INFO]$(NC) Check deployment status with:"
	@echo "kubectl get deployments alert-watcher2 -n $(NAMESPACE)"
	@echo "kubectl get pods -l app=alert-watcher2 -n $(NAMESPACE)"
	@echo "kubectl get svc alert-watcher2 -n $(NAMESPACE)"
	@echo ""
	@echo "$(GREEN)[INFO]$(NC) To access the application:"
	@echo "kubectl port-forward svc/alert-watcher2 8000:80 -n $(NAMESPACE)"

.PHONY: logs
logs:
	@echo "$(GREEN)[INFO]$(NC) View application logs with:"
	@echo "kubectl logs -l app=alert-watcher2 -n $(NAMESPACE) -f"

.PHONY: undeploy
undeploy:
	@echo "$(GREEN)[INFO]$(NC) Remove deployment with:"
	@echo "kubectl delete -f deploy/networkpolicy.yaml -n $(NAMESPACE)"
	@echo "kubectl delete -f deploy/pdb.yaml -n $(NAMESPACE)"
	@echo "kubectl delete -f deploy/service.yaml -n $(NAMESPACE)"
	@echo "kubectl delete -f deploy/deployment.yaml -n $(NAMESPACE)"
	@echo "kubectl delete -f deploy/rbac.yaml -n $(NAMESPACE)"

# Utility commands
.PHONY: shell
shell:
	@echo "$(GREEN)[INFO]$(NC) Open shell in running container with:"
	@echo "kubectl exec -it deployment/alert-watcher2 -n $(NAMESPACE) -- /bin/bash"

.PHONY: port-forward
port-forward:
	@echo "$(GREEN)[INFO]$(NC) Start port forwarding with:"
	@echo "kubectl port-forward deployment/alert-watcher2 8000:8000 -n $(NAMESPACE)"

.PHONY: health
health:
	@echo "$(GREEN)[INFO]$(NC) Check application health with:"
	@echo "kubectl exec -it deployment/alert-watcher2 -n $(NAMESPACE) -- curl -s localhost:8000/health"

# Test webhook endpoint
.PHONY: test-webhook
test-webhook:
	@echo "$(GREEN)[INFO]$(NC) Test webhook endpoint with:"
	@echo "1. kubectl port-forward svc/alert-watcher2 8000:80 -n $(NAMESPACE) &"
	@echo "2. curl -X POST http://localhost:8000/webhook/alertmanager \\"
	@echo "     -H 'Content-Type: application/json' \\"
	@echo "     -d '{\"alerts\": [{\"labels\": {\"alertname\": \"CrateDBContainerRestart\"}}]}'"

# Development shortcuts
.PHONY: dev-setup
dev-setup: install
	@echo "$(GREEN)[INFO]$(NC) Development environment setup complete"

.PHONY: dev-test
dev-test: test lint format-check
	@echo "$(GREEN)[INFO]$(NC) Development tests complete"

.PHONY: ci-build
ci-build: clean build test
	@echo "$(GREEN)[INFO]$(NC) CI build complete"

# Docker shortcuts
.PHONY: docker-run
docker-run: build
	@echo "$(GREEN)[INFO]$(NC) Running Docker container locally"
	docker run -p 8000:8000 --rm $(FULL_IMAGE)

.PHONY: docker-shell
docker-shell: build
	@echo "$(GREEN)[INFO]$(NC) Opening shell in Docker container"
	docker run -it --rm $(FULL_IMAGE) /bin/bash

# Quick deployment with custom tag
.PHONY: quick-deploy
quick-deploy:
	@if [ -z "$(TAG)" ]; then \
		echo "$(RED)[ERROR]$(NC) TAG is required. Usage: make quick-deploy TAG=your-tag"; \
		exit 1; \
	fi
	@$(MAKE) deploy TAG=$(TAG)

# Reset deployment (useful for development)
.PHONY: reset-deploy
reset-deploy: undeploy deploy
	@echo "$(GREEN)[INFO]$(NC) Deployment reset complete"

# Show resource usage
.PHONY: resources
resources:
	@echo "$(GREEN)[INFO]$(NC) Resource usage:"
	kubectl top pods -l app=alert-watcher2 -n $(NAMESPACE) 2>/dev/null || \
	echo "$(YELLOW)[WARN]$(NC) Metrics server not available"

# Debug information
.PHONY: debug
debug:
	@echo "$(GREEN)[INFO]$(NC) Debug information:"
	@echo "Image: $(FULL_IMAGE)"
	@echo "Namespace: $(NAMESPACE)"
	@echo "Kubectl context: $$(kubectl config current-context)"
	@echo "Docker version: $$(docker version --format '{{.Client.Version}}')"
	@echo "Kubectl version: $$(kubectl version --client --short)"

# Validate manifests
.PHONY: validate
validate:
	@echo "$(GREEN)[INFO]$(NC) Validating Kubernetes manifests"
	kubectl apply -k deploy/ --dry-run=client -o yaml > /dev/null
	@echo "$(GREEN)[INFO]$(NC) Manifests are valid"

# Show all available make targets
# Format code
.PHONY: format
format:
	@echo "$(GREEN)[INFO]$(NC) Formatting code with ruff"
	@if command -v uv >/dev/null 2>&1; then \
		uv run ruff format src/; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff format src/; \
	else \
		echo "$(YELLOW)[WARN]$(NC) ruff not installed, skipping format"; \
	fi

# Check formatting
.PHONY: format-check
format-check:
	@echo "$(GREEN)[INFO]$(NC) Checking code formatting with ruff"
	@if command -v uv >/dev/null 2>&1; then \
		uv run ruff format --check src/; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff format --check src/; \
	else \
		echo "$(YELLOW)[WARN]$(NC) ruff not installed, skipping format check"; \
	fi

# Fix linting issues
.PHONY: lint-fix
lint-fix:
	@echo "$(GREEN)[INFO]$(NC) Fixing linting issues with ruff"
	@if command -v uv >/dev/null 2>&1; then \
		uv run ruff check --fix src/; \
	elif command -v ruff >/dev/null 2>&1; then \
		ruff check --fix src/; \
	else \
		echo "$(YELLOW)[WARN]$(NC) ruff not installed, skipping lint fix"; \
	fi

.PHONY: targets
targets:
	@echo "$(GREEN)[INFO]$(NC) Available make targets:"
	@$(MAKE) -pRrq -f $(lastword $(MAKEFILE_LIST)) : 2>/dev/null | awk -v RS= -F: '/^# File/,/^# Finished Make data base/ {if ($$1 !~ "^[#.]") {print $$1}}' | sort | egrep -v -e '^[^[:alnum:]]' -e '^$@$$'
