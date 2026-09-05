# Baseline and Project Boundary

This repository extends the published Cursor Model Behavior Eval V2.3 release. The baseline is preserved outside this repository at:

`C:\Users\Patrick\Desktop\cursor-model-behavior-eval\public_release`

The reference release is commit `84c3f7a` (`docs: publish V2.3 evaluation results`). The baseline project is treated as immutable prior work. Its cases, registrations, reports, source, and published artifacts are not edited by this study.

The baseline established a descriptive behavioral evaluation around misleading-diagnosis recovery, minimal-patch discipline, hidden-invariant fidelity, repeated trials, runner-owned verification, and immutable run artifacts. It used a shared Cursor CLI harness and Python cases.

This extension keeps the same central question - what did the model do, and why might it have made that choice? - while changing the debugging domain to unfamiliar TypeScript and Next.js repositories. The extension adds paired counterfactual case families, explicit evidence budgets, controlled tool observations, and pre-registered intervention language so that causal explanations are separated from ordinary behavioral descriptions.

The extension does not claim to measure hidden reasoning or raw provider capability. Results are bound to the frozen model condition, agent adapter, prompt, tool contract, case variant, and harness version used in a run.
