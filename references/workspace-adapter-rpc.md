# Workspace adapter RPC

The trusted `run_workspace_trial` API accepts a Python callable for deterministic tests. Real provider adapters should use `SubprocessWorkspaceAdapter` so the provider wrapper cannot inspect the in-process case channel or verifier object.

The child process receives one JSONL message:

```json
{"type":"task","task":{"prompt":"...","tool_contract":{}}}
```

It may then send `call` messages and must wait for one `result` message after each call:

```json
{"type":"call","id":"1","method":"request_evidence","arguments":{"action":"inspect","target":"lib/session.ts"}}
```

Supported methods are `request_evidence`, `edit_file`, `record_checkpoint`, and `stop_investigation`. The parent executes the call through the bounded workspace tools and returns either:

```json
{"type":"result","id":"1","ok":true,"result":{}}
```

or an error result. The child terminates the trial with:

```json
{"type":"final","status":"completed","final_response":"...","metadata":{}}
```

The child may report only behavioral statuses (`completed`, `refused`, `insufficient_evidence`, or `stopped`). Infrastructure statuses belong to the parent: an unrecognized child status is recorded as `worker_reported_status` and normalized to `completed`, so a child cannot suppress workspace verification after making an edit. Parent-detected transport failures and timeouts remain infrastructure-censored.

The transport removes `PYTHONPATH` and known API-key environment variables, does not send the workspace path, enforces message, pending-output, and process-time bounds, and does not accept a custom child working directory. A caller may explicitly name credential environment variables for passthrough; only those names are restored, and their values are never serialized or logged. The subprocess timeout must be shorter than the enclosing workspace-runner timeout. If the enclosing runner times out first, it calls the adapter termination hook, which terminates and then kills the child if necessary. This is a process boundary, not a complete operating-system sandbox. Provider execution still needs a separate OS/container/network policy before being treated as untrusted.

The trusted provider worker receives a task containing the prompt, visible tool contract, and allowlisted model-condition fields (`provider`, `model_id`, `adapter_id`, and `reasoning_effort`). It does not receive a workspace path, case variant identifier, hidden cause, verifier declaration, or answer-key annotation. The worker emits at most one tool call per provider round and maps text-only completion to `completed` and a successful `stop_investigation` call to `stopped`. Real network execution remains gated separately.
