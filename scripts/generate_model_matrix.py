from __future__ import annotations

import argparse
from pathlib import Path

from evidence_eval.model_matrix import load_model_matrix, write_provider_registrations


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Generate provider-specific model matrix registrations.")
    parser.add_argument(
        "--matrix",
        type=Path,
        default=project_root / "configs" / "model_matrix.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=project_root / "results" / "model-matrix" / "registrations",
    )
    parser.add_argument("--project-root", type=Path, default=project_root)
    parser.add_argument("--python-executable", type=Path, default=None)
    args = parser.parse_args()

    matrix = load_model_matrix(args.matrix.resolve())
    paths = write_provider_registrations(
        matrix,
        args.output_dir,
        project_root=args.project_root,
        python_executable=args.python_executable,
    )
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
