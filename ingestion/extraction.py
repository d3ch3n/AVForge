"""Deterministic Fact Extraction v1 intermediate layer.

This module represents extracted evidence and facts only. It does not parse
documents, map schema fields, generate equipment records, or execute source
content. Acquired source metadata is supplied by the source pipeline.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .models import POLARITIES, PRECISIONS


EXTRACTION_VERSION = "1.0"
EVIDENCE_STATUSES = {"SUPPORTED", "UNKNOWN", "NOT_APPLICABLE", "REVIEW_REQUIRED"}
CONFLICT_RELATIONSHIPS = {
    "TRUE_CONFLICT",
    "TERMINOLOGY_DIFFERENCE",
    "PRECISION_DIFFERENCE",
    "CONTEXT_DIFFERENCE",
    "REVISION_DIFFERENCE",
    "UNKNOWN_RELATIONSHIP",
}
CONFLICT_STATUSES = {"UNRESOLVED", "REVIEW_REQUIRED", "RESOLVED"}
_MISSING = object()


def _canonical(value: Any, *, unordered_lists: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item, unordered_lists=unordered_lists) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = [_canonical(item, unordered_lists=unordered_lists) for item in value]
        if unordered_lists:
            items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return items
    return value


def _json_digest(value: Any, prefix: str) -> str:
    payload = json.dumps(_canonical(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return prefix + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _non_empty(value: Any, name: str) -> None:
    _require(isinstance(value, str) and bool(value.strip()), f"{name} must be a non-empty string")


def _json_value(value: Any, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON serializable") from exc


def _fact_identity_payload(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": _canonical(fact["subject"], unordered_lists=True),
        "property": fact["property"],
        "value": fact.get("value", _MISSING) if fact.get("value", _MISSING) is not _MISSING else {"absent": True},
        "unit": fact.get("unit"),
        "qualifiers": _canonical(fact.get("qualifiers", {}), unordered_lists=True),
        "semantic_precision": fact["semantic_precision"],
        "polarity": fact["polarity"],
        "evidence_status": fact["evidence_status"],
    }


def _fact_logical_payload(fact: dict[str, Any]) -> dict[str, Any]:
    payload = _fact_identity_payload(fact)
    for key in ("value", "unit", "semantic_precision", "polarity"):
        payload.pop(key, None)
    return payload


def make_fact(
    *,
    subject: dict[str, Any],
    property: str,
    value: Any = _MISSING,
    unit: str | None = None,
    qualifiers: dict[str, Any] | None = None,
    evidence_ids: Iterable[str] = (),
    extraction_method: str = "deterministic_parser",
    evidence_status: str = "SUPPORTED",
    semantic_precision: str = "exact",
    polarity: str = "POSITIVE_EXPLICIT",
) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "subject": _canonical(subject, unordered_lists=True),
        "property": property,
        "qualifiers": _canonical(qualifiers or {}, unordered_lists=True),
        "evidence_ids": sorted(set(evidence_ids)),
        "extraction_method": extraction_method,
        "evidence_status": evidence_status,
        "semantic_precision": semantic_precision,
        "polarity": polarity,
    }
    if value is not _MISSING:
        fact["value"] = value
    if unit is not None:
        fact["unit"] = unit
    fact["fact_id"] = _json_digest(_fact_identity_payload(fact), "fact-")
    validate_fact_record(fact)
    return fact


def make_evidence(
    *,
    source: dict[str, Any],
    locator: dict[str, Any],
    observation: Any,
    extraction_method: str,
) -> dict[str, Any]:
    _non_empty(source.get("source_id"), "source.source_id")
    _non_empty(source.get("content_hash"), "source.content_hash")
    _require(isinstance(locator, dict) and bool(locator), "evidence.locator must be a non-empty object")
    _json_value(observation, "evidence.observation")
    _non_empty(extraction_method, "evidence.extraction_method")
    evidence = {
        "source_id": source["source_id"],
        "source_sha256": source["content_hash"],
        "locator": _canonical(locator, unordered_lists=True),
        "extracted_text_or_normalized_observation": observation,
        "extraction_method": extraction_method,
    }
    evidence["evidence_id"] = _json_digest(evidence, "evidence-")
    validate_evidence_record(evidence, {source["source_id"]: source})
    return evidence


def make_conflict(
    *,
    fact_ids: Iterable[str],
    evidence_ids: Iterable[str],
    relationship: str,
    explanation: str,
    resolution_status: str = "UNRESOLVED",
) -> dict[str, Any]:
    record = {
        "fact_ids": sorted(set(fact_ids)),
        "evidence_ids": sorted(set(evidence_ids)),
        "relationship": relationship,
        "explanation": explanation,
        "resolution_status": resolution_status,
    }
    record["conflict_id"] = _json_digest({key: record[key] for key in ("fact_ids", "evidence_ids", "relationship")}, "conflict-")
    validate_conflict_record(record, set(record["fact_ids"]), set(record["evidence_ids"]))
    return record


def validate_fact_record(fact: dict[str, Any]) -> None:
    _require(isinstance(fact, dict), "fact must be an object")
    _non_empty(fact.get("fact_id"), "fact.fact_id")
    subject = fact.get("subject")
    _require(isinstance(subject, dict) and bool(subject), "fact.subject must be a non-empty object")
    _non_empty(subject.get("kind"), "fact.subject.kind")
    _non_empty(subject.get("local_id"), "fact.subject.local_id")
    _non_empty(fact.get("property"), "fact.property")
    _require(isinstance(fact.get("qualifiers"), dict), "fact.qualifiers must be an object")
    _require(isinstance(fact.get("evidence_ids"), list) and bool(fact["evidence_ids"]), "fact.evidence_ids is required")
    _require(all(isinstance(value, str) and value for value in fact["evidence_ids"]), "fact.evidence_ids must contain IDs")
    _non_empty(fact.get("extraction_method"), "fact.extraction_method")
    _require(fact.get("evidence_status") in EVIDENCE_STATUSES, "fact.evidence_status is invalid")
    _require(fact.get("semantic_precision") in PRECISIONS, "fact.semantic_precision is invalid")
    _require(fact.get("polarity") in POLARITIES, "fact.polarity is invalid")
    _json_value(fact.get("subject"), "fact.subject")
    _json_value(fact.get("qualifiers"), "fact.qualifiers")
    if fact["semantic_precision"] in {"unknown", "not-rated"} or fact["polarity"] in {"UNKNOWN", "NOT_APPLICABLE"}:
        _require("value" not in fact and "unit" not in fact, "unknown or not-rated facts cannot carry value or unit")
    else:
        _require("value" in fact, "supported fact requires value")
        _json_value(fact["value"], "fact.value")
        if isinstance(fact["value"], (int, float)) and not isinstance(fact["value"], bool):
            _non_empty(fact.get("unit"), "numeric fact.unit")
        if fact["semantic_precision"] in {"minimum", "maximum"}:
            _require(isinstance(fact["value"], (int, float)) and not isinstance(fact["value"], bool), "bounds require numeric values")
        if fact["semantic_precision"] == "range":
            value = fact["value"]
            _require(isinstance(value, dict) and set(value) == {"minimum", "maximum"}, "range requires minimum and maximum")
            _require(all(isinstance(value[key], (int, float)) and not isinstance(value[key], bool) for key in value), "range bounds must be numeric")
            _require(value["minimum"] <= value["maximum"], "range minimum cannot exceed maximum")
            _non_empty(fact.get("unit"), "range fact.unit")


def validate_evidence_record(evidence: dict[str, Any], sources: dict[str, dict[str, Any]]) -> None:
    _require(isinstance(evidence, dict), "evidence must be an object")
    _non_empty(evidence.get("evidence_id"), "evidence.evidence_id")
    source_id = evidence.get("source_id")
    _require(source_id in sources, "evidence references an unknown source")
    _require(evidence.get("source_sha256") == sources[source_id].get("content_hash"), "evidence source hash does not match source")
    _require(isinstance(evidence.get("locator"), dict) and bool(evidence["locator"]), "evidence.locator must be a non-empty object")
    _json_value(evidence.get("extracted_text_or_normalized_observation"), "evidence.observation")
    _non_empty(evidence.get("extraction_method"), "evidence.extraction_method")


def validate_conflict_record(conflict: dict[str, Any], fact_ids: set[str], evidence_ids: set[str]) -> None:
    _non_empty(conflict.get("conflict_id"), "conflict.conflict_id")
    _require(isinstance(conflict.get("fact_ids"), list) and bool(conflict["fact_ids"]), "conflict.fact_ids is required")
    _require(set(conflict["fact_ids"]).issubset(fact_ids), "conflict references an unknown fact")
    _require(isinstance(conflict.get("evidence_ids"), list) and set(conflict["evidence_ids"]).issubset(evidence_ids), "conflict references unknown evidence")
    _require(conflict.get("relationship") in CONFLICT_RELATIONSHIPS, "conflict.relationship is invalid")
    _non_empty(conflict.get("explanation"), "conflict.explanation")
    _require(conflict.get("resolution_status") in CONFLICT_STATUSES, "conflict.resolution_status is invalid")


def merge_facts(facts: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for fact in facts:
        validate_fact_record(fact)
        current = merged.setdefault(fact["fact_id"], json.loads(json.dumps(fact)))
        if current is not fact:
            _require(_fact_identity_payload(current) == _fact_identity_payload(fact), "same fact_id has different logical content")
            current["evidence_ids"] = sorted(set(current["evidence_ids"]) | set(fact["evidence_ids"]))
    return [merged[key] for key in sorted(merged)]


def build_extraction_result(
    *,
    job_id: str,
    identity: dict[str, Any],
    sources: Iterable[dict[str, Any]],
    facts: Iterable[dict[str, Any]] = (),
    evidence: Iterable[dict[str, Any]] = (),
    conflicts: Iterable[dict[str, Any]] = (),
    issues: Iterable[dict[str, Any]] = (),
    extraction_status: str = "COMPLETED",
    observed_at: str | None = None,
) -> dict[str, Any]:
    evidence_by_id = {item["evidence_id"]: json.loads(json.dumps(item)) for item in evidence}
    conflict_by_id = {item["conflict_id"]: json.loads(json.dumps(item)) for item in conflicts}
    result = {
        "extraction_version": EXTRACTION_VERSION,
        "job_id": job_id,
        "identity": _canonical(identity),
        "sources": sorted([json.loads(json.dumps(source)) for source in sources], key=lambda source: source.get("source_id", "")),
        "facts": merge_facts(facts),
        "evidence": [evidence_by_id[key] for key in sorted(evidence_by_id)],
        "conflicts": [conflict_by_id[key] for key in sorted(conflict_by_id)],
        "issues": sorted([json.loads(json.dumps(issue)) for issue in issues], key=lambda issue: json.dumps(issue, sort_keys=True)),
        "extraction_status": extraction_status,
        "generated_at": observed_at or datetime.now(timezone.utc).isoformat(),
    }
    validate_extraction(result)
    result["semantic_hash"] = _json_digest(_semantic_result(result), "sha256:")
    return result


def validate_extraction(result: dict[str, Any]) -> None:
    _require(isinstance(result, dict), "extraction result must be an object")
    _non_empty(result.get("extraction_version"), "extraction_version")
    _non_empty(result.get("job_id"), "job_id")
    _require(isinstance(result.get("identity"), dict), "identity must be an object")
    sources = result.get("sources")
    _require(isinstance(sources, list), "sources must be an array")
    source_map = {source.get("source_id"): source for source in sources}
    _require(None not in source_map and len(source_map) == len(sources), "source IDs must be unique")
    for source in sources:
        _non_empty(source.get("source_id"), "source.source_id")
        _non_empty(source.get("content_hash"), "source.content_hash")
    facts = result.get("facts")
    _require(isinstance(facts, list), "facts must be an array")
    fact_ids = {fact.get("fact_id") for fact in facts}
    _require(None not in fact_ids and len(fact_ids) == len(facts), "fact IDs must be unique")
    for fact in facts:
        validate_fact_record(fact)
        _require(set(fact["evidence_ids"]).issubset({item.get("evidence_id") for item in result.get("evidence", [])}), "fact references unknown evidence")
    evidence = result.get("evidence")
    _require(isinstance(evidence, list), "evidence must be an array")
    evidence_ids = {item.get("evidence_id") for item in evidence}
    _require(None not in evidence_ids and len(evidence_ids) == len(evidence), "evidence IDs must be unique")
    for item in evidence:
        validate_evidence_record(item, source_map)
    conflicts = result.get("conflicts")
    _require(isinstance(conflicts, list), "conflicts must be an array")
    conflict_ids = {item.get("conflict_id") for item in conflicts}
    _require(None not in conflict_ids and len(conflict_ids) == len(conflicts), "conflict IDs must be unique")
    for conflict in conflicts:
        validate_conflict_record(conflict, fact_ids, evidence_ids)
    _require(isinstance(result.get("issues"), list), "issues must be an array")
    _non_empty(result.get("extraction_status"), "extraction_status")


def _semantic_result(result: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(result))
    for key in ("generated_at", "semantic_hash", "manifest_path"):
        value.pop(key, None)
    for source in value.get("sources", []):
        for key in ("retrieved_at", "observed_at"):
            source.pop(key, None)
    return _canonical(value, unordered_lists=False)


def compare_extractions(previous: dict[str, Any], current: dict[str, Any]) -> str:
    validate_extraction(previous)
    validate_extraction(current)
    old_facts = {fact["fact_id"]: fact for fact in previous["facts"]}
    new_facts = {fact["fact_id"]: fact for fact in current["facts"]}
    old_content = {key: _fact_identity_payload(value) for key, value in old_facts.items()}
    new_content = {key: _fact_identity_payload(value) for key, value in new_facts.items()}
    common_ids = old_content.keys() & new_content.keys()
    if any(old_content[key] != new_content[key] for key in common_ids):
        return "FACT_CHANGED"
    added_ids = new_content.keys() - old_content.keys()
    removed_ids = old_content.keys() - new_content.keys()
    if added_ids or removed_ids:
        if added_ids and not removed_ids:
            return "FACT_ADDED"
        if removed_ids and not added_ids:
            return "FACT_REMOVED"
        old_logical = {_json_digest(_fact_logical_payload(fact), "") for fact in old_facts.values()}
        new_logical = {_json_digest(_fact_logical_payload(fact), "") for fact in new_facts.values()}
        if old_logical & new_logical:
            return "FACT_CHANGED"
        return "FACT_ADDED" if new_logical - old_logical else "FACT_REMOVED"
    old_evidence = {item["evidence_id"] for item in previous["evidence"]}
    new_evidence = {item["evidence_id"] for item in current["evidence"]}
    if old_evidence != new_evidence:
        if new_evidence > old_evidence:
            return "EVIDENCE_ADDED"
        if old_evidence > new_evidence:
            return "EVIDENCE_REMOVED"
        return "REVIEW_REQUIRED"
    if {item["conflict_id"] for item in previous["conflicts"]} != {item["conflict_id"] for item in current["conflicts"]}:
        return "CONFLICT_CHANGED"
    return "NO_CHANGE"


def write_extraction(result: dict[str, Any], root: Path) -> dict[str, Any]:
    validate_extraction(result)
    directory = root / ".ingestion" / "extractions"
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"{result['job_id']}.json"
    if base.exists():
        previous = json.loads(base.read_text())
        path = base if compare_extractions(previous, result) == "NO_CHANGE" else directory / f"{result['job_id']}.{result['semantic_hash'].split(':', 1)[1][:20]}.json"
    else:
        path = base
    if not path.exists():
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    result["manifest_path"] = str(path)
    return result
