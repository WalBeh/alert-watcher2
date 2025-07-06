#!/usr/bin/env python3
"""
Test script for the simplified CrateDB alert system.

This script tests the webhook endpoint with the two supported CrateDB alert types:
- CrateDBContainerRestart
- CrateDBCloudNotResponsive

Usage:
    python test_simplified_cratedb.py
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any

import httpx


# Base URL for the alert watcher service
BASE_URL = "http://localhost:8000"


def create_test_alert(alert_name: str, namespace: str = "cratedb-test", pod: str = "cratedb-pod-1") -> Dict[str, Any]:
    """
    Create a test alert payload for AlertManager webhook.
    
    Args:
        alert_name: Name of the alert (CrateDBContainerRestart or CrateDBCloudNotResponsive)
        namespace: Kubernetes namespace
        pod: Pod name
        
    Returns:
        AlertManager webhook payload
    """
    current_time = datetime.now(timezone.utc)
    
    return {
        "version": "4",
        "groupKey": f"{alert_name}:{namespace}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "alert-watcher2",
        "groupLabels": {
            "alertname": alert_name,
            "namespace": namespace
        },
        "commonLabels": {
            "alertname": alert_name,
            "namespace": namespace,
            "pod": pod
        },
        "commonAnnotations": {
            "summary": f"CrateDB {alert_name} alert",
            "description": f"CrateDB alert {alert_name} triggered for pod {pod} in namespace {namespace}"
        },
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": alert_name,
                    "namespace": namespace,
                    "pod": pod,
                    "kube_context": "test-cluster",
                    "sts": "cratedb-cluster",
                    "severity": "critical",
                    "instance": f"{pod}:4200",
                    "job": "cratedb"
                },
                "annotations": {
                    "summary": f"CrateDB {alert_name} alert",
                    "description": f"CrateDB alert {alert_name} triggered for pod {pod} in namespace {namespace}",
                    "runbook_url": "https://docs.cratedb.com/troubleshooting"
                },
                "startsAt": current_time.isoformat(),
                "endsAt": None,
                "generatorURL": f"http://prometheus:9090/graph?g0.expr=up{{job%3D%22cratedb%22}}&g0.tab=1",
                "fingerprint": f"test-{alert_name}-{int(time.time())}"
            }
        ]
    }


async def test_health_endpoint():
    """Test the health endpoint."""
    print("Testing health endpoint...")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/health")
            print(f"Health check status: {response.status_code}")
            print(f"Health response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            print(f"Health check failed: {e}")
            return False


async def test_readiness_endpoint():
    """Test the readiness endpoint."""
    print("\nTesting readiness endpoint...")
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{BASE_URL}/ready")
            print(f"Readiness check status: {response.status_code}")
            print(f"Readiness response: {response.json()}")
            return response.status_code == 200
        except Exception as e:
            print(f"Readiness check failed: {e}")
            return False


async def test_cratedb_alert(alert_name: str, namespace: str = "cratedb-test", pod: str = "cratedb-pod-1"):
    """
    Test sending a CrateDB alert to the webhook.
    
    Args:
        alert_name: Name of the alert to test
        namespace: Kubernetes namespace
        pod: Pod name
    """
    print(f"\nTesting {alert_name} alert...")
    
    # Create test alert payload
    alert_payload = create_test_alert(alert_name, namespace, pod)
    
    print(f"Alert payload:")
    print(json.dumps(alert_payload, indent=2))
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/webhook/alertmanager",
                json=alert_payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response body: {json.dumps(response.json(), indent=2)}")
            
            if response.status_code in [200, 207]:
                print(f"✅ {alert_name} alert sent successfully!")
                return True
            else:
                print(f"❌ {alert_name} alert failed with status {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Error sending {alert_name} alert: {e}")
            return False


async def test_unsupported_alert():
    """Test sending an unsupported alert type."""
    print("\nTesting unsupported alert (should be rejected)...")
    
    # Create test alert with unsupported type
    alert_payload = create_test_alert("UnsupportedAlert", "test-namespace", "test-pod")
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/webhook/alertmanager",
                json=alert_payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response body: {json.dumps(response.json(), indent=2)}")
            
            response_data = response.json()
            if response_data.get("rejected_count", 0) > 0:
                print("✅ Unsupported alert correctly rejected!")
                return True
            else:
                print("❌ Unsupported alert was not rejected")
                return False
                
        except Exception as e:
            print(f"❌ Error testing unsupported alert: {e}")
            return False


async def test_batch_alerts():
    """Test sending multiple alerts in a batch."""
    print("\nTesting batch alerts...")
    
    current_time = datetime.now(timezone.utc)
    
    # Create batch payload with both supported alerts
    batch_payload = {
        "version": "4",
        "groupKey": "batch-test",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "alert-watcher2",
        "groupLabels": {},
        "commonLabels": {},
        "commonAnnotations": {},
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "CrateDBContainerRestart",
                    "namespace": "cratedb-prod",
                    "pod": "cratedb-prod-1",
                    "severity": "critical"
                },
                "annotations": {
                    "summary": "CrateDB Container Restart",
                    "description": "CrateDB container has restarted"
                },
                "startsAt": current_time.isoformat(),
                "endsAt": None,
                "fingerprint": f"batch-restart-{int(time.time())}"
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "CrateDBCloudNotResponsive",
                    "namespace": "cratedb-prod",
                    "pod": "cratedb-prod-2",
                    "severity": "critical"
                },
                "annotations": {
                    "summary": "CrateDB Cloud Not Responsive",
                    "description": "CrateDB cloud is not responsive"
                },
                "startsAt": current_time.isoformat(),
                "endsAt": None,
                "fingerprint": f"batch-cloud-{int(time.time())}"
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "UnsupportedAlert",
                    "namespace": "test",
                    "pod": "test-pod",
                    "severity": "warning"
                },
                "annotations": {
                    "summary": "Unsupported Alert",
                    "description": "This should be rejected"
                },
                "startsAt": current_time.isoformat(),
                "endsAt": None,
                "fingerprint": f"batch-unsupported-{int(time.time())}"
            }
        ]
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/webhook/alertmanager",
                json=batch_payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Response status: {response.status_code}")
            print(f"Response body: {json.dumps(response.json(), indent=2)}")
            
            response_data = response.json()
            processed_count = response_data.get("processed_count", 0)
            rejected_count = response_data.get("rejected_count", 0)
            
            if processed_count == 2 and rejected_count == 1:
                print("✅ Batch alerts processed correctly!")
                return True
            else:
                print(f"❌ Batch alerts not processed correctly (processed: {processed_count}, rejected: {rejected_count})")
                return False
                
        except Exception as e:
            print(f"❌ Error testing batch alerts: {e}")
            return False


async def main():
    """Main test function."""
    print("=" * 60)
    print("CrateDB Alert Watcher 2 - Simplified Test Suite")
    print("=" * 60)
    
    # Test results
    results = []
    
    # Test health and readiness
    health_ok = await test_health_endpoint()
    results.append(("Health Check", health_ok))
    
    readiness_ok = await test_readiness_endpoint()
    results.append(("Readiness Check", readiness_ok))
    
    if not (health_ok and readiness_ok):
        print("\n❌ Service is not healthy. Please check if Alert Watcher 2 is running.")
        print("To start the service:")
        print("1. Start Temporal: temporal server start-dev")
        print("2. Start Alert Watcher 2: python -m src.alert_watcher.main")
        return
    
    # Test supported alerts
    restart_ok = await test_cratedb_alert("CrateDBContainerRestart", "cratedb-dev", "cratedb-dev-1")
    results.append(("CrateDBContainerRestart Alert", restart_ok))
    
    # Wait a bit between tests
    await asyncio.sleep(2)
    
    cloud_ok = await test_cratedb_alert("CrateDBCloudNotResponsive", "cratedb-staging", "cratedb-staging-1")
    results.append(("CrateDBCloudNotResponsive Alert", cloud_ok))
    
    # Wait a bit between tests
    await asyncio.sleep(2)
    
    # Test unsupported alert
    unsupported_ok = await test_unsupported_alert()
    results.append(("Unsupported Alert Rejection", unsupported_ok))
    
    # Wait a bit between tests
    await asyncio.sleep(2)
    
    # Test batch alerts
    batch_ok = await test_batch_alerts()
    results.append(("Batch Alerts", batch_ok))
    
    # Print summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{test_name:<40} {status}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The simplified CrateDB alert system is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the service logs and Temporal UI.")
    
    print("\nTo monitor the workflow executions:")
    print("1. Open Temporal UI: http://localhost:8233")
    print("2. Look for workflows with names like 'CrateDBContainerRestart-<namespace>-<uuid>'")
    print("3. Check the activity executions for hemako command placeholders")


if __name__ == "__main__":
    asyncio.run(main())