"""Deterministic AVForge catalog-ingestion core."""

from .intake import IntakeError, parse_csv, parse_json
from .models import Job, validate_evidence, validate_fact, validate_job, validate_source
from .state import aggregate_state, compare_jobs
from .source_pipeline import compare_manifests, run_source_pipeline
from .manufacturer_registry import ManufacturerRegistry
from .extraction import build_extraction_result, compare_extractions, make_conflict, make_evidence, make_fact, validate_extraction, write_extraction

__all__ = [
    "IntakeError",
    "Job",
    "aggregate_state",
    "compare_jobs",
    "compare_manifests",
    "ManufacturerRegistry",
    "build_extraction_result",
    "compare_extractions",
    "make_conflict",
    "make_evidence",
    "make_fact",
    "validate_extraction",
    "write_extraction",
    "parse_csv",
    "parse_json",
    "run_source_pipeline",
    "validate_evidence",
    "validate_fact",
    "validate_job",
    "validate_source",
]
