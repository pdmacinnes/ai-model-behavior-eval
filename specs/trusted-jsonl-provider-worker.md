# Spec: Trusted JSONL Provider Worker

## Requirements & Goals

- Add the first model-provider integration for the evidence-bounded debugging study.
- Reuse the existing `SubprocessWorkspaceAdapter` and parent-owned workspace tool protocol rather than allowing a provider process to access the workspace directly.
- Define a provider-neutral worker loop that can translate model tool calls into the existing JSONL `call` and `result` messages.
- Implement an OpenAI-compatible transport seam because it supports the simplest common request shape for models with native tool calling.
- Include a deterministic in-process mock transport so the full worker loop can be tested without credentials, network access, or paid model calls.
- Keep the study focused on observable behavior: evidence requests, edits, checkpoints, stopping, verifier outcomes, and lifecycle status.
- Keep credentials outside the repository and outside all artifacts.
- Do not enable real network execution as part of this milestone. The real-provider path must remain explicitly gated until a separate network execution policy is approved.
- Do not add a composite score, ranking, private chain-of-thought capture, direct workspace access, automatic retries, or provider-specific answer-key logic.

## Inputs, Outputs & Behavior

### Worker input

The worker reads the existing initial JSONL task message containing:

- The frozen case prompt.
- The bounded workspace tool contract.
- Selected non-secret model-condition fields needed to identify the provider request: `provider`, `model_id`, `adapter_id`, and `reasoning_effort` when present.

The current parent task payload is only `family.initial_context` plus `tool_contract`. This milestone therefore includes a **minimal parent change**: `run_workspace_trial` (and any pilot path that builds the same task) must inject those allowlisted condition fields into the task object before the adapter runs. The task must still omit hidden cause, verifier declaration, case variant identifier, workspace path, and answer-key annotation.

The worker may receive provider configuration through explicitly allowlisted process-environment names. Environment values are never written into commands, task messages, logs, metadata, or artifacts.

Credential allowlist note: `SubprocessWorkspaceAdapter` currently spawns children with `_clean_agent_env()`, which strips `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GOOGLE_API_KEY`, and Cursor auth vars. For this milestone, credential env names must either:

1. Use project-specific allowlisted names that are not stripped by `_clean_agent_env()` (preferred for scaffolding tests), or
2. Extend the subprocess adapter with an explicit, documented credential-env allowlist passthrough.

Do not rely on `OPENAI_API_KEY` reaching the child under the current cleaner unless the adapter passthrough is implemented and tested. Real network use of any credential remains gated off in this milestone.

### Provider transport interface

The worker uses a small transport interface with one request operation. A transport receives the conversation, tool definitions, selected model identifier, and request limits, then returns either:

- A model message containing text and zero or more tool calls.
- A bounded provider error that the worker reports as an adapter failure.

The initial implementation includes:

- A deterministic mock transport for unit and integration tests.
- An OpenAI-compatible HTTP transport implementation whose real network path is disabled unless an explicit future execution gate is satisfied.

The HTTP transport must use a bounded request timeout, bounded response size, explicit model selection, and structured parsing. It must reject malformed responses, missing choices, unsupported tool-call shapes, and provider responses that exceed configured limits.

A provider round that returns more than one tool call, or a tool call whose name is not one of the four supported workspace methods, is fail-closed as an adapter error. Parallel tool execution is out of scope; the worker emits at most one JSONL `call` per provider round.

### Normal worker flow

1. Read and validate exactly one task message from stdin.
2. Build the provider request from the prompt and the visible tool contract.
3. Ask the model for its next message through the configured transport.
4. If the model emits exactly one supported tool call, emit one JSONL `call` message to the parent and wait for the matching `result` message.
5. Append the tool result to the provider conversation without exposing any parent-only object or hidden case data.
6. Continue until the model returns final text with no tool calls, calls `stop_investigation`, reaches the configured round bound, or a bounded provider/transport error occurs.
7. Emit exactly one final JSONL message using one of the existing behavioral statuses: `completed`, `refused`, `insufficient_evidence`, or `stopped`.
8. Record only non-secret, bounded metadata such as provider label, request count, and worker protocol version.

Final-status mapping for this milestone:

- After a successful `stop_investigation` tool result, the worker emits `stopped` unless the model already indicated refusal or insufficient evidence in a prior bounded decision (default: `stopped`).
- Final assistant text with no tool calls maps to `completed`.
- Explicit refusal / insufficient-evidence outcomes are only used when the transport/mock scripted response (or a future approved mapping) selects those behavioral statuses; the OpenAI-compatible path must not invent them from free-text heuristics in this milestone beyond the mock's scripted finals.
- Provider/transport failures must emit a final message with an infrastructure-style report only via parent-observable adapter failure: prefer exiting without a behavioral `final` so the parent records `adapter_error`, or emit only if the existing protocol already treats the chosen status as behavioral. Do not self-label `refused` for timeout or HTTP errors.

Tool calls must preserve the existing method names and argument schemas: `request_evidence`, `edit_file`, `record_checkpoint`, and `stop_investigation`. The worker must not implement a second workspace API or silently execute file, shell, or test actions itself.

### Parent integration

- The parent remains the only component that executes workspace evidence, edits, checkpoints, verification, timeout handling, and infrastructure censorship.
- The worker receives no workspace path and does not change its working directory to the trial workspace.
- The parent injects selected model identifier and non-secret provider label fields into the task, but hidden causes and verifier declarations remain parent-only.
- Real network-required registrations remain rejected by the current pilot runner until the future provider execution policy explicitly allows them.
- The existing public release behavior remains unchanged: raw adapter results and final response files are omitted, while structured manifests remain subject to the existing publication gate.
- The existing deterministic `scripts/reference_workspace_worker.py` remains the credential-free pilot smoke policy script; the new provider worker is a separate entrypoint.

### Test and smoke outputs

- Unit tests cover request construction, tool-call parsing, result continuation, final status mapping, bounds, and malformed provider responses.
- An integration test runs the worker against the deterministic mock transport through `SubprocessWorkspaceAdapter` and confirms that the parent-owned verifier still receives the resulting workspace.
- The milestone smoke run uses the mock transport across one paired family and does not claim real-model behavior.
- OpenAI-compatible construction/parsing tests use fixtures or a non-network fake; they must not open sockets.

## Edge Cases & Error Handling

- Missing or malformed initial task input produces a bounded adapter error and no provider request.
- A provider response with multiple choices, multiple tool calls in one message, unsupported tool calls, invalid JSON arguments, or missing required fields is fail-closed as an adapter error.
- A tool result with an error is returned to the model as data; the worker must not retry the tool automatically or bypass the parent.
- The worker stops after a configured maximum number of provider rounds and reports a bounded adapter error rather than looping indefinitely.
- Provider request, response, and metadata sizes are bounded independently of the parent JSONL message limit.
- Provider timeouts and transport failures remain parent-observable adapter failures and cannot mark a behavioral refusal or skip a verifier by themselves.
- A model that reports an unsupported infrastructure status is normalized by the existing parent adapter behavior and cannot suppress verification after an edit.
- Missing credentials, disallowed credential environment names, or a disabled network gate prevent real provider execution before any request is sent.
- Credential values, authorization headers, local paths, workspace contents, hidden causes, and verifier details must not appear in exceptions, stderr retention, structured metadata, or publishable manifests. The worker must not print secrets to stderr because the parent may retain a stderr tail on infrastructure failure.
- The worker must not leak provider response text into a new publishable artifact. Existing internal final-response storage remains subject to the current public-release exclusion.
- If the worker exits without a final message, the existing subprocess adapter records an infrastructure failure and the batch continues without retrying or replacing the trial.

## Acceptance Criteria

- [ ] A documented worker transport interface can represent a model text response, supported tool calls, bounded provider errors, and final behavioral statuses.
- [ ] A deterministic mock transport can drive at least one evidence request, one checkpoint, one edit, and one stop through the existing JSONL subprocess protocol.
- [ ] The mock integration test uses the real parent-owned workspace tools and completes without infrastructure censorship.
- [ ] The worker never receives a workspace path, verifier object, hidden cause, case variant identifier, or answer-key annotation.
- [ ] The parent injects only allowlisted non-secret condition fields (`provider`, `model_id`, `adapter_id`, `reasoning_effort`) into the task payload.
- [ ] The worker emits only the existing supported JSONL message types and tool method names.
- [ ] Multiple tool calls in one provider message fail closed.
- [ ] OpenAI-compatible request construction and response parsing are covered by tests without making network calls.
- [ ] Malformed, oversized, unsupported, timed-out, and credential-missing provider cases fail closed with bounded diagnostics.
- [ ] Provider credentials can be passed only through an explicit environment allowlist that either survives `_clean_agent_env` or is explicitly passed through by the subprocess adapter; credential values are absent from artifacts and retained diagnostics.
- [ ] Real HTTP execution remains disabled behind an explicit gate in this milestone; the current runner continues to reject `network_required=true` registrations.
- [ ] The full existing test suite and the new worker tests pass.
- [ ] The mock smoke run produces artifacts accepted by the existing public release sanitizer.
- [ ] No composite score, leaderboard, ranking field, private chain-of-thought capture, automatic retry, or provider-specific answer-key logic is added.
