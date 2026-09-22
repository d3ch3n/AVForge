"""Generation Plan v1 models, validation, policy, and runtime persistence.

This module stops at a validated structural plan. It does not materialize
equipment JSON, select Mapping targets, or publish candidates.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable

from .extraction import validate_extraction
from .mapping import (
    MAPPING_VERSION,
    _canonical,
    _collection_semantics,
    _canonicalize_collections,
    _digest,
    validate_mapping_result,
    validate_target,
)
from .unit_normalization import EXACT_CONVERSION_RULES, validate_normalized_value


GENERATION_PLAN_VERSION = "1.0"
PLAN_RERUN_STATES = {"NO_CHANGE", "CHANGED", "STALE"}
ISSUE_CODES = {
    "CONFLICT",
    "NOTES_ONLY",
    "OMIT_UNKNOWN",
    "VOCAB_GAP",
    "SCHEMA_GAP",
    "INSUFFICIENT_EVIDENCE",
    "VALIDATION_FAILED",
    "IDENTITY_AMBIGUOUS",
    "SOURCE_NOT_FOUND",
}
VALUE_SOURCE_KINDS = {"literal", "fact", "normalized_binding", "identity", "entity_reference"}
OPERATION_KINDS = {"ENSURE_OBJECT", "SET_VALUE", "ADD_REFERENCE"}
ROOT_FIELDS = {
    "id",
    "manufacturer",
    "model",
    "product_name",
    "category",
    "subcategory",
    "product_family",
    "sku",
    "part_number",
    "schema_version",
    "revision",
    "status",
}
REQUIRED_ROOT_FIELDS = {"id", "manufacturer", "model", "product_name", "category", "schema_version", "status"}
IDENTITY_FIELDS = {
    "manufacturer",
    "canonical_manufacturer",
    "canonical_model",
    "product_family",
    "variant",
    "official_domain",
    "official_product_url",
    "identity_status",
}
FACT_FIELDS = {
    "subject",
    "property",
    "value",
    "unit",
    "qualifiers",
    "conditions",
    "semantic_precision",
    "polarity",
    "evidence_status",
    "fact_id",
}
_SCALAR_REFERENCE_FIELDS = {"source_id", "mode_id", "target_id", "equipment_id", "interface_id"}
_SAFE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


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


def _path(value: Any, name: str, *, allow_empty: bool = False) -> list[str]:
    _require(isinstance(value, list) and (allow_empty or bool(value)), f"{name} must be a non-empty path")
    _require(all(isinstance(part, str) and bool(part.strip()) for part in value), f"{name} must contain non-empty strings")
    return list(value)


def _get_path(value: Any, path: list[str], name: str) -> Any:
    current = value
    for part in path:
        _require(isinstance(current, dict) and part in current, f"{name} does not exist")
        current = current[part]
    return current


def _target_key(target: dict[str, Any]) -> str:
    return json.dumps({"root": target["root"], "segments": target["segments"]}, sort_keys=True, separators=(",", ":"))


def _target_leaf(target: dict[str, Any]) -> str | None:
    segments = target.get("segments", [])
    return segments[-1].get("name") if segments and segments[-1].get("kind") == "property" else None


def _validate_plan_target(target: Any, name: str) -> None:
    validate_target(target)
    for segment in target["segments"]:
        if segment["kind"] == "property":
            _require(bool(_SAFE_NAME.fullmatch(segment["name"])), f"{name} contains an unsafe property segment")
        else:
            key = segment["key"]
            _require(bool(_SAFE_ID.fullmatch(key["value"])), f"{name} contains an unsafe entity ID")
            _require("[" not in key["value"] and "]" not in key["value"], f"{name} cannot use array indexes")


def _identity_digest(identity: dict[str, Any]) -> str:
    return _digest(identity, "identity-")


def make_input_bindings(
    *,
    identity: dict[str, Any],
    extraction_result: dict[str, Any],
    mapping_result: dict[str, Any],
    schema: dict[str, str],
    vocabularies: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build immutable input metadata without copying source ledgers."""

    return {
        "resolved_identity": {"digest": _identity_digest(identity), "value": _canonical(identity)},
        "extraction": {
            "version": extraction_result.get("extraction_version"),
            "semantic_hash": extraction_result.get("semantic_hash"),
        },
        "mapping": {
            "version": mapping_result.get("mapping_version"),
            "semantic_hash": mapping_result.get("semantic_hash"),
        },
        "schema": _canonical(schema),
        "vocabularies": _canonical(vocabularies),
    }


def _validate_input_bindings(
    bindings: Any,
    *,
    extraction_result: dict[str, Any] | None,
    mapping_result: dict[str, Any] | None,
    vocabularies: dict[str, set[str]] | None,
    verify_inputs: bool = True,
) -> dict[str, Any]:
    _require(isinstance(bindings, dict), "input_bindings must be an object")
    required = {"resolved_identity", "extraction", "mapping", "schema", "vocabularies"}
    _require(set(bindings) == required, "input_bindings has unsupported or missing fields")
    identity = bindings["resolved_identity"]
    _require(isinstance(identity, dict) and set(identity) == {"digest", "value"}, "resolved_identity binding is invalid")
    _require(isinstance(identity["value"], dict), "resolved_identity.value must be an object")
    _require(identity["digest"] == _identity_digest(identity["value"]), "resolved_identity digest is not deterministic")
    for key in ("extraction", "mapping"):
        value = bindings[key]
        _require(isinstance(value, dict) and set(value) == {"version", "semantic_hash"}, f"{key} binding is invalid")
        _non_empty(value.get("version"), f"{key}.version")
        _non_empty(value.get("semantic_hash"), f"{key}.semantic_hash")
    schema = bindings["schema"]
    _require(isinstance(schema, dict), "schema binding must be an object")
    _require(set(schema) == {"id", "version", "sha256"}, "schema binding has unsupported or missing fields")
    for key in ("id", "version", "sha256"):
        _non_empty(schema.get(key), f"schema.{key}")
    vocab_binding = bindings["vocabularies"]
    _require(isinstance(vocab_binding, dict), "vocabularies binding must be an object")
    for name, value in vocab_binding.items():
        _non_empty(name, "vocabulary name")
        _require(isinstance(value, dict) and set(value) == {"version", "sha256"}, "vocabulary binding is invalid")
        _non_empty(value.get("version"), f"vocabularies.{name}.version")
        _non_empty(value.get("sha256"), f"vocabularies.{name}.sha256")
    if extraction_result is not None:
        validate_extraction(extraction_result)
        if verify_inputs:
            _require(bindings["extraction"]["version"] == extraction_result["extraction_version"], "extraction version binding differs")
            _require(bindings["extraction"]["semantic_hash"] == extraction_result.get("semantic_hash"), "extraction hash binding differs")
    if mapping_result is not None:
        validate_mapping_result(mapping_result, vocabularies or {})
        if verify_inputs:
            _require(bindings["mapping"]["version"] == mapping_result["mapping_version"], "mapping version binding differs")
            _require(bindings["mapping"]["semantic_hash"] == mapping_result.get("semantic_hash"), "mapping hash binding differs")
        _require(mapping_result.get("mapping_version") == MAPPING_VERSION, "Generation Plan requires Mapping 1.1")
    return identity["value"]


def _validate_value_source(
    source: Any,
    *,
    facts: dict[str, dict[str, Any]] | None,
    mappings: dict[str, dict[str, Any]] | None,
    identity: dict[str, Any],
    entities: dict[tuple[str, str], dict[str, Any]],
    vocabularies: dict[str, set[str]],
) -> None:
    _require(isinstance(source, dict), "value_source must be an object")
    kind = source.get("kind")
    _require(kind in VALUE_SOURCE_KINDS, "value_source.kind is unsupported")
    if kind == "literal":
        _require(set(source) <= {"kind", "value", "collection_semantics"}, "literal value_source has unsupported fields")
        _json_value(source["value"], "literal.value")
        if "collection_semantics" in source:
            semantics = _collection_semantics(source["collection_semantics"])
            _canonicalize_collections(source["value"], semantics)
    elif kind == "fact":
        _require(set(source) <= {"kind", "fact_id", "path", "collection_semantics"}, "fact value_source has unsupported fields")
        _non_empty(source.get("fact_id"), "fact.fact_id")
        path = _path(source.get("path"), "fact.path")
        _require(path[0] in FACT_FIELDS, "fact.path must begin with a Fact field")
        if "collection_semantics" in source:
            _collection_semantics(source["collection_semantics"])
        _require(facts is not None, "Fact context is required to validate a Fact value_source")
        if facts is not None:
            _require(source["fact_id"] in facts, "fact value_source references an unknown Fact")
            _get_path(facts[source["fact_id"]], path, "fact.path")
    elif kind == "normalized_binding":
        _require(set(source) <= {"kind", "mapping_id", "path", "collection_semantics"}, "normalized_binding has unsupported fields")
        _non_empty(source.get("mapping_id"), "normalized_binding.mapping_id")
        path = _path(source.get("path"), "normalized_binding.path")
        _require(path[0] == "normalization", "normalized_binding.path must begin with normalization")
        if "collection_semantics" in source:
            _collection_semantics(source["collection_semantics"])
        _require(mappings is not None, "Mapping context is required to validate a normalized_binding")
        if mappings is not None:
            mapping = mappings.get(source["mapping_id"])
            _require(mapping is not None, "normalized_binding references an unknown Mapping")
            binding = next((item for item in mapping.get("semantic_bindings", []) if item.get("dimension") == "value"), None)
            _require(isinstance(binding, dict) and isinstance(binding.get("normalization"), dict), "Mapping has no accepted normalization binding")
            normalization = binding["normalization"]
            _get_path({"normalization": normalization}, path, "normalized_binding.path")
            fact = facts.get(mapping["fact_id"])
            _require(fact is not None, "normalized_binding Fact is unavailable")
            _require("units" in vocabularies, "units vocabulary is required for normalized bindings")
            validate_normalized_value(normalization, fact, canonical_unit_ids=vocabularies["units"], rules=EXACT_CONVERSION_RULES)
    elif kind == "identity":
        _require(set(source) == {"kind", "path"}, "identity value_source has unsupported fields")
        path = _path(source.get("path"), "identity.path")
        _require(len(path) == 1 and path[0] in IDENTITY_FIELDS, "identity.path is not an allowed identity field")
        _require(path[0] in identity, "identity value_source field is unavailable")
    else:
        _require(set(source) == {"kind", "entity_kind", "entity_id"}, "entity_reference has unsupported fields")
        _non_empty(source.get("entity_kind"), "entity_reference.entity_kind")
        _non_empty(source.get("entity_id"), "entity_reference.entity_id")
        _require((source["entity_kind"], source["entity_id"]) in entities, "entity_reference is dangling")


def _validate_entities(entities: Any) -> dict[tuple[str, str], dict[str, Any]]:
    _require(isinstance(entities, list), "entities must be an array")
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for entity in entities:
        _require(isinstance(entity, dict), "entity declaration must be an object")
        _require(set(entity) <= {"entity_kind", "entity_id", "collection_target", "schema_ref"}, "entity declaration has unsupported fields")
        _non_empty(entity.get("entity_kind"), "entity.entity_kind")
        _non_empty(entity.get("entity_id"), "entity.entity_id")
        _require(bool(_SAFE_ID.fullmatch(entity["entity_id"])), "entity.entity_id is invalid")
        _validate_plan_target(entity.get("collection_target"), "entity.collection_target")
        _require(entity["collection_target"]["segments"][-1]["kind"] == "property", "entity.collection_target must end at a collection property")
        if "schema_ref" in entity:
            _non_empty(entity["schema_ref"], "entity.schema_ref")
        key = (entity["entity_kind"], entity["entity_id"])
        if key in result:
            _require(result[key] == entity, "conflicting entity declaration")
        else:
            result[key] = entity
    return result


def _operation_references(operation: dict[str, Any]) -> tuple[set[str], set[str]]:
    facts: set[str] = set()
    mappings: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("fact_id"), str):
                facts.add(value["fact_id"])
            if isinstance(value.get("mapping_id"), str):
                mappings.add(value["mapping_id"])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(operation)
    return facts, mappings


def _operation_references_with_mappings(operation: dict[str, Any], mappings: dict[str, dict[str, Any]]) -> tuple[set[str], set[str]]:
    facts, mapping_ids = _operation_references(operation)
    facts.update(mappings[mapping_id]["fact_id"] for mapping_id in mapping_ids if mapping_id in mappings)
    return facts, mapping_ids


def _validate_operation_shape(operation: Any, entities: dict[tuple[str, str], dict[str, Any]]) -> None:
    _require(isinstance(operation, dict), "operation must be an object")
    kind = operation.get("op")
    _require(kind in OPERATION_KINDS, "operation type is unsupported")
    _validate_plan_target(operation.get("target"), "operation.target")
    if kind == "ENSURE_OBJECT":
        _require(set(operation) <= {"op", "target"}, "ENSURE_OBJECT has unsupported fields")
    elif kind == "SET_VALUE":
        _require(set(operation) <= {"op", "target", "value_source", "provenance"}, "SET_VALUE has unsupported fields")
        _require("value_source" in operation, "SET_VALUE.value_source is required")
    else:
        _require(set(operation) <= {"op", "target", "reference", "provenance"}, "ADD_REFERENCE has unsupported fields")
        reference = operation.get("reference")
        _require(isinstance(reference, dict) and set(reference) == {"entity_kind", "entity_id"}, "ADD_REFERENCE.reference is invalid")
        _non_empty(reference.get("entity_kind"), "ADD_REFERENCE.reference.entity_kind")
        _non_empty(reference.get("entity_id"), "ADD_REFERENCE.reference.entity_id")
        _require((reference["entity_kind"], reference["entity_id"]) in entities, "ADD_REFERENCE reference is dangling")
    if "provenance" in operation:
        provenance = operation["provenance"]
        _require(isinstance(provenance, dict) and set(provenance) <= {"fact_ids", "mapping_ids"}, "operation provenance is invalid")
        for key in ("fact_ids", "mapping_ids"):
            if key in provenance:
                _require(isinstance(provenance[key], list) and all(isinstance(item, str) and item for item in provenance[key]), f"provenance.{key} is invalid")


def _operation_signature(operation: dict[str, Any]) -> str:
    return json.dumps(_canonical(operation), sort_keys=True, separators=(",", ":"))


def _validate_merge_intent(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_target: dict[tuple[str, str], dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    seen_references: set[str] = set()
    for operation in operations:
        key = (operation["op"], _target_key(operation["target"]))
        if operation["op"] == "ENSURE_OBJECT":
            previous = by_target.get(key)
            if previous is not None:
                _require(previous == operation, "conflicting ENSURE_OBJECT declarations")
                continue
            by_target[key] = operation
        elif operation["op"] == "SET_VALUE":
            key = ("SET_VALUE", _target_key(operation["target"]))
            previous = by_target.get(key)
            if previous is not None:
                _require(previous["value_source"] == operation["value_source"], "contradictory SET_VALUE operations")
                continue
            by_target[key] = operation
        else:
            reference_key = json.dumps({"target": operation["target"], "reference": operation["reference"]}, sort_keys=True, separators=(",", ":"))
            if reference_key in seen_references:
                continue
            seen_references.add(reference_key)
            if _target_leaf(operation["target"]) in _SCALAR_REFERENCE_FIELDS:
                scalar_key = ("ADD_REFERENCE_SCALAR", _target_key(operation["target"]))
                previous = by_target.get(scalar_key)
                if previous is not None:
                    _require(previous["reference"] == operation["reference"], "contradictory scalar references")
                by_target[scalar_key] = operation
        result.append(operation)
    return result


def _normalize_issue(issue: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(issue)
    result["fact_ids"] = sorted(set(result.get("fact_ids", [])))
    result["mapping_ids"] = sorted(set(result.get("mapping_ids", [])))
    return _canonical(result)


def _normalize_value_source(source: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(source)
    if "collection_semantics" in result:
        semantics = _collection_semantics(result["collection_semantics"])
        result["collection_semantics"] = semantics
        if result.get("kind") == "literal":
            result["value"] = _canonicalize_collections(result["value"], semantics)
    return _canonical(result)


def _normalize_operations(operations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for operation in operations:
        item = deepcopy(operation)
        if item.get("op") == "SET_VALUE" and isinstance(item.get("value_source"), dict):
            item["value_source"] = _normalize_value_source(item["value_source"])
        normalized.append(_canonical(item))
    return normalized


def derive_issue_impacts(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Derive lifecycle impact from issue code and referenced operations."""

    operation_refs = [_operation_references(operation) for operation in plan.get("operations", [])]
    impacts = []
    for issue in plan.get("issues", []):
        code = issue["code"]
        affected_facts = set(issue.get("fact_ids", []))
        affected_mappings = set(issue.get("mapping_ids", []))
        referenced = any(facts & affected_facts or mappings & affected_mappings for facts, mappings in operation_refs)
        if code in {"NOTES_ONLY", "OMIT_UNKNOWN"}:
            impact = {"generation_blocking": False, "candidate_incomplete": False, "publication_blocking": False}
        elif code == "CONFLICT":
            impact = {"generation_blocking": False, "candidate_incomplete": not referenced, "publication_blocking": True}
        elif code in {"VOCAB_GAP", "SCHEMA_GAP", "VALIDATION_FAILED", "IDENTITY_AMBIGUOUS"}:
            impact = {"generation_blocking": True, "candidate_incomplete": False, "publication_blocking": True}
        else:
            impact = {"generation_blocking": referenced, "candidate_incomplete": bool(affected_facts or affected_mappings) and not referenced, "publication_blocking": True}
        impacts.append({"issue_id": issue["issue_id"], **impact})
    return sorted(impacts, key=lambda item: item["issue_id"])


def _semantic_plan(plan: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(plan)
    for key in ("plan_id", "generated_at", "artifact_path"):
        value.pop(key, None)
    for key in ("entities", "operations", "issues", "provenance"):
        if key in value:
            value[key] = sorted(value[key], key=lambda item: json.dumps(_canonical(item), sort_keys=True, separators=(",", ":")))
    value["operations"] = _normalize_operations(value.get("operations", []))
    value["operations"] = _validate_merge_intent(value.get("operations", []))
    value["issue_impacts"] = derive_issue_impacts(value)
    return _canonical(value)


def plan_id(plan: dict[str, Any]) -> str:
    return _digest(_semantic_plan(plan), "generation-plan-")


def _facts_and_mappings(extraction_result: dict[str, Any] | None, mapping_result: dict[str, Any] | None) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    facts = {fact["fact_id"]: fact for fact in (extraction_result or {}).get("facts", [])}
    if mapping_result is not None:
        facts.update({fact["fact_id"]: fact for fact in mapping_result.get("facts", [])})
    mappings = {mapping["mapping_id"]: mapping for mapping in (mapping_result or {}).get("mappings", [])}
    return facts, mappings


def validate_generation_plan(
    plan: dict[str, Any],
    *,
    extraction_result: dict[str, Any] | None = None,
    mapping_result: dict[str, Any] | None = None,
    vocabularies: dict[str, set[str]] | None = None,
    verify_inputs: bool = True,
) -> None:
    """Raise ValueError unless a Generation Plan is structurally valid."""

    _require(isinstance(plan, dict), "generation plan must be an object")
    _require(plan.get("generation_plan_version") == GENERATION_PLAN_VERSION, "generation_plan_version is unsupported")
    _non_empty(plan.get("plan_id"), "plan_id")
    _non_empty(plan.get("job_id"), "job_id")
    identity = _validate_input_bindings(plan.get("input_bindings"), extraction_result=extraction_result, mapping_result=mapping_result, vocabularies=vocabularies, verify_inputs=verify_inputs)
    root = plan.get("root")
    _require(isinstance(root, dict) and set(root) == {"fields"}, "root declaration is invalid")
    fields = root["fields"]
    _require(isinstance(fields, dict), "root.fields must be an object")
    _require(REQUIRED_ROOT_FIELDS <= set(fields), "root declaration is missing required fields")
    _require(set(fields) <= ROOT_FIELDS, "root declaration has unsupported fields")
    entities = _validate_entities(plan.get("entities"))
    facts, mappings = _facts_and_mappings(extraction_result, mapping_result)
    for source in fields.values():
        _validate_value_source(source, facts=facts, mappings=mappings, identity=identity, entities=entities, vocabularies=vocabularies or {})
    operations = plan.get("operations")
    _require(isinstance(operations, list), "operations must be an array")
    for operation in operations:
        _validate_operation_shape(operation, entities)
        if operation["op"] == "SET_VALUE":
            _validate_value_source(operation["value_source"], facts=facts, mappings=mappings, identity=identity, entities=entities, vocabularies=vocabularies or {})
        if "collection_semantics" in operation:
            _collection_semantics(operation["collection_semantics"])
    _validate_merge_intent(operations)
    issues = plan.get("issues")
    _require(isinstance(issues, list), "issues must be an array")
    issue_ids: set[str] = set()
    for issue in issues:
        _require(isinstance(issue, dict), "issue must be an object")
        _require(set(issue) <= {"issue_id", "code", "source", "fact_ids", "mapping_ids", "reason", "impact"}, "issue has unsupported fields")
        _non_empty(issue.get("issue_id"), "issue.issue_id")
        _require(issue["issue_id"] not in issue_ids, "duplicate issue_id")
        issue_ids.add(issue["issue_id"])
        _require(issue.get("code") in ISSUE_CODES, "issue.code is unsupported")
        source = issue.get("source")
        _require(isinstance(source, dict) and set(source) == {"kind", "id"}, "issue.source is invalid")
        _non_empty(source.get("kind"), "issue.source.kind")
        _non_empty(source.get("id"), "issue.source.id")
        for key in ("fact_ids", "mapping_ids"):
            _require(isinstance(issue.get(key, []), list) and all(isinstance(item, str) and item for item in issue.get(key, [])), f"issue.{key} is invalid")
        _non_empty(issue.get("reason"), "issue.reason")
        if issue["code"] == "OMIT_UNKNOWN":
            affected = set(issue.get("fact_ids", [])) | set(issue.get("mapping_ids", []))
            selected_facts = set().union(*(_operation_references_with_mappings(operation, mappings)[0] for operation in operations)) if operations else set()
            selected_mappings = set().union(*(_operation_references_with_mappings(operation, mappings)[1] for operation in operations)) if operations else set()
            selected = affected & (selected_facts | selected_mappings)
            _require(not selected, "OMIT_UNKNOWN cannot be selected by an operation")
    impacts = derive_issue_impacts(plan)
    if "issue_impacts" in plan:
        _require(plan["issue_impacts"] == impacts, "issue impacts are not deterministically derived")
    for issue in issues:
        if "impact" in issue:
            expected = next(item for item in impacts if item["issue_id"] == issue["issue_id"])
            _require(issue["impact"] == {key: expected[key] for key in ("generation_blocking", "candidate_incomplete", "publication_blocking")}, "issue impact is not deterministic")
        if issue["code"] in {"CONFLICT", "VOCAB_GAP", "SCHEMA_GAP"}:
            facts_used = set().union(*(_operation_references_with_mappings(operation, mappings)[0] for operation in operations)) if operations else set()
            operation_mapping_ids = set().union(*(_operation_references_with_mappings(operation, mappings)[1] for operation in operations)) if operations else set()
            affected_facts = set(issue.get("fact_ids", [])); affected_mappings = set(issue.get("mapping_ids", []))
            _require(not facts_used & affected_facts and not operation_mapping_ids & affected_mappings, f"{issue['code']} cannot be selected by an operation")
    _require(plan["plan_id"] == plan_id(plan), "plan_id is not deterministic")


def assess_generation_plan(
    plan: dict[str, Any],
    *,
    extraction_result: dict[str, Any] | None = None,
    mapping_result: dict[str, Any] | None = None,
    vocabularies: dict[str, set[str]] | None = None,
    resolved_identity: dict[str, Any] | None = None,
    schema_context: dict[str, str] | None = None,
    vocabulary_context: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return structural validity and fail-closed execution policy separately."""

    errors: list[str] = []
    try:
        complete_context = all(value is not None for value in (extraction_result, mapping_result, resolved_identity, schema_context, vocabulary_context))
        validate_generation_plan(
            plan,
            extraction_result=extraction_result if complete_context else None,
            mapping_result=mapping_result if complete_context else None,
            vocabularies=vocabularies if complete_context else None,
        )
    except ValueError as exc:
        errors.append(str(exc))
    impacts = derive_issue_impacts(plan) if isinstance(plan, dict) and isinstance(plan.get("issues"), list) else []
    authorization_errors: list[str] = []
    missing_contexts: list[str] = []
    bindings = plan.get("input_bindings") if isinstance(plan, dict) else None
    if extraction_result is None:
        missing_contexts.append("extraction")
    if mapping_result is None:
        missing_contexts.append("mapping")
    if resolved_identity is None:
        missing_contexts.append("resolved_identity")
    if schema_context is None:
        missing_contexts.append("schema")
    if vocabulary_context is None:
        missing_contexts.append("vocabularies")
    if missing_contexts:
        authorization_errors.append("MISSING_AUTHORITATIVE_CONTEXT:" + ",".join(missing_contexts))
    elif isinstance(bindings, dict):
        try:
            validate_extraction(extraction_result)
            validate_mapping_result(mapping_result, vocabularies)
            _require(bindings["extraction"]["version"] == extraction_result["extraction_version"], "extraction version binding differs")
            _require(bindings["extraction"]["semantic_hash"] == extraction_result.get("semantic_hash"), "extraction hash binding differs")
            _require(bindings["mapping"]["version"] == mapping_result["mapping_version"], "mapping version binding differs")
            _require(bindings["mapping"]["semantic_hash"] == mapping_result.get("semantic_hash"), "mapping hash binding differs")
            _require(bindings["resolved_identity"]["value"] == _canonical(resolved_identity), "resolved identity binding differs")
            _require(extraction_result["identity"] == _canonical(resolved_identity), "Extraction identity differs")
            _require(mapping_result["identity"] == _canonical(resolved_identity), "Mapping identity differs")
            _require(bindings["schema"] == _canonical(schema_context), "schema binding differs")
            _require(bindings["vocabularies"] == _canonical(vocabulary_context), "vocabulary binding differs")
        except (KeyError, TypeError, ValueError) as exc:
            authorization_errors.append(f"AUTHORITATIVE_CONTEXT_MISMATCH:{exc}")
    authorization_blocked = bool(authorization_errors)
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": [],
        "issue_impacts": impacts,
        "authorization_errors": authorization_errors,
        "generation_allowed": not errors and not authorization_blocked and not any(item["generation_blocking"] for item in impacts),
        "publication_blocking": bool(errors) or authorization_blocked or any(item["publication_blocking"] for item in impacts),
    }


def make_plan(
    *,
    job_id: str,
    input_bindings: dict[str, Any],
    root: dict[str, Any],
    entities: Iterable[dict[str, Any]] = (),
    operations: Iterable[dict[str, Any]] = (),
    issues: Iterable[dict[str, Any]] = (),
    provenance: Iterable[dict[str, Any]] = (),
    generated_at: str | None = None,
    extraction_result: dict[str, Any] | None = None,
    mapping_result: dict[str, Any] | None = None,
    vocabularies: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    plan: dict[str, Any] = {
        "generation_plan_version": GENERATION_PLAN_VERSION,
        "job_id": job_id,
        "input_bindings": deepcopy(input_bindings),
        "root": deepcopy(root),
        "entities": [_canonical(entity) for entity in entities],
        "operations": _normalize_operations(operations),
        "issues": [_normalize_issue(issue) for issue in issues],
        "provenance": [_canonical(item) for item in provenance],
    }
    plan["issue_impacts"] = derive_issue_impacts(plan)
    plan["plan_id"] = plan_id(plan)
    if generated_at is not None:
        plan["generated_at"] = generated_at
    validate_generation_plan(plan, extraction_result=extraction_result, mapping_result=mapping_result, vocabularies=vocabularies)
    return plan


def compare_generation_plans(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    extraction_result: dict[str, Any] | None = None,
    mapping_result: dict[str, Any] | None = None,
    vocabularies: dict[str, set[str]] | None = None,
) -> str:
    validate_generation_plan(previous, extraction_result=extraction_result, mapping_result=mapping_result, vocabularies=vocabularies, verify_inputs=False)
    validate_generation_plan(current, extraction_result=extraction_result, mapping_result=mapping_result, vocabularies=vocabularies, verify_inputs=False)
    if previous.get("input_bindings") != current.get("input_bindings"):
        return "STALE"
    return "NO_CHANGE" if previous.get("plan_id") == current.get("plan_id") else "CHANGED"


def write_generation_plan(
    plan: dict[str, Any],
    root: Path,
    *,
    extraction_result: dict[str, Any] | None = None,
    mapping_result: dict[str, Any] | None = None,
    vocabularies: dict[str, set[str]] | None = None,
) -> Path:
    validate_generation_plan(plan, extraction_result=extraction_result, mapping_result=mapping_result, vocabularies=vocabularies)
    directory = root / ".ingestion" / "generation-plans"
    directory.mkdir(parents=True, exist_ok=True)
    base = directory / f"{plan['job_id']}.json"
    if base.exists():
        previous = json.loads(base.read_text())
        path = base if compare_generation_plans(previous, plan, extraction_result=extraction_result, mapping_result=mapping_result, vocabularies=vocabularies) == "NO_CHANGE" else directory / f"{plan['job_id']}.{plan['plan_id'].split('-', 2)[-1][:20]}.json"
    else:
        path = base
    if not path.exists():
        path.write_text(json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
    return path


def read_generation_plan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())
