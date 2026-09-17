# Spec: Model-Matrix Audit Remediation and Recovery Runs

## Requirements & Goals

- Preserve every existing raw batch as immutable historical evidence.
- Produce a curated primary report that does not pool setup failures, smoke runs, alternate transports, or superseded duplicate full batches.
- Make provider transport, timeout, source revision, registration identity, and case-set identity auditable for every future batch.
- Prevent Windows text-encoding failures from censoring otherwise valid provider trials.
- Split evidence-budget depletion from rejected actions whose cost exceeds the remaining budget.
- Mark deferred Chinese-model conditions as pending until they are intentionally scheduled.
- Run targeted recovery and repair-completion audits without replacing the original constrained-protocol results.

## Scope

### 1. Harness and artifact provenance

Add safe, non-secret provenance fields to batch and run artifacts:

- source Git revision when available;
- provider transport;
- worker timeout and enclosing trial timeout;
- registration hash and a stable safe registration projection;
- case-set hash and harness version.

The implementation must never serialize credentials, endpoint values, command paths, workspace paths, or raw provider responses into publishable artifacts. Existing registration hashes remain valid historical identifiers.

### 2. Windows JSONL encoding

Make provider-worker JSONL output encoding-independent on Windows. Unicode model text must not cause a worker process to terminate before its final message. Add an offline regression test containing non-ASCII checkpoint and final-response text.

### 3. Budget annotation semantics

Extend behavioral analysis with separate fields:

- `budget_depleted`: remaining cost reached zero;
- `action_rejected_for_insufficient_budget`: at least one requested action cost exceeded remaining cost;
- retain a compatibility `budget_exhausted` field only where needed for historical reports, with documentation that it is a union of the two conditions.

Reports and narratives must use the more precise fields when available.

### 4. Curated report selection

Add an explicit report input selection mechanism so a release can name exact batch IDs. The curated primary release will use:

- `model-matrix-openai-full-v2`;
- `model-matrix-google-full-v2`;
- `model-matrix-xai-full-v2`;
- `model-matrix-anthropic-full-retry-v5`;
- `model-matrix-meta-full-meta-v2`.

Historical failed, smoke, duplicate, and alternate-transport batches remain available but are labeled separately and excluded from primary model profiles.

The resulting primary report must preserve the known scope: 108 planned trials, 100 usable trials, and 8 infrastructure-censored trials before recovery.

### 5. Matrix configuration and documentation

- Move DeepSeek, Qwen, and Kimi from active to pending in the committed model matrix.
- Update the multi-provider specification and tests to reflect the current 9-condition active matrix and Meta’s completed status.
- Document that native Gemini and OpenAI-compatible Gemini batches are separate transport conditions unless deliberately preregistered as a comparison.

### 6. Recovery runs

Create new, clearly named recovery batches. Never overwrite or relabel historical runs.

#### Infrastructure recovery

Retry the eight censored trials from the selected primary full batches after the encoding and provenance fixes. Preserve the original evidence-budget and case definitions. Increase only the provider conversation/worker headroom enough to distinguish infrastructure censorship from model behavior, and record the changed bound as an explicit recovery condition.

#### Repair-completion audit

Create a separate audit case set or registered budget override with unchanged prompts, visible files, variants, observations, and verifier logic, but generous evidence budgets sufficient for diagnosis plus repair:

- dashboard family: 14 cost units;
- pagination and session families: 8 cost units.

Run two repetitions for:

- Claude Opus 5;
- Meta Muse Spark 1.3;
- Claude Sonnet 5 as a comparison control.

Keep this audit separate from the primary report because it answers a different question: repair completion under adequate evidence budget.

### 7. Partial-visibility limitation

Document that the session cases intentionally omit some implementation details. Do not change the primary case definitions in this remediation. If a full-visibility repair arm is added later, it must be a separate preregistered condition and report.

## Inputs, Outputs & Behavior

Inputs include the current case families, historical batch artifacts, committed model matrix, provider credentials already configured by the user, and the approved live-provider execution path.

Outputs include:

- updated harness and tests;
- updated model matrix and specification;
- a curated primary sanitized release and report;
- recovery batch artifacts for previously censored primary trials;
- a separate repair-completion audit release and report;
- an audit note describing retained historical batches and exclusions.

All paid provider calls must remain behind the existing explicit live-network execution gate. No credential value may be written to source, registration artifacts, reports, or commits.

## Edge Cases & Error Handling

- If a provider credential or balance is unavailable, record the batch as blocked or infrastructure-censored; do not reinterpret it as behavior and do not silently retry.
- If a recovery trial still reaches a bound, retain it as censored with the exact bound category.
- If a provider returns a final response without an explicit stop action, report that termination separately from provider failure and budget state.
- If a historical batch lacks recoverable transport or timeout metadata, label the metadata unavailable rather than inferring it from the model result.
- If the curated report has duplicate run IDs, mismatched case hashes, missing artifacts, or mixed case-set hashes, fail closed before writing the release.
- If the broader historical report is rebuilt, it must be labeled archival and must not be presented as the primary comparison.

## Acceptance Criteria

- [ ] Existing historical batch directories and reports are unchanged.
- [ ] Provider-worker JSONL output survives non-ASCII text on Windows in an offline test.
- [ ] Batch/run artifacts expose safe transport, timeout, source-revision, registration, and case-set provenance.
- [ ] Budget analysis distinguishes zero remaining cost from rejected over-budget actions.
- [ ] The model matrix contains only the nine currently active conditions, with the three Chinese conditions pending.
- [ ] The curated primary report contains exactly the five selected full-batch sources and reports 108 planned, 100 usable, and 8 censored trials before recovery.
- [ ] The eight selected infrastructure-censored trials are rerun in new recovery batches, with recovery bounds recorded.
- [ ] The repair-completion audit runs Opus, Meta, and Sonnet for all six variants and two repetitions under the increased budgets.
- [ ] Recovery and repair-completion results are not merged into the original constrained primary report.
- [ ] Public-release sanitization continues to exclude credentials, endpoint values, commands, local paths, raw adapter results, and final provider responses.
- [ ] Existing tests pass, new audit tests pass, and all generated reports validate before any result is called complete.
