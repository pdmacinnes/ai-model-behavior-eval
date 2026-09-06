# Evidence-Bounded Debugging Behavior Study

This is a public, reproducible study of how coding agents investigate unfamiliar TypeScript and Next.js codebases.

The project asks a narrower question than a normal coding benchmark: when a model sees a bug and several plausible explanations, what evidence does it choose, what does it ignore, when does it form or revise a hypothesis, and when does it patch? The output is a set of behavioral observations and case narratives, not a composite score or overall model ranking.

## Relationship to the Cursor evaluation

The project extends the published Cursor Model Behavior Eval V2.3 release. That work is preserved as an immutable reference and is documented in [references/baseline.md](references/baseline.md). The first implementation reuses its tested artifact and harness foundations while adding a TypeScript/Next.js case protocol and paired counterfactuals.

The study makes causal language deliberately narrower than descriptive language. A trace can show that a model inspected one file before another. A claim that a controlled factor caused that choice requires a pre-registered paired case or intervention whose visible surface remains comparable.

## Current pilot

The pilot contains three paired case families:

- `dashboard-filter-refresh` - query propagation versus a static cache key
- `session-refresh-role` - stale session data versus an authorization guard
- `pagination-offset` - client offset mismatch versus server page normalization

Each family has the same relevant visible symptom across variants, at least two plausible hypotheses, discriminating evidence, a bounded tool protocol, and a hidden verifier declaration. The dependency-free fixture calibration now executes the pre-fix failure, binds the inferred cause, checks mutation necessity, applies the declared mutation in memory, and checks the post-fix invariant. This is an authoring oracle only and must not be reused as the authoritative grader for model-produced patches. The current proof uses deterministic policies only; it does not invoke a real model.

## Run locally

From the project root:

```powershell
$env:PYTHONPATH = 'src'
python scripts/validate_behavior_cases.py
python scripts/run_behavior_proof.py
python scripts/run_unattended_proof.py
python scripts/build_public_behavior_release.py --cases-root behavior_cases --output-root results/public-release
python -m unittest discover -s tests -v
```

The validation and proof commands are designed to run unattended. The unattended proof writes immutable artifacts under `results/unattended-proof/`, which is ignored as local run output. Unsupported actions, budget violations, malformed checkpoints, and other protocol failures are returned deterministically and recorded in the trace. Workspace adapter timeouts are infrastructure-censored (`infrastructure_censored=true`): verification is skipped and the live workspace is retained rather than being deleted while an in-process adapter may still be running.

## Scope and limitations

The public protocol records observable tool use, edits, checkpoints, verifier outcomes, and termination state. It does not request or store private chain-of-thought. Internal traces retain answer-key annotations for analysis, while [public sanitizers](src/evidence_eval/public.py) remove them before release. A model identity is reported exactly as registered, including any mediated agent or model-selection label; results are not generalized to a raw provider model unless that identity is directly established. `execution_status` describes adapter lifecycle; verifier pass/fail is recorded separately in `verifier_result`.

The approved design is in [specs/evidence-bounded-debugging-behavior-study.md](specs/evidence-bounded-debugging-behavior-study.md). The current fixtures are dependency-free semantic checks over TypeScript/TSX snapshots, not a full Next.js server. The harness now includes a safe visible-file materializer, a workspace trial runner with runner-owned verifier invocation, and separate source-level verifiers for the six pilot variants. Provider adapters, a full Next.js runtime verifier, and subprocess transport for untrusted adapters remain subsequent implementation phases. The public release builder produces sanitized case packs and run artifacts.
