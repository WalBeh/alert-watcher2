"""
Simple test script for the new Kubernetes Temporal approach.

This script tests the simplified architecture to ensure that:
1. Activities run in proper isolation from workflows
2. Kubernetes client works without time.localtime restrictions
3. The overall approach is clean and maintainable
"""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from temporalio.client import Client
from temporalio.worker import Worker
from simple_agent.workflows import SimpleAgentWorkflow, KubernetesWorkflow
from simple_agent.k8s_activities import get_nodes, get_pods, execute_kubectl_command


async def test_simple_approach():
    """Test the simple approach with a single worker."""
    print("=== Testing Simple Approach ===")
    
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        print("✅ Connected to Temporal server")
        
        # Create worker with both workflows and activities
        worker = Worker(
            client=client,
            task_queue="test-k8s-simple",
            workflows=[SimpleAgentWorkflow, KubernetesWorkflow],
            activities=[get_nodes, get_pods, execute_kubectl_command],
            max_concurrent_activities=2,
            max_concurrent_workflow_tasks=5
        )
        
        print("✅ Created worker")
        
        # Start worker in background
        worker_task = asyncio.create_task(worker.run())
        print("✅ Started worker")
        
        # Wait a moment for worker to be ready
        await asyncio.sleep(2)
        
        # Test 1: Start simple agent workflow
        print("\n🧪 Test 1: Simple Agent Workflow")
        try:
            result = await client.execute_workflow(
                SimpleAgentWorkflow.run,
                {"cluster_context": "default"},
                id="test-simple-agent",
                task_queue="test-k8s-simple"
            )
            print(f"✅ Simple agent workflow completed: {result.get('success')}")
            if result.get('test_result'):
                print(f"   Node count: {result['test_result'].get('node_count', 'unknown')}")
        except Exception as e:
            print(f"❌ Simple agent workflow failed: {e}")
        
        # Test 2: Kubernetes operations workflow
        print("\n🧪 Test 2: Kubernetes Operations Workflow")
        try:
            operations = [
                {"type": "get_nodes"},
                {"type": "get_pods", "namespace": "default"},
                {"type": "kubectl_command", "command": "get nodes"}
            ]
            
            result = await client.execute_workflow(
                KubernetesWorkflow.run,
                "default",
                operations,
                id="test-k8s-operations",
                task_queue="test-k8s-simple"
            )
            print(f"✅ Kubernetes operations workflow completed")
            print(f"   Total operations: {result.get('total_operations')}")
            print(f"   Successful: {result.get('successful_operations')}")
            print(f"   Failed: {result.get('failed_operations')}")
            
        except Exception as e:
            print(f"❌ Kubernetes operations workflow failed: {e}")
        
        # Test 3: Direct activity execution
        print("\n🧪 Test 3: Direct Activity Execution")
        try:
            # This tests if activities can be executed directly without workflow context issues
            handle = await client.start_workflow(
                "test_direct_activity",
                id="test-direct-activity",
                task_queue="test-k8s-simple"
            )
            print("✅ Started direct activity test workflow")
            
        except Exception as e:
            print(f"❌ Direct activity test failed: {e}")
        
        print("\n✅ All tests completed!")
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up
        if 'worker_task' in locals():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        print("🧹 Cleaned up")


async def test_separated_approach():
    """Test the separated workers approach."""
    print("\n=== Testing Separated Workers Approach ===")
    
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        print("✅ Connected to Temporal server")
        
        # Create separate workflow and activity workers
        workflow_worker = Worker(
            client=client,
            task_queue="test-k8s-workflows",
            workflows=[SimpleAgentWorkflow, KubernetesWorkflow],
            activities=[],  # No activities on workflow worker
            max_concurrent_workflow_tasks=5,
            max_concurrent_activities=0
        )
        
        activity_worker = Worker(
            client=client,
            task_queue="test-k8s-activities",
            workflows=[],  # No workflows on activity worker
            activities=[get_nodes, get_pods, execute_kubectl_command],
            max_concurrent_workflow_tasks=0,
            max_concurrent_activities=3
        )
        
        print("✅ Created separated workers")
        
        # Start both workers
        workflow_task = asyncio.create_task(workflow_worker.run())
        activity_task = asyncio.create_task(activity_worker.run())
        print("✅ Started both workers")
        
        # Wait for workers to be ready
        await asyncio.sleep(2)
        
        # Test with separated workers
        print("\n🧪 Test: Separated Workers Execution")
        try:
            # Create a custom workflow that uses the activity task queue
            @workflow.defn
            class SeparatedTestWorkflow:
                @workflow.run
                async def run(self):
                    # Execute activity on the activity worker task queue
                    result = await workflow.execute_activity(
                        get_nodes,
                        "default",
                        task_queue="test-k8s-activities",  # Route to activity worker
                        start_to_close_timeout=timedelta(minutes=2)
                    )
                    return result
            
            # Register the test workflow
            workflow_worker._workflow_registry.register(SeparatedTestWorkflow)
            
            result = await client.execute_workflow(
                SeparatedTestWorkflow.run,
                id="test-separated-workflow",
                task_queue="test-k8s-workflows"
            )
            
            print(f"✅ Separated workers test completed: {result.get('success')}")
            if result.get('node_count'):
                print(f"   Node count: {result['node_count']}")
                
        except Exception as e:
            print(f"❌ Separated workers test failed: {e}")
        
        print("\n✅ Separated workers test completed!")
        
    except Exception as e:
        print(f"❌ Separated workers test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # Clean up
        if 'workflow_task' in locals():
            workflow_task.cancel()
        if 'activity_task' in locals():
            activity_task.cancel()
        
        try:
            await asyncio.gather(workflow_task, activity_task, return_exceptions=True)
        except:
            pass
        print("🧹 Cleaned up separated workers")


async def test_minimal_activity():
    """Test a minimal activity to isolate any issues."""
    print("\n=== Testing Minimal Activity ===")
    
    try:
        from temporalio import activity
        
        @activity.defn
        async def minimal_test() -> dict:
            """Minimal test activity."""
            import time
            import datetime
            
            # Test time functions that were causing issues
            current_time = time.time()
            local_time = time.localtime()
            dt = datetime.datetime.now()
            
            return {
                "success": True,
                "current_time": current_time,
                "local_time": time.strftime("%Y-%m-%d %H:%M:%S", local_time),
                "datetime": dt.isoformat(),
                "message": "Time functions work correctly in activity"
            }
        
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        
        # Create minimal worker
        worker = Worker(
            client=client,
            task_queue="test-minimal",
            workflows=[SimpleAgentWorkflow],
            activities=[minimal_test],
            max_concurrent_activities=1
        )
        
        # Start worker
        worker_task = asyncio.create_task(worker.run())
        await asyncio.sleep(1)
        
        # Test minimal activity execution
        @workflow.defn
        class MinimalTestWorkflow:
            @workflow.run
            async def run(self):
                return await workflow.execute_activity(
                    minimal_test,
                    start_to_close_timeout=timedelta(seconds=30)
                )
        
        # Register workflow
        worker._workflow_registry.register(MinimalTestWorkflow)
        
        result = await client.execute_workflow(
            MinimalTestWorkflow.run,
            id="test-minimal-activity",
            task_queue="test-minimal"
        )
        
        print(f"✅ Minimal activity test: {result.get('success')}")
        print(f"   Message: {result.get('message')}")
        print(f"   Local time: {result.get('local_time')}")
        
    except Exception as e:
        print(f"❌ Minimal activity test failed: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        if 'worker_task' in locals():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass


if __name__ == "__main__":
    async def main():
        print("🚀 Starting Simple Agent Tests")
        print("=" * 50)
        
        # Test 1: Simple approach
        await test_simple_approach()
        
        # Test 2: Separated approach
        await test_separated_approach()
        
        # Test 3: Minimal activity test
        await test_minimal_activity()
        
        print("\n" + "=" * 50)
        print("🎉 All tests completed!")
    
    asyncio.run(main())