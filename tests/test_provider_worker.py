from __future__ import annotations

import io
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch
from pathlib import Path

from evidence_eval.execution_policy import NETWORK_AUTHORIZATION_ENV, PROVIDER_BASE_URL_ENV, PROVIDER_CREDENTIAL_ENV
from evidence_eval.provider_worker import (
    OpenAICompatibleTransport,
    OpenAIResponsesTransport,
    ProviderReply,
    ProviderToolCall,
    ProviderWorkerError,
    ProviderTransportError,
    ScriptedMockTransport,
    build_openai_compatible_request,
    build_openai_responses_request,
    main,
    parse_openai_compatible_response,
    parse_openai_responses_response,
    run_provider_worker,
)
from evidence_eval.runner import ModelCondition
from evidence_eval.schema import load_case_family
from evidence_eval.subprocess_adapter import SubprocessAdapterConfig, SubprocessWorkspaceAdapter
from evidence_eval.workspace_runner import run_workspace_trial, workspace_tool_contract


ROOT = Path(__file__).resolve().parents[1]


class ProviderWorkerTests(unittest.TestCase):
    def _task(self) -> dict[str, object]:
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        return {
            "type": "task",
            "task": {
                **family.initial_context,
                "tool_contract": workspace_tool_contract(family),
                "model_condition": {
                    "provider": "mock-provider",
                    "model_id": "mock-model",
                    "adapter_id": "jsonl-provider-worker",
                    "reasoning_effort": None,
                },
            },
        }

    def test_openai_request_shape_does_not_include_credentials(self):
        request = build_openai_compatible_request(
            [{"role": "user", "content": "investigate"}],
            [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
            model_id="model-a",
            reasoning_effort="high",
        )
        self.assertEqual(request["model"], "model-a")
        self.assertEqual(request["reasoning_effort"], "high")
        self.assertNotIn("api_key", json.dumps(request))
        self.assertNotIn("Authorization", json.dumps(request))

    def test_openai_response_parser_accepts_one_tool_call(self):
        reply = parse_openai_compatible_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "request_evidence",
                                        "arguments": '{"action":"inspect","target":"lib/cache.ts"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
        self.assertEqual(reply.tool_calls[0].name, "request_evidence")
        self.assertEqual(reply.tool_calls[0].arguments["target"], "lib/cache.ts")

    def test_openai_response_parser_rejects_multiple_tool_calls(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"id": "one", "function": {"name": "stop_investigation", "arguments": "{}"}},
                            {"id": "two", "function": {"name": "stop_investigation", "arguments": "{}"}},
                        ],
                    }
                }
            ]
        }
        with self.assertRaises(ProviderTransportError):
            parse_openai_compatible_response(response)

    def test_openai_response_parser_rejects_oversized_text_and_bad_arguments(self):
        oversized = {"choices": [{"message": {"content": "too long", "tool_calls": []}}]}
        with self.assertRaises(ProviderTransportError):
            parse_openai_compatible_response(oversized, max_text_chars=3)
        bad_arguments = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "function": {"name": "request_evidence", "arguments": "not-json"},
                            }
                        ],
                    }
                }
            ]
        }
        with self.assertRaises(ProviderTransportError):
            parse_openai_compatible_response(bad_arguments)

    def test_responses_request_shape_translates_conversation_and_tools(self):
        messages = [
            {"role": "user", "content": "investigate"},
            {
                "role": "assistant",
                "content": "I will inspect the cache path.",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "request_evidence",
                            "arguments": '{"action":"inspect","target":"lib/cache.ts"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call-1",
                "content": '{"content":"cache key omits range"}',
            },
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "request_evidence",
                    "description": "Inspect evidence",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]
        request = build_openai_responses_request(
            messages,
            tools,
            model_id="gpt-5.6-luna",
            reasoning_effort="high",
        )
        self.assertEqual(request["model"], "gpt-5.6-luna")
        self.assertEqual(request["reasoning"], {"effort": "high"})
        self.assertFalse(request["parallel_tool_calls"])
        self.assertFalse(request["store"])
        self.assertEqual(request["tools"][0]["name"], "request_evidence")
        self.assertNotIn("function", request["tools"][0])
        self.assertEqual(request["input"][1]["type"], "message")
        self.assertEqual(request["input"][2]["type"], "function_call")
        self.assertEqual(request["input"][3]["type"], "function_call_output")
        self.assertNotIn("Authorization", json.dumps(request))
        self.assertNotIn("api_key", json.dumps(request))

    def test_responses_request_omits_null_reasoning(self):
        request = build_openai_responses_request(
            [{"role": "user", "content": "investigate"}],
            [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
            model_id="model-a",
            reasoning_effort=None,
        )
        self.assertNotIn("reasoning", request)

    def test_responses_request_rejects_mismatched_call_id_before_network(self):
        messages = [
            {"role": "user", "content": "investigate"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {"name": "request_evidence", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call-2", "content": "{}"},
        ]
        with self.assertRaisesRegex(ProviderWorkerError, "call id"):
            build_openai_responses_request(
                messages,
                [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                model_id="model-a",
                reasoning_effort=None,
            )

    def test_responses_parser_accepts_text_and_one_function_call(self):
        reply = parse_openai_responses_response(
            {
                "status": "completed",
                "output_text": "I found the relevant evidence.",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "request_evidence",
                        "arguments": '{"action":"inspect","target":"lib/cache.ts"}',
                    },
                ],
            }
        )
        self.assertEqual(reply.text, "I found the relevant evidence.")
        self.assertEqual(reply.tool_calls[0].call_id, "call-1")
        self.assertEqual(reply.tool_calls[0].arguments["action"], "inspect")

    def test_responses_parser_rejects_multiple_function_calls(self):
        response = {
            "status": "completed",
            "output": [
                {"type": "function_call", "call_id": "one", "name": "stop_investigation", "arguments": "{}"},
                {"type": "function_call", "call_id": "two", "name": "stop_investigation", "arguments": "{}"},
            ],
        }
        with self.assertRaises(ProviderTransportError):
            parse_openai_responses_response(response)

    def test_responses_parser_rejects_incomplete_response(self):
        with self.assertRaisesRegex(ProviderTransportError, "not completed"):
            parse_openai_responses_response({"status": "in_progress", "output": []})

    def test_network_transport_is_disabled_before_request(self):
        transport = OpenAICompatibleTransport(base_url="https://example.invalid/v1", api_key="secret")
        with self.assertRaisesRegex(ProviderTransportError, "network execution is disabled"):
            transport.request([], [{"type": "function"}], model_id="model-a", reasoning_effort=None)

    def test_network_transport_rejects_missing_credential_without_request(self):
        transport = OpenAICompatibleTransport(base_url="https://example.invalid/v1", api_key="", allow_network=True)
        with self.assertRaisesRegex(ProviderTransportError, "credential is missing"):
            transport.request([], [{"type": "function"}], model_id="model-a", reasoning_effort=None)

    def test_request_byte_bound_rejects_before_urlopen(self):
        transport = OpenAICompatibleTransport(
            base_url="https://example.invalid/v1",
            api_key="secret",
            allow_network=True,
            max_request_bytes=1,
        )
        with patch("evidence_eval.provider_worker.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ProviderWorkerError, "request exceeded the byte bound"):
                transport.request(
                    [{"role": "user", "content": "investigate"}],
                    [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                    model_id="model-a",
                    reasoning_effort=None,
                )
        urlopen.assert_not_called()

    def test_tool_definition_bound_is_independent(self):
        with self.assertRaisesRegex(ProviderWorkerError, "tool definitions exceeded"):
            build_openai_compatible_request(
                [{"role": "user", "content": "investigate"}],
                [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                model_id="model-a",
                reasoning_effort=None,
                max_tool_definition_bytes=1,
            )

    def test_conversation_append_bound_fails_before_next_request(self):
        class OneCallTransport:
            calls = 0

            def request(self, messages, tools, *, model_id, reasoning_effort):
                del messages, tools, model_id, reasoning_effort
                self.calls += 1
                return ProviderReply(
                    tool_calls=(ProviderToolCall("call-1", "request_evidence", {"action": "inspect", "target": "app/dashboard/page.tsx"}),),
                )

        task = self._task()
        input_stream = io.StringIO(
            json.dumps(task)
            + "\n"
            + json.dumps(
                {
                    "type": "result",
                    "id": "call-1",
                    "ok": True,
                    "result": {"content": "x" * 1000},
                }
            )
            + "\n"
        )
        transport = OneCallTransport()
        with self.assertRaisesRegex(ProviderWorkerError, "conversation exceeded"):
            run_provider_worker(input_stream, io.StringIO(), transport, max_conversation_chars=500)
        self.assertEqual(transport.calls, 1)

    def test_http_timeout_is_sanitized(self):
        transport = OpenAICompatibleTransport(
            base_url="https://example.invalid/v1",
            api_key="secret",
            allow_network=True,
        )
        with patch(
            "evidence_eval.provider_worker.urllib.request.urlopen",
            side_effect=urllib.error.URLError("secret-body"),
        ):
            with self.assertRaisesRegex(ProviderTransportError, "provider request failed") as context:
                transport.request(
                    [{"role": "user", "content": "investigate"}],
                    [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                    model_id="model-a",
                    reasoning_effort=None,
                )
        self.assertNotIn("secret-body", str(context.exception))

    def test_fake_http_transport_parses_without_external_network(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit):
                self.limit = limit
                return b'{"choices":[{"message":{"content":"ok","tool_calls":[]}}]}'

        transport = OpenAICompatibleTransport(
            base_url="http://fake.local/v1",
            api_key="secret",
            allow_network=True,
        )
        with patch("evidence_eval.provider_worker.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            reply = transport.request(
                [{"role": "user", "content": "investigate"}],
                [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                model_id="model-a",
                reasoning_effort=None,
            )
        self.assertEqual(reply.text, "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://fake.local/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_fake_responses_transport_parses_without_external_network(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, limit):
                self.limit = limit
                return json.dumps(
                    {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": "ok"}],
                            }
                        ],
                    }
                ).encode("utf-8")

        transport = OpenAIResponsesTransport(
            base_url="http://fake.local/v1",
            api_key="secret",
            allow_network=True,
        )
        with patch("evidence_eval.provider_worker.urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            reply = transport.request(
                [{"role": "user", "content": "investigate"}],
                [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                model_id="model-a",
                reasoning_effort=None,
            )
        self.assertEqual(reply.text, "ok")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://fake.local/v1/responses")
        payload = json.loads(request.data.decode("utf-8"))
        self.assertNotIn("reasoning", payload)
        self.assertFalse(payload["store"])
        self.assertEqual(request.get_header("Authorization"), "Bearer secret")

    def test_responses_request_byte_bound_rejects_before_urlopen(self):
        transport = OpenAIResponsesTransport(
            base_url="https://example.invalid/v1",
            api_key="secret",
            allow_network=True,
            max_request_bytes=1,
        )
        with patch("evidence_eval.provider_worker.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ProviderWorkerError, "request exceeded the byte bound"):
                transport.request(
                    [{"role": "user", "content": "investigate"}],
                    [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                    model_id="model-a",
                    reasoning_effort=None,
                )
        urlopen.assert_not_called()

    def test_responses_conversation_bound_rejects_before_urlopen(self):
        transport = OpenAIResponsesTransport(
            base_url="https://example.invalid/v1",
            api_key="secret",
            allow_network=True,
            max_conversation_chars=1,
        )
        with patch("evidence_eval.provider_worker.urllib.request.urlopen") as urlopen:
            with self.assertRaisesRegex(ProviderWorkerError, "conversation exceeded"):
                transport.request(
                    [{"role": "user", "content": "investigate"}],
                    [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                    model_id="model-a",
                    reasoning_effort=None,
                )
        urlopen.assert_not_called()

    def test_responses_http_error_is_sanitized(self):
        transport = OpenAIResponsesTransport(
            base_url="https://example.invalid/v1",
            api_key="secret",
            allow_network=True,
        )
        error = urllib.error.HTTPError(
            "https://example.invalid/v1/responses",
            400,
            "bad request",
            {},
            io.BytesIO(b'{"error":{"message":"secret-body"}}'),
        )
        with patch("evidence_eval.provider_worker.urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(ProviderTransportError, "provider HTTP error 400") as context:
                transport.request(
                    [{"role": "user", "content": "investigate"}],
                    [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                    model_id="model-a",
                    reasoning_effort=None,
                )
        self.assertNotIn("secret-body", str(context.exception))

    def test_responses_http_timeout_is_sanitized(self):
        transport = OpenAIResponsesTransport(
            base_url="https://example.invalid/v1",
            api_key="secret",
            allow_network=True,
        )
        with patch(
            "evidence_eval.provider_worker.urllib.request.urlopen",
            side_effect=urllib.error.URLError("secret-body"),
        ):
            with self.assertRaisesRegex(ProviderTransportError, "provider request failed") as context:
                transport.request(
                    [{"role": "user", "content": "investigate"}],
                    [{"type": "function", "function": {"name": "request_evidence", "parameters": {}}}],
                    model_id="model-a",
                    reasoning_effort=None,
                )
        self.assertNotIn("secret-body", str(context.exception))

    def test_worker_network_gate_is_parent_environment_only(self):
        with patch.dict(os.environ, {PROVIDER_BASE_URL_ENV: "https://example.invalid/v1"}, clear=True):
            with patch("evidence_eval.provider_worker.run_provider_worker") as run_worker:
                self.assertEqual(main(["--transport", "openai-compatible"]), 0)
        disabled_transport = run_worker.call_args.args[2]
        self.assertFalse(disabled_transport.allow_network)

        with patch.dict(
            os.environ,
            {
                PROVIDER_BASE_URL_ENV: "https://example.invalid/v1",
                PROVIDER_CREDENTIAL_ENV: "secret",
                NETWORK_AUTHORIZATION_ENV: "1",
            },
            clear=True,
        ):
            with patch("evidence_eval.provider_worker.run_provider_worker") as run_worker:
                self.assertEqual(main(["--transport", "openai-compatible"]), 0)
        enabled_transport = run_worker.call_args.args[2]
        self.assertTrue(enabled_transport.allow_network)

        with patch.dict(
            os.environ,
            {
                PROVIDER_BASE_URL_ENV: "https://example.invalid/v1",
                PROVIDER_CREDENTIAL_ENV: "secret",
                NETWORK_AUTHORIZATION_ENV: "1",
            },
            clear=True,
        ):
            with patch("evidence_eval.provider_worker.run_provider_worker") as run_worker:
                self.assertEqual(main(["--transport", "openai-responses"]), 0)
        self.assertIsInstance(run_worker.call_args.args[2], OpenAIResponsesTransport)
        self.assertTrue(run_worker.call_args.args[2].allow_network)

    def test_worker_rejects_local_network_and_credential_overrides(self):
        with self.assertRaises(SystemExit):
            main(["--allow-network"])
        with self.assertRaises(SystemExit):
            main(["--api-key-env", "OTHER"])

    def test_mock_worker_completes_tool_loop_and_stops(self):
        task = self._task()
        input_stream = io.StringIO(
            "\n".join(
                [
                    json.dumps(task),
                    json.dumps({"type": "result", "id": "mock-inspect", "ok": True, "result": {"content": "await getMetrics()"}}),
                    json.dumps({"type": "result", "id": "mock-checkpoint", "ok": True, "result": {"accepted": True}}),
                    json.dumps({"type": "result", "id": "mock-edit", "ok": True, "result": {"accepted": True}}),
                    json.dumps({"type": "result", "id": "mock-stop", "ok": True, "result": {"accepted": True}}),
                ]
            )
            + "\n"
        )
        output_stream = io.StringIO()
        run_provider_worker(input_stream, output_stream, ScriptedMockTransport())
        messages = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual([message["type"] for message in messages], ["call", "call", "call", "call", "final"])
        self.assertEqual(messages[-1]["status"], "stopped")
        self.assertEqual(messages[0]["method"], "request_evidence")
        self.assertEqual(messages[1]["method"], "record_checkpoint")
        self.assertEqual(messages[2]["method"], "edit_file")
        self.assertEqual(messages[3]["method"], "stop_investigation")

    def test_mock_worker_runs_through_parent_owned_workspace_tools(self):
        family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
        condition = ModelCondition(
            provider="mock-provider",
            model_id="mock-model",
            adapter_id="jsonl-provider-worker",
            prompt=family.initial_context["prompt"],
        )
        command = (
            sys.executable,
            str(ROOT / "scripts" / "openai_compatible_workspace_worker.py"),
            "--transport",
            "mock",
        )
        adapter = SubprocessWorkspaceAdapter(SubprocessAdapterConfig(command, timeout_seconds=5.0))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = []
            for variant in family.variants:
                records.append(
                    run_workspace_trial(
                        family,
                        variant,
                        condition,
                        adapter,
                        artifacts_root=root / "artifacts",
                        workspace_parent=root / "workspaces",
                        run_id=f"mock-{variant.variant_id}",
                        adapter_timeout_seconds=10.0,
                    )
                )
        self.assertTrue(all(record["execution_status"] == "stopped" for record in records))
        self.assertTrue(all(not record["infrastructure_censored"] for record in records))
        self.assertTrue(any(record["verifier_result"]["passed"] for record in records))

    def test_responses_worker_runs_through_subprocess_and_parent_tools(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self.server.payloads.append(payload)
                if self.server.round == 0:
                    output = [
                        {
                            "type": "function_call",
                            "call_id": "fake-inspect",
                            "name": "request_evidence",
                            "arguments": '{"action":"inspect","target":"app/dashboard/page.tsx"}',
                        }
                    ]
                else:
                    output = [
                        {
                            "type": "function_call",
                            "call_id": "fake-stop",
                            "name": "stop_investigation",
                            "arguments": '{"reason":"fake Responses transport completed"}',
                        }
                    ]
                self.server.round += 1
                body = json.dumps({"status": "completed", "output": output}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                del format, args

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.round = 0
        server.payloads = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            family = load_case_family(ROOT / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
            condition = ModelCondition(
                provider="openai",
                model_id="fake-model",
                adapter_id="jsonl-provider-worker",
                prompt=family.initial_context["prompt"],
            )
            command = (
                sys.executable,
                str(ROOT / "scripts" / "openai_compatible_workspace_worker.py"),
                "--transport",
                "openai-responses",
                "--base-url",
                f"http://127.0.0.1:{server.server_port}/v1",
            )
            adapter = SubprocessWorkspaceAdapter(
                SubprocessAdapterConfig(
                    command,
                    timeout_seconds=5.0,
                    credential_env_names=(PROVIDER_CREDENTIAL_ENV,),
                    network_authorized=True,
                )
            )
            with patch.dict(os.environ, {PROVIDER_CREDENTIAL_ENV: "secret"}, clear=False):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    record = run_workspace_trial(
                        family,
                        family.variants[0],
                        condition,
                        adapter,
                        artifacts_root=root / "artifacts",
                        workspace_parent=root / "workspaces",
                        run_id="responses-fake-subprocess",
                        adapter_timeout_seconds=10.0,
                    )
            self.assertEqual(record["execution_status"], "stopped")
            self.assertFalse(record["infrastructure_censored"])
            self.assertEqual(len(server.payloads), 2)
            self.assertFalse(server.payloads[0]["store"])
            self.assertNotIn("reasoning", server.payloads[0])
            self.assertEqual(server.payloads[1]["input"][-1]["type"], "function_call_output")
            self.assertEqual(server.payloads[1]["input"][-1]["call_id"], "fake-inspect")
        finally:
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    unittest.main()
