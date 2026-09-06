from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from evidence_eval.pilot import PilotCondition, PilotRegistration, run_pilot_batch


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Run one paired-family mock provider smoke batch.")
    parser.add_argument("--batch-id", default="provider-worker-mock-v1")
    parser.add_argument("--output-root", type=Path, default=root / "results" / "provider-worker-mock")
    args = parser.parse_args()
    registration = PilotRegistration(
        batch_id=args.batch_id,
        harness_version="0.1.0",
        case_root=root / "behavior_cases",
        family_ids=("dashboard-filter-refresh",),
        variant_ids={},
        repetitions=1,
        trial_timeout_seconds=10.0,
        artifacts_root=args.output_root,
        workspace_parent=args.output_root / "workspaces",
        conditions=(
            PilotCondition(
                condition_id="mock-provider",
                provider="mock-provider",
                model_id="mock-model",
                adapter_id="jsonl-provider-worker",
                command=(sys.executable, str(root / "scripts" / "openai_compatible_workspace_worker.py"), "--transport", "mock"),
                reasoning_effort=None,
                network_required=False,
                timeout_seconds=5.0,
            ),
        ),
    )
    print(json.dumps(run_pilot_batch(registration), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
