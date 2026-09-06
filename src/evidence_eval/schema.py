from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolObservation:
    action: str
    target: str
    content: str
    reveals: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ToolObservation":
        return cls(
            action=str(value["action"]),
            target=str(value["target"]),
            content=str(value["content"]),
            reveals=tuple(str(item) for item in value.get("reveals", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "target": self.target,
            "content": self.content,
            "reveals": list(self.reveals),
        }


@dataclass(frozen=True)
class CaseVariant:
    family_id: str
    variant_id: str
    surface_signature: str
    hidden_cause: str
    hypotheses: tuple[str, ...]
    files: dict[str, str]
    observations: tuple[ToolObservation, ...]
    verifier: dict[str, Any]
    calibration: dict[str, Any]

    def observation_for(self, action: str, target: str) -> ToolObservation | None:
        for observation in self.observations:
            if observation.action == action and observation.target == target:
                return observation
        return None


@dataclass(frozen=True)
class CaseFamily:
    family_id: str
    dimension: str
    initial_context: dict[str, str]
    allowed_actions: tuple[str, ...]
    action_costs: dict[str, int]
    max_cost: int
    max_events: int
    max_response_chars: int
    perturbations: tuple[dict[str, Any], ...]
    variants: tuple[CaseVariant, ...]
    canonical_sha256: str
    source_path: str

    def variant(self, variant_id: str) -> CaseVariant:
        for value in self.variants:
            if value.variant_id == variant_id:
                return value
        raise KeyError(f"unknown variant {variant_id!r} in {self.family_id!r}")


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def load_case_family(path: Path) -> CaseFamily:
    raw = json.loads(path.read_text(encoding="utf-8"))
    variants = tuple(
        CaseVariant(
            family_id=str(raw["family_id"]),
            variant_id=str(value["variant_id"]),
            surface_signature=str(value["surface_signature"]),
            hidden_cause=str(value["hidden_cause"]),
            hypotheses=tuple(str(item) for item in value["hypotheses"]),
            files={str(key): str(content) for key, content in value["files"].items()},
            observations=tuple(ToolObservation.from_dict(item) for item in value["observations"]),
            verifier=dict(value["verifier"]),
            calibration=dict(value["calibration"]),
        )
        for value in raw["variants"]
    )
    return CaseFamily(
        family_id=str(raw["family_id"]),
        dimension=str(raw["dimension"]),
        initial_context={str(key): str(value) for key, value in raw["initial_context"].items()},
        allowed_actions=tuple(str(item) for item in raw["allowed_actions"]),
        action_costs={str(key): int(value) for key, value in raw["action_costs"].items()},
        max_cost=int(raw["max_cost"]),
        max_events=int(raw.get("max_events", 32)),
        max_response_chars=int(raw.get("max_response_chars", 4000)),
        perturbations=tuple(dict(item) for item in raw.get("perturbations", [])),
        variants=variants,
        canonical_sha256=hashlib.sha256(_canonical_json(raw)).hexdigest(),
        source_path=str(path),
    )
