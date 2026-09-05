# Spec: Evidence-Bounded Debugging Behavior Study

## Requirements & Goals

- Extend the existing Cursor Model Behavior Eval into a focused study of how newly released AI models investigate unfamiliar TypeScript and Next.js codebases.
- Preserve the original Cursor evaluation as an immutable baseline. The new project must not modify its cases, registrations, reports, source, or published artifacts.
- Study observable debugging behavior rather than produce a single performance score or overall model ranking.
- Center the study on evidence acquisition: what a model chooses to inspect, test, trace, or change before committing to a diagnosis or patch.
- Use controlled interventions and paired cases so that claims about why a model behaved a certain way are supported by changes in observable behavior, not only by the model's retrospective explanation.
- Keep the evaluation public and reproducible, with versioned case definitions, frozen model configurations, deterministic environments, sanitized traces, and a narrative report.
- Make the core runner unattended. A normal evaluation batch must not require per-test human approval, interactive desktop-agent prompts, live external services, or package installation.
- Keep the core environment model-agnostic. Cursor model selections may be included as one adapter, but the study must leave room for additional providers and model families behind the same tool contract.
- Do not claim to inspect private chain-of-thought or infer intrinsic provider behavior from a mediated agent integration. Claims must be limited to behavior observed under the frozen environment, prompt, tool contract, and model configuration.
- Do not treat supporting telemetry such as runtime, action count, or verifier success as the project's headline result. These fields support behavioral analysis and case narratives.

### Non-goals

- Building another generic coding leaderboard.
- Ranking providers or claiming that a Cursor model-selection label proves raw provider identity.
- Recreating the entire Cursor harness before determining which existing components can be reused.
- Measuring hidden reasoning directly.
- Optimizing cases for one model, one provider, or one agent UI.
- Expanding to arbitrary open-source repositories before the controlled case methodology is validated.

## Inputs, Outputs & Behavior

### Baseline and project boundary

The existing Cursor Model Behavior Eval is the reference point for the project. Its published V2.3 work already establishes a descriptive, non-leaderboard behavioral evaluation with misleading-evidence recovery, minimal-patch discipline, hidden-invariant fidelity, repeated trials, runner-owned verification, and immutable run artifacts.

The new study adds a TypeScript/Next.js debugging domain and a stronger causal design. It must distinguish the following two layers:

1. **Observed behavior:** what the model did in one run, including tool calls, file reads, tests, edits, reversions, and final state.
2. **Behavioral explanation:** a claim that a controlled factor, such as a framework prior or misleading clue, caused a change in the model's decision path.

The second layer is allowed only when supported by a pre-registered paired case, perturbation, or counterfactual comparison.

### Case inputs

Each case family contains:

- A realistic, unfamiliar TypeScript or Next.js repository snapshot.
- A deterministic local runtime with fixture data and any required fake services.
- A user-visible bug report and initial reproduction evidence.
- A baseline causal state and one or more counterfactual causal states.
- A list of plausible behavioral dimensions under study, such as misleading-prior recovery, evidence seeking, premature patching, or stopping behavior.
- A controlled tool contract for repository inspection, search, test execution, logs, traces, and diagnostics.
- A hidden authoritative verifier for the actual behavior and invariant under test.
- A case-specific mutation or variant proof showing that the intended intervention changes the underlying causal state while preserving the relevant surface symptom.
- A declared action budget, timeout, output bound, and workspace policy.

The initial visible context must not disclose the expected source path, hidden causal map, authoritative verifier, or the intended behavioral conclusion.

### Model registration inputs

Each registered model condition freezes:

- Provider and exact model-selection or API identifier.
- Agent or adapter implementation.
- System and task prompts.
- Reasoning or effort setting where applicable.
- Tool schemas and tool permissions.
- Model version, harness version, and evaluation date.
- Repetition count and deterministic trial order.

The original three tweet models are anchor conditions. Additional models may be added by a documented inclusion rule covering model family, availability window, and reproducible access. Adding models must not change the tool contract or case definitions for an existing release.

### Normal trial flow

1. Validate the case family, counterfactuals, visible tests, hidden verifier, and mutation proof without invoking a real model.
2. Materialize a fresh disposable workspace and local fixture environment for the selected case variant.
3. Present the model with the frozen task prompt and initial evidence.
4. Allow the model to choose its own investigation path through the controlled tool interface. The model may inspect, search, test, trace, instrument, edit, revert, ask for permitted information, or stop.
5. At pre-registered decision points, collect a concise structured state containing the model's leading hypothesis, main alternative, confidence, evidence that changed its view, and intended next action. These summaries are behavioral observations, not privileged reasoning access.
6. Record an append-only event stream covering tool calls, returned evidence, tests, edits, reverts, timing, failures, and termination reason.
7. Apply the runner-owned authoritative verifier and behavior observers after the model terminates or reaches a hard limit.
8. Store an immutable run record containing the registration binding, case variant, event trace, model response, verifier result, behavioral annotations, and environment hashes.
9. Produce sanitized aggregates and narrative case reports without exposing credentials, account identifiers, private paths, or unsanitized provider/session material.

### Required behavioral comparisons

The pilot must include paired or otherwise controlled comparisons such as:

- Same visible symptom with different underlying causes.
- Same case with a misleading framework-specific clue added or removed.
- Same case with initial evidence ordering changed.
- Same case with a limited versus generous evidence budget.
- Same case with contradictory evidence revealed after the model's initial hypothesis.

The analysis must report whether the model's actions, hypothesis state, stopping behavior, or patch path changed across the intervention. A model may reach the same final diagnosis through different valid paths; exact path matching is not required.

### Outputs

The project produces:

- A reusable local evaluation harness with unattended batch execution.
- Versioned case families and public development cases.
- Frozen registrations for each public evaluation release.
- Raw internal run artifacts and sanitized public traces.
- Per-case behavioral narratives.
- Model behavioral profiles organized by observed patterns, not rank order.
- Supporting descriptive fields such as misleading-target edits, unnecessary paths, evidence requests, hypothesis changes, action counts, runtime, verifier outcome, and repetition consistency.
- A public report explaining what changed across interventions, what did not change, and which claims remain unsupported.

The project must not collapse the outputs into a composite score. Supporting counts may be shown in tables when they clarify a behavioral claim.

## Edge Cases & Error Handling

- If the new project cannot identify the exact baseline Cursor release, it must record the known commit and assumptions rather than silently reconstructing missing details.
- If a case has no plausible competing hypotheses, no discriminating evidence, or no stable counterfactual, it is rejected from the behavioral pilot even if it is technically difficult.
- If two case variants do not preserve the intended surface symptom closely enough, the pair is invalid and cannot support a causal claim.
- If a visible test or hidden verifier passes before the intended change, the case fails calibration and cannot be registered.
- If an intervention changes multiple uncontrolled variables, the result is reported as descriptive only and is excluded from causal language.
- If a tool call is unsupported, malformed, exceeds its output bound, times out, or attempts unauthorized access, the harness returns a deterministic tool error and records it. The model is not given a human approval prompt.
- If the model writes outside the disposable workspace, the run is terminated and marked infrastructure-censored. The run is not retried or silently replaced.
- If a model identifier, adapter, prompt, tool schema, or harness version changes after registration, the affected condition fails closed and is not substituted.
- If a model stops early, refuses to investigate, or states that evidence is insufficient, that is a valid behavioral outcome and must be recorded rather than treated as an automatic failure.
- If the model modifies tests, fixtures, or misleading files, those changes are recorded as behavior. They must not change authoritative verifier authority.
- If a polling observer misses a transient edit, the limitation is reported and the case must use calibration bounds that make the intended transient behavior observable where it is part of the design.
- If the model's concise hypothesis summary conflicts with its observable actions, the discrepancy is reported as a behavioral finding. The summary does not override the event trace.
- If a provider exposes only a mediated agent integration, results are labeled with the exact mediated selection and are not generalized to the raw provider model.
- If a public release contains secrets, account data, session identifiers, private paths, or unreviewed raw model output, publication is blocked until sanitization succeeds.

## Acceptance Criteria

- [ ] A project-level baseline note identifies the existing Cursor Model Behavior Eval V2.3 release, its immutable reference location, and the exact scope of the new extension.
- [ ] The new repository contains a documented case schema covering repository snapshot, initial evidence, hidden causal state, counterfactual variant, tool contract, budget, verifier, and mutation proof.
- [ ] The pilot contains at least three paired TypeScript/Next.js debugging case families, each with the same relevant surface symptom and distinct underlying causal states.
- [ ] Each pilot case has at least two plausible hypotheses and at least one tool action whose returned evidence can discriminate between them.
- [ ] Each pilot case passes deterministic visible-test, authoritative-verifier, mutation, and counterfactual calibration without a real model invocation.
- [ ] The harness can run a complete batch in disposable local environments without per-test approval, live external services, or runtime dependency installation.
- [ ] The harness exposes a stable model-agnostic tool contract and records the exact tool request, result, cost/budget use, and failure state for every action.
- [ ] The harness records model decision checkpoints without requiring or storing hidden chain-of-thought.
- [ ] A registered run produces an immutable artifact set containing the exact model condition, case variant, prompt hash, tool-contract hash, event trace, final response, verifier result, and behavioral annotations.
- [ ] Paired-case analysis can show when a model changes or preserves its investigation behavior after the underlying cause changes.
- [ ] The analysis distinguishes descriptive observations from causal claims and requires a declared intervention for the latter.
- [ ] The public report presents behavioral profiles and case narratives without a composite score or overall model ranking.
- [ ] The public release includes sanitized case definitions, registration metadata, scoring/observation code, reproduction instructions, and derived traces sufficient to audit the reported claims.
- [ ] The original Cursor evaluation remains unchanged and is referenced as prior work rather than overwritten or silently forked.
- [ ] No implementation code is considered complete until the spec is explicitly approved and the acceptance checklist is verified against the built system.
