# Spec: Trusted Provider Execution Policy

## Requirements & Goals

- Define the conditions under which the OpenAI-compatible provider worker may make live network requests.
- Close the two medium findings from the `3368fd9` review before any real provider execution: unrestricted credential-environment selection and unbounded outbound request/conversation growth.
- Keep live execution unattended at the batch level. A user may explicitly authorize one batch, but the runner must not ask for approval per trial.
- Permit network access only for the repository's reviewed provider-worker entrypoint, not for arbitrary subprocess commands or model-generated workspace actions.
- Preserve parent-owned evidence tools, workspace edits, verification, timeouts, infrastructure censorship, and public artifact boundaries.
- Keep credentials out of registrations, commands, task messages, logs, diagnostics, and artifacts.
- Keep the current default fail-closed behavior: no network-required registration runs without an explicit execution authorization.
- Do not add an OS sandbox, container runtime, provider-specific model claims, retry policy, score, leaderboard, or private chain-of-thought capture in this milestone.

## Inputs, Outputs & Behavior

### Execution authorization

The live path requires all of the following before the first worker starts:

- The registration declares `network_required: true` on every condition that will make provider HTTP calls.
- Those conditions use the reviewed provider-worker adapter identifier and approved worker entrypoint.
- The caller supplies one explicit batch-level `--allow-network` execution flag on the pilot runner (`scripts/run_model_pilot.py` or the equivalent library entrypoint argument).
- The registration and worker configuration pass all static validation checks.

The runner must reject network-required registrations when the flag is absent, and must reject the flag when the registration does not declare network use on any condition. Authorization applies to the current process only and is never serialized into registrations, manifests, or artifacts, and is never carried into subsequent runs. No per-trial approval prompt is allowed.

**Batch flag vs worker gate:** The batch-level `--allow-network` is the only user-facing authorization. The parent injects a non-secret, parent-owned child environment marker (for example `EVIDENCE_EVAL_NETWORK_AUTHORIZED=1`) into approved live workers only after validation succeeds. The worker enables HTTP only when that marker is present; a worker-local CLI `--allow-network` flag is removed or rejected so a direct child invocation cannot open the live path without the parent policy. Mock transport remains available without the marker.

The current credential-free and `network_required: false` paths remain unchanged. Existing reference and mock workers must continue to run without network authorization.

If a registration mixes network and non-network conditions, the batch flag is required because network use is declared; non-network conditions must still use non-live worker identities and must not receive the network authorization marker or credential passthrough.

### Trusted worker allowlist

Only the reviewed OpenAI-compatible provider worker may use the live network policy. Validation must require:

- The exact approved adapter identifier: `jsonl-provider-worker`.
- An approved command shape whose executable is the current Python interpreter and whose script path resolves to the repository entrypoint `scripts/openai_compatible_workspace_worker.py` (path normalized; no `..` escape outside the repo), or an equivalent content-hash check over that entrypoint plus `src/evidence_eval/provider_worker.py` that the policy module pins and documents.
- Allowed optional argv for the live worker is restricted to an explicit list (for example `--transport openai-compatible` and bound numeric flags already defined by the worker). Forbidden: `--api-key-env`, shell wrappers (`cmd`, `bash`, `-c`), extra interpreters, helper scripts, or additional network-capable commands.
- No custom child working directory (existing subprocess adapter rule remains).
- No arbitrary shell wrapper, command interpolation, or additional network-capable helper command.

The bound worker content hash, when used, is a constant maintained in the execution-policy module. If the reviewed files change, validation fails until the constant is deliberately updated as part of a reviewed policy change.

The worker remains a trusted wrapper. Model output can request only the four parent-mediated workspace methods, and the parent continues to execute and verify those methods.

### Credential environment policy

The worker reads exactly one project-specific environment variable: `EVIDENCE_EVAL_PROVIDER_API_KEY`.

- The command-line `--api-key-env` override is removed or rejected.
- For live network trials, the parent subprocess adapter explicitly passes only this allowlisted variable when it is present (`credential_env_names=("EVIDENCE_EVAL_PROVIDER_API_KEY",)`). Non-network trials do not receive credential passthrough.
- The variable name, not its value, may appear in internal configuration if needed for diagnostics; the value must never appear in any artifact or retained stderr.
- Standard provider variable names such as `OPENAI_API_KEY` do not reach the child through implicit inheritance. Supporting one later requires a separate reviewed allowlist change.
- A missing credential fails before an HTTP request is sent. The batch may also preflight credential presence once before the first live trial; either way, failure must not expose the variable value.

### Outbound request and conversation bounds

The provider transport must enforce independent limits before every HTTP request:

- Maximum serialized request bytes.
- Maximum number of conversation messages.
- Maximum serialized conversation characters.
- Maximum tool-definition bytes.
- Existing maximum provider response bytes and response-text characters.
- Existing maximum provider rounds and parent JSONL message size.

The request body must be serialized once, measured, and rejected before `urlopen` when any request bound is exceeded. Tool results and assistant messages must be bounded as they enter the conversation so the worker cannot defer the overflow until a later request. Error messages must identify only the bound that failed and must not include request bodies, credentials, workspace contents, or authorization headers.

Concrete default ceilings may be chosen in implementation, but they must be positive, documented next to the transport, and covered by overflow tests that never open external sockets.

### Normal live batch flow

1. Load and validate the versioned registration.
2. Validate the worker identity, network declaration, credential policy, timeouts, and all request/message bounds.
3. Require the explicit batch-level network authorization flag when network is declared; reject the flag when network is not declared.
4. Run deterministic case validation and calibration before any provider request.
5. For each planned live trial, construct `SubprocessAdapterConfig` with the approved command, credential passthrough limited to `EVIDENCE_EVAL_PROVIDER_API_KEY`, and the parent-owned network authorization marker in the child environment.
6. Let the worker make bounded provider requests and use only the parent JSONL tool protocol.
7. Let the parent record observable traces, edits, checkpoints, final status, verifier outcome, and infrastructure censorship.
8. Continue after a censored or behavioral failure without retrying or replacing the trial.
9. Write the existing publishable manifest without commands, credential values, local paths, raw adapter output, or final response files.

Replace the current hard rejection text that says network is unsupported before a “provider sandbox policy” exists with this execution-policy validation. OS/container sandbox remains explicitly out of scope.

No live provider call is made by unit tests, case calibration, public-release building, or registration validation.

## Edge Cases & Error Handling

- A network-required registration without the explicit batch flag fails before case execution or worker startup.
- A non-network registration supplied with the live-network flag fails closed rather than silently broadening its policy.
- An unapproved adapter identifier, worker path, worker hash, command wrapper, or custom working directory fails validation before any worker starts.
- A `--api-key-env` argument or equivalent override is rejected; only `EVIDENCE_EVAL_PROVIDER_API_KEY` is accepted.
- A missing credential fails before network I/O and is recorded as an adapter or preflight failure without exposing the variable value.
- A request exceeding bytes, message count, conversation characters, tool-definition bytes, response bytes, or response text limits fails before the next provider request or is recorded as a bounded provider failure.
- A provider timeout, HTTP error, malformed response, or transport failure remains an infrastructure-level adapter failure and cannot become a behavioral refusal or suppress verification by itself.
- Credential values, authorization headers, request bodies, response bodies, workspace paths, hidden causes, verifier declarations, and local environment values must not be included in stderr tails, exception text, metadata, or publishable manifests. Environment **names** used by the allowlist may appear in diagnostics; values must not.
- Parent timeouts still terminate the child before finalizing the trial record. No live worker may remain active while a verifier runs.
- The public release builder continues to omit raw adapter results and final response files and must accept a network-authorized manifest only when its publishable fields pass the existing gate.
- If the approved worker implementation changes, the bound worker hash becomes invalid until the policy is re-reviewed and updated.

## Acceptance Criteria

- [ ] A versioned execution-policy validation path requires `network_required: true`, the approved worker identity, and one explicit batch-level network flag before live execution.
- [ ] Network-required registrations remain rejected by default when the flag is absent.
- [ ] Non-network registrations reject the live-network flag rather than silently accepting it.
- [ ] Arbitrary worker commands, wrappers, custom working directories, and unapproved adapter identifiers cannot use the live network policy.
- [ ] The worker accepts only `EVIDENCE_EVAL_PROVIDER_API_KEY`; arbitrary `--api-key-env` overrides are rejected.
- [ ] The worker enables HTTP only when the parent-owned network authorization marker is present; worker-local `--allow-network` is removed or rejected.
- [ ] The parent explicitly passes only the approved credential variable for live trials, and tests prove standard provider variables remain stripped unless separately approved.
- [ ] Missing credentials fail before any HTTP request is attempted.
- [ ] Outbound request bytes, conversation message count, conversation size, and tool-definition size are independently bounded before each request, and conversation appends are bounded as they enter the conversation.
- [ ] Tests cover request overflow, conversation overflow, credential rejection, HTTP timeout, and sanitized diagnostics without making external network calls.
- [ ] The existing parent timeout, queue, verifier, and infrastructure-censorship tests remain green.
- [ ] A local fake HTTP transport can exercise request/response parsing without permitting the live network gate.
- [ ] The existing mock/reference workers and public sanitizer continue to pass without network authorization.
- [ ] No live provider call is made as part of implementation or automated tests.
- [ ] The implementation adds no score, ranking, retry, OS sandbox, container policy, or private chain-of-thought capture.
