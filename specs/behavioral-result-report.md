# Spec: Public Behavioral Result Report

## Requirements & Goals

Create a provider-neutral, read-only report builder that turns completed pilot artifacts into a concise description of observable model behavior. The report is for understanding why a model made a decision, not for producing a composite score, ranking models, or replacing the raw run artifacts.

The report must:

- summarize evidence acquisition and action choices from `event_trace.json` or its nested trace;
- preserve checkpoint hypotheses and confidence as observable annotations;
- distinguish repair attempts, budget exhaustion, ordinary stopping, and infrastructure censorship;
- keep verifier outcomes separate from behavioral observations;
- compare paired variant slots descriptively without claiming causality automatically;
- accept internal artifacts or an already-sanitized public release;
- be safe to publish even when its input came from internal artifacts.

The report builder must not make live provider calls, inspect workspaces, read answer-key fields, or modify source artifacts.

## Inputs, Outputs & Behavior

Add a small library module and CLI script. The CLI accepts:

- `--artifacts-root`, pointing to a pilot artifact tree containing `batches/` and `runs/`;
- `--output`, the report JSON path;
- optional `--public-root`, pointing to a public release tree. When supplied, it is used as the source instead of `--artifacts-root`.

Exactly one source option is required. The output parent is created if needed.

The output schema is `evidence-bounded-debugging-behavior-report-v1` and contains:

- `schema` and `report_version`;
- `source`, with source kind, batch ids, and run count;
- `runs`, one entry per run with public condition metadata, execution status, censorship state, verifier status, and a `behavior` object;
- `comparisons`, grouped by condition, family, repetition, and variant slot where paired runs are available;
- `limitations`, explicitly stating that the report is descriptive and does not establish causal claims or model rankings.

Each public run entry may contain only:

- run, batch, condition, family, repetition, and variant-slot identifiers already present in sanitized artifacts;
- provider, model id, adapter id, and reasoning effort from sanitized condition metadata;
- execution status, infrastructure-censored state, verifier status, and verifier pass state;
- the following behavior fields from `analyze_trace`: action sequence, target sequence, action counts, first action/target, actions before first edit, first edit target, repair attempted, edit count, termination reason, budget exhausted, checkpoint count, leading hypotheses, confidence sequence, rejected action count, and remaining cost.

The report must never emit `variant_id`, hidden causes, verifier declarations, calibration data, reveals or revealed factors, workspace paths, commands, credentials, adapter results, final responses, or arbitrary unknown fields from input artifacts. Internal variant ids are converted to the public `variant_slot` when available and otherwise represented as `redacted`.

Comparisons are descriptive paired observations. Each comparison contains the grouping keys, the two public variant slots when available, changed behavioral fields, and `comparison_is_causal_only_if_pre_registered: true`. It must not contain hidden environment fields or a score.

The builder reads only `manifest.json`, `run.json`, `event_trace.json`, and `behavioral_annotations.json` under the source tree. Missing optional event/annotation files produce a run with null/empty behavior fields and a source warning. Malformed JSON or a malformed batch manifest fails closed with a clear error before writing the report. Incomplete runs are included only when a valid `run.json` exists; the source section records skipped directories.

## Edge Cases & Error Handling

- A public release may have redacted variant ids and no internal batch registration. The report must still build, preserving `variant_slot` if present in run ids or manifest planned trials and otherwise using `redacted`.
- A run with infrastructure censorship must retain that state and verifier status but must not be interpreted as a behavioral failure.
- A run with no accepted actions must produce empty sequences and null first-action fields, not an exception.
- Duplicate run ids are rejected.
- Unknown input fields are ignored rather than copied into the report.
- A comparison is emitted only when two distinct variant slots can be paired within the same condition, family, and repetition. Unpaired runs remain in `runs`.
- Output is deterministic: source files and all report arrays are sorted by stable identifiers.

## Acceptance Criteria

- [ ] A dependency-free report library and CLI exist and support internal artifacts and sanitized public releases.
- [ ] The report contains observable behavior fields and separate verifier/censorship fields without scores or ranking.
- [ ] Paired comparisons expose changed behavioral fields and explicitly avoid automatic causal claims.
- [ ] Hidden answer-key fields, raw provider outputs, credentials, commands, paths, and unknown input fields cannot appear in output.
- [ ] Missing optional behavior files are handled deterministically; malformed required JSON fails closed; duplicate run ids are rejected.
- [ ] Tests cover a complete paired report, censorship separation, public-input compatibility, redaction, malformed input, duplicate ids, and deterministic ordering.
- [ ] The existing test suite and the new report tests pass.
- [ ] The implementation is committed separately from unrelated user-local registration files.
