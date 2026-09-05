from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from .canonical import CaseDefinition, load_case, sha256_bytes
from .environment import collect_environment


FROZEN_MODEL_IDS = (
    "gpt-5.3-codex-high",
    "claude-opus-5-thinking-high",
    "gemini-3.7-flash-high",
    "cursor-grok-4.6-high",
    "composer-2.5",
)
INVENTORY_RELATIVE = Path("artifacts/cursor-cli-model-inventory-2026-08-16.txt")
INVENTORY_SHA256 = "442066DD7CE7EC51C20C66EA4983EAB160631147B495C6E86098E7C0C8416DF5"
CURSOR_AGENT_VERSION = "2026.08.11-e8db854"
CURSOR_AGENT_BINARY_SHA256 = "eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831"


def _hash_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _binding_files(project_root: Path) -> list[Path]:
    files: list[Path] = []
    files.extend(sorted((project_root / "src" / "cursor_eval").glob("*.py")))
    files.extend(sorted((project_root / "scripts").glob("*.py")))
    files.append(project_root / "pyproject.toml")
    files.extend(sorted((project_root / "cases").glob("*/canonical.json")))
    files.append(project_root / INVENTORY_RELATIVE)
    return [path for path in files if path.is_file()]


def executor_binding(project_root: Path) -> dict[str, Any]:
    entries = []
    for path in _binding_files(project_root):
        relative = path.relative_to(project_root).as_posix()
        entries.append({"path": relative, "sha256": _hash_file(path)})
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"files": entries, "sha256": sha256_bytes(encoded)}


def _case_records(project_root: Path) -> list[dict[str, Any]]:
    records = []
    for case_dir in sorted((project_root / "cases").iterdir()):
        canonical = case_dir / "canonical.json"
        if not canonical.is_file():
            continue
        case = load_case(canonical)
        verifier = project_root / "src" / "cursor_eval" / "verifiers.py"
        records.append(
            {
                "case_id": case.case_id,
                "canonical_path": canonical.relative_to(project_root).as_posix(),
                "canonical_sha256": case.canonical_sha256,
                "prompt": case.prompt,
                "prompt_sha256": sha256_bytes(case.prompt.encode("utf-8")),
                "visible_test_command": list(case.visible_test_command),
                "verifier_id": case.grading["verifier_id"],
                "verifier_source_sha256": _hash_file(verifier),
                "necessary_changed_paths": list(case.grading.get("necessary_changed_paths", [])),
                "misleading_paths": list(case.grading.get("misleading_paths", [])),
            }
        )
    if {record["case_id"] for record in records} != {"recovery", "minimal_patch", "hidden_invariant"}:
        raise ValueError("V1 requires exactly the three named cases")
    return records


def build_registration(project_root: Path, *, registration_date: str | None = None) -> dict[str, Any]:
    project_root = project_root.resolve()
    cases = _case_records(project_root)
    slots = []
    for case in cases:
        for model_id in FROZEN_MODEL_IDS:
            for repetition in (1, 2):
                slots.append(
                    {
                        "case_id": case["case_id"],
                        "model_requested": model_id,
                        "repetition": repetition,
                        "state": "pending",
                    }
                )
    if len(slots) != 30:
        raise AssertionError("unexpected V1 slot count")
    inventory = project_root / INVENTORY_RELATIVE
    if _hash_file(inventory).lower() != INVENTORY_SHA256.lower():
        raise ValueError("inventory evidence hash does not match the approved V1 inventory")
    environment = collect_environment(project_root)
    environment.update(
        {
            "cursor_agent_version": CURSOR_AGENT_VERSION,
            "cursor_agent_binary": "cursor-agent",
            "cursor_agent_binary_sha256": CURSOR_AGENT_BINARY_SHA256,
            "cursor_cli_distribution": "Ubuntu WSL 2",
        }
    )
    return {
        "registration_version": "v1",
        "registration_id": "cursor-model-behavior-eval-v1-2026-08-16",
        "registration_date": registration_date or date.today().isoformat(),
        "status": "preregistered_pending_execution_approval",
        "research_question": "How does model selection change coding-agent behavior when selected models are mediated through the same Cursor Agent CLI harness?",
        "interpretation": "System-mediated behavioral comparison, not a controlled comparison of raw base-model capability, equivalent compute, or equivalent capability tiers.",
        "cursor": {
            "agent_version": CURSOR_AGENT_VERSION,
            "executable_name": "agent",
            "executable_path": "agent",
            "distribution": "Ubuntu WSL 2",
            "model_selection": "--model <exact-id>",
            "headless": "--print",
            "output_format": "stream-json",
            "identity_limit": "Cursor-reported model is a user-facing label; underlying provider identity is not asserted without stronger evidence.",
        },
        "inventory_evidence": {
            "path": INVENTORY_RELATIVE.as_posix(),
            "sha256": INVENTORY_SHA256,
            "inventory_date": "2026-08-16",
            "account_scoped": True,
            "model_count_excluding_auto": 203,
            "auto_excluded": True,
        },
        "selected_models": list(FROZEN_MODEL_IDS),
        "cases": cases,
        "trial_matrix": slots,
        "trial_count": len(slots),
        "repetitions_per_case_model": 2,
        "execution_policy": {
            "replacement": "none",
            "adaptive_selection": False,
            "extra_trials": False,
            "all_slots_pending": True,
            "real_invocation_approval_required": True,
        },
        "timeouts": {"agent_seconds": 300, "visible_test_seconds": 30, "hidden_verifier_seconds": 30},
        "censoring_rules": {
            "infrastructure_failures": "consumed and reported separately as infrastructure_censored; never silently rerun or replace",
            "model_unavailable": "fail closed and consume the slot; no substitution",
            "behavioral_failure": "final visible-test or authoritative-verifier failure after a completed agent run",
        },
        "cost_policy": {
            "read_only_cli_cost_fields": "none exposed",
            "hard_cap": "no programmatic hard cap exposed; manual stop required before first trial",
            "maximum_slots": 30,
            "no_cost_estimation_calls": True,
        },
        "environment": environment,
        "executor_critical_binding": executor_binding(project_root),
        "primary_metrics": {
            "all_runs": ["task_success", "authoritative_verifier_pass", "visible_tests_pass_final", "execution_status"],
            "recovery": ["misleading_target_modified", "misleading_target_later_reverted", "recovery_observed", "actions_before_first_edit"],
            "minimal_patch": ["unnecessary_changed_paths", "unnecessary_edit_count", "diff_surface_area"],
            "hidden_invariant": ["visible_tests_pass", "hidden_verifier_pass", "shortcut_pattern_detected"],
        },
        "secondary_metrics": [
            "cursor_exit_status", "model_requested", "cursor_reported_model", "model_selection_accepted",
            "underlying_provider_identity_verified", "model_identity_verified", "workspace_interaction",
            "commands_executed", "files_read", "changed_paths", "lines_added", "lines_deleted", "tests_changed",
            "edit_events", "test_execution_events", "first_edit_event", "final_diff", "runtime_seconds", "usage",
            "self_generated_tests_observed", "regressions", "unnecessary_edit_later_reverted",
        ],
        "analysis_plan": {
            "axes": ["correctness", "investigation_recovery", "patch_discipline", "hidden_invariant_fidelity", "edit_efficiency", "test_behavior"],
            "reporting": "case-level results and descriptive aggregate counts; no weighted composite and no significance testing for two repetitions",
            "unit_of_analysis": "frozen case x frozen model selection x independent repetition",
            "aggregation": "report each case and axis separately; report counts and proportions only; infrastructure-censored runs are excluded from behavioral denominators and reported separately",
        },
        "known_limitations": [
            "The comparison measures models selected through a shared Cursor Agent CLI harness, not raw provider APIs.",
            "Cursor may apply model-dependent routing, prompting, context management, tool formatting, caching, or other integration behavior.",
            "The structured initialization model field is a user-facing label and does not verify canonical provider identity.",
            "Two repetitions per case/model are exploratory and descriptive, not sufficient for population-level ranking or significance testing.",
            "The mutation observer is polling-based and can miss a write shorter than its interval; the interval is recorded per run.",
            "Read-only CLI commands exposed no cost, quota, or billing fields; a manual account-level stop rule is required before execution.",
        ],
        "execution_approval": {"real_cursor_invocations_allowed": False, "all_slots_pending": True},
    }


def validate_registration(registration_path: Path, project_root: Path) -> dict[str, Any]:
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    if registration.get("status") != "preregistered_pending_execution_approval":
        raise ValueError("registration is not in the pending execution state")
    if registration.get("selected_models") != list(FROZEN_MODEL_IDS):
        raise ValueError("selected model set differs from the frozen V1 set")
    if registration.get("trial_count") != 30 or len(registration.get("trial_matrix", [])) != 30:
        raise ValueError("registration does not contain exactly 30 trial slots")
    if any(slot.get("state") != "pending" for slot in registration["trial_matrix"]):
        raise ValueError("a preregistration slot is not pending")
    inventory = project_root / INVENTORY_RELATIVE
    if _hash_file(inventory).lower() != registration["inventory_evidence"]["sha256"].lower():
        raise ValueError("inventory evidence drifted")
    expected = executor_binding(project_root)
    if expected != registration.get("executor_critical_binding"):
        raise ValueError("executor-critical source binding drifted")
    for case in registration.get("cases", []):
        canonical = project_root / case["canonical_path"]
        if _hash_file(canonical).lower() != case["canonical_sha256"].lower():
            raise ValueError(f"case drifted: {case['case_id']}")
    return registration
