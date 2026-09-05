from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _append_lock(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            handle.write("0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


class ReservationLedger:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.ledger = root / "reservations.jsonl"
        self.lock = root / "reservations.lock"
        self.root.mkdir(parents=True, exist_ok=True)

    def _records(self) -> list[dict[str, Any]]:
        if not self.ledger.exists():
            return []
        records = []
        for line in self.ledger.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def reserve(self, registration_id: str, case_id: str, model_id: str, repetition: int) -> dict[str, Any]:
        trial_key = f"{registration_id}:{case_id}:{model_id}:{repetition}"
        with _append_lock(self.lock):
            records = self._records()
            if any(record.get("trial_key") == trial_key for record in records):
                raise RuntimeError(f"trial slot already reserved or consumed: {trial_key}")
            reservation = {
                "record_type": "reservation",
                "reservation_id": str(uuid.uuid4()),
                "trial_key": trial_key,
                "registration_id": registration_id,
                "case_id": case_id,
                "model_id": model_id,
                "repetition": repetition,
                "state": "reserved",
                "timestamp": _timestamp(),
            }
            with self.ledger.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(reservation, sort_keys=True) + "\n")
            return reservation

    def consume(self, reservation_id: str, *, status: str, run_id: str) -> dict[str, Any]:
        if status not in {"behavioral", "infrastructure_censored"}:
            raise ValueError(f"invalid consumed status: {status}")
        with _append_lock(self.lock):
            records = self._records()
            matches = [record for record in records if record.get("reservation_id") == reservation_id]
            if len(matches) != 1:
                raise RuntimeError(f"unknown reservation: {reservation_id}")
            if matches[0].get("state") != "reserved":
                raise RuntimeError(f"reservation already consumed: {reservation_id}")
            consumed = {
                "record_type": "consumption",
                "reservation_id": reservation_id,
                "run_id": run_id,
                "state": "consumed",
                "outcome_class": status,
                "timestamp": _timestamp(),
            }
            with self.ledger.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(consumed, sort_keys=True) + "\n")
            return consumed
