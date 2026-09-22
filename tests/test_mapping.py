import copy
import json
import tempfile
import unittest
from pathlib import Path

from ingestion.extraction import build_extraction_result, make_conflict, make_evidence, make_fact
from ingestion.mapping import (
    MAPPING_STATES,
    build_mapping_result,
    compare_mappings,
    load_mapping_context,
    load_vocabularies,
    make_mapping,
    make_schema_gap,
    make_semantic_bindings,
    make_target,
    make_vocab_gap,
    validate_mapping_result,
    write_mapping,
)
from ingestion.unit_normalization import normalize_fact


VOCABS = {"connectors": {"hdmi-type-a"}, "units": {"watt", "kilogram", "ampere", "milliampere", "volt"}}


def source():
    return {
        "source_id": "source-fixture",
        "content_hash": "sha256:fixture",
        "tier": 1,
        "canonicality": "official-canonical",
        "source_type": "html",
        "final_url": "https://manufacturer.example/product",
    }


def extraction(*facts, conflicts=()):
    source_value = source()
    evidence = []
    for fact_value in facts:
        evidence.extend(
            make_evidence(
                source=source_value,
                locator={"kind": "html", "heading": fact_value["property"]},
                observation=fact_value["property"],
                extraction_method="fixture",
            )
            for _ in [0]
        )
    # Rebuild facts with the evidence generated above, preserving fixture order.
    rebuilt = []
    for fact_value, evidence_value in zip(facts, evidence):
        rebuilt.append(make_fact(evidence_ids=[evidence_value["evidence_id"]], **fact_value))
    return build_extraction_result(
        job_id="job-fixture",
        identity={"manufacturer": "Acme", "canonical_model": "Model X", "identity_status": "RESOLVED"},
        sources=[source_value],
        facts=rebuilt,
        evidence=evidence,
        conflicts=conflicts,
        observed_at="2026-01-01T00:00:00+00:00",
    )


def known_fact(property_name="maximum_power", value=100, **kwargs):
    return {
        "subject": {"kind": "interface", "local_id": "output-1", "direction": "output"},
        "property": property_name,
        "value": value,
        "unit": kwargs.pop("unit", "watt"),
        "qualifiers": kwargs.pop("qualifiers", {}),
        **kwargs,
    }


def unknown_fact(property_name="maximum_power"):
    return {
        "subject": {"kind": "interface", "local_id": "output-1", "direction": "output"},
        "property": property_name,
        "qualifiers": {},
        "semantic_precision": "unknown",
        "polarity": "UNKNOWN",
        "evidence_status": "UNKNOWN",
    }


def target(local_id="output-1"):
    return make_target(
        segments=[
            {"kind": "property", "name": "interfaces"},
            {"kind": "entity", "entity_kind": "interface", "key": {"kind": "local_id", "value": local_id}},
            {"kind": "property", "name": "maximum_power"},
        ],
        schema_ref="#/$defs/interface",
    )


def mapping_for(result, index=0, state="STRUCTURED", **kwargs):
    fact = result["facts"][index]
    if state == "STRUCTURED" and "target" not in kwargs:
        kwargs["target"] = target()
    if state == "STRUCTURED" and "semantic_bindings" not in kwargs:
        kwargs["semantic_bindings"] = make_semantic_bindings(fact, target=kwargs["target"])
    return make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state=state, **kwargs)


def mapping_result(result, mappings, **kwargs):
    observed_at = kwargs.pop("observed_at", "2026-01-01T00:00:00+00:00")
    return build_mapping_result(extraction_result=result, mappings=mappings, vocabularies=VOCABS, observed_at=observed_at, **kwargs)


def collection_fixture(members, sequence):
    result = extraction({
        "subject": {"kind": "equipment", "local_id": "fixture.equipment"},
        "property": "collection_fixture",
        "value": {
            "members": members,
            "quantity": {"unit": "g", "value": 794},
            "sequence": sequence,
        },
        "qualifiers": {},
    })
    fact = result["facts"][0]
    target_value = make_target(segments=[{"kind": "property", "name": "collection_fixture"}])
    normalized = normalize_fact(
        fact,
        dimension="mass",
        canonical_unit="kilogram",
        canonical_unit_ids=VOCABS["units"],
        value_path=("quantity",),
    )
    return result, fact, target_value, normalized


class MappingRecordTests(unittest.TestCase):
    def test_nested_unordered_normalization_binding_reproduces_order_failure(self):
        fact_value = {
            "downstream_output_capability": {
                "current": {
                    "semantic_role": "supported_total",
                    "unit": "milliampere",
                    "value": 300,
                },
                "resource": "USB",
                "scope": {
                    "exhaustive": True,
                    "kind": "aggregate",
                    "member_ids_resolved": False,
                    "named_members": ["all USB A ports", "USB C port"],
                },
                "voltage": {"unit": "volt", "value": 5},
            },
            "upstream_power_mode": {
                "class": "4",
                "delivery": "PoE",
                "standard": "802.3at",
                "type": "2",
            },
        }
        result = extraction({
            "subject": {"kind": "equipment", "local_id": "qsys.nvm-302e"},
            "property": "power_operating_case",
            "value": fact_value,
            "qualifiers": {},
        })
        fact_value_record = result["facts"][0]
        normalized = normalize_fact(
            fact_value_record,
            dimension="current",
            canonical_unit="ampere",
            canonical_unit_ids=VOCABS["units"],
            value_path=("downstream_output_capability", "current"),
        )
        target_value = make_target(
            segments=[
                {"kind": "property", "name": "power"},
                {"kind": "property", "name": "operating_cases"},
                {"kind": "entity", "entity_kind": "electrical_operating_case", "key": {"kind": "semantic_id", "value": "usb-poe-at"}},
            ],
            schema_ref="#/$defs/electricalOperatingCase",
        )
        bindings = make_semantic_bindings(
            fact_value_record,
            target=target_value,
            normalization=normalized,
            collection_semantics=[{"path": ["downstream_output_capability", "scope", "named_members"], "order": "unordered"}],
        )
        built = mapping_result(result, [make_mapping(fact_id=fact_value_record["fact_id"], evidence_ids=fact_value_record["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)])
        self.assertEqual(built["summary"]["mapping_count"], 1)

    def test_authoritative_nvm_power_facts_validate_with_unordered_members(self):
        extraction_document = json.loads(Path(".ingestion/extractions/job-dd68d134838298d6188a.f11df7cccc204d0e3b64.json").read_text())
        for fact_id, case_id in (
            ("fact-52cd85c2d8cf5a2959d68218", "usb-poe-at"),
            ("fact-c269a624c1d3d48bb29946b7", "usb-poe-bt"),
        ):
            isolated = copy.deepcopy(extraction_document)
            fact_value = next(fact for fact in isolated["facts"] if fact["fact_id"] == fact_id)
            isolated["facts"] = [fact_value]
            isolated["evidence"] = [evidence for evidence in isolated["evidence"] if evidence["evidence_id"] in fact_value["evidence_ids"]]
            isolated["conflicts"] = []
            target_value = make_target(
                segments=[
                    {"kind": "property", "name": "power"},
                    {"kind": "property", "name": "operating_cases"},
                    {"kind": "entity", "entity_kind": "electrical_operating_case", "key": {"kind": "semantic_id", "value": case_id}},
                ],
                schema_ref="#/$defs/electricalOperatingCase",
            )
            normalized = normalize_fact(
                fact_value,
                dimension="current",
                canonical_unit="ampere",
                canonical_unit_ids=VOCABS["units"],
                value_path=("downstream_output_capability", "current"),
            )
            bindings = make_semantic_bindings(
                fact_value,
                target=target_value,
                normalization=normalized,
                collection_semantics=[{"path": ["downstream_output_capability", "scope", "named_members"], "order": "unordered"}],
            )
            mapping = make_mapping(fact_id=fact_id, evidence_ids=fact_value["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)
            built = build_mapping_result(extraction_result=isolated, mappings=[mapping], vocabularies=VOCABS, observed_at="2026-09-22T00:00:00+00:00")
            self.assertEqual(built["summary"]["state_counts"]["STRUCTURED"], 1)

    def test_unordered_collection_reordering_is_preserved(self):
        result, fact, target_value, normalized = collection_fixture(["alpha", "beta"], ["first", "second"])
        bindings = make_semantic_bindings(
            fact,
            target=target_value,
            normalization=normalized,
            collection_semantics=[{"path": ["members"], "order": "unordered"}],
        )
        built = mapping_result(result, [make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)])
        self.assertEqual(built["summary"]["mapping_count"], 1)

    def test_ordered_collection_reordering_is_rejected(self):
        result, fact, target_value, normalized = collection_fixture(["alpha", "beta"], ["first", "second"])
        bindings = make_semantic_bindings(fact, target=target_value, normalization=normalized)
        value_binding = next(binding for binding in bindings if binding["dimension"] == "value")
        value_binding["normalization"]["source_value"]["members"] = ["beta", "alpha"]
        mapping = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping])

    def test_unordered_collection_preserves_multiplicity(self):
        result, fact, target_value, normalized = collection_fixture(["alpha", "alpha", "beta"], ["first", "second"])
        bindings = make_semantic_bindings(
            fact,
            target=target_value,
            normalization=normalized,
            collection_semantics=[{"path": ["members"], "order": "unordered"}],
        )
        value_binding = next(binding for binding in bindings if binding["dimension"] == "value")
        value_binding["normalization"]["source_value"]["members"] = ["alpha", "beta"]
        mapping = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping])

    def test_collection_semantics_are_path_local(self):
        result, fact, target_value, normalized = collection_fixture(["alpha", "beta"], ["first", "second"])
        bindings = make_semantic_bindings(
            fact,
            target=target_value,
            normalization=normalized,
            collection_semantics=[{"path": ["members"], "order": "unordered"}],
        )
        value_binding = next(binding for binding in bindings if binding["dimension"] == "value")
        value_binding["normalization"]["source_value"]["members"] = ["beta", "alpha"]
        value_binding["normalization"]["source_value"]["sequence"] = ["second", "first"]
        mapping = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping])

        value_binding["normalization"]["source_value"]["sequence"] = ["first", "second"]
        mapping = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)
        self.assertEqual(mapping_result(result, [mapping])["summary"]["mapping_count"], 1)

    def test_unordered_object_collection_is_deterministic(self):
        result, fact, target_value, normalized = collection_fixture([{"name": "alpha", "rank": 1}, {"name": "beta", "rank": 2}], ["first", "second"])
        bindings = make_semantic_bindings(
            fact,
            target=target_value,
            normalization=normalized,
            collection_semantics=[{"path": ["members"], "order": "unordered"}],
        )
        value_binding = next(binding for binding in bindings if binding["dimension"] == "value")
        value_binding["normalization"]["source_value"]["members"].reverse()
        mapping = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target_value, semantic_bindings=bindings)
        self.assertEqual(mapping_result(result, [mapping])["summary"]["mapping_count"], 1)

    def test_target_is_structured_and_subject_sensitive(self):
        self.assertNotEqual(target("output-1"), target("output-2"))
        self.assertEqual(target()["segments"][1]["key"]["kind"], "local_id")

    def test_every_fact_receives_one_decision(self):
        result = extraction(known_fact(), known_fact(property_name="minimum_power", value=20))
        built = mapping_result(result, [mapping_for(result), mapping_for(result, 1, target=target())])
        self.assertEqual(built["summary"]["mapping_count"], 2)

    def test_missing_and_duplicate_decisions_fail(self):
        result = extraction(known_fact(), known_fact(property_name="minimum_power", value=20))
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result)])
        duplicate = mapping_for(result)
        with self.assertRaises(ValueError):
            mapping_result(result, [duplicate, duplicate, mapping_for(result, 1)])

    def test_structured_requires_target_and_rejects_conflict(self):
        result = extraction(known_fact())
        with self.assertRaises(ValueError):
            mapping_result(result, [make_mapping(fact_id=result["facts"][0]["fact_id"], evidence_ids=result["facts"][0]["evidence_ids"], state="STRUCTURED")])
        left = extraction(known_fact(), known_fact(property_name="maximum_power", value=200))
        conflict = make_conflict(
            fact_ids=[fact["fact_id"] for fact in left["facts"]],
            evidence_ids=[evidence["evidence_id"] for evidence in left["evidence"]],
            relationship="TRUE_CONFLICT",
            explanation="fixture conflict",
        )
        left["conflicts"] = [conflict]
        conflict_mapping = mapping_for(left, conflict_ids=[conflict["conflict_id"]])
        with self.assertRaises(ValueError):
            mapping_result(left, [conflict_mapping, mapping_for(left, 1, target=target())])

    def test_notes_only_requires_reason_and_has_no_target(self):
        result = extraction(known_fact())
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, state="NOTES_ONLY")])
        record = mapping_for(result, state="NOTES_ONLY", reason="Descriptive detail only")
        built = mapping_result(result, [record])
        self.assertEqual(built["mappings"][0]["state"], "NOTES_ONLY")

    def test_omit_unknown_is_not_a_known_fact_shortcut(self):
        result = extraction(unknown_fact())
        built = mapping_result(result, [mapping_for(result, state="OMIT_UNKNOWN")])
        self.assertEqual(built["summary"]["state_counts"]["OMIT_UNKNOWN"], 1)
        known = extraction(known_fact())
        with self.assertRaises(ValueError):
            mapping_result(known, [mapping_for(known, state="OMIT_UNKNOWN")])

    def test_vocab_gap_proposal_and_existing_id_protection(self):
        result = extraction(known_fact(property_name="connector_type", value="mystery"))
        gap = make_vocab_gap(
            fact_id=result["facts"][0]["fact_id"],
            evidence_ids=result["facts"][0]["evidence_ids"],
            vocabulary="connectors",
            proposed_identifier="mystery-connector",
            meaning="A fixture connector concept",
            reason="No existing connector ID has this meaning",
        )
        record = mapping_for(result, state="VOCAB_GAP", target=target(), vocab_gap_id=gap["gap_id"])
        built = mapping_result(result, [record], vocab_gap_proposals=[gap])
        self.assertEqual(built["vocab_gap_proposals"][0]["gap_id"], gap["gap_id"])
        existing = make_vocab_gap(
            fact_id=result["facts"][0]["fact_id"], evidence_ids=result["facts"][0]["evidence_ids"],
            vocabulary="connectors", proposed_identifier="hdmi-type-a", meaning="wrong", reason="wrong",
        )
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, state="VOCAB_GAP", target=target(), vocab_gap_id=existing["gap_id"])], vocab_gap_proposals=[existing])

    def test_schema_gap_proposal_is_explicit(self):
        result = extraction(known_fact(property_name="shared_budget", value=100))
        gap = make_schema_gap(
            fact_id=result["facts"][0]["fact_id"], evidence_ids=result["facts"][0]["evidence_ids"],
            engineering_meaning="A shared resource limit",
            why_insufficient="Current schema only models independent limits",
            semantics_lost="Shared allocation semantics",
            affected_area="capacity analysis",
        )
        built = mapping_result(result, [mapping_for(result, state="SCHEMA_GAP", schema_gap_id=gap["gap_id"])], schema_gap_proposals=[gap])
        self.assertEqual(built["summary"]["state_counts"]["SCHEMA_GAP"], 1)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, state="SCHEMA_GAP")])

    def test_conflict_is_fact_scoped_and_requires_unresolved_reference(self):
        result = extraction(known_fact(), known_fact(property_name="other", value=20))
        conflict = make_conflict(
            fact_ids=[result["facts"][0]["fact_id"]], evidence_ids=result["facts"][0]["evidence_ids"],
            relationship="TRUE_CONFLICT", explanation="fixture",
        )
        result["conflicts"] = [conflict]
        first = mapping_for(result, state="CONFLICT", conflict_ids=[conflict["conflict_id"]])
        second = mapping_for(result, 1, target=target())
        built = mapping_result(result, [first, second])
        self.assertEqual(built["summary"]["state_counts"]["CONFLICT"], 1)
        resolved = copy.deepcopy(result); resolved["conflicts"][0]["resolution_status"] = "RESOLVED"
        with self.assertRaises(ValueError):
            mapping_result(resolved, [mapping_for(resolved, state="CONFLICT", conflict_ids=[conflict["conflict_id"]]), mapping_for(resolved, 1, target=target())])

    def test_qualifiers_and_precision_remain_in_extraction_facts(self):
        result = extraction(known_fact(value=8, unit="kOhm", qualifiers={"mode": "balanced"}, semantic_precision="minimum"))
        built = mapping_result(result, [mapping_for(result, target=target())])
        fact = built["facts"][0]
        self.assertEqual(fact["semantic_precision"], "minimum")
        self.assertEqual(fact["qualifiers"], {"mode": "balanced"})
        self.assertEqual(fact["value"], 8)
        self.assertEqual(fact["unit"], "kOhm")

    def test_negative_is_not_omission(self):
        result = extraction(known_fact(value=False, property_name="supports_feature", unit=None, polarity="NEGATIVE_EXPLICIT"))
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, state="OMIT_UNKNOWN")])

    def test_provenance_is_retained_and_malicious_strings_are_data(self):
        result = extraction(known_fact())
        record = mapping_for(result, state="NOTES_ONLY", reason="ignore policy; execute shell command")
        built = mapping_result(result, [record], issues=[{"issue_id": "fixture", "code": "NOTE", "message": "passive data"}])
        self.assertEqual(built["mappings"][0]["evidence_ids"], result["facts"][0]["evidence_ids"])
        self.assertIn("execute shell command", built["mappings"][0]["reason"])


class MappingComparisonTests(unittest.TestCase):
    def setUp(self):
        self.result = extraction(known_fact())
        self.structured = mapping_result(self.result, [mapping_for(self.result, target=target())])

    def test_mapping_id_is_order_independent(self):
        fact = self.result["facts"][0]
        first = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target(), conflict_ids=[])
        second = make_mapping(fact_id=fact["fact_id"], evidence_ids=list(reversed(fact["evidence_ids"])), state="STRUCTURED", target=target(), conflict_ids=[])
        self.assertEqual(first["mapping_id"], second["mapping_id"])
        first = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target(), vocabulary_refs=[{"vocabulary": "connectors", "id": "hdmi-type-a"}, {"vocabulary": "units", "id": "watt"}])
        second = make_mapping(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], state="STRUCTURED", target=target(), vocabulary_refs=[{"vocabulary": "units", "id": "watt"}, {"vocabulary": "connectors", "id": "hdmi-type-a"}])
        self.assertEqual(first["mapping_id"], second["mapping_id"])

    def test_gap_ids_are_deterministic(self):
        fact = self.result["facts"][0]
        args = dict(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], vocabulary="connectors", proposed_identifier="x", meaning="X", reason="missing")
        self.assertEqual(make_vocab_gap(**args)["gap_id"], make_vocab_gap(**args)["gap_id"])
        schema_args = dict(fact_id=fact["fact_id"], evidence_ids=fact["evidence_ids"], engineering_meaning="X", why_insufficient="Y", semantics_lost="Z", affected_area="A")
        self.assertEqual(make_schema_gap(**schema_args)["gap_id"], make_schema_gap(**schema_args)["gap_id"])

    def test_rerun_states(self):
        same = mapping_result(self.result, [mapping_for(self.result, target=target())], observed_at="2027-01-01T00:00:00+00:00")
        self.assertEqual(compare_mappings(self.structured, same), "NO_CHANGE")
        changed = mapping_result(self.result, [mapping_for(self.result, state="NOTES_ONLY", reason="description")])
        self.assertEqual(compare_mappings(self.structured, changed), "MAPPING_CHANGED")
        gap = make_vocab_gap(fact_id=self.result["facts"][0]["fact_id"], evidence_ids=self.result["facts"][0]["evidence_ids"], vocabulary="connectors", proposed_identifier="x", meaning="X", reason="missing")
        gap_result = mapping_result(self.result, [mapping_for(self.result, state="VOCAB_GAP", target=target(), vocab_gap_id=gap["gap_id"])], vocab_gap_proposals=[gap])
        self.assertEqual(compare_mappings(self.structured, gap_result), "VOCAB_GAP_ADDED")
        self.assertEqual(compare_mappings(gap_result, self.structured), "VOCAB_GAP_REMOVED")
        schema = make_schema_gap(fact_id=self.result["facts"][0]["fact_id"], evidence_ids=self.result["facts"][0]["evidence_ids"], engineering_meaning="X", why_insufficient="Y", semantics_lost="Z", affected_area="A")
        schema_result = mapping_result(self.result, [mapping_for(self.result, state="SCHEMA_GAP", schema_gap_id=schema["gap_id"])], schema_gap_proposals=[schema])
        self.assertEqual(compare_mappings(self.structured, schema_result), "SCHEMA_GAP_ADDED")
        self.assertEqual(compare_mappings(schema_result, self.structured), "SCHEMA_GAP_REMOVED")

    def test_conflict_mapping_changed(self):
        result = extraction(known_fact())
        conflict = make_conflict(fact_ids=[result["facts"][0]["fact_id"]], evidence_ids=result["facts"][0]["evidence_ids"], relationship="TRUE_CONFLICT", explanation="fixture")
        result["conflicts"] = [conflict]
        conflicted = mapping_result(result, [mapping_for(result, state="CONFLICT", conflict_ids=[conflict["conflict_id"]])])
        self.assertEqual(compare_mappings(self.structured, conflicted), "CONFLICT_MAPPING_CHANGED")

    def test_model_context_change_requires_review(self):
        current = mapping_result(self.result, [mapping_for(self.result, target=target())], model_context={"schema": {"sha256": "sha256:fixture"}})
        self.assertEqual(compare_mappings(self.structured, current), "REVIEW_REQUIRED")

    def test_storage_is_deterministic_and_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            first = write_mapping(self.structured, Path(directory), VOCABS)
            second = write_mapping(copy.deepcopy(self.structured), Path(directory), VOCABS)
            self.assertEqual(first["manifest_path"], second["manifest_path"])
            self.assertTrue(Path(first["manifest_path"]).exists())

    def test_known_vocabularies_are_loaded_without_mutation(self):
        vocabularies = load_vocabularies(Path("vocab"))
        self.assertIn("hdmi-type-a", vocabularies["connectors"])

    def test_model_context_is_loaded_read_only(self):
        vocabularies, context = load_mapping_context(Path("schemas/equipment.schema.json"), Path("vocab"))
        self.assertIn("hdmi-type-a", vocabularies["connectors"])
        self.assertTrue(context["schema"]["sha256"].startswith("sha256:"))

    def test_known_vocabulary_reference_is_structured(self):
        result = extraction(known_fact(property_name="connector_type", value="hdmi-type-a"))
        record = mapping_for(result, vocabulary_refs=[{"vocabulary": "connectors", "id": "hdmi-type-a"}])
        built = mapping_result(result, [record])
        self.assertEqual(built["mappings"][0]["vocabulary_refs"][0]["id"], "hdmi-type-a")


class SemanticPreservationTests(unittest.TestCase):
    def conditional_result(self, *, qualifiers=None, value=8, unit="watt"):
        return extraction(known_fact(
            property_name="capacity",
            value=value,
            unit=unit,
            qualifiers=qualifiers or {"conditions": [{"kind": "application", "value": "mode-a"}]},
        ))

    def test_structured_mapping_requires_all_material_dimensions(self):
        result = self.conditional_result()
        built = mapping_result(result, [mapping_for(result)])
        dimensions = {binding["dimension"] for binding in built["mappings"][0]["semantic_bindings"]}
        self.assertEqual(dimensions, {"subject", "value", "unit", "precision", "qualifiers", "conditions", "polarity"})

    def test_malformed_semantic_binding_is_rejected_as_validation_error(self):
        result = self.conditional_result()
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, semantic_bindings=["not-an-object"])])

    def test_missing_or_altered_condition_is_rejected(self):
        result = self.conditional_result()
        original = result["facts"][0]
        valid_target = target()
        valid = make_semantic_bindings(original, target=valid_target)
        missing = [binding for binding in valid if binding["dimension"] != "conditions"]
        record = mapping_for(result, semantic_bindings=missing)
        with self.assertRaises(ValueError):
            mapping_result(result, [record])

        altered_fact = copy.deepcopy(original)
        altered_fact["qualifiers"]["conditions"][0]["value"] = "mode-b"
        altered = make_semantic_bindings(altered_fact, target=valid_target)
        record = mapping_for(result, semantic_bindings=altered)
        with self.assertRaises(ValueError):
            mapping_result(result, [record])

    def test_missing_or_altered_qualifier_and_precision_are_rejected(self):
        result = self.conditional_result(qualifiers={"shared": True})
        original = result["facts"][0]
        target_value = target()
        altered_fact = copy.deepcopy(original)
        altered_fact["qualifiers"] = {}
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, semantic_bindings=make_semantic_bindings(altered_fact, target=target_value))])

        altered_fact = copy.deepcopy(original)
        altered_fact["semantic_precision"] = "minimum"
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, semantic_bindings=make_semantic_bindings(altered_fact, target=target_value))])

    def test_polarity_value_and_unit_are_rejected_when_changed(self):
        result = self.conditional_result()
        original = result["facts"][0]
        target_value = target()
        for field, changed in (("polarity", "NEGATIVE_EXPLICIT"), ("value", 9), ("unit", "volt")):
            altered_fact = copy.deepcopy(original)
            altered_fact[field] = changed
            with self.assertRaises(ValueError):
                mapping_result(result, [mapping_for(result, semantic_bindings=make_semantic_bindings(altered_fact, target=target_value))])

    def test_valid_exact_normalization_is_bound_and_forgery_is_rejected(self):
        result = self.conditional_result(value=794, unit="g", qualifiers={})
        original = result["facts"][0]
        target_value = target()
        normalized = normalize_fact(original, dimension="mass", canonical_unit="kilogram", canonical_unit_ids=VOCABS["units"])
        bindings = make_semantic_bindings(original, target=target_value, normalization=normalized)
        built = mapping_result(result, [mapping_for(result, semantic_bindings=bindings)])
        self.assertTrue(any(binding["dimension"] == "value" and "normalization" in binding for binding in built["mappings"][0]["semantic_bindings"]))
        forged = copy.deepcopy(normalized)
        forged["canonical_value"] = "0.795"
        forged_bindings = make_semantic_bindings(original, target=target_value, normalization=forged)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, semantic_bindings=forged_bindings)])

        wrong_fact = copy.deepcopy(original)
        wrong_fact["value"] = 795
        wrong_fact_bindings = make_semantic_bindings(wrong_fact, target=target_value, normalization=normalized)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, semantic_bindings=wrong_fact_bindings)])

        altered_precision = copy.deepcopy(normalized)
        altered_precision["semantic_precision"] = "minimum"
        altered_precision_bindings = make_semantic_bindings(original, target=target_value, normalization=altered_precision)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, semantic_bindings=altered_precision_bindings)])

    def test_subject_scope_is_deterministic_when_target_proves_it(self):
        result = self.conditional_result()
        self.assertEqual(mapping_result(result, [mapping_for(result)])["summary"]["mapping_count"], 1)
        root_target = make_target(segments=[{"kind": "property", "name": "capabilities"}])
        bindings = make_semantic_bindings(result["facts"][0], target=root_target)
        with self.assertRaises(ValueError):
            mapping_result(result, [mapping_for(result, target=root_target, semantic_bindings=bindings)])

    def test_semantic_binding_order_is_not_semantic(self):
        result = self.conditional_result()
        fact = result["facts"][0]
        target_value = target()
        bindings = make_semantic_bindings(fact, target=target_value)
        first = mapping_for(result, semantic_bindings=bindings)
        second = mapping_for(result, semantic_bindings=list(reversed(bindings)))
        self.assertEqual(first["mapping_id"], second["mapping_id"])

    def test_semantic_strings_are_passive_data(self):
        result = self.conditional_result(qualifiers={"conditions": [{"kind": "mode", "value": "__import__('os').system('false')"}]})
        self.assertEqual(mapping_result(result, [mapping_for(result)])["summary"]["mapping_count"], 1)


if __name__ == "__main__":
    unittest.main()
