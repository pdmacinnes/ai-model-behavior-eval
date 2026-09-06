# Spec: Public Release Answer-Key and Report Hardening

## Requirements & Goals

- Harden the public-release projection so it does not publish cause-discriminating fixture prose, fixture source bodies, or recoverable variant mappings while still exposing useful behavioral evidence.
- Make the public release README and manifest accurately describe what is and is not removed.
- Preserve public behavioral evidence such as accepted actions, targets, costs, checkpoints, model hypotheses, termination, verifier status, and censorship status without publishing raw provider responses.
- Make censored runs visibly partial and prevent them from being described as complete behavioral episodes or included in paired behavioral comparisons.
- Preserve non-declarative verifier outcomes, including the boolean `passed` field, in public run artifacts.
- Make paired comparisons opaque: public consumers may see that runs were paired, but must not be able to map a public run or comparison to variant 1 versus variant 2 or to a hidden cause.
- Separate decision-path changes from operational bookkeeping changes in comparison narratives so budget, confidence, or remaining-cost churn alone does not produce an overstated “behavior changed” claim.
- Make the report builder quiet by default, printing a compact summary and output path instead of the complete report. Provide an explicit verbose mode for full output when needed.
- Keep raw internal artifacts unchanged and keep the existing no-score, no-ranking report design.
- Non-goals:
  - changing the behavioral cases, model prompts, provider adapters, or verifier logic;
  - running provider calls;
  - adding operating-system sandboxing or secret scrubbing to raw internal artifacts;
  - making the public release a replayable model input package;
  - introducing model rankings or composite scores.

## Inputs, Outputs & Behavior

### Inputs

- Existing `behavior_cases/*/family.json` files.
- Existing batch manifests and run artifacts supplied to `build_public_behavior_release.py`.
- Existing public-release artifacts supplied to `build_behavioral_report.py`.

### Public case projection

- Retain family-level task surface (`initial_context`), `allowed_actions`, `action_costs`, `max_cost` / related bounds, `family_id`, `dimension`, and non-cause-specific perturbation types.
- Retain only opaque variant count metadata (for example `variant_count`) needed to describe that the family is paired. Do not emit ordered public variant objects that still carry files or observations.
- Remove variant-specific fixture source bodies (`files`), predefined cause-named hypothesis lists (`hypotheses`), observation objects (including `content`, `target`, and `reveals`), `hidden_cause`, verifier declarations, calibration data, `surface_signature` when it is only duplicated metadata, and other answer-key material.
- Do not expose a public field that maps an opaque variant or slot to a cause.

### Public trace projection

- Retain event `kind`, `action`, `target`, accepted/rejected state, `cost`, `error`, `remaining_cost`, and safe structural hashes or lengths where useful (for example existing `before_sha256` / `after_sha256` on edits).
- Remove action `content` payloads by default, including inspected source, search hit bodies, `list_files` listings, and other workspace text. Do not copy arbitrary workspace content into the public release.
- Retain model-authored checkpoint hypotheses (`leading_hypothesis`, `alternative_hypothesis`, confidence, `changed_by`, `next_action`) only as behavioral observations, after existing path and credential sanitization. Model text may still paraphrase a cause; that residual is accepted and must be described honestly in the README.
- Continue excluding `adapter_result.json` and `final_response.txt`.

### Public batch and run projection

- Replace internal run identifiers with deterministic opaque public run identifiers in the release output (run directories, `run.json`, manifests, registrations, and reports).
- Recommended public ID form: a stable prefix plus a hex digest derived from the internal run ID (for example `pub-` + first 16–32 hex chars of SHA-256), unique within the release, with no variant/repetition encoding in the string.
- Remove `variant_id`, `variant_slot`, and raw run IDs containing variant/repetition encodings from public manifests, run artifacts, and report fields.
- Preserve enough opaque pairing metadata for the report to compare preregistered trials without revealing which member corresponds to which variant:
  - Emit a deterministic `pair_id` (or equivalent) from batch, condition, family, and repetition.
  - Attach each public run to that `pair_id` without labeling members as slot 1 vs slot 2.
  - Paired comparisons list the two opaque public run IDs in lexicographic order (or another slot-independent order), never as `first_variant_slot` / `second_variant_slot`.
- Preserve safe condition, family, repetition, execution, verifier `status`, verifier `passed`, and infrastructure-censorship fields.
- Preserve registration projections without commands, credentials, paths, or internal trial identifiers.
- Manifest validation must reject public outputs that still contain forbidden keys (`variant_id`, `variant_slot`, `command`, credential-like keys, etc.), local paths, or non-opaque run identifiers.

### Behavioral report

- Build reports from the sanitized public projection without reconstructing variant identity from filenames or run IDs (remove `_inferred_trial_fields` and similar decoding).
- Mark censored runs as partial or unavailable behavioral observations. Their narratives must state that the episode was interrupted and must not present a complete repair/outcome story (no full evidence-path + repair + verifier storyline).
- Exclude censored or missing-observation runs from paired behavioral comparisons.
- Report decision-path fields separately from operational fields:

  **Decision-path fields:** `action_sequence`, `target_sequence`, `action_counts`, `first_action`, `first_target`, `actions_before_first_edit`, `first_edit_target`, `repair_attempted`, `edit_count`, `termination_reason`, `checkpoint_count`, `leading_hypotheses`.

  **Operational fields:** `confidence_sequence`, `rejected_action_count`, `remaining_cost`, `budget_exhausted`.

  A comparison may report `decision_behavior_changed` and/or `operational_metadata_changed`. Bookkeeping-only differences must not be narrated as a decision-path behavior change.
- Retain verifier status and pass/fail as a separate outcome from behavioral evidence.
- Keep the report descriptive and non-ranking.

### Report CLI

- Default output writes the report file and prints only a compact summary containing source kind, run count, profile count, comparison count, censored count, and output path.
- `--verbose` may print the full report for local debugging.

## Edge Cases & Error Handling

- A case variant has fixture files or observation content but no explicit hidden-cause field: treat the content as potentially cause-discriminating and remove it from the public projection.
- A trace event has `content` that is not source code: remove it unless it is explicitly classified as safe structural metadata; never copy arbitrary workspace content by default.
- A censored run contains a partial trace or annotations: preserve only the allowed structural and behavioral fields, mark the observation partial, and do not generate a complete repair narrative.
- A run or manifest lacks the metadata needed to establish an opaque pairing: fail closed with a clear error rather than guessing or exposing internal identifiers.
- A public manifest contains an internal forbidden key, local path, command, credential, raw run ID, or variant slot: reject the release build before writing a publishable output.
- Rebuilding the same source into a clean output root produces stable public identifiers and equivalent sanitized content.
- Existing raw artifact trees may contain stderr, response bodies, source text, or credentials: the hardening pass must not modify them, and those values must not be copied into the public output.
- A report contains only operational-field differences: report the changed operational fields without labeling the decision behavior as changed.
- The report CLI must preserve its nonzero failure behavior for malformed or unsafe input while keeping normal logs bounded.

## Acceptance Criteria

- [ ] Public case-family files contain no fixture source bodies, observation `content`, predefined cause-named `hypotheses`, `reveals`, `hidden_cause`, verifier declarations, or calibration data.
- [ ] Public event traces contain no full inspected or edited workspace source content and no raw provider response artifact.
- [ ] Public manifests, registrations, run files, and reports contain no internal `variant_id`, `variant_slot`, or raw run identifier that encodes a variant.
- [ ] Public run IDs are deterministic, opaque, unique within a release, and do not reveal variant or repetition encoding.
- [ ] Public pairing remains reproducible and supports the expected preregistered comparisons without exposing variant-to-cause mapping or slot labels.
- [ ] Public run verifier projections retain both safe `status` and boolean `passed` when present, while removing declarations and answer-key fields.
- [ ] Censored runs are clearly marked partial or unavailable, are excluded from paired comparisons, and do not receive a complete repair/outcome narrative.
- [ ] Decision-path comparison fields are separated from operational bookkeeping fields, and bookkeeping-only differences do not produce an overstated behavior-change narrative.
- [ ] The public README and root manifest accurately describe the new sanitization behavior, including removal of fixture source and cause-discriminating prose, and note that model checkpoint text may still paraphrase causes.
- [ ] The report CLI prints a bounded summary by default and prints the full report only with `--verbose`.
- [ ] New tests cover case-content redaction, trace-content redaction, opaque IDs/pairing, censored partial narratives, verifier `passed` preservation, bookkeeping-only comparisons, and quiet/verbose CLI behavior.
- [ ] Existing public sanitizer, release-builder, behavior-report, and full project test suites pass.
- [ ] The raw internal batch artifacts and the user’s local registration files remain unchanged.
