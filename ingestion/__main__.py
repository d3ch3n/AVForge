"""Minimal command line interface for deterministic ingestion jobs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import validate_job
from .runner import jobs_root, read_job, run_batch
from .state import batch_summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)
    intake = subparsers.add_parser("intake", help="create paused jobs from JSON or CSV")
    intake.add_argument("input", type=Path)
    intake.add_argument("--format", choices=("json", "csv"), required=True)
    intake.add_argument("--root", type=Path, default=Path.cwd())
    status = subparsers.add_parser("status", help="validate and print one job")
    status.add_argument("job", type=Path)
    summary = subparsers.add_parser("summary", help="summarize runtime jobs")
    summary.add_argument("--root", type=Path, default=Path.cwd())
    validate = subparsers.add_parser("validate", help="validate one serialized job")
    validate.add_argument("job", type=Path)
    args = parser.parse_args(argv)
    if args.command == "intake":
        result = run_batch(args.input, args.format, args.root)
        print(json.dumps(result["summary"], indent=2, sort_keys=True))
        return 0
    if args.command == "status":
        job = read_job(args.job)
        validate_job(job)
        print(json.dumps(job, indent=2, sort_keys=True))
        return 0
    if args.command == "validate":
        validate_job(read_job(args.job))
        print("valid")
        return 0
    paths = sorted(jobs_root(args.root).glob("job-*.json"))
    jobs = [read_job(path) for path in paths]
    print(json.dumps(batch_summary(jobs), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
