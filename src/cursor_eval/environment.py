from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .canonical import instruction_file_hashes


def _command_output(command: list[str], timeout: float = 10.0) -> str | None:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return (completed.stdout or completed.stderr).strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect_environment(project_root: Path, *, cursor_version: str | None = None, cursor_binary: Path | None = None) -> dict[str, Any]:
    binaries = {}
    for name in ("python", "python3", "git", "rg", "bash", "wsl", "cursor-agent", "agent"):
        found = shutil.which(name)
        binaries[name] = found
    record: dict[str, Any] = {
        "os": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "git_version": _command_output(["git", "--version"]),
        "cursor_agent_version": cursor_version,
        "cursor_agent_binary": str(cursor_binary) if cursor_binary else None,
        "cursor_agent_binary_sha256": sha256_file(cursor_binary) if cursor_binary and cursor_binary.is_file() else None,
        "path": os.environ.get("PATH", ""),
        "available_binaries": binaries,
        "dependencies": [],
        "network_policy": "disabled for benchmark workspaces; CLI network access reserved for approved real trials",
        "timeout_seconds": 300,
        "command_approval_policy": "fixed CLI flags recorded by adapter; no interactive approval during benchmark",
        "worktree_layout": "one fresh isolated workspace per trial",
        "instruction_file_hashes": instruction_file_hashes(project_root),
    }
    return record
