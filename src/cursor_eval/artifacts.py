from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


class ArtifactExistsError(FileExistsError):
    """Raised when an immutable artifact would be overwritten."""


def write_once(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    mode = 0o444
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError as exc:
        raise ArtifactExistsError(str(path)) from exc
    try:
        payload = data.encode("utf-8") if isinstance(data, str) else data
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
    except FileExistsError as exc:
        raise ArtifactExistsError(str(path)) from exc
    finally:
        if descriptor != -1:
            os.close(descriptor)
    try:
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:
        pass


def write_json_once(path: Path, value: Any) -> None:
    write_once(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_run_artifacts(run_dir: Path, artifacts: dict[str, str | bytes | dict[str, Any] | list[Any]]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for relative, value in artifacts.items():
        path = run_dir / relative
        if isinstance(value, (dict, list)):
            write_json_once(path, value)
        else:
            write_once(path, value)
    write_once(run_dir / "immutable.complete", "complete\n")
