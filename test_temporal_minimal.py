#!/usr/bin/env python3
"""
Minimal test to isolate the Temporal start_workflow API issue.
"""

import asyncio
from temporalio.client import Client
from temporalio import workflow


@workflow.defn
class SimpleWorkflow:
    @workflow.run
    async def run(self) -> str:
        workflow.logger.info("Simple workflow started")
        return "success"


async def main():
    print("Testing Temporal start_workflow API...")
    
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        print("✅ Connected to Temporal")
        
        # Test 1: Try the call that's failing
        print("\nTest 1: start_workflow with no arguments")
        try:
            handle = await client.start_workflow(
                SimpleWorkflow.run,
                id="test-workflow-1",
                task_queue="test-queue"
            )
            print("✅ start_workflow with no args succeeded")
            print(f"   Workflow ID: {handle.id}")
        except Exception as e:
            print(f"❌ start_workflow failed: {e}")
        
        # Test 2: Try with execute_workflow instead
        print("\nTest 2: execute_workflow with no arguments")
        try:
            result = await client.execute_workflow(
                SimpleWorkflow.run,
                id="test-workflow-2", 
                task_queue="test-queue"
            )
            print("✅ execute_workflow succeeded")
            print(f"   Result: {result}")
        except Exception as e:
            print(f"❌ execute_workflow failed: {e}")
            
        # Test 3: Try with string workflow name
        print("\nTest 3: start_workflow with string name")
        try:
            handle = await client.start_workflow(
                "SimpleWorkflow",
                id="test-workflow-3",
                task_queue="test-queue"
            )
            print("✅ start_workflow with string name succeeded")
            print(f"   Workflow ID: {handle.id}")
        except Exception as e:
            print(f"❌ start_workflow with string name failed: {e}")
            
    except Exception as e:
        print(f"❌ Failed to connect to Temporal: {e}")
        print("Make sure Temporal server is running: temporal server start-dev")


if __name__ == "__main__":
    asyncio.run(main())