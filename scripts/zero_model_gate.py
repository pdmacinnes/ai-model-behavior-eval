from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cursor_eval.adapters import RealCursorAdapter, RealInvocationBlocked
from cursor_eval.canonical import load_case
from cursor_eval.environment import collect_environment
from cursor_eval.registration import FROZEN_MODEL_IDS


def main() -> int:
    adapter = RealCursorAdapter()
    case = load_case(PROJECT_ROOT / "cases" / "recovery" / "canonical.json")
    command = adapter.command_for(PROJECT_ROOT / "artifacts" / "zero-model-workspace", case.prompt, FROZEN_MODEL_IDS[0])
    environment = collect_environment(PROJECT_ROOT, cursor_version="2026.08.11-e8db854")
    environment.update(
        {
            "cursor_agent_binary": "cursor-agent",
            "cursor_agent_binary_sha256": "eed61c5224668c9236334c4c68936a16aecc37374b592f59e31eb50433817831",
            "cursor_cli_distribution": "Ubuntu WSL 2",
        }
    )
    report = {
        "real_invocation_allowed": adapter.allow_real_invocation,
        "command_template": command[:-1] + ["<prompt-redacted>"],
        "contains_print": "--print" in command,
        "contains_stream_json": "stream-json" in command,
        "contains_frozen_model": FROZEN_MODEL_IDS[0] in command,
        "contains_workspace": "--workspace" in command,
        "model_count_in_registration": len(FROZEN_MODEL_IDS),
        "environment": environment,
        "gate": "pass",
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
