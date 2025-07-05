#!/usr/bin/env python3
"""
Test script that sends real Prometheus AlertManager webhooks to the FastAPI endpoint.

This script demonstrates the complete end-to-end flow:
1. Sends real AlertManager webhook payloads to the FastAPI server
2. Shows different alert types (CrateDB, Prometheus, complex names)
3. Generates real Temporal events you can see in the UI
4. Tests both specific activities and fallback mechanism

Prerequisites:
- Alert Watcher 2 application must be running: python -m src.alert_watcher.main
- Temporal server must be running: temporal server start-dev
- FastAPI server should be accessible at http://localhost:8000

This is the most realistic test as it simulates actual AlertManager behavior.
"""

import asyncio
import json
import sys
import time
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Any


def create_alertmanager_webhook(alerts: List[Dict[str, Any]], status: str = "firing") -> Dict[str, Any]:
    """Create a realistic AlertManager webhook payload."""
    # Get the first alert for group labels
    first_alert = alerts[0] if alerts else {}
    alertname = first_alert.get("labels", {}).get("alertname", "TestAlert")
    
    return {
        "version": "4",
        "groupKey": f"{{}}:{{alertname=\"{alertname}\"}}",
        "truncatedAlerts": 0,
        "status": status,
        "receiver": "webhook",
        "groupLabels": {
            "alertname": alertname
        },
        "commonLabels": {
            "alertname": alertname,
            "severity": "warning"
        },
        "commonAnnotations": {
            "summary": f"Test {alertname} alert group",
            "description": f"This is a test alert group for {alertname}"
        },
        "externalURL": "http://alertmanager:9093",
        "alerts": alerts
    }


def create_cratedb_alert() -> Dict[str, Any]:
    """Create a CrateDB alert (should use log_cratedb_alert activity)."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    return {
        "status": "firing",
        "labels": {
            "alertname": "CrateDB",
            "namespace": "cratedb-cluster",
            "pod": "cratedb-master-0",
            "severity": "critical",
            "instance": "cratedb-cluster-node-1:4200",
            "job": "cratedb-monitoring",
            "cluster": "production-cluster"
        },
        "annotations": {
            "summary": "CrateDB database connection issues",
            "description": "CrateDB cluster is experiencing connection timeouts. This may indicate network issues or database overload.",
            "runbook_url": "https://docs.cratedb.com/troubleshooting/connection-issues"
        },
        "startsAt": timestamp,
        "endsAt": None,
        "generatorURL": "http://prometheus:9090/graph?g0.expr=cratedb_cluster_health%20%3C%201&g0.tab=1",
        "fingerprint": f"cratedb-health-{int(time.time())}"
    }


def create_prometheus_alert() -> Dict[str, Any]:
    """Create a Prometheus alert (should use log_prometheus_alert activity)."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    return {
        "status": "firing",
        "labels": {
            "alertname": "Prometheus",
            "namespace": "monitoring",
            "pod": "prometheus-server-0",
            "severity": "warning",
            "instance": "prometheus-server:9090",
            "job": "prometheus-monitoring"
        },
        "annotations": {
            "summary": "Prometheus scrape target down",
            "description": "Prometheus is unable to scrape metrics from one or more targets. Check target health and network connectivity.",
            "runbook_url": "https://prometheus.io/docs/prometheus/troubleshooting"
        },
        "startsAt": timestamp,
        "endsAt": None,
        "generatorURL": "http://prometheus:9090/graph?g0.expr=up%20%3D%3D%200&g0.tab=1",
        "fingerprint": f"prometheus-scrape-{int(time.time())}"
    }


def create_node_alert() -> Dict[str, Any]:
    """Create a Node alert (should use log_node_alert activity)."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    return {
        "status": "firing",
        "labels": {
            "alertname": "Node",
            "namespace": "kube-system",
            "pod": "node-exporter-xyz",
            "severity": "warning",
            "instance": "worker-node-1:9100",
            "job": "node-exporter",
            "node": "worker-node-1"
        },
        "annotations": {
            "summary": "High CPU usage on node",
            "description": "Node worker-node-1 is experiencing high CPU usage (>90%) for more than 5 minutes.",
            "runbook_url": "https://kubernetes.io/docs/tasks/debug-application-cluster/debug-cluster"
        },
        "startsAt": timestamp,
        "endsAt": None,
        "generatorURL": "http://prometheus:9090/graph?g0.expr=node_cpu_usage%20%3E%200.9&g0.tab=1",
        "fingerprint": f"node-cpu-{int(time.time())}"
    }


def create_complex_alert() -> Dict[str, Any]:
    """Create a complex alert name (should use log_alert fallback)."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    return {
        "status": "firing",
        "labels": {
            "alertname": "CrateDBContainerRestart",
            "namespace": "cratedb-cluster",
            "pod": "cratedb-data-0",
            "severity": "critical",
            "instance": "cratedb-cluster-node-2:4200",
            "job": "cratedb-monitoring",
            "container": "cratedb",
            "restart_count": "3"
        },
        "annotations": {
            "summary": "CrateDB container has restarted multiple times",
            "description": "The CrateDB container in pod cratedb-data-0 has restarted 3 times in the last 10 minutes. This indicates a potential issue with the database or resource constraints.",
            "runbook_url": "https://docs.cratedb.com/troubleshooting/container-restarts"
        },
        "startsAt": timestamp,
        "endsAt": None,
        "generatorURL": "http://prometheus:9090/graph?g0.expr=increase(container_restarts_total%7Bcontainer%3D%22cratedb%22%7D%5B10m%5D)%20%3E%202&g0.tab=1",
        "fingerprint": f"cratedb-restart-{int(time.time())}"
    }


def create_custom_alert() -> Dict[str, Any]:
    """Create a custom alert (should use log_alert fallback)."""
    timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    
    return {
        "status": "firing",
        "labels": {
            "alertname": "DatabaseConnectionPoolExhaustion",
            "namespace": "application",
            "pod": "webapp-backend-2",
            "severity": "critical",
            "instance": "webapp-backend-2:8080",
            "job": "webapp-monitoring",
            "service": "user-service"
        },
        "annotations": {
            "summary": "Database connection pool exhausted",
            "description": "The application has exhausted its database connection pool. New requests are being queued or rejected.",
            "runbook_url": "https://docs.company.com/troubleshooting/database-connections"
        },
        "startsAt": timestamp,
        "endsAt": None,
        "generatorURL": "http://prometheus:9090/graph?g0.expr=db_connections_active%20%3E%3D%20db_connections_max&g0.tab=1",
        "fingerprint": f"db-pool-{int(time.time())}"
    }


async def send_webhook(payload: Dict[str, Any], webhook_url: str = "http://localhost:8000/webhook/alertmanager") -> bool:
    """Send webhook payload to the FastAPI endpoint."""
    try:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Alertmanager/0.24.0"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=10.0
            )
        
        if response.status_code == 200:
            return True
        else:
            print(f"❌ HTTP {response.status_code}: {response.text}")
            return False
            
    except httpx.ConnectError:
        print(f"❌ Connection failed to {webhook_url}")
        print("   Make sure Alert Watcher 2 is running: python -m src.alert_watcher.main")
        return False
    except httpx.TimeoutException:
        print(f"❌ Request timeout to {webhook_url}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


async def test_webhook_flow():
    """Test the complete webhook to Temporal flow."""
    print("🧪 Testing Webhook to Temporal Flow")
    print("="*60)
    
    webhook_url = "http://localhost:8000/webhook/alertmanager"
    
    # Test cases: (alert_creator, expected_activity, description)
    test_cases = [
        (create_cratedb_alert, "log_cratedb_alert", "CrateDB database alert"),
        (create_prometheus_alert, "log_prometheus_alert", "Prometheus monitoring alert"),
        (create_node_alert, "log_node_alert", "Kubernetes node alert"),
        (create_complex_alert, "log_alert", "Complex alert name (fallback)"),
        (create_custom_alert, "log_alert", "Custom alert name (fallback)")
    ]
    
    print(f"📡 Target webhook URL: {webhook_url}")
    print(f"🎯 Expected workflow name pattern: alert-watcher2")
    print()
    
    all_success = True
    
    for i, (alert_creator, expected_activity, description) in enumerate(test_cases, 1):
        print(f"📨 Test {i}/5: {description}")
        print(f"   Expected activity: {expected_activity}")
        
        # Create alert
        alert = alert_creator()
        alertname = alert["labels"]["alertname"]
        
        # Create webhook payload
        webhook_payload = create_alertmanager_webhook([alert])
        
        print(f"   Alert name: {alertname}")
        print(f"   Alert ID: {alert['fingerprint']}")
        
        # Send webhook
        success = await send_webhook(webhook_payload, webhook_url)
        
        if success:
            print(f"   ✅ Webhook sent successfully")
        else:
            print(f"   ❌ Webhook failed")
            all_success = False
        
        # Wait between requests
        await asyncio.sleep(2)
        print()
    
    return all_success


async def test_health_endpoint():
    """Test the health endpoint."""
    print("🔍 Testing Health Endpoint")
    print("="*30)
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("http://localhost:8000/health", timeout=5.0)
        
        if response.status_code == 200:
            health_data = response.json()
            print("✅ Health endpoint accessible")
            print(f"   Status: {health_data.get('status', 'unknown')}")
            return True
        else:
            print(f"❌ Health endpoint returned {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Health endpoint failed: {e}")
        return False


async def test_batch_alerts():
    """Test sending multiple alerts in a single webhook (realistic scenario)."""
    print("📦 Testing Batch Alerts (Multiple alerts in one webhook)")
    print("="*60)
    
    # Create multiple alerts for the same webhook call
    alerts = [
        create_cratedb_alert(),
        create_prometheus_alert(),
        create_node_alert()
    ]
    
    # Modify alert names to show they're part of a batch
    for i, alert in enumerate(alerts):
        alert["labels"]["batch_id"] = f"batch-test-{int(time.time())}"
        alert["labels"]["alert_sequence"] = str(i + 1)
    
    webhook_payload = create_alertmanager_webhook(alerts)
    
    print(f"📨 Sending batch of {len(alerts)} alerts:")
    for i, alert in enumerate(alerts, 1):
        print(f"   {i}. {alert['labels']['alertname']} (ID: {alert['fingerprint']})")
    
    success = await send_webhook(webhook_payload)
    
    if success:
        print("✅ Batch webhook sent successfully")
        print("   Each alert should be processed individually in Temporal")
        return True
    else:
        print("❌ Batch webhook failed")
        return False


async def main():
    """Main test function."""
    print("🧪 Alert Watcher 2 - Webhook to Temporal Test")
    print("="*80)
    print("This script sends real AlertManager webhooks to the FastAPI endpoint")
    print("and generates actual Temporal events you can see in the UI.")
    print()
    
    print("📋 Prerequisites:")
    print("1. ✅ Temporal server running: temporal server start-dev")
    print("2. ✅ Alert Watcher 2 running: python -m src.alert_watcher.main")
    print("3. ✅ FastAPI server accessible at http://localhost:8000")
    print()
    
    # Test health endpoint first
    health_ok = await test_health_endpoint()
    print()
    
    if not health_ok:
        print("❌ Cannot proceed - health endpoint not accessible")
        print("   Please start Alert Watcher 2: python -m src.alert_watcher.main")
        return False
    
    # Test individual alerts
    individual_ok = await test_webhook_flow()
    
    # Test batch alerts
    batch_ok = await test_batch_alerts()
    
    print("\n" + "="*80)
    print("🎯 TEMPORAL UI INSTRUCTIONS:")
    print("="*80)
    print("1. Open Temporal UI: http://localhost:8233")
    print("2. Look for workflow: alert-watcher2")
    print("3. Click on the workflow to see details")
    print("4. Check the 'Activities' section - you should see:")
    print("   • log_cratedb_alert (for CrateDB alerts)")
    print("   • log_prometheus_alert (for Prometheus alerts)")
    print("   • log_node_alert (for Node alerts)")
    print("   • log_alert (for CrateDBContainerRestart and custom alerts)")
    print("5. Click on any activity to see:")
    print("   • Input: Complete alert data from webhook")
    print("   • Output: ActivityResult with success=true")
    print("   • Execution time and status")
    print()
    print("🔍 What to look for:")
    print("• Activity names clearly show which alert type was processed")
    print("• Complex alert names use the fallback 'log_alert' activity")
    print("• All activities should show as COMPLETED")
    print("• Input data contains the full AlertManager webhook payload")
    
    print("\n📊 Test Results:")
    print("="*30)
    if health_ok:
        print("✅ Health endpoint test passed")
    else:
        print("❌ Health endpoint test failed")
    
    if individual_ok:
        print("✅ Individual alerts test passed")
    else:
        print("❌ Individual alerts test failed")
    
    if batch_ok:
        print("✅ Batch alerts test passed")
    else:
        print("❌ Batch alerts test failed")
    
    overall_success = health_ok and individual_ok and batch_ok
    
    if overall_success:
        print("\n🎉 ALL TESTS PASSED!")
        print("✅ Webhooks sent successfully to FastAPI endpoint")
        print("✅ Should see activities in Temporal UI with new naming system")
        print("✅ Both specific activities and fallback mechanism tested")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("Please check the Alert Watcher 2 application status")
    
    print(f"\n🔗 Next steps:")
    print(f"• Check Temporal UI: http://localhost:8233")
    print(f"• Check application logs for alert processing")
    print(f"• Verify activity names match expected pattern")
    
    return overall_success


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Script interrupted by user")
        print("Check Temporal UI to see any events that were generated")
        sys.exit(0)