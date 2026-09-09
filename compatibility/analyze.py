#!/usr/bin/env python3
"""Conservative v0.1 catalog compatibility analyzer for AVForge."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


FINAL_RESULTS = {
    "COMPATIBLE",
    "INCOMPATIBLE",
    "CONDITIONALLY_COMPATIBLE",
    "INSUFFICIENT_DATA",
}
LAYER_NAMES = (
    "physical",
    "electrical",
    "signal",
    "protocol",
    "direction",
    "restrictions",
    "capacity",
)
SCOPES = {"CATALOG"}
INTERCONNECT_ASSUMPTIONS = {"DIRECT", "APPROPRIATE_MEDIUM"}


class AnalysisInputError(ValueError):
    """Raised when the request or loaded catalog cannot be analyzed."""


def _layer(applicable: bool, result: str | None = None, reasons: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {"applicable": applicable}
    if applicable:
        if result not in FINAL_RESULTS:
            raise ValueError(f"Invalid layer result: {result}")
        value["result"] = result
        value["reasons"] = reasons or []
    return value


def _required_text(mapping: Any, field: str, path: str) -> str:
    if not isinstance(mapping, dict) or not isinstance(mapping.get(field), str) or not mapping[field]:
        raise AnalysisInputError(f"{path}.{field} must be a non-empty string")
    return mapping[field]


def _validate_request(request: Any) -> None:
    if not isinstance(request, dict):
        raise AnalysisInputError("Request must be an object")
    for field in ("source", "target"):
        _required_text(request.get(field), "equipment_id", field)
        _required_text(request.get(field), "interface_id", field)
    function = request.get("requested_function")
    if not isinstance(function, dict):
        raise AnalysisInputError("requested_function must be an object")
    if not any(function.get(field) is not None for field in ("signal_type", "signal_family", "protocol_family")):
        raise AnalysisInputError(
            "requested_function must contain signal_type, signal_family, or protocol_family"
        )
    for field in ("signal_type", "signal_family", "protocol_family", "signal_format", "direction"):
        if field in function and not isinstance(function[field], str):
            raise AnalysisInputError(f"requested_function.{field} must be a string")
    if "capacity_requirement" in function:
        if not isinstance(function["capacity_requirement"], dict) or not function["capacity_requirement"]:
            raise AnalysisInputError("requested_function.capacity_requirement must be a non-empty object")
        for key, value in function["capacity_requirement"].items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                raise AnalysisInputError(f"capacity_requirement.{key} must be a non-negative number")
    holder = request.get("electrical_requirements")
    if holder is not None:
        if not isinstance(holder, dict):
            raise AnalysisInputError("electrical_requirements must be an object")
        if "balance_mode" in holder and holder["balance_mode"] not in ("balanced", "unbalanced"):
            raise AnalysisInputError('electrical_requirements.balance_mode must be "balanced" or "unbalanced"')
    scope = request.get("analysis_scope")
    if scope not in SCOPES:
        raise AnalysisInputError("analysis_scope must be CATALOG in v0.1")
    if request.get("interconnect_assumption") not in INTERCONNECT_ASSUMPTIONS:
        raise AnalysisInputError(
            "interconnect_assumption must be DIRECT or APPROPRIATE_MEDIUM"
        )


def _index_records(records: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(records, list) or not records:
        raise AnalysisInputError("records must be a non-empty list of equipment objects")
    index: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
            raise AnalysisInputError("Every equipment record must have a non-empty id")
        if record["id"] in index:
            raise AnalysisInputError(f"Duplicate equipment id: {record['id']}")
        index[record["id"]] = record
    return index


def _resolve_interfaces(request: dict[str, Any], records: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved = []
    for side in ("source", "target"):
        reference = request[side]
        equipment = records.get(reference["equipment_id"])
        if equipment is None:
            raise AnalysisInputError(f"{side} equipment does not exist: {reference['equipment_id']}")
        interface = next(
            (item for item in equipment.get("interfaces", []) if item.get("id") == reference["interface_id"]),
            None,
        )
        if interface is None:
            raise AnalysisInputError(
                f"{side} interface does not exist: {reference['equipment_id']}/{reference['interface_id']}"
            )
        resolved.append({"equipment": equipment, "interface": interface})
    return resolved[0], resolved[1]


def _signals(interface: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in interface.get("signals", []) if isinstance(item, dict)]


def _matches_requirements(signal: dict[str, Any], function: dict[str, Any]) -> bool:
    for field in ("signal_type", "signal_family", "signal_format"):
        required = function.get(field)
        if required is not None and signal.get(field) != required:
            return False
    return True


def _matching_signals(interface: dict[str, Any], function: dict[str, Any]) -> list[dict[str, Any]]:
    return [signal for signal in _signals(interface) if _matches_requirements(signal, function)]


def _signal_constraint_state(signal_value: Any, required: Any) -> str | None:
    if required is None:
        return None
    if signal_value is None:
        return "unknown"
    if signal_value == required:
        return "satisfied"
    return "contradicted"


def _side_signal_evidence(interface: dict[str, Any], function: dict[str, Any]) -> str:
    signals = _signals(interface)
    if not signals:
        return "unknown"
    requested = [field for field in ("signal_type", "signal_family", "signal_format") if function.get(field) is not None]
    if not requested:
        return "unknown"
    supported = False
    all_contradicted = True
    for item in signals:
        states = [_signal_constraint_state(item.get(field), function.get(field)) for field in requested]
        if all(state == "satisfied" for state in states):
            supported = True
            break
        if not any(state == "contradicted" for state in states):
            all_contradicted = False
    if supported:
        return "supported"
    if all_contradicted:
        return "contradicted"
    return "unknown"


def _selected_signal(side: dict[str, Any], function: dict[str, Any], side_name: str) -> dict[str, Any] | None:
    candidates = _matching_signals(side["interface"], function)
    required_direction = "output" if side_name == "source" else "input"
    directional_candidates = [
        signal
        for signal in candidates
        if signal.get("direction") in {required_direction, "bidirectional"}
    ]
    if len(directional_candidates) != 1:
        return None
    return directional_candidates[0]


def _signal_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    applicable = any(function.get(field) is not None for field in ("signal_type", "signal_family", "signal_format"))
    if not applicable:
        return _layer(False)
    source_evidence = _side_signal_evidence(source["interface"], function)
    target_evidence = _side_signal_evidence(target["interface"], function)
    if source_evidence == "supported" and target_evidence == "supported":
        return _layer(True, "COMPATIBLE")
    if source_evidence == "contradicted" or target_evidence == "contradicted":
        return _layer(True, "INCOMPATIBLE", ["Requested signal requirements are contradicted by one or both interfaces."])
    return _layer(True, "INSUFFICIENT_DATA", ["Required signal data is not declared for both interfaces."])


def _communication_capabilities(record: dict[str, Any], protocol: str, interface_id: str) -> tuple[list[dict[str, Any]], bool]:
    matches = []
    excluded = False
    for capability in record.get("communication_capabilities", []):
        if not isinstance(capability, dict) or capability.get("protocol_family") != protocol:
            continue
        assignment = capability.get("interface_assignment") or {}
        allowed = assignment.get("allowed_interface_ids", [])
        if interface_id in allowed:
            matches.append(capability)
        else:
            excluded = True
    return matches, excluded


def _protocol_coverage_complete(record: dict[str, Any]) -> bool:
    coverage = record.get("catalog_coverage")
    if not isinstance(coverage, dict):
        return False
    protocols = coverage.get("communication_protocols")
    return isinstance(protocols, dict) and protocols.get("complete") is True


def _protocol_support(side: dict[str, Any], protocol: str) -> tuple[str, list[str], list[dict[str, Any]]]:
    interface = side["interface"]
    record = side["equipment"]
    interface_id = interface.get("id", "")
    signals = _signals(interface)
    signal_supports = any(signal.get("protocol_family") == protocol for signal in signals)
    other_protocol_signal = any(
        signal.get("protocol_family") is not None and signal.get("protocol_family") != protocol
        for signal in signals
    )
    unknown_signal_route = any(signal.get("protocol_family") is None for signal in signals)
    capabilities, excluded = _communication_capabilities(record, protocol, interface_id)
    if excluded and not capabilities:
        return "INCOMPATIBLE", [f"Protocol {protocol} is explicitly assigned away from interface {interface_id}."], []
    available = [capability for capability in capabilities if capability.get("availability") in (None, "available")]
    conditional = [capability for capability in capabilities if capability.get("availability") == "conditional"]
    unavailable = [capability for capability in capabilities if capability.get("availability") == "unavailable"]
    unknown_signal_route = any(signal.get("protocol_family") is None for signal in signals)
    evidence = [signal for signal in signals if signal.get("protocol_family") == protocol] + capabilities
    if available or (signal_supports and not unavailable and not conditional):
        return "COMPATIBLE", [], evidence
    if signal_supports and unavailable:
        return "INCOMPATIBLE", [f"Protocol {protocol} is explicitly unavailable for interface {interface_id}."], evidence
    if conditional:
        return "CONDITIONALLY_COMPATIBLE", [f"Protocol {protocol} has a documented conditional availability."], evidence
    if signal_supports:
        return "COMPATIBLE", [], evidence
    if unavailable or other_protocol_signal:
        if unknown_signal_route:
            return "INSUFFICIENT_DATA", [f"Protocol {protocol} is not declared for interface {interface_id}."], evidence
        if unavailable:
            return "INCOMPATIBLE", [f"Protocol {protocol} is explicitly unavailable for interface {interface_id}."], evidence
        return "INCOMPATIBLE", [f"Interface {interface_id} explicitly declares a different protocol."], evidence
    if _protocol_coverage_complete(record):
        return "INCOMPATIBLE", [f"Protocol {protocol} is absent from the complete catalog protocol coverage."], []
    return "INSUFFICIENT_DATA", [f"Protocol {protocol} is not declared for interface {interface_id}."], evidence


def _protocol_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    protocol = function.get("protocol_family")
    if protocol is None:
        return _layer(False), []
    source_result, source_reasons, source_evidence = _protocol_support(source, protocol)
    target_result, target_reasons, target_evidence = _protocol_support(target, protocol)
    if "INCOMPATIBLE" in (source_result, target_result):
        result = "INCOMPATIBLE"
    elif "INSUFFICIENT_DATA" in (source_result, target_result):
        result = "INSUFFICIENT_DATA"
    elif "CONDITIONALLY_COMPATIBLE" in (source_result, target_result):
        result = "CONDITIONALLY_COMPATIBLE"
    else:
        result = "COMPATIBLE"
    return _layer(True, result, source_reasons + target_reasons), source_evidence + target_evidence


def _role_acceptable(direction: Any, side_name: str, required: str | None) -> bool:
    if side_name == "source":
        if required == "input":
            return direction == "input"
        if required == "output":
            return direction == "output"
        return direction in ("output", "bidirectional")
    if required == "input":
        return direction == "input"
    if required == "output":
        return direction == "output"
    return direction in ("input", "bidirectional")


def _side_direction_state(side: dict[str, Any], function: dict[str, Any], side_name: str, required: str | None) -> tuple[bool | None, bool]:
    signals = _matching_signals(side["interface"], function)
    protocol = function.get("protocol_family")
    if protocol:
        signals = [signal for signal in signals if signal.get("protocol_family") == protocol]
    if signals:
        if required in ("input", "output"):
            values = {signal.get("direction") for signal in signals if signal.get("direction")}
            if not values:
                return None, False
            if any(_role_acceptable(value, side_name, required) for value in values):
                return True, False
            return False, False
        selected = _selected_signal(side, function, side_name)
        if selected is not None and selected.get("direction"):
            if _role_acceptable(selected["direction"], side_name, required):
                return True, False
            return False, False
        if any(_role_acceptable(signal.get("direction"), side_name, required) for signal in signals if signal.get("direction")):
            return None, False
        if any(signal.get("direction") for signal in signals):
            return False, False
        return None, False
    if protocol:
        capabilities, _ = _communication_capabilities(side["equipment"], protocol, side["interface"].get("id", ""))
        values = {capability.get("direction") for capability in capabilities if capability.get("direction")}
        if values:
            if required in ("input", "output"):
                if any(_role_acceptable(value, side_name, required) for value in values):
                    return True, False
                return False, False
            if (side_name == "source" and ("output" in values or "bidirectional" in values)) or (
                side_name == "target" and ("input" in values or "bidirectional" in values)
            ):
                return True, False
            return False, False
    direction = side["interface"].get("direction")
    if not direction:
        return None, False
    return _role_acceptable(direction, side_name, required), False


def _direction_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    required = function.get("direction")
    if required and required not in {"input", "output", "bidirectional"}:
        return _layer(True, "INSUFFICIENT_DATA", [f"Requested direction is not deterministically interpretable: {required}."])
    if required == "bidirectional":
        required = None
    source_state, source_conditional = _side_direction_state(source, function, "source", required)
    target_state, target_conditional = _side_direction_state(target, function, "target", required)
    if source_state is False or target_state is False:
        return _layer(True, "INCOMPATIBLE", ["Source and target directions are not complementary."])
    if source_state is None or target_state is None:
        return _layer(True, "INSUFFICIENT_DATA", ["Direction is not declared for both interfaces."])
    if source_conditional or target_conditional:
        return _layer(True, "CONDITIONALLY_COMPATIBLE", ["A documented interface assignment is required."])
    return _layer(True, "COMPATIBLE")


def _passive_interconnection_status(interface: dict[str, Any]) -> str | None:
    capabilities = interface.get("physical_connection_capabilities")
    if not isinstance(capabilities, dict):
        return None
    passive = capabilities.get("passive_interconnection")
    if not isinstance(passive, dict):
        return None
    status = passive.get("status")
    if status in ("supported", "unsupported"):
        return status
    return None


def _physical_layer(source: dict[str, Any], target: dict[str, Any], assumption: str) -> dict[str, Any]:
    source_interface = source["interface"]
    target_interface = target["interface"]
    if assumption == "APPROPRIATE_MEDIUM":
        source_status = _passive_interconnection_status(source_interface)
        target_status = _passive_interconnection_status(target_interface)
        if source_status == "unsupported" and target_status == "unsupported":
            return _layer(True, "INCOMPATIBLE", ["Both interfaces declare passive interconnection as unsupported."])
        if source_status == "unsupported":
            return _layer(True, "INCOMPATIBLE", ["Source interface declares passive interconnection as unsupported."])
        if target_status == "unsupported":
            return _layer(True, "INCOMPATIBLE", ["Target interface declares passive interconnection as unsupported."])
        if source_status == "supported" and target_status == "supported":
            return _layer(True, "COMPATIBLE", ["Both interfaces declare passive interconnection as supported."])
        if source_status is None and target_status is None:
            return _layer(True, "INSUFFICIENT_DATA", ["Passive interconnection capability is not declared for both interfaces."])
        if source_status is None:
            return _layer(True, "INSUFFICIENT_DATA", ["Passive interconnection capability is not declared for the source interface."])
        return _layer(True, "INSUFFICIENT_DATA", ["Passive interconnection capability is not declared for the target interface."])
    source_connector = source_interface.get("connector")
    target_connector = target_interface.get("connector")
    if not isinstance(source_connector, str) or not isinstance(target_connector, str):
        return _layer(True, "INSUFFICIENT_DATA", ["Connector identity is not declared for both interfaces."])
    if source_connector != target_connector:
        return _layer(True, "INCOMPATIBLE", ["Direct mating requires the same connector identity."])
    source_gender = source_interface.get("connector_gender")
    target_gender = target_interface.get("connector_gender")
    if source_gender not in {"male", "female", "receptacle"} or target_gender not in {"male", "female", "receptacle"}:
        return _layer(True, "INSUFFICIENT_DATA", ["Connector gender is not sufficient to establish direct mating."])
    if {source_gender, target_gender} <= {"male", "female"}:
        return _layer(True, "COMPATIBLE") if source_gender != target_gender else _layer(True, "INCOMPATIBLE", ["Two identical connector genders cannot mate directly."])
    if "male" in {source_gender, target_gender} and ("female" in {source_gender, target_gender} or "receptacle" in {source_gender, target_gender}):
        return _layer(True, "COMPATIBLE")
    return _layer(True, "INCOMPATIBLE", ["The connector genders do not establish direct mating."])


def _characteristics(signal: dict[str, Any]) -> dict[str, Any]:
    value = signal.get("signal_characteristics")
    return value if isinstance(value, dict) else {}


def _electrical_profile(interface: dict[str, Any], role: str) -> dict[str, Any] | None:
    characteristics = interface.get("electrical_characteristics")
    if not isinstance(characteristics, dict):
        return None
    profile = characteristics.get("output" if role == "source" else "input")
    return profile if isinstance(profile, dict) else None


def _resolve_electrical_profile(profile: dict[str, Any], mode: str) -> tuple[dict[str, Any] | None, str | None]:
    base = {key: value for key, value in profile.items() if key != "variants"}
    variants = profile.get("variants", [])
    if "variants" not in profile:
        return base, None
    if not isinstance(variants, list):
        return None, "variants-not-a-list"
    matches = [
        item for item in variants
        if isinstance(item, dict) and isinstance(item.get("conditions"), dict)
        and item["conditions"].get("balance_mode") == mode
    ]
    if len(matches) > 1:
        return None, "duplicate-variant"
    if not matches:
        return base, None
    variant = matches[0]
    for key in ("maximum_level", "impedance"):
        if key in variant and key in base:
            return None, "base-variant-conflict"
    resolved = dict(base)
    for key in ("maximum_level", "impedance"):
        if key in variant:
            resolved[key] = variant[key]
    return resolved, None


def _measurement_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    amount = value.get("value")
    unit = value.get("unit")
    if isinstance(amount, (int, float)) and isinstance(unit, str):
        return f"{amount} {unit}"
    return None


def _requested_balance_mode(request: dict[str, Any]) -> str | None:
    requirements = request.get("electrical_requirements")
    if isinstance(requirements, dict) and requirements.get("balance_mode") in ("balanced", "unbalanced"):
        return requirements["balance_mode"]
    return None


def _evaluate_electrical_scenario(
    source_profile: dict[str, Any],
    target_profile: dict[str, Any],
    mode: str,
) -> tuple[str, list[str]]:
    source_resolved, source_issue = _resolve_electrical_profile(source_profile, mode)
    target_resolved, target_issue = _resolve_electrical_profile(target_profile, mode)
    if source_issue is not None or target_issue is not None:
        return "INSUFFICIENT_DATA", ["Electrical variant resolution is structurally inconsistent for the evaluated balance mode."]
    assert source_resolved is not None and target_resolved is not None
    source_modes = source_profile.get("balance_modes")
    target_modes = target_profile.get("balance_modes")
    if isinstance(source_modes, list) and mode not in source_modes:
        return "INCOMPATIBLE", [f"Source does not support balance mode {mode}."]
    if isinstance(target_modes, list) and mode not in target_modes:
        return "INCOMPATIBLE", [f"Target does not support balance mode {mode}."]
    if not isinstance(source_modes, list) or not isinstance(target_modes, list):
        return "INSUFFICIENT_DATA", ["Balance mode capability is not declared for both endpoints."]
    source_levels = source_resolved.get("operating_level_classes")
    target_levels = target_resolved.get("operating_level_classes")
    if isinstance(source_levels, list) and isinstance(target_levels, list):
        overlap = sorted(set(source_levels) & set(target_levels))
        if not overlap:
            return "INCOMPATIBLE", ["Operating level classes do not overlap for the evaluated balance mode."]
    else:
        return "INSUFFICIENT_DATA", ["Operating level classes are not declared for both endpoints."]
    overlap = sorted(set(source_levels) & set(target_levels))
    source_minimum = source_resolved.get("minimum_load_impedance")
    if isinstance(source_minimum, dict) and "value" in source_minimum and "unit" in source_minimum:
        target_nominal = (target_resolved.get("impedance") or {}) if isinstance(target_resolved.get("impedance"), dict) else {}
        nominal = target_nominal.get("nominal")
        if not isinstance(nominal, dict) or nominal.get("unit") != source_minimum.get("unit") or not isinstance(nominal.get("value"), (int, float)):
            return "INSUFFICIENT_DATA", ["Target input impedance is not sufficient to evaluate the declared source minimum load."]
        if nominal["value"] < source_minimum["value"]:
            return "INCOMPATIBLE", ["Target input impedance is below the declared source minimum load."]
    reasons = [f"Balance mode {mode} is supported by both endpoints with operating level overlap {overlap}."]
    maximum = _measurement_text(source_resolved.get("maximum_level")) or _measurement_text(target_resolved.get("maximum_level"))
    if maximum is not None:
        reasons.append(f"Maximum level {maximum} is informational.")
    nominal_levels = source_resolved.get("nominal_levels") or target_resolved.get("nominal_levels")
    if isinstance(nominal_levels, list) and nominal_levels:
        reasons.append("Nominal levels are informational.")
    impedance = source_resolved.get("impedance") or target_resolved.get("impedance")
    if isinstance(impedance, dict) and impedance:
        reasons.append("Impedance data is informational.")
    if isinstance(source_resolved.get("phantom_power"), dict) or isinstance(target_resolved.get("phantom_power"), dict):
        reasons.append("Phantom power data is informational.")
    return "COMPATIBLE", reasons


def _electrical_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any], request: dict[str, Any] | None = None) -> dict[str, Any]:
    if function.get("signal_family") != "analog-audio":
        return _layer(False)
    if _selected_signal(source, function, "source") is None or _selected_signal(target, function, "target") is None:
        return _layer(True, "INSUFFICIENT_DATA", ["Analog electrical comparison requires one unambiguous signal per connection role."])
    source_profile = _electrical_profile(source["interface"], "source")
    target_profile = _electrical_profile(target["interface"], "target")
    if source_profile is None or target_profile is None:
        return _layer(True, "INSUFFICIENT_DATA", ["Required analog electrical characteristics are not declared."])
    requested = _requested_balance_mode(request or {})
    if requested is not None:
        state, reasons = _evaluate_electrical_scenario(source_profile, target_profile, requested)
        return _layer(True, state, reasons)
    source_modes = source_profile.get("balance_modes")
    target_modes = target_profile.get("balance_modes")
    if isinstance(source_modes, list) and isinstance(target_modes, list):
        common = sorted(set(source_modes) & set(target_modes))
        if not common:
            return _layer(True, "INCOMPATIBLE", ["No common balance mode is declared by both endpoints."])
        results = [(_evaluate_electrical_scenario(source_profile, target_profile, mode), mode) for mode in common]
        compatible = [(reasons, mode) for (state, reasons), mode in results if state == "COMPATIBLE"]
        if compatible:
            reasons, modes = [], []
            for scenario_reasons, mode in compatible:
                modes.append(mode)
                reasons.extend(scenario_reasons)
            return _layer(True, "COMPATIBLE", [f"Compatible balance mode(s): {sorted(modes)}."] + reasons)
        if any(state == "INCOMPATIBLE" for (state, _), _ in results):
            reasons: list[str] = []
            for (state, scenario_reasons), mode in results:
                if state == "INCOMPATIBLE":
                    reasons.extend(scenario_reasons)
            return _layer(True, "INCOMPATIBLE", reasons)
        reasons = []
        for (_, scenario_reasons), _ in results:
            reasons.extend(scenario_reasons)
        return _layer(True, "INSUFFICIENT_DATA", reasons)
    return _layer(True, "INSUFFICIENT_DATA", ["Balance mode capability is not declared for both endpoints."])


def _selector_match_state(selector: dict[str, Any], target: dict[str, Any], interface_id: str) -> bool | None:
    equipment = target["equipment"]
    interface = target["interface"]
    checks = {
        "equipment_id": equipment.get("id"),
        "manufacturer": equipment.get("manufacturer"),
        "model": equipment.get("model"),
        "product_family": equipment.get("product_family"),
        "remote_interface_id": interface_id,
        "remote_interface_role": interface.get("role"),
    }
    matched = False
    for key, actual in checks.items():
        if key not in selector:
            continue
        matched = True
        if actual is None:
            return None
        if actual != selector[key]:
            return False
    return True if matched else None


def _restriction_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    applicable = False
    unknown = False
    exhaustive_excluded: str | None = None
    for owner, remote, remote_side in ((source, target, "target"), (target, source, "source")):
        constraints = owner["interface"].get("connection_constraints")
        if not isinstance(constraints, dict):
            continue
        constraint_protocol = constraints.get("protocol_family")
        requested_protocol = function.get("protocol_family")
        if constraint_protocol and requested_protocol and constraint_protocol != requested_protocol:
            continue
        if constraint_protocol and not requested_protocol:
            continue
        applicable = True
        remote_interface_id = remote["interface"].get("id", "")
        for selector in (constraints.get("denied_targets") or {}).get("targets", []):
            if not isinstance(selector, dict):
                continue
            state = _selector_match_state(selector, remote, remote_interface_id)
            if state is True:
                return _layer(True, "INCOMPATIBLE", [f"Explicit denied restriction applies from {remote_side}."])
            if state is None:
                unknown = True
        allowed = (constraints.get("allowed_targets") or {}).get("targets")
        if allowed is not None and (constraints.get("allowed_targets") or {}).get("exhaustive"):
            states = [
                _selector_match_state(selector, remote, remote_interface_id)
                for selector in allowed
                if isinstance(selector, dict)
            ]
            if not any(state is True for state in states):
                if any(state is None for state in states):
                    unknown = True
                elif exhaustive_excluded is None:
                    exhaustive_excluded = remote["equipment"].get("id")
    if exhaustive_excluded is not None:
        return _layer(True, "INCOMPATIBLE", [f"Exhaustive allowed restriction excludes {exhaustive_excluded}."])
    if unknown:
        return _layer(True, "INSUFFICIENT_DATA", ["Restriction references metadata that is not declared."])
    if not applicable:
        return _layer(False)
    return _layer(True, "COMPATIBLE", [])


SUPPORTED_CAPACITY_DIMENSIONS = ("rx_channels", "tx_channels", "streams", "sessions", "endpoints")


def _capacity_number(value: Any) -> float | int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _relevant_capacity_capabilities(record: dict[str, Any], interface_id: str, protocol: str | None) -> list[dict[str, Any]]:
    relevant = []
    for capability in record.get("communication_capabilities", []):
        if not isinstance(capability, dict):
            continue
        if protocol is not None and capability.get("protocol_family") != protocol:
            continue
        allowed = (capability.get("interface_assignment") or {}).get("allowed_interface_ids", [])
        if interface_id not in allowed:
            continue
        relevant.append(capability)
    return relevant


def _resolve_pool_limits(record: dict[str, Any], pool_id: Any) -> tuple[dict[str, float | int] | None, bool]:
    if pool_id is None:
        return None, False
    pool = next(
        (item for item in record.get("resource_pools", []) if isinstance(item, dict) and item.get("id") == pool_id),
        None,
    )
    if pool is None or not isinstance(pool.get("resources"), dict):
        return None, True
    limits: dict[str, float | int] = {}
    for dimension in SUPPORTED_CAPACITY_DIMENSIONS:
        value = _capacity_number(pool["resources"].get(dimension))
        if value is not None:
            limits[dimension] = value
    return limits, False


def _route_dimension_state(
    capability_limits: dict[str, float | int],
    pool_limits: dict[str, float | int] | None,
    pool_broken: bool,
    dimension: str,
    required: float | int,
) -> str:
    own = capability_limits.get(dimension)
    pooled = pool_limits.get(dimension) if pool_limits is not None else None
    if own is not None and pooled is not None:
        return "supported" if min(own, pooled) >= required else "contradicted"
    if own is not None:
        if own < required:
            return "contradicted"
        if pool_broken:
            return "unknown"
        return "supported"
    if pooled is not None:
        return "supported" if pooled >= required else "contradicted"
    return "unknown"


def _evaluate_capacity_route(
    record: dict[str, Any],
    capability: dict[str, Any],
    dimensions: list[str],
    requirement: dict[str, Any],
) -> str:
    capability_limits: dict[str, float | int] = {}
    own = capability.get("capacity")
    if isinstance(own, dict):
        for dimension in SUPPORTED_CAPACITY_DIMENSIONS:
            value = _capacity_number(own.get(dimension))
            if value is not None:
                capability_limits[dimension] = value
    pool_limits, pool_broken = _resolve_pool_limits(record, capability.get("resource_pool_id"))
    contradicted = False
    unknown = False
    for dimension in dimensions:
        state = _route_dimension_state(
            capability_limits, pool_limits, pool_broken, dimension, requirement[dimension]
        )
        if state == "contradicted":
            contradicted = True
        elif state == "unknown":
            unknown = True
    if contradicted:
        return "contradicted"
    if unknown:
        return "unknown"
    return "supported"


def _side_capacity_state(
    side: dict[str, Any], dimensions: list[str], requirement: dict[str, Any], protocol: str | None
) -> str:
    record = side["equipment"]
    interface_id = side["interface"].get("id", "")
    routes = _relevant_capacity_capabilities(record, interface_id, protocol)
    if not routes:
        return "unknown"
    states = [_evaluate_capacity_route(record, capability, dimensions, requirement) for capability in routes]
    if any(state == "supported" for state in states):
        return "supported"
    if any(state == "unknown" for state in states):
        return "unknown"
    return "contradicted"


def _capacity_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    requirement = function.get("capacity_requirement")
    if requirement is None:
        return _layer(False)
    dimensions = [key for key in requirement if key in SUPPORTED_CAPACITY_DIMENSIONS]
    unsupported = [key for key in requirement if key not in SUPPORTED_CAPACITY_DIMENSIONS]
    protocol = function.get("protocol_family")
    source_state = _side_capacity_state(source, dimensions, requirement, protocol) if dimensions else "unknown"
    target_state = _side_capacity_state(target, dimensions, requirement, protocol) if dimensions else "unknown"
    if source_state == "contradicted" or target_state == "contradicted":
        keys = sorted({key for key in dimensions if key in requirement})
        return _layer(True, "INCOMPATIBLE", [f"Requested {keys} exceeds declared catalog capacity."])
    if unsupported or source_state == "unknown" or target_state == "unknown":
        if unsupported:
            return _layer(True, "INSUFFICIENT_DATA", ["Requested capacity dimension is not supported by Capacity v1."])
        return _layer(True, "INSUFFICIENT_DATA", ["Requested catalog capacity is not declared for both endpoints."])
    return _layer(True, "COMPATIBLE")


def _evidence(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for owner, remote in ((source, target), (target, source)):
        for relation in owner["equipment"].get("known_compatibilities", []):
            if not isinstance(relation, dict):
                continue
            if relation.get("local_interface_id") not in (None, owner["interface"].get("id")):
                continue
            if relation.get("remote_interface_id") not in (None, remote["interface"].get("id")):
                continue
            if relation.get("protocol_family") not in (None, function.get("protocol_family")):
                continue
            selector = {
                "equipment_id": remote["equipment"].get("id"),
                "model": remote["equipment"].get("model"),
                "product_family": remote["equipment"].get("product_family"),
            }
            if any(relation.get(key) is not None and relation.get(key) != value for key, value in selector.items()):
                continue
            result.append({"equipment_id": owner["equipment"].get("id"), "compatibility": relation})
    return result


def _aggregate(layers: dict[str, dict[str, Any]]) -> str:
    results = [layer["result"] for layer in layers.values() if layer.get("applicable")]
    for result in ("INCOMPATIBLE", "INSUFFICIENT_DATA", "CONDITIONALLY_COMPATIBLE"):
        if result in results:
            return result
    return "COMPATIBLE"


def analyze(request: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    """Analyze a catalog request and return the normative result object."""
    _validate_request(request)
    record_index = _index_records(records)
    source, target = _resolve_interfaces(request, record_index)
    function = request["requested_function"]
    protocol_layer, protocol_evidence = _protocol_layer(source, target, function)
    layers = {
        "physical": _physical_layer(source, target, request["interconnect_assumption"]),
        "electrical": _electrical_layer(source, target, function, request),
        "signal": _signal_layer(source, target, function),
        "protocol": protocol_layer,
        "direction": _direction_layer(source, target, function),
        "restrictions": _restriction_layer(source, target, function),
        "capacity": _capacity_layer(source, target, function),
    }
    evidence = protocol_evidence + _evidence(source, target, function)
    reasons = [reason for layer in layers.values() for reason in layer.get("reasons", [])]
    conditions = [reason for layer in layers.values() if layer.get("result") == "CONDITIONALLY_COMPATIBLE" for reason in layer.get("reasons", [])]
    missing_data = [reason for layer in layers.values() if layer.get("result") == "INSUFFICIENT_DATA" for reason in layer.get("reasons", [])]
    return {
        "source": request["source"],
        "target": request["target"],
        "requested_function": function,
        "analysis_scope": request["analysis_scope"],
        "interconnect_assumption": request["interconnect_assumption"],
        "result": _aggregate(layers),
        "layers": layers,
        "reasons": reasons,
        "conditions": conditions,
        "missing_data": missing_data,
        "evidence": evidence,
    }


def _load_records(paths: list[str]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        try:
            value = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError) as error:
            raise AnalysisInputError(f"Unable to load {path}: {error}") from error
        if not isinstance(value, dict):
            raise AnalysisInputError(f"Equipment file must contain an object: {path}")
        records.append(value)
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze AVForge catalog compatibility.")
    parser.add_argument("--equipment", nargs="+", required=True, help="Equipment JSON records to load")
    parser.add_argument("--source-equipment", required=True)
    parser.add_argument("--source-interface", required=True)
    parser.add_argument("--target-equipment", required=True)
    parser.add_argument("--target-interface", required=True)
    parser.add_argument("--requested-function", required=True, help="Requested function as a JSON object")
    parser.add_argument("--analysis-scope", required=True)
    parser.add_argument("--interconnect-assumption", required=True)
    args = parser.parse_args(argv)
    try:
        requested_function = json.loads(args.requested_function)
        request = {
            "source": {"equipment_id": args.source_equipment, "interface_id": args.source_interface},
            "target": {"equipment_id": args.target_equipment, "interface_id": args.target_interface},
            "requested_function": requested_function,
            "analysis_scope": args.analysis_scope,
            "interconnect_assumption": args.interconnect_assumption,
        }
        result = analyze(request, _load_records(args.equipment))
    except (AnalysisInputError, json.JSONDecodeError) as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
