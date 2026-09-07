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

Each family has the same relevant visible symptom across variants, at least two plausible hypotheses, discriminating evidence, a bounded tool protocol, and a hidden verifier declaration. The dependency-free fixture calibration now executes the pre-fix failure, binds the inferred cause, checks mutation necessity, applies the declared mutation in memory, and checks the post-fix invariant. This is an authoring oracle only and must not be reused as the authoritative grader for model-produced patches. The current proof uses deterministic policies only; it does not invoke a real model. Workspace trials return raw visible file bytes for `inspect`; families may opt into a zero-cost `list_files` action that returns relative paths only.

## Run locally

From the project root:

```powershell
$env:PYTHONPATH = 'src'
python scripts/validate_behavior_cases.py
python scripts/run_behavior_proof.py
python scripts/run_unattended_proof.py
python scripts/run_reference_pilot.py --batch-id reference-smoke-v1 --repetitions 3 --output-root results/reference-pilot-smoke
python scripts/build_public_behavior_release.py --cases-root behavior_cases --output-root results/public-release
python -m unittest discover -s tests -v
```

The validation and proof commands are designed to run unattended. The unattended proof writes immutable artifacts under `results/unattended-proof/`, which is ignored as local run output. Unsupported actions, budget violations, malformed checkpoints, and other protocol failures are returned deterministically and recorded in the trace. Workspace adapter timeouts are infrastructure-censored (`infrastructure_censored=true`): verification is skipped and the live workspace is retained rather than being deleted while an in-process adapter may still be running.

The reference pilot command runs 18 credential-free subprocess trials across the three families, both variants, and three repetitions. Its worker intentionally does not patch the cases, so verifier failures in that smoke batch are expected; the smoke is green when the trials complete without infrastructure censorship and the immutable artifacts can be sanitized. Registered model conditions can be run with `scripts/run_model_pilot.py` after their JSONL workers are available.

## Scope and limitations

The public protocol records observable tool use, edits, checkpoints, verifier outcomes, termination state, and repair-attempt annotations. It does not request or store private chain-of-thought. Internal traces retain answer-key annotations for analysis, while [public sanitizers](src/evidence_eval/public.py) remove fixture source, cause-discriminating observation prose, variant mappings, and other answer-key material before release. Model-authored checkpoint text remains behavioral evidence and may still paraphrase a cause. A model identity is reported exactly as registered, including any mediated agent or model-selection label; results are not generalized to a raw provider model unless that identity is directly established. `execution_status` describes adapter lifecycle; verifier pass/fail is recorded separately in `verifier_result` and is not a diagnosis-quality score.

The approved design is in [specs/evidence-bounded-debugging-behavior-study.md](specs/evidence-bounded-debugging-behavior-study.md), and the current batch milestones are in [specs/model-pilot-batch.md](specs/model-pilot-batch.md) and [specs/trusted-provider-execution-policy.md](specs/trusted-provider-execution-policy.md). The current fixtures are dependency-free semantic checks over TypeScript/TSX snapshots, not a full Next.js server. The harness now includes a safe visible-file materializer, a workspace trial runner with runner-owned verifier invocation, separate source-level verifiers for the six pilot variants, a JSONL subprocess adapter boundary, and an unattended provider-neutral pilot batch runner. A full Next.js runtime verifier and OS/container sandbox remain out of scope. The public release builder produces sanitized case packs, structured run artifacts, and publishable batch manifests while intentionally omitting raw adapter results and final response files.

The trusted provider-worker milestone adds a provider-neutral JSONL loop, a credential-free mock transport, and batch-gated OpenAI-compatible, OpenAI Responses, and native Google Gemini transport seams. The provider worker receives only the prompt, visible tool contract, and allowlisted model-condition fields. Live execution requires a registration marked `network_required`, the reviewed worker command, the `EVIDENCE_EVAL_PROVIDER_API_KEY` credential, and `--allow-network` on `scripts/run_model_pilot.py`; the parent injects the worker authorization marker only for those trials. Responses transport registrations use `--transport openai-responses` and native Gemini registrations use `--transport google-gemini`; both must declare `network_required: true`. Native Gemini requests use the documented root `https://generativelanguage.googleapis.com/v1beta`, authenticate with `x-goog-api-key`, and retain opaque `thoughtSignature` continuation fields only in child-process memory. They do not request thought summaries or use server-side conversation state. Run the mock integration smoke with `python scripts/run_provider_worker_mock_smoke.py` after setting `PYTHONPATH=src`.

To turn completed artifacts into a publishable behavioral summary, first build the sanitized release and then build the report from that release:

```powershell
$env:PYTHONPATH = 'src'
python scripts/build_public_behavior_release.py --cases-root behavior_cases --artifacts-root results/your-batch --output-root results/public-release
python scripts/build_behavioral_report.py --public-root results/public-release --output results/public-release/behavior-report.json
```

The report describes evidence selection, action sequences, hypotheses, repair attempts, termination, and verifier outcomes separately. It does not rank models, calculate a composite score, or include raw provider responses, adapter artifacts, or answer-key fields. Paired differences use opaque public identifiers and are descriptive unless the comparison was pre-registered.
