from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from pathlib import Path

from evidence_eval.execution_policy import NETWORK_AUTHORIZATION_ENV, PROVIDER_BASE_URL_ENV, PROVIDER_CREDENTIAL_ENV
from evidence_eval.provider_worker import (
    OpenAICompatibleTransport,
    ProviderReply,
    ProviderToolCall,
    ProviderWorkerError,
    ProviderTransportError,
    ScriptedMockTransport,
    build_openai_compatible_request,
    main,
    parse_openai_compatible_response,
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


if __name__ == "__main__":
    unittest.main()
