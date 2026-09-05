from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class NormalizedEvent:
    sequence: int
    timestamp: str
    source: str
    kind: str
    path: str | None = None
    command: list[str] | None = None
    detail: dict[str, Any] | None = None


class EventLog:
    def __init__(self) -> None:
        self._events: list[NormalizedEvent] = []
        self._lock = threading.Lock()

    def record(
        self,
        source: str,
        kind: str,
        *,
        path: str | None = None,
        command: list[str] | None = None,
        detail: dict[str, Any] | None = None,
    ) -> NormalizedEvent:
        with self._lock:
            event = NormalizedEvent(
                sequence=len(self._events) + 1,
                timestamp=utc_now(),
                source=source,
                kind=kind,
                path=path,
                command=list(command) if command else None,
                detail=detail or {},
            )
            self._events.append(event)
            return event

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [asdict(event) for event in self._events]

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            for event in self.snapshot():
                handle.write(json.dumps(event, sort_keys=True) + "\n")
