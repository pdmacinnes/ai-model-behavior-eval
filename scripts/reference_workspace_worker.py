"""Credential-free JSONL worker used only for the deterministic pilot smoke batch."""

from __future__ import annotations

import json
import sys


def _send(value: dict[str, object]) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


def main() -> int:
    task_line = sys.stdin.readline()
    if not task_line:
        return 1
    json.loads(task_line)

    _send(
        {
            "type": "call",
            "id": "evidence-1",
            "method": "request_evidence",
            "arguments": {"action": "search", "target": "return"},
        }
    )
    json.loads(sys.stdin.readline())

    _send(
        {
            "type": "call",
            "id": "checkpoint-1",
            "method": "record_checkpoint",
            "arguments": {
                "leading_hypothesis": "the implementation boundary needs more evidence",
                "alternative_hypothesis": "the visible symptom is caused by a different boundary",
                "confidence": 0.5,
                "changed_by": "generic smoke evidence",
                "next_action": "stop",
            },
        }
    )
    json.loads(sys.stdin.readline())

    _send(
        {
            "type": "call",
            "id": "stop-1",
            "method": "stop_investigation",
            "arguments": {"reason": "credential-free reference worker complete"},
        }
    )
    json.loads(sys.stdin.readline())
    _send(
        {
            "type": "final",
            "status": "completed",
            "final_response": "Credential-free reference worker completed.",
            "metadata": {"worker_kind": "deterministic_reference"},
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
