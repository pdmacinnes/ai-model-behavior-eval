"""Entry point for the gated OpenAI-compatible JSONL provider worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evidence_eval.provider_worker import main


if __name__ == "__main__":
    raise SystemExit(main())
