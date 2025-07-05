#!/usr/bin/env python3
"""
Simple verification script to test the alert processing system.

This script sends a single test alert to verify the system is working.
"""

import asyncio
import json
import time
from datetime import datetime, UTC

import httpx


async def send_test_alert():
    """Send a simple test alert to verify the system is working."""
    
    # Create a minimal test alert payload
    test_payload = {
        "version": "4",
        "groupKey": "{}:{alertname=\"TestAlert\"}",
        "truncatedAlerts": 0,
        "status": "firing",
        "receiver": "webhook",
        "groupLabels": {
            "alertname": "TestAlert"
        },
        "commonLabels": {
            "alertname": "TestAlert",
            "namespace": "test",
            "severity": "info"
        },
        "commonAnnotations": {
            "summary": "Test alert for verification",
            "description": "This is a test alert to verify the system is working"
        },
        "externalURL": "http://alertmanager:9093",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "TestAlert",
                    "namespace": "test",
                    "pod": "test-pod",
                    "severity": "info"
                },
                "annotations": {
                    "summary": "Test alert for verification",
                    "description": "This is a test alert to verify the system is working"
                },
                "startsAt": datetime.now(UTC).isoformat(),
                "endsAt": None,
                "generatorURL": "http://test/verify",
                "fingerprint": "test123"
            }
        ]
    }
    
    print("🚀 Sending test alert to verify system is working...")
    print(f"📊 Test payload: {json.dumps(test_payload, indent=2)}")
    
    try:
        async with httpx.AsyncClient() as client:
            # Test health endpoint first
            print("\n🔍 Checking health endpoint...")
            health_response = await client.get("http://localhost:8000/health", timeout=5.0)
            
            if health_response.status_code == 200:
                print("✅ Health endpoint OK")
                print(f"   Response: {health_response.json()}")
            else:
                print(f"❌ Health endpoint failed: {health_response.status_code}")
                return False
            
            # Send test alert
            print("\n📡 Sending test alert...")
            alert_response = await client.post(
                "http://localhost:8000/webhook/alertmanager",
                json=test_payload,
                timeout=10.0
            )
            
            if alert_response.status_code == 200:
                result = alert_response.json()
                print("✅ Test alert sent successfully!")
                print(f"   Correlation ID: {result.get('correlation_id')}")
                print(f"   Processed alerts: {result.get('processed_count', 0)}")
                return True
            else:
                print(f"❌ Test alert failed: {alert_response.status_code}")
                print(f"   Response: {alert_response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        return False


async def main():
    """Main verification function."""
    print("🔧 Alert Watcher 2 - System Verification")
    print("=" * 50)
    
    success = await send_test_alert()
    
    if success:
        print("\n🎉 SUCCESS: System is working correctly!")
        print("💡 Check the application logs to see the processed alert data structure.")
        print("🌐 You can also check the Temporal UI to see the workflow activity.")
    else:
        print("\n💥 FAILURE: System is not working properly.")
        print("🔧 Make sure the application is running with:")
        print("   uv run python -m src.alert_watcher.main")
        print("🏃 And that Temporal server is running with:")
        print("   temporal server start-dev")


if __name__ == "__main__":
    asyncio.run(main())