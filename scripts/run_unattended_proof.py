from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_eval.runner import AgentResult, ModelCondition, run_unattended_trial
from evidence_eval.schema import load_case_family


def trace_first(target):
    def policy(task, tools):
        response = tools.request("trace", target)
        tools.checkpoint(
            leading_hypothesis="the trace will discriminate between the leading causes",
            alternative_hypothesis="the initial symptom is insufficient",
            confidence=0.5 if response.accepted else 0.1,
            changed_by="initial trace request",
            next_action="stop",
        )
        tools.stop("deterministic proof policy complete")
        return AgentResult(status="completed", final_response="Trace-first policy completed.")

    return policy


def inspect_first(target):
    def policy(task, tools):
        response = tools.request("inspect", target)
        tools.checkpoint(
            leading_hypothesis="the inspected implementation boundary is causal",
            alternative_hypothesis="the symptom originates elsewhere",
            confidence=0.7 if response.accepted else 0.1,
            changed_by="initial implementation inspection",
            next_action="stop",
        )
        tools.stop("deterministic proof policy complete")
        return AgentResult(status="completed", final_response="Inspect-first policy completed.")

    return policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic unattended evidence-policy proofs.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("results") / "unattended-proof",
        help="directory for immutable proof artifacts",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    summaries = []
    trace_targets = {
        "dashboard-filter-refresh": "metrics-request",
        "session-refresh-role": "role-transition",
        "pagination-offset": "pagination-request",
    }
    inspect_targets = {
        "dashboard-filter-refresh": "lib/fetchMetrics.ts",
        "session-refresh-role": "lib/session.ts",
        "pagination-offset": "app/orders/page.tsx",
    }
    for path in sorted((root / "behavior_cases").glob("*/family.json")):
        family = load_case_family(path)
        for variant in family.variants:
            policies = (
                ("trace-first", trace_first(trace_targets[family.family_id])),
                ("inspect-first", inspect_first(inspect_targets[family.family_id])),
            )
            for policy_name, policy in policies:
                condition = ModelCondition(
                    provider="deterministic",
                    model_id=policy_name,
                    adapter_id="unattended-proof",
                    prompt=family.initial_context["prompt"],
                )
                record = run_unattended_trial(
                    family,
                    variant,
                    condition,
                    policy,
                    artifacts_root=args.output_root,
                    run_id=f"{policy_name}-{family.family_id}-{variant.variant_id}",
                )
                annotations = record["behavioral_annotations"]
                summaries.append(
                    {
                        "family_id": family.family_id,
                        "variant_id": variant.variant_id,
                        "policy": policy_name,
                        "first_action": annotations["first_action"],
                        "first_target": annotations["first_target"],
                        "rejected_action_count": annotations["rejected_action_count"],
                    }
                )
    print(json.dumps(summaries, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
