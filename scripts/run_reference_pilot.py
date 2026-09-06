from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidence_eval.pilot import PilotCondition, PilotRegistration, run_pilot_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the credential-free deterministic model pilot smoke batch.")
    parser.add_argument("--batch-id", default="reference-smoke-v1")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--output-root", type=Path, default=Path("results") / "reference-pilot")
    parser.add_argument("--workspace-parent", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    output_root = args.output_root.resolve()
    registration = PilotRegistration(
        batch_id=args.batch_id,
        harness_version="0.1.0",
        case_root=root / "behavior_cases",
        family_ids=("dashboard-filter-refresh", "session-refresh-role", "pagination-offset"),
        variant_ids={},
        repetitions=args.repetitions,
        trial_timeout_seconds=10.0,
        artifacts_root=output_root,
        workspace_parent=(args.workspace_parent or output_root / "workspaces").resolve(),
        conditions=(
            PilotCondition(
                condition_id="reference-worker",
                provider="deterministic",
                model_id="reference-worker",
                adapter_id="jsonl-reference-worker",
                command=(sys.executable, str(root / "scripts" / "reference_workspace_worker.py")),
                reasoning_effort=None,
                network_required=False,
                timeout_seconds=5.0,
            ),
        ),
    )
    manifest = run_pilot_batch(registration)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
