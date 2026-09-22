"""Deterministic, exact source-unit normalization for Mapping inputs.

Facts remain source-semantic records. This module creates a derived value
that a mapping planner may use when a canonical vocabulary unit is required.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping

from .extraction import validate_extraction, validate_fact_record


UNIT_NORMALIZATION_VERSION = "1.0"


class UnitNormalizationError(ValueError):
    """Raised when a normalized value cannot be validated deterministically."""


@dataclass(frozen=True)
class ConversionRule:
    """An explicitly registered exact source-to-canonical conversion."""

    rule_id: str
    source_unit: str
    canonical_unit: str
    dimension: str
    numerator: int
    denominator: int
    exact: bool = True

    @property
    def factor(self) -> Decimal:
        return Decimal(self.numerator) / Decimal(self.denominator)


EXACT_CONVERSION_RULES: tuple[ConversionRule, ...] = (
    ConversionRule(
        rule_id="mass:gram-to-kilogram",
        source_unit="g",
        canonical_unit="kilogram",
        dimension="mass",
        numerator=1,
        denominator=1000,
    ),
    ConversionRule(
        rule_id="current:milliampere-to-ampere",
        source_unit="milliampere",
        canonical_unit="ampere",
        dimension="current",
        numerator=1,
        denominator=1000,
    ),
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise UnitNormalizationError(message)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    except (TypeError, ValueError) as exc:
        raise UnitNormalizationError("value must be JSON serializable") from exc


def _decimal(value: Any, name: str) -> Decimal:
    _require(isinstance(value, (int, float, str)) and not isinstance(value, bool), f"{name} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise UnitNormalizationError(f"{name} must be a finite decimal") from exc
    _require(result.is_finite(), f"{name} must be a finite decimal")
    return result


def _decimal_text(value: Decimal) -> str:
    _require(value.is_finite(), "normalized value must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _convert_value(value: Any, factor: Decimal) -> Any:
    if isinstance(value, dict):
        _require(set(value) == {"minimum", "maximum"}, "range value requires minimum and maximum")
        return {
            key: _decimal_text(_decimal(value[key], f"value.{key}") * factor)
            for key in ("minimum", "maximum")
        }
    return _decimal_text(_decimal(value, "value") * factor)


def _rule_for(
    source_unit: str,
    canonical_unit: str,
    dimension: str,
    rules: Iterable[ConversionRule],
) -> ConversionRule:
    matches = [
        rule
        for rule in rules
        if rule.source_unit == source_unit and rule.canonical_unit == canonical_unit
    ]
    if not matches and source_unit == canonical_unit:
        canonical_units = {
            rule.canonical_unit
            for rule in EXACT_CONVERSION_RULES
            if rule.dimension == dimension
        }
        _require(
            len(canonical_units) == 1 and canonical_unit in canonical_units,
            "canonical identity unit is not registered for the dimension",
        )
        return ConversionRule(
            rule_id=f"identity:{dimension}:{canonical_unit}",
            source_unit=source_unit,
            canonical_unit=canonical_unit,
            dimension=dimension,
            numerator=1,
            denominator=1,
        )
    _require(len(matches) == 1, "no unique exact conversion rule exists")
    rule = matches[0]
    _require(rule.exact, "conversion rule is not exact")
    _require(rule.dimension == dimension, "conversion rule dimension is incompatible")
    _require(rule.numerator > 0 and rule.denominator > 0, "conversion rule factor must be positive")
    return rule


def _validate_canonical_unit(canonical_unit: str, canonical_unit_ids: Iterable[str]) -> None:
    _require(isinstance(canonical_unit, str) and bool(canonical_unit.strip()), "canonical unit is required")
    _require(canonical_unit in set(canonical_unit_ids), "canonical unit is not in the units vocabulary")


def _path(value_path: Iterable[str] | None) -> tuple[str, ...]:
    if value_path is None:
        return ()
    result = tuple(value_path)
    _require(bool(result) and all(isinstance(part, str) and bool(part.strip()) for part in result), "value_path must contain non-empty property names")
    return result


def _at_path(value: Any, value_path: tuple[str, ...]) -> dict[str, Any]:
    current = value
    for part in value_path:
        _require(isinstance(current, dict) and part in current, "value_path does not identify a nested quantity")
        current = current[part]
    _require(isinstance(current, dict), "value_path must identify a quantity object")
    return current


def _nested_quantity_value(quantity: Mapping[str, Any]) -> Any:
    _require("unit" in quantity, "nested quantity requires unit")
    _require("value" in quantity or {"minimum", "maximum"}.issubset(quantity), "nested quantity requires value or minimum and maximum")
    _require(not ("value" in quantity and ("minimum" in quantity or "maximum" in quantity)), "nested quantity cannot mix scalar and range fields")
    if "value" in quantity:
        return quantity["value"]
    return {"minimum": quantity["minimum"], "maximum": quantity["maximum"]}


def _convert_at_path(value: Any, value_path: tuple[str, ...], factor: Decimal, canonical_unit: str) -> dict[str, Any]:
    result = deepcopy(value)
    quantity = _at_path(result, value_path)
    converted = _convert_value(_nested_quantity_value(quantity), factor)
    quantity["unit"] = canonical_unit
    if isinstance(converted, dict):
        quantity.pop("value", None)
        quantity["minimum"] = converted["minimum"]
        quantity["maximum"] = converted["maximum"]
    else:
        quantity.pop("minimum", None)
        quantity.pop("maximum", None)
        quantity["value"] = converted
    return result


def normalize_fact(
    fact: Mapping[str, Any],
    *,
    dimension: str,
    canonical_unit: str,
    canonical_unit_ids: Iterable[str],
    rules: Iterable[ConversionRule] = EXACT_CONVERSION_RULES,
    value_path: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Derive one exact canonical value without mutating the source Fact."""

    source = dict(fact)
    canonical_units = set(canonical_unit_ids)
    conversion_rules = tuple(rules)
    nested_path = _path(value_path)
    validate_fact_record(source)
    _require(isinstance(dimension, str) and bool(dimension.strip()), "dimension is required")
    _validate_canonical_unit(canonical_unit, canonical_units)
    _require("value" in source, "fact must contain a value")
    _require(source["semantic_precision"] not in {"unknown", "not-rated"}, "fact has no normalizable value")
    if nested_path:
        nested_quantity = _at_path(source["value"], nested_path)
        source_unit = nested_quantity.get("unit")
        _require(isinstance(source_unit, str) and bool(source_unit.strip()), "nested quantity unit is required")
    else:
        _require("unit" in source, "fact must contain a unit")
        source_unit = source["unit"]
        _require(isinstance(source_unit, str) and bool(source_unit.strip()), "fact.unit is required")
    rule = _rule_for(source_unit, canonical_unit, dimension, conversion_rules)
    canonical_value = _convert_at_path(source["value"], nested_path, rule.factor, canonical_unit) if nested_path else _convert_value(source["value"], rule.factor)
    result = {
        "normalization_version": UNIT_NORMALIZATION_VERSION,
        "fact_id": source["fact_id"],
        "dimension": dimension,
        "source_value": source["value"],
        "source_unit": source_unit,
        "canonical_value": canonical_value,
        "canonical_unit": canonical_unit,
        "conversion": {
            "rule_id": rule.rule_id,
            "exact": rule.exact,
            "factor_numerator": rule.numerator,
            "factor_denominator": rule.denominator,
        },
        "semantic_precision": source["semantic_precision"],
        "qualifiers": json.loads(_canonical_json(source.get("qualifiers", {}))),
        "conditions": json.loads(_canonical_json(source.get("conditions", []))),
    }
    if nested_path:
        result["value_path"] = list(nested_path)
    validate_normalized_value(result, source, canonical_unit_ids=canonical_units, rules=conversion_rules)
    return result


def normalize_extraction_fact(
    extraction_result: Mapping[str, Any],
    fact_id: str,
    *,
    dimension: str,
    canonical_unit: str,
    canonical_unit_ids: Iterable[str],
    rules: Iterable[ConversionRule] = EXACT_CONVERSION_RULES,
    value_path: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Normalize a Fact found in a validated Fact Extraction result."""

    result = dict(extraction_result)
    validate_extraction(result)
    facts = {fact["fact_id"]: fact for fact in result["facts"]}
    _require(fact_id in facts, "fact_id is not present in the extraction result")
    return normalize_fact(
        facts[fact_id],
        dimension=dimension,
        canonical_unit=canonical_unit,
        canonical_unit_ids=canonical_unit_ids,
        rules=rules,
        value_path=value_path,
    )


def validate_normalized_value(
    normalized: Mapping[str, Any],
    fact: Mapping[str, Any],
    *,
    canonical_unit_ids: Iterable[str],
    rules: Iterable[ConversionRule] = EXACT_CONVERSION_RULES,
) -> None:
    """Validate provenance, rule identity, dimensions, and derived values."""

    source = dict(fact)
    canonical_units = set(canonical_unit_ids)
    conversion_rules = tuple(rules)
    validate_fact_record(source)
    value = dict(normalized)
    expected_keys = {
        "normalization_version", "fact_id", "dimension", "source_value", "source_unit",
        "canonical_value", "canonical_unit", "conversion", "semantic_precision", "qualifiers", "conditions",
    }
    if "value_path" in value:
        expected_keys.add("value_path")
    _require(set(value) == expected_keys, "normalized value has unsupported or missing fields")
    _require(value["normalization_version"] == UNIT_NORMALIZATION_VERSION, "normalization version is unsupported")
    _require(value["fact_id"] == source["fact_id"], "normalized value references the wrong Fact")
    nested_path = _path(value.get("value_path"))
    _require(_canonical_json(value["source_value"]) == _canonical_json(source.get("value")), "source value does not match Fact")
    expected_source_unit = _at_path(source["value"], nested_path).get("unit") if nested_path else source.get("unit")
    _require(value["source_unit"] == expected_source_unit, "source unit does not match Fact")
    _require(value["semantic_precision"] == source["semantic_precision"], "semantic precision changed")
    _require(_canonical_json(value["qualifiers"]) == _canonical_json(source.get("qualifiers", {})), "qualifiers changed")
    _require(_canonical_json(value["conditions"]) == _canonical_json(source.get("conditions", [])), "conditions changed")
    _validate_canonical_unit(value["canonical_unit"], canonical_units)
    _require(isinstance(value["dimension"], str) and bool(value["dimension"].strip()), "normalized dimension is required")
    rule = _rule_for(value["source_unit"], value["canonical_unit"], value["dimension"], conversion_rules)
    conversion = value["conversion"]
    _require(conversion == {
        "rule_id": rule.rule_id,
        "exact": rule.exact,
        "factor_numerator": rule.numerator,
        "factor_denominator": rule.denominator,
    }, "conversion rule metadata is inconsistent")
    expected = _convert_at_path(source["value"], nested_path, rule.factor, value["canonical_unit"]) if nested_path else _convert_value(source["value"], rule.factor)
    _require(value["canonical_value"] == expected, "canonical value does not match conversion rule")


def serialize_normalized_value(normalized: Mapping[str, Any]) -> str:
    """Return deterministic JSON; decimal canonical values remain exact text."""

    return json.dumps(dict(normalized), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
