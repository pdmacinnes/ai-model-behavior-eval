# Spec: OpenAI Responses Provider Transport

## Requirements & Goals

- Add a live OpenAI Responses API transport to the existing trusted JSONL provider worker.
- Make the OpenAI pilot compatible with reasoning/tool-calling models whose supported path is the Responses API, while preserving the worker's existing parent-mediated tool protocol.
- Keep the existing Chat Completions-compatible transport available for providers and registrations that explicitly use it; this milestone adds the Responses path rather than silently changing existing transport semantics.
- Map the existing model condition field `reasoning_effort` to the Responses request field `reasoning.effort` only when the condition provides a non-null value. A null value must omit the reasoning field entirely.
- Translate the existing four parent-owned tools into Responses custom function tools without exposing workspace paths, hidden causes, verifier data, credentials, or private reasoning.
- Accept up to `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE` ordered model function calls per provider round, while keeping parent execution sequential. Parallel provider execution remains out of scope; oversized, duplicate-id, malformed, or unsupported call batches fail closed as an infrastructure/provider error.
- Keep provider state stateless from the harness perspective: send `store: false`, do not request encrypted reasoning content, do not use `previous_response_id`, and do not retain or publish provider response identifiers.
- **Accepted quality tradeoff:** OpenAI recommends echoing reasoning items (or using `previous_response_id`) when continuing tool loops on reasoning models. This milestone deliberately does not echo reasoning items or store provider state, so that private reasoning never enters harness memory, artifacts, or logs. Live behavior may be weaker than a stateful Responses client; that is an explicit study-boundary choice, not an accidental omission.
- Preserve parent ownership of workspace evidence, edits, checkpoints, stop handling, verification, timeouts, censorship, and public artifact sanitization.
- Use the existing parent network authorization marker and credential allowlist. The worker must not gain a new worker-local network or credential override.
- Reference basis: OpenAI documents the Responses API as using `reasoning.effort` and custom function-call items, and recommends Responses for reasoning/tool-calling workflows. The current model documentation lists GPT-5.6 Luna as supporting the Responses endpoint and configurable reasoning effort.
- This milestone does not add an OpenAI SDK dependency, streaming, retries, persisted conversations, hosted tools, score computation, chain-of-thought capture, or an OS/container sandbox.

## Inputs, Outputs & Behavior

### Worker and registration inputs

- The existing worker entrypoint remains `scripts/openai_compatible_workspace_worker.py`.
- The worker accepts a new explicit transport value, `openai-responses`, in addition to the existing `mock` and `openai-compatible` values.
- The execution-policy allowlist for network-required conditions accepts the reviewed worker command with `--transport openai-compatible` **or** `--transport openai-responses`, and continues to reject wrappers, arbitrary commands, `--allow-network`, and `--api-key-env`. Allowed optional numeric flags are `--max-rounds`, `--max-message-chars`, `--max-conversation-messages`, `--max-conversation-chars`, and the positive finite `--request-timeout-seconds`.
- Any condition whose command selects `--transport openai-responses` must also declare `network_required: true`. A Responses transport with `network_required: false` fails execution-policy validation before worker startup.
- The live parent still supplies `EVIDENCE_EVAL_NETWORK_AUTHORIZED=1` only for an authorized network condition and passes only `EVIDENCE_EVAL_PROVIDER_API_KEY` to that child.
- The worker reads the existing task fields: prompt, optional initial_observation, tool_contract, and model_condition containing provider, model_id, adapter_id, and nullable reasoning_effort.
- The base URL continues to come from `EVIDENCE_EVAL_PROVIDER_BASE_URL`. The Responses transport targets `{base_url}/responses`, unless the configured base URL already ends in `/responses`.

### Request construction

- The transport receives the worker's existing Chat Completions-style internal message list and translates it to a Responses `input` list without changing the worker loop or parent tool semantics.
- The initial user prompt becomes a Responses user input item. Tool results become `function_call_output` items with the original call id from the prior model `function_call` (the same id used in the parent JSONL `call`) and bounded JSON output.
- Prior assistant tool-call state is represented as the corresponding Responses `function_call` item so the next request contains the provider-visible conversation required to continue the same investigation.
- Text-only assistant content is represented as bounded assistant/message input content when needed for a subsequent round; private reasoning items are never synthesized, requested, retained, or sent back by the harness.
- Each declared tool becomes a Responses custom function tool with top-level `type: function`, `name`, `description`, and `parameters`. Only the four existing supported method names are accepted.
- The request includes `model`, `input`, `tools`, `tool_choice: auto`, `parallel_tool_calls: false`, and `store: false`.
- When `reasoning_effort` is a non-empty string, the request includes `reasoning: {"effort": <value>}`. When it is null, the request contains no `reasoning` field and no null reasoning value.
- The serialized Responses request is measured after all translation and rejected before network I/O when it exceeds the request-byte bound.

### Response parsing and worker loop

- A successful Responses response must be a bounded JSON object with `status: "completed"` and an `output` list.
- The parser collects visible assistant output text from output message content (`output_text` parts) and returns it as `ProviderReply.text`.
- The parser accepts up to `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE` ordered `function_call` output items per response. It validates each call id, supported function name, and JSON-object arguments, rejects duplicate call ids within that response, and returns the existing `ProviderToolCall` shapes (`call_id`, `name`, `arguments`).
- Responses output items of type `reasoning`, encrypted reasoning, metadata, or other non-visible/non-function types are ignored for behavioral output and are never written to artifacts or stderr. Ignoring them does not require echoing them on the next request (see accepted quality tradeoff above).
- If a response contains visible text and one or more function calls, the text remains in the internal reply and the worker executes the calls sequentially through the existing parent JSONL protocol.
- If a response contains no function call, the worker retains the existing final-status behavior: text-only output maps to `completed`, and an accepted `stop_investigation` maps to `stopped`.
- More than the bounded number of function calls, duplicate call ids, malformed function arguments, unsupported output shapes required for a tool continuation, non-completed responses, invalid JSON, oversized responses, provider HTTP errors, and transport failures produce a bounded `ProviderTransportError` / `ProviderWorkerError`. They never become a behavioral refusal or verified result.
- Safe provider diagnostics may retain only HTTP status plus allowlisted structured fields such as error `type`, `code`, and `param`. Response bodies, free-text error messages that may echo request content, authorization headers, credentials, workspace data, and local paths remain excluded.

### Bounds and lifecycle

- Existing independent bounds remain enforced for serialized request bytes, conversation message count, conversation characters, tool-definition bytes, response bytes, response text, provider rounds, parent JSONL messages, and the bounded provider request timeout. Defaults and measurement helpers may be shared with the Chat Completions transport; the Responses path must not weaken them.
- Responses-specific wrapper overhead and `function_call_output` items are included in the pre-request serialized request-byte measurement.
- Conversation and tool-result bounds are checked when items are translated/appended, before the next network request.
- The parent continues to terminate timed-out children, skip verification for censored trials, and clean up according to the existing workspace lifecycle.
- No automated test or case calibration path may make an external provider request.

## Edge Cases & Error Handling

- A registration using `--transport openai-responses` without `network_required: true` is rejected by execution-policy validation.
- A network-required Responses registration without the batch-level `--allow-network` flag fails before worker startup.
- A non-network registration supplied with the live-network flag remains rejected; mock and reference paths remain unchanged.
- A null reasoning effort omits the reasoning request object. An invalid non-string or empty reasoning effort fails validation before network I/O.
- A model response containing up to `MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE` ordered function calls is accepted even if `parallel_tool_calls: false` was requested; larger or duplicate-id batches fail closed before any parent workspace method is invoked.
- A function call with an unsupported name, missing call id, non-object JSON arguments, or oversized arguments fails closed without invoking a parent tool.
- When translating the worker conversation into Responses input, a `function_call_output` whose call id does not match the preceding function-call item fails closed before network I/O and cannot mutate the workspace.
- An incomplete, failed, or otherwise non-completed Responses response is an infrastructure/provider failure. The parent records censorship or adapter failure using existing semantics and does not invoke a verifier on a timed-out active child.
- Provider HTTP errors are bounded and sanitized. The implementation must not include response bodies, free-text error messages, request content, credentials, authorization headers, workspace paths, or hidden case data in stderr, metadata, or public artifacts.
- Provider timeouts and connection failures are reported only with safe categories such as timeout, network error, or connection failure; exception text is not retained.
- Responses API output containing reasoning summaries or encrypted reasoning content is not captured, requested, published, or used as a behavioral annotation.
- An oversized translated request or conversation fails before the HTTP call. Tests prove the fake network function is not called in each overflow case.
- A missing credential or absent parent network marker fails before HTTP I/O.
- The existing public sanitizer must continue to exclude raw adapter results, final response text, commands, credentials, paths, and provider diagnostics from public releases.
- Existing `openai-compatible` registrations, mock smoke tests, reference workers, and public release tests continue to pass without modification to their observable behavior.

## Acceptance Criteria

- [ ] The worker accepts `--transport openai-responses` and constructs the Responses endpoint from the approved base URL.
- [ ] Execution-policy validation allows the reviewed worker command with `--transport openai-compatible` or `--transport openai-responses`, and rejects Responses transport without `network_required: true`.
- [ ] A Responses request contains `model`, translated `input`, top-level custom function tools, `tool_choice: auto`, `parallel_tool_calls: false`, and `store: false`.
- [ ] A non-null `reasoning_effort` maps to `reasoning.effort`, while a null value omits the entire `reasoning` field.
- [ ] The request builder never places credentials, authorization headers, workspace paths, hidden causes, verifier data, or task-internal artifact paths in the request payload.
- [ ] The parser converts visible output text and an ordered bounded Responses `function_call` list into the existing `ProviderReply` and `ProviderToolCall` types.
- [ ] Oversized, duplicate-id, malformed, or unsupported function-call outputs fail closed before any parent workspace method is invoked.
- [ ] Function-call results are translated to bounded ordered `function_call_output` items and the next request contains every correct call id.
- [ ] Reasoning output items, encrypted reasoning, response identifiers, and raw response bodies are not retained in worker output, metadata, or public artifacts, and are not echoed on subsequent requests.
- [ ] HTTP status plus safe structured diagnostic fields may be surfaced without leaking response bodies, credentials, request content, paths, or authorization headers.
- [ ] Request, conversation, tool-definition, response, round, and JSONL bounds are enforced on the Responses path, with overflow tests proving no external request occurs.
- [ ] Fake HTTP tests cover successful text output, one and multiple function calls, ordered tool-result continuation, null reasoning omission, non-null reasoning mapping, malformed output, duplicate/oversized calls, HTTP error sanitization, timeout/transport failure, and bound failures.
- [ ] A real `SubprocessWorkspaceAdapter` integration test exercises the Responses-shaped worker path using a fake transport and confirms parent-owned tools and verifier lifecycle remain unchanged.
- [ ] Existing mock/reference tests, execution-policy tests, public sanitizer tests, timeout/censorship tests, and the full test suite remain green.
- [ ] No live provider request is made by implementation or automated tests.
- [ ] The implementation adds no retries, scores, rankings, OS sandbox, container policy, or private chain-of-thought capture.
