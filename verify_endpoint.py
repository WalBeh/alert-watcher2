#!/usr/bin/env python3
"""
Quick verification script for the webhook endpoint.

This script checks that the correct webhook endpoint is accessible
and documents the correct URL for future reference.
"""

import asyncio
import httpx
import sys


async def verify_endpoints():
    """Verify webhook endpoints are accessible."""
    print("🔍 Verifying Alert Watcher 2 Endpoints")
    print("=" * 50)
    
    base_url = "http://localhost:8000"
    
    endpoints_to_test = [
        ("/health", "Health check endpoint"),
        ("/webhook/alertmanager", "AlertManager webhook endpoint (CORRECT)"),
        ("/webhook", "Generic webhook endpoint (WRONG - should return 404)"),
        ("/docs", "FastAPI documentation"),
        ("/", "Root endpoint")
    ]
    
    async with httpx.AsyncClient() as client:
        for endpoint, description in endpoints_to_test:
            url = f"{base_url}{endpoint}"
            
            try:
                response = await client.get(url, timeout=5.0)
                status = response.status_code
                
                if endpoint == "/webhook":
                    # This should return 404 (Method Not Allowed or Not Found)
                    if status in [404, 405]:
                        print(f"✅ {endpoint:<25} - {status} (Expected) - {description}")
                    else:
                        print(f"⚠️  {endpoint:<25} - {status} (Unexpected) - {description}")
                elif status == 200:
                    print(f"✅ {endpoint:<25} - {status} (OK) - {description}")
                else:
                    print(f"❌ {endpoint:<25} - {status} (Error) - {description}")
                    
            except httpx.ConnectError:
                print(f"❌ {endpoint:<25} - Connection failed - {description}")
            except Exception as e:
                print(f"❌ {endpoint:<25} - {str(e)} - {description}")
    
    print("\n📋 Summary:")
    print("✅ Correct webhook URL: http://localhost:8000/webhook/alertmanager")
    print("❌ Wrong webhook URL:   http://localhost:8000/webhook")
    print("\n🧪 Test command:")
    print("python test_webhook_alerts.py")


if __name__ == "__main__":
    try:
        asyncio.run(verify_endpoints())
    except KeyboardInterrupt:
        print("\n⚠️  Verification interrupted")
        sys.exit(0)