from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .events import EventLog


class RealInvocationBlocked(RuntimeError):
    """Raised whenever real Cursor execution is not explicitly enabled."""


@dataclass
class AdapterResult:
    execution_status: str
    cursor_exit_status: int | None
    raw_output: str
    model_resolved: str | None = None
    model_selection_accepted: bool | None = None
    underlying_provider_identity_verified: bool = False
    usage: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    runtime_seconds: float = 0.0


class ActionRecorder:
    def __init__(self, workspace: Path, events: EventLog, source: str = "fake-agent") -> None:
        self.workspace = workspace
        self.events = events
        self.source = source

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.workspace.resolve()).as_posix()

    def read_text(self, relative: str) -> str:
        path = self.workspace / relative
        content = path.read_text(encoding="utf-8")
        self.events.record(self.source, "read", path=self._relative(path))
        return content

    def write_text(self, relative: str, content: str) -> None:
        path = self.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        self.events.record(self.source, "write", path=self._relative(path))

    def delete(self, relative: str) -> None:
        path = self.workspace / relative
        path.unlink()
        self.events.record(self.source, "delete", path=self._relative(path))

    def run(self, command: Iterable[str], *, timeout: float = 30.0) -> subprocess.CompletedProcess[str]:
        argv = [str(item) for item in command]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
                env=_clean_agent_env(),
            )
        except subprocess.TimeoutExpired as exc:
            self.events.record(self.source, "command", command=argv, detail={"timeout": True})
            raise
        self.events.record(
            self.source,
            "command",
            command=argv,
            detail={
                "returncode": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
                "runtime_seconds": time.monotonic() - started,
            },
        )
        return completed


def _clean_agent_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.upper() in {"CURSOR_API_KEY", "CURSOR_AUTH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"}:
            env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


FakeAgentFunction = Callable[[ActionRecorder, str], None]


class FakeCursorAdapter:
    def __init__(self, agent: FakeAgentFunction, timeout_seconds: float = 30.0) -> None:
        self.agent = agent
        self.timeout_seconds = timeout_seconds

    def run(self, workspace: Path, prompt: str, model_requested: str, events: EventLog) -> AdapterResult:
        recorder = ActionRecorder(workspace, events)
        error_holder: list[BaseException] = []
        started = time.monotonic()

        def invoke() -> None:
            try:
                self.agent(recorder, prompt)
            except BaseException as exc:  # propagated below as an adapter result
                error_holder.append(exc)

        thread = threading.Thread(target=invoke, name="fake-cursor-agent", daemon=True)
        thread.start()
        thread.join(self.timeout_seconds)
        if thread.is_alive():
            return AdapterResult(
                execution_status="timeout",
                cursor_exit_status=None,
                raw_output="",
                error=f"fake agent exceeded {self.timeout_seconds} seconds",
                runtime_seconds=time.monotonic() - started,
            )
        if error_holder:
            exc = error_holder[0]
            return AdapterResult(
                execution_status="provider_failure",
                cursor_exit_status=1,
                raw_output="",
                error=f"{type(exc).__name__}: {exc}",
                runtime_seconds=time.monotonic() - started,
            )
        return AdapterResult(
            execution_status="completed",
            cursor_exit_status=0,
            raw_output="fake-agent-complete",
            model_resolved=model_requested,
            model_selection_accepted=True,
            runtime_seconds=time.monotonic() - started,
        )


@dataclass(frozen=True)
class RealCursorConfig:
    executable: str = "agent"
    distribution: str = "Ubuntu"
    timeout_seconds: float = 300.0
    force: bool = True
    trust: bool = True
    output_format: str = "stream-json"


class RealCursorAdapter:
    """Supported Cursor CLI adapter with an explicit no-invocation safety gate."""

    def __init__(self, config: RealCursorConfig | None = None, allow_real_invocation: bool = False) -> None:
        self.config = config or RealCursorConfig()
        self.allow_real_invocation = allow_real_invocation

    def command_for(self, workspace: Path, prompt: str, model_requested: str) -> list[str]:
        args = [
            "wsl.exe",
            "-d",
            self.config.distribution,
            "--",
            self.config.executable,
            "--print",
            "--output-format",
            self.config.output_format,
            "--workspace",
            to_wsl_path(workspace),
            "--model",
            model_requested,
        ]
        if self.config.force:
            args.append("--force")
        if self.config.trust:
            args.append("--trust")
        args.append(prompt)
        return args

    def run(self, workspace: Path, prompt: str, model_requested: str, events: EventLog) -> AdapterResult:
        if not self.allow_real_invocation:
            raise RealInvocationBlocked(
                "real Cursor invocation is disabled; set an explicit execution approval after preregistration"
            )
        command = self.command_for(workspace, prompt, model_requested)
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_clean_agent_env(),
        )
        stdout = ""
        stderr = ""
        model_resolved: str | None = None
        usage: dict[str, Any] = {}
        try:
            stdout, stderr = process.communicate(timeout=self.config.timeout_seconds)
            for line in stdout.splitlines():
                parsed = parse_cursor_event(line)
                if parsed is None:
                    continue
                event_type = parsed.get("type")
                if event_type == "system" and parsed.get("subtype") == "init":
                    model_resolved = parsed.get("model")
                    events.record("cursor", "session_init", detail={"model": model_resolved, "session_id": parsed.get("session_id")})
                _record_cursor_tool_event(parsed, events)
                usage.update(_find_usage_fields(parsed))
            returncode = process.returncode
        except subprocess.TimeoutExpired:
            process.kill()
            timed_out_stdout, timed_out_stderr = process.communicate()
            stdout = timed_out_stdout or stdout
            stderr = timed_out_stderr or stderr
            return AdapterResult(
                execution_status="timeout",
                cursor_exit_status=None,
                raw_output=stdout,
                model_resolved=model_resolved,
                model_selection_accepted=model_resolved is not None,
                usage=usage,
                error="Cursor CLI timed out",
                runtime_seconds=time.monotonic() - started,
            )
        if returncode != 0:
            return AdapterResult(
                execution_status="cli_failure",
                cursor_exit_status=returncode,
                raw_output=stdout,
                model_resolved=model_resolved,
                model_selection_accepted=model_resolved is not None,
                usage=usage,
                error=stderr[-4000:],
                runtime_seconds=time.monotonic() - started,
            )
        return AdapterResult(
            execution_status="completed",
            cursor_exit_status=0,
            raw_output=stdout,
            model_resolved=model_resolved,
            model_selection_accepted=model_resolved is not None,
            usage=usage,
            runtime_seconds=time.monotonic() - started,
        )


def to_wsl_path(path: Path) -> str:
    value = str(path.resolve())
    if re.match(r"^[A-Za-z]:[\\/]", value):
        drive = value[0].lower()
        rest = value[2:].replace("\\", "/")
        return f"/mnt/{drive}{rest}"
    return value.replace("\\", "/")


def parse_cursor_event(line: str) -> dict[str, Any] | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _record_cursor_tool_event(event: dict[str, Any], events: EventLog) -> None:
    if event.get("type") != "tool_call":
        return
    tool_call = event.get("tool_call")
    if not isinstance(tool_call, dict):
        return
    for tool_name, value in tool_call.items():
        args = value.get("args", {}) if isinstance(value, dict) else {}
        if not isinstance(args, dict):
            args = {}
        lower = tool_name.lower()
        if "read" in lower:
            events.record("cursor", "read", path=str(args.get("path")) if args.get("path") else None, detail={"tool": tool_name})
        elif "write" in lower or "edit" in lower:
            events.record("cursor", "write", path=str(args.get("path")) if args.get("path") else None, detail={"tool": tool_name})
        elif "shell" in lower or "terminal" in lower or "bash" in lower:
            command = args.get("command") or args.get("cmd") or args.get("script")
            argv = [str(command)] if isinstance(command, str) else [str(item) for item in command] if isinstance(command, list) else None
            events.record("cursor", "command", command=argv, detail={"tool": tool_name})
        else:
            events.record("cursor", "tool", detail={"tool": tool_name})


def _find_usage_fields(value: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = key.lower()
            if any(token in normalized for token in ("usage", "token", "cost", "billing", "quota")):
                found[key] = item
            else:
                found.update(_find_usage_fields(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_usage_fields(item))
    return found
