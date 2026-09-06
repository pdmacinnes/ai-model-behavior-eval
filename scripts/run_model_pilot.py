from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_eval.pilot import load_pilot_registration, run_pilot_batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a registered unattended model pilot batch.")
    parser.add_argument("--registration", type=Path, required=True)
    args = parser.parse_args()
    manifest = run_pilot_batch(load_pilot_registration(args.registration))
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
