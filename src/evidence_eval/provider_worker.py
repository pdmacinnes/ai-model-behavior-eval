"""Provider transport and JSONL worker primitives for trusted model wrappers."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, TextIO

from .execution_policy import (
    NETWORK_AUTHORIZATION_ENV,
    PROVIDER_BASE_URL_ENV,
    PROVIDER_CREDENTIAL_ENV,
)


SUPPORTED_TOOL_METHODS = frozenset(
    {"request_evidence", "edit_file", "record_checkpoint", "stop_investigation"}
)
BEHAVIOR_STATUSES = frozenset({"completed", "refused", "insufficient_evidence", "stopped"})
PROVIDER_WORKER_VERSION = "evidence-jsonl-provider-worker-v1"
DEFAULT_MAX_REQUEST_BYTES = 256_000
DEFAULT_MAX_CONVERSATION_MESSAGES = 32
DEFAULT_MAX_CONVERSATION_CHARS = 128_000
DEFAULT_MAX_TOOL_DEFINITION_BYTES = 32_000
DEFAULT_MAX_RESPONSE_BYTES = 128_000
DEFAULT_MAX_RESPONSE_TEXT_CHARS = 32_000


class ProviderWorkerError(RuntimeError):
    """A bounded provider-worker failure that is safe to report to stderr."""


class ProviderTransportError(ProviderWorkerError):
    pass


@dataclass(frozen=True)
class ProviderToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ProviderReply:
    text: str = ""
    tool_calls: tuple[ProviderToolCall, ...] = ()
    behavioral_status: str | None = None


class ProviderTransport(Protocol):
    def request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_id: str,
        reasoning_effort: str | None,
    ) -> ProviderReply: ...


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderWorkerError(f"{label} must be a non-empty string")
    return value


def _provider_tools(tool_contract: dict[str, Any]) -> list[dict[str, Any]]:
    raw_tools = tool_contract.get("tools")
    if not isinstance(raw_tools, list):
        raise ProviderWorkerError("tool contract must contain a tools list")
    result: list[dict[str, Any]] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            raise ProviderWorkerError("tool contract contains a non-object tool")
        name = _require_string(raw_tool.get("name"), "tool name")
        if name not in SUPPORTED_TOOL_METHODS:
            raise ProviderWorkerError("tool contract contains an unsupported tool")
        parameters = raw_tool.get("parameters")
        if not isinstance(parameters, dict):
            raise ProviderWorkerError("tool parameters must be an object")
        result.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(raw_tool.get("description", "")),
                    "parameters": parameters,
                },
            }
        )
    if not result:
        raise ProviderWorkerError("tool contract must contain at least one tool")
    return result


def build_openai_compatible_request(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    model_id: str,
    reasoning_effort: str | None,
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
    max_conversation_messages: int = DEFAULT_MAX_CONVERSATION_MESSAGES,
    max_conversation_chars: int = DEFAULT_MAX_CONVERSATION_CHARS,
    max_tool_definition_bytes: int = DEFAULT_MAX_TOOL_DEFINITION_BYTES,
) -> dict[str, Any]:
    model = _require_string(model_id, "model_id")
    if not isinstance(messages, list) or not all(isinstance(item, dict) for item in messages):
        raise ProviderWorkerError("provider messages must be objects")
    if not isinstance(tools, list) or not tools:
        raise ProviderWorkerError("provider tools must be a non-empty list")
    _validate_provider_bounds(
        messages,
        tools,
        max_request_bytes=max_request_bytes,
        max_conversation_messages=max_conversation_messages,
        max_conversation_chars=max_conversation_chars,
        max_tool_definition_bytes=max_tool_definition_bytes,
    )
    request: dict[str, Any] = {
        "model": model,
        "messages": json.loads(json.dumps(messages, ensure_ascii=False)),
        "tools": json.loads(json.dumps(tools, ensure_ascii=False)),
        "tool_choice": "auto",
    }
    if reasoning_effort is not None:
        request["reasoning_effort"] = _require_string(reasoning_effort, "reasoning_effort")
    if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_request_bytes:
        raise ProviderWorkerError("provider request exceeded the byte bound")
    return request


def _validate_provider_bounds(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_request_bytes: int,
    max_conversation_messages: int,
    max_conversation_chars: int,
    max_tool_definition_bytes: int,
) -> None:
    bounds = (
        max_request_bytes,
        max_conversation_messages,
        max_conversation_chars,
        max_tool_definition_bytes,
    )
    if any(value <= 0 for value in bounds):
        raise ValueError("provider request bounds must be positive")
    if len(messages) > max_conversation_messages:
        raise ProviderWorkerError("provider conversation exceeded the message bound")
    serialized_messages = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
    if len(serialized_messages) > max_conversation_chars:
        raise ProviderWorkerError("provider conversation exceeded the character bound")
    serialized_tools = json.dumps(tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(serialized_tools) > max_tool_definition_bytes:
        raise ProviderWorkerError("provider tool definitions exceeded the byte bound")


def parse_openai_compatible_response(value: Any, *, max_text_chars: int = 32_000) -> ProviderReply:
    if not isinstance(value, dict):
        raise ProviderTransportError("provider response must be an object")
    choices = value.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderTransportError("provider response must contain exactly one choice")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProviderTransportError("provider choice is missing a message")
    content = message.get("content", "")
    if content is None:
        content = ""
    if not isinstance(content, str) or len(content) > max_text_chars:
        raise ProviderTransportError("provider response text exceeded the bound")
    raw_tool_calls = message.get("tool_calls", [])
    if raw_tool_calls is None:
        raw_tool_calls = []
    if not isinstance(raw_tool_calls, list) or len(raw_tool_calls) > 1:
        raise ProviderTransportError("provider response must contain at most one tool call")
    tool_calls: list[ProviderToolCall] = []
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            raise ProviderTransportError("provider tool call must be an object")
        call_id = _require_string(raw_call.get("id"), "provider tool call id")
        function = raw_call.get("function")
        if not isinstance(function, dict):
            raise ProviderTransportError("provider tool call is missing a function")
        name = _require_string(function.get("name"), "provider tool name")
        if name not in SUPPORTED_TOOL_METHODS:
            raise ProviderTransportError("provider returned an unsupported tool")
        arguments = function.get("arguments")
        if not isinstance(arguments, str):
            raise ProviderTransportError("provider tool arguments must be JSON text")
        try:
            parsed_arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise ProviderTransportError("provider tool arguments were not valid JSON") from exc
        if not isinstance(parsed_arguments, dict):
            raise ProviderTransportError("provider tool arguments must decode to an object")
        tool_calls.append(ProviderToolCall(call_id, name, parsed_arguments))
    return ProviderReply(text=content, tool_calls=tuple(tool_calls))


class OpenAICompatibleTransport:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_text_chars: int = DEFAULT_MAX_RESPONSE_TEXT_CHARS,
        max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        max_conversation_messages: int = DEFAULT_MAX_CONVERSATION_MESSAGES,
        max_conversation_chars: int = DEFAULT_MAX_CONVERSATION_CHARS,
        max_tool_definition_bytes: int = DEFAULT_MAX_TOOL_DEFINITION_BYTES,
        allow_network: bool = False,
    ) -> None:
        if not base_url or "\n" in base_url or "\r" in base_url:
            raise ValueError("provider base URL must be a non-empty single-line value")
        if any(
            value <= 0
            for value in (
                timeout_seconds,
                max_response_bytes,
                max_text_chars,
                max_request_bytes,
                max_conversation_messages,
                max_conversation_chars,
                max_tool_definition_bytes,
            )
        ):
            raise ValueError("provider transport bounds must be positive")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_text_chars = max_text_chars
        self.max_request_bytes = max_request_bytes
        self.max_conversation_messages = max_conversation_messages
        self.max_conversation_chars = max_conversation_chars
        self.max_tool_definition_bytes = max_tool_definition_bytes
        self.allow_network = allow_network

    def request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_id: str,
        reasoning_effort: str | None,
    ) -> ProviderReply:
        if not self.allow_network:
            raise ProviderTransportError("real provider network execution is disabled")
        if not self.api_key:
            raise ProviderTransportError("provider credential is missing")
        payload = build_openai_compatible_request(
            messages,
            tools,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            max_request_bytes=self.max_request_bytes,
            max_conversation_messages=self.max_conversation_messages,
            max_conversation_chars=self.max_conversation_chars,
            max_tool_definition_bytes=self.max_tool_definition_bytes,
        )
        endpoint = self.base_url if self.base_url.endswith("/chat/completions") else f"{self.base_url}/chat/completions"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read(self.max_response_bytes + 1)
        except urllib.error.HTTPError as exc:
            raise ProviderTransportError(f"provider HTTP error {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProviderTransportError("provider request failed") from None
        if len(body) > self.max_response_bytes:
            raise ProviderTransportError("provider response exceeded the byte bound")
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderTransportError("provider response was not valid JSON") from exc
        return parse_openai_compatible_response(parsed, max_text_chars=self.max_text_chars)


class ScriptedMockTransport:
    """Credential-free scripted policy used only for worker integration tests."""

    def __init__(self) -> None:
        self.round = 0
        self.first_observation = ""

    def request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        *,
        model_id: str,
        reasoning_effort: str | None,
    ) -> ProviderReply:
        del tools, model_id, reasoning_effort
        if self.round == 0:
            self.round += 1
            return ProviderReply(
                tool_calls=(
                    ProviderToolCall(
                        "mock-inspect",
                        "request_evidence",
                        {"action": "inspect", "target": "app/dashboard/page.tsx"},
                    ),
                )
            )
        if self.round == 1:
            self.first_observation = _last_tool_content(messages)
            self.round += 1
            return ProviderReply(
                tool_calls=(
                    ProviderToolCall(
                        "mock-checkpoint",
                        "record_checkpoint",
                        {
                            "leading_hypothesis": "the visible request boundary is involved",
                            "alternative_hypothesis": "the cache identity is involved",
                            "confidence": 0.6,
                            "changed_by": "page inspection",
                            "next_action": "apply the narrowest candidate edit",
                        },
                    ),
                )
            )
        if self.round == 2:
            self.round += 1
            if "await getMetrics(params.range)" in self.first_observation:
                arguments = {
                    "path": "lib/cache.ts",
                    "before": "['metrics']);",
                    "after": "['metrics', range]);",
                }
            else:
                arguments = {
                    "path": "app/dashboard/page.tsx",
                    "before": "await getMetrics()",
                    "after": "await getMetrics(params.range)",
                }
            return ProviderReply(tool_calls=(ProviderToolCall("mock-edit", "edit_file", arguments),))
        if self.round == 3:
            self.round += 1
            return ProviderReply(
                tool_calls=(
                    ProviderToolCall(
                        "mock-stop",
                        "stop_investigation",
                        {"reason": "mock policy completed the bounded investigation"},
                    ),
                )
            )
        raise ProviderTransportError("mock transport exhausted")


def _last_tool_content(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "tool":
            return str(message.get("content", ""))
    return ""


def _read_line(stream: TextIO, max_chars: int) -> str:
    line = stream.readline(max_chars + 1)
    if not line:
        raise ProviderWorkerError("worker input ended before the required JSONL message")
    if len(line) > max_chars:
        raise ProviderWorkerError("worker JSONL message exceeded the bound")
    return line


def _read_json_line(stream: TextIO, max_chars: int) -> dict[str, Any]:
    line = _read_line(stream, max_chars)
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProviderWorkerError("worker received invalid JSONL") from exc
    if not isinstance(value, dict):
        raise ProviderWorkerError("worker JSONL message must be an object")
    return value


def _write_json_line(stream: TextIO, value: dict[str, Any], max_chars: int) -> None:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) > max_chars:
        raise ProviderWorkerError("worker JSONL message exceeded the bound")
    stream.write(encoded + "\n")
    stream.flush()


def _task_condition(task: dict[str, Any]) -> dict[str, Any]:
    value = task.get("model_condition")
    if not isinstance(value, dict):
        raise ProviderWorkerError("task is missing model condition metadata")
    required = {"provider", "model_id", "adapter_id", "reasoning_effort"}
    if set(value) != required:
        raise ProviderWorkerError("task model condition contains unexpected fields")
    _require_string(value.get("provider"), "provider")
    _require_string(value.get("model_id"), "model_id")
    _require_string(value.get("adapter_id"), "adapter_id")
    if value.get("reasoning_effort") is not None:
        _require_string(value.get("reasoning_effort"), "reasoning_effort")
    return value


def run_provider_worker(
    input_stream: TextIO,
    output_stream: TextIO,
    transport: ProviderTransport,
    *,
    max_rounds: int = 16,
    max_message_chars: int = 32_000,
    max_conversation_messages: int = DEFAULT_MAX_CONVERSATION_MESSAGES,
    max_conversation_chars: int = DEFAULT_MAX_CONVERSATION_CHARS,
    max_tool_definition_bytes: int = DEFAULT_MAX_TOOL_DEFINITION_BYTES,
) -> None:
    if any(value <= 0 for value in (max_rounds, max_message_chars, max_conversation_messages, max_conversation_chars, max_tool_definition_bytes)):
        raise ValueError("worker bounds must be positive")
    task_message = _read_json_line(input_stream, max_message_chars)
    if task_message.get("type") != "task" or not isinstance(task_message.get("task"), dict):
        raise ProviderWorkerError("worker expected one task message")
    task = task_message["task"]
    condition = _task_condition(task)
    prompt = _require_string(task.get("prompt"), "prompt")
    initial_observation = task.get("initial_observation")
    if initial_observation is not None:
        prompt = f"{prompt}\n\nInitial observation:\n{_require_string(initial_observation, 'initial_observation')}"
    tool_contract = task.get("tool_contract")
    if not isinstance(tool_contract, dict):
        raise ProviderWorkerError("task is missing a tool contract")
    tools = _provider_tools(tool_contract)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    _validate_provider_bounds(
        messages,
        tools,
        max_request_bytes=DEFAULT_MAX_REQUEST_BYTES,
        max_conversation_messages=max_conversation_messages,
        max_conversation_chars=max_conversation_chars,
        max_tool_definition_bytes=max_tool_definition_bytes,
    )
    rounds = 0

    while rounds < max_rounds:
        rounds += 1
        reply = transport.request(
            messages,
            tools,
            model_id=condition["model_id"],
            reasoning_effort=condition["reasoning_effort"],
        )
        if len(reply.tool_calls) > 1:
            raise ProviderWorkerError("provider returned multiple tool calls")
        if not reply.tool_calls:
            status = reply.behavioral_status or "completed"
            if status not in BEHAVIOR_STATUSES:
                raise ProviderWorkerError("provider returned an unsupported behavioral status")
            _write_json_line(
                output_stream,
                {
                    "type": "final",
                    "status": status,
                    "final_response": reply.text,
                    "metadata": {
                        "provider_worker_version": PROVIDER_WORKER_VERSION,
                        "provider": condition["provider"],
                        "model_id": condition["model_id"],
                        "request_count": rounds,
                    },
                },
                max_message_chars,
            )
            return

        call = reply.tool_calls[0]
        if call.name not in SUPPORTED_TOOL_METHODS:
            raise ProviderWorkerError("provider returned an unsupported tool")
        _write_json_line(
            output_stream,
            {"type": "call", "id": call.call_id, "method": call.name, "arguments": call.arguments},
            max_message_chars,
        )
        result_message = _read_json_line(input_stream, max_message_chars)
        if result_message.get("type") != "result" or result_message.get("id") != call.call_id:
            raise ProviderWorkerError("worker received an unexpected tool result")
        result_ok = result_message.get("ok") is True
        result_value = result_message.get("result") if result_ok else {"error": result_message.get("error", "tool call failed")}
        messages.append(
            {
                "role": "assistant",
                "content": reply.text or None,
                "tool_calls": [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False, separators=(",", ":")),
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": call.call_id,
                "content": json.dumps(result_value, ensure_ascii=False, separators=(",", ":")),
            }
        )
        _validate_provider_bounds(
            messages,
            tools,
            max_request_bytes=DEFAULT_MAX_REQUEST_BYTES,
            max_conversation_messages=max_conversation_messages,
            max_conversation_chars=max_conversation_chars,
            max_tool_definition_bytes=max_tool_definition_bytes,
        )
        if call.name == "stop_investigation" and result_ok:
            _write_json_line(
                output_stream,
                {
                    "type": "final",
                    "status": "stopped",
                    "final_response": reply.text,
                    "metadata": {
                        "provider_worker_version": PROVIDER_WORKER_VERSION,
                        "provider": condition["provider"],
                        "model_id": condition["model_id"],
                        "request_count": rounds,
                    },
                },
                max_message_chars,
            )
            return

    raise ProviderWorkerError("provider worker exceeded its round bound")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run a bounded JSONL provider worker.")
    parser.add_argument("--transport", choices=("mock", "openai-compatible"), default="openai-compatible")
    parser.add_argument("--base-url", default=os.environ.get(PROVIDER_BASE_URL_ENV, ""))
    parser.add_argument("--max-rounds", type=int, default=16)
    parser.add_argument("--max-message-chars", type=int, default=32_000)
    args = parser.parse_args(argv)
    try:
        if args.transport == "mock":
            transport: ProviderTransport = ScriptedMockTransport()
        else:
            transport = OpenAICompatibleTransport(
                base_url=args.base_url,
                api_key=os.environ.get(PROVIDER_CREDENTIAL_ENV, ""),
                allow_network=os.environ.get(NETWORK_AUTHORIZATION_ENV) == "1",
            )
        run_provider_worker(
            sys.stdin,
            sys.stdout,
            transport,
            max_rounds=args.max_rounds,
            max_message_chars=args.max_message_chars,
        )
    except (ProviderWorkerError, ValueError) as exc:
        print(f"provider worker failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
