"""Deterministic Mapping v1 between extracted facts and the AVForge model.

Mapping records describe future equipment-generation destinations.  They do
not generate equipment JSON, mutate schemas or vocabularies, or interpret
source content as instructions.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .extraction import validate_extraction


MAPPING_VERSION = "1.0"
MAPPING_STATES = {
    "STRUCTURED",
    "NOTES_ONLY",
    "OMIT_UNKNOWN",
    "VOCAB_GAP",
    "SCHEMA_GAP",
    "CONFLICT",
}
RERUN_STATES = {
    "NO_CHANGE",
    "MAPPING_CHANGED",
    "VOCAB_GAP_ADDED",
    "VOCAB_GAP_REMOVED",
    "SCHEMA_GAP_ADDED",
    "SCHEMA_GAP_REMOVED",
    "CONFLICT_MAPPING_CHANGED",
    "REVIEW_REQUIRED",
}
DECISION_PRECEDENCE = ("CONFLICT", "SCHEMA_GAP", "VOCAB_GAP", "STRUCTURED", "NOTES_ONLY", "OMIT_UNKNOWN")
_UNKNOWN_FACT_STATUSES = {"UNKNOWN", "NOT_APPLICABLE"}
_UNKNOWN_POLARITIES = {"UNKNOWN", "NOT_APPLICABLE"}
_UNKNOWN_PRECISIONS = {"unknown", "not-rated"}


def _canonical(value: Any, *, unordered_lists: bool = False) -> Any:
    if isinstance(value, dict):
        return {key: _canonical(item, unordered_lists=unordered_lists) for key, item in sorted(value.items())}
    if isinstance(value, list):
        items = [_canonical(item, unordered_lists=unordered_lists) for item in value]
        if unordered_lists:
            items.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return items
    return value


def _digest(value: Any, prefix: str) -> str:
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


def load_vocabularies(directory: Path) -> dict[str, set[str]]:
    """Load canonical IDs without changing vocabulary files."""

    result: dict[str, set[str]] = {}
    for path in sorted(directory.glob("*.json")):
        document = json.loads(path.read_text())
        entries = document.get("entries", [])
        _require(isinstance(entries, list), f"{path} entries must be an array")
        result[path.stem] = {entry["id"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("id"), str)}
    return result


def load_mapping_context(schema_path: Path, vocabulary_directory: Path) -> tuple[dict[str, set[str]], dict[str, Any]]:
    """Load read-only schema and vocabulary metadata used by a mapping run."""

    schema_document = json.loads(schema_path.read_text())
    vocabularies = load_vocabularies(vocabulary_directory)
    vocabulary_metadata: dict[str, dict[str, str]] = {}
    for path in sorted(vocabulary_directory.glob("*.json")):
        document = json.loads(path.read_text())
        vocabulary_metadata[path.stem] = {
            "version": str(document.get("version", "")),
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    context = {
        "schema": {
            "id": schema_document.get("$id", ""),
            "title": schema_document.get("title", ""),
            "sha256": "sha256:" + hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        },
        "vocabularies": vocabulary_metadata,
    }
    return vocabularies, context


def _known_vocabulary_id(vocabularies: dict[str, set[str]], vocabulary: str, identifier: str) -> bool:
    return identifier in vocabularies.get(vocabulary, set())


def make_target(*, segments: Iterable[dict[str, Any]], schema_ref: str | None = None) -> dict[str, Any]:
    target: dict[str, Any] = {"root": "equipment", "segments": _canonical(list(segments))}
    if schema_ref is not None:
        target["schema_ref"] = schema_ref
    validate_target(target)
    return target


def validate_target(target: dict[str, Any]) -> None:
    _require(isinstance(target, dict), "target must be an object")
    _require(target.get("root") == "equipment", "target.root must be equipment")
    segments = target.get("segments")
    _require(isinstance(segments, list) and bool(segments), "target.segments is required")
    if "schema_ref" in target:
        _non_empty(target["schema_ref"], "target.schema_ref")
    for segment in segments:
        _require(isinstance(segment, dict), "target segments must be objects")
        kind = segment.get("kind")
        if kind == "property":
            _non_empty(segment.get("name"), "property segment.name")
            _require(set(segment) <= {"kind", "name"}, "property segment has unsupported fields")
        elif kind == "entity":
            _non_empty(segment.get("entity_kind"), "entity segment.entity_kind")
            key = segment.get("key")
            _require(isinstance(key, dict), "entity segment.key is required")
            _require(key.get("kind") in {"local_id", "semantic_id"}, "entity key kind is invalid")
            _non_empty(key.get("value"), "entity key.value")
            _require(set(segment) <= {"kind", "entity_kind", "key"}, "entity segment has unsupported fields")
        else:
            raise ValueError("target segment kind must be property or entity")


def _gap_id_payload(record: dict[str, Any], kind: str) -> dict[str, Any]:
    fields = {
        "fact_id": record["fact_id"],
        "kind": kind,
    }
    if kind == "VOCAB_GAP":
        fields.update({key: record[key] for key in ("vocabulary", "proposed_identifier", "meaning", "reason")})
    else:
        fields.update({key: record[key] for key in ("engineering_meaning", "why_insufficient", "semantics_lost", "affected_area")})
    return fields


def make_vocab_gap(
    *,
    fact_id: str,
    evidence_ids: Iterable[str],
    vocabulary: str,
    proposed_identifier: str,
    meaning: str,
    reason: str,
) -> dict[str, Any]:
    record = {
        "fact_id": fact_id,
        "evidence_ids": sorted(set(evidence_ids)),
        "vocabulary": vocabulary,
        "proposed_identifier": proposed_identifier,
        "meaning": meaning,
        "reason": reason,
    }
    _non_empty(fact_id, "vocab_gap.fact_id")
    _require(record["evidence_ids"], "vocab_gap.evidence_ids is required")
    for key in ("vocabulary", "proposed_identifier", "meaning", "reason"):
        _non_empty(record[key], f"vocab_gap.{key}")
    record["gap_id"] = _digest(_gap_id_payload(record, "VOCAB_GAP"), "vocab-gap-")
    return record


def make_schema_gap(
    *,
    fact_id: str,
    evidence_ids: Iterable[str],
    engineering_meaning: str,
    why_insufficient: str,
    semantics_lost: str,
    affected_area: str,
) -> dict[str, Any]:
    record = {
        "fact_id": fact_id,
        "evidence_ids": sorted(set(evidence_ids)),
        "engineering_meaning": engineering_meaning,
        "why_insufficient": why_insufficient,
        "semantics_lost": semantics_lost,
        "affected_area": affected_area,
    }
    _non_empty(fact_id, "schema_gap.fact_id")
    _require(record["evidence_ids"], "schema_gap.evidence_ids is required")
    for key in ("engineering_meaning", "why_insufficient", "semantics_lost", "affected_area"):
        _non_empty(record[key], f"schema_gap.{key}")
    record["gap_id"] = _digest(_gap_id_payload(record, "SCHEMA_GAP"), "schema-gap-")
    return record


def make_mapping(
    *,
    fact_id: str,
    evidence_ids: Iterable[str],
    state: str,
    target: dict[str, Any] | None = None,
    vocabulary_refs: Iterable[dict[str, str]] = (),
    vocab_gap_id: str | None = None,
    schema_gap_id: str | None = None,
    conflict_ids: Iterable[str] = (),
    reason: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "mapping_version": MAPPING_VERSION,
        "fact_id": fact_id,
        "evidence_ids": sorted(set(evidence_ids)),
        "state": state,
        "vocabulary_refs": _canonical(list(vocabulary_refs), unordered_lists=True),
        "conflict_ids": sorted(set(conflict_ids)),
    }
    if target is not None:
        record["target"] = _canonical(target)
    if vocab_gap_id is not None:
        record["vocab_gap_id"] = vocab_gap_id
    if schema_gap_id is not None:
        record["schema_gap_id"] = schema_gap_id
    if reason is not None:
        record["reason"] = reason
    identity = _mapping_identity(record)
    record["mapping_id"] = _digest(identity, "mapping-")
    return record


def _mapping_identity(mapping: dict[str, Any]) -> dict[str, Any]:
    return {
        "mapping_version": mapping.get("mapping_version"),
        "fact_id": mapping.get("fact_id"),
        "state": mapping.get("state"),
        "target": mapping.get("target"),
        "vocabulary_refs": _canonical(mapping.get("vocabulary_refs", []), unordered_lists=True),
        "vocab_gap_id": mapping.get("vocab_gap_id"),
        "schema_gap_id": mapping.get("schema_gap_id"),
        "conflict_ids": sorted(mapping.get("conflict_ids", [])),
    }


def _fact_is_unknown(fact: dict[str, Any]) -> bool:
    return (
        fact.get("evidence_status") in _UNKNOWN_FACT_STATUSES
        or fact.get("polarity") in _UNKNOWN_POLARITIES
        or fact.get("semantic_precision") in _UNKNOWN_PRECISIONS
    )


def _validate_vocabulary_refs(refs: list[dict[str, Any]], vocabularies: dict[str, set[str]]) -> None:
    for ref in refs:
        _require(isinstance(ref, dict), "vocabulary_refs must contain objects")
        _non_empty(ref.get("vocabulary"), "vocabulary_ref.vocabulary")
        _non_empty(ref.get("id"), "vocabulary_ref.id")
        _require(set(ref) == {"vocabulary", "id"}, "vocabulary_ref has unsupported fields")
        _require(_known_vocabulary_id(vocabularies, ref["vocabulary"], ref["id"]), "vocabulary_ref is not a known canonical ID")


def validate_gap_proposal(proposal: dict[str, Any], kind: str, fact_ids: set[str], evidence_by_fact: dict[str, set[str]], vocabularies: dict[str, set[str]]) -> None:
    _require(isinstance(proposal, dict), f"{kind} proposal must be an object")
    _non_empty(proposal.get("gap_id"), f"{kind}.gap_id")
    _require(proposal.get("fact_id") in fact_ids, f"{kind} references an unknown fact")
    refs = proposal.get("evidence_ids")
    _require(isinstance(refs, list) and bool(refs), f"{kind}.evidence_ids is required")
    _require(set(refs) <= evidence_by_fact[proposal["fact_id"]], f"{kind} references evidence outside its fact")
    if kind == "VOCAB_GAP":
        for key in ("vocabulary", "proposed_identifier", "meaning", "reason"):
            _non_empty(proposal.get(key), f"vocab_gap.{key}")
        _require(not _known_vocabulary_id(vocabularies, proposal["vocabulary"], proposal["proposed_identifier"]), "vocab gap proposes an existing canonical ID")
        expected = _digest(_gap_id_payload(proposal, kind), "vocab-gap-")
    else:
        for key in ("engineering_meaning", "why_insufficient", "semantics_lost", "affected_area"):
            _non_empty(proposal.get(key), f"schema_gap.{key}")
        expected = _digest(_gap_id_payload(proposal, kind), "schema-gap-")
    _require(proposal["gap_id"] == expected, f"{kind} gap_id is not deterministic")


def validate_mapping_record(
    mapping: dict[str, Any],
    facts: dict[str, dict[str, Any]],
    conflicts: dict[str, dict[str, Any]],
    vocab_gap_ids: set[str],
    schema_gap_ids: set[str],
    vocabularies: dict[str, set[str]],
) -> None:
    _require(isinstance(mapping, dict), "mapping must be an object")
    _non_empty(mapping.get("mapping_id"), "mapping.mapping_id")
    _non_empty(mapping.get("mapping_version"), "mapping.mapping_version")
    _require(mapping["mapping_version"] == MAPPING_VERSION, "mapping_version is unsupported")
    fact_id = mapping.get("fact_id")
    _require(fact_id in facts, "mapping references an unknown fact")
    fact = facts[fact_id]
    refs = mapping.get("evidence_ids")
    _require(isinstance(refs, list) and len(refs) == len(set(refs)) and set(refs) == set(fact["evidence_ids"]), "mapping must preserve all fact evidence IDs")
    state = mapping.get("state")
    _require(state in MAPPING_STATES, "mapping.state is invalid")
    target = mapping.get("target")
    vocabulary_refs = mapping.get("vocabulary_refs", [])
    _require(isinstance(vocabulary_refs, list), "mapping.vocabulary_refs must be an array")
    _validate_vocabulary_refs(vocabulary_refs, vocabularies)
    conflict_ids = mapping.get("conflict_ids", [])
    _require(isinstance(conflict_ids, list), "mapping.conflict_ids must be an array")
    _require(set(conflict_ids) <= set(conflicts), "mapping references an unknown conflict")
    if target is not None:
        validate_target(target)
    if state == "STRUCTURED":
        _require(target is not None, "STRUCTURED mapping requires target")
        _require(not conflict_ids and not _fact_is_unknown(fact), "STRUCTURED mapping cannot hide unknowns or conflicts")
        _require(not mapping.get("vocab_gap_id") and not mapping.get("schema_gap_id"), "STRUCTURED mapping cannot reference a gap")
    elif state == "NOTES_ONLY":
        _non_empty(mapping.get("reason"), "NOTES_ONLY.reason")
        _require(target is None, "NOTES_ONLY mapping cannot have target")
    elif state == "OMIT_UNKNOWN":
        _require(target is None, "OMIT_UNKNOWN mapping cannot have target")
        _require(_fact_is_unknown(fact), "OMIT_UNKNOWN requires unknown or not-applicable fact semantics")
    elif state == "VOCAB_GAP":
        _require(target is not None, "VOCAB_GAP mapping requires target")
        _non_empty(mapping.get("vocab_gap_id"), "VOCAB_GAP.vocab_gap_id")
        _require(mapping["vocab_gap_id"] in vocab_gap_ids, "VOCAB_GAP references an unknown proposal")
        _require(not vocabulary_refs and not conflict_ids, "VOCAB_GAP cannot silently select vocabulary or hide conflicts")
    elif state == "SCHEMA_GAP":
        _non_empty(mapping.get("schema_gap_id"), "SCHEMA_GAP.schema_gap_id")
        _require(mapping["schema_gap_id"] in schema_gap_ids, "SCHEMA_GAP references an unknown proposal")
        _require(target is None and not conflict_ids, "SCHEMA_GAP cannot claim a faithful target or hide conflicts")
    elif state == "CONFLICT":
        _require(conflict_ids, "CONFLICT mapping requires conflict_ids")
        _require(all(conflicts[cid].get("resolution_status") == "UNRESOLVED" for cid in conflict_ids), "CONFLICT must reference unresolved conflicts")
        _require(target is None, "CONFLICT mapping cannot have target")
    _require(mapping["mapping_id"] == _digest(_mapping_identity(mapping), "mapping-"), "mapping_id is not deterministic")


def validate_mapping_result(result: dict[str, Any], vocabularies: dict[str, set[str]] | None = None) -> None:
    _require(isinstance(result, dict), "mapping result must be an object")
    _non_empty(result.get("mapping_version"), "mapping_version")
    _require(result["mapping_version"] == MAPPING_VERSION, "mapping_version is unsupported")
    _non_empty(result.get("job_id"), "job_id")
    _non_empty(result.get("fact_extraction_version"), "fact_extraction_version")
    _non_empty(result.get("fact_extraction_hash"), "fact_extraction_hash")
    _require(isinstance(result.get("model_context"), dict), "model_context is required")
    facts_result = result.get("facts")
    _require(isinstance(facts_result, list), "mapping result facts must be an array")
    facts = {fact.get("fact_id"): fact for fact in facts_result}
    _require(None not in facts and len(facts) == len(facts_result), "mapping result fact IDs must be unique")
    extraction = result.get("extraction")
    _require(isinstance(extraction, dict), "mapping result extraction metadata is required")
    _require(extraction.get("fact_ids") == sorted(facts), "mapping result fact coverage is not deterministic")
    evidence_by_fact = {fact_id: set(fact.get("evidence_ids", [])) for fact_id, fact in facts.items()}
    _require(isinstance(result.get("conflicts"), list), "mapping conflicts must be an array")
    conflicts = {conflict.get("conflict_id"): conflict for conflict in result["conflicts"]}
    _require(None not in conflicts and len(conflicts) == len(result.get("conflicts", [])), "mapping conflict IDs must be unique")
    vocabularies = vocabularies or {}
    mappings = result.get("mappings")
    _require(isinstance(mappings, list), "mappings must be an array")
    mapping_ids = {mapping.get("mapping_id") for mapping in mappings}
    _require(None not in mapping_ids and len(mapping_ids) == len(mappings), "mapping IDs must be unique")
    _require({mapping.get("fact_id") for mapping in mappings} == set(facts), "every fact requires exactly one mapping")
    vocab_gaps = result.get("vocab_gap_proposals")
    schema_gaps = result.get("schema_gap_proposals")
    _require(isinstance(vocab_gaps, list) and isinstance(schema_gaps, list), "gap proposals must be arrays")
    vocab_gap_ids = {gap.get("gap_id") for gap in vocab_gaps}; schema_gap_ids = {gap.get("gap_id") for gap in schema_gaps}
    _require(None not in vocab_gap_ids and len(vocab_gap_ids) == len(vocab_gaps), "vocabulary gap IDs must be unique")
    _require(None not in schema_gap_ids and len(schema_gap_ids) == len(schema_gaps), "schema gap IDs must be unique")
    for gap in vocab_gaps: validate_gap_proposal(gap, "VOCAB_GAP", set(facts), evidence_by_fact, vocabularies)
    for gap in schema_gaps: validate_gap_proposal(gap, "SCHEMA_GAP", set(facts), evidence_by_fact, vocabularies)
    for mapping in mappings: validate_mapping_record(mapping, facts, conflicts, vocab_gap_ids, schema_gap_ids, vocabularies)
    _require(isinstance(result.get("issues"), list), "mapping issues must be an array")
    for issue in result["issues"]:
        _non_empty(issue.get("issue_id"), "issue.issue_id"); _non_empty(issue.get("code"), "issue.code"); _non_empty(issue.get("message"), "issue.message")
    _require(isinstance(result.get("summary"), dict), "mapping summary is required")
    expected_counts = {state: sum(mapping.get("state") == state for mapping in mappings) for state in sorted(MAPPING_STATES)}
    _require(result["summary"] == {"mapping_count": len(mappings), "state_counts": expected_counts}, "mapping summary is not deterministic")
    _non_empty(result.get("generated_at"), "generated_at")


def build_mapping_result(
    *,
    extraction_result: dict[str, Any],
    mappings: Iterable[dict[str, Any]],
    vocab_gap_proposals: Iterable[dict[str, Any]] = (),
    schema_gap_proposals: Iterable[dict[str, Any]] = (),
    issues: Iterable[dict[str, Any]] = (),
    vocabularies: dict[str, set[str]] | None = None,
    model_context: dict[str, Any] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    validate_extraction(extraction_result)
    facts = sorted(extraction_result["facts"], key=lambda fact: fact["fact_id"])
    result = {
        "mapping_version": MAPPING_VERSION,
        "job_id": extraction_result["job_id"],
        "identity": extraction_result["identity"],
        "fact_extraction_version": extraction_result["extraction_version"],
        "fact_extraction_hash": extraction_result.get("semantic_hash", ""),
        "model_context": model_context or {},
        "extraction": {"fact_ids": [fact["fact_id"] for fact in facts]},
        "facts": facts,
        "mappings": sorted(list(mappings), key=lambda mapping: mapping.get("mapping_id", "")),
        "vocab_gap_proposals": sorted(list(vocab_gap_proposals), key=lambda proposal: proposal.get("gap_id", "")),
        "schema_gap_proposals": sorted(list(schema_gap_proposals), key=lambda proposal: proposal.get("gap_id", "")),
        "conflicts": sorted(extraction_result["conflicts"], key=lambda conflict: conflict["conflict_id"]),
        "issues": sorted(list(issues), key=lambda issue: json.dumps(issue, sort_keys=True)),
        "generated_at": observed_at or datetime.now(timezone.utc).isoformat(),
    }
    counts = {state: sum(mapping.get("state") == state for mapping in result["mappings"]) for state in sorted(MAPPING_STATES)}
    result["summary"] = {"mapping_count": len(result["mappings"]), "state_counts": counts}
    validate_mapping_result(result, vocabularies)
    result["semantic_hash"] = _digest(_semantic_result(result), "sha256:")
    return result


def _semantic_result(result: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(result))
    for key in ("generated_at", "semantic_hash", "manifest_path"):
        value.pop(key, None)
    return _canonical(value)


def compare_mappings(previous: dict[str, Any], current: dict[str, Any], vocabularies: dict[str, set[str]] | None = None) -> str:
    validate_mapping_result(previous, vocabularies); validate_mapping_result(current, vocabularies)
    if previous.get("fact_extraction_hash") != current.get("fact_extraction_hash") or previous.get("model_context") != current.get("model_context"):
        return "REVIEW_REQUIRED"
    old = {item["fact_id"]: item for item in previous["mappings"]}; new = {item["fact_id"]: item for item in current["mappings"]}
    if old != new:
        old_conflicts = {item["fact_id"] for item in previous["mappings"] if item["state"] == "CONFLICT"}
        new_conflicts = {item["fact_id"] for item in current["mappings"] if item["state"] == "CONFLICT"}
        if old_conflicts != new_conflicts or any(old.get(f, {}).get("conflict_ids") != new.get(f, {}).get("conflict_ids") for f in old.keys() & new.keys()):
            return "CONFLICT_MAPPING_CHANGED"
        if len(current["vocab_gap_proposals"]) != len(previous["vocab_gap_proposals"]):
            return "VOCAB_GAP_ADDED" if len(current["vocab_gap_proposals"]) > len(previous["vocab_gap_proposals"]) else "VOCAB_GAP_REMOVED"
        if len(current["schema_gap_proposals"]) != len(previous["schema_gap_proposals"]):
            return "SCHEMA_GAP_ADDED" if len(current["schema_gap_proposals"]) > len(previous["schema_gap_proposals"]) else "SCHEMA_GAP_REMOVED"
        return "MAPPING_CHANGED"
    old_vocab = {gap["gap_id"] for gap in previous["vocab_gap_proposals"]}; new_vocab = {gap["gap_id"] for gap in current["vocab_gap_proposals"]}
    if old_vocab != new_vocab: return "VOCAB_GAP_ADDED" if new_vocab > old_vocab else "VOCAB_GAP_REMOVED"
    old_schema = {gap["gap_id"] for gap in previous["schema_gap_proposals"]}; new_schema = {gap["gap_id"] for gap in current["schema_gap_proposals"]}
    if old_schema != new_schema: return "SCHEMA_GAP_ADDED" if new_schema > old_schema else "SCHEMA_GAP_REMOVED"
    if previous.get("issues") != current.get("issues"): return "REVIEW_REQUIRED"
    return "NO_CHANGE"


def write_mapping(result: dict[str, Any], root: Path, vocabularies: dict[str, set[str]] | None = None) -> dict[str, Any]:
    validate_mapping_result(result, vocabularies)
    directory = root / ".ingestion" / "mappings"; directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"{result['job_id']}.json"
    if base.exists():
        previous = json.loads(base.read_text())
        path = base if compare_mappings(previous, result, vocabularies) == "NO_CHANGE" else directory / f"{result['job_id']}.{result['semantic_hash'].split(':', 1)[1][:20]}.json"
    else: path = base
    if not path.exists(): path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    result["manifest_path"] = str(path)
    return result
