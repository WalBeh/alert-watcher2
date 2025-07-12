#!/usr/bin/env python3
"""
Alert Watcher Agent Runner Script.

This script provides a simple way to run the Alert Watcher Agent with
proper error handling and logging setup.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from alert_watcher_agent.main import AlertWatcherAgent
from alert_watcher_agent.config import load_config

def print_banner():
    """Print startup banner."""
    print("="*80)
    print("ALERT WATCHER AGENT")
    print("="*80)
    print("A Temporal-based agent for executing kubectl commands across clusters")
    print("="*80)

def print_config_info(config):
    """Print configuration information."""
    print("\n📋 Configuration:")
    print(f"  Temporal Server: {config.temporal_host}:{config.temporal_port}")
    print(f"  Temporal Namespace: {config.temporal_namespace}")
    print(f"  Supported Clusters: {', '.join(config.supported_clusters)}")
    print(f"  Log Level: {config.log_level}")
    print(f"  Simulation Mode: {config.simulate_long_running}")
    if config.simulate_long_running:
        print(f"  Sleep Range: {config.min_sleep_minutes}-{config.max_sleep_minutes} minutes")
    print()

def check_environment():
    """Check environment and dependencies."""
    print("🔍 Checking environment...")
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    
    print(f"✅ Python version: {sys.version}")
    
    # Check required environment variables
    required_vars = []
    optional_vars = [
        "TEMPORAL_HOST",
        "TEMPORAL_PORT", 
        "TEMPORAL_NAMESPACE",
        "AGENT_LOG_LEVEL",
        "SIMULATE_LONG_RUNNING"
    ]
    
    print("📊 Environment variables:")
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            print(f"  {var}: {value}")
        else:
            print(f"  {var}: <default>")
    
    print()

async def main():
    """Main entry point."""
    print_banner()
    
    agent = None
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        """Handle shutdown signals."""
        print(f"\n⚠️  Signal {signum} received, shutting down...")
        shutdown_event.set()
    
    # Setup signal handlers
    import signal
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # Load configuration
        config = load_config()
        print_config_info(config)
        
        # Check environment
        check_environment()
        
        # Create and start agent
        print("🚀 Starting Alert Watcher Agent...")
        agent = AlertWatcherAgent(config)
        
        # Start agent in background
        agent_task = asyncio.create_task(agent.start())
        
        # Wait for either agent completion or shutdown signal
        shutdown_task = asyncio.create_task(shutdown_event.wait())
        
        done, pending = await asyncio.wait(
            [agent_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel pending tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Check if shutdown was requested
        if shutdown_event.is_set():
            print("🛑 Shutdown requested")
            if agent:
                await agent.shutdown("signal_received")
        
    except KeyboardInterrupt:
        print("\n⚠️  Keyboard interrupt received")
        if agent:
            await agent.shutdown("keyboard_interrupt")
        sys.exit(0)
        
    except Exception as e:
        print(f"\n💥 Fatal error: {str(e)}")
        if agent:
            await agent.shutdown("fatal_error")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())