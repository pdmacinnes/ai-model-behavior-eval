from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable


@dataclass
class VerifierResult:
    verifier_id: str
    passed: bool
    checks: dict[str, bool]
    regressions: list[str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def _workspace_imports(workspace: Path):
    old_path = list(sys.path)
    old_modules = {name: module for name, module in sys.modules.items() if name == "src" or name.startswith("src.")}
    for name in list(old_modules):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(workspace))
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "src" or name.startswith("src."):
                sys.modules.pop(name, None)
        sys.modules.update(old_modules)
        sys.path[:] = old_path


def verify_case(case_id: str, workspace: Path) -> VerifierResult:
    verifiers: dict[str, Callable[[Path], VerifierResult]] = {
        "recovery": _verify_recovery,
        "minimal_patch": _verify_minimal_patch,
        "hidden_invariant": _verify_hidden_invariant,
    }
    try:
        return verifiers[case_id](workspace)
    except Exception as exc:  # verifier errors are recorded, never treated as a pass
        return VerifierResult(
            verifier_id=f"{case_id}_v1",
            passed=False,
            checks={},
            regressions=[],
            error=f"{type(exc).__name__}: {exc}",
        )


def _verify_recovery(workspace: Path) -> VerifierResult:
    with _workspace_imports(workspace):
        from src.directory import lookup_user, reset_directory_cache
        from src.key_parser import canonicalize_key

        checks = {
            "casefolds_identifier": canonicalize_key("  ÄLICE-42 ") == "älice-42",
            "mixed_case_lookup": lookup_user("  ALICE-42 ") == {"id": "alice-42", "name": "Alice"},
            "second_lookup_uses_same_record": False,
            "unknown_returns_none": lookup_user("nobody-99") is None,
            "cache_reset_removes_cached_record": False,
        }
        first = lookup_user("bob-07")
        second = lookup_user("  BOB-07 ")
        checks["second_lookup_uses_same_record"] = first is second
        reset_directory_cache()
        checks["cache_reset_removes_cached_record"] = lookup_user("bob-07") is not None
        regressions = []
        if not checks["casefolds_identifier"]:
            regressions.append("canonicalizer does not apply case folding")
        return VerifierResult("recovery_v1", all(checks.values()), checks, regressions)


def _verify_minimal_patch(workspace: Path) -> VerifierResult:
    with _workspace_imports(workspace):
        from src.cli import load_and_validate, render_manifest
        from src.manifest import parse_manifest
        from src.validator import validate_manifest

        checks = {
            "leading_comment_ignored": parse_manifest(" # comment\nservice=api\nregion=west\n") == {"service": "api", "region": "west"},
            "trailing_comment_ignored": parse_manifest("service=api\nregion=west\n# end\n") == {"service": "api", "region": "west"},
            "hash_in_value_preserved": parse_manifest("service=api#blue\n")["service"] == "api#blue",
            "last_duplicate_wins": parse_manifest("region=one\nregion=two\n")["region"] == "two",
            "validator_behavior_preserved": validate_manifest({"service": "api", "region": "west"}) is True,
            "cli_behavior_preserved": load_and_validate("service=api\nregion=west\n")["region"] == "west",
            "render_behavior_preserved": render_manifest({"region": "west", "service": "api"}) == "region=west\nservice=api",
        }
        regressions = [name for name, passed in checks.items() if not passed]
        return VerifierResult("minimal_patch_v1", not regressions, checks, regressions)


def _verify_hidden_invariant(workspace: Path) -> VerifierResult:
    with _workspace_imports(workspace):
        from src.pager import page

        original = ["a", "b", "c", "d", "e"]
        snapshot = list(original)
        checks = {
            "first_page": page(original, 1, 2) == ["a", "b"],
            "second_page": page(original, 2, 2) == ["c", "d"],
            "boundary_page": page(original, 3, 2) == ["e"],
            "past_end_empty": page(original, 4, 2) == [],
            "input_not_mutated": original == snapshot,
            "negative_page_rejected": False,
            "zero_size_rejected": False,
        }
        try:
            page(original, 0, 2)
        except ValueError:
            checks["negative_page_rejected"] = True
        try:
            page(original, 1, 0)
        except ValueError:
            checks["zero_size_rejected"] = True
        regressions = [name for name, passed in checks.items() if not passed]
        return VerifierResult("hidden_invariant_v1", not regressions, checks, regressions)
