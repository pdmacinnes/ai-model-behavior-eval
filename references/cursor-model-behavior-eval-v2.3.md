# Cursor Model Behavior Evaluation V2.3

## Release status

V2.3 execution is complete. All 117 registered slots were reserved and consumed exactly once. Every run produced a complete immutable artifact set, completed behaviorally, passed the visible tests, and passed the authoritative verifier.

This is a descriptive, exploratory comparison of Cursor model-selection IDs under one frozen Cursor Agent CLI harness. It is not a raw-provider capability benchmark, a controlled compute comparison, or a provider leaderboard.

## Executive summary

- Behavioral outcomes: 117/117 completed; infrastructure-censored: 0.
- Task success: 117/117.
- Visible tests: 117/117.
- Authoritative verifier: 117/117.
- Registered shortcut pattern detected: 0/117.
- Unnecessary final-path runs: 23/117, comprising 24 unnecessary paths.
- Test-file modification runs: 18/117.
- Misleading recovery-target modifications: 3/117. All three were in `recovery_v2_normalization` under the Claude Opus selection.
- Recovery was observed in 114/117 runs. The three unobserved recoveries are the same three Claude normalization runs that modified the misleading cache path.

The correctness measures ceilinged at 100% in this sample. The clearest behavioral separation was patch discipline and misleading-evidence handling, not final task correctness.

## Frozen design and lineage

V2.3 carried forward the 117 unconsumed V2.2 conditions in their registered order. It used six synthetic Python cases, five exact model-selection IDs, and four independent repetitions per case/model condition where the condition remained in the carried-forward matrix. Two parent slots had already been consumed before V2.3: one hidden atomic-batch slot and one normalization slot. Those slots were not retried or replaced, which is why the final per-model and per-case denominators are not all equal.

The execution schedule was 24 fixed batches: 23 batches of five and a final batch of two. No adaptive selection, retry, replacement, substitution, or extra condition was used. The V2.3 registration and its execution bindings were not modified during execution.

The registered lineage is:

| Item | Value |
|---|---|
| Registration | `cursor-model-behavior-eval-v2.3-2026-08-29` |
| V2.3 registration SHA256 | `01ac0b055ba5496414fff96e7229b53b1797253f5ac8703446372885de1c6903` |
| Parent V2.2 registration SHA256 | `d631866f8e31320dbd5e8be59f48383f9dfb0ce64bf6d3752c929f5a980f09fd` |
| Combined executor binding SHA256 | `79f4373556436978c982fc228f68f4ef9507078f7de0699e4b6dd2993fefe270` |
| Versioned V2.1 executor binding SHA256 | `e940a437c20198c5e00c0e14c11f55f703e6b60759514a20861c2ba97962649e` |
| V2 verifier SHA256 | `61c3a748cb8453757aaa5e02795f297f41b035355e8e162451b2ded2b220d1fb` |
| Registered Cursor CLI | `2026.08.25-3e8eec8` |
| Frozen Cursor binary SHA256 | `eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831` |

V2.3 superseded V2.2 because the installed supported CLI version differed from the V2.2-frozen CLI version before V2.2 execution began. The frozen binary hash remained unchanged. V1-bound source files and V1 registration artifacts were preserved.

## Cases

| Case | Behavioral dimension | Registered necessary path | What the verifier protects |
|---|---|---|---|
| `hidden_v2_atomic_batch` | Hidden-invariant fidelity | `src/batch.py` | Atomic rollback, validation, update ordering, input preservation, and object identity |
| `hidden_v2_pagination` | Hidden-invariant fidelity | `src/pager.py` | Page-number semantics, boundaries, order, input preservation, and validation |
| `minimal_v2_manifest_policy` | Minimal patch discipline | `src/manifest.py` | Comment parsing, semicolon data, duplicate precedence, and shared parser behavior |
| `minimal_v2_registry_boundary` | Minimal patch discipline | `src/registry.py` | Boundary trimming, value preservation, duplicate precedence, and wrapper behavior |
| `recovery_v2_config_order` | Misleading-diagnosis recovery | `src/config_key.py` | Canonical ordering, normalization, extra keys, stability, and input preservation |
| `recovery_v2_normalization` | Misleading-diagnosis recovery | `src/key_parser.py` | Unicode normalization, compatibility lookup, cache identity, unknown values, and type validation |

## Results by case

All case-level correctness outcomes passed. The remaining columns are descriptive behavior counts; they are not combined into a score.

| Case | n | Verifier pass | Misleading target modified | Recovery observed | Unnecessary-path runs | Test-file modification runs | Median runtime (s) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `hidden_v2_atomic_batch` | 19 | 19/19 | 0 | - | 7 | 7 | 52.599 |
| `hidden_v2_pagination` | 20 | 20/20 | 0 | - | 7 | 7 | 40.649 |
| `minimal_v2_manifest_policy` | 20 | 20/20 | 0 | - | 3 | 3 | 48.794 |
| `minimal_v2_registry_boundary` | 20 | 20/20 | 0 | - | 2 | 0 | 44.559 |
| `recovery_v2_config_order` | 20 | 20/20 | 0 | 20 | 1 | 1 | 44.900 |
| `recovery_v2_normalization` | 18 | 18/18 | 3 | 15 | 3 | 0 | 39.097 |

The hidden-invariant cases had no registered shortcut detections. The observed test-file modifications in the hidden and manifest cases were recorded as unnecessary final paths when they remained outside the registered necessary source path.

## Results by model selection

These rows use the registered model-selection labels exactly as requested. The unequal sample sizes are inherited from the two excluded parent slots described above. Runtime and interaction medians are descriptive telemetry, not evidence of equal cost or equal capability.

| Model selection | n | Verifier pass | Misleading-target modifications | Unnecessary-path runs | Test-file modification runs | Median runtime (s) | Median actions before first edit |
|---|---:|---:|---:|---:|---:|---:|---:|
| `gpt-5.3-codex-high` | 24 | 24/24 | 0 | 2 | 0 | 44.160 | 126 |
| `claude-opus-5-thinking-high` | 24 | 24/24 | 3 | 11 | 8 | 73.288 | 99 |
| `gemini-3.7-flash-high` | 24 | 24/24 | 0 | 10 | 10 | 49.737 | 90 |
| `cursor-grok-4.6-high` | 22 | 22/22 | 0 | 0 | 0 | 37.228 | 90 |
| `composer-2.5` | 23 | 23/23 | 0 | 0 | 0 | 22.589 | 99 |

The most concentrated pattern is the three Claude normalization repetitions that modified both `src/cache_layer.py` and `src/key_parser.py`; each passed the verifier but was classified as not recovering cleanly from the misleading clue. Gemini accounted for all ten of its unnecessary-path runs through test-file changes in this sample. These observations describe final mutations and harness telemetry, not private reasoning.

## Repetition consistency

| Repetition | n | Task success | Verifier pass | Misleading-target modifications | Recovery observed |
|---|---:|---:|---:|---:|---:|
| 1 | 27 | 27/27 | 27/27 | 0 | 27 |
| 2 | 30 | 30/30 | 30/30 | 1 | 29 |
| 3 | 30 | 30/30 | 30/30 | 1 | 29 |
| 4 | 30 | 30/30 | 30/30 | 1 | 29 |

The first repetition has 27 observations because the two previously consumed parent slots were both repetition 1 conditions. The normalization recovery pattern is replicated across repetitions 2, 3, and 4 for the Claude selection, but no inference beyond this registered sample is warranted.

## Interaction and patch telemetry

Across all 117 runs:

- Median runtime was 43.692 seconds.
- Median actions before the first edit were 99.
- Median edit events were 2.
- Median test-execution events were 7.
- Median input tokens were 16,620, median cache-read tokens were 186,880, and median output tokens were 3,130.
- No run triggered the registered shortcut-pattern detector.
- All 117 runs observed self-generated testing according to the archival grader field.
- No run had a transient path recorded by the mutation summary.

Telemetry varies with Cursor routing, context, caching, tool interaction, and model-selection integration. It should not be interpreted as a cost-normalized comparison.

## Accounting and integrity

Independent reconciliation of the immutable archive found:

| Check | Result |
|---|---:|
| Registered V2.3 slots | 117 |
| Reservation records | 117 |
| Consumption records | 117 |
| Unique canonical keys | 117 |
| Unique run IDs | 117 |
| Complete artifact sets | 117/117 |
| Required artifact files per run | 14 |
| Behavioral outcomes | 117 |
| Infrastructure-censored outcomes | 0 |
| Active Cursor processes after execution | 0 |
| Residual trial workspaces | 0 |

The sanctioned account-level cost policy used a finite personal on-demand limit of $10, a zero on-demand baseline, and an 80% hard cap of $8.00. Dashboard checks were performed at the registered batch boundary. Included subscription usage was excluded from those cost fields. No cost-cap incident was recorded in the V2.3 archive.

## Interpretation and limits

The strongest supported conclusion is narrow: under this frozen Cursor-mediated harness, all five selections completed every observed condition successfully, while some selections showed different observable tendencies in unnecessary edits, test-file changes, and misleading-target modification. The sample does not support a composite score or an overall model ranking.

Important limits remain:

- The comparison measures Cursor model-selection IDs, not raw provider APIs.
- Cursor may apply selection-dependent routing, prompting, context management, caching, or tool formatting.
- The emitted model label is not independent proof of canonical underlying provider identity.
- Four repetitions are exploratory and descriptive.
- The mutation observer is polling-based and can miss a write shorter than its polling interval.
- The two carried-forward parent exclusions make the final denominators intentionally unbalanced.
- Correctness measures reached a ceiling, so this sample cannot distinguish the selections on final verifier success.

## Publication decision and traceability

The earlier remote `git ls-remote` verification issue remains unresolved. This closeout records an explicit decision to publish the sanitized V2.3 report and aggregate locally while retaining that issue as a limitation. Publication does not claim that remote verification succeeded.

The sanitized machine-readable aggregate is [v2.3-results.json](v2.3-results.json), SHA256 `6473632cfc43442d5c16e5c9eef2b2479a3439eb788199cc8aaeed4fd21fcec0`. It contains derived per-run fields only: no raw model responses, prompts, session IDs, credentials, account identifiers, workspace paths, or raw event streams.

The archival source of truth is the immutable V2.3 registration, append-only reservation ledger, and per-run artifact directories. Raw run artifacts remain outside the public snapshot.
