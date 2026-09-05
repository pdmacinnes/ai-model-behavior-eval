# Spec: Cursor Capability Audit

## Requirements & Goals

- Determine whether the locally available Cursor interface supports a deterministic, headless, repeatable coding-agent invocation with explicit model selection.
- Record the executable identity, version, supported command surface, model-selection mechanism, model discovery, structured output, session behavior, working-directory controls, rules, approvals, sandbox behavior, telemetry, exit semantics, authentication, and usage information.
- Use only the installed Cursor interface and official Cursor documentation. Do not use private APIs, browser automation, UI-coordinate automation, undocumented network endpoints, or a real benchmark model invocation.
- Fail closed if the supported local interface cannot select models deterministically. Do not build the benchmark around a guessed or undocumented interface.

## Inputs, Outputs & Behavior

Audit date: 2026-08-16. Repository path: `<local project root>`.

### Local installation observed

- PATH command: `cursor.cmd`
- Exact executable name: `cursor.cmd`
- Wrapper target: `Cursor.exe`
- Cursor version output:

  ```text
  3.15.19
  de07bee81cefe43461ebf4f40c3d2d78d15052a0
  x64
  ```

- Installed `cursor.cmd` SHA-256: `CD8AFBBA4C12153D22BFB15787744DA9377F3356E43E4E82E6E661C67F44F4AE`
- Installed `Cursor.exe` SHA-256: `06FBE6104F49A6629598CF4800995BD5B5C21A25A1DE0E96C088B6B12D49A70C`
- Installed CLI implementation (`resources/app/out/cli.js`) SHA-256: `997DC1A7E5DD1AC5E9E8CE4A09C99704019F61353F85F6B7808D00D7A5AC8C7B`
- No `cursor-agent` or standalone `agent` executable was found on PATH or in the checked user-local Cursor locations.

### Local command audit

The following observations are the pre-install desktop CLI audit. They remain recorded for provenance but are superseded for execution by the post-install Cursor Agent CLI audit below.

- `cursor --help` returns the desktop CLI help. It includes path/window management, extension management, troubleshooting, and a top-level `agent` description, but it does not document `--print`, `--output-format`, `--model`, `--force`, `--resume`, `--list-models`, or an agent-specific help page.
- `cursor agent --help` returned the same desktop CLI help rather than agent-specific help.
- `cursor agent --version` returned the desktop Cursor version above rather than a distinct Cursor Agent CLI version.
- `cursor agent models --help` returned the same desktop CLI help rather than a model inventory.
- A probe of `cursor agent help` and `cursor agent --list-models` did not return an agent-specific result within the bounded probe and spawned normal Cursor processes. It was stopped. No model invocation was made.
- The local Cursor configuration contains a selected default model represented as `Auto`, but this is GUI configuration, not a supported headless model-selection contract. It cannot establish the underlying model identity.

### Capability matrix: pre-install desktop CLI

| Capability | Local evidence | Audit result |
| --- | --- | --- |
| Dedicated Cursor Agent CLI | No `cursor-agent` or standalone `agent` executable found | Not available locally |
| Headless/non-interactive execution | Desktop help has no agent print/headless contract; agent probes launch normal Cursor behavior | Not established |
| Exact model selection | No local agent `--model` help or executable | Not available |
| Model enumeration | No local `agent models` or `--list-models` result | Not available |
| Structured output | No local agent `--output-format` contract | Not available |
| Session/conversation behavior | Desktop CLI exposes no agent session contract | Not available |
| Working-directory control | Desktop CLI accepts paths and `--user-data-dir`; this is not sufficient to establish agent execution isolation | Partial only |
| Rule loading | Local agent execution was not available. Official docs state the Agent CLI reads `.cursor/rules`, `AGENTS.md`, and `CLAUDE.md` | Documentation only |
| Approval/command policy | Local agent execution was not available. Official docs describe CLI command approval and print-mode behavior | Documentation only |
| Sandbox/worktree behavior | No local agent contract observed | Not established |
| Telemetry/tool output | No local agent structured event stream observed | Not available |
| Exit status semantics | No local headless agent run available | Not established |
| Authentication | The local GUI config has non-secret identity metadata. Official Agent CLI documentation describes login and `CURSOR_API_KEY`; no agent CLI is installed for a readiness check | Documentation only |
| Usage/token/cost reporting | No local agent output or usage interface observed | Not available |

### Official documentation consulted

- [Cursor CLI parameters](https://docs.cursor.com/en/cli/reference/parameters) documents a separate `cursor-agent` executable with `-p/--print`, `--output-format`, and `--model`.
- [Cursor headless CLI](https://docs.cursor.com/en/cli/headless) documents non-interactive print mode, command execution, and structured output use.
- [Cursor output formats](https://docs.cursor.com/en/cli/reference/output-format) documents JSON and stream-JSON events, including the model field in initialization output.
- [Cursor CLI usage](https://docs.cursor.com/en/cli/using) documents rules and command approval behavior.
- [Cursor CLI installation](https://docs.cursor.com/en/cli/installation) documents installation of the separate CLI.

### Output and gate behavior

The pre-install result was a hard blocker for the requested benchmark build:

```text
BLOCKED: the locally available supported Cursor interface does not currently provide an observed deterministic headless model-selection mechanism.
```

The official standalone Cursor Agent CLI was subsequently installed with explicit approval. The current execution gate is recorded below.

### Post-install Cursor Agent CLI re-audit

Installation method: Cursor's official installer, invoked inside the existing Ubuntu WSL 2 distribution exactly as documented:

```text
curl https://cursor.com/install -fsS | bash
```

The installer downloaded the official package from `https://downloads.cursor.com/lab/2026.08.11-e8db854/linux/x64/agent-cli-package.tar.gz`.

- WSL distribution: `Ubuntu`, version `2`
- Installed version: `2026.08.11-e8db854`
- Primary executable name: `agent`
- Compatibility executable name: `cursor-agent`
- Primary executable: `agent`
- Compatibility executable: `cursor-agent`
- The frozen binary identity is recorded by SHA-256 rather than by a machine-specific path.
- Installed executable SHA-256: `eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831`

Observed supported interface from the installed executable's help output:

| Capability | Observed interface | Result |
| --- | --- | --- |
| Headless/non-interactive execution | `-p, --print` | Verified |
| Exact model selection | `--model <model>` | Verified as a supported flag; model identifiers still require authenticated discovery |
| Model enumeration | `--list-models` and `agent models` | Supported but authentication-gated |
| Structured output | `--output-format text | json | stream-json` with `--print` | Verified |
| Partial event streaming | `--stream-partial-output` with `stream-json` | Verified |
| Session behavior | `--resume [chatId]`, `--continue`, `ls`, `resume` | Verified |
| Working directory | `--workspace <path-or-name>`, `--add-dir <path>` | Verified |
| Isolated worktree | `--worktree [name]`, `--worktree-base`, `--skip-worktree-setup` | Verified |
| Approval policy | `--force`, `--yolo`, `--trust`, `--auto-review` | Verified as supported controls |
| Sandbox | `--sandbox enabled|disabled` | Verified |
| Endpoint/auth inputs | `--endpoint`, `--api-key`, `CURSOR_API_KEY`, `CURSOR_AUTH_TOKEN` | Verified as supported inputs |

Authentication and model inventory checks were read-only:

- The official `agent login` command was started without `NO_OPEN_BROWSER`; it launched the browser flow but timed out after 120 seconds before authentication completed.
- The post-login-attempt `agent status` command returned `Not logged in`.
- The post-login-attempt `agent --list-models` command returned an authentication-required error and did not list models.
- The post-login-attempt `agent models` command returned the same authentication-required error and did not list models.
- No `CURSOR_API_KEY`, `CURSOR_AUTH_TOKEN`, or `CURSOR_API_ENDPOINT` value was present in the WSL environment.
- No credential value was inspected, printed, persisted, or copied by the audit. The official CLI did not complete authentication.
- Therefore the selectable model inventory is currently unknown and no model set can be frozen.

Exact read-only inventory commands used after the official login attempt:

```text
wsl.exe -d Ubuntu -- agent status
wsl.exe -d Ubuntu -- agent --list-models
wsl.exe -d Ubuntu -- agent models
```

Current gate:

```text
READY FOR ZERO-PROVIDER HARNESS WORK; NOT READY FOR MODEL INVENTORY FREEZE.
STOP BEFORE ANY REAL CURSOR MODEL INVOCATION.
```

The installed CLI now satisfies the deterministic interface requirement in principle, but the primary benchmark cannot proceed to model selection until an authenticated, read-only `agent --list-models` check succeeds. No benchmark prompt, case task, or paid/model trial has been executed.

### Authenticated model-inventory audit

Audit date: 2026-08-16. The official WSL CLI reported a successful authenticated status. The exact read-only commands were:

```text
wsl.exe -d Ubuntu -- agent status
wsl.exe -d Ubuntu -- agent --list-models
wsl.exe -d Ubuntu -- agent models
```

Observed results:

- `agent status` returned `Logged in`.
- `agent --list-models` and `agent models` returned identical inventories.
- The inventory contains 203 non-automatic model identifiers plus `auto - Auto (default)`.
- The complete exact CLI output is preserved in [artifacts/cursor-cli-model-inventory-2026-08-16.txt](../artifacts/cursor-cli-model-inventory-2026-08-16.txt).
- Inventory artifact SHA-256: `442066DD7CE7EC51C20C66EA4983EAB160631147B495C6E86098E7C0C8416DF5`.
- The CLI ends the listing with `use --model <id>`, so every listed identifier is advertised as a selectable `--model` value. No model was invoked to test individual selections.
- No duplicate display names were present in the parsed inventory. Related mode variants are separate identifiers with distinct display names such as `-low`, `-medium`, `-high`, `-xhigh`, `-max`, `-thinking`, and `-fast`.
- Ten Fable entries are explicitly marked `(NO ZDR)`. This is an account/model restriction exposed by the CLI and is a reason to exclude them from the primary comparison unless privacy treatment is intentionally made part of the design.
- No unavailable or permission-gated entries were printed. Because the list is account-scoped, absence from the list is not evidence about models unavailable globally.

Family counts inferred from the exact identifier prefixes, not independently verified provider metadata:

| Identifier family | Count | Interpretation |
| --- | ---: | --- |
| `gpt-*` | 83 | GPT/Codex/Sol/Terra/Luna/Mini/Nano-labeled families |
| `claude-*` | 88 | Claude Opus/Sonnet/Fable-labeled families |
| `gemini-*` | 10 | Gemini-labeled families |
| `cursor-grok-*` | 14 | Cursor Grok-labeled families |
| `composer-*` | 2 | Cursor Composer-labeled family |
| `kimi-*` | 4 | Kimi-labeled family |
| `glm-*` | 2 | GLM-labeled family |
| `auto` | 1 | Automatic/router mode, excluded from primary comparison |

Selection and identity assessment:

- Deterministic headless selection is supported at the request layer for all 203 listed identifiers through `--print --model <exact-id>`. This conclusion is based on the supported CLI contract and account inventory, not on executing a model task.
- `auto` is not deterministically selectable as an underlying model and is excluded.
- Fast, effort, context, and thinking variants are distinct selectable identifiers but may represent configuration or routing variants within one model family. They are not treated as independent provider families.
- The documented stream-JSON initialization event exposes a `model` field, but the documented example shows a user-facing model label rather than a canonical provider model ID. Therefore the CLI exposes a useful resolved-model label, but this audit cannot yet establish that the label is sufficient to verify the exact underlying provider/model identity after selection. A future zero-provider-safe validation must record the init event from an actual run; no such run is permitted before preregistration approval.
- The three inventory commands exposed no usage, token, cost, quota, or billing fields. No cost information can be established from these read-only commands.

### Recommended subset, not frozen

The following five-model subset is recommended for approval, but is intentionally not frozen:

| Exact model ID | CLI display name | Contrast added |
| --- | --- | --- |
| `gpt-5.3-codex-high` | Codex 5.3 High | Coding-specialized GPT/Codex-labeled family; tests code repair and tool-loop discipline against general-purpose families. |
| `claude-opus-5-thinking-high` | Opus 5 1M Thinking | Claude Opus reasoning family; adds a deliberate deep-investigation contrast for misleading diagnosis and hidden invariants. |
| `gemini-3.7-flash-high` | Gemini 3.7 Flash | Gemini Flash family; adds a distinct provider-labeled, efficiency-oriented contrast without selecting an automatic router. |
| `cursor-grok-4.6-high` | Cursor Grok 4.6 | Cursor Grok family; adds a different provider-labeled reasoning/tool-use behavior under the same Cursor interface. |
| `composer-2.5` | Composer 2.5 | Cursor Composer family; tests whether a Cursor-native model behaves differently from externally labeled families while using the same CLI harness. |

The recommendation avoids `auto`, all `(NO ZDR)` Fable variants, fast duplicates, and redundant effort/context variants. Provider attribution in this table is label-based because the CLI does not expose an independent provider metadata field. If approved unchanged, the proposed matrix would be `3 cases x 5 models x 2 repetitions = 30 experimental runs`. The model set is not frozen and no reservation or preregistration has been created.

Current gate after authenticated inventory:

```text
AUTHENTICATED INVENTORY COMPLETE.
MODEL SUBSET PENDING USER APPROVAL.
STOP BEFORE BENCHMARK IMPLEMENTATION FREEZE OR ANY REAL MODEL INVOCATION.
```

### Approved V1 inventory freeze

On 2026-08-16, the following five exact Cursor CLI selection IDs were approved for V1. This supersedes the preceding non-frozen recommendation and is bound into the preregistration. No other model, alias, effort variant, fast variant, thinking variant, context variant, Fable/NO-ZDR entry, or router mode is part of V1.

```text
gpt-5.3-codex-high
claude-opus-5-thinking-high
gemini-3.7-flash-high
cursor-grok-4.6-high
composer-2.5
```

Frozen evidence:

- Inventory date: `2026-08-16`
- Authenticated account-scoped inventory: `artifacts/cursor-cli-model-inventory-2026-08-16.txt`
- Inventory SHA-256: `442066DD7CE7EC51C20C66EA4983EAB160631147B495C6E86098E7C0C8416DF5`
- Cursor Agent CLI version: `2026.08.11-e8db854`
- Cursor Agent CLI binary SHA-256: `eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831`
- Selection interface: headless `--print --output-format stream-json --model <exact-id>`

The five IDs are intentionally not treated as equivalent capability or compute tiers. They span materially different family/configuration labels and are compared as models selected through a shared Cursor Agent CLI harness. If any frozen ID disappears or becomes unavailable before execution, the corresponding slot fails closed and no substitute is permitted. The `auto` mode remains excluded because exact underlying model identity is ambiguous.

The structured initialization `model` field remains recorded as `cursor_reported_model`, but it is not treated as canonical provider identity. The preregistration therefore separates `model_requested`, `cursor_reported_model`, `model_selection_accepted`, and `underlying_provider_identity_verified`.

## Edge Cases & Error Handling

- GUI model configuration must not be treated as a headless model-selection API.
- `Auto` must be excluded from any future primary benchmark because it does not identify the underlying model deterministically.
- A command that launches the desktop UI or does not return agent-specific help must not be treated as a successful zero-provider preflight.
- No authentication values, API keys, tokens, browser profiles, or unrelated host credentials were read or written.
- The audit must not infer model names from private Cursor configuration, undocumented endpoints, or process internals.
- The installed CLI must be re-audited if its executable, version, endpoint, authentication state, or command surface changes.
- Authentication may be established only through Cursor's supported `agent login` flow or an externally supplied API credential; credentials must never be written into project artifacts. The login flow must complete before inventory enumeration can succeed.
- Model enumeration must be performed before freezing the candidate inventory. `Auto`, router modes, and any identity-ambiguous selection must be excluded from the primary benchmark.

## Acceptance Criteria

- [x] The installed Cursor executable name and exact path are recorded.
- [x] The installed Cursor version, commit, architecture, and executable hashes are recorded.
- [x] Presence, exact path, version, and hash of the dedicated Cursor Agent CLI are recorded.
- [x] Headless execution and model-selection behavior are based on observed local interface output, not assumed flags.
- [x] Model enumeration is confirmed as supported but authentication-gated; no inventory is claimed without successful enumeration.
- [x] Authenticated enumeration is recorded with exact commands, count, model IDs, display names, modes, and restrictions.
- [x] The complete authenticated inventory is preserved as a separate raw-output artifact.
- [x] A non-frozen 4-6 model recommendation and proposed run count are recorded.
- [x] Structured output, session, approval, sandbox, working-directory, authentication, and usage limitations are recorded.
- [x] Official Cursor documentation and the official installer source are identified.
- [x] No real benchmark model invocation was made.
- [x] The pre-authentication audit failed closed, the authenticated inventory was completed, the approved V1 freeze is recorded, and no real benchmark model invocation was made.
