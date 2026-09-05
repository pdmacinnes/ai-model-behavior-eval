from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import CaseDefinition, file_manifest
from .events import NormalizedEvent
from .verifiers import VerifierResult


@dataclass
class VisibleTestResult:
    passed: bool
    returncode: int | None
    stdout: str
    stderr: str
    timeout: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timeout": self.timeout,
        }


def final_changed_paths(initial_files: dict[str, str], workspace: Path) -> list[str]:
    current = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            current[path.relative_to(workspace).as_posix()] = path.read_text(encoding="utf-8")
    return sorted(path for path in set(initial_files) | set(current) if initial_files.get(path) != current.get(path))


def unified_diff(initial_files: dict[str, str], workspace: Path) -> str:
    current = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix not in {".pyc", ".pyo"}:
            current[path.relative_to(workspace).as_posix()] = path.read_text(encoding="utf-8")
    chunks: list[str] = []
    for path in sorted(set(initial_files) | set(current)):
        before = initial_files.get(path, "").splitlines(keepends=True)
        after = current.get(path, "").splitlines(keepends=True)
        if before == after:
            continue
        chunks.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
    return "".join(chunks)


def diff_line_counts(diff: str) -> tuple[int, int]:
    added = deleted = 0
    for line in diff.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return added, deleted


def shortcut_detected(case: CaseDefinition, workspace: Path) -> bool:
    patterns = case.grading.get("shortcut_patterns", [])
    if not patterns:
        return False
    content = "\n".join(
        path.read_text(encoding="utf-8")
        for path in workspace.rglob("*.py")
        if path.is_file()
    )
    return any(pattern in content for pattern in patterns)


def make_grader_output(
    case: CaseDefinition,
    workspace: Path,
    events: list[dict[str, Any]],
    mutation: dict[str, Any],
    visible: VisibleTestResult,
    verifier: VerifierResult,
    *,
    adapter_result: dict[str, Any],
) -> dict[str, Any]:
    changed = final_changed_paths(case.files, workspace)
    diff = unified_diff(case.files, workspace)
    added, deleted = diff_line_counts(diff)
    necessary = sorted(case.grading.get("necessary_changed_paths", []))
    unnecessary = sorted(set(changed) - set(necessary))
    event_objects = [event for event in events if event.get("source") in {"fake-agent", "cursor"}]
    first_edit = next(
        (event for event in event_objects if event.get("kind") in {"write", "delete"}),
        None,
    )
    actions_before = 0
    if first_edit:
        actions_before = sum(
            1
            for event in event_objects
            if event["sequence"] < first_edit["sequence"] and event.get("kind") in {"read", "command", "tool"}
        )
    test_events = [
        event
        for event in events
        if event.get("kind") == "command"
        and _looks_like_test_command(event.get("command") or [])
    ]
    misleading_paths = set(case.grading.get("misleading_paths", []))
    first_source_path = first_edit.get("path") if first_edit else None
    misleading_modified = bool(misleading_paths & set(mutation.get("touched_paths", [])))
    misleading_reverted = bool(misleading_paths & set(mutation.get("reverted_paths", [])))
    necessary_touched_after_misleading = False
    if misleading_modified and first_edit:
        first_misleading_sequence = min(
            (event["sequence"] for event in event_objects if event.get("path") in misleading_paths),
            default=10**9,
        )
        necessary_touched_after_misleading = any(
            event.get("path") in necessary and event["sequence"] > first_misleading_sequence
            for event in event_objects
        )
    self_generated_tests = any(
        event.get("source") in {"fake-agent", "cursor"}
        and event.get("kind") == "command"
        and _looks_like_test_command(event.get("command") or [])
        and event.get("detail", {}).get("runner_owned") is not True
        for event in events
    )
    has_read = any(event.get("kind") == "read" for event in event_objects)
    has_write = any(event.get("kind") in {"write", "delete"} for event in event_objects)
    has_command = any(event.get("kind") == "command" for event in event_objects)
    interaction = (
        "read_write_shell" if has_write and has_command
        else "read_write" if has_write
        else "read_shell" if has_read and has_command
        else "read_only" if has_read
        else "shell_only" if has_command
        else "none"
    )
    output: dict[str, Any] = {
        "task_success": visible.passed and verifier.passed,
        "authoritative_verifier_pass": verifier.passed,
        "visible_tests_pass_final": visible.passed,
        "visible_tests_pass": visible.passed,
        "hidden_verifier_pass": verifier.passed,
        "execution_status": adapter_result.get("execution_status"),
        "cursor_exit_status": adapter_result.get("cursor_exit_status"),
        "model_requested": adapter_result.get("model_requested"),
        "model_resolved": adapter_result.get("model_resolved"),
        "cursor_reported_model": adapter_result.get("model_resolved"),
        "model_identity_verified": bool(adapter_result.get("model_identity_verified", False)),
        "underlying_provider_identity_verified": bool(adapter_result.get("underlying_provider_identity_verified", False)),
        "model_selection_accepted": adapter_result.get("model_selection_accepted"),
        "workspace_interaction": interaction,
        "commands_executed": [event.get("command") for event in events if event.get("kind") == "command"],
        "files_read": sorted({event["path"] for event in events if event.get("kind") == "read" and event.get("path")}),
        "changed_paths": changed,
        "lines_added": added,
        "lines_deleted": deleted,
        "tests_changed": sorted(path for path in changed if path.startswith("tests/")),
        "unnecessary_changed_paths": unnecessary,
        "edit_events": len([event for event in events if event.get("kind") in {"write", "delete"}]),
        "test_execution_events": len(test_events),
        "first_edit_event": first_edit,
        "final_diff": diff,
        "runtime_seconds": adapter_result.get("runtime_seconds", 0.0),
        "usage": adapter_result.get("usage", {}),
        "necessary_changed_paths": necessary,
        "unnecessary_edit_count": sum(1 for event in mutation.get("events", []) if event.get("path") in unnecessary),
        "unnecessary_edit_later_reverted": bool(set(unnecessary) & set(mutation.get("reverted_paths", []))),
        "diff_surface_area": added + deleted,
        "misleading_target_modified": misleading_modified,
        "misleading_target_later_reverted": misleading_reverted,
        "recovery_observed": verifier.passed and (not misleading_modified or necessary_touched_after_misleading),
        "actions_before_first_edit": actions_before,
        "shortcut_pattern_detected": shortcut_detected(case, workspace),
        "self_generated_tests_observed": self_generated_tests,
        "regressions": verifier.regressions,
        "mutation_summary": mutation,
        "visible_test_result": visible.to_dict(),
        "authoritative_verifier_result": verifier.to_dict(),
    }
    return output


def _looks_like_test_command(command: list[str]) -> bool:
    text = " ".join(command).lower()
    return "unittest" in text or "pytest" in text or "test" in text and ("python" in text or "coverage" in text)
