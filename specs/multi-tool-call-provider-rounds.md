# Spec: Bounded Multi-Tool Provider Responses

## Requirements & Goals

- Allow provider responses that contain several supported tool calls in one model response. Grok exposed this gap during the first live smoke: the provider returned multiple calls and the current worker censored the trial before any parent tool ran.
- Preserve the provider's declared call order and the fact that the calls came from one provider round.
- Keep all workspace access, validation, budget reservation, mutation, and lifecycle ownership in the parent process.
- Keep the current single-call JSONL protocol backward compatible for existing workers and registrations.
- Keep provider execution bounded and fail closed for malformed, oversized, ambiguous, or unsafe call batches.

### Scope and supersession

This spec supersedes the "at most one tool call" clauses in `specs/trusted-jsonl-provider-worker.md` and `specs/openai-responses-provider-transport.md` for the OpenAI-compatible and OpenAI Responses transports only. Native Gemini remains explicitly single-call under this spec and the existing Gemini clauses remain authoritative.

## Inputs, Outputs & Behavior

### Provider response boundary

- `ProviderReply.tool_calls` may contain zero through `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE` `ProviderToolCall` values for the OpenAI-compatible and OpenAI Responses transports. The implementation sets `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE = 8`; this is a safety bound on one provider response, not a model-quality score. The limit was widened from four after the first live Grok smoke produced more than four calls in one response.
- Tool calls must retain provider order. Every call must have a non-empty id unique within that provider response, a supported method name, and a JSON-object argument value.
- A response with more than `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE` calls, duplicate call ids within that response, malformed calls, or unsupported methods is a bounded provider error. No parent workspace method is invoked for that response.
- Visible provider text may accompany zero or more valid tool calls and remains bounded by the existing response-text limit.
- Native Gemini remains single-call for this milestone because its signature-bearing continuation history requires a separate multi-call design.

### Parent JSONL protocol

- No new parent message type is required. For a response with one tool call, the worker continues emitting the existing JSONL `call` message and waiting for the matching `result` message.
- For a response with multiple tool calls, the worker emits the existing `call` messages one at a time in provider order and waits for each matching `result` before emitting the next one. Parent execution is sequential, never concurrent.
- The worker validates the complete provider call list before emitting the first parent call. This prevents a malformed later call from causing a partial batch.
- A parent tool error is returned to the provider as data for that call. The worker still collects later calls from the same provider response unless the parent process or protocol fails.
- A multi-call response containing `stop_investigation` is rejected before any parent call. `stop_investigation` remains valid only as a single call and retains the existing successful-stop mapping.

### Provider continuation

- After all results for a provider response are collected, the worker appends one assistant message containing the complete ordered tool-call list, followed by one ordered tool-result message per call.
- The next provider request is made only after the complete result set has been appended and all existing conversation and request bounds pass.
- The provider round counter increments once per provider HTTP response, not once per tool call. Existing parent evidence and event limits still charge each dispatched tool independently.
- OpenAI Responses requests continue to send `parallel_tool_calls: false`. The worker nevertheless accepts a bounded multi-call response because a provider may emit multiple calls despite that request preference; the worker does not use the field to assume that the response is single-call.
- OpenAI Responses translation must represent all function calls and all corresponding function-call outputs in order. It must preserve existing stateless reasoning behavior and must not capture or echo private reasoning items.

### Observability and safety

- Existing parent event traces remain the source of truth for accepted, rejected, and failed workspace actions. No provider response body, credential, workspace path, hidden cause, verifier object, or private reasoning is added to artifacts or diagnostics.
- Public release and report formats remain unchanged. Sequential actions from a multi-call provider response must remain visible through the existing action and annotation fields.
- Existing JSONL, provider request, response, conversation, parent workspace, and provider request-timeout bounds remain enforced. The eight-call response limit is independent of those bounds.

## Edge Cases & Error Handling

- A provider response containing zero tool calls retains existing final-status behavior.
- If any call id is missing, duplicated, or mismatched with a parent result, the worker fails closed without making a provider continuation request.
- If a later call in a valid batch receives a parent error, its error result is appended as bounded provider-visible data; the worker does not retry or silently skip it.
- If emitting a call or reading a result encounters a JSONL size, EOF, timeout, broken-pipe, or protocol error, the parent records the existing infrastructure-level adapter failure.
- If the conversation or request would exceed a bound after adding the complete assistant call list and tool results, the worker fails before the next provider request.
- Existing one-call mock, reference-worker, Gemini, sanitizer, timeout, and lifecycle behavior must not regress.

## Implementation Plan

1. Add a shared bounded call-list validator and the named `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE = 8` constant.
2. Update OpenAI-compatible and Responses response parsers to accept ordered supported call lists and reject duplicate or oversized lists.
3. Update the worker loop to dispatch a validated multi-call response through the existing `call`/`result` JSONL messages and append the complete continuation conversation.
4. Update Responses conversation translation for multiple assistant function calls and function-call outputs.
5. Add unit tests for order, duplicate ids, call-limit overflow, stop mixed with other calls, parent errors, continuation shape, and no-request-after-failure behavior.
6. Add subprocess integration coverage using a fake multi-call transport and verify parent-owned tools, budgets, traces, and verifier lifecycle.
7. Update the worker documentation and replace the old single-call acceptance language where it describes OpenAI-compatible and Responses transports.

No live provider call is made by implementation or automated tests. The existing censored xAI smoke remains immutable and is not rerun until this spec is implemented and verified.

## Acceptance Criteria

- [ ] OpenAI-compatible and Responses parsers accept up to `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE` ordered supported tool calls and reject malformed, duplicate-within-response, unsupported, or oversized lists before parent dispatch.
- [ ] The worker emits existing single-call JSONL messages sequentially for multi-call provider responses without introducing concurrent workspace access.
- [ ] The worker validates the complete batch before its first parent call.
- [ ] The worker appends one complete assistant tool-call message and ordered tool-result messages before the next provider request.
- [ ] A multi-call response containing `stop_investigation` fails closed before any parent action; a single successful stop still maps to `stopped`.
- [ ] Native Gemini continues to reject multiple function calls and retains its existing signature-bearing single-call continuation behavior.
- [ ] Parent tool errors remain provider-visible data and do not trigger automatic retries or hidden bypasses.
- [ ] Provider round, request, response, conversation, JSONL, evidence budget, event, timeout, verifier, and cleanup bounds remain enforced.
- [ ] Fake transport tests cover successful multi-call continuation, call ordering, parent errors, duplicate ids, overflow, malformed calls, and provider failure without external network access.
- [ ] A real `SubprocessWorkspaceAdapter` integration test confirms parent-owned tools and verifier lifecycle remain correct.
- [ ] Existing tests and public sanitization continue to pass; no live provider request is made by implementation or automated tests.
