# Spec: Native Gemini Provider Transport

## Requirements & Goals

- Add a native Google Gemini `generateContent` transport for `gemini-3.8-flash` so the study can execute multi-step workspace investigations without relying on the OpenAI compatibility layer's incomplete continuation behavior.
- Preserve Gemini's model-generated function-call parts and opaque `thoughtSignature` values in memory across tool-result turns. These values must never be printed, written to artifacts, or exposed to the parent task protocol.
- Keep the existing parent-owned workspace tools, verifier, subprocess boundary, timeout, budget, and infrastructure-censorship semantics unchanged.
- Keep the transport provider-specific and explicit. Other providers continue using their existing OpenAI-compatible or Responses transports.
- Use the native REST API with the standard library rather than adding a runtime SDK dependency. The transport must remain testable with a local fake HTTP server and must not make network calls during offline verification.
- Do not expose private chain-of-thought or thought summaries. Opaque signatures are continuation tokens only.
- Do not add automatic retries, provider-specific answer-key logic, scores, rankings, or a Google server-side stateful interaction.

## Inputs, Outputs & Behavior

### Registration and policy

- Add an approved worker transport identifier, `google-gemini`, to:
  - the worker CLI (`--transport` choices),
  - `APPROVED_PROVIDER_TRANSPORTS` in execution policy,
  - `APPROVED_TRANSPORTS` in the model-matrix catalog validator,
  - and generated Google registrations.
- Like `openai-responses`, a condition that selects `--transport google-gemini` must declare `network_required: true`.
- Update only the Google model-matrix transport selection (`google-gemini-3-8-flash` → `google-gemini`). The catalog continues to use `openai-compatible` for xAI, DeepSeek, Alibaba, and Moonshot (and Anthropic as currently configured), and `openai-responses` for OpenAI.
- Existing registrations and raw artifacts remain untouched. Failed Google smoke batches are retained as infrastructure-censored records and are not rewritten.

### Credentials and endpoint

- The Google transport reads the existing generic provider environment variables:
  - `EVIDENCE_EVAL_PROVIDER_API_KEY` for the Google API key;
  - `EVIDENCE_EVAL_PROVIDER_BASE_URL` for the native API root.
- An empty or missing base URL fails closed before HTTP I/O (same fail-closed posture as other live transports). The approved Google root for live use is `https://generativelanguage.googleapis.com/v1beta`. Document that value in matrix/operator notes; do not silently substitute a different host.
- The transport constructs the endpoint as `{base}/models/{model_id}:generateContent` after validating `model_id` as a single URL path segment (reject `/`, `?`, `#`, whitespace, and empty values). Dots in ids such as `gemini-3.8-flash` are allowed.
- Authenticate native requests with the `x-goog-api-key` header. Do not send the key in a query string, task message, response metadata, stderr, or artifact.

### Tool and prompt mapping

- Translate the visible provider-neutral tool definitions into Gemini `tools[].functionDeclarations[]` definitions without adding hidden case data or provider-only actions.
- Translate the first user prompt into native Gemini `contents` with a user text part. The current Google condition has `reasoning_effort: null`, so the request uses the model's default thinking behavior and must not request thought summaries (`includeThoughts` / equivalent remain off).
- If a future Google condition supplies a supported reasoning effort, map it only through an explicit documented table and reject unsupported values before network I/O.

### Transport-owned native history (critical)

- The existing worker loop continues to pass Chat Completions-style `messages` into `ProviderTransport.request` and to emit parent JSONL `call` / `result` messages.
- Those Chat-style messages **cannot** carry `thoughtSignature` values. Therefore `GoogleGeminiTransport` must own a separate in-memory native `contents` history for the lifetime of the child process / one trial.
- Bridging rules:
  1. On the first request, seed native history from the task prompt (and ignore reconstructing signatures from Chat messages).
  2. When the model returns a function call, store the full native model `content` / `parts` (including signatures) in that history, then return a `ProviderToolCall` whose `call_id` is the exact Gemini function-call `id`.
  3. On the next `request` after the worker appends a Chat tool result, read only the matching latest tool result from the Chat `messages` list, append a native user `functionResponse` part that uses the exact pending function name and id, then send the full native history back to Gemini.
  4. Do not rebuild native model parts from Chat `assistant`/`tool_calls` messages; doing so would drop signatures.
- Continuation state lives only in the child process memory for one trial. Do not use `previous_interaction_id`, server-side store flags, or any other Google stateful interaction API.

### Request / response loop

- On a function-call response:
  1. Require exactly one candidate and at most one function call.
  2. Require a supported function name and an object of arguments.
  3. Require the mandatory `thoughtSignature` on the function-call part (Gemini 3 function-calling rule). Missing signature fails closed before any parent tool is treated as successfully continuable into a follow-up provider request.
  4. Preserve the complete native model content parts, including any `thoughtSignature` fields, in transport-owned history without logging their values.
  5. Return the existing `ProviderToolCall` / `ProviderReply` shapes to the worker so the parent JSONL protocol is unchanged.
- On the matching parent result, append a native Gemini user content block containing a `functionResponse` with the exact function-call name, exact function-call id, and the bounded result object. Send the complete prior native history back to Gemini, including the original model parts and their signatures exactly where received.
- Continue until the model returns final text without a function call, the parent returns an error result, `stop_investigation` succeeds, or an existing bound or transport failure ends the trial.
- Parse final text from native text parts. A response that contains both text and one function call returns both to the worker; text-only completion maps to `completed` through the existing worker behavior; successful `stop_investigation` still maps to `stopped`.
- Reject parallel or multiple function calls in this milestone, even though Gemini supports them, because the parent JSONL protocol intentionally permits one call per provider round.
- Apply existing independent request, conversation, tool-definition, response-byte, response-text, JSONL, subprocess, and trial-timeout bounds. Count opaque signatures toward serialized request-size limits but never include signature values in diagnostics.

## Edge Cases & Error Handling

- Missing API key or disabled parent network authorization fails before HTTP I/O with the existing bounded provider error behavior.
- A malformed native response, missing candidate/content/parts, missing function-call id, missing function name, invalid arguments, unsupported function name, multiple candidates, or multiple function calls fails closed as an adapter error.
- A Gemini function-call response without the required `thoughtSignature` fails closed before sending a function-result continuation request. The error must identify only the missing continuation field, never the response body or signature value.
- A model part containing a signature must remain a separate part in the exact original position. The transport must not merge, reorder, decode for display, or synthesize signatures.
- A parent tool result whose id or name does not match the pending Gemini function call fails closed without a second provider request.
- A provider HTTP 400, 401, 403, 429, 500, 502, 503, timeout, invalid JSON response, or connection failure remains an infrastructure-level adapter failure. It must not become a behavioral refusal or a verifier pass.
- HTTP error diagnostics may retain only the status code and a fixed safe category. They must not include response bodies, request bodies, headers, API keys, local paths, workspace contents, signature values, or model-authored free text.
- If the worker exits without a final message, the existing subprocess adapter records `adapter_error` and infrastructure censorship. No retry or replacement trial is created.

## Acceptance Criteria

- [ ] `google-gemini` is an approved worker transport and the worker rejects unknown transport identifiers.
- [ ] Execution policy requires `network_required: true` for `google-gemini`, matching the Responses policy posture.
- [ ] The Google model-matrix catalog and generated Google registrations select `google-gemini`; other provider registrations retain their current transports.
- [ ] Native request construction uses the expected Gemini endpoint, `x-goog-api-key`, model id, `contents`, function declarations, and bounded request serialization.
- [ ] A fake native response containing one function call and a `thoughtSignature` is parsed into the existing provider reply without exposing the signature in returned metadata, stderr, or artifacts.
- [ ] The subsequent fake request contains the exact original model parts, exact signature in its original part, and a matching native `functionResponse` with the exact call id and name.
- [ ] Text-only native responses produce a completed provider reply, and successful `stop_investigation` continues to map to `stopped` through the existing worker loop.
- [ ] Missing signatures, mismatched call ids, malformed parts, unsupported tools, multiple candidates, and multiple function calls fail closed before unsafe continuation.
- [ ] Provider HTTP failures, timeouts, oversized requests/responses, and invalid JSON produce bounded diagnostics without bodies, credentials, signatures, workspace paths, or hidden case data.
- [ ] A subprocess integration test exercises the Google transport against a local fake server through the parent-owned workspace tools and verifier.
- [ ] Offline tests do not contact Google or any external network and do not require a Google API key.
- [ ] Existing OpenAI, Responses, mock-worker, public-release, execution-policy, and model-matrix tests remain green.
- [ ] The full suite passes before any new live Google smoke is attempted.
- [ ] After implementation, a fresh two-trial Google smoke can be run with the existing local key and credits; the full Google batch remains blocked until that smoke completes without infrastructure censorship (operational gate, not a unit-test claim).
- [ ] No private chain-of-thought capture, signature logging, automatic retry, score, ranking, or provider-specific verifier logic is added.
