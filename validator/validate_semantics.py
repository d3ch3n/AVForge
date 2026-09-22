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
        "power_sources": [
            (f"power.sources[{index}].id", item.get("id"))
            for index, item in enumerate(equipment.get("power", {}).get("sources", []))
            if isinstance(item, dict)
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


def _condition_key(condition: dict[str, Any]) -> tuple[str, str]:
    return condition["kind"], condition["value"]


def _validate_applications(
    equipment: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Validate Application Model v1 identity and state semantics."""
    equipment_id = equipment.get("id", "<missing-id>")
    applications = equipment.get("applications", [])
    if not isinstance(applications, list):
        return

    application_ids: set[str] = set()
    for application_index, application in enumerate(applications):
        if not isinstance(application, dict):
            continue
        application_path = f"applications[{application_index}]"
        application_id = application.get("id")
        if isinstance(application_id, str):
            if application_id in application_ids:
                _issue(
                    issues,
                    "DUPLICATE_APPLICATION_ID",
                    ERROR,
                    equipment_id,
                    f"{application_path}.id",
                    "Application IDs must be unique within an equipment record.",
                    referenced_id=application_id,
                )
            application_ids.add(application_id)

    for application_index, application in enumerate(applications):
        if not isinstance(application, dict):
            continue
        application_path = f"applications[{application_index}]"
        assertions = application.get("state_assertions", [])
        if not isinstance(assertions, list):
            continue
        seen_assertions: dict[tuple[str, tuple[tuple[str, str], ...]], bool] = {}
        for assertion_index, assertion in enumerate(assertions):
            if not isinstance(assertion, dict):
                continue
            assertion_path = f"{application_path}.state_assertions[{assertion_index}]"
            state = assertion.get("state")
            value = assertion.get("value")
            if state not in {"installed", "available"}:
                _issue(
                    issues,
                    "INVALID_APPLICATION_STATE",
                    ERROR,
                    equipment_id,
                    f"{assertion_path}.state",
                    "Application Model v1 state must be 'installed' or 'available'.",
                    referenced_id=state if isinstance(state, str) else None,
                )
                continue
            if not isinstance(value, bool):
                _issue(
                    issues,
                    "INVALID_APPLICATION_STATE_VALUE",
                    ERROR,
                    equipment_id,
                    f"{assertion_path}.value",
                    "Application state assertion value must be boolean.",
                )
                continue

            conditions = assertion.get("conditions")
            if conditions is None:
                normalized_conditions: tuple[tuple[str, str], ...] = ()
            elif not isinstance(conditions, list):
                continue
            elif not conditions:
                _issue(
                    issues,
                    "EMPTY_APPLICATION_CONDITIONS",
                    ERROR,
                    equipment_id,
                    f"{assertion_path}.conditions",
                    "Empty application conditions must be omitted.",
                )
                continue
            else:
                condition_keys: list[tuple[str, str]] = []
                for condition_index, condition in enumerate(conditions):
                    if not isinstance(condition, dict):
                        continue
                    kind = condition.get("kind")
                    condition_value = condition.get("value")
                    if not isinstance(kind, str) or not kind or not isinstance(condition_value, str) or not condition_value:
                        continue
                    condition_key = _condition_key(condition)
                    if condition_key in condition_keys:
                        _issue(
                            issues,
                            "DUPLICATE_APPLICATION_CONDITION",
                            ERROR,
                            equipment_id,
                            f"{assertion_path}.conditions[{condition_index}]",
                            "Application conditions must be unique after canonicalization.",
                        )
                    condition_keys.append(condition_key)
                    if kind == "application" and condition_value not in application_ids:
                        _issue(
                            issues,
                            "INVALID_APPLICATION_REFERENCE",
                            ERROR,
                            equipment_id,
                            f"{assertion_path}.conditions[{condition_index}].value",
                            "Application condition must reference an application ID in the same equipment record.",
                            referenced_id=condition_value,
                        )
                normalized_conditions = tuple(sorted(condition_keys))

            assertion_key = (state, normalized_conditions)
            if assertion_key in seen_assertions:
                code = "CONTRADICTORY_APPLICATION_ASSERTION" if seen_assertions[assertion_key] != value else "DUPLICATE_APPLICATION_ASSERTION"
                message = (
                    "Application assertions with the same state and conditions cannot disagree."
                    if code == "CONTRADICTORY_APPLICATION_ASSERTION"
                    else "Duplicate application state assertions are not allowed."
                )
                _issue(issues, code, ERROR, equipment_id, assertion_path, message)
            else:
                seen_assertions[assertion_key] = value


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

    for index, capability in enumerate(equipment.get("amplifier_output_capabilities", [])):
        if not isinstance(capability, dict):
            continue
        for group_index, group in enumerate(capability.get("member_groups", [])):
            if not isinstance(group, list):
                continue
            for member_index, member_id in enumerate(group):
                internal(
                    member_id,
                    interface_ids,
                    f"amplifier_output_capabilities[{index}].member_groups[{group_index}][{member_index}]",
                )

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


def _validate_amplifier_capabilities(
    equipment: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Validate cross-field consistency for Schema 3.8 amplifier output capabilities."""
    equipment_id = equipment.get("id", "<missing-id>")
    capabilities = equipment.get("amplifier_output_capabilities", [])
    if not isinstance(capabilities, list):
        return

    interfaces_by_id = {
        interface.get("id"): interface
        for interface in equipment.get("interfaces", [])
        if isinstance(interface, dict) and isinstance(interface.get("id"), str)
    }

    seen_capability_ids: set[str] = set()
    for index, capability in enumerate(capabilities):
        if not isinstance(capability, dict):
            continue
        base_path = f"amplifier_output_capabilities[{index}]"
        capability_id = capability.get("id")
        if isinstance(capability_id, str):
            if capability_id in seen_capability_ids:
                _issue(
                    issues,
                    "DUPLICATE_AMPLIFIER_CAPABILITY_ID",
                    ERROR,
                    equipment_id,
                    f"{base_path}.id",
                    f"Duplicate amplifier output capability ID '{capability_id}'.",
                    referenced_id=capability_id,
                )
            seen_capability_ids.add(capability_id)

        topology = capability.get("topology")
        member_groups = capability.get("member_groups", [])
        if isinstance(member_groups, list):
            for group_index, group in enumerate(member_groups):
                if not isinstance(group, list):
                    continue
                group_path = f"{base_path}.member_groups[{group_index}]"
                if topology == "independent":
                    if len(group) != 1:
                        _issue(
                            issues,
                            "AMPLIFIER_ARITY_INDEPENDENT",
                            ERROR,
                            equipment_id,
                            group_path,
                            f"Amplifier capability '{capability_id}': independent topology requires exactly 1 member per group.",
                            topology=topology,
                        )
                elif topology in ("bridge", "parallel", "bridge_parallel"):
                    if len(group) < 2:
                        _issue(
                            issues,
                            "AMPLIFIER_ARITY_COMBINED",
                            ERROR,
                            equipment_id,
                            group_path,
                            f"Amplifier capability '{capability_id}': topology '{topology}' requires at least 2 members per group.",
                            topology=topology,
                        )
                for member_id in group:
                    interface = interfaces_by_id.get(member_id) if isinstance(member_id, str) else None
                    if not isinstance(interface, dict):
                        continue
                    direction = interface.get("direction")
                    if isinstance(direction, str) and direction not in ("output", "bidirectional"):
                        _issue(
                            issues,
                            "AMPLIFIER_MEMBER_NOT_OUTPUT",
                            ERROR,
                            equipment_id,
                            group_path,
                            f"Amplifier capability '{capability_id}': member '{member_id}' is not an output-capable interface.",
                            referenced_id=member_id if isinstance(member_id, str) else None,
                        )
                    signals = interface.get("signals", [])
                    has_audio = any(
                        isinstance(signal, dict) and signal.get("signal_type") == "audio"
                        for signal in signals
                    ) if isinstance(signals, list) else False
                    if not has_audio:
                        _issue(
                            issues,
                            "AMPLIFIER_MEMBER_SIGNAL_UNDECLARED",
                            WARNING,
                            equipment_id,
                            group_path,
                            f"Amplifier capability '{capability_id}': member '{member_id}' declares no audio signal.",
                            referenced_id=member_id if isinstance(member_id, str) else None,
                        )

        operating_points = capability.get("operating_points", [])
        if isinstance(operating_points, list):
            seen_point_ids: set[str] = set()
            for point_index, point in enumerate(operating_points):
                if not isinstance(point, dict):
                    continue
                point_path = f"{base_path}.operating_points[{point_index}]"
                point_id = point.get("id")
                if isinstance(point_id, str):
                    if point_id in seen_point_ids:
                        _issue(
                            issues,
                            "DUPLICATE_AMPLIFIER_OPERATING_POINT_ID",
                            ERROR,
                            equipment_id,
                            f"{point_path}.id",
                            f"Amplifier capability '{capability_id}': duplicate operating point ID '{point_id}' within the capability.",
                            referenced_id=point_id,
                        )
                    seen_point_ids.add(point_id)
                load = point.get("load")
                if isinstance(load, dict):
                    load_type = load.get("type")
                    if load_type == "low_impedance":
                        impedance = load.get("impedance")
                        if isinstance(impedance, dict):
                            unit = impedance.get("unit")
                            if isinstance(unit, str) and unit != "ohm":
                                _issue(
                                    issues,
                                    "AMPLIFIER_LOAD_UNIT_INVALID",
                                    ERROR,
                                    equipment_id,
                                    f"{point_path}.load.impedance.unit",
                                    f"Amplifier capability '{capability_id}': low_impedance load requires unit 'ohm'.",
                                    referenced_id=unit,
                                )
                    elif load_type == "constant_voltage":
                        voltage = load.get("voltage")
                        if isinstance(voltage, dict):
                            unit = voltage.get("unit")
                            if isinstance(unit, str) and unit != "volt":
                                _issue(
                                    issues,
                                    "AMPLIFIER_LOAD_UNIT_INVALID",
                                    ERROR,
                                    equipment_id,
                                    f"{point_path}.load.voltage.unit",
                                    f"Amplifier capability '{capability_id}': constant_voltage load requires unit 'volt'.",
                                    referenced_id=unit,
                                )
                ratings = point.get("ratings", [])
                if isinstance(ratings, list):
                    for rating_index, rating in enumerate(ratings):
                        if not isinstance(rating, dict):
                            continue
                        rating_path = f"{point_path}.ratings[{rating_index}]"
                        rating_type = rating.get("type")
                        if isinstance(rating_type, str) and rating_type not in ("maximum", "continuous"):
                            _issue(
                                issues,
                                "AMPLIFIER_RATING_TYPE_UNKNOWN",
                                WARNING,
                                equipment_id,
                                f"{rating_path}.type",
                                f"Amplifier capability '{capability_id}': unknown rating type '{rating_type}'.",
                                referenced_id=rating_type,
                            )
                        power = rating.get("power")
                        if isinstance(power, dict):
                            unit = power.get("unit")
                            if isinstance(unit, str) and unit != "watt":
                                _issue(
                                    issues,
                                    "AMPLIFIER_POWER_UNIT_INVALID",
                                    ERROR,
                                    equipment_id,
                                    f"{rating_path}.power.unit",
                                    f"Amplifier capability '{capability_id}': power rating requires unit 'watt'.",
                                    referenced_id=unit,
                                )


_ELECTRICAL_UNITS = {
    "voltage": {"volt", "volt-rms"},
    "current": {"ampere", "milliampere"},
    "power": {"watt"},
}


def _semantic_value(value: Any) -> str:
    """Canonicalize unordered membership for semantic duplicate checks."""

    if isinstance(value, dict):
        return json.dumps(
            {
                key: _semantic_value(child)
                for key, child in sorted(value.items())
                if key != "id"
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(value, list):
        items = [_semantic_value(item) for item in value]
        return json.dumps(sorted(items), separators=(",", ":"))
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _scope_signature(scope: dict[str, Any]) -> tuple[Any, ...]:
    return (
        scope.get("mode"),
        tuple(sorted(scope.get("interface_ids", []), key=repr)) if isinstance(scope.get("interface_ids"), list) else (),
        tuple(sorted(scope.get("named_members", []), key=repr)) if isinstance(scope.get("named_members"), list) else (),
    )


def _quantity_signature(quantity: Any) -> tuple[Any, ...] | None:
    if not isinstance(quantity, dict):
        return None
    if "value" in quantity:
        return (
            "scalar",
            quantity.get("value"),
            quantity.get("unit"),
            quantity.get("precision"),
            quantity.get("semantic_role"),
        )
    return (
        "range",
        (quantity.get("minimum"), quantity.get("maximum")),
        quantity.get("unit"),
        quantity.get("precision"),
        quantity.get("semantic_role"),
    )


def _validate_electrical_quantity(
    quantity: Any,
    dimension: str,
    equipment_id: str,
    path: str,
    issues: list[dict[str, Any]],
) -> None:
    if not isinstance(quantity, dict):
        return
    unit = quantity.get("unit")
    if isinstance(unit, str) and unit not in _ELECTRICAL_UNITS[dimension]:
        _issue(
            issues,
            "ELECTRICAL_QUANTITY_UNIT_INVALID",
            ERROR,
            equipment_id,
            f"{path}.unit",
            f"Electrical {dimension} quantity uses incompatible unit '{unit}'.",
            referenced_id=unit,
            dimension=dimension,
        )
    if "value" in quantity and quantity.get("precision") == "range":
        _issue(
            issues,
            "ELECTRICAL_QUANTITY_PRECISION_INVALID",
            ERROR,
            equipment_id,
            f"{path}.precision",
            "Scalar electrical quantities cannot use range precision.",
            dimension=dimension,
        )
    if "minimum" in quantity and "maximum" in quantity:
        minimum = quantity.get("minimum")
        maximum = quantity.get("maximum")
        if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)) and minimum > maximum:
            _issue(
                issues,
                "ELECTRICAL_QUANTITY_RANGE_INVALID",
                ERROR,
                equipment_id,
                path,
                "Electrical quantity range minimum cannot exceed maximum.",
                dimension=dimension,
            )


def _validate_electrical_operating_cases(
    equipment: dict[str, Any],
    issues: list[dict[str, Any]],
) -> None:
    """Validate Schema 3.10 neutral electrical operating cases."""

    equipment_id = equipment.get("id", "<missing-id>")
    power = equipment.get("power", {})
    if not isinstance(power, dict):
        return
    sources = power.get("sources", [])
    cases = power.get("operating_cases", [])
    if not isinstance(sources, list) or not isinstance(cases, list):
        return

    source_by_id: dict[str, dict[str, Any]] = {}
    for source_index, source in enumerate(sources):
        if not isinstance(source, dict):
            continue
        source_id = source.get("id")
        if isinstance(source_id, str):
            source_by_id.setdefault(source_id, source)
        modes = source.get("modes", [])
        if not isinstance(modes, list):
            continue
        mode_ids: set[str] = set()
        for mode_index, mode in enumerate(modes):
            if not isinstance(mode, dict):
                continue
            mode_id = mode.get("id")
            mode_path = f"power.sources[{source_index}].modes[{mode_index}]"
            if not isinstance(mode_id, str):
                continue
            if mode_id in mode_ids:
                _issue(
                    issues,
                    "DUPLICATE_POWER_SOURCE_MODE_ID",
                    ERROR,
                    equipment_id,
                    f"{mode_path}.id",
                    "Power source mode IDs must be unique within their source.",
                    referenced_id=mode_id,
                )
            mode_ids.add(mode_id)

    interfaces = {
        interface.get("id")
        for interface in equipment.get("interfaces", [])
        if isinstance(interface, dict) and isinstance(interface.get("id"), str)
    }
    case_ids: set[str] = set()
    case_signatures: dict[str, str] = {}
    for case_index, operating_case in enumerate(cases):
        if not isinstance(operating_case, dict):
            continue
        case_path = f"power.operating_cases[{case_index}]"
        case_id = operating_case.get("id")
        if isinstance(case_id, str):
            if case_id in case_ids:
                _issue(
                    issues,
                    "DUPLICATE_ELECTRICAL_OPERATING_CASE_ID",
                    ERROR,
                    equipment_id,
                    f"{case_path}.id",
                    "Electrical operating-case IDs must be unique within an equipment record.",
                    referenced_id=case_id,
                )
            case_ids.add(case_id)

        upstream = operating_case.get("upstream", {})
        source_id = upstream.get("source_id") if isinstance(upstream, dict) else None
        mode_id = upstream.get("mode_id") if isinstance(upstream, dict) else None
        source = source_by_id.get(source_id) if isinstance(source_id, str) else None
        if source is None and isinstance(source_id, str):
            _issue(
                issues,
                "INVALID_POWER_OPERATING_SOURCE_REFERENCE",
                ERROR,
                equipment_id,
                f"{case_path}.upstream.source_id",
                "Operating-case source_id must reference a declared power source.",
                referenced_id=source_id,
            )
        elif isinstance(mode_id, str):
            mode_ids = {
                mode.get("id")
                for mode in source.get("modes", [])
                if isinstance(mode, dict) and isinstance(mode.get("id"), str)
            }
            if mode_id not in mode_ids:
                _issue(
                    issues,
                    "INVALID_POWER_OPERATING_MODE_REFERENCE",
                    ERROR,
                    equipment_id,
                    f"{case_path}.upstream.mode_id",
                    "Operating-case mode_id must reference a mode belonging to its source_id.",
                    referenced_id=mode_id,
                )

        downstream = operating_case.get("downstream_capabilities", [])
        if not isinstance(downstream, list):
            continue
        downstream_ids: set[str] = set()
        semantic_capabilities: list[str] = []
        group_quantities: dict[tuple[Any, ...], dict[str, tuple[Any, ...] | None]] = {}
        for capability_index, capability in enumerate(downstream):
            if not isinstance(capability, dict):
                continue
            capability_path = f"{case_path}.downstream_capabilities[{capability_index}]"
            capability_id = capability.get("id")
            if isinstance(capability_id, str):
                if capability_id in downstream_ids:
                    _issue(
                        issues,
                        "DUPLICATE_DOWNSTREAM_CAPABILITY_ID",
                        ERROR,
                        equipment_id,
                        f"{capability_path}.id",
                        "Downstream capability IDs must be unique within an operating case.",
                        referenced_id=capability_id,
                    )
                downstream_ids.add(capability_id)

            scope = capability.get("scope")
            if not isinstance(scope, dict):
                continue
            interface_ids = scope.get("interface_ids", [])
            named_members = scope.get("named_members", [])
            if not isinstance(interface_ids, list):
                interface_ids = []
            if not isinstance(named_members, list):
                named_members = []
            if len(interface_ids) != len({_semantic_value(item) for item in interface_ids}):
                _issue(
                    issues,
                    "DUPLICATE_ELECTRICAL_INTERFACE_MEMBER",
                    ERROR,
                    equipment_id,
                    f"{capability_path}.scope.interface_ids",
                    "Electrical scope interface IDs must be unique.",
                )
            if len(named_members) != len({_semantic_value(item) for item in named_members}):
                _issue(
                    issues,
                    "DUPLICATE_ELECTRICAL_NAMED_MEMBER",
                    ERROR,
                    equipment_id,
                    f"{capability_path}.scope.named_members",
                    "Electrical scope named members must be unique.",
                )
            for member_index, member_id in enumerate(interface_ids):
                if isinstance(member_id, str) and member_id not in interfaces:
                    _issue(
                        issues,
                        "INVALID_ELECTRICAL_INTERFACE_REFERENCE",
                        ERROR,
                        equipment_id,
                        f"{capability_path}.scope.interface_ids[{member_index}]",
                        "Electrical scope interface ID must reference an equipment interface.",
                        referenced_id=member_id,
                    )
            resolved = scope.get("member_ids_resolved")
            if resolved is True and not interface_ids:
                _issue(
                    issues,
                    "RESOLVED_ELECTRICAL_SCOPE_MISSING_IDS",
                    ERROR,
                    equipment_id,
                    f"{capability_path}.scope",
                    "Resolved electrical scope requires interface_ids.",
                )
            if resolved is False and not named_members:
                _issue(
                    issues,
                    "UNRESOLVED_ELECTRICAL_SCOPE_MISSING_NAMES",
                    ERROR,
                    equipment_id,
                    f"{capability_path}.scope",
                    "Unresolved electrical scope requires named_members.",
                )
            if not interface_ids and not named_members:
                _issue(
                    issues,
                    "EMPTY_ELECTRICAL_SCOPE",
                    ERROR,
                    equipment_id,
                    f"{capability_path}.scope",
                    "Electrical scope must identify at least one member.",
                )

            quantity_signatures: dict[str, tuple[Any, ...] | None] = {}
            for dimension in ("voltage", "current", "power"):
                quantity = capability.get(dimension)
                if quantity is not None:
                    _validate_electrical_quantity(quantity, dimension, equipment_id, f"{capability_path}.{dimension}", issues)
                quantity_signatures[dimension] = _quantity_signature(quantity)
            semantic_payload = dict(capability)
            semantic_key = _semantic_value(semantic_payload)
            if semantic_key in semantic_capabilities:
                _issue(
                    issues,
                    "DUPLICATE_DOWNSTREAM_CAPABILITY",
                    ERROR,
                    equipment_id,
                    capability_path,
                    "Downstream capabilities with identical semantic content are duplicates.",
                )
            semantic_capabilities.append(semantic_key)

            group_key = (capability.get("resource"), _scope_signature(scope))
            previous = group_quantities.setdefault(group_key, {})
            for dimension, signature in quantity_signatures.items():
                if signature is None:
                    continue
                if dimension in previous and previous[dimension] != signature:
                    current_precision = signature[3]
                    prior_precision = previous[dimension][3]
                    if current_precision == prior_precision:
                        _issue(
                            issues,
                            "CONTRADICTORY_ELECTRICAL_CAPABILITY",
                            ERROR,
                            equipment_id,
                            capability_path,
                            "Equivalent electrical scope and precision declare incompatible quantities.",
                            dimension=dimension,
                        )
                else:
                    previous[dimension] = signature

        case_signature = _semantic_value({
            "upstream": upstream,
            "downstream_capabilities": sorted(semantic_capabilities),
        })
        if case_signature in case_signatures:
            _issue(
                issues,
                "DUPLICATE_ELECTRICAL_OPERATING_CASE",
                ERROR,
                equipment_id,
                case_path,
                "Electrical operating cases with identical semantic content are duplicates.",
                referenced_id=case_signatures[case_signature],
            )
        elif isinstance(case_id, str):
            case_signatures[case_signature] = case_id


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
        _validate_applications(record, issues)
        _validate_references(record, ids_by_type, equipment_index, issues)
        _validate_vocabularies(record, vocabularies, issues)
        _validate_electrical_variants(record, issues)
        _validate_electrical_operating_cases(record, issues)
        _validate_amplifier_capabilities(record, issues)

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
