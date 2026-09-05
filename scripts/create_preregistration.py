from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cursor_eval.registration import build_registration
from cursor_eval.artifacts import write_once


def main() -> int:
    destination = PROJECT_ROOT / "registrations" / "v1.json"
    if destination.exists():
        raise SystemExit(f"refusing to overwrite existing preregistration: {destination}")
    registration = build_registration(PROJECT_ROOT, registration_date="2026-08-16")
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(registration, indent=2, sort_keys=True) + "\n"
    write_once(destination, payload)
    print(destination)
    print(json.dumps({
        "trial_count": registration["trial_count"],
        "status": registration["status"],
        "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
