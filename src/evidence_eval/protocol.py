from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import CaseFamily, CaseVariant


@dataclass(frozen=True)
class ToolResponse:
    accepted: bool
    action: str
    target: str
    content: str
    cost: int
    remaining_cost: int
    reveals: tuple[str, ...] = ()
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "action": self.action,
            "target": self.target,
            "content": self.content,
            "cost": self.cost,
            "remaining_cost": self.remaining_cost,
            "reveals": list(self.reveals),
            "error": self.error,
        }


class EvidenceSession:
    """Deterministic, model-agnostic evidence interface for one case variant."""

    def __init__(self, family: CaseFamily, variant: CaseVariant) -> None:
        if variant.family_id != family.family_id:
            raise ValueError("variant does not belong to the supplied case family")
        self.family = family
        self.variant = variant
        self.remaining_cost = family.max_cost
        self.status = "active"
        self.events: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []

    def request(self, action: str, target: str) -> ToolResponse:
        cost = self.family.action_costs.get(action)
        if self.status != "active":
            return self._reject(action, target, 0, "session is no longer active")
        if action not in self.family.allowed_actions or cost is None:
            return self._reject(action, target, 0, "unsupported action")
        if cost > self.remaining_cost:
            return self._reject(action, target, cost, "evidence budget exceeded")
        observation = self.variant.observation_for(action, target)
        if observation is None:
            return self._reject(action, target, cost, "unsupported target for this case")
        self.remaining_cost -= cost
        response = ToolResponse(
            accepted=True,
            action=action,
            target=target,
            content=observation.content,
            cost=cost,
            remaining_cost=self.remaining_cost,
            reveals=observation.reveals,
        )
        self.events.append({"kind": "action", **response.to_dict()})
        return response

    def checkpoint(
        self,
        *,
        leading_hypothesis: str,
        alternative_hypothesis: str,
        confidence: float,
        changed_by: str,
        next_action: str,
    ) -> None:
        if self.status != "active":
            raise RuntimeError("cannot checkpoint an inactive session")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
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
        if self.status != "active":
            return
        self.status = "stopped"
        self.events.append({"kind": "stop", "reason": reason, "remaining_cost": self.remaining_cost})

    def record_edit(self, target: str) -> ToolResponse:
        return self.request("edit", target)

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
        self.events.append({"kind": "rejected_action", **response.to_dict()})
        return response
