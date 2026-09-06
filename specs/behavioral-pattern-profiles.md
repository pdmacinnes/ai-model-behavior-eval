# Spec: Behavioral Pattern Profiles

## Requirements & Goals

Add descriptive profiles to the public behavioral report so readers can see recurring observable patterns for each registered condition without turning the study into a leaderboard. Profiles must describe what happened in the traces, not infer model quality or hidden causes.

## Inputs, Outputs & Behavior

The existing report builder groups report runs by `condition_id` and adds a top-level `profiles` array. Each profile contains:

- the condition metadata already allowlisted in the report;
- `run_count` and sorted `family_ids` for context;
- `observed_patterns`, each with a stable pattern name, occurrence count, and sorted public run ids.

Pattern names are structural and finite:

- `infrastructure_censored`;
- `no_accepted_actions`;
- `evidence_first_list_files`, `evidence_first_inspect`, `evidence_first_search`, or `evidence_first_trace`;
- `hypothesis_checkpoint_recorded`;
- `repair_attempted` or `no_repair_edit`;
- `budget_exhausted`;
- `rejected_action_recorded`.

Patterns are derived only from the report’s allowlisted run fields. A censored run receives only the censorship pattern and is not classified as a behavioral no-action pattern. A run may contribute to multiple patterns. Counts are supporting context, not scores.

Profiles are sorted by condition id and pattern names. The output must retain the existing run narratives and comparisons unchanged.

## Edge Cases & Error Handling

- Conditions with no accepted actions are described neutrally as `no_accepted_actions` unless infrastructure-censored.
- Missing or null condition ids use `redacted` as the grouping key.
- Missing behavior annotations do not raise; only patterns supported by known boolean/count fields are emitted.
- Unknown fields are ignored and cannot appear in a profile.
- The profile builder must not compare conditions, rank them, or emit a composite score.

## Acceptance Criteria

- [ ] Reports contain deterministic condition-level profiles with finite structural pattern names.
- [ ] Profiles include counts only as supporting context and do not contain scores or rankings.
- [ ] Censored, empty, and ordinary runs are classified distinctly.
- [ ] Tests cover pattern derivation, grouping, ordering, and redaction.
- [ ] The full existing suite passes and the completed change is committed separately.
