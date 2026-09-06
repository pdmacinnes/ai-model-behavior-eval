"""Trusted in-process workspace trials; untrusted adapters need subprocess transport."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Protocol

from cursor_eval.artifacts import write_run_artifacts
from cursor_eval.canonical import file_manifest
from cursor_eval.observer import MutationObserver

from .analysis import analyze_trace
from .protocol import ToolResponse
from .runner import AgentResult, ModelCondition
from .schema import CaseFamily, CaseVariant
from .workspace import MaterializedWorkspace, materialize_variant, resolve_workspace_path
from .workspace_grader import WorkspaceVerifier, WorkspaceVerifierResult, invoke_workspace_verifier
from .workspace_verifiers import registered_workspace_verifier


WORKSPACE_PROTOCOL_VERSION = "evidence-workspace-v1"
_WORKSPACE_CHANNELS: dict[str, "_WorkspaceSession"] = {}
_WORKSPACE_CHANNEL_LOCK = threading.Lock()


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("run_id must contain only letters, numbers, underscore, period, or hyphen")
    return value


def _channel_session(channel_id: str) -> "_WorkspaceSession":
    with _WORKSPACE_CHANNEL_LOCK:
        session = _WORKSPACE_CHANNELS.get(channel_id)
    if session is None:
        raise RuntimeError("workspace evidence channel is closed")
    return session


class WorkspaceAdapter(Protocol):
    def __call__(self, task: dict[str, Any], tools: "WorkspaceTools") -> AgentResult: ...


class _WorkspaceSession:
    def __init__(self, family: CaseFamily, variant: CaseVariant, workspace: Path) -> None:
        if variant.family_id != family.family_id:
            raise ValueError("variant does not belong to the supplied case family")
        self.family = family
        self.variant = variant
        self.workspace = workspace
        self.remaining_cost = family.max_cost
        self.status = "active"
        self._sealed = False
        self.events: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []

    def _reject(self, action: str, target: str, cost: int, error: str) -> ToolResponse:
        response = ToolResponse(
            accepted=False,
            action=action,
            target=target,
            content="",
            cost=cost,
            remaining_cost=self.remaining_cost,
            error=error,
        )
        if not self._sealed:
            self.events.append({"kind": "rejected_action", **response.to_dict()})
        return response

    def _reserve(self, action: str, target: str) -> int | ToolResponse:
        cost = self.family.action_costs.get(action)
        if self._sealed:
            return self._reject(action, target, cost or 0, "session is sealed")
        if self.status != "active":
            return self._reject(action, target, cost or 0, "session is no longer active")
        if action not in self.family.allowed_actions or cost is None:
            return self._reject(action, target, 0, "unsupported action")
        if cost > self.remaining_cost:
            return self._reject(action, target, cost, "evidence budget exceeded")
        if len(self.events) >= self.family.max_events:
            self.status = "event_limit"
            return self._reject(action, target, cost, "event limit exceeded")
        self.remaining_cost -= cost
        return cost

    def _refund(self, cost: int) -> None:
        self.remaining_cost += cost

    def _accepted(self, action: str, target: str, content: str, cost: int, *, reveals: tuple[str, ...] = ()) -> ToolResponse:
        response = ToolResponse(
            accepted=True,
            action=action,
            target=target,
            content=content,
            cost=cost,
            remaining_cost=self.remaining_cost,
        )
        self.events.append({"kind": "action", **response.to_dict(), "reveals": list(reveals)})
        return response

    def _inspect(self, target: str) -> tuple[str, str | None]:
        try:
            path = resolve_workspace_path(self.workspace, target)
        except ValueError as exc:
            return "", str(exc)
        if not path.is_file():
            return "", "inspect target is not a visible file"
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            return "", f"could not inspect target: {type(exc).__name__}"
        if len(content) > self.family.max_response_chars:
            return "", "tool output bound exceeded"
        return content, None

    def _search(self, query: str) -> tuple[str, str | None]:
        if not query:
            return "", "search query must not be empty"
        matches: list[str] = []
        lowered = query.lower()
        for path in sorted(self.workspace.rglob("*")):
            if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts:
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError):
                continue
            relative = path.relative_to(self.workspace).as_posix()
            matches.extend(
                f"{relative}:{line_number}: {line}"
                for line_number, line in enumerate(lines, start=1)
                if lowered in line.lower()
            )
        content = "\n".join(matches) if matches else "No matches."
        if len(content) > self.family.max_response_chars:
            return "", "tool output bound exceeded"
        return content, None

    def request(self, action: str, target: str) -> ToolResponse:
        if action == "edit":
            return self._reject(action, target, self.family.action_costs.get(action, 0), "use edit_file for workspace edits")
        reserved = self._reserve(action, target)
        if isinstance(reserved, ToolResponse):
            return reserved
        cost = reserved
        if action == "inspect":
            content, error = self._inspect(target)
        elif action == "search":
            content, error = self._search(target)
        elif action in {"trace", "run_test"}:
            observation = self.variant.observation_for(action, target)
            if observation is None:
                content, error = "", "unsupported target for this case"
            elif len(observation.content) > self.family.max_response_chars:
                content, error = "", "tool output bound exceeded"
            else:
                content, error = observation.content, None
        else:
            content, error = "", "unsupported action"
        if error is not None:
            self._refund(cost)
            return self._reject(action, target, self.family.action_costs.get(action, 0), error)
        observation = self.variant.observation_for(action, target)
        return self._accepted(action, target, content, cost, reveals=observation.reveals if observation else ())

    def edit_file(self, path_text: str, before: str, after: str) -> ToolResponse:
        reserved = self._reserve("edit", path_text)
        if isinstance(reserved, ToolResponse):
            return reserved
        cost = reserved
        try:
            path = resolve_workspace_path(self.workspace, path_text)
        except ValueError as exc:
            self._refund(cost)
            return self._reject("edit", path_text, self.family.action_costs.get("edit", 0), str(exc))
        if not path.is_file():
            self._refund(cost)
            return self._reject("edit", path_text, self.family.action_costs.get("edit", 0), "edit target is not a visible file")
        if before == after or not before:
            self._refund(cost)
            return self._reject("edit", path_text, self.family.action_costs.get("edit", 0), "edit must replace non-empty text with different text")
        if len(before) > self.family.max_response_chars * 4 or len(after) > self.family.max_response_chars * 4:
            self._refund(cost)
            return self._reject("edit", path_text, self.family.action_costs.get("edit", 0), "edit payload exceeded bound")
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self._refund(cost)
            return self._reject("edit", path_text, self.family.action_costs.get("edit", 0), f"could not read edit target: {type(exc).__name__}")
        if source.count(before) != 1:
            self._refund(cost)
            return self._reject("edit", path_text, self.family.action_costs.get("edit", 0), "edit text must match exactly once")
        updated = source.replace(before, after, 1)
        try:
            path.write_text(updated, encoding="utf-8", newline="\n")
        except OSError as exc:
            self.remaining_cost += cost
            return self._reject("edit", path_text, cost, f"could not write edit target: {type(exc).__name__}")
        response = self._accepted("edit", path_text, "", cost)
        self.events[-1].update({
            "before_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "after_sha256": hashlib.sha256(updated.encode("utf-8")).hexdigest(),
        })
        return response

    def checkpoint(self, *, leading_hypothesis: str, alternative_hypothesis: str, confidence: float, changed_by: str, next_action: str) -> None:
        if self.status != "active" or self._sealed:
            raise RuntimeError("cannot checkpoint an inactive session")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if len(self.events) >= self.family.max_events - 1:
            self.status = "event_limit"
            if len(self.events) < self.family.max_events:
                self.events.append({"kind": "rejected_checkpoint", "error": "event limit exceeded"})
            return
        checkpoint = {
            "leading_hypothesis": leading_hypothesis,
            "alternative_hypothesis": alternative_hypothesis,
            "confidence": confidence,
            "changed_by": changed_by,
            "next_action": next_action,
        }
        self.checkpoints.append(checkpoint)
        self.events.append({"kind": "checkpoint", **checkpoint})

    def stop(self, reason: str) -> None:
        if self.status != "active" or self._sealed:
            return
        self.status = "stopped"
        self.events.append({"kind": "stop", "reason": reason, "remaining_cost": self.remaining_cost})

    def seal(self) -> None:
        self._sealed = True

    def to_record(self) -> dict[str, Any]:
        return {
            "family_id": self.family.family_id,
            "variant_id": self.variant.variant_id,
            "case_sha256": self.family.canonical_sha256,
            "status": self.status,
            "remaining_cost": self.remaining_cost,
            "events": list(self.events),
            "checkpoints": list(self.checkpoints),
        }


class WorkspaceTools:
    """Bounded workspace capability facade for trusted adapter wrappers."""

    __slots__ = ("__channel_id",)

    def __init__(self, channel_id: str) -> None:
        self.__channel_id = channel_id

    def request(self, action: str, target: str) -> ToolResponse:
        return _channel_session(self.__channel_id).request(action, target)

    def edit_file(self, path: str, before: str, after: str) -> ToolResponse:
        return _channel_session(self.__channel_id).edit_file(path, before, after)

    def checkpoint(self, *, leading_hypothesis: str, alternative_hypothesis: str, confidence: float, changed_by: str, next_action: str) -> None:
        _channel_session(self.__channel_id).checkpoint(
            leading_hypothesis=leading_hypothesis,
            alternative_hypothesis=alternative_hypothesis,
            confidence=confidence,
            changed_by=changed_by,
            next_action=next_action,
        )

    def stop(self, reason: str) -> None:
        _channel_session(self.__channel_id).stop(reason)


def workspace_tool_contract(family: CaseFamily) -> dict[str, Any]:
    evidence_actions = [action for action in family.allowed_actions if action != "edit"]
    return {
        "protocol_version": WORKSPACE_PROTOCOL_VERSION,
        "tools": [
            {
                "type": "function",
                "name": "request_evidence",
                "description": "Inspect, search, trace, or run one bounded local evidence action.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": evidence_actions},
                        "target": {"type": "string"},
                    },
                    "required": ["action", "target"],
                    "additionalProperties": False,
                },
                "returns": ["accepted", "action", "target", "content", "cost", "remaining_cost", "error"],
            },
            {
                "type": "function",
                "name": "edit_file",
                "description": "Replace one exact text occurrence in a visible workspace file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "before": {"type": "string"},
                        "after": {"type": "string"},
                    },
                    "required": ["path", "before", "after"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "record_checkpoint",
                "description": "Record an observable hypothesis checkpoint without requesting hidden reasoning.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "leading_hypothesis": {"type": "string"},
                        "alternative_hypothesis": {"type": "string"},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "changed_by": {"type": "string"},
                        "next_action": {"type": "string"},
                    },
                    "required": ["leading_hypothesis", "alternative_hypothesis", "confidence", "changed_by", "next_action"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "stop_investigation",
                "description": "End the investigation and record the termination reason.",
                "parameters": {
                    "type": "object",
                    "properties": {"reason": {"type": "string"}},
                    "required": ["reason"],
                    "additionalProperties": False,
                },
            },
        ],
        "allowed_actions": list(family.allowed_actions),
        "action_costs": dict(sorted(family.action_costs.items())),
        "max_cost": family.max_cost,
        "max_events": family.max_events,
        "max_response_chars": family.max_response_chars,
    }


def run_workspace_trial(
    family: CaseFamily,
    variant: CaseVariant,
    condition: ModelCondition,
    adapter: WorkspaceAdapter,
    *,
    artifacts_root: Path,
    workspace_parent: Path,
    verifier: WorkspaceVerifier | None = None,
    run_id: str | None = None,
    registration_id: str = "unregistered",
    adapter_timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    if variant.family_id != family.family_id:
        raise ValueError("variant does not belong to the supplied case family")
    if condition.prompt != family.initial_context.get("prompt"):
        raise ValueError("condition prompt must match the case's frozen prompt")
    resolved_run_id = _safe_run_id(run_id or str(uuid.uuid4()))
    workspace_parent.mkdir(parents=True, exist_ok=True)
    workspace: Path | None = None
    channel_id: str | None = None
    worker: threading.Thread | None = None
    timed_out = False
    try:
        workspace = Path(tempfile.mkdtemp(prefix=f"{family.family_id}-{resolved_run_id}-", dir=workspace_parent))
        materialized: MaterializedWorkspace = materialize_variant(variant, workspace)
        session = _WorkspaceSession(family, variant, workspace)
        channel_id = uuid.uuid4().hex
        with _WORKSPACE_CHANNEL_LOCK:
            _WORKSPACE_CHANNELS[channel_id] = session
        tools = WorkspaceTools(channel_id)
        contract = workspace_tool_contract(family)
        task: dict[str, Any] = dict(family.initial_context)
        task["tool_contract"] = contract
        task_hash = _hash_json(task)
        contract_hash = _hash_json(contract)
        started_at = time.time()
        started = time.monotonic()
        holder: dict[str, AgentResult] = {}
        failures: dict[str, BaseException] = {}

        def invoke() -> None:
            try:
                candidate = adapter(task, tools)
                if not isinstance(candidate, AgentResult):
                    raise TypeError("workspace adapters must return AgentResult")
                holder["result"] = candidate
            except BaseException as exc:  # Adapter failures are data, not interactive prompts.
                failures["error"] = exc

        observer = MutationObserver(workspace)
        observer.start()
        worker = threading.Thread(target=invoke, name=f"workspace-adapter-{resolved_run_id}", daemon=True)
        worker.start()
        worker.join(timeout=adapter_timeout_seconds)
        worker_alive = worker.is_alive()
        timed_out = worker_alive
        if worker_alive:
            result = AgentResult(status="adapter_timeout", error=f"adapter exceeded {adapter_timeout_seconds:.3f}s")
            session.stop("adapter timeout")
        elif "error" in failures:
            exc = failures["error"]
            result = AgentResult(status="adapter_error", error=f"{type(exc).__name__}: {exc}")
            session.stop("adapter error")
        else:
            result = holder["result"]
            if len(result.final_response) > family.max_response_chars:
                result = AgentResult(
                    status="adapter_output_limit",
                    final_response=result.final_response[: family.max_response_chars],
                    metadata=dict(result.metadata),
                    error="final response exceeded output bound and was truncated",
                )
        if session.status == "active":
            session.stop("adapter returned without stopping")
        session.seal()
        with _WORKSPACE_CHANNEL_LOCK:
            _WORKSPACE_CHANNELS.pop(channel_id, None)
        mutation = observer.stop()
        trace = session.to_record()
        annotations = analyze_trace(trace)
        if timed_out:
            verifier_result = WorkspaceVerifierResult(
                verifier_id=f"{family.family_id}:timeout",
                status="timeout",
                passed=False,
                checks={},
                regressions=[],
                error="workspace verification skipped because the in-process adapter did not terminate",
            )
        else:
            verifier_result = invoke_workspace_verifier(verifier or registered_workspace_verifier(family), family, variant, workspace)
        final_manifest = file_manifest(workspace)
        run_record = {
            "run_id": resolved_run_id,
            "registration_id": registration_id,
            "family_id": family.family_id,
            "variant_id": variant.variant_id,
            "case_sha256": family.canonical_sha256,
            "condition": condition.to_dict(),
            "task_hash": task_hash,
            "prompt_hash": hashlib.sha256(condition.prompt.encode("utf-8")).hexdigest(),
            "tool_contract_hash": contract_hash,
            "environment_sha256": _hash_json({"case_sha256": family.canonical_sha256, "task_hash": task_hash, "tool_contract_hash": contract_hash, "workspace_manifest_sha256": materialized.manifest_sha256}),
            "protocol_version": WORKSPACE_PROTOCOL_VERSION,
            "started_at_utc_epoch": started_at,
            "runtime_seconds": time.monotonic() - started,
            "execution_status": result.status,
            "infrastructure_censored": result.status in {"adapter_timeout", "adapter_error"},
            "verifier_result": verifier_result.to_dict(),
            "initial_workspace_manifest_sha256": materialized.manifest_sha256,
            "final_workspace_manifest_sha256": _hash_json(final_manifest),
            "workspace_cleanup_deferred": timed_out,
            "workspace_cleanup_reason": "adapter_thread_alive_after_timeout" if timed_out else None,
        }
        artifacts = {
            "run.json": run_record,
            "condition.json": condition.to_dict(),
            "task.json": task,
            "tool_contract.json": contract,
            "prompt.txt": condition.prompt,
            "initial_workspace_manifest.json": materialized.files,
            "final_workspace_manifest.json": final_manifest,
            "mutation_observer.json": mutation,
            "event_trace.json": trace,
            "final_response.txt": result.final_response,
            "adapter_result.json": result.to_dict(),
            "verifier_result.json": verifier_result.to_dict(),
            "behavioral_annotations.json": annotations,
        }
        write_run_artifacts(artifacts_root / "runs" / resolved_run_id, artifacts)
    finally:
        if channel_id is not None:
            with _WORKSPACE_CHANNEL_LOCK:
                _WORKSPACE_CHANNELS.pop(channel_id, None)
        if workspace is not None and not timed_out:
            try:
                shutil.rmtree(workspace)
            except OSError:
                pass
    return run_record | {
        "trace": trace,
        "adapter_result": result.to_dict(),
        "verifier_result": verifier_result.to_dict(),
        "behavioral_annotations": annotations,
        "mutation_observer": mutation,
    }
