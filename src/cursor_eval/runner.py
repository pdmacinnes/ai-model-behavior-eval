from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .adapters import AdapterResult, FakeCursorAdapter, RealCursorAdapter, RealInvocationBlocked, _clean_agent_env
from .artifacts import write_run_artifacts
from .canonical import CaseDefinition, file_manifest, materialize_case
from .events import EventLog
from .grader import VisibleTestResult, make_grader_output
from .observer import MutationObserver
from .reservation import ReservationLedger
from .verifiers import verify_case


def run_visible_tests(case: CaseDefinition, workspace: Path, *, timeout_seconds: float = 30.0, events: EventLog | None = None) -> VisibleTestResult:
    command = list(case.visible_test_command)
    if command and command[0] == "python":
        command[0] = sys.executable
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            cwd=workspace,
            env=_clean_agent_env(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        if events:
            events.record("runner", "command", command=command, detail={"runner_owned": True, "timeout": True})
        return VisibleTestResult(False, None, exc.stdout or "", exc.stderr or "", timeout=True)
    if events:
        events.record(
            "runner",
            "command",
            command=command,
            detail={
                "runner_owned": True,
                "returncode": completed.returncode,
                "runtime_seconds": time.monotonic() - started,
            },
        )
    return VisibleTestResult(completed.returncode == 0, completed.returncode, completed.stdout, completed.stderr)


def _write_workspace_snapshot(path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(file_manifest(path), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def run_trial(
    case: CaseDefinition,
    model_requested: str,
    repetition: int,
    adapter: FakeCursorAdapter | RealCursorAdapter,
    *,
    registration_id: str,
    workspace_parent: Path,
    results_root: Path,
    reservations_root: Path,
    prompt: str | None = None,
    timeout_seconds: float = 300.0,
) -> dict[str, Any]:
    ledger = ReservationLedger(reservations_root)
    reservation = ledger.reserve(registration_id, case.case_id, model_requested, repetition)
    run_id = str(uuid.uuid4())
    workspace = Path(tempfile.mkdtemp(prefix=f"{case.case_id}-{run_id}-", dir=workspace_parent))
    artifact_dir = results_root / "runs" / run_id
    events = EventLog()
    started = time.monotonic()
    execution_exception: str | None = None
    materialize_case(case, workspace)
    initial_manifest = file_manifest(workspace)
    observer = MutationObserver(workspace)
    observer.start()
    try:
        try:
            result = adapter.run(workspace, prompt or case.prompt, model_requested, events)
        except RealInvocationBlocked as exc:
            execution_exception = f"{type(exc).__name__}: {exc}"
            result = AdapterResult("blocked", None, "", error=execution_exception)
    finally:
        mutation = observer.stop()
    result_dict = asdict(result)
    result_dict["model_requested"] = model_requested
    result_dict["execution_exception"] = execution_exception
    visible = run_visible_tests(case, workspace, events=events)
    verifier = verify_case(case.case_id, workspace)
    grader = make_grader_output(
        case,
        workspace,
        events.snapshot(),
        mutation,
        visible,
        verifier,
        adapter_result=result_dict,
    )
    grader["registration_id"] = registration_id
    grader["run_id"] = run_id
    grader["case_id"] = case.case_id
    grader["case_sha256"] = case.canonical_sha256
    grader["model_requested"] = model_requested
    grader["repetition"] = repetition
    grader["prompt"] = prompt or case.prompt
    grader["runtime_seconds"] = time.monotonic() - started
    infra = result.execution_status != "completed"
    outcome_class = "infrastructure_censored" if infra else "behavioral"
    artifacts = {
        "registration.json": {"registration_id": registration_id},
        "prompt.txt": prompt or case.prompt,
        "initial_workspace_manifest.json": initial_manifest,
        "final_workspace_manifest.json": file_manifest(workspace),
        "raw_cursor_output.txt": result.raw_output,
        "normalized_events.jsonl": "\n".join(json.dumps(event, sort_keys=True) for event in events.snapshot()) + "\n",
        "mutation_observer.json": mutation,
        "visible_test_result.json": visible.to_dict(),
        "authoritative_verifier_result.json": verifier.to_dict(),
        "grader.json": grader,
        "final_diff.patch": grader["final_diff"],
        "adapter_result.json": result_dict,
        "run.json": {
            "run_id": run_id,
            "registration_id": registration_id,
            "reservation_id": reservation["reservation_id"],
            "case_id": case.case_id,
            "case_sha256": case.canonical_sha256,
            "model_requested": model_requested,
            "repetition": repetition,
            "execution_status": result.execution_status,
            "outcome_class": outcome_class,
            "workspace_path": str(workspace),
            "runtime_seconds": grader["runtime_seconds"],
        },
    }
    write_run_artifacts(artifact_dir, artifacts)
    ledger.consume(reservation["reservation_id"], status=outcome_class, run_id=run_id)
    try:
        shutil.rmtree(workspace)
    except OSError:
        pass
    return grader
