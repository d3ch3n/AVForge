import copy
import json
import unittest

from ingestion.extraction import make_fact, validate_extraction
from ingestion.unit_normalization import (
    ConversionRule,
    UnitNormalizationError,
    normalize_extraction_fact,
    normalize_fact,
    serialize_normalized_value,
    validate_normalized_value,
)


UNITS = {"kilogram", "watt"}


def fact(value=794, unit="g", precision="exact"):
    record = make_fact(
        subject={"kind": "equipment", "local_id": "fixture.equipment"},
        property="mass",
        value=value,
        unit=unit,
        qualifiers={"source": "fixture"},
        evidence_ids=["evidence-fixture"],
        semantic_precision=precision,
    )
    record["conditions"] = [{"kind": "fixture-mode", "value": "test"}]
    return record


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

    def test_fact_and_identity_remain_unchanged(self):
        source = fact()
        before = copy.deepcopy(source)
        result = normalize_fact(source, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=UNITS)
        self.assertEqual(source, before)
        self.assertEqual(result["fact_id"], source["fact_id"])
        self.assertNotIn("evidence", result)

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
