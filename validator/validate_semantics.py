#!/usr/bin/env python3
"""Minimal deterministic semantic validation for AVForge equipment records."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ERROR = "ERROR"
WARNING = "WARNING"


def _issue(
    issues: list[dict[str, Any]],
    code: str,
    severity: str,
    equipment_id: str,
    json_path: str,
    message: str,
    **extra: Any,
) -> None:
    issue = {
        "code": code,
        "severity": severity,
        "equipment_id": equipment_id,
        "json_path": json_path,
        "message": message,
    }
    issue.update({key: value for key, value in extra.items() if value is not None})
    issues.append(issue)


def load_vocabularies(vocab_dir: Path) -> dict[str, dict[str, set[str]]]:
    vocabularies: dict[str, dict[str, set[str]]] = {}
    for path in sorted(vocab_dir.glob("*.json")):
        document = json.loads(path.read_text())
        name = document["vocabulary"]
        ids = {entry["id"] for entry in document["entries"]}
        aliases = {
            alias
            for entry in document["entries"]
            for alias in entry.get("aliases", [])
        }
        symbols = {
            entry["symbol"]
            for entry in document["entries"]
            if "symbol" in entry
        }
        vocabularies[name] = {"ids": ids, "aliases": aliases, "symbols": symbols}
    return vocabularies


def _validate_vocab_value(
    value: Any,
    vocabulary: str,
    vocabularies: dict[str, dict[str, set[str]]],
    issues: list[dict[str, Any]],
    equipment_id: str,
    json_path: str,
) -> None:
    if not isinstance(value, str):
        _issue(
            issues,
            "INVALID_VOCAB_ID",
            ERROR,
            equipment_id,
            json_path,
            f"Vocabulary value must be a canonical string ID for {vocabulary}.",
            vocabulary=vocabulary,
            expected_type="canonical_id",
        )
        return

    vocabulary_data = vocabularies.get(vocabulary, {"ids": set(), "aliases": set(), "symbols": set()})
    if value in vocabulary_data["ids"]:
        return

    if value in vocabulary_data["aliases"] or value in vocabulary_data["symbols"]:
        _issue(
            issues,
            "NON_CANONICAL_VOCAB_VALUE",
            ERROR,
            equipment_id,
            json_path,
            f"Value is an alias or display symbol, not a canonical ID in {vocabulary}.",
            vocabulary=vocabulary,
            referenced_id=value,
        )
        return

    _issue(
        issues,
        "INVALID_VOCAB_ID",
        ERROR,
        equipment_id,
        json_path,
        f"Value does not exist as a canonical ID in {vocabulary}.",
        vocabulary=vocabulary,
        referenced_id=value,
    )


def _validate_ids(
    equipment: dict[str, Any],
    issues: list[dict[str, Any]],
) -> dict[str, set[str]]:
    equipment_id = equipment.get("id", "<missing-id>")
    collections: dict[str, list[tuple[str, Any]]] = {
        "interfaces": [
            (f"interfaces[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("interfaces", []))
        ],
        "physical_connectors": [
            (f"physical_connectors[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("physical_connectors", []))
        ],
        "communication_capabilities": [
            (f"communication_capabilities[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("communication_capabilities", []))
        ],
        "resource_pools": [
            (f"resource_pools[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("resource_pools", []))
        ],
        "capability_modifiers": [
            (f"capability_modifiers[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("capability_modifiers", []))
        ],
        "known_compatibilities": [
            (f"known_compatibilities[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("known_compatibilities", []))
        ],
        "capabilities": [
            (f"capabilities[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("capabilities", []))
        ],
    }

    ids_by_type: dict[str, set[str]] = {}
    for collection, entries in collections.items():
        ids: set[str] = set()
        for json_path, value in entries:
            if not isinstance(value, str):
                continue
            if value in ids:
                _issue(
                    issues,
                    "DUPLICATE_LOCAL_ID",
                    ERROR,
                    equipment_id,
                    json_path,
                    f"Duplicate ID in {collection} collection.",
                    referenced_id=value,
                )
            ids.add(value)
        ids_by_type[collection] = ids

    for connector_index, connector in enumerate(equipment.get("physical_connectors", [])):
        ids: set[str] = set()
        for point_index, point in enumerate(connector.get("connection_points", [])):
            value = point.get("id")
            if not isinstance(value, str):
                continue
            json_path = f"physical_connectors[{connector_index}].connection_points[{point_index}].id"
            if value in ids:
                _issue(
                    issues,
                    "DUPLICATE_LOCAL_ID",
                    ERROR,
                    equipment_id,
                    json_path,
                    "Duplicate connection point ID within physical connector.",
                    referenced_id=value,
                )
            ids.add(value)

    for interface_index, interface in enumerate(equipment.get("interfaces", [])):
        ids: set[str] = set()
        for signal_index, signal in enumerate(interface.get("signals", [])):
            value = signal.get("id")
            if not isinstance(value, str):
                continue
            json_path = f"interfaces[{interface_index}].signals[{signal_index}].id"
            if value in ids:
                _issue(
                    issues,
                    "DUPLICATE_LOCAL_ID",
                    ERROR,
                    equipment_id,
                    json_path,
                    "Duplicate signal ID within interface.",
                    referenced_id=value,
                )
            ids.add(value)

    ids_by_type["connection_points"] = {
        point.get("id")
        for connector in equipment.get("physical_connectors", [])
        for point in connector.get("connection_points", [])
        if isinstance(point.get("id"), str)
    }
    return ids_by_type


def _external_reference(
    target_id: Any,
    path: str,
    equipment_id: str,
    equipment_index: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    if not isinstance(target_id, str) or target_id in equipment_index:
        return
    _issue(
        issues,
        "EXTERNAL_REFERENCE_UNRESOLVED",
        WARNING,
        equipment_id,
        path,
        "Equipment reference is not present in the loaded catalog.",
        referenced_id=target_id,
    )


def _validate_references(
    equipment: dict[str, Any],
    ids_by_type: dict[str, set[str]],
    equipment_index: dict[str, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    equipment_id = equipment.get("id", "<missing-id>")
    interface_ids = ids_by_type["interfaces"]
    pool_ids = ids_by_type["resource_pools"]
    capability_ids = ids_by_type["capabilities"]
    communication_ids = ids_by_type["communication_capabilities"]
    connector_ids = ids_by_type["physical_connectors"]

    def internal(value: Any, expected: set[str], path: str) -> None:
        if isinstance(value, str) and value not in expected:
            _issue(
                issues,
                "INVALID_INTERNAL_REFERENCE",
                ERROR,
                equipment_id,
                path,
                "Referenced ID does not exist in the equipment record.",
                referenced_id=value,
            )

    for index, capability in enumerate(equipment.get("communication_capabilities", [])):
        assignment = capability.get("interface_assignment", {})
        for interface_index, interface_id in enumerate(assignment.get("allowed_interface_ids", [])):
            internal(
                interface_id,
                interface_ids,
                f"communication_capabilities[{index}].interface_assignment.allowed_interface_ids[{interface_index}]",
            )
        if "resource_pool_id" in capability:
            internal(capability["resource_pool_id"], pool_ids, f"communication_capabilities[{index}].resource_pool_id")

    for index, modifier in enumerate(equipment.get("capability_modifiers", [])):
        _external_reference(modifier.get("source_equipment_id"), f"capability_modifiers[{index}].source_equipment_id", equipment_id, equipment_index, issues)
        for affect_index, affect in enumerate(modifier.get("affects", [])):
            target_type = affect.get("target_type")
            expected = {
                "communication_capability": communication_ids,
                "resource_pool": pool_ids,
                "capability": capability_ids,
            }.get(target_type)
            if expected is not None:
                internal(affect.get("target_id"), expected, f"capability_modifiers[{index}].affects[{affect_index}].target_id")

    for index, interface in enumerate(equipment.get("interfaces", [])):
        connection = interface.get("physical_connection")
        if not connection:
            continue
        connector_id = connection.get("connector_id")
        internal(connector_id, connector_ids, f"interfaces[{index}].physical_connection.connector_id")
        connector = next(
            (item for item in equipment.get("physical_connectors", []) if item.get("id") == connector_id),
            None,
        )
        point_ids = {
            point.get("id")
            for point in (connector or {}).get("connection_points", [])
            if isinstance(point.get("id"), str)
        }
        for point_index, point_id in enumerate(connection.get("connection_point_ids", [])):
            internal(
                point_id,
                point_ids,
                f"interfaces[{index}].physical_connection.connection_point_ids[{point_index}]",
            )

    for index, compatibility in enumerate(equipment.get("known_compatibilities", [])):
        if "local_interface_id" in compatibility:
            internal(compatibility["local_interface_id"], interface_ids, f"known_compatibilities[{index}].local_interface_id")
        _external_reference(compatibility.get("target_equipment_id"), f"known_compatibilities[{index}].target_equipment_id", equipment_id, equipment_index, issues)

    for index, output in enumerate(equipment.get("power", {}).get("poe_supplied", [])):
        internal(output.get("interface_id"), interface_ids, f"power.poe_supplied[{index}].interface_id")

    behavior = equipment.get("functional_behavior", {})
    signal_ids = {
        signal.get("id")
        for interface in equipment.get("interfaces", [])
        for signal in interface.get("signals", [])
        if isinstance(signal.get("id"), str)
    }
    for field in ("receives_signals", "produces_signals"):
        for index, signal_id in enumerate(behavior.get(field, [])):
            internal(signal_id, signal_ids, f"functional_behavior.{field}[{index}]")
    for index, process in enumerate(behavior.get("processing", [])):
        for field in ("input_signal_ids", "output_signal_ids"):
            for signal_index, signal_id in enumerate(process.get(field, [])):
                internal(signal_id, signal_ids, f"functional_behavior.processing[{index}].{field}[{signal_index}]")

    def scan_external_targets(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key == "equipment_id":
                    _external_reference(child, child_path, equipment_id, equipment_index, issues)
                scan_external_targets(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                scan_external_targets(child, f"{path}[{index}]")

    for index, interface in enumerate(equipment.get("interfaces", [])):
        scan_external_targets(interface.get("connection_constraints", {}), f"interfaces[{index}].connection_constraints")


def _validate_vocabularies(
    equipment: dict[str, Any],
    vocabularies: dict[str, dict[str, set[str]]],
    issues: list[dict[str, Any]],
) -> None:
    equipment_id = equipment.get("id", "<missing-id>")

    def check(value: Any, vocabulary: str, path: str) -> None:
        _validate_vocab_value(value, vocabulary, vocabularies, issues, equipment_id, path)

    def walk(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key
                if key in {"connector", "connector_type"}:
                    check(child, "connectors", child_path)
                elif key == "signal_type":
                    check(child, "signal-types", child_path)
                elif key == "signal_family":
                    check(child, "signal-families", child_path)
                elif key == "signal_format":
                    check(child, "signal-formats", child_path)
                elif key == "protocol_family":
                    check(child, "protocol-families", child_path)
                elif key == "direction":
                    check(child, "interface-directions", child_path)
                elif key == "unit":
                    check(child, "units", child_path)
                elif key == "slot_type":
                    check(child, "slot-types", child_path)
                elif key == "module_type":
                    check(child, "module-types", child_path)
                elif key == "compatible_slot_types" and isinstance(child, list):
                    for index, item in enumerate(child):
                        check(item, "slot-types", f"{child_path}[{index}]")
                elif key == "module_types" and isinstance(child, list):
                    for index, item in enumerate(child):
                        check(item, "module-types", f"{child_path}[{index}]")
                walk(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(equipment)


def _validate_electrical_variants(
    equipment: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Validate cross-field consistency for Schema 3.6 electrical variants."""
    equipment_id = equipment.get("id", "<missing-id>")

    for interface_index, interface in enumerate(equipment.get("interfaces", [])):
        electrical = interface.get("electrical_characteristics")
        if not isinstance(electrical, dict):
            continue
        interface_id = interface.get("id", f"interfaces[{interface_index}]")

        for profile_name in ("input", "output"):
            profile = electrical.get(profile_name)
            if not isinstance(profile, dict) or "variants" not in profile:
                continue
            variants = profile.get("variants")
            profile_path = f"interfaces[{interface_index}].electrical_characteristics.{profile_name}"
            variant_path = f"{profile_path}.variants"
            if not isinstance(variants, list):
                continue

            balance_modes = profile.get("balance_modes")
            if not isinstance(balance_modes, list):
                _issue(
                    issues,
                    "ELECTRICAL_VARIANT_MODE_DOMAIN_MISSING",
                    ERROR,
                    equipment_id,
                    variant_path,
                    f"Interface {interface_id} {profile_name}: variants require declared profile.balance_modes.",
                    profile=profile_name,
                )
                continue

            variant_modes: list[str] = []
            undeclared_modes: set[str] = set()
            variant_properties: set[str] = set()
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                conditions = variant.get("conditions")
                if not isinstance(conditions, dict):
                    continue
                mode = conditions.get("balance_mode")
                if isinstance(mode, str):
                    variant_modes.append(mode)
                    if mode not in balance_modes:
                        undeclared_modes.add(mode)
                if "maximum_level" in variant:
                    variant_properties.add("maximum_level")
                impedance = variant.get("impedance")
                if isinstance(impedance, dict):
                    if "nominal" in impedance:
                        variant_properties.add("impedance.nominal")
                    if "upper_bound" in impedance:
                        variant_properties.add("impedance.upper_bound")

            for mode in sorted(undeclared_modes):
                _issue(
                    issues,
                    "ELECTRICAL_VARIANT_MODE_UNDECLARED",
                    ERROR,
                    equipment_id,
                    f"{variant_path}.conditions.balance_mode",
                    f"Interface {interface_id} {profile_name}: variant balance_mode '{mode}' is not declared in profile.balance_modes.",
                    profile=profile_name,
                    balance_mode=mode,
                )

            for mode in sorted(set(variant_modes)):
                if variant_modes.count(mode) > 1:
                    _issue(
                        issues,
                        "DUPLICATE_ELECTRICAL_VARIANT_MODE",
                        ERROR,
                        equipment_id,
                        variant_path,
                        f"Interface {interface_id} {profile_name}: duplicate electrical variant for balance_mode '{mode}'.",
                        profile=profile_name,
                        balance_mode=mode,
                    )

            base_properties: set[str] = set()
            if "maximum_level" in profile:
                base_properties.add("maximum_level")
            impedance = profile.get("impedance")
            if isinstance(impedance, dict):
                if "nominal" in impedance:
                    base_properties.add("impedance.nominal")
                if "upper_bound" in impedance:
                    base_properties.add("impedance.upper_bound")

            for property_name in sorted(base_properties & variant_properties):
                _issue(
                    issues,
                    "BASE_AND_CONDITIONAL_ELECTRICAL_PROPERTY",
                    ERROR,
                    equipment_id,
                    profile_path,
                    f"Interface {interface_id} {profile_name}: property '{property_name}' exists both as base and conditional value.",
                    profile=profile_name,
                    property=property_name,
                )


def validate_records(
    records: list[dict[str, Any]],
    vocab_dir: Path | None = None,
) -> dict[str, Any]:
    """Validate loaded records and return a JSON-serializable result."""
    if vocab_dir is None:
        vocab_dir = Path(__file__).resolve().parent.parent / "vocab"
    vocabularies = load_vocabularies(vocab_dir)
    equipment_index = {
        record.get("id"): record
        for record in records
        if isinstance(record.get("id"), str)
    }
    issues: list[dict[str, Any]] = []
    for record in records:
        ids_by_type = _validate_ids(record, issues)
        _validate_references(record, ids_by_type, equipment_index, issues)
        _validate_vocabularies(record, vocabularies, issues)
        _validate_electrical_variants(record, issues)

    errors = [issue for issue in issues if issue["severity"] == ERROR]
    warnings = [issue for issue in issues if issue["severity"] == WARNING]
    return {
        "valid": not errors,
        "summary": {
            "equipment_count": len(records),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
        "issues": issues,
    }


def _load_records(paths: list[str]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        records.append(json.loads(Path(path).read_text()))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate AVForge equipment semantics.")
    parser.add_argument("equipment", nargs="+", help="Equipment JSON files to validate")
    args = parser.parse_args(argv)
    try:
        result = validate_records(_load_records(args.equipment))
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
