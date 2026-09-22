import copy
import json
import unittest
from pathlib import Path

from ingestion.extraction import make_fact, validate_extraction
from ingestion.mapping import make_semantic_bindings, make_target
from ingestion.unit_normalization import (
    ConversionRule,
    UnitNormalizationError,
    normalize_extraction_fact,
    normalize_fact,
    serialize_normalized_value,
    validate_normalized_value,
)


UNITS = {"kilogram", "watt", "ampere", "milliampere", "volt"}


def fact(value=794, unit="g", precision="exact", property_name="mass"):
    record = make_fact(
        subject={"kind": "equipment", "local_id": "fixture.equipment"},
        property=property_name,
        value=value,
        unit=unit,
        qualifiers={"source": "fixture"},
        evidence_ids=["evidence-fixture"],
        semantic_precision=precision,
    )
    record["conditions"] = [{"kind": "fixture-mode", "value": "test"}]
    return record


def nvm_extraction():
    return json.loads(Path(".ingestion/extractions/job-dd68d134838298d6188a.f11df7cccc204d0e3b64.json").read_text())


def extraction_with(record):
    result = {
        "extraction_version": "1.0",
        "job_id": "job-fixture",
        "identity": {"manufacturer": "Fixture", "canonical_model": "Model", "identity_status": "RESOLVED"},
        "sources": [{"source_id": "source-fixture", "source_type": "text", "canonicality": "official-canonical", "tier": 1, "path": "fixture.txt", "content_hash": "sha256:fixture"}],
        "facts": [record],
        "evidence": [{"evidence_id": "evidence-fixture", "source_id": "source-fixture", "source_sha256": "sha256:fixture", "locator": {"kind": "text", "line": 1}, "extracted_text_or_normalized_observation": "fixture", "extraction_method": "fixture"}],
        "conflicts": [],
        "issues": [],
        "extraction_status": "COMPLETED",
        "generated_at": "2026-01-01T00:00:00+00:00",
    }
    validate_extraction(result)
    return result


class UnitNormalizationTests(unittest.TestCase):
    def test_exact_mass_conversion_and_serialization(self):
        result = normalize_fact(fact(), dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(result["canonical_value"], "0.794")
        self.assertEqual(result["canonical_unit"], "kilogram")
        self.assertEqual(serialize_normalized_value(result), serialize_normalized_value(result))
        self.assertEqual(json.loads(serialize_normalized_value(result))["canonical_value"], "0.794")

    def test_exact_current_conversions(self):
        for source_value, expected in ((300, "0.3"), (900, "0.9"), (0, "0"), (1, "0.001"), (1000, "1"), (1500, "1.5")):
            result = normalize_fact(
                fact(value=source_value, unit="milliampere", property_name="current"),
                dimension="current",
                canonical_unit="ampere",
                canonical_unit_ids=UNITS,
            )
            self.assertEqual(result["canonical_value"], expected)
            self.assertEqual(json.loads(serialize_normalized_value(result))["canonical_value"], expected)

    def test_negative_current_conversion_is_deterministic(self):
        result = normalize_fact(
            fact(value=-300, unit="milliampere", property_name="current"),
            dimension="current",
            canonical_unit="ampere",
            canonical_unit_ids=UNITS,
        )
        self.assertEqual(result["canonical_value"], "-0.3")

    def test_canonical_current_is_unchanged_and_idempotent(self):
        source = fact(value=0.3, unit="ampere", property_name="current")
        first = normalize_fact(source, dimension="current", canonical_unit="ampere", canonical_unit_ids=UNITS)
        second = normalize_fact(source, dimension="current", canonical_unit="ampere", canonical_unit_ids=UNITS)
        self.assertEqual(first, second)
        self.assertEqual(first["canonical_value"], "0.3")
        self.assertEqual(first["canonical_unit"], "ampere")
        self.assertEqual(first["conversion"]["factor_numerator"], 1)
        self.assertEqual(first["conversion"]["factor_denominator"], 1)

    def test_identity_cannot_claim_ampere_is_voltage(self):
        with self.assertRaises(UnitNormalizationError):
            normalize_fact(
                fact(value=0.3, unit="ampere", property_name="voltage"),
                dimension="voltage",
                canonical_unit="ampere",
                canonical_unit_ids=UNITS,
            )

    def test_identity_requires_code_owned_dimension_canonical_pair(self):
        invalid = (
            ("current", "kilogram", "kilogram"),
            ("mass", "ampere", "ampere"),
            ("current", "milliampere", "milliampere"),
            ("mass", "g", "g"),
            ("made-up", "ampere", "ampere"),
        )
        for dimension, unit, canonical_unit in invalid:
            with self.subTest(dimension=dimension, unit=unit, canonical_unit=canonical_unit):
                with self.assertRaises(UnitNormalizationError):
                    normalize_fact(
                        fact(value=1, unit=unit, property_name="test"),
                        dimension=dimension,
                        canonical_unit=canonical_unit,
                        canonical_unit_ids=UNITS,
                    )

        with self.assertRaises(UnitNormalizationError):
            normalize_fact(
                fact(value=1, unit="made-up-unit", property_name="current"),
                dimension="current",
                canonical_unit="ampere",
                canonical_unit_ids=UNITS,
            )

    def test_canonical_mass_is_unchanged_and_idempotent(self):
        source = fact(value=0.794, unit="kilogram")
        first = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        second = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(first, second)
        self.assertEqual(first["canonical_value"], "0.794")
        self.assertEqual(first["canonical_unit"], "kilogram")

    def test_fact_and_identity_remain_unchanged(self):
        source = fact()
        before = copy.deepcopy(source)
        result = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(source, before)
        self.assertEqual(result["fact_id"], source["fact_id"])
        self.assertNotIn("evidence", result)

    def test_nested_nvm_quantity_preserves_fact_and_unrelated_values(self):
        extraction = nvm_extraction()
        source = next(fact for fact in extraction["facts"] if fact["fact_id"] == "fact-52cd85c2d8cf5a2959d68218")
        before = copy.deepcopy(source)
        result = normalize_extraction_fact(
            extraction,
            source["fact_id"],
            dimension="current",
            canonical_unit="ampere",
            canonical_unit_ids=UNITS,
            value_path=("downstream_output_capability", "current"),
        )
        capability = result["canonical_value"]["downstream_output_capability"]
        self.assertEqual(capability["current"], {"semantic_role": "supported_total", "unit": "ampere", "value": "0.3"})
        self.assertEqual(capability["voltage"], {"unit": "volt", "value": 5})
        self.assertEqual(result["canonical_value"]["upstream_power_mode"], source["value"]["upstream_power_mode"])
        self.assertEqual(result["source_unit"], "milliampere")
        self.assertEqual(result["value_path"], ["downstream_output_capability", "current"])
        self.assertEqual(result["semantic_precision"], "exact")
        self.assertEqual(source, before)
        self.assertEqual(source["polarity"], "POSITIVE_EXPLICIT")
        self.assertEqual(source["evidence_ids"], ["evidence-9203d04af8b5d2c9cdb1394c"])

        target = make_target(segments=[{"kind": "property", "name": "power"}])
        bindings = make_semantic_bindings(source, target=target, normalization=result)
        self.assertIn("value", {binding["dimension"] for binding in bindings})

    def test_nested_second_nvm_quantity_normalizes_without_touching_poe_or_voltage(self):
        extraction = nvm_extraction()
        source = next(fact for fact in extraction["facts"] if fact["fact_id"] == "fact-c269a624c1d3d48bb29946b7")
        result = normalize_extraction_fact(
            extraction,
            source["fact_id"],
            dimension="current",
            canonical_unit="ampere",
            canonical_unit_ids=UNITS,
            value_path=("downstream_output_capability", "current"),
        )
        value = result["canonical_value"]
        self.assertEqual(value["downstream_output_capability"]["current"]["value"], "0.9")
        self.assertEqual(value["downstream_output_capability"]["voltage"], {"unit": "volt", "value": 5})
        self.assertEqual(value["upstream_power_mode"], {"class": "5", "delivery": "PoE", "standard": "802.3bt", "type": "3"})
        self.assertEqual(value["downstream_output_capability"]["current"]["semantic_role"], "supported_total")

    def test_nested_value_path_is_explicit_and_shape_checked(self):
        extraction = nvm_extraction()
        with self.assertRaises(UnitNormalizationError):
            normalize_extraction_fact(
                extraction,
                "fact-52cd85c2d8cf5a2959d68218",
                dimension="current",
                canonical_unit="ampere",
                canonical_unit_ids=UNITS,
                value_path=("missing", "current"),
            )

        malformed = copy.deepcopy(extraction)
        source = next(fact for fact in malformed["facts"] if fact["fact_id"] == "fact-52cd85c2d8cf5a2959d68218")
        source["value"]["downstream_output_capability"]["current"]["minimum"] = 0
        with self.assertRaises(UnitNormalizationError):
            normalize_extraction_fact(
                malformed,
                source["fact_id"],
                dimension="current",
                canonical_unit="ampere",
                canonical_unit_ids=UNITS,
                value_path=("downstream_output_capability", "current"),
            )

    def test_precision_qualifiers_and_conditions_are_preserved(self):
        for precision in ("exact", "minimum", "maximum", "approximate", "nominal"):
            source = fact(precision=precision)
            result = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
            self.assertEqual(result["semantic_precision"], precision)
            self.assertEqual(result["qualifiers"], source["qualifiers"])
            self.assertEqual(result["conditions"], source["conditions"])

    def test_range_preserves_range_semantics(self):
        source = fact(value={"minimum": 794, "maximum": 1000}, precision="range")
        result = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(result["canonical_value"], {"minimum": "0.794", "maximum": "1"})

    def test_canonical_unit_must_exist(self):
        with self.assertRaises(UnitNormalizationError):
            normalize_fact(fact(), dimension="mass", canonical_unit="gram", canonical_unit_ids=UNITS)

    def test_unsupported_conversion_is_rejected(self):
        with self.assertRaises(UnitNormalizationError):
            normalize_fact(fact(unit="lb"), dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)

        with self.assertRaises(UnitNormalizationError):
            normalize_fact(fact(value=300, unit="milliampere", property_name="current"), dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)

    def test_wrong_dimension_does_not_apply_current_conversion(self):
        with self.assertRaises(UnitNormalizationError):
            normalize_fact(
                fact(value=300, unit="milliampere", property_name="voltage"),
                dimension="voltage",
                canonical_unit="volt",
                canonical_unit_ids=UNITS,
            )

    def test_incompatible_dimension_is_rejected(self):
        incompatible = ConversionRule("invalid", "g", "watt", "power", 1, 1000)
        with self.assertRaises(UnitNormalizationError):
            normalize_fact(fact(), dimension="mass", canonical_unit="watt", canonical_unit_ids=UNITS, rules=(incompatible,))

    def test_forged_and_mismatched_values_are_rejected(self):
        source = fact()
        result = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        forged = copy.deepcopy(result)
        forged["canonical_value"] = "0.795"
        with self.assertRaises(UnitNormalizationError):
            validate_normalized_value(forged, source, canonical_unit_ids=UNITS)
        mismatched = copy.deepcopy(result)
        mismatched["source_value"] = 795
        with self.assertRaises(UnitNormalizationError):
            validate_normalized_value(mismatched, source, canonical_unit_ids=UNITS)
        mismatched = copy.deepcopy(result)
        mismatched["source_unit"] = "kg"
        with self.assertRaises(UnitNormalizationError):
            validate_normalized_value(mismatched, source, canonical_unit_ids=UNITS)
        mismatched = copy.deepcopy(result)
        mismatched["semantic_precision"] = "minimum"
        with self.assertRaises(UnitNormalizationError):
            validate_normalized_value(mismatched, source, canonical_unit_ids=UNITS)
        mismatched = copy.deepcopy(result)
        mismatched["qualifiers"] = {"source": "forged"}
        with self.assertRaises(UnitNormalizationError):
            validate_normalized_value(mismatched, source, canonical_unit_ids=UNITS)
        mismatched = copy.deepcopy(result)
        mismatched["conditions"] = [{"kind": "forged"}]
        with self.assertRaises(UnitNormalizationError):
            validate_normalized_value(mismatched, source, canonical_unit_ids=UNITS)

    def test_missing_fact_and_extraction_provenance_are_rejected(self):
        source = fact()
        extraction = extraction_with(source)
        with self.assertRaises(UnitNormalizationError):
            normalize_extraction_fact(extraction, "fact-missing", dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        result = normalize_extraction_fact(extraction, source["fact_id"], dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(result["fact_id"], source["fact_id"])

    def test_malicious_unit_is_passive_data(self):
        with self.assertRaises(UnitNormalizationError):
            normalize_fact(fact(unit="__import__('os').system('false')"), dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)

    def test_repeated_normalization_is_identical_and_creates_no_fact_or_evidence(self):
        source = fact()
        first = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        second = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(first, second)
        self.assertEqual(first["fact_id"], source["fact_id"])
        self.assertEqual(set(first) & {"fact", "facts", "evidence"}, set())


if __name__ == "__main__":
    unittest.main()
