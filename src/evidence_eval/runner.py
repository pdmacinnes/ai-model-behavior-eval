from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from cursor_eval.artifacts import write_run_artifacts

from .analysis import analyze_trace
from .protocol import EvidenceSession, ToolResponse
from .schema import CaseFamily, CaseVariant


PROTOCOL_VERSION = "evidence-protocol-v1"


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
    def __call__(self, task: dict[str, str], tools: "EvidenceTools") -> AgentResult: ...


class EvidenceTools:
    """The only interface an adapter needs to investigate one case variant."""

    def __init__(self, session: EvidenceSession) -> None:
        self._session = session

    def request(self, action: str, target: str) -> ToolResponse:
        return self._session.request(action, target)

    def checkpoint(
        self,
        *,
        leading_hypothesis: str,
        alternative_hypothesis: str,
        confidence: float,
        changed_by: str,
        next_action: str,
    ) -> None:
        self._session.checkpoint(
            leading_hypothesis=leading_hypothesis,
            alternative_hypothesis=alternative_hypothesis,
            confidence=confidence,
            changed_by=changed_by,
            next_action=next_action,
        )

    def stop(self, reason: str) -> None:
        self._session.stop(reason)


def tool_contract(family: CaseFamily) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request": {
            "action": "string from allowed_actions",
            "target": "string case target",
            "returns": ["accepted", "content", "cost", "remaining_cost", "reveals", "error"],
        },
        "checkpoint": [
            "leading_hypothesis",
            "alternative_hypothesis",
            "confidence",
            "changed_by",
            "next_action",
        ],
        "stop": ["reason"],
        "allowed_actions": list(family.allowed_actions),
        "action_costs": dict(sorted(family.action_costs.items())),
        "max_cost": family.max_cost,
    }


def run_unattended_trial(
    family: CaseFamily,
    variant: CaseVariant,
    condition: ModelCondition,
    adapter: EvidenceAdapter,
    *,
    artifacts_root: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    if variant.family_id != family.family_id:
        raise ValueError("variant does not belong to the supplied case family")
    if condition.prompt != family.initial_context.get("prompt"):
        raise ValueError("condition prompt must match the case's frozen prompt")

    resolved_run_id = run_id or str(uuid.uuid4())
    session = EvidenceSession(family, variant)
    tools = EvidenceTools(session)
    started = time.monotonic()
    try:
        task = dict(family.initial_context)
        task["family_id"] = family.family_id
        task["variant_id"] = variant.variant_id
        result = adapter(task, tools)
        if not isinstance(result, AgentResult):
            raise TypeError("evidence adapters must return AgentResult")
    except Exception as exc:  # Adapter failures are data, not interactive prompts.
        result = AgentResult(status="adapter_error", error=f"{type(exc).__name__}: {exc}")
        session.stop("adapter error")
    if session.status == "active":
        session.stop("adapter returned without stopping")

    trace = session.to_record()
    contract = tool_contract(family)
    run_record = {
        "run_id": resolved_run_id,
        "family_id": family.family_id,
        "variant_id": variant.variant_id,
        "case_sha256": family.canonical_sha256,
        "condition": condition.to_dict(),
        "prompt_hash": hashlib.sha256(condition.prompt.encode("utf-8")).hexdigest(),
        "tool_contract_hash": _hash_json(contract),
        "protocol_version": PROTOCOL_VERSION,
        "runtime_seconds": time.monotonic() - started,
        "execution_status": result.status,
        "verifier_result": {
            "status": "not_executed",
            "reason": "protocol-only trial has no materialized workspace",
            "declaration": dict(variant.verifier),
        },
    }
    artifacts = {
        "run.json": run_record,
        "condition.json": condition.to_dict(),
        "tool_contract.json": contract,
        "prompt.txt": condition.prompt,
        "event_trace.json": trace,
        "final_response.txt": result.final_response,
        "adapter_result.json": result.to_dict(),
        "verifier_result.json": run_record["verifier_result"],
        "behavioral_annotations.json": analyze_trace(trace),
    }
    write_run_artifacts(artifacts_root / "runs" / resolved_run_id, artifacts)
    return run_record | {
        "trace": trace,
        "adapter_result": result.to_dict(),
        "behavioral_annotations": analyze_trace(trace),
    }
