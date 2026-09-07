"""Validation for the explicitly authorized trusted provider execution path."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Mapping, TYPE_CHECKING

if TYPE_CHECKING:
    from .pilot import PilotCondition, PilotRegistration


APPROVED_PROVIDER_ADAPTER_ID = "jsonl-provider-worker"
APPROVED_PROVIDER_TRANSPORTS = frozenset({"openai-compatible", "openai-responses", "google-gemini"})
NETWORK_AUTHORIZATION_ENV = "EVIDENCE_EVAL_NETWORK_AUTHORIZED"
PROVIDER_CREDENTIAL_ENV = "EVIDENCE_EVAL_PROVIDER_API_KEY"
PROVIDER_BASE_URL_ENV = "EVIDENCE_EVAL_PROVIDER_BASE_URL"
_POSITIVE_INTEGER = re.compile(r"[1-9][0-9]*\Z")
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
APPROVED_PROVIDER_ENTRYPOINT = (_PROJECT_ROOT / "scripts" / "openai_compatible_workspace_worker.py").resolve()


class ExecutionPolicyError(ValueError):
    pass


def _resolved_path(value: str) -> Path:
    return Path(value).resolve()


def validate_trusted_provider_command(condition: "PilotCondition") -> None:
    if condition.adapter_id != APPROVED_PROVIDER_ADAPTER_ID:
        raise ExecutionPolicyError("network-required condition uses an unapproved adapter identifier")
    command = condition.command
    if len(command) < 4:
        raise ExecutionPolicyError("network-required condition must use the approved provider worker command")
    if _resolved_path(command[0]) != _resolved_path(sys.executable):
        raise ExecutionPolicyError("network-required worker must use the current Python interpreter")
    if _resolved_path(command[1]) != APPROVED_PROVIDER_ENTRYPOINT:
        raise ExecutionPolicyError("network-required worker path is not the approved provider entrypoint")
    if command[2] != "--transport" or command[3] not in APPROVED_PROVIDER_TRANSPORTS:
        raise ExecutionPolicyError("network-required worker must select an approved provider transport")
    index = 4
    seen: set[str] = set()
    allowed_numeric = {
        "--max-rounds",
        "--max-message-chars",
        "--max-conversation-messages",
        "--max-conversation-chars",
    }
    while index < len(command):
        flag = command[index]
        if flag not in allowed_numeric or flag in seen:
            raise ExecutionPolicyError("network-required worker command contains an unapproved argument")
        if index + 1 >= len(command) or not _POSITIVE_INTEGER.fullmatch(command[index + 1]):
            raise ExecutionPolicyError("network-required worker bound arguments must be positive integers")
        seen.add(flag)
        index += 2


def validate_execution_authorization(
    registration: "PilotRegistration",
    *,
    allow_network: bool,
    environment: Mapping[str, str] | None = None,
) -> None:
    for condition in registration.conditions:
        if (
            len(condition.command) >= 4
            and condition.command[2] == "--transport"
            and condition.command[3] in {"openai-responses", "google-gemini"}
            and not condition.network_required
        ):
            raise ExecutionPolicyError("selected native provider transport requires network_required: true")
    network_conditions = tuple(condition for condition in registration.conditions if condition.network_required)
    if network_conditions and not allow_network:
        raise ExecutionPolicyError("network-required registration needs the explicit --allow-network batch flag")
    if not network_conditions and allow_network:
        raise ExecutionPolicyError("--allow-network is only valid when a condition declares network use")
    for condition in network_conditions:
        validate_trusted_provider_command(condition)
    if network_conditions:
        values = environment if environment is not None else os.environ
        if not values.get(PROVIDER_CREDENTIAL_ENV):
            raise ExecutionPolicyError(f"missing required provider credential environment variable: {PROVIDER_CREDENTIAL_ENV}")


def live_environment_names(condition: "PilotCondition") -> tuple[str, ...]:
    if not condition.network_required:
        return ()
    return (PROVIDER_CREDENTIAL_ENV,)
