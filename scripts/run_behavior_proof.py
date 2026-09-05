from __future__ import annotations

import json
from pathlib import Path

from evidence_eval.analysis import analyze_trace, compare_variants
from evidence_eval.protocol import EvidenceSession
from evidence_eval.schema import load_case_family


def discriminating_policy(session: EvidenceSession) -> dict:
    session.request("trace", "metrics-request")
    session.checkpoint(
        leading_hypothesis="query propagation or cache key behavior",
        alternative_hypothesis="stale client props",
        confidence=0.5,
        changed_by="initial evidence",
        next_action="inspect the component boundary",
    )
    session.stop("enough evidence for a case report")
    return session.to_record()


def framework_prior_policy(session: EvidenceSession) -> dict:
    session.request("inspect", "lib/fetchMetrics.ts")
    session.checkpoint(
        leading_hypothesis="cache behavior",
        alternative_hypothesis="query propagation",
        confidence=0.8,
        changed_by="familiar framework pattern",
        next_action="inspect cache helper",
    )
    session.stop("committed to first familiar explanation")
    return session.to_record()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    family = load_case_family(root / "behavior_cases" / "dashboard-filter-refresh" / "family.json")
    reports = []
    for policy_name, policy in (("discriminating", discriminating_policy), ("framework_prior", framework_prior_policy)):
        traces = []
        for variant in family.variants:
            traces.append(analyze_trace(policy(EvidenceSession(family, variant))))
        reports.append({
            "policy": policy_name,
            "variant_observations": traces,
            "variant_comparison": compare_variants(traces[0], traces[1]),
        })
    print(json.dumps(reports, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
