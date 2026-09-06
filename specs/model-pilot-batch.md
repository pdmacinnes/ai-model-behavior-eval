# Spec: Unattended Model Pilot Batch

## Requirements & Goals

- Move the project from deterministic proof policies to repeatable real-model trials without changing the approved case protocol.
- Provide one provider-neutral batch runner that can execute any model wrapper implementing the existing JSONL subprocess workspace adapter contract.
- Keep the pilot unattended: a batch must run all registered conditions, case variants, and repetitions without per-trial human approval.
- Freeze the exact model condition, prompt, tool contract, case hash, repetition index, and harness version for every trial.
- Preserve the project's descriptive purpose. The batch must collect observable decisions and evidence paths, not compute a composite score or model ranking.
- Make the first pilot small enough to debug operationally while retaining paired-case comparisons.
- Keep credentials and provider-specific configuration outside committed files. Provider workers may read credentials from their process environment, but the runner must never serialize credential values into artifacts.
- Make infrastructure censorship parent-owned. Only the parent runner may mark a run `infrastructure_censored` or skip the verifier because of a timeout, transport failure, malformed or oversized JSONL, output flood, invalid process exit, or forced termination. A child final status can never cause censorship.

## Inputs, Outputs & Behavior

### Pilot registration

The batch runner accepts a versioned registration containing:

- A registration schema version. Unknown top-level or condition fields are rejected.
- A batch identifier and harness version.
- One or more model conditions with provider, model identifier, adapter identifier, reasoning setting, worker command, and an explicit `network_required` boolean.
- A repetition count for each condition.
- The case-family root and selected family identifiers.
- The artifact output root.
- The workspace parent and per-trial timeout.

`reasoning_effort` is either a string or explicit `null`. `network_required` is a boolean and must be `false` for this batch runner until an explicit provider sandbox policy exists. Worker conditions do not accept a `cwd` field or any equivalent workspace-root override.

Worker commands are executed through `SubprocessWorkspaceAdapter`. The runner passes no workspace path, verifier object, hidden cause, or answer-key annotation to the worker. A worker may use only the JSONL workspace tool protocol. The in-repository deterministic reference worker is a policy script, not a real model and requires no API key.

The initial pilot registration defaults are:

- All three existing paired families.
- Both variants in every family.
- Three repetitions per condition for the smoke batch.
- Five repetitions per condition for the first public pilot after the smoke batch passes.

The model list remains registration data rather than a code assumption. Adding a condition must not alter existing case files, prompts, tool contracts, or verifier behavior.

### Batch flow

1. Validate every selected case family and run deterministic calibration before starting any model trial.
2. Validate each registration, including safe identifiers, non-empty commands, positive repetition counts, and a worker timeout shorter than the enclosing trial timeout.
3. For each condition, family, variant, and repetition, create a stable run identifier from the batch, condition, family, variant, and repetition index.
4. Materialize a fresh workspace and execute exactly one subprocess worker for the trial.
5. Record the existing immutable trial artifacts, including the model condition, case and tool-contract hashes, event trace, checkpoints, final response, mutation record, execution status, verifier result, and behavioral annotations.
6. On a parent-detected timeout, terminate and, if necessary, kill the subprocess before completing the trial record. Mark the run infrastructure-censored and skip verification. Do not rely on abandoning only the enclosing Python thread.
7. Continue to the next registered trial after an infrastructure-censored or behavioral failure. Do not retry, replace, or silently omit a failed trial.
8. Write a batch manifest containing registration hashes, planned trial identifiers, actual outcomes, start/end timestamps, and counts grouped by condition and case family.
9. Refuse to overwrite an existing batch or run artifact. A rerun must use a new batch identifier and remain distinguishable in public provenance.
10. Allow the existing public release builder to sanitize the resulting case and run artifacts after the batch completes.

### Batch manifest

The manifest uses schema `evidence-bounded-debugging-batch-v1` and contains:

- The batch identifier, registration hash, case-set hash, harness version, and timestamps.
- The complete planned trial list, including run ID, condition ID, family, variant, and repetition index.
- The actual result list, including execution status, parent-owned infrastructure-censorship flag, verifier status, and verifier pass/fail.
- Aggregate counts grouped by condition and family. These are descriptive bookkeeping, not a score.

The manifest is publishable provenance and must not contain worker commands, environment values, credentials, workspace paths, hidden causes, verifier declarations, or raw answer-key annotations. The source registration remains internal because it contains local command paths.

### Observable pilot outputs

The batch output must support questions such as:

- Which evidence action was selected first for each case variant?
- Did the model inspect discriminating evidence before editing?
- Did the model change its leading hypothesis after contradictory evidence?
- Did the paired underlying cause change the investigation path while the visible symptom stayed comparable?
- Did repeated runs of one frozen condition converge on one path or reveal meaningful variation?
- Did the model stop, refuse, or continue when evidence was insufficient?

The runner may include counts and verifier outcomes as supporting fields, but it must not emit a single headline score or rank order.

## Edge Cases & Error Handling

- Invalid case calibration blocks the batch before any real-model invocation.
- An unknown family, variant, condition, adapter, or registration field fails closed with a clear validation error.
- A worker timeout, malformed JSONL message, oversized message, bounded queue/output flood, process failure, or protocol violation produces an infrastructure-censored run and does not trigger an automatic retry.
- A worker-reported infrastructure status is treated as behavioral completion metadata, not as authority to skip the runner-owned verifier.
- A worker-reported refusal, insufficient-evidence result, or early stop remains a valid behavioral outcome.
- A verifier failure remains separate from adapter lifecycle status. The batch must retain both fields without relabeling one as the other.
- If one trial leaves a deferred workspace after a timeout, the batch records the cleanup state and continues without reusing that workspace.
- If a run or batch identifier already exists, the runner refuses to overwrite it.
- If the worker command references a missing executable or exits before its final message, the run is recorded as infrastructure-censored and the batch proceeds.
- If a registration contains a `cwd`, workspace path, case-root override, unknown field, or `network_required=true`, validation fails before any worker invocation.
- Raw adapter results and final response files are excluded from the public release in version one. If a provider worker writes credentials, workspace paths, or hidden case data into structured publishable artifacts such as the batch manifest, publication is blocked. Version one does not claim to scrub arbitrary free text; the sanitizer must not be described as a secret-removal system.
- If a provider requires network access, that requirement must be declared in the condition and handled by the future provider sandbox policy. The batch runner itself must not silently broaden filesystem or network access.

## Acceptance Criteria

- [ ] A versioned pilot registration can describe multiple model conditions, selected case families, variants, repetitions, timeouts, and artifact roots without embedding secrets.
- [ ] The batch runner validates all cases and registrations before invoking the first worker.
- [ ] The runner creates stable, collision-resistant run identifiers and refuses to overwrite prior batch or run artifacts.
- [ ] The runner executes every planned trial without human approval prompts and continues after individual infrastructure or behavioral failures.
- [ ] Every trial uses the existing subprocess workspace adapter and preserves the current parent-owned verifier boundary.
- [ ] Only parent-detected timeout, transport, malformed-message, oversized-message, output-flood, process-exit, or forced-termination conditions can mark a run infrastructure-censored or skip verification.
- [ ] A parent timeout terminates and, if necessary, kills the child subprocess before the trial is finalized.
- [ ] The subprocess transport enforces a concrete maximum message size and pending-output queue bound.
- [ ] Registration rejects custom `cwd` or equivalent workspace-root overrides and rejects undeclared fields.
- [ ] A batch manifest records planned trials, completed outcomes, infrastructure censorship, verifier outcomes, and provenance hashes.
- [ ] An in-repository deterministic reference JSONL worker, requiring no credentials, can complete a full smoke batch across all three pilot families and both variants.
- [ ] Tests cover registration validation, stable identifiers, no-overwrite behavior, continuation after failure, and manifest aggregation.
- [ ] The smoke batch produces artifacts accepted by the existing public release sanitizer.
- [ ] The publishable batch manifest contains provenance only and excludes commands, environment values, credentials, workspace paths, and hidden case annotations.
- [ ] Raw adapter results and final response files are excluded from public release; structured batch manifests are rejected when they contain known credential/path/answer-key fields.
- [ ] Version one makes no unsupported claim that arbitrary free text is scrubbed.
- [ ] The implementation does not add a composite score, leaderboard, or model-ranking field.
- [ ] The implementation is complete only after the full test suite and deterministic smoke batch pass.
