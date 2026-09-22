"""Batch job creation and runtime artifact handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .intake import parse_csv, parse_json
from .state import aggregate_state, batch_summary, compare_jobs, new_job


def jobs_root(root: Path) -> Path:
    return root / ".ingestion" / "jobs"


def write_job(job: dict[str, Any], root: Path) -> Path:
    path = jobs_root(root) / f"{job['job_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(job, indent=2, sort_keys=True) + "\n")
    return path


def read_job(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def run_batch(input_path: Path, fmt: str, root: Path) -> dict[str, Any]:
    items = parse_json(input_path) if fmt == "json" else parse_csv(input_path)
    jobs = [new_job(item) for item in items]
    for job in jobs:
        job["primary_state"] = aggregate_state(job)
        write_job(job, root)
    return {"jobs": jobs, "summary": batch_summary(jobs)}


def resume_job(previous_path: Path, current_path: Path, root: Path) -> dict[str, Any]:
    previous = read_job(previous_path)
    current = read_job(current_path)
    current["rerun_status"] = compare_jobs(previous, current)
    current["primary_state"] = aggregate_state(current)
    write_job(current, root)
    return current


def publication_allowed(job: dict[str, Any]) -> bool:
    """Return eligibility only; this function deliberately performs no git action."""
    from .models import validate_job

    try:
        validate_job(job)
    except ValueError:
        return False
    return aggregate_state(job) == "READY"
