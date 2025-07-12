# TODO

## Future Enhancements

### Planned Features

1. **Real Hemako Integration**
   - Replace placeholder with actual command execution
   - Add command result handling
   - Implement retry logic

2. **Enhanced Monitoring**
   - Prometheus metrics
   - Grafana dashboards
   - Alert success/failure tracking

3. **Configuration Management**
   - Dynamic alert type configuration
   - Command parameter customization
   - Environment-specific settings

## Development Tasks

- [ ] Implement actual hemako command execution
- [ ] Add comprehensive error handling
- [ ] Set up monitoring and metrics
- [ ] Add configuration management system
- [ ] Improve documentation
- [ ] Add more test coverage

## Ideas for Future Consideration

- [ ] Support for additional alert types
- [ ] Web UI for monitoring
- [ ] Alert history and analytics
- [ ] Integration with other monitoring tools

--
- [ ] agent: Catch expired or invalid credentials and not able to connec to k8s api:
```
An error occurred (ExpiredToken) when calling the AssumeRole operation: The security token included in the request is expired
E0712 14:02:43.947035   39555 memcache.go:265] "Unhandled Error" err="couldn't get current server API group list: Get \"https://eks1-us-east-1-dev.tail1ec75.ts.net/api?timeout=32s\": getting credentials: exec: executable aws failed with exit code 254"
```

- [ ] web-hook server: should be able to re-connect to temporarl
- [x] workflow names: should be shorter: either cluster name, or only first token in the UUID of the namespace, sts: `kubectl-exec-CrateDBContainerRestart-85c8074c-9bf8-4f0a-867c-faf252c76bf0-crate-data-hot-d84c10e6-d8fb-4d10-bf60-f9f2ea919a73-1-1b1c0f8d-hemako_crash_heapdump-1752324341.407892`


- [x] correctly handly 0 uploaded files
```
  File "/Users/walter/tmp/alert-watcher2/.venv/lib/python3.12/site-packages/temporalio/worker/_workflow_instance.py", line 407, in activate
    self._run_once(check_conditions=index == 1 or index == 2)

  File "/Users/walter/tmp/alert-watcher2/.venv/lib/python3.12/site-packages/temporalio/worker/_workflow_instance.py", line 1988, in _run_once
    raise self._current_activation_error

  File "/Users/walter/tmp/alert-watcher2/.venv/lib/python3.12/site-packages/temporalio/worker/_workflow_instance.py", line 2006, in _run_top_level_workflow_function
    await coro

  File "/Users/walter/tmp/alert-watcher2/.venv/lib/python3.12/site-packages/temporalio/worker/_workflow_instance.py", line 897, in run_workflow
    result = await self._inbound.execute_workflow(input)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

  File "/Users/walter/tmp/alert-watcher2/.venv/lib/python3.12/site-packages/temporalio/worker/_workflow_instance.py", line 2387, in execute_workflow
    return await input.run_fn(*args)
           ^^^^^^^^^^^^^^^^^^^^^^^^^

  File "/Users/walter/tmp/alert-watcher2/src/alert_watcher_agent/workflows.py", line 859, in run
    "command_executed": f"Processed {len(crash_dump_result['processed_pods'])} pods, uploaded {crash_dump_result['upload_count']} files",
                                                                                               ~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^

```
- [x] S3-Upload-CrateDBContainerRestart-CrateDBContainerRestart-unknown-unknown-0-1752348400.460056
