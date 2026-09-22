"""Deterministic primary-state and rerun calculations."""

from __future__ import annotations

import hashlib
import json
from typing import Any

PRECEDENCE = ("VALIDATION_FAILED", "SCHEMA_GAP", "VOCAB_GAP", "IDENTITY_AMBIGUOUS", "SOURCE_NOT_FOUND", "INSUFFICIENT_EVIDENCE", "NEEDS_REVIEW", "READY")
REQUIRED_VALIDATIONS = {"json_parse", "equipment_schema", "semantic_validation", "existing_tests", "compatibility_tests", "catalog_validation", "git_diff_check", "machine_audit"}


def _issue_state(issue: dict[str, Any]) -> str | None:
    code = issue.get("code", "")
    if code in {"VALIDATION_FAILED", "JSON_INVALID", "SCHEMA_INVALID", "SEMANTIC_INVALID", "TEST_FAILED", "CATALOG_INVALID", "AUDIT_FAILED"}:
        return "VALIDATION_FAILED"
    if code == "SCHEMA_GAP":
        return "SCHEMA_GAP"
    if code == "VOCAB_GAP":
        return "VOCAB_GAP"
    if code in {"IDENTITY_AMBIGUOUS", "IDENTITY_NOT_FOUND"}:
        return "IDENTITY_AMBIGUOUS"
    if code in {"SOURCE_NOT_FOUND", "ACQUISITION_FAILED"}:
        return "SOURCE_NOT_FOUND"
    if code in {"INSUFFICIENT_EVIDENCE", "EVIDENCE_MISSING"}:
        return "INSUFFICIENT_EVIDENCE"
    return "NEEDS_REVIEW" if issue else None


def _ready_stages(job: dict[str, Any]) -> bool:
    required = {"intake", "identity_resolution", "source_discovery", "source_acquisition", "source_classification", "fact_extraction", "evidence_normalization", "conflict_detection", "schema_vocabulary_mapping", "draft_generation", "structural_validation", "semantic_validation", "regression_validation", "machine_audit"}
    stages = job.get("stages", {})
    return required.issubset(stages) and all(stages[name] == "COMPLETED" for name in required)


def aggregate_state(job: dict[str, Any]) -> str:
    if any(result.get("passed") is False for result in job.get("validations", [])):
        return "VALIDATION_FAILED"
    states = {_issue_state(issue) for issue in job.get("issues", [])}
    states.discard(None)
    for state in PRECEDENCE:
        if state in states:
            return state
    if any(mapping.get("disposition") == "SCHEMA_GAP" for mapping in job.get("mappings", [])):
        return "SCHEMA_GAP"
    if any(mapping.get("disposition") == "VOCAB_GAP" for mapping in job.get("mappings", [])):
        return "VOCAB_GAP"
    if any(mapping.get("disposition") == "CONFLICT" for mapping in job.get("mappings", [])):
        return "NEEDS_REVIEW"
    facts = job.get("facts", [])
    fact_ids = [fact.get("fact_id") for fact in facts]
    evidence_ids = {evidence.get("evidence_id") for evidence in job.get("evidence", [])}
    source_ids = {source.get("source_id") for source in job.get("sources", [])}
    if not facts or len(fact_ids) != len(set(fact_ids)) or any(set(fact.get("evidence_refs", [])) - evidence_ids for fact in facts):
        return "NEEDS_REVIEW"
    if any(evidence.get("source_id") not in source_ids for evidence in job.get("evidence", [])):
        return "NEEDS_REVIEW"
    mappings = job.get("mappings", [])
    mapping_ids = [mapping.get("fact_id") for mapping in mappings]
    if set(mapping_ids) != set(fact_ids) or len(mapping_ids) != len(set(mapping_ids)):
        return "NEEDS_REVIEW"
    if job.get("pipeline_status") != "COMPLETED" or not _ready_stages(job) or not job.get("resolved_identity"):
        return "NEEDS_REVIEW"
    validations = {result.get("stage"): result for result in job.get("validations", [])}
    if set(validations) != REQUIRED_VALIDATIONS or not all(result.get("passed") is True for result in validations.values()):
        return "NEEDS_REVIEW"
    return "READY"


def _canonical(value: Any, *, sort_lists: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item, sort_lists=sort_lists) for key, item in sorted(value.items()) if key not in {"retrieved_at", "observed_at", "timestamp", "batch_index"}}
    if isinstance(value, list):
        items = [_canonical(item, sort_lists=sort_lists) for item in value]
        if sort_lists and all(isinstance(item, dict) for item in items):
            items.sort(key=lambda item: next((item[key] for key in ("source_id", "evidence_id", "fact_id", "issue_id", "stage") if key in item), ""))
        return items
    return value


def _digest(value: Any, *, sort_lists: bool = False) -> str:
    return hashlib.sha256(json.dumps(_canonical(value, sort_lists=sort_lists), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def compare_jobs(previous: dict[str, Any], current: dict[str, Any]) -> str:
    if any(_digest(previous.get(key)) != _digest(current.get(key)) for key in ("intake", "resolved_identity", "candidate")):
        return "REVIEW_REQUIRED"
    if _digest(previous.get("mappings", []), sort_lists=True) != _digest(current.get("mappings", []), sort_lists=True) or _digest(previous.get("issues", []), sort_lists=True) != _digest(current.get("issues", []), sort_lists=True) or _digest(previous.get("validations", []), sort_lists=True) != _digest(current.get("validations", []), sort_lists=True):
        return "REVIEW_REQUIRED"
    if _digest(previous.get("facts", []), sort_lists=True) != _digest(current.get("facts", []), sort_lists=True):
        return "FACTS_CHANGED"
    if _digest(previous.get("sources", []), sort_lists=True) != _digest(current.get("sources", []), sort_lists=True):
        return "SOURCE_UPDATED"
    return "NO_CHANGE"


def new_job(item: dict[str, Any]) -> dict[str, Any]:
    stages = {"intake": "COMPLETED", "identity_resolution": "BLOCKED", "source_discovery": "PENDING", "source_acquisition": "PENDING", "source_classification": "PENDING", "fact_extraction": "PENDING", "evidence_normalization": "PENDING", "conflict_detection": "PENDING", "schema_vocabulary_mapping": "PENDING", "draft_generation": "PENDING", "structural_validation": "PENDING", "semantic_validation": "PENDING", "regression_validation": "PENDING", "machine_audit": "PENDING", "decision": "PENDING", "publication": "SKIPPED"}
    return {"job_id": item["job_id"], "intake": item, "resolved_identity": None, "sources": [], "evidence": [], "facts": [], "mappings": [], "issues": [], "validations": [], "primary_state": "NEEDS_REVIEW", "rerun_status": None, "stages": stages, "candidate": None, "pipeline_status": "BLOCKED"}


def batch_summary(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {state: 0 for state in PRECEDENCE}
    for job in jobs:
        counts[aggregate_state(job)] += 1
    return {"total": len(jobs), "states": counts}
