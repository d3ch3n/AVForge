"""Deterministic AVForge catalog-ingestion core."""

from .intake import IntakeError, parse_csv, parse_json
from .models import Job, validate_evidence, validate_fact, validate_job, validate_source
from .state import aggregate_state, compare_jobs
from .source_pipeline import compare_manifests, run_source_pipeline
from .manufacturer_registry import ManufacturerRegistry

__all__ = [
    "IntakeError",
    "Job",
    "aggregate_state",
    "compare_jobs",
    "compare_manifests",
    "ManufacturerRegistry",
    "parse_csv",
    "parse_json",
    "run_source_pipeline",
    "validate_evidence",
    "validate_fact",
    "validate_job",
    "validate_source",
]
