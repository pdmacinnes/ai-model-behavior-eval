# Spec: Public Behavioral Case Narratives

## Requirements & Goals

Add one deterministic narrative per condition/batch/case family to connect paired run observations into a reader-facing case summary. The narrative must explain what changed or stayed stable in observable behavior without claiming that an intervention caused the change unless the comparison was pre-registered.

## Inputs, Outputs & Behavior

Extend the behavioral report with a sorted `case_narratives` array. Each entry contains:

- batch id, condition id, family id, run count, repetition count, and observed variant slots;
- `paired_comparison_count` and `behavior_changed_comparison_count` as descriptive context;
- a sorted union of changed behavioral fields;
- `verifier_status_counts` and `infrastructure_censored_count` as separate outcome context;
- `narrative`, a deterministic paragraph describing paired behavioral differences or the absence of a pair, followed by the causal-language limitation.

Groupings must not mix batches, conditions, or families. The narrative may mention action, hypothesis, stopping, or repair fields by name, but must not include hidden causes, verifier declarations, raw provider text, scores, rankings, or claims that one model is better.

## Edge Cases & Error Handling

- A group with no complete paired variants gets a neutral “no paired comparison was available” narrative.
- A group with paired runs but no changed fields says the compared observable fields were preserved.
- Infrastructure-censored runs contribute to the separate censorship count but do not become behavioral failures or behavioral pair comparisons.
- Missing verifier statuses are counted as `unavailable` only in the outcome context.
- Output ordering is deterministic and unknown input fields are ignored.

## Acceptance Criteria

- [ ] Reports contain deterministic case narratives grouped by batch, condition, and family.
- [ ] Narratives distinguish changed behavior, preserved behavior, no pair, and infrastructure censorship.
- [ ] Narratives carry an explicit pre-registration limitation and contain no score or ranking.
- [ ] Tests cover changed paired behavior, preserved/no-pair behavior, and censorship separation.
- [ ] The full suite passes and the completed change is committed separately.
