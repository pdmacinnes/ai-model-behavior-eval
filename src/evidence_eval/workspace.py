from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from cursor_eval.canonical import file_manifest

from .schema import CaseVariant


class WorkspaceMaterializationError(ValueError):
    """Raised when a case cannot be safely copied into a disposable workspace."""


@dataclass(frozen=True)
class MaterializedWorkspace:
    root: Path
    files: dict[str, dict[str, Any]]
    manifest_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "files": self.files,
            "manifest_sha256": self.manifest_sha256,
        }


def _validate_relative_path(relative: str) -> None:
    if not relative or "\\" in relative:
        raise WorkspaceMaterializationError(f"unsafe workspace path: {relative!r}")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    raw_parts = relative.split("/")
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in raw_parts)
        or ".." in posix.parts
    ):
        raise WorkspaceMaterializationError(f"unsafe workspace path: {relative!r}")


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _has_link_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if _is_link(current):
            return True
    return False


def _manifest_sha256(manifest: dict[str, dict[str, Any]]) -> str:
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def resolve_workspace_path(root: Path, relative: str) -> Path:
    """Resolve a model-visible path while preserving the workspace boundary."""
    _validate_relative_path(relative)
    workspace_root = root.resolve()
    candidate = workspace_root / Path(relative)
    if _has_link_component(candidate):
        raise WorkspaceMaterializationError(f"workspace path contains a symlink or junction: {relative!r}")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise WorkspaceMaterializationError(f"workspace path escapes destination: {relative!r}") from exc
    return resolved


def materialize_variant(variant: CaseVariant, destination: Path) -> MaterializedWorkspace:
    """Copy only visible variant files into a fresh disposable workspace.

    Hidden causes, hypotheses, observations, verifier declarations, and calibration
    metadata are available to the harness but are never written into the workspace.
    """
    if _has_link_component(destination):
        raise WorkspaceMaterializationError(f"workspace destination contains a symlink or junction: {destination}")
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise WorkspaceMaterializationError(f"workspace destination is not a directory: {destination}")
        if any(destination.iterdir()):
            raise FileExistsError(f"workspace destination is not empty: {destination}")
    else:
        destination.mkdir(parents=True, exist_ok=True)

    root = destination.resolve()
    for relative, content in sorted(variant.files.items()):
        if not isinstance(relative, str) or not isinstance(content, str):
            raise WorkspaceMaterializationError("workspace files must map string paths to string contents")
        _validate_relative_path(relative)
        target = resolve_workspace_path(root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    manifest = file_manifest(root)
    return MaterializedWorkspace(root=root, files=manifest, manifest_sha256=_manifest_sha256(manifest))
