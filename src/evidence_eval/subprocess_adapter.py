"""JSONL subprocess transport for workspace adapters.

The child process receives the task and can request only the declared workspace
tools. It does not receive the workspace path, case variant, or verifier object.
This is a process boundary, not a complete OS sandbox; untrusted providers still
need an external sandbox policy.
"""

from __future__ import annotations

import json
import queue
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from cursor_eval.adapters import _clean_agent_env

from .runner import AgentResult
from .workspace_runner import WorkspaceTools


@dataclass(frozen=True)
class SubprocessAdapterConfig:
    command: tuple[str, ...]
    timeout_seconds: float = 300.0
    max_message_chars: int = 32_000
    max_pending_messages: int = 128


_WORKER_BEHAVIOR_STATUSES = frozenset({"completed", "refused", "insufficient_evidence", "stopped"})


class SubprocessWorkspaceAdapter:
    """Adapt a JSONL worker process to the trusted WorkspaceAdapter callable."""

    def __init__(self, config: SubprocessAdapterConfig) -> None:
        if not config.command:
            raise ValueError("subprocess adapter command must not be empty")
        if config.timeout_seconds <= 0:
            raise ValueError("subprocess adapter timeout must be positive")
        if config.max_message_chars <= 0:
            raise ValueError("subprocess adapter message bound must be positive")
        if config.max_pending_messages <= 0:
            raise ValueError("subprocess adapter pending-message bound must be positive")
        self.config = config
        self._process_lock = threading.Lock()
        self._active_process: subprocess.Popen[str] | None = None

    @property
    def timeout_seconds(self) -> float:
        return self.config.timeout_seconds

    def __call__(self, task: dict[str, Any], tools: WorkspaceTools) -> AgentResult:
        return self.run(task, tools)

    def _encode(self, value: dict[str, Any]) -> str:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(payload) > self.config.max_message_chars:
            raise ValueError("subprocess adapter message exceeded bound")
        return payload + "\n"

    def _send(self, process: subprocess.Popen[str], value: dict[str, Any]) -> None:
        if process.stdin is None:
            raise BrokenPipeError("subprocess adapter stdin is closed")
        process.stdin.write(self._encode(value))
        process.stdin.flush()

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=0.5)
                except (OSError, subprocess.TimeoutExpired):
                    pass

    def terminate(self) -> None:
        """Terminate the active child when the enclosing runner times out."""
        with self._process_lock:
            process = self._active_process
        if process is not None:
            self._terminate_process(process)

    def run(self, task: dict[str, Any], tools: WorkspaceTools) -> AgentResult:
        env = _clean_agent_env()
        env.pop("PYTHONPATH", None)
        try:
            process = subprocess.Popen(
                list(self.config.command),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            return AgentResult(status="adapter_error", error=f"could not start subprocess adapter: {type(exc).__name__}: {exc}")
        with self._process_lock:
            self._active_process = process

        messages: queue.Queue[tuple[str, str | None]] = queue.Queue(maxsize=self.config.max_pending_messages)
        output_overflow = threading.Event()
        line_overflow = threading.Event()

        def read_stream(name: str, stream) -> None:
            try:
                while True:
                    line = stream.readline(self.config.max_message_chars + 2)
                    if not line:
                        break
                    if len(line.rstrip("\r\n")) > self.config.max_message_chars:
                        line_overflow.set()
                        return
                    try:
                        messages.put_nowait((name, line))
                    except queue.Full:
                        output_overflow.set()
                        return
            finally:
                try:
                    messages.put_nowait((f"{name}_eof", None))
                except queue.Full:
                    output_overflow.set()

        stdout_thread = threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True)
        stderr_thread = threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True)
        stdout_thread.start()
        stderr_thread.start()
        stderr_lines: deque[str] = deque(maxlen=128)
        started = time.monotonic()
        final: AgentResult | None = None
        try:
            self._send(process, {"type": "task", "task": task})
            deadline = started + self.config.timeout_seconds
            while final is None:
                if line_overflow.is_set():
                    return AgentResult(
                        status="adapter_error",
                        error="subprocess adapter response exceeded bound",
                        metadata={"stderr": "".join(stderr_lines)[-4000:]},
                    )
                if output_overflow.is_set():
                    return AgentResult(
                        status="adapter_error",
                        error="subprocess adapter output queue exceeded bound",
                        metadata={"stderr": "".join(stderr_lines)[-4000:]},
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return AgentResult(
                        status="adapter_timeout",
                        error=f"subprocess adapter exceeded {self.config.timeout_seconds:.3f}s",
                        metadata={"stderr": "".join(stderr_lines)[-4000:]},
                    )
                try:
                    stream_name, line = messages.get(timeout=min(remaining, 0.25))
                except queue.Empty:
                    if process.poll() is not None:
                        return AgentResult(
                            status="adapter_error",
                            error="subprocess adapter exited without a final message",
                            metadata={"stderr": "".join(stderr_lines)[-4000:]},
                        )
                    continue
                if line is None:
                    if stream_name == "stdout_eof":
                        if process.poll() is not None:
                            return AgentResult(
                                status="adapter_error",
                                error="subprocess adapter exited without a final message",
                                metadata={"stderr": "".join(stderr_lines)[-4000:]},
                            )
                    continue
                if stream_name == "stderr":
                    stderr_lines.append(line)
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as exc:
                    return AgentResult(status="adapter_error", error=f"invalid subprocess adapter JSON: {exc}")
                if not isinstance(message, dict):
                    return AgentResult(status="adapter_error", error="subprocess adapter message must be an object")
                message_type = message.get("type")
                if message_type == "final":
                    reported_status = str(message.get("status", "completed"))
                    response = str(message.get("final_response", ""))
                    metadata = message.get("metadata", {})
                    worker_metadata = dict(metadata) if isinstance(metadata, dict) else {}
                    if reported_status not in _WORKER_BEHAVIOR_STATUSES:
                        worker_metadata["worker_reported_status"] = reported_status
                        if message.get("error") is not None:
                            worker_metadata["worker_reported_error"] = str(message["error"])
                        status = "completed"
                        error = None
                    else:
                        status = reported_status
                        error = str(message["error"]) if message.get("error") is not None else None
                    final = AgentResult(
                        status=status,
                        final_response=response,
                        metadata=worker_metadata,
                        error=error,
                    )
                    break
                if message_type != "call":
                    return AgentResult(status="adapter_error", error="subprocess adapter expected call or final message")
                call_id = str(message.get("id", ""))
                method = message.get("method")
                arguments = message.get("arguments", {})
                if not isinstance(arguments, dict):
                    self._send(process, {"type": "result", "id": call_id, "ok": False, "error": "arguments must be an object"})
                    continue
                try:
                    result = self._dispatch(method, arguments, tools)
                    self._send(process, {"type": "result", "id": call_id, "ok": True, "result": result})
                except Exception as exc:
                    self._send(
                        process,
                        {"type": "result", "id": call_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"},
                    )
            return final or AgentResult(status="adapter_error", error="subprocess adapter produced no final result")
        except (BrokenPipeError, OSError, ValueError) as exc:
            return AgentResult(status="adapter_error", error=f"subprocess adapter transport error: {type(exc).__name__}: {exc}")
        finally:
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            self._terminate_process(process)
            stdout_thread.join(timeout=0.5)
            stderr_thread.join(timeout=0.5)
            for stream in (process.stdout, process.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            with self._process_lock:
                if self._active_process is process:
                    self._active_process = None

    @staticmethod
    def _dispatch(method: Any, arguments: dict[str, Any], tools: WorkspaceTools) -> dict[str, Any]:
        if method == "request_evidence":
            response = tools.request(str(arguments.get("action", "")), str(arguments.get("target", "")))
            return response.to_dict()
        if method == "edit_file":
            response = tools.edit_file(
                str(arguments.get("path", "")),
                str(arguments.get("before", "")),
                str(arguments.get("after", "")),
            )
            return response.to_dict()
        if method == "record_checkpoint":
            tools.checkpoint(
                leading_hypothesis=str(arguments.get("leading_hypothesis", "")),
                alternative_hypothesis=str(arguments.get("alternative_hypothesis", "")),
                confidence=float(arguments.get("confidence", 0.0)),
                changed_by=str(arguments.get("changed_by", "")),
                next_action=str(arguments.get("next_action", "")),
            )
            return {"accepted": True}
        if method == "stop_investigation":
            tools.stop(str(arguments.get("reason", "")))
            return {"accepted": True}
        raise ValueError(f"unsupported subprocess adapter method: {method!r}")
