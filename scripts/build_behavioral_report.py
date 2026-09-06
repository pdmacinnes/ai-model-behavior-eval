from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_eval.behavior_report import build_behavior_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a public-safe behavioral report from completed run artifacts.")
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--artifacts-root", type=Path)
    sources.add_argument("--public-root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verbose", action="store_true", help="print the complete report after writing it")
    args = parser.parse_args()

    source_root = args.public_root or args.artifacts_root
    source_kind = "public_release" if args.public_root else "internal_artifacts"
    report = build_behavior_report(source_root, source_kind=source_kind)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    if args.verbose:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        censored_count = sum(1 for run in report["runs"] if run.get("infrastructure_censored") is True)
        print(
            "source_kind={source_kind} runs={runs} profiles={profiles} comparisons={comparisons} "
            "censored={censored} output={output}".format(
                source_kind=source_kind,
                runs=len(report["runs"]),
                profiles=len(report["profiles"]),
                comparisons=len(report["comparisons"]),
                censored=censored_count,
                output=args.output,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
