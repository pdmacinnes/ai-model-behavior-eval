from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from cursor_eval.artifacts import write_run_artifacts

from .analysis import analyze_trace
from .protocol import EvidenceSession, ToolResponse
from .schema import CaseFamily, CaseVariant


PROTOCOL_VERSION = "evidence-protocol-v1"
_CHANNELS: dict[str, EvidenceSession] = {}


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ModelCondition:
    provider: str
    model_id: str
    adapter_id: str
    prompt: str
    reasoning_effort: str | None = None
    harness_version: str = "0.1.0"

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "adapter_id": self.adapter_id,
            "prompt": self.prompt,
            "reasoning_effort": self.reasoning_effort,
            "harness_version": self.harness_version,
        }


@dataclass(frozen=True)
class AgentResult:
    status: str
    final_response: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "final_response": self.final_response,
            "metadata": dict(self.metadata),
            "error": self.error,
        }


class EvidenceAdapter(Protocol):
    def __call__(self, task: dict[str, Any], tools: "EvidenceTools") -> AgentResult: ...


class EvidenceTools:
    """A capability facade that exposes no case or session object to adapters."""

    __slots__ = ("__channel_id",)

    def __init__(self, channel_id: str) -> None:
        self.__channel_id = channel_id

    def request(self, action: str, target: str) -> ToolResponse:
        return _CHANNELS[self.__channel_id].request(action, target)

    def checkpoint(
        self,
        *,
        leading_hypothesis: str,
        alternative_hypothesis: str,
        confidence: float,
        changed_by: str,
        next_action: str,
    ) -> None:
        _CHANNELS[self.__channel_id].checkpoint(
            leading_hypothesis=leading_hypothesis,
            alternative_hypothesis=alternative_hypothesis,
            confidence=confidence,
            changed_by=changed_by,
            next_action=next_action,
        )

    def stop(self, reason: str) -> None:
        _CHANNELS[self.__channel_id].stop(reason)


def tool_contract(family: CaseFamily) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "tools": [
            {
                "type": "function",
                "name": "request_evidence",
                "description": "Request one bounded evidence action for the current debugging task.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": list(family.allowed_actions)},
                        "target": {"type": "string"},
                    },
                    "required": ["action", "target"],
                    "additionalProperties": False,
                },
                "returns": ["accepted", "action", "target", "content", "cost", "remaining_cost", "error"],
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


def _safe_run_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise ValueError("run_id must contain only letters, numbers, underscore, period, or hyphen")
    return value


def run_unattended_trial(
    family: CaseFamily,
    variant: CaseVariant,
    condition: ModelCondition,
    adapter: EvidenceAdapter,
    *,
    artifacts_root: Path,
    run_id: str | None = None,
    registration_id: str = "unregistered",
    adapter_timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    if variant.family_id != family.family_id:
        raise ValueError("variant does not belong to the supplied case family")
    if condition.prompt != family.initial_context.get("prompt"):
        raise ValueError("condition prompt must match the case's frozen prompt")

    resolved_run_id = _safe_run_id(run_id or str(uuid.uuid4()))
    session = EvidenceSession(family, variant)
    channel_id = uuid.uuid4().hex
    _CHANNELS[channel_id] = session
    tools = EvidenceTools(channel_id)
    contract = tool_contract(family)
    task: dict[str, Any] = dict(family.initial_context)
    task["tool_contract"] = contract
    task_hash = _hash_json(task)
    contract_hash = _hash_json(contract)
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    holder: dict[str, AgentResult] = {}
    failures: dict[str, BaseException] = {}

    def invoke() -> None:
        try:
            candidate = adapter(task, tools)
            if not isinstance(candidate, AgentResult):
                raise TypeError("evidence adapters must return AgentResult")
            holder["result"] = candidate
        except BaseException as exc:  # Adapter failures are data, not interactive prompts.
            failures["error"] = exc

    worker = threading.Thread(target=invoke, name=f"evidence-adapter-{resolved_run_id}", daemon=True)
    worker.start()
    worker.join(timeout=adapter_timeout_seconds)
    if worker.is_alive():
        result = AgentResult(status="adapter_timeout", error=f"adapter exceeded {adapter_timeout_seconds:.3f}s")
        session.stop("adapter timeout")
        session.seal()
    elif "error" in failures:
        exc = failures["error"]
        result = AgentResult(status="adapter_error", error=f"{type(exc).__name__}: {exc}")
        session.stop("adapter error")
        session.seal()
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

    trace = session.to_record()
    annotations = analyze_trace(trace)
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
        "environment_sha256": _hash_json({"case_sha256": family.canonical_sha256, "task_hash": task_hash, "tool_contract_hash": contract_hash}),
        "protocol_version": PROTOCOL_VERSION,
        "started_at_utc": started_at,
        "runtime_seconds": time.monotonic() - started,
        "execution_status": result.status,
        "verifier_result": {
            "status": "declarative_only",
            "reason": "protocol-only trial has no materialized workspace or executable verifier",
            "declaration": dict(variant.verifier),
        },
    }
    artifacts = {
        "run.json": run_record,
        "condition.json": condition.to_dict(),
        "task.json": task,
        "tool_contract.json": contract,
        "prompt.txt": condition.prompt,
        "event_trace.json": trace,
        "final_response.txt": result.final_response,
        "adapter_result.json": result.to_dict(),
        "verifier_result.json": run_record["verifier_result"],
        "behavioral_annotations.json": annotations,
    }
    write_run_artifacts(artifacts_root / "runs" / resolved_run_id, artifacts)
    _CHANNELS.pop(channel_id, None)
    return run_record | {
        "trace": trace,
        "adapter_result": result.to_dict(),
        "behavioral_annotations": annotations,
    }
