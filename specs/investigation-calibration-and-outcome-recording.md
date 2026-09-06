# Spec: Investigation Calibration and Outcome Recording

## Requirements & Goals

- Make the `dashboard-filter-refresh` family valid for substantive model-behavior study before running additional live providers or models.
- Ensure both dashboard variants can be investigated and repaired within their declared evidence budget.
- Make workspace navigation explicit and inexpensive so differences in file-path discovery are not mistaken for differences in causal reasoning.
- Preserve the distinction between:
  - the model's observable investigation and hypothesis formation,
  - whether it attempted a repair, and
  - whether the final workspace satisfies the registered source invariant.
- Make the `inspect` tool contract match the implementation: `inspect` returns raw visible file bytes, while authored observation text is used only by authored observation actions such as `trace` and `run_test`.
- Keep hidden causes, verifier declarations, calibration metadata, workspace paths, and private reasoning out of the model task and public release.
- Do not add live provider calls, model-specific behavior, chain-of-thought capture, or performance scoring in this milestone.

## Inputs, Outputs & Behavior

### `list_files` (opt-in)

- The dashboard case family opts into a zero-cost `list_files` evidence action (`action_costs.list_files: 0`).
  - The action accepts the target `.` only.
  - It returns a sorted newline-delimited list of relative visible workspace paths.
  - It returns file paths only, never file contents, hidden causes, verifier data, or calibration data.
  - The response is bounded by the family response limit (`max_response_chars`).
- The workspace tool contract advertises `list_files` only for families that include it in `allowed_actions` and `action_costs`. Other pilot families remain unchanged and do not gain the action by default.
- A rejected `list_files` target refunds its reserved cost (a no-op when cost is zero) and records the rejection like other rejected evidence actions. The action must not enumerate outside the disposable workspace.
- Enumeration uses the same workspace-boundary helpers as inspect/search: skip symlinks/junctions, use normalized relative POSIX paths, and never return absolute paths or the workspace root string.

### Dashboard budget

- The dashboard family raises `max_cost` to `10` while preserving the existing non-zero action costs (`inspect`/`search` 1, `trace`/`run_test` 2, `edit` 3).
- This permits a bounded path such as: free `list_files`, one `trace` (2), two `inspect`s (2), and two required `edit`s (6) for `query-omitted` (total 10). `cache-key-static` remains solvable with spare budget.
- The dashboard family keeps the same paired symptom, variant files, hidden causes, registered verifiers, and canonical mutation proofs. The calibration change must not expose answer-key metadata.

### Outcome annotations

- `analyze_trace` adds observable outcome fields to `behavioral_annotations.json`:
  - `repair_attempted`: whether an accepted `edit` action occurred;
  - `edit_count`: number of accepted edits;
  - `termination_reason`: the recorded stop reason when a stop event is present, otherwise `null`;
  - `budget_exhausted`: `true` when `remaining_cost == 0` at end of trace **or** any rejected action recorded the budget-exceeded error; otherwise `false`.
- These fields are descriptive annotations only. They do not convert a failed verifier into a pass and do not infer private reasoning or hidden causes.
- Existing annotation fields (`first_action`, sequences, checkpoints, etc.) remain. `revealed_factors` remain internal answer-key-adjacent annotations and continue to be stripped from public releases.

### Verifier boundary

- `verifier_result` remains a final-workspace invariant result:
  - `passed` means the registered source postcondition is present;
  - `failed` means it is absent or inconsistent;
  - infrastructure-censored statuses remain reserved for adapter lifecycle failures.
- Correct-looking hypotheses with no edit are behavioral outcomes: `repair_attempted: false`, separate verifier failure, not censorship.

### Inspect contract honesty

- The authoring contract, tool descriptions, and documentation state that `inspect` returns raw bytes from the visible materialized file.
- Authored `inspect` observation prose in case JSON must not be presented as the runtime `inspect` response. If retained for analysis-only `reveals` matching, that metadata must not be treated as model-visible evidence content.
- Runtime `trace` and `run_test` continue to return authored observation text.

### Public release

- Public sanitization continues to remove hidden verifier, cause, calibration, and `reveals` / `revealed_factors` data while retaining the permitted observable trace fields and the new outcome annotations (`repair_attempted`, `edit_count`, `termination_reason`, `budget_exhausted`).

## Edge Cases & Error Handling

- `list_files` with a target other than `.` (including empty targets and relative paths) is rejected without changing workspace state.
- A workspace with no visible files returns an empty bounded listing rather than hidden fixture metadata.
- A listing that exceeds the response bound is rejected with a bounded tool error and its cost is refunded.
- The file inventory must use normalized relative POSIX paths and must not include symlinks, junctions, parent traversal, absolute paths, workspace roots, or files created outside the materialized workspace.
- `max_cost` must be sufficient for both registered dashboard mutation proofs. Tests must prove that the required edit sequence can complete without relying on an impossible budget (for `query-omitted`, two accepted edits totaling cost 6 with `max_cost` 10).
- A model may form a correct-looking hypothesis and stop without editing. The run must record `repair_attempted: false`, preserve the trace, and report the verifier result separately. This is a behavioral outcome, not infrastructure censorship.
- A model may edit incorrectly, edit only one file, or exhaust its budget before editing. These cases remain verifier failures but must be distinguishable through mutation and annotation artifacts (`edit_count`, `repair_attempted`, `budget_exhausted`).
- Existing timeout, subprocess, channel-sealing, workspace-cleanup, public-sanitization, and provider network-policy behavior must remain unchanged.
- The implementation must not serialize hidden causes, verifier declarations, calibration proofs, API credentials, or absolute workspace paths into task-visible or publishable artifacts.

## Acceptance Criteria

- [ ] A spec-aligned implementation adds `list_files` to the workspace protocol for opted-in families and advertises it in the tool contract.
- [ ] `list_files` returns only the sorted relative visible file paths and rejects non-`.` targets, traversal, symlink, and output-bound cases.
- [ ] The dashboard family has `max_cost: 10` and `list_files` cost `0`, and its `query-omitted` mutation proof can be applied through two accepted edits without budget exhaustion.
- [ ] A deterministic workspace-runner test completes `list_files`, evidence inspection, and the required edits for both dashboard variants, and both registered verifiers pass.
- [ ] Trace-analysis tests cover repair attempted, edit count, termination reason, and budget exhaustion for successful edits, no-edit stops, and budget-exceeded runs.
- [ ] Tests prove that an accepted `inspect` action returns raw materialized file content and does not substitute authored observation prose.
- [ ] Tests prove that the new task-visible inventory and annotations contain no hidden cause, verifier declaration, calibration metadata, workspace root, or credential values.
- [ ] Public release tests prove hidden verifier and calibration data remain excluded while permitted observable annotations (`repair_attempted`, `edit_count`, `termination_reason`, `budget_exhausted`) remain available.
- [ ] Existing provider-worker, subprocess-adapter, workspace-lifecycle, execution-policy, and full test suites remain green.
- [ ] No live provider request is made by the implementation or test suite.
