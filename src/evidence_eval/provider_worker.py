"""Provider transport and JSONL worker primitives for trusted model wrappers."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
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
MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE = 4
BEHAVIOR_STATUSES = frozenset({"completed", "refused", "insufficient_evidence", "stopped"})
PROVIDER_WORKER_VERSION = "evidence-jsonl-provider-worker-v1"
DEFAULT_MAX_REQUEST_BYTES = 256_000
DEFAULT_MAX_CONVERSATION_MESSAGES = 32
DEFAULT_MAX_CONVERSATION_CHARS = 128_000
DEFAULT_MAX_TOOL_DEFINITION_BYTES = 32_000
DEFAULT_MAX_RESPONSE_BYTES = 128_000
DEFAULT_MAX_RESPONSE_TEXT_CHARS = 32_000
_GEMINI_MODEL_SEGMENT = re.compile(r"[^/\?#\s]+\Z")
_GEMINI_REASONING_LEVELS = {
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
}


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


def _validate_tool_call_batch(
    tool_calls: list[ProviderToolCall] | tuple[ProviderToolCall, ...],
    *,
    error_type: type[ProviderWorkerError],
) -> tuple[ProviderToolCall, ...]:
    if not isinstance(tool_calls, (list, tuple)):
        raise error_type("provider tool calls must be a list")
    if len(tool_calls) > MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE:
        raise error_type("provider response contained too many tool calls")
    seen_ids: set[str] = set()
    for call in tool_calls:
        if not isinstance(call, ProviderToolCall):
            raise error_type("provider tool call must be an object")
        if not isinstance(call.call_id, str) or not call.call_id:
            raise error_type("provider tool call id must be a non-empty string")
        if not isinstance(call.name, str) or not call.name:
            raise error_type("provider tool name must be a non-empty string")
        if call.name not in SUPPORTED_TOOL_METHODS:
            raise error_type("provider returned an unsupported tool")
        if not isinstance(call.arguments, dict):
            raise error_type("provider tool arguments must be an object")
        if call.call_id in seen_ids:
            raise error_type("provider response contained duplicate tool call id")
        seen_ids.add(call.call_id)
    return tuple(tool_calls)


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


def _responses_input_items(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    input_items: list[dict[str, Any]] = []
    pending_call_ids: set[str] = set()
    for message in messages:
        role = message.get("role")
        if role == "user":
            content = message.get("content", "")
            if not isinstance(content, str):
                raise ProviderWorkerError("Responses user message content must be text")
            input_items.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": content}],
                }
            )
            continue
        if role == "assistant":
            content = message.get("content")
            if content:
                if not isinstance(content, str):
                    raise ProviderWorkerError("Responses assistant message content must be text")
                input_items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}],
                    }
                )
            raw_calls = message.get("tool_calls", [])
            if raw_calls is None:
                raw_calls = []
            if not isinstance(raw_calls, list):
                raise ProviderWorkerError("Responses conversation tool calls must be a list")
            if len(raw_calls) > MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE:
                raise ProviderWorkerError("Responses conversation contained too many function calls")
            seen_call_ids: set[str] = set()
            for raw_call in raw_calls:
                if not isinstance(raw_call, dict):
                    raise ProviderWorkerError("Responses function call must be an object")
                call_id = _require_string(raw_call.get("id"), "Responses function call id")
                if call_id in seen_call_ids:
                    raise ProviderWorkerError("Responses conversation contained duplicate function call id")
                seen_call_ids.add(call_id)
                function = raw_call.get("function")
                if not isinstance(function, dict):
                    raise ProviderWorkerError("Responses function call is missing a function")
                name = _require_string(function.get("name"), "Responses function name")
                if name not in SUPPORTED_TOOL_METHODS:
                    raise ProviderWorkerError("Responses conversation contained an unsupported tool")
                arguments_text = _require_string(function.get("arguments"), "Responses function arguments")
                try:
                    arguments = json.loads(arguments_text)
                except json.JSONDecodeError as exc:
                    raise ProviderWorkerError("Responses function arguments were not valid JSON") from exc
                if not isinstance(arguments, dict):
                    raise ProviderWorkerError("Responses function arguments must decode to an object")
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
                    }
                )
                pending_call_ids.add(call_id)
            continue
        if role == "tool":
            call_id = _require_string(message.get("tool_call_id"), "Responses function output call id")
            if call_id not in pending_call_ids:
                raise ProviderWorkerError("Responses function output call id did not match a prior function call")
            content = message.get("content")
            if not isinstance(content, str):
                raise ProviderWorkerError("Responses function output must be text")
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content,
                }
            )
            pending_call_ids.remove(call_id)
            continue
        raise ProviderWorkerError("Responses conversation contained an unsupported message role")
    if pending_call_ids:
        raise ProviderWorkerError("Responses conversation contains a function call without its result")
    return input_items


def _responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw_tool in tools:
        function = raw_tool.get("function")
        if not isinstance(function, dict):
            raise ProviderWorkerError("Responses tool is missing a function")
        name = _require_string(function.get("name"), "Responses tool name")
        description = function.get("description", "")
        if not isinstance(description, str):
            raise ProviderWorkerError("Responses tool description must be text")
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            raise ProviderWorkerError("Responses tool parameters must be an object")
        result.append(
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": json.loads(json.dumps(parameters, ensure_ascii=False)),
            }
        )
    return result


def build_openai_responses_request(
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
    input_items = _responses_input_items(messages)
    response_tools = _responses_tools(tools)
    serialized_input = json.dumps(input_items, ensure_ascii=False, separators=(",", ":"))
    serialized_tools = json.dumps(response_tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(input_items) > max_conversation_messages:
        raise ProviderWorkerError("provider conversation exceeded the message bound")
    if len(serialized_input) > max_conversation_chars:
        raise ProviderWorkerError("provider conversation exceeded the character bound")
    if len(serialized_tools) > max_tool_definition_bytes:
        raise ProviderWorkerError("provider tool definitions exceeded the byte bound")
    request: dict[str, Any] = {
        "model": model,
        "input": input_items,
        "tools": response_tools,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "store": False,
    }
    if reasoning_effort is not None:
        request["reasoning"] = {"effort": _require_string(reasoning_effort, "reasoning_effort")}
    if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_request_bytes:
        raise ProviderWorkerError("provider request exceeded the byte bound")
    return request


def parse_openai_responses_response(value: Any, *, max_text_chars: int = DEFAULT_MAX_RESPONSE_TEXT_CHARS) -> ProviderReply:
    if not isinstance(value, dict):
        raise ProviderTransportError("provider response must be an object")
    if value.get("status") != "completed":
        raise ProviderTransportError("provider response was not completed")
    output = value.get("output")
    if not isinstance(output, list):
        raise ProviderTransportError("provider response must contain an output list")
    raw_text = value.get("output_text")
    text_parts: list[str] = []
    if raw_text is not None:
        if not isinstance(raw_text, str):
            raise ProviderTransportError("provider response output_text must be text")
        text_parts.append(raw_text)
    tool_calls: list[ProviderToolCall] = []
    for item in output:
        if not isinstance(item, dict):
            raise ProviderTransportError("provider response output item must be an object")
        item_type = item.get("type")
        if item_type == "message" and raw_text is None:
            content = item.get("content")
            if not isinstance(content, list):
                raise ProviderTransportError("provider response message content must be a list")
            for part in content:
                if not isinstance(part, dict):
                    raise ProviderTransportError("provider response message content item must be an object")
                if part.get("type") == "output_text":
                    text = part.get("text")
                    if not isinstance(text, str):
                        raise ProviderTransportError("provider response output text must be text")
                    text_parts.append(text)
        elif item_type == "function_call":
            if len(tool_calls) >= MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE:
                raise ProviderTransportError("provider response contained too many tool calls")
            call_id = _require_string(item.get("call_id"), "provider function call id")
            name = _require_string(item.get("name"), "provider function name")
            arguments_text = _require_string(item.get("arguments"), "provider function arguments")
            try:
                arguments = json.loads(arguments_text)
            except json.JSONDecodeError as exc:
                raise ProviderTransportError("provider function arguments were not valid JSON") from exc
            if not isinstance(arguments, dict):
                raise ProviderTransportError("provider function arguments must decode to an object")
            if name not in SUPPORTED_TOOL_METHODS:
                raise ProviderTransportError("provider returned an unsupported tool")
            tool_calls.append(ProviderToolCall(call_id, name, arguments))
    text = "".join(text_parts)
    if len(text) > max_text_chars:
        raise ProviderTransportError("provider response text exceeded the bound")
    return ProviderReply(
        text=text,
        tool_calls=_validate_tool_call_batch(tool_calls, error_type=ProviderTransportError),
    )


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
    if not isinstance(raw_tool_calls, list):
        raise ProviderTransportError("provider tool calls must be a list")
    if len(raw_tool_calls) > MAX_PROVIDER_TOOL_CALLS_PER_RESPONSE:
        raise ProviderTransportError("provider response contained too many tool calls")
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
    return ProviderReply(
        text=content,
        tool_calls=_validate_tool_call_batch(tool_calls, error_type=ProviderTransportError),
    )


def _gemini_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    declarations: list[dict[str, Any]] = []
    for raw_tool in tools:
        if not isinstance(raw_tool, dict):
            raise ProviderWorkerError("Gemini tool must be an object")
        function = raw_tool.get("function")
        if not isinstance(function, dict):
            raise ProviderWorkerError("Gemini tool is missing a function")
        name = _require_string(function.get("name"), "Gemini tool name")
        if name not in SUPPORTED_TOOL_METHODS:
            raise ProviderWorkerError("Gemini tool is unsupported")
        description = function.get("description", "")
        if not isinstance(description, str):
            raise ProviderWorkerError("Gemini tool description must be text")
        parameters = function.get("parameters")
        if not isinstance(parameters, dict):
            raise ProviderWorkerError("Gemini tool parameters must be an object")
        declarations.append(
            {
                "name": name,
                "description": description,
                "parametersJsonSchema": json.loads(json.dumps(parameters, ensure_ascii=False)),
            }
        )
    if not declarations:
        raise ProviderWorkerError("Gemini tools must contain at least one function declaration")
    return [{"functionDeclarations": declarations}]


def _validate_gemini_bounds(
    contents: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    *,
    max_request_bytes: int,
    max_conversation_messages: int,
    max_conversation_chars: int,
    max_tool_definition_bytes: int,
) -> list[dict[str, Any]]:
    bounds = (
        max_request_bytes,
        max_conversation_messages,
        max_conversation_chars,
        max_tool_definition_bytes,
    )
    if any(value <= 0 for value in bounds):
        raise ValueError("provider request bounds must be positive")
    if not isinstance(contents, list) or not contents or not all(isinstance(item, dict) for item in contents):
        raise ProviderWorkerError("Gemini contents must be a non-empty list of objects")
    if len(contents) > max_conversation_messages:
        raise ProviderWorkerError("provider conversation exceeded the message bound")
    serialized_contents = json.dumps(contents, ensure_ascii=False, separators=(",", ":"))
    if len(serialized_contents) > max_conversation_chars:
        raise ProviderWorkerError("provider conversation exceeded the character bound")
    gemini_tools = _gemini_tools(tools)
    serialized_tools = json.dumps(gemini_tools, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(serialized_tools) > max_tool_definition_bytes:
        raise ProviderWorkerError("provider tool definitions exceeded the byte bound")
    return gemini_tools


def build_google_gemini_request(
    contents: list[dict[str, Any]],
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
    if not _GEMINI_MODEL_SEGMENT.fullmatch(model):
        raise ProviderWorkerError("Gemini model_id must be one URL path segment")
    gemini_tools = _validate_gemini_bounds(
        contents,
        tools,
        max_request_bytes=max_request_bytes,
        max_conversation_messages=max_conversation_messages,
        max_conversation_chars=max_conversation_chars,
        max_tool_definition_bytes=max_tool_definition_bytes,
    )
    request: dict[str, Any] = {
        "contents": json.loads(json.dumps(contents, ensure_ascii=False)),
        "tools": gemini_tools,
    }
    if reasoning_effort is not None:
        effort = _require_string(reasoning_effort, "reasoning_effort")
        thinking_level = _GEMINI_REASONING_LEVELS.get(effort)
        if thinking_level is None:
            raise ProviderWorkerError("Gemini reasoning_effort is unsupported")
        request["generationConfig"] = {"thinkingConfig": {"thinkingLevel": thinking_level}}
    if len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_request_bytes:
        raise ProviderWorkerError("provider request exceeded the byte bound")
    return request


def _gemini_response_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProviderTransportError(f"Gemini response is missing {label}")
    return value


def _parse_google_gemini_response_content(
    value: Any,
    *,
    max_text_chars: int,
) -> tuple[ProviderReply, dict[str, Any]]:
    if not isinstance(value, dict):
        raise ProviderTransportError("Gemini response must be an object")
    candidates = value.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise ProviderTransportError("Gemini response must contain exactly one candidate")
    native_content = candidates[0].get("content")
    if not isinstance(native_content, dict):
        raise ProviderTransportError("Gemini response candidate is missing content")
    parts = native_content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ProviderTransportError("Gemini response content is missing parts")

    text_parts: list[str] = []
    tool_calls: list[ProviderToolCall] = []
    for part in parts:
        if not isinstance(part, dict):
            raise ProviderTransportError("Gemini response part must be an object")
        if "text" in part:
            text = part["text"]
            if not isinstance(text, str):
                raise ProviderTransportError("Gemini response text must be text")
            if not part.get("thought"):
                text_parts.append(text)
        if "functionCall" not in part:
            continue
        if len(tool_calls) >= 1:
            raise ProviderTransportError("Gemini response must contain at most one function call")
        function_call = part["functionCall"]
        if not isinstance(function_call, dict):
            raise ProviderTransportError("Gemini function call must be an object")
        call_id = _gemini_response_string(function_call.get("id"), "function call id")
        name = _gemini_response_string(function_call.get("name"), "function name")
        if name not in SUPPORTED_TOOL_METHODS:
            raise ProviderTransportError("Gemini returned an unsupported tool")
        arguments = function_call.get("args")
        if not isinstance(arguments, dict):
            raise ProviderTransportError("Gemini function arguments must be an object")
        if not isinstance(part.get("thoughtSignature"), str) or not part["thoughtSignature"]:
            raise ProviderTransportError("Gemini function call is missing thoughtSignature")
        tool_calls.append(ProviderToolCall(call_id, name, json.loads(json.dumps(arguments, ensure_ascii=False))))

    text = "".join(text_parts)
    if len(text) > max_text_chars:
        raise ProviderTransportError("Gemini response text exceeded the bound")
    return ProviderReply(text=text, tool_calls=tuple(tool_calls)), json.loads(
        json.dumps(native_content, ensure_ascii=False)
    )


def parse_google_gemini_response(value: Any, *, max_text_chars: int = DEFAULT_MAX_RESPONSE_TEXT_CHARS) -> ProviderReply:
    reply, _ = _parse_google_gemini_response_content(value, max_text_chars=max_text_chars)
    return reply


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


class OpenAIResponsesTransport(OpenAICompatibleTransport):
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
        payload = build_openai_responses_request(
            messages,
            tools,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            max_request_bytes=self.max_request_bytes,
            max_conversation_messages=self.max_conversation_messages,
            max_conversation_chars=self.max_conversation_chars,
            max_tool_definition_bytes=self.max_tool_definition_bytes,
        )
        endpoint = self.base_url if self.base_url.endswith("/responses") else f"{self.base_url}/responses"
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
        return parse_openai_responses_response(parsed, max_text_chars=self.max_text_chars)


class GoogleGeminiTransport:
    """Native Gemini transport with provider-owned continuation history."""

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
        if "\n" in base_url or "\r" in base_url:
            raise ValueError("provider base URL must be a single-line value")
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
        self._native_contents: list[dict[str, Any]] | None = None
        self._pending_call: tuple[str, str] | None = None

    def _seed_history(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict):
            raise ProviderWorkerError("Gemini initial conversation must contain one user message")
        if messages[0].get("role") != "user":
            raise ProviderWorkerError("Gemini initial conversation must start with a user message")
        prompt = messages[0].get("content")
        if not isinstance(prompt, str):
            raise ProviderWorkerError("Gemini user message content must be text")
        return [{"role": "user", "parts": [{"text": prompt}]}]

    def _build_function_result(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        if self._native_contents is None or self._pending_call is None:
            raise ProviderWorkerError("Gemini conversation has no pending function call")
        if not messages or not isinstance(messages[-1], dict) or messages[-1].get("role") != "tool":
            raise ProviderWorkerError("Gemini conversation is missing the latest function result")
        result_message = messages[-1]
        call_id, name = self._pending_call
        if result_message.get("tool_call_id") != call_id:
            raise ProviderWorkerError("Gemini function result call id did not match the pending function call")
        result_text = result_message.get("content")
        if not isinstance(result_text, str):
            raise ProviderWorkerError("Gemini function result must be text")
        try:
            result_value = json.loads(result_text)
        except json.JSONDecodeError as exc:
            raise ProviderWorkerError("Gemini function result was not valid JSON") from exc
        if not isinstance(result_value, dict):
            raise ProviderWorkerError("Gemini function result must be an object")

        matching_assistant = None
        for message in reversed(messages[:-1]):
            if message.get("role") != "assistant":
                continue
            raw_calls = message.get("tool_calls", [])
            if not isinstance(raw_calls, list) or len(raw_calls) > 1:
                raise ProviderWorkerError("Gemini conversation must contain at most one function call per round")
            if raw_calls:
                matching_assistant = raw_calls[0]
                break
        if not isinstance(matching_assistant, dict) or matching_assistant.get("id") != call_id:
            raise ProviderWorkerError("Gemini function result did not match the pending function call")
        function = matching_assistant.get("function")
        if not isinstance(function, dict) or function.get("name") != name:
            raise ProviderWorkerError("Gemini function result name did not match the pending function call")

        return {
            "role": "user",
            "parts": [
                {
                    "functionResponse": {
                        "name": name,
                        "response": {"result": result_value},
                        "id": call_id,
                    }
                }
            ],
        }

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
        if not self.base_url:
            raise ProviderTransportError("provider base URL is missing")
        if not self.api_key:
            raise ProviderTransportError("provider credential is missing")
        if self._native_contents is None:
            staged_contents = self._seed_history(messages)
        elif self._pending_call is not None:
            staged_contents = [*self._native_contents, self._build_function_result(messages)]
        else:
            raise ProviderWorkerError("Gemini conversation received a request after final completion")

        payload = build_google_gemini_request(
            staged_contents,
            tools,
            model_id=model_id,
            reasoning_effort=reasoning_effort,
            max_request_bytes=self.max_request_bytes,
            max_conversation_messages=self.max_conversation_messages,
            max_conversation_chars=self.max_conversation_chars,
            max_tool_definition_bytes=self.max_tool_definition_bytes,
        )
        model = _require_string(model_id, "model_id")
        if not _GEMINI_MODEL_SEGMENT.fullmatch(model):
            raise ProviderWorkerError("Gemini model_id must be one URL path segment")
        endpoint = f"{self.base_url}/models/{urllib.parse.quote(model, safe='')}:generateContent"
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
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
        reply, native_content = _parse_google_gemini_response_content(parsed, max_text_chars=self.max_text_chars)
        self._native_contents = [*staged_contents, native_content]
        self._pending_call = None
        if reply.tool_calls:
            call = reply.tool_calls[0]
            self._pending_call = (call.call_id, call.name)
        return reply


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
        tool_calls = _validate_tool_call_batch(reply.tool_calls, error_type=ProviderWorkerError)
        if not tool_calls:
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

        if len(tool_calls) > 1 and any(call.name == "stop_investigation" for call in tool_calls):
            raise ProviderWorkerError("a multi-call provider response cannot contain stop_investigation")
        results: list[tuple[ProviderToolCall, bool, Any]] = []
        for call in tool_calls:
            _write_json_line(
                output_stream,
                {"type": "call", "id": call.call_id, "method": call.name, "arguments": call.arguments},
                max_message_chars,
            )
            result_message = _read_json_line(input_stream, max_message_chars)
            if result_message.get("type") != "result" or result_message.get("id") != call.call_id:
                raise ProviderWorkerError("worker received an unexpected tool result")
            result_ok = result_message.get("ok") is True
            result_value = (
                result_message.get("result")
                if result_ok
                else {"error": result_message.get("error", "tool call failed")}
            )
            results.append((call, result_ok, result_value))
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
                    for call in tool_calls
                ],
            }
        )
        messages.extend(
            {
                "role": "tool",
                "tool_call_id": call.call_id,
                "content": json.dumps(result_value, ensure_ascii=False, separators=(",", ":")),
            }
            for call, _result_ok, result_value in results
        )
        _validate_provider_bounds(
            messages,
            tools,
            max_request_bytes=DEFAULT_MAX_REQUEST_BYTES,
            max_conversation_messages=max_conversation_messages,
            max_conversation_chars=max_conversation_chars,
            max_tool_definition_bytes=max_tool_definition_bytes,
        )
        if len(tool_calls) == 1 and tool_calls[0].name == "stop_investigation" and results[0][1]:
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
    parser.add_argument(
        "--transport",
        choices=("mock", "openai-compatible", "openai-responses", "google-gemini"),
        default="openai-compatible",
    )
    parser.add_argument("--base-url", default=os.environ.get(PROVIDER_BASE_URL_ENV, ""))
    parser.add_argument("--max-rounds", type=int, default=16)
    parser.add_argument("--max-message-chars", type=int, default=32_000)
    parser.add_argument("--max-conversation-messages", type=int, default=DEFAULT_MAX_CONVERSATION_MESSAGES)
    parser.add_argument("--max-conversation-chars", type=int, default=DEFAULT_MAX_CONVERSATION_CHARS)
    args = parser.parse_args(argv)
    try:
        if args.transport == "mock":
            transport: ProviderTransport = ScriptedMockTransport()
        elif args.transport == "openai-responses":
            transport = OpenAIResponsesTransport(
                base_url=args.base_url,
                api_key=os.environ.get(PROVIDER_CREDENTIAL_ENV, ""),
                max_conversation_messages=args.max_conversation_messages,
                max_conversation_chars=args.max_conversation_chars,
                allow_network=os.environ.get(NETWORK_AUTHORIZATION_ENV) == "1",
            )
        elif args.transport == "google-gemini":
            transport = GoogleGeminiTransport(
                base_url=args.base_url,
                api_key=os.environ.get(PROVIDER_CREDENTIAL_ENV, ""),
                max_conversation_messages=args.max_conversation_messages,
                max_conversation_chars=args.max_conversation_chars,
                allow_network=os.environ.get(NETWORK_AUTHORIZATION_ENV) == "1",
            )
        else:
            transport = OpenAICompatibleTransport(
                base_url=args.base_url,
                api_key=os.environ.get(PROVIDER_CREDENTIAL_ENV, ""),
                max_conversation_messages=args.max_conversation_messages,
                max_conversation_chars=args.max_conversation_chars,
                allow_network=os.environ.get(NETWORK_AUTHORIZATION_ENV) == "1",
            )
        run_provider_worker(
            sys.stdin,
            sys.stdout,
            transport,
            max_rounds=args.max_rounds,
            max_message_chars=args.max_message_chars,
            max_conversation_messages=args.max_conversation_messages,
            max_conversation_chars=args.max_conversation_chars,
        )
    except (ProviderWorkerError, ValueError) as exc:
        print(f"provider worker failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
