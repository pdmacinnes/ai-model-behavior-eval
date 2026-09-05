from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CaseFormatError(ValueError):
    """Raised when a canonical case definition is malformed."""


@dataclass(frozen=True)
class CaseDefinition:
    case_id: str
    dimension: str
    prompt: str
    visible_test_command: tuple[str, ...]
    grading: dict[str, Any]
    files: dict[str, str]
    canonical_path: Path
    canonical_sha256: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validate_relative_path(path: str) -> None:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts or "\\" in path:
        raise CaseFormatError(f"unsafe case path: {path!r}")
    if not path or path.endswith("/"):
        raise CaseFormatError(f"invalid case path: {path!r}")


def load_case(canonical_path: Path) -> CaseDefinition:
    raw = canonical_path.read_bytes()
    digest = sha256_bytes(raw)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseFormatError(f"invalid canonical JSON: {canonical_path}") from exc
    required = {"case_id", "dimension", "prompt", "visible_test_command", "grading", "files"}
    missing = required - payload.keys()
    if missing:
        raise CaseFormatError(f"missing case fields: {sorted(missing)}")
    files = payload["files"]
    if not isinstance(files, dict) or not files:
        raise CaseFormatError("case files must be a non-empty object")
    normalized_files: dict[str, str] = {}
    for path, content in files.items():
        if not isinstance(path, str) or not isinstance(content, str):
            raise CaseFormatError("case file paths and contents must be strings")
        _validate_relative_path(path)
        if "\r" in content:
            raise CaseFormatError(f"case content contains CR bytes: {path}")
        normalized_files[path] = content
    command = payload["visible_test_command"]
    if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
        raise CaseFormatError("visible_test_command must be a non-empty string list")
    grading = payload["grading"]
    if not isinstance(grading, dict):
        raise CaseFormatError("grading must be an object")
    return CaseDefinition(
        case_id=str(payload["case_id"]),
        dimension=str(payload["dimension"]),
        prompt=str(payload["prompt"]),
        visible_test_command=tuple(command),
        grading=grading,
        files=normalized_files,
        canonical_path=canonical_path,
        canonical_sha256=digest,
    )


def materialize_case(case: CaseDefinition, workspace: Path) -> None:
    if workspace.exists() and any(workspace.iterdir()):
        raise FileExistsError(f"workspace is not empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    for relative, content in case.files.items():
        destination = workspace / Path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content.encode("utf-8"))


def file_manifest(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        result[relative] = {
            "sha256": sha256_bytes(data),
            "size": len(data),
            "mode": os.stat(path).st_mode & 0o777,
        }
    return result


def instruction_file_hashes(root: Path) -> dict[str, str]:
    candidates = ["AGENTS.md", "CLAUDE.md", ".cursor/mcp.json"]
    candidates.extend(path.relative_to(root).as_posix() for path in root.glob(".cursor/rules/*") if path.is_file())
    result: dict[str, str] = {}
    for relative in candidates:
        path = root / relative
        if path.is_file():
            result[relative] = sha256_bytes(path.read_bytes())
    return result
