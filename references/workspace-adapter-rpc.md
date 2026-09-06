# Workspace adapter RPC

The trusted `run_workspace_trial` API accepts a Python callable for deterministic tests. Real provider adapters should use `SubprocessWorkspaceAdapter` so the provider wrapper cannot inspect the in-process case channel or verifier object.

The child process receives one JSONL message:

```json
{"type":"task","task":{"initial_context":"...","tool_contract":{}}}
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

The transport removes `PYTHONPATH` and known API-key environment variables, does not send the workspace path, and enforces message and process-time bounds. This is a process boundary, not a complete operating-system sandbox. Provider execution still needs a separate OS/container/network policy before being treated as untrusted.
