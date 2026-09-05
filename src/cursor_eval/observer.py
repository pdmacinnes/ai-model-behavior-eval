from __future__ import annotations

import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from .canonical import file_manifest
from .events import utc_now


@dataclass
class MutationEvent:
    sequence: int
    timestamp: str
    path: str
    action: str
    before_exists: bool
    after_exists: bool
    before_hash: str | None
    after_hash: str | None


class MutationObserver:
    """Polling observer kept outside the model-visible workspace."""

    def __init__(self, workspace: Path, interval_seconds: float = 0.02) -> None:
        self.workspace = workspace
        self.interval_seconds = interval_seconds
        self.baseline = file_manifest(workspace)
        self._previous = dict(self.baseline)
        self._events: list[MutationEvent] = []
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("observer already started")
        self._thread = threading.Thread(target=self._poll, name="cursor-eval-mutation-observer", daemon=True)
        self._thread.start()

    def _poll(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval_seconds)
        self._sample()

    def _sample(self) -> None:
        current = file_manifest(self.workspace)
        for path in sorted(set(self._previous) | set(current)):
            before = self._previous.get(path)
            after = current.get(path)
            before_hash = before["sha256"] if before else None
            after_hash = after["sha256"] if after else None
            if before_hash == after_hash and bool(before) == bool(after):
                continue
            action = "created" if before is None else "deleted" if after is None else "modified"
            with self._lock:
                self._events.append(
                    MutationEvent(
                        sequence=len(self._events) + 1,
                        timestamp=utc_now(),
                        path=path,
                        action=action,
                        before_exists=before is not None,
                        after_exists=after is not None,
                        before_hash=before_hash,
                        after_hash=after_hash,
                    )
                )
        self._previous = current

    def stop(self) -> dict[str, Any]:
        if self._thread is None:
            raise RuntimeError("observer has not started")
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_seconds * 20))
        if self._thread.is_alive():
            raise RuntimeError("observer thread did not stop")
        final = file_manifest(self.workspace)
        with self._lock:
            events = [asdict(event) for event in self._events]
        final_changed = sorted(
            path
            for path in set(self.baseline) | set(final)
            if self.baseline.get(path, {}).get("sha256") != final.get(path, {}).get("sha256")
        )
        touched = sorted({event["path"] for event in events})
        reverted = sorted(
            path for path in touched if self.baseline.get(path, {}).get("sha256") == final.get(path, {}).get("sha256")
        )
        created_then_deleted = sorted(
            path
            for path in touched
            if path not in self.baseline and path not in final
        )
        return {
            "baseline": self.baseline,
            "final": final,
            "events": events,
            "touched_paths": touched,
            "final_changed_paths": final_changed,
            "reverted_paths": reverted,
            "created_then_deleted_paths": created_then_deleted,
            "poll_interval_seconds": self.interval_seconds,
        }
