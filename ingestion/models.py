"""Small, JSON-serializable models and shape validation for ingestion jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PRECISIONS = {"exact", "minimum", "maximum", "range", "approximate", "nominal", "not-rated", "unknown"}
POLARITIES = {"POSITIVE_EXPLICIT", "NEGATIVE_EXPLICIT", "UNKNOWN", "NOT_APPLICABLE"}
MAPPING_STATES = {"STRUCTURED", "NOTES_ONLY", "OMIT_UNKNOWN", "VOCAB_GAP", "SCHEMA_GAP", "CONFLICT"}
STAGE_STATES = {"PENDING", "RUNNING", "COMPLETED", "BLOCKED", "FAILED", "SKIPPED"}
PRIMARY_STATES = {"READY", "NEEDS_REVIEW", "VOCAB_GAP", "SCHEMA_GAP", "INSUFFICIENT_EVIDENCE", "SOURCE_NOT_FOUND", "IDENTITY_AMBIGUOUS", "VALIDATION_FAILED"}
RERUN_STATES = {"NO_CHANGE", "SOURCE_UPDATED", "FACTS_CHANGED", "REVIEW_REQUIRED"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _non_empty_string(value: Any, name: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{name} must be a non-empty string")


def validate_source(source: dict[str, Any]) -> None:
    _require(isinstance(source, dict), "source must be an object")
    for key in ("source_id", "source_type", "canonicality"):
        _non_empty_string(source.get(key), f"source.{key}")
    _require(source["source_type"] in {"html", "pdf", "text", "other"}, "source.source_type is invalid")
    _require(source.get("tier") in {1, 2, 3, 4}, "source.tier must be 1, 2, 3, or 4")
    _require(isinstance(source.get("metadata", {}), dict), "source.metadata must be an object")
    _require(bool(source.get("url") or source.get("path")), "source requires url or path")
    if "content_hash" in source:
        _non_empty_string(source["content_hash"], "source.content_hash")


def validate_evidence(evidence: dict[str, Any], source_ids: set[str] | None = None) -> None:
    _require(isinstance(evidence, dict), "evidence must be an object")
    _non_empty_string(evidence.get("evidence_id"), "evidence.evidence_id")
    _non_empty_string(evidence.get("source_id"), "evidence.source_id")
    if source_ids is not None:
        _require(evidence["source_id"] in source_ids, "evidence references an unknown source")
    _require(isinstance(evidence.get("locator"), dict), "evidence.locator must be an object")
    _require(bool(evidence["locator"]), "evidence.locator must not be empty")
    _non_empty_string(evidence.get("evidence_role"), "evidence.evidence_role")


def validate_fact(fact: dict[str, Any], evidence_ids: set[str] | None = None) -> None:
    _require(isinstance(fact, dict), "fact must be an object")
    _non_empty_string(fact.get("fact_id"), "fact.fact_id")
    subject = fact.get("subject")
    _require(isinstance(subject, dict), "fact.subject must be an object")
    _non_empty_string(subject.get("kind"), "fact.subject.kind")
    _non_empty_string(subject.get("local_id"), "fact.subject.local_id")
    _non_empty_string(fact.get("property"), "fact.property")
    _require(isinstance(fact.get("qualifiers", {}), dict), "fact.qualifiers must be an object")
    _require(isinstance(fact.get("conditions", []), list), "fact.conditions must be an array")
    _require(fact.get("semantic_precision") in PRECISIONS, "fact.semantic_precision is invalid")
    _require(fact.get("polarity") in POLARITIES, "fact.polarity is invalid")
    _require(isinstance(fact.get("evidence_refs"), list) and bool(fact["evidence_refs"]), "fact.evidence_refs is required")
    if evidence_ids is not None:
        _require(set(fact["evidence_refs"]).issubset(evidence_ids), "fact references unknown evidence")
    _non_empty_string(fact.get("extraction_method"), "fact.extraction_method")
    _non_empty_string(fact.get("evidence_status"), "fact.evidence_status")
    absent_value = fact["semantic_precision"] in {"unknown", "not-rated"} or fact["polarity"] in {"UNKNOWN", "NOT_APPLICABLE"}
    if absent_value:
        _require("value" not in fact and "unit" not in fact, "unknown or not-rated fact cannot carry value or unit")
        return
    _require("value" in fact, "supported fact requires value")
    if fact["semantic_precision"] in {"minimum", "maximum"}:
        _require(isinstance(fact["value"], (int, float)) and not isinstance(fact["value"], bool), "bounds require a numeric value")
    if fact["semantic_precision"] == "range":
        value = fact["value"]
        _require(isinstance(value, dict), "range requires minimum and maximum")
        _require(set(value) == {"minimum", "maximum"}, "range requires only minimum and maximum")
        _require(all(isinstance(value[key], (int, float)) and not isinstance(value[key], bool) for key in value), "range bounds must be numeric")
        _require(value["minimum"] <= value["maximum"], "range minimum cannot exceed maximum")
        _non_empty_string(fact.get("unit"), "range fact.unit")
    elif isinstance(fact["value"], (int, float)) and not isinstance(fact["value"], bool):
        _non_empty_string(fact.get("unit"), "numeric fact.unit")


def validate_mapping(mapping: dict[str, Any]) -> None:
    _require(isinstance(mapping, dict), "mapping must be an object")
    _non_empty_string(mapping.get("fact_id"), "mapping.fact_id")
    _require(mapping.get("disposition") in MAPPING_STATES, "mapping.disposition is invalid")


def validate_issue(issue: dict[str, Any]) -> None:
    _require(isinstance(issue, dict), "issue must be an object")
    for key in ("issue_id", "code", "severity", "stage", "message"):
        _non_empty_string(issue.get(key), f"issue.{key}")
    _require(isinstance(issue.get("blocking"), bool), "issue.blocking must be boolean")
    for key in ("subjects", "evidence_refs"):
        if key in issue:
            _require(isinstance(issue[key], list), f"issue.{key} must be an array")


@dataclass
class Job:
    job_id: str
    intake: dict[str, Any]
    stages: dict[str, str] = field(default_factory=dict)
    resolved_identity: dict[str, Any] | None = None
    sources: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    mappings: list[dict[str, Any]] = field(default_factory=list)
    issues: list[dict[str, Any]] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    primary_state: str = "NEEDS_REVIEW"
    rerun_status: str | None = None
    candidate: dict[str, Any] | None = None
    pipeline_status: str = "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {"job_id": self.job_id, "intake": self.intake, "resolved_identity": self.resolved_identity, "sources": self.sources, "evidence": self.evidence, "facts": self.facts, "mappings": self.mappings, "issues": self.issues, "validations": self.validations, "primary_state": self.primary_state, "rerun_status": self.rerun_status, "stages": self.stages, "candidate": self.candidate, "pipeline_status": self.pipeline_status}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Job":
        validate_job(value)
        return cls(**{key: value.get(key) for key in cls.__dataclass_fields__})


def validate_job(job: dict[str, Any]) -> None:
    _require(isinstance(job, dict), "job must be an object")
    _non_empty_string(job.get("job_id"), "job.job_id")
    _require(isinstance(job.get("intake"), dict), "job.intake must be an object")
    _require(isinstance(job.get("stages"), dict), "job.stages must be an object")
    for stage, status in job["stages"].items():
        _non_empty_string(stage, "stage name")
        _require(status in STAGE_STATES, f"invalid stage status: {status}")
    for key in ("sources", "evidence", "facts", "mappings", "issues", "validations"):
        _require(isinstance(job.get(key), list), f"job.{key} must be an array")
    for source in job["sources"]:
        validate_source(source)
    source_ids = {source["source_id"] for source in job["sources"]}
    _require(len(source_ids) == len(job["sources"]), "duplicate source_id")
    for evidence in job["evidence"]:
        validate_evidence(evidence, source_ids)
    evidence_ids = {evidence["evidence_id"] for evidence in job["evidence"]}
    _require(len(evidence_ids) == len(job["evidence"]), "duplicate evidence_id")
    for fact in job["facts"]:
        validate_fact(fact, evidence_ids)
    fact_ids = {fact["fact_id"] for fact in job["facts"]}
    _require(len(fact_ids) == len(job["facts"]), "duplicate fact_id")
    for mapping in job["mappings"]:
        validate_mapping(mapping)
    mapping_fact_ids = [mapping["fact_id"] for mapping in job["mappings"]]
    _require(set(mapping_fact_ids).issubset(fact_ids), "mapping references unknown fact")
    _require(len(mapping_fact_ids) == len(set(mapping_fact_ids)), "multiple mappings for one fact")
    _require(set(mapping_fact_ids) == fact_ids, "every fact requires exactly one mapping")
    for issue in job["issues"]:
        validate_issue(issue)
        _require(set(issue.get("evidence_refs", [])).issubset(evidence_ids), "issue references unknown evidence")
    _require(all(isinstance(result, dict) for result in job["validations"]), "validation result must be an object")
    _require(all(isinstance(result.get("passed"), bool) for result in job["validations"]), "validation result passed must be boolean")
    validation_stages = [result.get("stage") for result in job["validations"]]
    _require(all(isinstance(stage, str) and stage for stage in validation_stages), "validation result stage is required")
    _require(len(validation_stages) == len(set(validation_stages)), "duplicate validation stage")
    _require(job.get("primary_state") in PRIMARY_STATES, "job.primary_state is invalid")
    _require(job.get("pipeline_status") in {"PENDING", "RUNNING", "BLOCKED", "FAILED", "COMPLETED"}, "job.pipeline_status is invalid")
    if job.get("rerun_status") is not None:
        _require(job["rerun_status"] in RERUN_STATES, "job.rerun_status is invalid")
