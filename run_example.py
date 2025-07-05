#!/usr/bin/env python3
"""
Simple script to demonstrate the Alert Watcher 2 simplified system.

This script shows how to:
1. Start the system
2. Send test alerts
3. View the logged alert data structures

Usage:
    python run_example.py
"""

import asyncio
import json
import sys
import time
from datetime import datetime
from typing import Dict, Any

import httpx


def create_test_alerts() -> Dict[str, Any]:
    """Create test AlertManager webhook payload with two different alert types."""
    return {
        "version": "4",
        "groupKey": "{}:{alertname=\"CrateDBCloudNotResponsive\"}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "webhook-test",
        "groupLabels": {
            "alertname": "CrateDBCloudNotResponsive"
        },
        "commonLabels": {
            "alertname": "CrateDBCloudNotResponsive",
            "namespace": "cratedb-cloud",
            "severity": "critical"
        },
        "commonAnnotations": {
            "summary": "CrateDB Cloud issues detected",
            "description": "Multiple CrateDB instances experiencing problems"
        },
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "CrateDBCloudNotResponsive",
                    "namespace": "cratedb-cloud-prod",
                    "pod": "crate-data-0",
                    "kube_context": "prod-cluster-west-1",
                    "sts": "crate-data",
                    "severity": "critical",
                    "instance": "crate-data-0.crate-data.cratedb-cloud-prod.svc.cluster.local:4200",
                    "job": "cratedb-monitoring",
                    "cluster": "prod-west-1",
                    "datacenter": "us-west-1",
                    "environment": "production"
                },
                "annotations": {
                    "summary": "CrateDB Cloud instance is not responsive",
                    "description": "The CrateDB instance crate-data-0 in production namespace cratedb-cloud-prod is not responding to health checks for more than 5 minutes",
                    "runbook_url": "https://docs.cratedb.com/troubleshooting/not-responsive",
                    "dashboard_url": "https://grafana.company.com/d/cratedb-overview",
                    "escalation_policy": "critical-database-issues"
                },
                "startsAt": datetime.fromtimestamp(time.time()).isoformat() + "Z",
                "endsAt": None,
                "generatorURL": "http://prometheus:9090/graph?g0.expr=up%7Bjob%3D%22cratedb-monitoring%22%7D+%3D%3D+0&g0.tab=1",
                "fingerprint": "abc123def456789"
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "CrateDBContainerRestart",
                    "namespace": "cratedb-cloud-staging",
                    "pod": "crate-data-1",
                    "kube_context": "staging-cluster-east-1",
                    "sts": "crate-data",
                    "severity": "warning",
                    "instance": "crate-data-1.crate-data.cratedb-cloud-staging.svc.cluster.local:4200",
                    "job": "cratedb-monitoring",
                    "cluster": "staging-east-1",
                    "datacenter": "us-east-1",
                    "environment": "staging",
                    "restart_count": "3"
                },
                "annotations": {
                    "summary": "CrateDB container restarted multiple times",
                    "description": "The CrateDB container crate-data-1 in staging namespace cratedb-cloud-staging has restarted 3 times in the last 10 minutes",
                    "runbook_url": "https://docs.cratedb.com/troubleshooting/container-restart",
                    "dashboard_url": "https://grafana.company.com/d/cratedb-restarts",
                    "escalation_policy": "database-stability-issues"
                },
                "startsAt": datetime.fromtimestamp(time.time()).isoformat() + "Z",
                "endsAt": None,
                "generatorURL": "http://prometheus:9090/graph?g0.expr=changes%28kube_pod_container_status_restarts_total%5B10m%5D%29+%3E+2&g0.tab=1",
                "fingerprint": "def456ghi789abc"
            }
        ]
    }


async def check_service_health(base_url: str = "http://localhost:8000") -> bool:
    """Check if the alert watcher service is running."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}/health", timeout=5.0)
            return response.status_code == 200
    except Exception:
        return False


async def send_test_alerts(base_url: str = "http://localhost:8000"):
    """Send test alerts to the webhook endpoint."""
    test_payload = create_test_alerts()
    
    print("📤 Sending test alerts to webhook...")
    print(f"   URL: {base_url}/webhook/alertmanager")
    print(f"   Alert count: {len(test_payload['alerts'])}")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base_url}/webhook/alertmanager",
                json=test_payload,
                timeout=30.0
            )
            
            if response.status_code in [200, 207]:
                result = response.json()
                print("✅ Webhook request successful!")
                print(f"   Status: {response.status_code}")
                print(f"   Processed alerts: {result.get('processed_count', 0)}")
                print(f"   Correlation ID: {result.get('correlation_id')}")
                
                if result.get('errors'):
                    print(f"   Errors: {len(result['errors'])}")
                    for error in result['errors']:
                        print(f"     - {error}")
                
                return True
            else:
                print(f"❌ Webhook request failed with status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Error sending webhook: {e}")
        return False


def print_expected_output():
    """Print what users should expect to see in the logs."""
    print("\n" + "="*80)
    print("EXPECTED LOG OUTPUT")
    print("="*80)
    print("You should see detailed JSON logs like this in the application console:")
    print()
    print("2025-01-01T12:00:00Z [info] Alert received and logged")
    print("  alert_id=CrateDBCloudNotResponsive-cratedb-cloud-prod-crate-data-0-uuid")
    print("  alert_name=CrateDBCloudNotResponsive")
    print("  namespace=cratedb-cloud-prod")
    print("  pod=crate-data-0")
    print("  full_alert_data={...complete alert structure...}")
    print()
    print("================================================================================")
    print("ALERT DATA STRUCTURE:")
    print("================================================================================")
    print("{")
    print('  "timestamp": "2025-01-01T12:00:00Z",')
    print('  "event": "alert_received",')
    print('  "alert_id": "CrateDBCloudNotResponsive-cratedb-cloud-prod-crate-data-0-uuid",')
    print('  "processing_id": "correlation-uuid",')
    print('  "alert_data": {')
    print('    "status": "firing",')
    print('    "labels": {')
    print('      "alertname": "CrateDBCloudNotResponsive",')
    print('      "namespace": "cratedb-cloud-prod",')
    print('      "pod": "crate-data-0",')
    print('      "kube_context": "prod-cluster-west-1",')
    print('      "sts": "crate-data",')
    print('      "severity": "critical",')
    print('      "instance": "crate-data-0.crate-data.cratedb-cloud-prod.svc.cluster.local:4200",')
    print('      "job": "cratedb-monitoring",')
    print('      "cluster": "prod-west-1",')
    print('      "datacenter": "us-west-1",')
    print('      "environment": "production"')
    print('    },')
    print('    "annotations": {')
    print('      "summary": "CrateDB Cloud instance is not responsive",')
    print('      "description": "The CrateDB instance crate-data-0...",')
    print('      "runbook_url": "https://docs.cratedb.com/troubleshooting/not-responsive",')
    print('      "dashboard_url": "https://grafana.company.com/d/cratedb-overview",')
    print('      "escalation_policy": "critical-database-issues"')
    print('    },')
    print('    "startsAt": "2025-01-01T12:00:00Z",')
    print('    "endsAt": null,')
    print('    "generatorURL": "http://prometheus:9090/graph?...",')
    print('    "fingerprint": "abc123def456789"')
    print('  }')
    print('}')
    print("================================================================================")
    print()


def print_instructions():
    """Print usage instructions."""
    print("🚀 Alert Watcher 2 - Simplified System Test")
    print("="*50)
    print()
    print("This script will:")
    print("1. Check if the Alert Watcher service is running")
    print("2. Send test AlertManager webhooks")
    print("3. Show you what to expect in the logs")
    print()
    print("PREREQUISITES:")
    print("- Alert Watcher 2 service running on http://localhost:8000")
    print("- Temporal server running (for workflow processing)")
    print()
    print("TO START THE SERVICE:")
    print("  Terminal 1: temporal server start-dev")
    print("  Terminal 2: uv run python -m src.alert_watcher.main")
    print("  Terminal 3: uv run python run_example.py")
    print()


async def main():
    """Main test execution."""
    print_instructions()
    
    # Check if service is running
    print("🔍 Checking if Alert Watcher service is running...")
    if not await check_service_health():
        print("❌ Alert Watcher service is not running!")
        print("   Please start the service first:")
        print("   uv run python -m src.alert_watcher.main")
        sys.exit(1)
    
    print("✅ Alert Watcher service is running!")
    
    # Send test alerts
    print("\n" + "="*50)
    success = await send_test_alerts()
    
    if success:
        print("\n✅ Test alerts sent successfully!")
        print("\n💡 What happens next:")
        print("1. The webhook receives the AlertManager payload")
        print("2. Each alert is sent as a signal to the Temporal workflow")
        print("3. The workflow calls the log_alert activity")
        print("4. The activity logs the complete alert JSON structure")
        print("5. Check the application console for detailed logs")
        
        print_expected_output()
        
        print("\n🎯 KEY INSIGHTS TO LOOK FOR:")
        print("- How AlertManager structures the webhook payload")
        print("- What labels are available for each alert type")
        print("- How annotations provide additional context")
        print("- The difference between labels and annotations")
        print("- Which fields you need for 'hemako jfr collect' commands")
        
        print("\n🔄 NEXT STEPS:")
        print("1. Examine the logged alert structures")
        print("2. Identify the labels needed for JFR collection")
        print("3. Build 'hemako jfr collect' commands from the labels")
        print("4. Add back specific alert processing logic")
        
    else:
        print("\n❌ Test failed! Check the Alert Watcher service logs.")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())