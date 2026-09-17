# Spec: Multi-Provider Model Matrix Generation

## Requirements & Goals

- Describe the active model conditions for the behavior study in one provider-neutral catalog.
- Cover the 9 currently active models:
  - OpenAI GPT-6 Astra, GPT-5.6 Sol, and GPT-5.6 Luna.
  - Anthropic Claude Fable 5.1, Claude Opus 5, and Claude Sonnet 5.
  - Google Gemini 3.8 Flash.
  - xAI Grok 4.6.
  - Meta Muse Spark 1.3.
- Keep DeepSeek V4 Pro, Alibaba Qwen 3.8 Max 0902, and Moonshot Kimi K2.6 visible as pending conditions until the Anthropic and Meta audits are complete.
- Generate provider-specific pilot registrations because the current worker uses one endpoint and credential environment per process.
- Preserve the existing parent-owned verification, timeout, censorship, and public-release boundaries.
- Make the normal execution path unattended after the operator sets the provider environment variables and explicitly authorizes a live batch.
- Keep generated registrations free of credentials, endpoint values, hidden case data, and arbitrary commands.

## Inputs, Outputs & Behavior

### Model catalog

The committed catalog is `configs/model_matrix.json` with schema
`evidence-bounded-debugging-model-matrix-v1`. Active conditions contain only:

- a safe condition identifier;
- provider name;
- exact provider model identifier;
- approved worker transport;
- nullable reasoning effort.

Pending conditions contain a safe identifier, provider, display name, and a reason. They are not emitted into executable registrations.

The catalog must not contain credentials, endpoint URLs, worker commands, filesystem paths, or provider-specific environment values. Adding an unknown field fails closed.

### Generated registrations

`scripts/generate_model_matrix.py` reads the catalog and writes registrations under the ignored results area by default:
`results/model-matrix/registrations/`.

For every provider with at least one active condition, it writes:

- `<provider>-smoke.json`: one repetition of the existing `dashboard-filter-refresh` family, both variants;
- `<provider>-full.json`: two repetitions of all three existing case families, both variants.

Each generated condition uses the reviewed `jsonl-provider-worker` command, the approved transport recorded in the catalog, `network_required: true`, the configured reasoning effort, and explicit bounded worker headroom. Generated registrations use absolute local paths so they can be run directly from PowerShell without manual path editing. No live run is started by generation.

Provider batches are intentionally separate. The operator selects the matching provider endpoint and credential in the environment before running that provider's registration with `--allow-network`.

Native Gemini transport and OpenAI-compatible Gemini transport are distinct preregistered conditions. Results from one transport must not be pooled with the other unless that comparison is explicitly registered.

### Trial counts

The 9 active conditions produce:

- 18 smoke trials total: 9 conditions x 1 family x 2 variants x 1 repetition;
- 108 full trials total: 9 conditions x 3 families x 2 variants x 2 repetitions;
- 126 trials across both phases.

These are bookkeeping counts only. The project does not add a composite score, leaderboard, or model ranking.

## Edge Cases & Error Handling

- Unknown catalog schema, top-level fields, condition fields, or transport names fail closed.
- Active conditions must have non-empty exact model IDs and cannot use placeholder values.
- Active and pending condition IDs must be unique.
- A catalog with no active conditions fails closed.
- Generation refuses to overwrite an existing registration file.
- A provider with only pending conditions produces no executable registration.
- The generator fails before writing output if the approved worker entrypoint is missing.
- Generated registrations must pass the existing pilot registration parser and execution-policy shape checks without needing network access.
- The generator never reads or writes credential values.
- This change does not alter existing local registration files or execute provider requests.

## Acceptance Criteria

- [ ] The committed catalog contains the 9 active conditions and three pending Chinese-provider conditions.
- [ ] The catalog parser rejects unknown fields, duplicate IDs, placeholders, credentials, paths, and endpoint configuration.
- [ ] Generation groups conditions by provider and creates smoke and full registrations for every active provider.
- [ ] Smoke registrations select one family, both variants, and one repetition.
- [ ] Full registrations select all three families, both variants, and two repetitions.
- [ ] Generated conditions use only the approved worker entrypoint and approved transports.
- [ ] Generated registrations contain no credential values, endpoint values, hidden annotations, or verifier declarations.
- [ ] Generated registrations load successfully through the existing pilot parser.
- [ ] Generation refuses to overwrite existing files.
- [ ] Tests verify the model list, pending Chinese-provider behavior, provider grouping, trial counts, validation, and overwrite protection.
- [ ] The full existing test suite and offline generation checks pass.
- [ ] No live provider call occurs during implementation or verification.
