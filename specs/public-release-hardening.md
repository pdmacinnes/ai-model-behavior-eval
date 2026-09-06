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

- Inputs:
  - Existing `behavior_cases/*/family.json` files.
  - Existing batch manifests and run artifacts supplied to `build_public_behavior_release.py`.
  - Existing public-release artifacts supplied to `build_behavioral_report.py`.

- Public case projection:
  - Retain family-level task surface, allowed actions, action costs, maximum budget, and non-cause-specific perturbation types.
  - Retain only opaque variant count/order metadata needed to describe the fixture structure.
  - Remove variant-specific fixture source bodies, predefined cause-named hypothesis lists, observation prose, observation `reveals`, hidden causes, verifier declarations, calibration data, and other answer-key material.
  - Do not expose a public field that maps an opaque variant or slot to a cause.

- Public trace projection:
  - Retain event kind, action, target, accepted/rejected state, cost, error, remaining budget, and safe structural hashes or lengths where useful.
  - Remove inspected or edited source content and other full workspace payloads from action events.
  - Retain model-authored checkpoint hypotheses only as behavioral observations, after existing path and credential sanitization.
  - Continue excluding `adapter_result.json` and `final_response.txt`.

- Public batch and run projection:
  - Replace internal run identifiers with deterministic opaque public run identifiers in the release output.
  - Remove `variant_id`, `variant_slot`, and raw run IDs containing variant/repetition encodings from public manifests, run artifacts, and report fields.
  - Preserve enough opaque pairing metadata for the report to compare preregistered trials without revealing which member corresponds to which variant.
  - Preserve safe condition, family, repetition, execution, verifier status, verifier `passed`, and infrastructure-censorship fields.
  - Preserve registration projections without commands, credentials, paths, or internal trial identifiers.

- Behavioral report:
  - Build reports from the sanitized public projection without reconstructing variant identity from filenames or run IDs.
  - Mark censored runs as partial or unavailable behavioral observations. Their narratives must state that the episode was interrupted and must not present a complete repair/outcome story.
  - Exclude censored or missing-observation runs from paired behavioral comparisons.
  - Report decision-path fields separately from operational fields. A comparison may say that operational metadata changed without calling that a decision-path behavior change.
  - Retain verifier status and pass/fail as a separate outcome from behavioral evidence.
  - Keep the report descriptive and non-ranking.

- Report CLI:
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
- [ ] Public pairing remains reproducible and supports the expected preregistered comparisons without exposing variant-to-cause mapping.
- [ ] Public run verifier projections retain both safe `status` and boolean `passed` when present, while removing declarations and answer-key fields.
- [ ] Censored runs are clearly marked partial or unavailable, are excluded from paired comparisons, and do not receive a complete repair/outcome narrative.
- [ ] Decision-path comparison fields are separated from operational bookkeeping fields, and bookkeeping-only differences do not produce an overstated behavior-change narrative.
- [ ] The public README and root manifest accurately describe the new sanitization behavior, including removal of fixture source and cause-discriminating prose.
- [ ] The report CLI prints a bounded summary by default and prints the full report only with `--verbose`.
- [ ] New tests cover case-content redaction, trace-content redaction, opaque IDs/pairing, censored partial narratives, verifier `passed` preservation, bookkeeping-only comparisons, and quiet/verbose CLI behavior.
- [ ] Existing public sanitizer, release-builder, behavior-report, and full project test suites pass.
- [ ] The raw internal batch artifacts and the user’s local registration files remain unchanged.
