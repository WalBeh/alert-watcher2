# Changes

## 🔧 Recent Updates & Fixes

### Latest Changes (2025-07-11)
- 🎯 **MAJOR ENHANCEMENT: Child Workflows for Individual Kubectl Executions** - Implemented separate child workflows for each kubectl execution type (`KubectlTestWorkflow`, `HemakoJfrWorkflow`, `HemakoCrashHeapdumpWorkflow`) providing:
  - **Enhanced Temporal UI visibility** - Each kubectl execution now has its own workflow with searchable metadata
  - **Searchable attributes** - Can search by `alert_id`, `cluster_context`, `command_type`, `alert_name`, `namespace`, `pod`, `correlation_id`
  - **Individual execution tracking** - Better monitoring and debugging capabilities
  - **Dedicated retry/timeout policies** - Optimized per command type (longer timeouts for JFR/heapdump operations)
- 🚨 **CRITICAL FIX: Resolved Temporal Workflow Sandbox Restrictions** - Fixed `RestrictedWorkflowAccessError: Cannot access time.localtime` by:
  - **Moved Kubernetes imports inside activities** - No more module-level imports causing sandbox restrictions
  - **Added KubeConfigHandler** - Proper multi-file kubeconfig support with context validation
  - **Fixed structlog import issues** - Replaced with workflow.logger to avoid sandbox restrictions
- ✅ **All activity restrictions resolved** - Activities can now use `time.localtime()`, Kubernetes client, and other restricted functions
- ✅ **Multi-file kubeconfig support** - Handles colon-separated KUBECONFIG paths correctly
- ✅ **Child workflow pattern verified** - Tested and working with proper parent-child relationships

### Previous Changes (2025-07-06)
- 🚨 **CRITICAL FIX: Resolved AttributeError in worker initialization** - Fixed `'AgentConfig' object has no attribute 'task_queues'` error by using `get_task_queues()` method instead of direct attribute access. This was preventing all workflows from starting properly.
- 🚨 **CRITICAL FIX: Added task_queue parameter to activity execution** - Fixed activities running on workflow workers instead of dedicated activity workers by adding `task_queue` parameter to `workflow.execute_activity()` call. This resolves the `time.localtime` restriction error by ensuring activities run in proper execution context.
- ✅ **Fixed Temporal workflow logging compatibility** - Resolved `Logger._log()` keyword argument errors
- ✅ **All tests passing** - Complete test suite verification completed
- ✅ **Alert filtering verified** - Confirmed rejection of unsupported alert types
- ✅ **Sub-workflow naming confirmed** - Pattern `{AlertName}-{Namespace}-{UUID}` working correctly

### Verified Working Features
- ✅ Health and readiness endpoints
- ✅ CrateDBContainerRestart alert processing
- ✅ CrateDBCloudNotResponsive alert processing
- ✅ Unsupported alert rejection with clear messaging
- ✅ Batch alert processing (mixed supported/unsupported)
- ✅ Sub-workflow creation and execution
- ✅ Hemako command placeholder with correct parameters
- ✅ **Child workflow pattern** - Individual kubectl executions as separate workflows
- ✅ **Searchable metadata** - Each execution has searchable attributes in Temporal UI
- ✅ **Kubernetes client in activities** - No more sandbox restrictions
- ✅ **Multi-file kubeconfig support** - Handles complex kubeconfig setups
- ✅ **Time functions in activities** - `time.localtime()` and other time functions work correctly

### Architecture Benefits
- 🔍 **Better visibility** - Each kubectl execution visible as separate workflow in Temporal UI
- 🔍 **Enhanced searchability** - Find executions by alert metadata (alert_id, cluster, namespace, pod)
- 🛠️ **Improved debugging** - Individual workflow logs and execution history per kubectl operation
- ⚡ **Optimized timeouts** - Different timeout/retry policies per command type
- 📊 **Better monitoring** - Individual metrics and success/failure tracking per execution type