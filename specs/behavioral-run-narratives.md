# Spec: Public Behavioral Run Narratives

## Requirements & Goals

Extend the public behavioral report with a deterministic, provider-neutral narrative for each run. The narrative should answer the practical question “what did the model do and why might that choice have followed from the evidence it selected?” using only observable, already-sanitized fields.

This is a presentation layer, not a second evaluator. It must not infer hidden causes, judge diagnosis quality, assign scores, rank models, or reproduce provider output.

## Inputs, Outputs & Behavior

The existing report builder remains the source of truth. For each report run, add a `narrative` object containing:

- `summary`, a short deterministic paragraph;
- `evidence_path`, a sentence describing the accepted action sequence and targets before the first edit;
- `hypothesis_path`, a sentence describing checkpoint count, leading hypotheses, and confidence progression;
- `outcome`, a sentence describing repair attempt, termination, budget state, censorship, and verifier status separately.

Narrative text is generated from the report’s allowlisted `behavior`, execution, and verifier fields. It must use neutral language such as “the run recorded” or “the model selected”; it must not say that a hidden cause was proven or that one model is better.

The narrative builder must handle empty action sequences, missing checkpoint annotations, missing verifier status, and infrastructure-censored runs without raising. It must preserve redaction of local paths and credential-like strings already enforced by the report builder.

## Edge Cases & Error Handling

- A run with no accepted actions says that no accepted tool action was recorded.
- A run with no checkpoints says that no checkpoint hypothesis was recorded.
- A run with no edit says that no repair edit was attempted; this is descriptive and not a failure judgment.
- A censored run explicitly says behavioral verification was unavailable because execution was infrastructure-censored.
- Narrative generation must not add arbitrary input fields to the report.
- Output must remain deterministic for identical input reports.

## Acceptance Criteria

- [ ] Every report run contains the three narrative fields and the existing structured behavior fields.
- [ ] Narratives explain evidence path, hypothesis/checkpoint path, and outcome without scores or causal claims.
- [ ] Empty, incomplete, and censored runs produce useful neutral narratives.
- [ ] Tests cover a normal repair/no-repair narrative, missing checkpoints, and infrastructure censorship.
- [ ] The full existing suite passes and the completed change is committed separately.
