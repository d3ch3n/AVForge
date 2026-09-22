"""Validation orchestration without duplicating AVForge validation rules."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]


def _result(stage: str, passed: bool, exit_status: int = 0, command: list[str] | None = None, summary: Any = None, output: str = "") -> dict[str, Any]:
    return {"stage": stage, "passed": passed, "exit_status": exit_status, "command": command or [], "summary": summary, "output": output}


def validate_json_files(paths: Iterable[Path]) -> dict[str, Any]:
    errors = []
    for path in paths:
        try:
            json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            errors.append({"path": str(path), "message": str(exc)})
    return _result("json_parse", not errors, 0 if not errors else 1, summary={"errors": errors})


def run_command(stage: str, command: list[str], cwd: Path = ROOT) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as exc:
        return _result(stage, False, 127, command, summary={"error": str(exc)})
    return _result(stage, completed.returncode == 0, completed.returncode, command, output=completed.stdout + completed.stderr)


def run_repository_validation(candidate_paths: Iterable[Path] = (), run_tests: bool = True) -> list[dict[str, Any]]:
    paths = list(candidate_paths)
    results = [validate_json_files(paths)]
    if paths:
        try:
            import jsonschema
            schema = json.loads((ROOT / "schemas/equipment.schema.json").read_text())
            validator = jsonschema.Draft202012Validator(schema)
            errors = []
            for path in paths:
                record = json.loads(path.read_text())
                errors.extend({"path": str(path), "message": error.message} for error in validator.iter_errors(record))
            results.append(_result("equipment_schema", not errors, 0 if not errors else 1, summary={"errors": errors}))
        except Exception as exc:
            results.append(_result("equipment_schema", False, 1, summary={"error": str(exc)}))
        try:
            from validator.validate_semantics import validate_records

            semantic = validate_records([json.loads(path.read_text()) for path in paths])
            results.append(_result("semantic_validation", semantic["valid"], 0 if semantic["valid"] else 1, summary=semantic))
        except Exception as exc:
            results.append(_result("semantic_validation", False, 1, summary={"error": str(exc)}))
    if run_tests:
        results.append(run_command("existing_tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests"]))
        results.append(run_command("compatibility_tests", [sys.executable, "-m", "unittest", "discover", "-s", "compatibility", "-p", "test_*.py"]))
    catalog_paths = sorted((ROOT / "equipment").rglob("*.json"))
    results.append(run_command("catalog_validation", [sys.executable, "validator/validate_semantics.py", *[str(path) for path in catalog_paths]]))
    results.append(run_command("git_diff_check", ["git", "diff", "--check"]))
    candidate_strings = [str(path) for path in paths]
    duplicate_paths = len(candidate_strings) != len(set(candidate_strings))
    results.append(_result("machine_audit", not duplicate_paths, 0 if not duplicate_paths else 1, summary={"candidate_count": len(paths), "duplicate_paths": duplicate_paths}))
    return results
