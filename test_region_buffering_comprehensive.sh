#!/bin/bash

# Comprehensive test script for region support and alert buffering
# This script demonstrates and tests the new region-based cluster routing
# and alert buffering functionality

set -e

# Configuration
WEBHOOK_URL="http://localhost:8000"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%S.000Z")
TEST_NAMESPACE="85c8074c-9bf8-4f0a-867c-faf252c76bf0"
TEST_POD="crate-data-hot-d84c10e6-d8fb-4d10-bf60-f9f2ea919a73-1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo -e "\n${BLUE}============================================================${NC}"
    echo -e "${BLUE} $1${NC}"
    echo -e "${BLUE}============================================================${NC}"
}

print_section() {
    echo -e "\n${YELLOW}--- $1 ---${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ $1${NC}"
}

check_webhook_server() {
    print_section "Checking webhook server availability"

    if curl -s -f "$WEBHOOK_URL/health" > /dev/null; then
        print_success "Webhook server is running at $WEBHOOK_URL"
        return 0
    else
        print_error "Webhook server is not available at $WEBHOOK_URL"
        print_info "Please start the webhook server first: python webhook_server.py"
        return 1
    fi
}

test_region_routing() {
    print_header "TESTING REGION-BASED CLUSTER ROUTING"

    # Test 1: US East 1 (AWS)
    print_section "Test 1: AWS US East 1 Region"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{
            "version": "4",
            "receiver": "webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "CrateDBContainerRestart",
                        "container": "crate",
                        "namespace": "'$TEST_NAMESPACE'",
                        "pod": "'$TEST_POD'",
                        "region": "us-east-1",
                        "provider": "aws"
                    },
                    "annotations": {
                        "description": "CrateDB container restarted in AWS us-east-1",
                        "summary": "CrateDB container restart detected"
                    },
                    "startsAt": "'$TIMESTAMP'"
                }
            ]
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        cluster_context=$(echo "$response_body" | jq -r '.processed_alerts[0].cluster_context // empty')
        if [ "$cluster_context" = "eks1-us-east-1-dev" ]; then
            print_success "US East 1 correctly mapped to eks1-us-east-1-dev"
        else
            print_error "US East 1 mapping failed. Got: $cluster_context"
        fi
    else
        print_error "HTTP $http_code - Request failed"
        echo "$response_body" | jq . 2>/dev/null || echo "$response_body"
    fi

    # Test 2: Azure East US
    print_section "Test 2: Azure East US Region"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{
            "version": "4",
            "receiver": "webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "CrateDBCloudNotResponsive",
                        "container": "crate",
                        "namespace": "'$TEST_NAMESPACE'",
                        "pod": "'$TEST_POD'",
                        "region": "eastus",
                        "provider": "azure"
                    },
                    "annotations": {
                        "description": "CrateDB not responsive in Azure East US",
                        "summary": "CrateDB cluster health check failed"
                    },
                    "startsAt": "'$TIMESTAMP'"
                }
            ]
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        cluster_context=$(echo "$response_body" | jq -r '.processed_alerts[0].cluster_context // empty')
        if [ "$cluster_context" = "aks1-eastus-dev" ]; then
            print_success "Azure East US correctly mapped to aks1-eastus-dev"
        else
            print_error "Azure East US mapping failed. Got: $cluster_context"
        fi
    else
        print_error "HTTP $http_code - Request failed"
        echo "$response_body" | jq . 2>/dev/null || echo "$response_body"
    fi

    # Test 3: Fallback to namespace mapping (no region)
    print_section "Test 3: Fallback to Namespace Mapping"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{
            "version": "4",
            "receiver": "webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "CrateDBContainerRestart",
                        "container": "crate",
                        "namespace": "cratedb-prod",
                        "pod": "crate-data-prod-0"
                    },
                    "annotations": {
                        "description": "CrateDB container restarted - no region specified",
                        "summary": "CrateDB container restart (fallback test)"
                    },
                    "startsAt": "'$TIMESTAMP'"
                }
            ]
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        cluster_context=$(echo "$response_body" | jq -r '.processed_alerts[0].cluster_context // empty')
        if [ "$cluster_context" = "aks1-eastus-dev" ]; then
            print_success "Namespace fallback correctly mapped to aks1-eastus-dev"
        else
            print_error "Namespace fallback mapping failed. Got: $cluster_context"
        fi
    else
        print_error "HTTP $http_code - Request failed"
        echo "$response_body" | jq . 2>/dev/null || echo "$response_body"
    fi

    # Test 4: Unknown region fallback
    print_section "Test 4: Unknown Region Fallback"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{
            "version": "4",
            "receiver": "webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "CrateDBContainerRestart",
                        "container": "crate",
                        "namespace": "unknown-namespace",
                        "pod": "unknown-pod",
                        "region": "unknown-region"
                    },
                    "annotations": {
                        "description": "Test with unknown region and namespace",
                        "summary": "Unknown region fallback test"
                    },
                    "startsAt": "'$TIMESTAMP'"
                }
            ]
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        cluster_context=$(echo "$response_body" | jq -r '.processed_alerts[0].cluster_context // empty')
        if [ "$cluster_context" = "aks1-eastus-dev" ]; then
            print_success "Unknown region/namespace correctly fell back to aks1-eastus-dev"
        else
            print_error "Unknown region/namespace fallback failed. Got: $cluster_context"
        fi
    else
        print_error "HTTP $http_code - Request failed"
        echo "$response_body" | jq . 2>/dev/null || echo "$response_body"
    fi
}

test_buffer_functionality() {
    print_header "TESTING ALERT BUFFERING FUNCTIONALITY"

    # Test 1: Check initial buffer state
    print_section "Test 1: Initial Buffer State"
    response=$(curl -s "$WEBHOOK_URL/buffer/stats")
    if [ $? -eq 0 ]; then
        total_alerts=$(echo "$response" | jq -r '.total_alerts // 0')
        buffered_alerts=$(echo "$response" | jq -r '.buffered_alerts // 0')
        print_success "Buffer stats retrieved: $total_alerts total, $buffered_alerts buffered"
        echo "$response" | jq .
    else
        print_error "Failed to get buffer stats"
    fi

    # Test 2: Send alert (will be buffered if agent unavailable)
    print_section "Test 2: Send Alert for Buffering"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{
            "version": "4",
            "receiver": "webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "CrateDBContainerRestart",
                        "container": "crate",
                        "namespace": "'$TEST_NAMESPACE'",
                        "pod": "'$TEST_POD'",
                        "region": "us-east-1",
                        "provider": "aws"
                    },
                    "annotations": {
                        "description": "Test alert for buffering functionality",
                        "summary": "CrateDB container restart (buffer test)"
                    },
                    "startsAt": "'$TIMESTAMP'"
                }
            ]
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        processed_count=$(echo "$response_body" | jq -r '.processed_count // 0')
        print_success "Alert sent successfully - $processed_count alerts processed"

        # Check if alert was buffered or processed directly
        status=$(echo "$response_body" | jq -r '.processed_alerts[0].status // "unknown"')
        if [ "$status" = "forwarded" ]; then
            print_info "Alert was processed directly (agent available)"
        else
            print_info "Alert may have been buffered (agent unavailable)"
        fi
    else
        print_error "HTTP $http_code - Failed to send alert"
        echo "$response_body" | jq . 2>/dev/null || echo "$response_body"
    fi

    # Test 3: Check buffer state after sending alert
    print_section "Test 3: Buffer State After Alert"
    sleep 1  # Give time for processing
    response=$(curl -s "$WEBHOOK_URL/buffer/stats")
    if [ $? -eq 0 ]; then
        total_alerts=$(echo "$response" | jq -r '.total_alerts // 0')
        buffered_alerts=$(echo "$response" | jq -r '.buffered_alerts // 0')
        processed_alerts=$(echo "$response" | jq -r '.processed_alerts // 0')
        failed_alerts=$(echo "$response" | jq -r '.failed_alerts // 0')

        print_success "Buffer stats after alert:"
        echo "  Total: $total_alerts"
        echo "  Buffered: $buffered_alerts"
        echo "  Processed: $processed_alerts"
        echo "  Failed: $failed_alerts"
    else
        print_error "Failed to get buffer stats"
    fi

    # Test 4: List buffered alerts
    print_section "Test 4: List Buffered Alerts"
    response=$(curl -s "$WEBHOOK_URL/buffer/alerts")
    if [ $? -eq 0 ]; then
        alert_count=$(echo "$response" | jq -r '.total_alerts // 0')
        print_success "Found $alert_count buffered alerts"

        if [ "$alert_count" -gt 0 ]; then
            echo "Buffered alerts:"
            echo "$response" | jq -r '.alerts[] | "  - \(.alert_name) (\(.status)) - \(.namespace)/\(.pod)"'
        fi
    else
        print_error "Failed to list buffered alerts"
    fi

    # Test 5: Manual buffer flush
    print_section "Test 5: Manual Buffer Flush"
    response=$(curl -s -X POST "$WEBHOOK_URL/buffer/flush")
    if [ $? -eq 0 ]; then
        success=$(echo "$response" | jq -r '.success // false')
        message=$(echo "$response" | jq -r '.message // "No message"')

        if [ "$success" = "true" ]; then
            print_success "Buffer flush completed: $message"
        else
            print_info "Buffer flush result: $message"
        fi
    else
        print_error "Failed to flush buffer"
    fi

    # Test 6: Final buffer state
    print_section "Test 6: Final Buffer State"
    sleep 1  # Give time for processing
    response=$(curl -s "$WEBHOOK_URL/buffer/stats")
    if [ $? -eq 0 ]; then
        total_alerts=$(echo "$response" | jq -r '.total_alerts // 0')
        buffered_alerts=$(echo "$response" | jq -r '.buffered_alerts // 0')
        processed_alerts=$(echo "$response" | jq -r '.processed_alerts // 0')
        failed_alerts=$(echo "$response" | jq -r '.failed_alerts // 0')

        print_success "Final buffer stats:"
        echo "  Total: $total_alerts"
        echo "  Buffered: $buffered_alerts"
        echo "  Processed: $processed_alerts"
        echo "  Failed: $failed_alerts"
    else
        print_error "Failed to get final buffer stats"
    fi
}

test_api_endpoints() {
    print_header "TESTING API ENDPOINTS"

    # Test 1: Health endpoint
    print_section "Test 1: Health Endpoint"
    response=$(curl -s -w "\n%{http_code}" "$WEBHOOK_URL/health")
    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" = "200" ]; then
        print_success "Health endpoint working"
    else
        print_error "Health endpoint failed: HTTP $http_code"
    fi

    # Test 2: Ready endpoint
    print_section "Test 2: Ready Endpoint"
    response=$(curl -s -w "\n%{http_code}" "$WEBHOOK_URL/ready")
    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        status=$(echo "$response_body" | jq -r '.status // "unknown"')
        temporal_connected=$(echo "$response_body" | jq -r '.temporal_connected // false')
        buffer_active=$(echo "$response_body" | jq -r '.buffer_manager_active // false')

        print_success "Ready endpoint working - Status: $status"
        print_info "Temporal connected: $temporal_connected"
        print_info "Buffer manager active: $buffer_active"
    else
        print_error "Ready endpoint failed: HTTP $http_code"
    fi

    # Test 3: Test alert endpoint
    print_section "Test 3: Test Alert Endpoint"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/test/alert" \
        -H "Content-Type: application/json" \
        -d '{
            "alert_name": "CrateDBContainerRestart",
            "namespace": "cratedb-prod",
            "pod": "test-pod",
            "region": "us-east-1"
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        cluster_context=$(echo "$response_body" | jq -r '.cluster_context // "unknown"')
        print_success "Test alert endpoint working - Cluster: $cluster_context"
    else
        print_error "Test alert endpoint failed: HTTP $http_code"
    fi
}

test_error_handling() {
    print_header "TESTING ERROR HANDLING"

    # Test 1: Invalid alert name
    print_section "Test 1: Invalid Alert Name"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{
            "version": "4",
            "receiver": "webhook",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "InvalidAlertName",
                        "namespace": "'$TEST_NAMESPACE'",
                        "pod": "'$TEST_POD'"
                    },
                    "annotations": {
                        "summary": "Invalid alert for testing"
                    },
                    "startsAt": "'$TIMESTAMP'"
                }
            ]
        }')

    http_code=$(echo "$response" | tail -n1)
    response_body=$(echo "$response" | sed '$d')

    if [ "$http_code" = "200" ]; then
        rejected_count=$(echo "$response_body" | jq -r '.rejected_count // 0')
        if [ "$rejected_count" -gt 0 ]; then
            print_success "Invalid alert correctly rejected"
        else
            print_error "Invalid alert was not rejected"
        fi
    else
        print_error "Unexpected HTTP code for invalid alert: $http_code"
    fi

    # Test 2: Malformed JSON
    print_section "Test 2: Malformed JSON"
    response=$(curl -s -w "\n%{http_code}" -X POST "$WEBHOOK_URL/webhook/alertmanager" \
        -H "Content-Type: application/json" \
        -d '{"invalid": "json"')

    http_code=$(echo "$response" | tail -n1)

    if [ "$http_code" = "422" ] || [ "$http_code" = "400" ]; then
        print_success "Malformed JSON correctly rejected with HTTP $http_code"
    else
        print_error "Malformed JSON handling failed: HTTP $http_code"
    fi
}

generate_test_report() {
    print_header "TEST REPORT SUMMARY"

    echo "Region Support and Alert Buffering Test Results"
    echo "Date: $(date)"
    echo "Webhook URL: $WEBHOOK_URL"
    echo ""
    echo "Test Categories:"
    echo "✓ Region-based cluster routing"
    echo "✓ Alert buffering functionality"
    echo "✓ API endpoints"
    echo "✓ Error handling"
    echo ""
    echo "Key Features Tested:"
    echo "- Region mapping (us-east-1, eastus, etc.)"
    echo "- Namespace fallback routing"
    echo "- Alert buffering when agent unavailable"
    echo "- Buffer statistics and monitoring"
    echo "- Manual buffer flushing"
    echo "- API endpoint functionality"
    echo "- Error handling and validation"
    echo ""
    echo "For detailed logs, review the output above."
}

main() {
    print_header "COMPREHENSIVE REGION & BUFFERING TEST SUITE"

    print_info "This script tests the new region support and alert buffering features"
    print_info "Webhook URL: $WEBHOOK_URL"
    print_info "Test timestamp: $TIMESTAMP"

    # Check prerequisites
    if ! command -v jq &> /dev/null; then
        print_error "jq is required but not installed. Please install jq first."
        exit 1
    fi

    if ! check_webhook_server; then
        exit 1
    fi

    # Run test suites
    test_region_routing
    test_buffer_functionality
    test_api_endpoints
    test_error_handling

    # Generate report
    generate_test_report

    print_header "TESTS COMPLETED"
    print_success "All test suites have been executed"
    print_info "Check the output above for detailed results"
    print_info "To run individual test suites, use the functions directly"
}

# Allow running individual test functions
if [ "$1" = "region" ]; then
    check_webhook_server && test_region_routing
elif [ "$1" = "buffer" ]; then
    check_webhook_server && test_buffer_functionality
elif [ "$1" = "api" ]; then
    check_webhook_server && test_api_endpoints
elif [ "$1" = "error" ]; then
    check_webhook_server && test_error_handling
else
    main
fi
