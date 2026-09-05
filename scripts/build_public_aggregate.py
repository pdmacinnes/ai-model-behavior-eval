"""Build a sanitized V1 aggregate from an archival results directory."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _usage(grader: dict) -> dict:
    usage = grader.get("usage", {})
    if isinstance(usage, dict) and isinstance(usage.get("usage"), dict):
        usage = usage["usage"]
    return {
        "input_tokens": usage.get("inputTokens"),
        "cache_read_tokens": usage.get("cacheReadTokens"),
        "output_tokens": usage.get("outputTokens"),
    }


def _run_record(run_dir: Path) -> dict:
    run = _read(run_dir / "run.json")
    grader = _read(run_dir / "grader.json")
    mutation = grader.get("mutation_summary", {})
    changed = grader.get("changed_paths", [])
    return {
        "run_id": run["run_id"],
        "case": run["case_id"],
        "model_requested": run["model_requested"],
        "repetition": run["repetition"],
        "cursor_reported_model": grader.get("cursor_reported_model"),
        "model_selection_accepted": grader.get("model_selection_accepted"),
        "underlying_provider_identity_verified": grader.get("underlying_provider_identity_verified"),
        "task_success": grader.get("task_success"),
        "visible_tests_pass": grader.get("visible_tests_pass_final"),
        "authoritative_verifier_pass": grader.get("authoritative_verifier_pass"),
        "execution_status": grader.get("execution_status"),
        "cursor_exit_status": grader.get("cursor_exit_status"),
        "changed_paths": changed,
        "necessary_changed_paths": grader.get("necessary_changed_paths", []),
        "unnecessary_changed_paths": grader.get("unnecessary_changed_paths", []),
        "transient_paths": mutation.get("created_then_deleted_paths", []),
        "reverted_paths": mutation.get("reverted_paths", []),
        "tests_changed": grader.get("tests_changed", []),
        "lines_added": grader.get("lines_added"),
        "lines_deleted": grader.get("lines_deleted"),
        "diff_surface_area": grader.get("diff_surface_area"),
        "edit_events": grader.get("edit_events"),
        "test_execution_events": grader.get("test_execution_events"),
        "actions_before_first_edit": grader.get("actions_before_first_edit"),
        "runtime_seconds": grader.get("runtime_seconds"),
        "misleading_target_modified": grader.get("misleading_target_modified"),
        "misleading_target_later_reverted": grader.get("misleading_target_later_reverted"),
        "recovery_observed": grader.get("recovery_observed"),
        "unnecessary_edit_count": grader.get("unnecessary_edit_count"),
        "unnecessary_edit_later_reverted": grader.get("unnecessary_edit_later_reverted"),
        "shortcut_pattern_detected": grader.get("shortcut_pattern_detected"),
        "self_generated_tests_observed": grader.get("self_generated_tests_observed"),
        "regressions": grader.get("regressions", []),
        **_usage(grader),
    }


def build(source_root: Path) -> dict:
    registration = _read(source_root / "registrations" / "v1.json")
    run_dirs = sorted(
        path for path in (source_root / "results" / "runs").iterdir()
        if path.is_dir() and (path / "run.json").is_file() and (path / "grader.json").is_file()
    )
    runs = [_run_record(path) for path in run_dirs]
    runs.sort(key=lambda item: (item["case"], item["model_requested"], item["repetition"]))
    return {
        "schema": "cursor-model-behavior-eval-v1-public-results",
        "source_registration_id": registration["registration_id"],
        "source_registration_sha256": "06794c654a41c427ee641d64cbcaf58fc7b9ff07e5961611bdcd412d90133d95",
        "source_executor_binding_sha256": "1e56527df806cc8fed7bc08ec2f93c512e32db1d42be54566c571cfc662aec85",
        "trial_count": len(runs),
        "raw_telemetry_included": False,
        "account_identifiers_included": False,
        "local_paths_included": False,
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build(args.source_root.resolve())
    if payload["trial_count"] != 30:
        raise SystemExit(f"expected 30 archived runs, found {payload['trial_count']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
