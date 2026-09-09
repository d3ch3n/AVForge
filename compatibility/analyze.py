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
    source_matches = _matching_signals(source["interface"], function)
    target_matches = _matching_signals(target["interface"], function)
    if source_matches and target_matches:
        return _layer(True, "COMPATIBLE")
    source_has_data = bool(_signals(source["interface"]))
    target_has_data = bool(_signals(target["interface"]))
    if source_has_data and target_has_data:
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
    signal_matches = [signal for signal in _signals(interface) if signal.get("protocol_family") == protocol]
    explicit_other_protocol = any(
        signal.get("protocol_family") is not None and signal.get("protocol_family") != protocol
        for signal in _signals(interface)
    )
    capabilities, excluded = _communication_capabilities(record, protocol, interface.get("id", ""))
    if excluded and not capabilities:
        return "INCOMPATIBLE", [f"Protocol {protocol} is explicitly assigned away from interface {interface['id']}."], []
    evidence = signal_matches + capabilities
    if not evidence:
        if explicit_other_protocol:
            return "INCOMPATIBLE", [f"Interface {interface['id']} explicitly declares a different protocol."] , []
        if _protocol_coverage_complete(record):
            return "INCOMPATIBLE", [f"Protocol {protocol} is absent from the complete catalog protocol coverage."] , []
        return "INSUFFICIENT_DATA", [f"Protocol {protocol} is not declared for interface {interface['id']}."] , []
    if any(capability.get("availability") == "unavailable" for capability in capabilities):
        return "INCOMPATIBLE", [f"Protocol {protocol} is explicitly unavailable."] , evidence
    if any((capability.get("interface_assignment") or {}).get("mode") == "configurable" for capability in capabilities):
        return "CONDITIONALLY_COMPATIBLE", [f"Protocol {protocol} requires interface assignment/configuration."] , evidence
    if any(capability.get("availability") == "conditional" for capability in capabilities):
        return "CONDITIONALLY_COMPATIBLE", [f"Protocol {protocol} has a documented conditional availability."] , evidence
    return "COMPATIBLE", [], evidence


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


def _direction_values(side: dict[str, Any], function: dict[str, Any]) -> tuple[set[str], bool]:
    signals = _matching_signals(side["interface"], function)
    protocol = function.get("protocol_family")
    if protocol:
        signals = [signal for signal in signals if signal.get("protocol_family") == protocol]
    configurable = False
    if signals:
        values = {signal.get("direction") for signal in signals if signal.get("direction")}
        configurable = any(signal.get("signal_characteristics", {}).get("configurable_role") for signal in signals)
        if values:
            return values, configurable
    if protocol:
        capabilities, _ = _communication_capabilities(side["equipment"], protocol, side["interface"].get("id", ""))
        values = {capability.get("direction") for capability in capabilities if capability.get("direction")}
        configurable = any(
            (capability.get("interface_assignment") or {}).get("mode") == "configurable"
            for capability in capabilities
        )
        if values:
            return values, configurable
    direction = side["interface"].get("direction")
    return ({direction} if direction else set()), configurable


def _direction_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    source_values, source_configurable = _direction_values(source, function)
    target_values, target_configurable = _direction_values(target, function)
    if not source_values or not target_values:
        return _layer(True, "INSUFFICIENT_DATA", ["Direction is not declared for both interfaces."])
    required = function.get("direction")
    if required and required not in {"input", "output", "bidirectional"}:
        return _layer(True, "INSUFFICIENT_DATA", [f"Requested direction is not deterministically interpretable: {required}."])
    source_can_output = "output" in source_values or "bidirectional" in source_values
    target_can_input = "input" in target_values or "bidirectional" in target_values
    if required == "input":
        source_can_output = "input" in source_values
        target_can_input = "input" in target_values
    if required == "output":
        source_can_output = "output" in source_values
        target_can_input = "output" in target_values
    if not source_can_output or not target_can_input:
        return _layer(True, "INCOMPATIBLE", ["Source and target directions are not complementary."])
    if source_configurable or target_configurable:
        return _layer(True, "CONDITIONALLY_COMPATIBLE", ["A documented input/output mode selection is required."])
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


def _electrical_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    if function.get("signal_family") != "analog-audio":
        return _layer(False)
    source_signal = _selected_signal(source, function, "source")
    target_signal = _selected_signal(target, function, "target")
    if source_signal is None or target_signal is None:
        return _layer(True, "INSUFFICIENT_DATA", ["Analog electrical comparison requires one unambiguous signal per connection role."])
    source_chars = _characteristics(source_signal)
    target_chars = _characteristics(target_signal)
    if not source_chars or not target_chars:
        return _layer(True, "INSUFFICIENT_DATA", ["Required analog electrical characteristics are not declared."])
    source_balanced = source_chars.get("balanced")
    target_balanced = target_chars.get("balanced")
    if source_balanced is not None and target_balanced is not None and source_balanced != target_balanced:
        return _layer(True, "CONDITIONALLY_COMPATIBLE", ["Balanced/unbalanced connection requires a documented wiring condition."])
    if source_balanced is None or target_balanced is None:
        return _layer(True, "INSUFFICIENT_DATA", ["Balanced/unbalanced behavior is not structured for both signals."])
    return _layer(True, "COMPATIBLE")


def _selector_matches(selector: dict[str, Any], target: dict[str, Any], interface_id: str) -> bool:
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
    return all(key not in selector or selector[key] == value for key, value in checks.items())


def _selector_role_unknown(selector: dict[str, Any], target: dict[str, Any]) -> bool:
    return "remote_interface_role" in selector and not target["interface"].get("role")


def _restriction_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    applicable = False
    reasons: list[str] = []
    conditional = False
    for owner, remote, remote_side in ((source, target, "target"), (target, source, "source")):
        constraints = owner["interface"].get("connection_constraints")
        if not isinstance(constraints, dict):
            continue
        protocol = constraints.get("protocol_family")
        if protocol and function.get("protocol_family") and protocol != function["protocol_family"]:
            continue
        applicable = True
        unknown_selector = False
        for selector in (constraints.get("denied_targets") or {}).get("targets", []):
            if not isinstance(selector, dict):
                continue
            if _selector_role_unknown(selector, remote):
                unknown_selector = True
            elif _selector_matches(selector, remote, remote["interface"].get("id", "")):
                return _layer(True, "INCOMPATIBLE", [f"Explicit denied restriction applies from {remote_side}."])
        allowed = (constraints.get("allowed_targets") or {}).get("targets")
        if allowed is not None and (constraints.get("allowed_targets") or {}).get("exhaustive"):
            if any(isinstance(selector, dict) and _selector_role_unknown(selector, remote) for selector in allowed):
                unknown_selector = True
            elif not any(isinstance(selector, dict) and _selector_matches(selector, remote, remote["interface"].get("id", "")) for selector in allowed):
                return _layer(True, "INCOMPATIBLE", [f"Exhaustive allowed restriction excludes {remote['equipment'].get('id')}."])
        if unknown_selector:
            return _layer(True, "INSUFFICIENT_DATA", ["Restriction references an interface role that is not declared."])
    if not applicable:
        return _layer(False)
    return _layer(True, "CONDITIONALLY_COMPATIBLE" if conditional else "COMPATIBLE", reasons)


def _capacity_for(side: dict[str, Any], function: dict[str, Any]) -> dict[str, float] | None:
    protocol = function.get("protocol_family")
    capabilities = []
    if protocol:
        capabilities, _ = _communication_capabilities(side["equipment"], protocol, side["interface"].get("id", ""))
        if not capabilities:
            return None
    else:
        capabilities = [item for item in side["equipment"].get("communication_capabilities", []) if isinstance(item, dict)]
    for capability in capabilities:
        capacity = capability.get("capacity")
        if isinstance(capacity, dict):
            return {key: value for key, value in capacity.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
        pool_id = capability.get("resource_pool_id")
        if pool_id:
            pool = next((item for item in side["equipment"].get("resource_pools", []) if item.get("id") == pool_id), None)
            if isinstance(pool, dict) and isinstance(pool.get("resources"), dict):
                return {key: value for key, value in pool["resources"].items() if isinstance(value, (int, float)) and not isinstance(value, bool)}
    return None


def _capacity_layer(source: dict[str, Any], target: dict[str, Any], function: dict[str, Any]) -> dict[str, Any]:
    requirement = function.get("capacity_requirement")
    if requirement is None:
        return _layer(False)
    source_capacity = _capacity_for(source, function)
    target_capacity = _capacity_for(target, function)
    if source_capacity is None or target_capacity is None:
        return _layer(True, "INSUFFICIENT_DATA", ["Requested catalog capacity is not declared for both endpoints."])
    for key, required in requirement.items():
        if key not in source_capacity or key not in target_capacity:
            return _layer(True, "INSUFFICIENT_DATA", [f"Catalog capacity does not declare required field: {key}."])
        if source_capacity[key] < required or target_capacity[key] < required:
            return _layer(True, "INCOMPATIBLE", [f"Requested {key} exceeds declared catalog capacity."])
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
        "electrical": _electrical_layer(source, target, function),
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
