#!/usr/bin/env python3
"""
Demo script showing the new Alert Watcher 2 naming system.

This script demonstrates:
1. How the workflow name has changed to "alert-watcher2"
2. How activities are now named based on alert types
3. How the system handles different alert types
4. How to customize the workflow name
"""

import asyncio
import json
import sys
from datetime import datetime
from typing import Dict, Any

# Add the src directory to the path for imports
sys.path.insert(0, 'src')

from alert_watcher.config import config
from alert_watcher.models import Alert, AlertLabel, AlertAnnotation, AlertProcessingSignal
from alert_watcher.activities import log_alert, log_cratedb_alert, log_prometheus_alert


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "="*80)
    print(f"📋 {title}")
    print("="*80)


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n🔍 {title}")
    print("-" * 60)


def demo_workflow_naming():
    """Demonstrate the workflow naming changes."""
    print_section("Workflow Naming Demo")
    
    # Show current workflow name
    print(f"Current workflow ID: {config.workflow_id}")
    print(f"✅ This is the new default name (changed from 'alert-processor')")
    
    # Show how easy it is to change
    print("\n🔧 Easy Configuration:")
    print("   • Environment variable: WORKFLOW_ID=my-custom-name")
    print("   • Config file: workflow_id=my-custom-name")
    print("   • Programmatically: config.workflow_id = 'my-custom-name'")
    
    # Demo changing it
    original_id = config.workflow_id
    config.workflow_id = "production-alert-watcher"
    print(f"\n🔄 Changed to: {config.workflow_id}")
    
    # Restore original
    config.workflow_id = original_id
    print(f"🔄 Restored to: {config.workflow_id}")


def demo_activity_naming():
    """Demonstrate the activity naming changes."""
    print_section("Activity Naming Demo")
    
    # Show the naming pattern
    print("🏷️  New Activity Naming Pattern:")
    print("   Alert Name → Activity Name")
    print("   ─────────────────────────────")
    
    alert_examples = [
        ("CrateDB", "log_cratedb_alert"),
        ("Prometheus", "log_prometheus_alert"),
        ("Node", "log_node_alert"),
        ("Pod", "log_pod_alert"),
        ("Service", "log_service_alert"),
        ("CustomAlert", "log_customalert_alert")
    ]
    
    for alert_name, activity_name in alert_examples:
        print(f"   {alert_name:<12} → {activity_name}")
    
    print("\n📝 Activity Function Registration:")
    activities = [
        "log_alert (generic fallback)",
        "log_cratedb_alert",
        "log_prometheus_alert", 
        "log_node_alert",
        "log_pod_alert",
        "log_service_alert"
    ]
    
    for activity in activities:
        print(f"   ✅ {activity}")


def create_demo_alert(alert_name: str, description: str) -> AlertProcessingSignal:
    """Create a demo alert for testing."""
    labels = AlertLabel(
        alertname=alert_name,
        namespace="demo-namespace",
        pod="demo-pod",
        severity="warning",
        instance="demo-instance"
    )
    
    annotations = AlertAnnotation(
        summary=f"Demo {alert_name} alert",
        description=description
    )
    
    alert_data = Alert(
        status="firing",
        labels=labels,
        annotations=annotations,
        startsAt=datetime.now(),
        endsAt=None,
        generatorURL="http://demo-generator",
        fingerprint="demo-fingerprint"
    )
    
    return AlertProcessingSignal(
        alert_id=f"demo-{alert_name.lower()}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        alert_data=alert_data,
        processing_id=f"demo-processing-{alert_name.lower()}"
    )


def demo_alert_processing():
    """Demonstrate how different alert types are processed."""
    print_section("Alert Processing Demo")
    
    # Create demo alerts
    demo_alerts = [
        ("CrateDB", "Database connection timeout detected"),
        ("Prometheus", "High memory usage on monitoring server"),
        ("Node", "Kubernetes node experiencing high CPU load"),
        ("CustomAlert", "This is a custom alert type for demonstration")
    ]
    
    for alert_name, description in demo_alerts:
        print(f"\n📊 Processing {alert_name} Alert:")
        
        # Create alert
        alert_signal = create_demo_alert(alert_name, description)
        
        # Show the alert details
        print(f"   Alert ID: {alert_signal.alert_id}")
        print(f"   Alert Name: {alert_signal.alert_data.labels.alertname}")
        print(f"   Description: {alert_signal.alert_data.annotations.description}")
        
        # Show activity name generation
        alert_name_lower = alert_name.lower()
        activity_name = f"log_{alert_name_lower}_alert"
        print(f"   Generated Activity: {activity_name}")
        
        # Show fallback mechanism
        predefined_activities = ["cratedb", "prometheus", "node", "pod", "service"]
        if alert_name_lower in predefined_activities:
            print(f"   ✅ Pre-defined activity exists")
        else:
            print(f"   🔄 Will fallback to generic 'log_alert' activity")


def demo_enhanced_logging():
    """Demonstrate the enhanced logging features."""
    print_section("Enhanced Logging Demo")
    
    print("📝 Log Message Improvements:")
    print("   Before: 'Alert received and logged'")
    print("   After:  'CrateDB alert received and logged'")
    print()
    
    print("🖥️  Console Output Improvements:")
    print("   Before:")
    print("   ┌─────────────────────────────────────┐")
    print("   │ ALERT DATA STRUCTURE:               │")
    print("   └─────────────────────────────────────┘")
    print("   After:")
    print("   ┌─────────────────────────────────────┐")
    print("   │ CRATEDB ALERT DATA STRUCTURE:       │")
    print("   └─────────────────────────────────────┘")
    print()
    
    print("🏷️  Activity Success Messages:")
    print("   Before: 'Alert abc123 logged successfully'")
    print("   After:  'CrateDB alert abc123 logged successfully'")


def demo_configuration_flexibility():
    """Demonstrate configuration flexibility."""
    print_section("Configuration Flexibility Demo")
    
    print("🔧 Multiple Configuration Methods:")
    print()
    
    print("1. Environment Variable:")
    print("   export WORKFLOW_ID='production-alert-watcher'")
    print("   export TEMPORAL_TASK_QUEUE='prod-alerts'")
    print()
    
    print("2. Config File (.env):")
    print("   WORKFLOW_ID=production-alert-watcher")
    print("   TEMPORAL_TASK_QUEUE=prod-alerts")
    print()
    
    print("3. Docker Environment:")
    print("   docker run -e WORKFLOW_ID=prod-alerts alert-watcher2")
    print()
    
    print("4. Kubernetes ConfigMap:")
    print("   apiVersion: v1")
    print("   kind: ConfigMap")
    print("   metadata:")
    print("     name: alert-watcher-config")
    print("   data:")
    print("     WORKFLOW_ID: production-alert-watcher")
    print()
    
    print("5. Programmatic Configuration:")
    print("   from alert_watcher.config import config")
    print("   config.workflow_id = 'custom-workflow-name'")


def demo_temporal_ui_benefits():
    """Demonstrate benefits in Temporal UI."""
    print_section("Temporal UI Benefits")
    
    print("🎯 Improved Visibility in Temporal UI:")
    print()
    
    print("📊 Workflow List:")
    print("   Before: Multiple 'alert-processor' workflows")
    print("   After:  Clearly identified 'alert-watcher2' workflows")
    print()
    
    print("🔍 Activity Execution:")
    print("   Before: All activities named 'log_alert'")
    print("   After:  Specific names like 'log_cratedb_alert'")
    print()
    
    print("📈 Monitoring Benefits:")
    print("   • Track performance per alert type")
    print("   • Filter activities by alert type")
    print("   • Identify which alert types are most frequent")
    print("   • Debug specific alert processing issues")


def demo_migration_safety():
    """Demonstrate migration safety features."""
    print_section("Migration Safety Features")
    
    print("🛡️  Backward Compatibility:")
    print("   • Fallback mechanism ensures no alerts are lost")
    print("   • Generic 'log_alert' activity still available")
    print("   • Existing configurations continue to work")
    print()
    
    print("🔄 Rollback Process:")
    print("   1. Change workflow_id back to 'alert-processor'")
    print("   2. Remove specific activity registrations")
    print("   3. Use only generic 'log_alert' activity")
    print()
    
    print("✅ Zero Downtime Migration:")
    print("   • Changes are additive, not breaking")
    print("   • New workflows work alongside old ones")
    print("   • Gradual rollout possible")


def main():
    """Main demo function."""
    print_header("Alert Watcher 2 - Naming System Demo")
    
    print("🎯 This demo showcases the new naming system improvements:")
    print("   1. Workflow name changed to 'alert-watcher2'")
    print("   2. Activities now use alert-specific names")
    print("   3. Enhanced logging and monitoring capabilities")
    print("   4. Easy configuration and migration")
    
    # Run all demos
    demo_workflow_naming()
    demo_activity_naming()
    demo_alert_processing()
    demo_enhanced_logging()
    demo_configuration_flexibility()
    demo_temporal_ui_benefits()
    demo_migration_safety()
    
    print_header("Demo Complete")
    print("🎉 The new naming system provides:")
    print("   ✅ Clear identification of workflows and activities")
    print("   ✅ Better debugging and monitoring capabilities")
    print("   ✅ Easy configuration and customization")
    print("   ✅ Backward compatibility and safe migration")
    print("   ✅ Enhanced operational visibility")
    
    print("\n📚 For more information:")
    print("   • Read NAMING_CHANGES.md for detailed documentation")
    print("   • Run test_naming_changes.py to verify the system")
    print("   • Check the Temporal UI when running with alerts")
    
    print("\n🚀 Ready to process alerts with the new naming system!")


if __name__ == "__main__":
    main()